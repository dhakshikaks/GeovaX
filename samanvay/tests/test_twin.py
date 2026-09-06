"""Tests for the Land Digital Twin, Explainable AI Evidence, and Temporal Land Intelligence
views (``api/twin.py``).

Every property value in the fixtures below is copied verbatim from a real published
pipeline run (``out/ms_proof/`` — a small real AOI harmonising TNGIS cadastre against
GCC/Google/Microsoft building footprints), including the geometry that makes the
adjudication-linkage test actually exercise a real recorded conflict rather than an
invented one. This follows the repo's existing convention (``test_pipeline_units.py``) of
exercising real-shaped small objects directly instead of loading a multi-hundred-megabyte
corpus in a unit test; the full pipeline output was additionally exercised end-to-end
through ``api/app.py`` by hand (see docs/10-digital-twin.md) as part of validating this
module, since that is what actually proves the file-backed store integration works, not
just the pure functions in isolation.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from samanvay.api import twin
from samanvay.core.ledger import ProvenanceLedger
from samanvay.pipeline.presets import default_layers

# --------------------------------------------------------------------------------------
# fixtures: verbatim field values from a real out/ms_proof pipeline run
# --------------------------------------------------------------------------------------

# A real parcel: PAR-87127b016bef524246a2a3a8 / ULPIN 33GCCD8ES7W2T1, single contributing
# dataset (NCSCM_CADASTRE had zero features in this AOI), no recorded conflict.
PARCEL = {
    "type": "Feature",
    "geometry": {"type": "Polygon", "coordinates": [[
        [80.14911629803642, 13.097818901011525], [80.14887200308442, 13.097883096079372],
        [80.14808910099268, 13.098028099728491], [80.14797900287445, 13.097246502100115],
        [80.14837659906195, 13.097114096785765], [80.14838290205303, 13.096783099242309],
        [80.14869120090218, 13.096722199061075], [80.1490040967179, 13.096660300992676],
        [80.14903440304909, 13.0968630988935], [80.14944589577891, 13.096874103679923],
        [80.14949069540067, 13.097589797341397], [80.14947829998843, 13.097656403196977],
        [80.14911629803642, 13.097818901011525],
    ]]},
    "properties": {
        "entity_id": "PAR-87127b016bef524246a2a3a8", "ulpin": "33GCCD8ES7W2T1",
        "contributing_datasets": "TNGIS_CADASTRE", "n_sources": 1, "conflicts": 0,
        "survey_number": "0", "subdivision": "570", "computed_extent_m2": 17436.097,
        "building_count": 98, "built_up_area_m2": 15533.14, "ground_coverage_pct": 89.09,
        "confidence": 0.5262, "confidence_grade": "D",
        "conf_positional": 0.2773, "conf_source_agreement": 0.3,
        "conf_topological": 1.0, "conf_attribute_completeness": 0.2966,
        "conf_temporal_currency": 0.8105, "conf_lineage_integrity": 1.0,
    },
}

# A real building under that same parcel: BUI-1e5bd6b965e60475bcd06306, door number
# preserved as a passthrough attribute — this is the identifier changes.json actually keys
# cross-source building changes on, since change detection runs before ULPIN minting.
BUILDING_WITH_CHANGE = {
    "type": "Feature",
    "geometry": {"type": "Polygon", "coordinates": [[
        [80.14858180000002, 13.097014], [80.1484613, 13.0969809], [80.1484561, 13.0969996],
        [80.1484464, 13.0970388], [80.148579, 13.0970727], [80.1485931, 13.0970163],
        [80.14858180000002, 13.097014],
    ]]},
    "properties": {
        "entity_id": "BUI-1e5bd6b965e60475bcd06306", "ulpin": None,
        "contributing_datasets": "GCC_BUILDINGS,GOOGLE_OPEN_BUILDINGS", "n_sources": 2,
        "conflicts": 1, "ward": "86", "zone": "7", "door_number": "G-086-23-00578",
        "locality": "ATHIPATTU", "footprint_area_m2": 96.222, "parcel_ulpin": "33GCCD8ES7W2T1",
        "confidence": 0.6505, "confidence_grade": "C",
        "conf_positional": 0.4635, "conf_source_agreement": 0.3835,
        "conf_topological": 1.0, "conf_attribute_completeness": 0.7031,
        "conf_temporal_currency": 0.7794, "conf_lineage_integrity": 1.0,
    },
}

# The real ChangeRecord (changes.json) whose entity_id is that same door number.
CHANGE_RECORD = {
    "entity_id": "G-086-23-00578", "change_type": "geometric_disagreement", "confidence": 0.9998,
    "area_before_m2": 96.17, "area_after_m2": 95.16, "area_delta_m2": -1.01, "area_delta_pct": -1.05,
    "centroid_shift_m": 4.723, "residual_shift_m": 6.536, "height_delta_m": None,
    "changed_attributes": {}, "related_ids": ["GOOGLE_OPEN_BUILDINGS#107400"],
    "registry_action": ("Two departments hold materially different boundaries for the same "
                         "feature. Reconcile before either is used for a statutory purpose."),
    "evidence": ["boundary moved 6.54 m beyond the layer-wide offset"], "is_actionable": True,
}

# A second real building, at a different location, escalated to human adjudication —
# BUI-1a8c7aa96226821166ba33d3 — whose geometry is *identical* to the boundary the
# adjudication queue actually published for case ADJ-CF-f1fdcb8018bf (Dempster-Shafer
# geometry fusion always emits one source's real boundary verbatim, never an average, so an
# exact match here is expected, not a coincidence).
BUILDING_WITH_CONFLICT = {
    "type": "Feature",
    "geometry": {"type": "Polygon", "coordinates": [[
        [80.1528956, 13.0593714], [80.1527335, 13.0593743], [80.15245570000002, 13.0593793],
        [80.1523004, 13.0593821], [80.152267, 13.0593827], [80.1522681, 13.0600815],
        [80.152901, 13.0600891], [80.1528956, 13.0593714],
    ]]},
    "properties": {
        "entity_id": "BUI-1a8c7aa96226821166ba33d3", "ulpin": None,
        "contributing_datasets": "GCC_BUILDINGS,GOOGLE_OPEN_BUILDINGS", "n_sources": 2,
        "conflicts": 1, "ward": "150", "door_number": "N-150-23-03107",
        "parcel_ulpin": "33GCC94KMBVPWJ", "footprint_area_m2": 5360.382,
        "confidence": 0.6292, "confidence_grade": "C",
        "conf_positional": 0.3983, "conf_source_agreement": 0.3697,
        "conf_topological": 1.0, "conf_attribute_completeness": 0.7031,
        "conf_temporal_currency": 0.7794, "conf_lineage_integrity": 1.0,
    },
}

ADJUDICATION_FEATURE = {
    "type": "Feature",
    "geometry": BUILDING_WITH_CONFLICT["geometry"],
    "properties": {"case_id": "ADJ-CF-f1fdcb8018bf", "property": "geometry", "priority": 0.8741,
                   "severity": 0.9, "uncertainty": 1.0, "state": "queued",
                   "batch": "geometry|GCC_BUILDINGS+GOOGLE_OPEN_BUILDINGS|R-GEO-01"},
}

ADJUDICATION_BRIEF = {
    "case_id": "ADJ-CF-f1fdcb8018bf", "entity_id": "C00000010", "property": "geometry",
    "question": ("Which surveyed boundary is correct for this parcel? The sources disagree "
                 "beyond the tolerance that automated fusion can resolve."),
    "options": [
        {"dataset": "GCC_BUILDINGS", "source_type": "municipal_gis", "weight": 0.502,
         "observed": "2024-06-30T00:00:00+00:00", "declared_accuracy_m": 1.0},
        {"dataset": "GOOGLE_OPEN_BUILDINGS", "source_type": "ai_extraction", "weight": 0.387,
         "observed": "2023-06-30T00:00:00+00:00", "declared_accuracy_m": 1.8},
    ],
    "why": ("[R-GEO-01] Competing boundaries more than 10 m apart are not a digitising "
            "difference. This is a datum, control or identity error and automated fusion "
            "would launder it into a false answer."),
    "belief": 0.0, "uncertainty": 1.0, "severity": 0.9, "priority": 0.8741,
    "context": {"area_m2": 5357.21, "ward": "150"},
}


def real_provenance_entries() -> list[dict]:
    """The real per-run provenance entries, built the same way `/api/provenance` and
    `api/app.py::_real_provenance_entries` do, from the pipeline's own real LayerSpec
    presets — not a hand-typed stand-in schema.
    """
    entries = []
    for layer in default_layers(data_dir=""):
        entries.append({
            "dataset_id": layer.dataset_id,
            "source_type": layer.source_type.value,
            "authority": layer.authority,
            "authority_full_name": layer.authority,
            "licence": layer.licence,
            "accuracy_m": layer.accuracy_m,
            "vintage": layer.vintage,
            "tier": layer.tier,
            "platform": layer.platform,
            "transformation": layer.transformation,
            "coverage": layer.coverage,
            "crs": None,
        })
    return entries


class FakeStore:
    """A minimal stand-in for FeatureStore/PostgisStore exposing the same read surface
    (`collections`, `.queue()`, `.changes()`, `.ledger`, `.metrics()`) that `api/twin.py`
    actually uses, backed by in-memory fixtures instead of files on disk."""

    def __init__(self, parcels=None, buildings=None, adjudication=None, utilities=None,
                 queue=None, changes=None, ledger=None):
        self.collections = {
            "parcels": parcels or [], "buildings": buildings or [],
            "adjudication": adjudication or [], "utilities": utilities or [],
        }
        self._queue = queue or []
        self._changes = changes or []
        self.ledger = ledger or ProvenanceLedger()

    def queue(self):
        return self._queue

    def changes(self):
        return self._changes

    def metrics(self):
        return {}


ENTRIES = real_provenance_entries()


# --------------------------------------------------------------------------------------
# 1. Land Digital Twin
# --------------------------------------------------------------------------------------


def test_digital_twin_links_buildings_and_datasets():
    store = FakeStore(parcels=[PARCEL], buildings=[BUILDING_WITH_CHANGE])
    result = twin.digital_twin(store, "33GCCD8ES7W2T1", ENTRIES)

    assert result is not None
    assert result["identity"]["ulpin"] == "33GCCD8ES7W2T1"
    assert result["identity"]["entity_id"] == "PAR-87127b016bef524246a2a3a8"
    assert result["buildings"]["count"] == 1
    assert result["buildings"]["features"][0]["properties"]["entity_id"] == "BUI-1e5bd6b965e60475bcd06306"

    by_id = {d["dataset_id"]: d for d in result["linked_datasets"]}
    assert "TNGIS_CADASTRE" in by_id
    assert by_id["TNGIS_CADASTRE"]["category"] == "cadastral"
    assert by_id["TNGIS_CADASTRE"]["roles"] == ["parcel boundary/attributes"]
    assert "GCC_BUILDINGS" in by_id
    assert by_id["GCC_BUILDINGS"]["category"] == "municipal_gis"
    assert "building BUI-1e5bd6b965e60475bcd06306" in by_id["GCC_BUILDINGS"]["roles"]


def test_digital_twin_unknown_ulpin_returns_none():
    store = FakeStore(parcels=[PARCEL])
    assert twin.digital_twin(store, "NOT-A-REAL-ULPIN", ENTRIES) is None


# --------------------------------------------------------------------------------------
# 2. Explainable AI Evidence
# --------------------------------------------------------------------------------------


def test_evidence_object_reconstructs_stored_confidence_exactly():
    store = FakeStore(buildings=[BUILDING_WITH_CHANGE])
    result = twin.evidence_object(store, "BUI-1e5bd6b965e60475bcd06306", ENTRIES)

    assert result is not None
    conf = result["confidence"]
    # The composite this reconstructs from the six stored conf_* dimensions must match the
    # composite the pipeline itself stored — proof this is a re-derivation, not a guess.
    assert conf["composite_matches_stored_record"] is True
    assert conf["stored_composite"] == 0.6505
    assert conf["weakest_dimension"] == "source_agreement"
    assert len(conf["dimensions"]) == 6
    names = {d["name"] for d in conf["dimensions"]}
    assert names == {"positional", "source_agreement", "topological",
                      "attribute_completeness", "temporal_currency", "lineage_integrity"}
    for d in conf["dimensions"]:
        assert d["meaning"]  # every dimension carries a real, non-empty explanation


def test_evidence_object_links_real_conflict_case_by_geometry():
    store = FakeStore(
        buildings=[BUILDING_WITH_CONFLICT],
        adjudication=[ADJUDICATION_FEATURE],
        queue=[ADJUDICATION_BRIEF],
    )
    result = twin.evidence_object(store, "BUI-1a8c7aa96226821166ba33d3", ENTRIES)

    assert result is not None
    linked = result["conflicting_sources"]["linked_case"]
    assert linked is not None
    assert linked["case_id"] == "ADJ-CF-f1fdcb8018bf"
    assert "distance=0.00 m" in linked["matched_by"]
    assert "derived" in linked["matched_by"]  # never presented as an authoritative key
    assert len(linked["options"]) == 2


def test_evidence_object_honestly_reports_absence_of_a_linkable_case():
    # Same conflict flag, but no adjudication data published at all — must not fabricate one.
    store = FakeStore(buildings=[BUILDING_WITH_CONFLICT])
    result = twin.evidence_object(store, "BUI-1a8c7aa96226821166ba33d3", ENTRIES)

    conflicting = result["conflicting_sources"]
    assert conflicting["conflict_count_on_record"] == 1
    assert "linked_case" not in conflicting
    assert "auto-resolved" in conflicting["note"] or "no adjudication-queue case" in conflicting["note"]


def test_evidence_object_no_conflicts_reports_corroboration():
    store = FakeStore(parcels=[PARCEL])
    result = twin.evidence_object(store, "33GCCD8ES7W2T1", ENTRIES)
    conflicting = result["conflicting_sources"]
    assert conflicting["conflict_count_on_record"] == 0
    assert "TNGIS_CADASTRE" in conflicting["note"]


def test_evidence_object_unknown_identifier_returns_none():
    store = FakeStore(parcels=[PARCEL], buildings=[BUILDING_WITH_CHANGE])
    assert twin.evidence_object(store, "does-not-exist", ENTRIES) is None


def test_source_reliability_breakdown_reflects_real_registry_priors():
    store = FakeStore(buildings=[BUILDING_WITH_CHANGE])
    result = twin.evidence_object(store, "BUI-1e5bd6b965e60475bcd06306", ENTRIES)
    by_id = {r["dataset_id"]: r for r in result["source_reliability"]}
    assert set(by_id) == {"GCC_BUILDINGS", "GOOGLE_OPEN_BUILDINGS"}
    for r in by_id.values():
        assert 0.0 <= r["reliability_prior"] <= 1.0
        assert 0.0 <= r["recency_weight"] <= 1.0
        assert 0.0 <= r["accuracy_weight"] <= 1.0
    # A municipal total-station survey is the stronger positional/identity source of the
    # two here; a weaker prior would mean the registry priors were wired up backwards.
    assert by_id["GCC_BUILDINGS"]["reliability_prior"] >= by_id["GOOGLE_OPEN_BUILDINGS"]["reliability_prior"]


# --------------------------------------------------------------------------------------
# 3. Temporal Land Intelligence
# --------------------------------------------------------------------------------------


def test_link_changes_matches_only_the_real_shared_identifier():
    linked = twin.link_changes(BUILDING_WITH_CHANGE, [CHANGE_RECORD])
    assert linked == [CHANGE_RECORD]

    # A building with a different door number must not pick up someone else's change.
    unrelated = {**BUILDING_WITH_CHANGE, "properties": {**BUILDING_WITH_CHANGE["properties"],
                                                         "door_number": "N-999-99-99999"}}
    assert twin.link_changes(unrelated, [CHANGE_RECORD]) == []


def test_parcel_timeline_reports_source_observations_and_pipeline_stages():
    ledger = ProvenanceLedger()
    ledger.append("TNGIS_CADASTRE", "ingest", {"features": 30689}, actor="samanvay/auto")
    ledger.append("TNGIS_CADASTRE", "schema_map", {"columns": 12}, actor="samanvay/auto")

    store = FakeStore(parcels=[PARCEL], buildings=[BUILDING_WITH_CHANGE],
                       changes=[CHANGE_RECORD], ledger=ledger)
    result = twin.parcel_timeline(store, "33GCCD8ES7W2T1", ENTRIES)

    assert result["available"] is True
    kinds = {e["kind"] for e in result["events"]}
    assert "source_observation" in kinds
    assert "pipeline_stage" in kinds
    assert "change_detected" in kinds

    observation = next(e for e in result["events"]
                       if e["kind"] == "source_observation" and e["dataset_id"] == "TNGIS_CADASTRE")
    assert observation["date"].startswith("2023")  # real vintage "2023" -> mid-year date

    change_event = next(e for e in result["events"] if e["kind"] == "change_detected")
    assert change_event["change_type"] == "geometric_disagreement"
    assert change_event["date"] is None  # no independent timestamp — never invented

    dated = [e["date"] for e in result["events"] if e["date"]]
    assert dated == sorted(dated)


def test_parcel_timeline_honestly_reports_unavailable_history():
    bare_parcel = {
        **PARCEL,
        "properties": {**PARCEL["properties"], "contributing_datasets": "SOME_UNKNOWN_DATASET"},
    }
    store = FakeStore(parcels=[bare_parcel])  # no buildings, no changes, empty ledger
    result = twin.parcel_timeline(store, "33GCCD8ES7W2T1", ENTRIES)

    assert result["available"] is False
    assert result["events"] == []
    assert "does not fabricate" in result["reason"]


def test_parcel_timeline_unknown_ulpin_returns_none():
    store = FakeStore(parcels=[PARCEL])
    assert twin.parcel_timeline(store, "NOT-A-REAL-ULPIN", ENTRIES) is None
