"""Evidence / Provenance Graph.

Reshapes ``api/twin.py::evidence_object``'s already-real output into an explicit, traceable
node/edge structure:

    FINAL PARCEL/BUILDING -> DECISION -> CONFLICT/MATCH -> SOURCE FEATURE CLAIMS -> DATASET -> AUTHORITY

No new computation happens here — this module composes ``evidence_object`` (confidence
reconstruction, source reliability, geometrically-linked adjudication case) and
``index_provenance`` (the run's real dataset catalogue) and relabels the result as nodes and
edges. A relationship only appears in the graph if the underlying data it names is real:
there is a CONFLICT/MATCH node only when ``evidence_object`` found a real, geometrically-
linked adjudication case (never a fabricated one — see that function's disclosed 30 m
threshold), and every DATASET/AUTHORITY node's fields come straight from this run's
provenance catalogue, not from a static lookup table.
"""
from __future__ import annotations

from typing import Any

from . import twin


def provenance_graph(
    store: Any, identifier: str, provenance_entries: list[dict[str, Any]]
) -> dict[str, Any] | None:
    evidence = twin.evidence_object(store, identifier, provenance_entries)
    if evidence is None:
        return None

    entries_by_id = twin.index_provenance(provenance_entries)
    subject = evidence["subject"]
    record_id = f"{subject['feature_class']}:{subject['entity_id']}"

    nodes: dict[str, dict[str, Any]] = {
        record_id: {
            "id": record_id,
            "type": subject["feature_class"],
            "label": subject.get("ulpin") or subject["entity_id"],
            "data": subject,
        }
    }
    edges: list[dict[str, str]] = []

    decision_id = None
    if evidence["confidence"]:
        conf = evidence["confidence"]
        decision_id = f"decision:{subject['entity_id']}"
        nodes[decision_id] = {
            "id": decision_id,
            "type": "decision",
            "label": f"Grade {conf['grade']} ({conf['composite'] * 100:.1f}%)",
            "data": {
                "composite": conf["composite"], "grade": conf["grade"],
                "weakest_dimension": conf["weakest_dimension"], "explanation": conf["explanation"],
            },
        }
        edges.append({"from": record_id, "to": decision_id, "relation": "SCORED_AS"})

    linked_case = evidence["conflicting_sources"].get("linked_case")
    if linked_case and decision_id:
        conflict_id = f"conflict:{linked_case['case_id']}"
        nodes[conflict_id] = {
            "id": conflict_id,
            "type": "conflict",
            "label": linked_case["case_id"],
            "data": {
                "why": linked_case.get("why"), "belief": linked_case.get("belief"),
                "uncertainty": linked_case.get("uncertainty"), "severity": linked_case.get("severity"),
                "matched_by": linked_case.get("matched_by"),
            },
        }
        edges.append({"from": decision_id, "to": conflict_id, "relation": "EXPLAINED_BY"})

        for option in linked_case.get("options", []):
            dataset_id = option.get("dataset")
            if not dataset_id:
                continue
            claim_id = f"claim:{linked_case['case_id']}:{dataset_id}"
            nodes[claim_id] = {
                "id": claim_id,
                "type": "source_feature_claim",
                "label": f"{dataset_id} boundary claim",
                "data": option,
            }
            edges.append({"from": conflict_id, "to": claim_id, "relation": "CONSIDERED_CLAIM"})
            edges.append({"from": claim_id, "to": f"dataset:{dataset_id}", "relation": "FROM_DATASET"})

    for reliability in evidence["source_reliability"]:
        dataset_id = reliability["dataset_id"]
        dataset_node_id = f"dataset:{dataset_id}"
        entry = entries_by_id.get(dataset_id, {})
        nodes[dataset_node_id] = {
            "id": dataset_node_id,
            "type": "dataset",
            "label": dataset_id,
            "data": {
                **reliability,
                "licence": entry.get("licence"),
                "crs": entry.get("crs"),
                "transformation": entry.get("transformation"),
                "coverage": entry.get("coverage"),
                "tier": entry.get("tier"),
            },
        }
        edges.append({"from": record_id, "to": dataset_node_id, "relation": "CONTRIBUTED_BY"})

        authority = entry.get("authority")
        if authority:
            authority_id = f"authority:{authority}"
            nodes[authority_id] = {
                "id": authority_id,
                "type": "authority",
                "label": entry.get("authority_full_name") or authority,
                "data": {
                    "authority": authority, "tier": entry.get("tier"),
                    "platform": entry.get("platform"), "vintage": entry.get("vintage"),
                },
            }
            edges.append({"from": dataset_node_id, "to": authority_id, "relation": "PUBLISHED_BY"})

    return {
        "subject": subject,
        "nodes": list(nodes.values()),
        "edges": edges,
        "scope_note": (
            "Every node and edge here is derived from this run's real, persisted outputs "
            "(the six-dimension confidence components, the adjudication queue's real "
            "Dempster-Shafer evidence when a case can be geometrically linked, and the "
            "provenance catalogue) via api/twin.py::evidence_object — no relationship is "
            "inferred beyond what that function already computes and discloses. A CONFLICT "
            "node appears only when a real case was found within the disclosed geometric "
            "match threshold; its absence means no such case was found, not that none exists."
        ),
    }
