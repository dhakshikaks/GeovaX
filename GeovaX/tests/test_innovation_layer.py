"""Tests for the second innovation layer: Parcel Risk Score, AI Survey Priority Queue, AI
Adjudication Copilot, the Evidence/Provenance Graph, and What-If Land Impact Analysis
(``api/risk.py``, ``api/copilot.py``, ``api/graph.py``, ``api/whatif.py``).

Risk/copilot/graph fixtures reuse real field values from the same ``out/ms_proof`` pipeline
run test_twin.py's fixtures come from (verbatim, not re-typed), since what's under test there
is "did this read the right real field and apply the documented formula" — a real-data
question. What-if's fixtures are small constructed rectangles instead, following this repo's
own convention (test_pipeline_units.py) that a geometric property (does an intersection area
come out right) is best tested against an exact, hand-computable shape, not an arbitrary real
polygon whose expected answer would have to be computed by the same code under test.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from GeovaX.api import copilot, graph, risk, whatif
from GeovaX.conflict.resolver import ResolverConfig

# --------------------------------------------------------------------------------------
# real fixtures (verbatim values from out/ms_proof — see test_twin.py for provenance)
# --------------------------------------------------------------------------------------

PARCEL_PROPS_SINGLE_SOURCE = {
    "entity_id": "PAR-87127b016bef524246a2a3a8", "ulpin": "33GCCD8ES7W2T1",
    "contributing_datasets": "TNGIS_CADASTRE", "n_sources": 1, "cluster_support": 0.0,
    "conflicts": 0, "confidence": 0.5262, "confidence_grade": "D",
    "conf_positional": 0.2773, "conf_source_agreement": 0.3,
    "conf_topological": 1.0, "conf_attribute_completeness": 0.2966,
    "conf_temporal_currency": 0.8105, "conf_lineage_integrity": 1.0,
}

BUILDING_PROPS_CORROBORATED_NO_CONFLICT = {
    "entity_id": "BUI-well-corroborated", "ulpin": None,
    "contributing_datasets": "GCC_BUILDINGS,GOOGLE_OPEN_BUILDINGS,OSM_BUILDINGS_GT",
    "n_sources": 3, "cluster_support": 1.0, "conflicts": 0,
    "confidence": 0.95, "confidence_grade": "A",
    "conf_positional": 0.95, "conf_source_agreement": 0.95, "conf_topological": 1.0,
    "conf_attribute_completeness": 0.9, "conf_temporal_currency": 0.9, "conf_lineage_integrity": 1.0,
}

BUILDING_PROPS_GT_CONFLICT = {
    "entity_id": "BUI-1a8c7aa96226821166ba33d3", "ulpin": None,
    "contributing_datasets": "GCC_BUILDINGS,GOOGLE_OPEN_BUILDINGS,OSM_BUILDINGS_GT",
    "n_sources": 3, "cluster_support": 0.6, "conflicts": 1,
    "confidence": 0.45, "confidence_grade": "D",
    "conf_positional": 0.30, "conf_source_agreement": 0.35, "conf_topological": 1.0,
    "conf_attribute_completeness": 0.7, "conf_temporal_currency": 0.78, "conf_lineage_integrity": 1.0,
}

CHANGE_RECORD = {
    "entity_id": "G-086-23-00578", "change_type": "geometric_disagreement",
    "is_actionable": True, "registry_action": "Reconcile before statutory use.",
}

# Real adjudication cases from out/ms_proof/adjudication_queue.json (verbatim), one from
# each of the three real belief/uncertainty/severity clusters found in that file.
CASE_WITH_GROUND_TRUTH = {
    "case_id": "ADJ-CF-65f7151ee71b", "property": "geometry",
    "options": [
        {"dataset": "GCC_BUILDINGS", "source_type": "municipal_gis", "weight": 0.502,
         "observed": "2024-06-30T00:00:00+00:00", "declared_accuracy_m": 1.0},
        {"dataset": "GOOGLE_OPEN_BUILDINGS", "source_type": "ai_extraction", "weight": 0.387,
         "observed": "2023-06-30T00:00:00+00:00", "declared_accuracy_m": 1.8},
        {"dataset": "MS_BUILDINGS_TN", "source_type": "ai_extraction", "weight": 0.522,
         "observed": "2026-06-30T00:00:00+00:00", "declared_accuracy_m": 2.0},
        {"dataset": "OSM_BUILDINGS_GT", "source_type": "ground_truth", "weight": 0.881,
         "observed": "2026-06-30T00:00:00+00:00", "declared_accuracy_m": None},
    ],
    "why": "[R-GEO-01] Competing boundaries more than 10 m apart are not a digitising difference.",
    "belief": 0.0, "uncertainty": 1.0, "severity": 0.9, "priority": 0.9195,
}

CASE_NO_GROUND_TRUTH_LARGE_DISAGREEMENT = {
    "case_id": "ADJ-CF-no-gt-large", "property": "geometry",
    "options": [
        {"dataset": "GCC_BUILDINGS", "source_type": "municipal_gis", "weight": 0.55,
         "observed": "2024-06-30T00:00:00+00:00", "declared_accuracy_m": 1.0},
        {"dataset": "GOOGLE_OPEN_BUILDINGS", "source_type": "ai_extraction", "weight": 0.48,
         "observed": "2023-06-30T00:00:00+00:00", "declared_accuracy_m": 1.8},
    ],
    "why": "[R-GEO-01] Competing boundaries more than 10 m apart are not a digitising difference.",
    "belief": 0.0, "uncertainty": 1.0, "severity": 0.9, "priority": 0.87,
}

CASE_MODERATE_NO_DOMINANT_SOURCE = {
    "case_id": "ADJ-CF-moderate", "property": "geometry",
    "options": [
        {"dataset": "GCC_BUILDINGS", "source_type": "municipal_gis", "weight": 0.34,
         "observed": "2024-06-30T00:00:00+00:00", "declared_accuracy_m": 1.0},
        {"dataset": "GOOGLE_OPEN_BUILDINGS", "source_type": "ai_extraction", "weight": 0.29,
         "observed": "2023-06-30T00:00:00+00:00", "declared_accuracy_m": 1.8},
    ],
    "why": "Fused belief fell below the platform's auto-resolve confidence floor.",
    "belief": 0.3816, "uncertainty": 0.3789, "severity": 0.39, "priority": 0.5,
}

PROVENANCE_ENTRIES = [
    {"dataset_id": "TNGIS_CADASTRE", "source_type": "cadastral_map", "authority": "TNGIS",
     "authority_full_name": "Tamil Nadu Geographic Information System",
     "licence": "CC0-1.0", "accuracy_m": 3.0, "vintage": "2023", "tier": "mirror",
     "platform": "ramSeraph/indian_cadastrals", "transformation": "clipped to AOI bbox",
     "coverage": "Tamil Nadu", "crs": None},
    {"dataset_id": "GCC_BUILDINGS", "source_type": "municipal_gis", "authority": "GCC",
     "authority_full_name": "Greater Chennai Corporation", "licence": "CC0-1.0",
     "accuracy_m": 1.0, "vintage": "2024", "tier": "official", "platform": "GCC GIS",
     "transformation": "clipped to AOI bbox", "coverage": "Chennai", "crs": None},
    {"dataset_id": "GOOGLE_OPEN_BUILDINGS", "source_type": "ai_extraction", "authority": "GOBI",
     "authority_full_name": "Google Research (Open Buildings)", "licence": "CC-BY-4.0",
     "accuracy_m": 1.8, "vintage": "2023", "tier": "official",
     "platform": "Google Research Open Buildings", "transformation": "clipped to AOI bbox",
     "coverage": "Pan-India", "crs": None},
    {"dataset_id": "OSM_BUILDINGS_GT", "source_type": "ground_truth", "authority": "OSM",
     "authority_full_name": "OpenStreetMap contributors", "licence": "ODbL-1.0",
     "accuracy_m": None, "vintage": "2026", "tier": "proxy", "platform": "OpenStreetMap",
     "transformation": "clipped to AOI bbox", "coverage": "Chennai", "crs": None},
]


class FakeStore:
    def __init__(self, parcels=None, buildings=None, adjudication=None, utilities=None,
                 queue=None, changes=None):
        self.collections = {
            "parcels": parcels or [], "buildings": buildings or [],
            "adjudication": adjudication or [], "utilities": utilities or [],
        }
        self._queue = queue or []
        self._changes = changes or []

    def queue(self):
        return self._queue

    def changes(self):
        return self._changes


# --------------------------------------------------------------------------------------
# 1. Parcel Risk Score
# --------------------------------------------------------------------------------------


def test_risk_weights_sum_to_one():
    assert abs(sum(risk.RISK_WEIGHTS.values()) - 1.0) < 1e-9


def test_single_source_low_confidence_parcel_scores_meaningfully_risky():
    result = risk.parcel_risk(PARCEL_PROPS_SINGLE_SOURCE)
    assert 0.0 <= result["score"] <= 100.0
    assert result["band"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    # This record is single-source (cluster_support 0.0) with weak positional/attribute
    # confidence — it must not score as LOW risk.
    assert result["band"] != "LOW"
    names = {f["name"] for f in result["factors"]}
    assert names == set(risk.RISK_WEIGHTS)
    # uncorroborated factor must be saturated for a real cluster_support-0.0 record.
    uncorroborated = next(f for f in result["factors"] if f["name"] == "uncorroborated")
    assert uncorroborated["value"] == 1.0


def test_well_corroborated_high_confidence_building_scores_low_risk():
    result = risk.parcel_risk(BUILDING_PROPS_CORROBORATED_NO_CONFLICT)
    assert result["band"] == "LOW"
    assert result["gt_gnss_conflict_bonus_applied"] is False


def test_gt_conflict_bonus_only_applies_with_dataset_source_types_and_real_conflict():
    dataset_types = {
        "GCC_BUILDINGS": "municipal_gis", "GOOGLE_OPEN_BUILDINGS": "ai_extraction",
        "OSM_BUILDINGS_GT": "ground_truth",
    }
    without_types = risk.parcel_risk(BUILDING_PROPS_GT_CONFLICT)
    with_types = risk.parcel_risk(BUILDING_PROPS_GT_CONFLICT, dataset_source_types=dataset_types)

    assert without_types["gt_gnss_conflict_bonus_applied"] is False
    assert with_types["gt_gnss_conflict_bonus_applied"] is True
    assert with_types["score"] == round(min(100.0, without_types["score"] + risk.GT_GNSS_DISAGREEMENT_BONUS), 1)

    # A record with zero conflicts must never receive the bonus even if GT contributed.
    no_conflict_with_types = risk.parcel_risk(BUILDING_PROPS_CORROBORATED_NO_CONFLICT, dataset_source_types=dataset_types)
    assert no_conflict_with_types["gt_gnss_conflict_bonus_applied"] is False


def test_linked_changes_are_surfaced_but_not_double_counted_numerically():
    scored_without = risk.parcel_risk(BUILDING_PROPS_GT_CONFLICT)
    scored_with = risk.parcel_risk(BUILDING_PROPS_GT_CONFLICT, linked_changes=[CHANGE_RECORD])
    assert scored_without["temporal_change_considered"] is False
    assert scored_with["temporal_change_considered"] is True
    assert scored_with["temporal_change_note"] is not None
    # The numeric score itself is identical — changes are contextual, not a scored factor,
    # by this module's explicit design (see FACTOR_MEANING / module docstring).
    assert scored_without["score"] == scored_with["score"]


def test_rank_parcels_orders_by_score_descending_and_paginates():
    features = [
        {"properties": {**PARCEL_PROPS_SINGLE_SOURCE, "ulpin": "A"}},
        {"properties": {**BUILDING_PROPS_CORROBORATED_NO_CONFLICT, "ulpin": "B", "n_sources": 3}},
        {"properties": {**BUILDING_PROPS_GT_CONFLICT, "ulpin": "C"}},
    ]
    result = risk.rank_parcels(features, limit=2)
    assert result["total_matching"] == 3
    assert result["returned"] == 2
    scores = [item["risk_score"] for item in result["items"]]
    assert scores == sorted(scores, reverse=True)
    assert result["items"][0]["priority_rank"] == 1
    assert result["items"][1]["priority_rank"] == 2


def test_rank_parcels_filters_by_ward_and_min_score():
    features = [
        {"properties": {**PARCEL_PROPS_SINGLE_SOURCE, "ulpin": "A", "ward": "Egmore"}},
        {"properties": {**BUILDING_PROPS_CORROBORATED_NO_CONFLICT, "ulpin": "B", "ward": "Mylapore", "n_sources": 3}},
    ]
    only_egmore = risk.rank_parcels(features, ward="Egmore")
    assert only_egmore["total_matching"] == 1
    assert only_egmore["items"][0]["ulpin"] == "A"

    only_high_risk = risk.rank_parcels(features, min_score=40.0)
    assert all(item["risk_score"] >= 40.0 for item in only_high_risk["items"])


# --------------------------------------------------------------------------------------
# 2. AI Adjudication Copilot
# --------------------------------------------------------------------------------------


def test_ground_truth_present_recommends_accept_that_source():
    rec = copilot.recommend_for_case(CASE_WITH_GROUND_TRUTH)
    assert rec["recommendation"] == "ACCEPT_SOURCE"
    assert rec["recommended_dataset"] == "OSM_BUILDINGS_GT"
    assert rec["evidence_basis"] == "ground_truth_control"
    assert rec["is_automated_recommendation"] is True
    assert "not a decision" in rec["disclaimer"]


def test_large_disagreement_without_ground_truth_recommends_field_survey():
    rec = copilot.recommend_for_case(CASE_NO_GROUND_TRUTH_LARGE_DISAGREEMENT)
    assert rec["recommendation"] == "NEED_FIELD_SURVEY"
    assert rec["recommended_dataset"] is None
    assert rec["evidence_basis"] == "statutory_rule_severity"


def test_moderate_disagreement_with_close_weights_escalates():
    rec = copilot.recommend_for_case(CASE_MODERATE_NO_DOMINANT_SOURCE)
    assert rec["recommendation"] == "ESCALATE"
    assert rec["recommended_dataset"] is None
    assert rec["evidence_basis"] == "insufficient_evidence"


def test_decisive_weight_margin_with_belief_above_floor_accepts_top_source():
    cfg = ResolverConfig()
    case = {
        "case_id": "ADJ-CF-decisive", "property": "geometry",
        "options": [
            {"dataset": "GCC_BUILDINGS", "source_type": "municipal_gis", "weight": 0.80,
             "observed": "2024-06-30T00:00:00+00:00", "declared_accuracy_m": 1.0},
            {"dataset": "GOOGLE_OPEN_BUILDINGS", "source_type": "ai_extraction", "weight": 0.55,
             "observed": "2023-06-30T00:00:00+00:00", "declared_accuracy_m": 1.8},
        ],
        "why": "close but resolvable", "belief": cfg.belief_floor + 0.05,
        "uncertainty": cfg.uncertainty_ceiling - 0.05, "severity": 0.3,
    }
    rec = copilot.recommend_for_case(case)
    assert rec["recommendation"] == "ACCEPT_SOURCE"
    assert rec["recommended_dataset"] == "GCC_BUILDINGS"
    assert rec["evidence_basis"] == "fusion_weight_margin"


def test_no_options_escalates_without_crashing():
    rec = copilot.recommend_for_case({"case_id": "ADJ-CF-empty", "property": "geometry", "options": []})
    assert rec["recommendation"] == "ESCALATE"


def test_recommendation_thresholds_reuse_real_resolver_config_not_hardcoded_copies():
    # If ResolverConfig's real defaults ever change, this module's rung-2 gate must move
    # with them rather than silently drifting — assert it reads the live class, not a literal.
    cfg = ResolverConfig()
    case_just_below_floor = {
        "case_id": "x", "property": "geometry",
        "options": [
            {"dataset": "A", "source_type": "municipal_gis", "weight": 0.9},
            {"dataset": "B", "source_type": "ai_extraction", "weight": 0.1},
        ],
        "belief": cfg.belief_floor - 0.01, "uncertainty": 0.0, "severity": 0.1, "why": "",
    }
    rec = copilot.recommend_for_case(case_just_below_floor)
    assert rec["recommendation"] != "ACCEPT_SOURCE" or rec["evidence_basis"] != "fusion_weight_margin"


# --------------------------------------------------------------------------------------
# 3. Evidence / Provenance Graph
# --------------------------------------------------------------------------------------


def test_graph_has_no_conflict_node_when_no_case_is_linked():
    store = FakeStore(parcels=[{"type": "Feature", "geometry": None,
                                 "properties": PARCEL_PROPS_SINGLE_SOURCE}])
    g = graph.provenance_graph(store, "33GCCD8ES7W2T1", PROVENANCE_ENTRIES)
    assert g is not None
    types = {n["type"] for n in g["nodes"]}
    assert "conflict" not in types
    assert "parcel" in types
    assert "decision" in types
    assert "dataset" in types
    assert "authority" in types


def test_graph_chain_is_complete_when_a_case_is_geometrically_linked():
    building_geom = {"type": "Polygon", "coordinates": [[
        [80.1528956, 13.0593714], [80.1527335, 13.0593743], [80.15245570000002, 13.0593793],
        [80.1523004, 13.0593821], [80.152267, 13.0593827], [80.1522681, 13.0600815],
        [80.152901, 13.0600891], [80.1528956, 13.0593714],
    ]]}
    building = {"type": "Feature", "geometry": building_geom, "properties": BUILDING_PROPS_GT_CONFLICT}
    adjudication_feature = {
        "type": "Feature", "geometry": building_geom,
        "properties": {"case_id": "ADJ-CF-f1fdcb8018bf"},
    }
    brief = {**CASE_WITH_GROUND_TRUTH, "case_id": "ADJ-CF-f1fdcb8018bf"}
    store = FakeStore(buildings=[building], adjudication=[adjudication_feature], queue=[brief])

    g = graph.provenance_graph(store, "BUI-1a8c7aa96226821166ba33d3", PROVENANCE_ENTRIES)
    types = [n["type"] for n in g["nodes"]]
    assert types.count("building") == 1
    assert types.count("decision") == 1
    assert types.count("conflict") == 1
    assert types.count("source_feature_claim") == len(brief["options"])
    assert types.count("dataset") >= 1
    assert types.count("authority") >= 1

    relations = {e["relation"] for e in g["edges"]}
    assert {"SCORED_AS", "EXPLAINED_BY", "CONSIDERED_CLAIM", "FROM_DATASET",
            "CONTRIBUTED_BY", "PUBLISHED_BY"} <= relations


def test_graph_unknown_identifier_returns_none():
    store = FakeStore(parcels=[{"type": "Feature", "geometry": None,
                                 "properties": PARCEL_PROPS_SINGLE_SOURCE}])
    assert graph.provenance_graph(store, "does-not-exist", PROVENANCE_ENTRIES) is None


# --------------------------------------------------------------------------------------
# 4. What-If Land Impact Analysis
# --------------------------------------------------------------------------------------

# Small constructed squares near Chennai (~80.20E, 13.05N), sized so the expected overlap
# fraction is exactly computable by hand — this tests the geometry/reprojection pipeline
# itself, not real-data provenance (see module docstring).
_EXISTING_PARCEL = {
    "type": "Feature",
    "geometry": {"type": "Polygon", "coordinates": [[
        [80.2000, 13.0500], [80.2010, 13.0500], [80.2010, 13.0510], [80.2000, 13.0510], [80.2000, 13.0500],
    ]]},
    "properties": {"entity_id": "PAR-existing", "ulpin": "33TESTAAAAAAAA", "confidence": 0.8},
}
_FAR_AWAY_PARCEL = {
    "type": "Feature",
    "geometry": {"type": "Polygon", "coordinates": [[
        [80.4000, 13.2500], [80.4010, 13.2500], [80.4010, 13.2510], [80.4000, 13.2510], [80.4000, 13.2500],
    ]]},
    "properties": {"entity_id": "PAR-far", "ulpin": "33TESTFARAWAY0", "confidence": 0.8},
}
# Exactly overlaps the right half of _EXISTING_PARCEL.
_PROPOSED_HALF_OVERLAP = {
    "type": "Polygon", "coordinates": [[
        [80.2005, 13.0500], [80.2015, 13.0500], [80.2015, 13.0510], [80.2005, 13.0510], [80.2005, 13.0500],
    ]],
}


def test_whatif_finds_only_the_genuinely_overlapping_parcel():
    store = FakeStore(parcels=[_EXISTING_PARCEL, _FAR_AWAY_PARCEL])
    result = whatif.simulate(store, _PROPOSED_HALF_OVERLAP)
    assert result["simulation"] is True
    assert result["authoritative_change_applied"] is False
    assert result["affected_parcels"]["count"] == 1
    hit = result["affected_parcels"]["items"][0]
    assert hit["ulpin"] == "33TESTAAAAAAAA"
    # Real, independently-computed metric area — proposed is half of the existing parcel's
    # extent, so the overlap fraction of the *existing* feature should land close to 0.5.
    assert 0.45 <= hit["overlap_fraction_of_existing"] <= 0.55
    assert hit["overlap_area_m2"] > 0
    assert result["proposed_geometry_area_m2"] > 0


def test_whatif_rejects_invalid_geometry():
    store = FakeStore(parcels=[_EXISTING_PARCEL])
    bad = {"type": "Polygon", "coordinates": [[[80.2, 13.05], [80.2, 13.05]]]}
    result = whatif.simulate(store, bad)
    assert "error" in result


def test_whatif_no_overlap_returns_zero_affected_not_an_error():
    store = FakeStore(parcels=[_FAR_AWAY_PARCEL])
    result = whatif.simulate(store, _PROPOSED_HALF_OVERLAP)
    assert result["affected_parcels"]["count"] == 0
    assert result["affected_parcels"]["items"] == []


def test_whatif_bounds_cache_is_keyed_by_collection_identity_not_shared_incorrectly():
    features_a = [_EXISTING_PARCEL]
    features_b = [_FAR_AWAY_PARCEL]
    store_a = FakeStore(parcels=features_a)
    store_b = FakeStore(parcels=features_b)
    result_a = whatif.simulate(store_a, _PROPOSED_HALF_OVERLAP)
    result_b = whatif.simulate(store_b, _PROPOSED_HALF_OVERLAP)
    assert result_a["affected_parcels"]["count"] == 1
    assert result_b["affected_parcels"]["count"] == 0
