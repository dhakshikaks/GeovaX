"""Deterministic Parcel Risk Score and AI Survey Priority Queue.

Both views are pure functions over fields the harmonisation pipeline already computed and
persisted on every parcel/building record — the same ``conf_*`` confidence components,
``conflicts`` count and corroboration signals (``n_sources``, ``cluster_support``) already
rendered in the existing "Parcel Harmonization Evidence" card and consumed by
``api/twin.py``. Nothing here re-runs any pipeline stage, re-derives a confidence dimension
from geometry, or invents a score: every factor is read directly from a real, persisted
field, and the weights are declared and documented — checkable by hand, the same way
``ConfidenceReport``'s weights are (``core/models.py``).

Risk is deliberately not "1 - confidence": confidence is a report card on how much to trust
what the pipeline already decided, whereas risk also weighs signals confidence intentionally
keeps separate — how many conflicts a record actually carries, whether it rests on a single
uncorroborated source, and whether an unresolved disagreement involves a ground-truth/GNSS
source (the platform's highest positional reliability tier, ``core/registry.py`` ``PRIORS``).
"""
from __future__ import annotations

from typing import Any

from . import twin as _twin

# --------------------------------------------------------------------------------------
# scoring model
# --------------------------------------------------------------------------------------

# Each factor is a real 0..1 "how bad is this" measure, derived from a field the pipeline
# already persisted. Weights sum to 1.0 so the composite lands directly in 0..100.
RISK_WEIGHTS: dict[str, float] = {
    "positional": 0.20,
    "source_agreement": 0.20,
    "topological": 0.15,
    "conflict_density": 0.12,
    "attribute_completeness": 0.10,
    "uncorroborated": 0.08,
    "temporal_currency": 0.08,
    "lineage_integrity": 0.07,
}
assert abs(sum(RISK_WEIGHTS.values()) - 1.0) < 1e-9, "RISK_WEIGHTS must sum to 1.0"

CONFLICT_DENSITY_CAP = 3
"""Conflict count at/above which the conflict_density factor saturates at 1.0 — three
independent unresolved disagreements on one record is already the ceiling of "how much
worse can this get" for a single-property conflict count in the observed real data."""

GT_GNSS_DISAGREEMENT_BONUS = 10.0
"""Added on top of the weighted composite, capped at 100, when a real conflict on this
record involves a ground-truth or GNSS-CORS source. These carry the platform's highest
positional reliability prior (core/registry.py PRIORS: 0.96 / 0.99 vs 0.55-0.76 for
cadastral/municipal/AI sources) — a disagreement touching one is a materially stronger
signal than an ordinary inter-department or inter-model disagreement, and the statutory
rule R-CTL-01 (conflict/resolver.py) already treats such control as authoritative."""

RISK_BANDS: tuple[tuple[float, str], ...] = (
    (75.0, "CRITICAL"),
    (50.0, "HIGH"),
    (25.0, "MEDIUM"),
    (0.0, "LOW"),
)

FACTOR_MEANING: dict[str, str] = {
    "positional": "Weakness in expected geometric accuracy (1 - positional confidence).",
    "source_agreement": (
        "How little independent corroboration this record has, and whether it carries an "
        "unresolved conflict (1 - source agreement confidence)."
    ),
    "topological": (
        "Geometry validity/repair issues remaining after automated topology correction "
        "(1 - topological confidence)."
    ),
    "conflict_density": f"Recorded conflicts on this entity, scaled to 1.0 at {CONFLICT_DENSITY_CAP}+ conflicts.",
    "attribute_completeness": "Missing canonical attribute fields (1 - attribute completeness confidence).",
    "uncorroborated": "Whether this record rests on a single, uncorroborated source (low cluster support).",
    "temporal_currency": "How stale the freshest contributing source is (1 - temporal currency confidence).",
    "lineage_integrity": (
        "Weakness in the provenance ledger/rationale trail behind this record "
        "(1 - lineage integrity confidence)."
    ),
}


def _band(score: float) -> str:
    for floor, name in RISK_BANDS:
        if score >= floor:
            return name
    return "LOW"


def _conf(props: dict[str, Any], name: str) -> float:
    v = props.get(f"conf_{name}")
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        # Missing dimension: the pipeline didn't compute one, which is itself informative,
        # but treating it as "unknown" (0.5) rather than "worst case" (0.0/risk=1.0) avoids
        # penalising a record for a confidence dimension this run simply didn't populate.
        return 0.5


def parcel_risk(
    props: dict[str, Any],
    *,
    linked_changes: list[dict[str, Any]] | None = None,
    dataset_source_types: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Deterministic 0..100 risk score for one harmonised parcel or building record.

    ``props`` is a GeoJSON Feature's ``properties`` dict as published by this pipeline run —
    the same object already rendered in the "Parcel Harmonization Evidence" card. Every
    factor below reads a field that already exists there; nothing is recomputed from
    geometry or re-derived from source claims.

    ``linked_changes`` / ``dataset_source_types`` are optional enrichment for a single-record
    view (``GET /api/risk/{ulpin}`` fetches and passes them). The bulk survey-priority
    ranking (``rank_parcels``) omits them for O(1)-per-record performance at 218k+ parcel
    scale — the response says so explicitly (``temporal_change_considered``,
    ``gt_gnss_conflict_bonus_applied`` staying ``False`` without ``dataset_source_types``)
    rather than silently pretending the fuller picture was checked.
    """
    conflicts_raw = props.get("conflicts") or 0
    try:
        conflicts = float(conflicts_raw)
    except (TypeError, ValueError):
        conflicts = 0.0

    n_sources = props.get("n_sources")
    cluster_support = props.get("cluster_support")
    if n_sources == 1 or cluster_support == 0:
        uncorroborated_factor = 1.0
    elif cluster_support is not None:
        try:
            uncorroborated_factor = max(0.0, 1.0 - float(cluster_support))
        except (TypeError, ValueError):
            uncorroborated_factor = 0.3
    else:
        # Neither field present on this record: unknown corroboration, not "fine".
        uncorroborated_factor = 0.3

    factors = {
        "positional": 1.0 - _conf(props, "positional"),
        "source_agreement": 1.0 - _conf(props, "source_agreement"),
        "topological": 1.0 - _conf(props, "topological"),
        "conflict_density": min(conflicts / CONFLICT_DENSITY_CAP, 1.0),
        "attribute_completeness": 1.0 - _conf(props, "attribute_completeness"),
        "uncorroborated": uncorroborated_factor,
        "temporal_currency": 1.0 - _conf(props, "temporal_currency"),
        "lineage_integrity": 1.0 - _conf(props, "lineage_integrity"),
    }

    composite = sum(RISK_WEIGHTS[name] * value for name, value in factors.items())
    score = round(composite * 100.0, 1)

    bonus_applied = False
    bonus_reason = None
    if conflicts > 0 and dataset_source_types:
        contributing = _twin.split_datasets(props.get("contributing_datasets"))
        involved_types = {dataset_source_types.get(d) for d in contributing}
        if involved_types & {"ground_truth", "gnss_cors"}:
            score = min(100.0, round(score + GT_GNSS_DISAGREEMENT_BONUS, 1))
            bonus_applied = True
            bonus_reason = (
                f"+{GT_GNSS_DISAGREEMENT_BONUS:.0f}: an unresolved conflict on this record "
                "involves a ground-truth/GNSS-CORS source, the platform's highest positional "
                "reliability tier."
            )

    change_note = None
    if linked_changes:
        actionable = [c for c in linked_changes if c.get("is_actionable")]
        if actionable:
            change_note = (
                f"{len(actionable)} actionable change-detection record(s) linked to this "
                "entity — not scored numerically here (see /api/timeline for detail), shown "
                "for context only."
            )

    return {
        "score": score,
        "band": _band(score),
        "factors": [
            {
                "name": name,
                "value": round(value, 4),
                "weight": RISK_WEIGHTS[name],
                "contribution": round(RISK_WEIGHTS[name] * value * 100.0, 2),
                "meaning": FACTOR_MEANING[name],
            }
            for name, value in factors.items()
        ],
        "conflicts_on_record": conflicts,
        "gt_gnss_conflict_bonus_applied": bonus_applied,
        "gt_gnss_conflict_bonus_reason": bonus_reason,
        "temporal_change_considered": linked_changes is not None,
        "temporal_change_note": change_note,
    }


# --------------------------------------------------------------------------------------
# AI Survey Priority Queue
# --------------------------------------------------------------------------------------


def _feature_area_matches(props: dict[str, Any], ward: str | None, zone: str | None) -> bool:
    if ward and ward.lower() != "all":
        candidate = str(
            props.get("ward") or props.get("village_name") or props.get("taluk_name") or ""
        ).lower()
        if ward.lower() not in candidate:
            return False
    if zone:
        candidate = str(props.get("zone") or props.get("ulb_code") or "").lower()
        if zone.lower() not in candidate:
            return False
    return True


def rank_parcels(
    features: list[dict[str, Any]],
    *,
    ward: str | None = None,
    zone: str | None = None,
    min_score: float = 0.0,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Rank real harmonised records by deterministic risk score, highest first.

    Deliberately O(1)-per-record: only the fields already on each ``properties`` dict are
    used (no per-record adjudication/change lookups), so this stays fast at the full run's
    scale (218k parcels / 1.4M buildings observed against the live ``chennai_metro`` output)
    without needing a cache to be usable at all — callers wanting the richer per-record
    picture (linked conflicts, changes) should follow up with ``GET /api/risk/{ulpin}`` or
    ``GET /api/evidence/{identifier}`` for that one record.
    """
    scored: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for f in features:
        props = f.get("properties", {})
        if not _feature_area_matches(props, ward, zone):
            continue
        risk = parcel_risk(props)
        if risk["score"] < min_score:
            continue
        scored.append((risk, props))

    scored.sort(key=lambda pair: pair[0]["score"], reverse=True)
    total = len(scored)
    page = scored[offset: offset + limit]

    items = []
    for i, (risk, props) in enumerate(page):
        top_factors = sorted(risk["factors"], key=lambda f: f["contribution"], reverse=True)[:3]
        items.append({
            "priority_rank": offset + i + 1,
            "ulpin": props.get("ulpin"),
            "entity_id": props.get("entity_id"),
            "ward": props.get("ward") or props.get("village_name"),
            "survey_number": props.get("survey_number"),
            "risk_score": risk["score"],
            "risk_band": risk["band"],
            "confidence_grade": props.get("confidence_grade"),
            "conflicts_on_record": risk["conflicts_on_record"],
            "top_risk_factors": [
                {"name": tf["name"], "contribution": tf["contribution"], "meaning": tf["meaning"]}
                for tf in top_factors
            ],
        })

    return {
        "total_matching": total,
        "returned": len(items),
        "offset": offset,
        "limit": limit,
        "filters": {"ward": ward, "zone": zone, "min_score": min_score},
        "items": items,
    }
