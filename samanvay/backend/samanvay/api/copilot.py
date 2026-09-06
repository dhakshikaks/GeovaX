"""AI Adjudication Copilot.

Generates an evidence-based recommendation for one real, unresolved adjudication case —
never an authoritative decision. The recommendation ladder mirrors, in order, the exact
ladder ``conflict/resolver.py::ConflictResolver`` itself uses (statutory rules and domain
precedence, then evidence-fusion strength, then escalation) and reuses that module's own
``PRECEDENCE`` table and ``ResolverConfig`` thresholds directly — this file adds no second,
independently-tuned copy of "how authoritative is this source" or "how confident is
confident enough". It never re-runs Dempster-Shafer fusion or invents a belief/weight: every
number it reasons over (``options[].weight``, ``belief``, ``uncertainty``, ``severity``,
``why``) is exactly what the pipeline's own resolver already computed and persisted to
``adjudication_queue.json``.

Every response carries ``is_automated_recommendation: true`` and a disclaimer naming the
authoritative decision path (``POST /api/adjudication/resolve``) — this module recommends,
it does not decide.
"""
from __future__ import annotations

from typing import Any

from ..conflict.resolver import PRECEDENCE, ResolverConfig
from ..core.models import SourceType
from ..core.registry import property_family

RECOMMENDATION_ACCEPT = "ACCEPT_SOURCE"
RECOMMENDATION_FIELD_SURVEY = "NEED_FIELD_SURVEY"
RECOMMENDATION_ESCALATE = "ESCALATE"

WEIGHT_MARGIN_THRESHOLD = 0.10
"""Minimum gap between the top two Dempster-Shafer option weights for the copilot to treat
one option as decisively ahead on evidence weight alone (no precedence, no ground truth).
Chosen from the real observed weight spread in adjudication_queue.json (typical gaps between
distinct real sources run 0.10-0.20); anything tighter is evidence the fusion itself
considered these sources near-equally credible, which is exactly what escalation exists for."""

SEVERITY_FIELD_SURVEY_FLOOR = 0.85
"""At/above this severity, the case was escalated by a statutory distance rule (R-GEO-01
fires at severity 0.90 in this pipeline) rather than by ordinary evidence weighing — the
rule's own rationale is that a >10 m disagreement is a datum/control/identity error no
automated weighing should paper over, so the copilot defers to field verification rather
than picking a side on weight alone."""

_DISCLAIMER = (
    "This is an automated recommendation only, derived from this run's real evidence "
    "(source weights, confidence, precedence, ground-truth/GNSS presence). It is not a "
    "decision. The adjudicating officer's determination via POST /api/adjudication/resolve "
    "is the only authoritative outcome, and may differ from this recommendation."
)


def _precedence_rank(source_type_value: str, family: str) -> int | None:
    order = PRECEDENCE.get(family, ())
    try:
        return order.index(SourceType(source_type_value))
    except ValueError:
        return None


def recommend_for_case(case: dict[str, Any]) -> dict[str, Any]:
    """An evidence-based recommendation for one real adjudication-queue case brief (the
    exact object ``store.queue()`` / ``GET /api/adjudication`` already serves).
    """
    options = case.get("options") or []
    if not options:
        return {
            "case_id": case.get("case_id"),
            "recommendation": RECOMMENDATION_ESCALATE,
            "recommended_dataset": None,
            "rationale": "This case carries no competing options to reason over.",
            "evidence_basis": "none",
            "is_automated_recommendation": True,
            "disclaimer": _DISCLAIMER,
        }

    family = property_family(str(case.get("property", "geometry")))
    cfg = ResolverConfig()

    # -- rung 1: domain precedence (includes GNSS/ground-truth control, R-CTL-01) ---------
    ranked = []
    for opt in options:
        rank = _precedence_rank(opt.get("source_type", ""), family)
        if rank is not None:
            ranked.append((rank, opt))
    if ranked:
        ranked.sort(key=lambda pair: pair[0])
        best_rank, best_opt = ranked[0]
        tied = [opt for rank, opt in ranked if rank == best_rank and opt is not best_opt]
        if not tied:
            source_type = best_opt.get("source_type")
            is_control = source_type in ("gnss_cors", "ground_truth")
            rationale = (
                f"{best_opt['dataset']} ({source_type}) is authoritative for '{family}' "
                + (
                    "under statutory rule R-CTL-01: GNSS/CORS and ground-truth control take "
                    "precedence over every photogrammetric or cartographic claim."
                    if is_control else
                    f"under this platform's declared domain precedence for '{family}' "
                    "(core/registry.py PRECEDENCE), ahead of every other source present "
                    "in this case."
                )
            )
            return {
                "case_id": case.get("case_id"),
                "recommendation": RECOMMENDATION_ACCEPT,
                "recommended_dataset": best_opt["dataset"],
                "rationale": rationale,
                "evidence_basis": "domain_precedence" if not is_control else "ground_truth_control",
                "evidence": {
                    "family": family,
                    "precedence_order": [t.value for t in PRECEDENCE.get(family, ())],
                    "options_considered": options,
                },
                "is_automated_recommendation": True,
                "disclaimer": _DISCLAIMER,
            }

    # -- rung 2: evidence-fusion strength, using the resolver's own confidence gate --------
    by_weight = sorted(options, key=lambda o: o.get("weight", 0.0), reverse=True)
    top = by_weight[0]
    second = by_weight[1] if len(by_weight) > 1 else None
    margin = top.get("weight", 0.0) - (second.get("weight", 0.0) if second else 0.0)
    belief = float(case.get("belief", 0.0))
    uncertainty = float(case.get("uncertainty", 1.0))

    if (
        belief >= cfg.belief_floor
        and uncertainty <= cfg.uncertainty_ceiling
        and margin >= WEIGHT_MARGIN_THRESHOLD
    ):
        return {
            "case_id": case.get("case_id"),
            "recommendation": RECOMMENDATION_ACCEPT,
            "recommended_dataset": top["dataset"],
            "rationale": (
                f"{top['dataset']} carries the highest fused evidence weight "
                f"({top.get('weight')}, {margin:.3f} ahead of the next option), and this "
                f"case's fused belief ({belief:.3f}) clears the platform's own auto-resolve "
                f"confidence floor ({cfg.belief_floor}) with acceptable uncertainty "
                f"({uncertainty:.3f} <= {cfg.uncertainty_ceiling})."
            ),
            "evidence_basis": "fusion_weight_margin",
            "evidence": {
                "belief": belief, "uncertainty": uncertainty, "weight_margin": round(margin, 4),
                "options_considered": options,
            },
            "is_automated_recommendation": True,
            "disclaimer": _DISCLAIMER,
        }

    # -- rung 3: statutory-scale disagreement -> field verification, not a guess -----------
    severity = float(case.get("severity", 0.0))
    if severity >= SEVERITY_FIELD_SURVEY_FLOOR:
        return {
            "case_id": case.get("case_id"),
            "recommendation": RECOMMENDATION_FIELD_SURVEY,
            "recommended_dataset": None,
            "rationale": (
                f"Severity {severity:.2f} matches this platform's statutory large-disagreement "
                f"threshold. {case.get('why', '')}".strip()
            ),
            "evidence_basis": "statutory_rule_severity",
            "evidence": {"severity": severity, "why": case.get("why"), "options_considered": options},
            "is_automated_recommendation": True,
            "disclaimer": _DISCLAIMER,
        }

    # -- rung 4: nothing decisive — the resolver's own escalation stands ------------------
    return {
        "case_id": case.get("case_id"),
        "recommendation": RECOMMENDATION_ESCALATE,
        "recommended_dataset": None,
        "rationale": (
            f"No source has domain precedence for '{family}' here, and the fused evidence "
            f"weights are too close (top-two margin {margin:.3f} < {WEIGHT_MARGIN_THRESHOLD}) "
            f"with belief {belief:.3f} / uncertainty {uncertainty:.3f} — this is exactly the "
            "condition the platform's own resolver escalates rather than auto-resolves "
            f"(belief floor {cfg.belief_floor}, uncertainty ceiling {cfg.uncertainty_ceiling})."
        ),
        "evidence_basis": "insufficient_evidence",
        "evidence": {
            "belief": belief, "uncertainty": uncertainty, "weight_margin": round(margin, 4),
            "options_considered": options,
        },
        "is_automated_recommendation": True,
        "disclaimer": _DISCLAIMER,
    }
