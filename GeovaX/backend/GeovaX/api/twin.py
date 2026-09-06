"""Land Digital Twin, Explainable AI Evidence, and Temporal Land Intelligence.

Three read-only views assembled entirely from what the harmonisation pipeline already
computed and published for a run (``FeatureStore``/``PostgisStore`` collections, the
provenance ledger, the confidence components baked into every parcel/building record, and
the adjudication queue's Dempster-Shafer fusion output). Nothing here re-runs matching,
re-derives confidence from raw geometry, or invents a number the pipeline did not itself
produce.

Two real, disclosed scope limits shape what these views can show (see ``db/store.py``'s own
module docstring): ``source_feature`` / ``source_claim`` / ``match_pair`` rows are not
persisted by any pipeline stage today, so per-claim provenance is only available at the
*dataset* level (``contributing_datasets`` plus the run's provenance catalogue, not a
feature-by-feature audit trail); and there is no persisted key linking an escalated
adjudication case's cluster id back to the (possibly still-provisional) harmonised record it
concerns, because clustering happens before ULPIN minting. Where that link is useful, it is
*derived* here — a nearest-centroid geometry match against the adjudication queue's own
published boundaries, which are real and in the same CRS as every harmonised feature — and
the response always labels it as a derived match with the real distance, never as an
authoritative foreign key that does not exist.
"""

from __future__ import annotations

from typing import Any

from shapely.geometry import shape as _shapely_shape

from ..attributes.canonical import BUILDING_SCHEMA, PARCEL_SCHEMA, redact_pii
from ..core.models import Authority, ConfidenceReport, SourceDataset, SourceType
from ..core.registry import AUTHORITIES, SourceRegistry
from ..crs.engine import haversine_m
from ..pipeline.harmonise import _parse_vintage

CONFIDENCE_DIMENSION_MEANING: dict[str, str] = {
    "positional": (
        "How closely the record's geometry is expected to match ground truth, derived from "
        "the declared or empirically measured accuracy of its best contributing source "
        "against the platform's target accuracy, adjusted for any measured ground-control "
        "residual."
    ),
    "source_agreement": (
        "How many independent sources corroborate this record, how deep their resolution is, "
        "and whether that agreement survived without an unresolved conflict."
    ),
    "topological": (
        "Whether the geometry is valid and free of self-overlap, gaps against neighbours, or "
        "a large repair shift, after automated topology correction."
    ),
    "attribute_completeness": (
        "The importance-weighted fraction of canonical schema fields that carry a real, "
        "non-redacted value on this record."
    ),
    "temporal_currency": (
        "How recently the freshest contributing source was acquired, decayed by that source "
        "type's typical rate of going stale."
    ),
    "lineage_integrity": (
        "Whether the provenance ledger chain for this run verifies intact, and how much of "
        "this record's claims and resolutions carry an attributed rationale."
    ),
}

CATEGORY_BY_SOURCE_TYPE: dict[str, str] = {
    SourceType.CADASTRAL_MAP.value: "cadastral",
    SourceType.REVENUE_RECORD.value: "revenue",
    SourceType.MUNICIPAL_GIS.value: "municipal_gis",
    SourceType.UTILITY_NETWORK.value: "utility",
    SourceType.GROUND_TRUTH.value: "ground_truth",
    SourceType.GNSS_CORS.value: "gnss",
    SourceType.DRONE_IMAGERY.value: "drone_imagery",
    SourceType.ORI.value: "orthorectified_imagery",
    SourceType.DSM.value: "elevation",
    SourceType.DTM.value: "elevation",
    SourceType.POINT_CLOUD.value: "elevation",
    SourceType.AI_EXTRACTION.value: "ai_extraction",
    SourceType.BUILDING_FOOTPRINT.value: "building_footprint",
    SourceType.ADMIN_BOUNDARY.value: "administrative",
    SourceType.TRANSPORT_NETWORK.value: "transport",
    SourceType.HYDROLOGY.value: "hydrology",
}

# Buildings this fixture's harmonisation covers run a few tens of metres across, and the
# statutory rule that escalates a geometric conflict (R-GEO-01) triggers past 10 m of
# disagreement — so a real, escalated case's boundary can legitimately sit this far from a
# record's own resolved centroid. Wider than that and a "nearest" match is more likely a
# different, unrelated feature than the one actually in dispute.
MATCH_DISTANCE_THRESHOLD_M = 30.0

CONFIDENCE_DIMENSIONS = (
    "positional", "source_agreement", "topological",
    "attribute_completeness", "temporal_currency", "lineage_integrity",
)


# --------------------------------------------------------------------------------------
# small shared helpers
# --------------------------------------------------------------------------------------


def split_datasets(value: Any) -> list[str]:
    """``contributing_datasets`` is comma-joined in the GeoJSON file store and may already
    be a list from a Postgres ``text[]`` column — accept either without assuming one."""
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [d for d in str(value or "").split(",") if d]


def find_by_ulpin(features: list[dict[str, Any]], ulpin: str) -> dict[str, Any] | None:
    for f in features:
        if f.get("properties", {}).get("ulpin") == ulpin:
            return f
    return None


def find_by_identifier(features: list[dict[str, Any]], ident: str) -> dict[str, Any] | None:
    for f in features:
        p = f.get("properties", {})
        if p.get("ulpin") == ident or p.get("entity_id") == ident:
            return f
    return None


def find_buildings_for_parcel(buildings: list[dict[str, Any]], ulpin: str) -> list[dict[str, Any]]:
    return [b for b in buildings if b.get("properties", {}).get("parcel_ulpin") == ulpin]


def _centroid(geometry: dict[str, Any] | None) -> tuple[float, float] | None:
    if not geometry:
        return None
    try:
        c = _shapely_shape(geometry).centroid
        return (c.x, c.y)
    except Exception:
        return None


def category_for(source_type: str | None) -> str:
    return CATEGORY_BY_SOURCE_TYPE.get(source_type or "", "other")


# --------------------------------------------------------------------------------------
# provenance / reliability
# --------------------------------------------------------------------------------------


def index_provenance(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {e["dataset_id"]: e for e in entries if e.get("dataset_id")}


def build_source_registry(entries: list[dict[str, Any]]) -> SourceRegistry:
    """A real ``SourceRegistry`` populated from this run's actual provenance catalogue.

    Rebuilt here from the same catalogue ``/api/provenance`` serves (rather than requiring
    the pipeline process's own in-memory registry to still be alive) so the reliability,
    recency and accuracy weights below come from the exact formulas production fusion uses
    (``core/registry.py``), applied to this run's real declared accuracies and vintages —
    not a second, independently-tuned implementation that could drift from it.
    """
    registry = SourceRegistry()
    for entry in entries:
        dataset_id = entry.get("dataset_id")
        if not dataset_id:
            continue
        try:
            source_type = SourceType(entry.get("source_type"))
        except ValueError:
            continue
        authority = AUTHORITIES.get(entry.get("authority") or "")
        if authority is None:
            authority = Authority(
                entry.get("authority") or "UNKNOWN",
                entry.get("authority_full_name") or entry.get("authority") or "unknown authority",
                "institutional",
            )
        registry.register(SourceDataset(
            dataset_id=dataset_id,
            title=dataset_id,
            source_type=source_type,
            authority=authority,
            licence=entry.get("licence") or "",
            crs=entry.get("crs") or "EPSG:4326",
            acquired_on=_parse_vintage(entry.get("vintage") or ""),
            positional_accuracy_m=entry.get("accuracy_m"),
            tier=entry.get("tier") or "official",
            platform=entry.get("platform") or "",
            transformation=entry.get("transformation") or "",
        ))
    return registry


def source_reliability_breakdown(
    dataset_ids: list[str],
    entries_by_id: dict[str, dict[str, Any]],
    registry: SourceRegistry,
) -> list[dict[str, Any]]:
    out = []
    for dsid in dataset_ids:
        entry = entries_by_id.get(dsid, {})
        out.append({
            "dataset_id": dsid,
            "source_type": entry.get("source_type"),
            "authority": entry.get("authority"),
            "declared_accuracy_m": entry.get("accuracy_m"),
            "vintage": entry.get("vintage"),
            "reliability_prior": round(registry.reliability(dsid, "geometry"), 4),
            "recency_weight": round(registry.recency_weight(dsid), 4),
            "accuracy_weight": round(registry.accuracy_weight(dsid), 4),
        })
    return out


# --------------------------------------------------------------------------------------
# cross-linking: change detection and the adjudication queue
# --------------------------------------------------------------------------------------


def link_changes(record: dict[str, Any], changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Real ``ChangeRecord`` entries whose ``entity_id`` matches a raw identifier still
    carried on this harmonised record (e.g. a source door number preserved as a passthrough
    attribute). Change detection runs source-to-source before ULPIN minting, so there is no
    persisted ``change_record`` -> harmonised-entity key; this recovers the link only where
    an exact identifier match exists, and returns nothing rather than guessing.
    """
    props = record.get("properties", {})
    candidate_ids = {str(v) for v in props.values() if isinstance(v, (str, int)) and str(v)}
    candidate_ids.discard("")
    return [c for c in changes if str(c.get("entity_id")) in candidate_ids]


def link_adjudication_case(
    record: dict[str, Any],
    adjudication_features: list[dict[str, Any]],
    queue_briefs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Best-effort link from a harmonised record to an escalated conflict case.

    ``adjudication_queue.json``'s ``entity_id`` is a pre-ULPIN matching-stage cluster id
    with no persisted key back to the harmonised parcel/building it concerns. What *is*
    published is the case's own disputed boundary (``adjudication_queue.geojson``), in the
    same CRS as every harmonised feature. This finds the nearest such boundary by real
    centroid distance and returns a match only inside a disclosed threshold
    (``MATCH_DISTANCE_THRESHOLD_M``) — a derived spatial join, not an identity lookup, and
    always labelled as such in the result.
    """
    target = _centroid(record.get("geometry"))
    if target is None:
        return None
    best_feat, best_dist = None, None
    for feat in adjudication_features:
        c = _centroid(feat.get("geometry"))
        if c is None:
            continue
        d = haversine_m(target[0], target[1], c[0], c[1])
        if best_dist is None or d < best_dist:
            best_dist, best_feat = d, feat
    if best_feat is None or best_dist is None or best_dist > MATCH_DISTANCE_THRESHOLD_M:
        return None
    case_id = best_feat.get("properties", {}).get("case_id")
    brief = next((b for b in queue_briefs if b.get("case_id") == case_id), None)
    if brief is None:
        return None
    return {
        **brief,
        "matched_by": (
            f"nearest-geometry centroid match, distance={best_dist:.2f} m "
            "(derived — this pipeline run persists no direct case-to-entity key)"
        ),
    }


# --------------------------------------------------------------------------------------
# 1. Land Digital Twin
# --------------------------------------------------------------------------------------


def digital_twin(store: Any, ulpin: str, provenance_entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    parcels = store.collections.get("parcels", [])
    buildings = store.collections.get("buildings", [])
    parcel = find_by_ulpin(parcels, ulpin)
    if parcel is None:
        return None

    props = parcel.get("properties", {})
    linked_buildings = find_buildings_for_parcel(buildings, ulpin)
    entries_by_id = index_provenance(provenance_entries)

    dataset_roles: dict[str, set[str]] = {}
    for d in split_datasets(props.get("contributing_datasets")):
        dataset_roles.setdefault(d, set()).add("parcel boundary/attributes")
    for b in linked_buildings:
        bprops = b.get("properties", {})
        label = f"building {bprops.get('entity_id')}"
        for d in split_datasets(bprops.get("contributing_datasets")):
            dataset_roles.setdefault(d, set()).add(label)

    linked_datasets = []
    for dsid, roles in dataset_roles.items():
        entry = entries_by_id.get(dsid)
        if entry is None:
            linked_datasets.append({
                "dataset_id": dsid,
                "category": "other",
                "roles": sorted(roles),
                "note": (
                    "dataset id recorded on the harmonised record but not present in this "
                    "run's provenance catalogue (pipeline.presets.default_layers)"
                ),
            })
            continue
        linked_datasets.append({
            "dataset_id": dsid,
            "category": category_for(entry.get("source_type")),
            "source_type": entry.get("source_type"),
            "authority": entry.get("authority"),
            "authority_full_name": entry.get("authority_full_name"),
            "licence": entry.get("licence"),
            "crs": entry.get("crs"),
            "accuracy_m": entry.get("accuracy_m"),
            "vintage": entry.get("vintage"),
            "tier": entry.get("tier"),
            "platform": entry.get("platform"),
            "transformation": entry.get("transformation"),
            "coverage": entry.get("coverage"),
            "roles": sorted(roles),
        })
    linked_datasets.sort(key=lambda x: x["dataset_id"])

    utility_links = []
    pc = _centroid(parcel.get("geometry"))
    if pc is not None:
        for u in store.collections.get("utilities", []):
            uc = _centroid(u.get("geometry"))
            if uc is None:
                continue
            d = haversine_m(pc[0], pc[1], uc[0], uc[1])
            if d <= 75.0:
                uprops = u.get("properties", {})
                utility_links.append({
                    "feature": uprops.get("name") or uprops.get("id") or uprops.get("asset_id") or "unnamed segment",
                    "distance_m": round(d, 1),
                })
    utility_links.sort(key=lambda x: x["distance_m"])

    return {
        "identity": {
            "ulpin": props.get("ulpin"),
            "entity_id": props.get("entity_id"),
            "confidence": props.get("confidence"),
            "confidence_grade": props.get("confidence_grade"),
            "note": (
                "ULPIN is a 14-character, checksum-validated identifier minted from a "
                "geohash-snapped parcel centroid (core/ids.py::mint_ulpin); it is stable "
                "under re-survey because it depends on location, not on the exact boundary "
                "vertices, and a single substituted character is provably caught by the "
                "trailing checksum digit."
            ),
        },
        "parcel": {**parcel, "properties": redact_pii(props, PARCEL_SCHEMA)},
        "buildings": {
            "count": len(linked_buildings),
            "features": [
                {**b, "properties": redact_pii(b.get("properties", {}), BUILDING_SCHEMA)}
                for b in linked_buildings[:200]
            ],
            "truncated": len(linked_buildings) > 200,
        },
        "linked_datasets": linked_datasets,
        "utility_links": utility_links[:10],
        "provenance_scope_note": (
            "Linkage above is at the dataset level: contributing_datasets recorded on this "
            "parcel and its linked buildings, cross-referenced against this run's real "
            "provenance catalogue (authority, licence, CRS, accuracy, transformation). "
            "Per-source-feature claim records (source_feature / source_claim in schema.sql) "
            "are not persisted by this pipeline run, so a feature-by-feature audit trail "
            "below the dataset level is not available here."
        ),
    }


# --------------------------------------------------------------------------------------
# 2. Explainable AI Evidence
# --------------------------------------------------------------------------------------


def _confidence_report_from_properties(props: dict[str, Any]) -> ConfidenceReport | None:
    values: dict[str, float] = {}
    for dim in CONFIDENCE_DIMENSIONS:
        v = props.get(f"conf_{dim}")
        if v is None:
            return None
        try:
            values[dim] = float(v)
        except (TypeError, ValueError):
            return None
    return ConfidenceReport(entity_id=str(props.get("entity_id", "")), **values)


def evidence_object(store: Any, identifier: str, provenance_entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    parcels = store.collections.get("parcels", [])
    buildings = store.collections.get("buildings", [])

    feature_class = "parcel"
    record = find_by_identifier(parcels, identifier)
    if record is None:
        record = find_by_identifier(buildings, identifier)
        feature_class = "building"
    if record is None:
        return None

    props = record.get("properties", {})
    entries_by_id = index_provenance(provenance_entries)
    registry = build_source_registry(provenance_entries)
    contributing = split_datasets(props.get("contributing_datasets"))

    confidence_block = None
    report = _confidence_report_from_properties(props)
    if report is not None:
        stored_composite = props.get("confidence")
        matches_stored = True
        if stored_composite is not None:
            try:
                matches_stored = abs(report.composite - float(stored_composite)) < 0.001
            except (TypeError, ValueError):
                matches_stored = True
        confidence_block = {
            "composite": round(report.composite, 4),
            "stored_composite": stored_composite,
            "composite_matches_stored_record": matches_stored,
            "grade": report.grade,
            "weakest_dimension": report.weakest()[0],
            "explanation": report.explain(),
            "weights": dict(report.DEFAULT_WEIGHTS),
            "dimensions": [
                {
                    "name": name,
                    "score": round(value, 4),
                    "weight": report.DEFAULT_WEIGHTS.get(name, 0.0),
                    "contribution_to_composite": round(value * report.DEFAULT_WEIGHTS.get(name, 0.0), 4),
                    "meaning": CONFIDENCE_DIMENSION_MEANING[name],
                }
                for name, value in report.components().items()
            ],
        }

    linked_changes = link_changes(record, store.changes())
    linked_case = link_adjudication_case(
        record, store.collections.get("adjudication", []), store.queue(),
    )

    conflict_count = props.get("conflicts")
    conflicting_sources: dict[str, Any] = {"conflict_count_on_record": conflict_count}
    if linked_case is not None:
        conflicting_sources["linked_case"] = linked_case
    elif conflict_count:
        conflicting_sources["note"] = (
            f"This record's properties record {conflict_count} conflict(s) resolved during "
            "harmonisation, but no adjudication-queue case could be geometrically linked to "
            "it within the disclosed match threshold — it was most likely auto-resolved by "
            "statutory rule or evidence fusion rather than escalated to human review."
        )
    else:
        corroborating = ", ".join(contributing) or "a single source"
        conflicting_sources["note"] = f"No conflicts were recorded for this entity. Contributing source(s): {corroborating}."

    return {
        "subject": {
            "ulpin": props.get("ulpin"),
            "entity_id": props.get("entity_id"),
            "feature_class": feature_class,
        },
        "confidence": confidence_block,
        "source_reliability": source_reliability_breakdown(contributing, entries_by_id, registry),
        "conflicting_sources": conflicting_sources,
        "change_evidence": [
            {
                "change_type": c.get("change_type"),
                "confidence": c.get("confidence"),
                "centroid_shift_m": c.get("centroid_shift_m"),
                "residual_shift_m": c.get("residual_shift_m"),
                "area_delta_pct": c.get("area_delta_pct"),
                "height_delta_m": c.get("height_delta_m"),
                "registry_action": c.get("registry_action"),
                "evidence": c.get("evidence"),
                "is_actionable": c.get("is_actionable"),
            }
            for c in linked_changes
        ],
        "change_evidence_note": (
            None if linked_changes else
            "No change-detection record in this run's changes.json shares a raw source "
            "identifier with this entity."
        ),
    }


# --------------------------------------------------------------------------------------
# 3. Temporal Land Intelligence
# --------------------------------------------------------------------------------------


def parcel_timeline(store: Any, ulpin: str, provenance_entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    parcels = store.collections.get("parcels", [])
    buildings = store.collections.get("buildings", [])
    parcel = find_by_ulpin(parcels, ulpin)
    if parcel is None:
        return None

    props = parcel.get("properties", {})
    linked_buildings = find_buildings_for_parcel(buildings, ulpin)
    entries_by_id = index_provenance(provenance_entries)

    dataset_ids: set[str] = set(split_datasets(props.get("contributing_datasets")))
    for b in linked_buildings:
        dataset_ids.update(split_datasets(b.get("properties", {}).get("contributing_datasets")))

    events: list[dict[str, Any]] = []

    for dsid in sorted(dataset_ids):
        entry = entries_by_id.get(dsid)
        if not entry:
            continue
        dt = _parse_vintage(entry.get("vintage") or "")
        if dt is None:
            continue
        accuracy = entry.get("accuracy_m")
        description = (
            f"{dsid} ({entry.get('source_type')}) observed the ground at "
            f"±{accuracy} m accuracy (vintage {entry.get('vintage')})."
            if accuracy is not None else
            f"{dsid} ({entry.get('source_type')}) observed the ground (vintage {entry.get('vintage')})."
        )
        events.append({
            "date": dt.isoformat(),
            "kind": "source_observation",
            "dataset_id": dsid,
            "source_type": entry.get("source_type"),
            "description": description,
        })

    changes = store.changes()
    linked_changes = link_changes(parcel, changes)
    for b in linked_buildings:
        linked_changes = linked_changes + link_changes(b, changes)
    for c in linked_changes:
        events.append({
            "date": None,
            "kind": "change_detected",
            "change_type": c.get("change_type"),
            "description": c.get("registry_action"),
            "evidence": c.get("evidence"),
            "magnitude": {
                "area_delta_pct": c.get("area_delta_pct"),
                "centroid_shift_m": c.get("centroid_shift_m"),
                "height_delta_m": c.get("height_delta_m"),
            },
        })

    for dsid in dataset_ids:
        for entry_ in store.ledger.history(dsid):
            events.append({
                "date": entry_.timestamp,
                "kind": "pipeline_stage",
                "operation": entry_.operation,
                "dataset_id": entry_.entity_id,
                "description": f"Harmonisation pipeline stage '{entry_.operation}' processed {entry_.entity_id}.",
            })

    if not events:
        return {
            "ulpin": ulpin,
            "entity_id": props.get("entity_id"),
            "available": False,
            "reason": (
                "No dataset vintage, provenance-ledger entry, or linkable change record was "
                "found for this parcel or its linked buildings in this pipeline run's "
                "published outputs. This platform does not fabricate a survey history where "
                "none was captured."
            ),
            "events": [],
        }

    dated = sorted((e for e in events if e.get("date")), key=lambda e: e["date"])
    undated = [e for e in events if not e.get("date")]

    return {
        "ulpin": ulpin,
        "entity_id": props.get("entity_id"),
        "available": True,
        "events": dated + undated,
        "note": (
            "Dated events come from real dataset vintages and provenance-ledger stage "
            "timestamps for the datasets that contributed to this record. Change-detection "
            "events are linked by a shared raw source identifier and carry no independent "
            "timestamp of their own in this run's output, so they are listed without a date "
            "rather than an invented one. This pipeline does not persist bitemporal "
            "(valid_from/valid_to) per-parcel versioning, so this is not a continuous survey "
            "history — it is the harmonisation provenance trail behind the record's current "
            "state."
        ),
    }
