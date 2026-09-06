# 11 · Risk scoring, adjudication copilot, provenance graph, and what-if analysis

The second innovation layer, built entirely on top of the first
([10 · Digital twin, evidence & timeline](10-digital-twin-evidence-timeline.md)) and the
harmonisation pipeline's own outputs. Four capabilities, in
`backend/GeovaX/api/{risk,copilot,graph,whatif}.py`:

- `GET /api/risk/queue`, `GET /api/risk/{identifier}` — Parcel Risk Score / AI Survey
  Priority Queue
- `GET /api/copilot/recommend` — AI Adjudication Copilot
- `GET /api/graph/{identifier}` — Evidence/Provenance Graph
- `POST /api/whatif/simulate` — What-If Land Impact Analysis

(see [04 · API reference](04-api.md) for full parameter/response detail). As with the first
layer, this document states what is real, what is *derived*, and any disclosed scope limit.

---

## 1. Parcel Risk Score / AI Survey Priority Queue

**What it is.** A deterministic 0-100 score for one parcel or building, and a ranking of a
whole collection by that score — never a hardcoded or invented number. Every factor is read
directly from a field the pipeline already persisted on the record: the six `conf_*`
confidence components, `conflicts`, `n_sources`, `cluster_support`. The eight weights
(`RISK_WEIGHTS` in `api/risk.py`) are declared and sum to exactly 1.0, so the composite is
checkable by hand — the same convention `ConfidenceReport.DEFAULT_WEIGHTS` already
established (`core/models.py`).

**Why risk isn't just "1 - confidence".** Confidence is a report card on how much to trust
what the pipeline already decided. Risk additionally weighs signals confidence deliberately
keeps distinct: how many conflicts a record actually carries (`conflict_density`), whether it
rests on a single uncorroborated source (`uncorroborated`, from real `cluster_support`), and
— specifically — whether an unresolved conflict on the record involves a ground-truth or
GNSS-CORS source. That last one gets its own documented `GT_GNSS_DISAGREEMENT_BONUS`: these
sources carry the platform's highest positional reliability prior
(`core/registry.py::PRIORS`: 0.96-0.99 vs 0.55-0.76 for cadastral/municipal/AI sources), and
statutory rule R-CTL-01 already treats such control as authoritative — a disagreement
touching one is a materially stronger signal than an ordinary inter-department disagreement,
and the bonus only ever applies when both a real conflict (`conflicts > 0`) and a real
GT/GNSS-typed contributing dataset are present.

**Bulk vs single-record scope, stated honestly.** The priority queue (`rank_parcels`) is
deliberately O(1) per record — no per-record adjudication or change lookup — so it stays fast
at full scale (measured on the real `chennai_metro` run: **11.2 s** cold over 218,331
parcels, **10.8 s** cold over 1,455,650 buildings, cached 60 s afterward, matching the
existing `/collections/{id}/items` caching pattern). The single-record view
(`GET /api/risk/{identifier}`) additionally calls `twin.link_changes` and builds a
dataset→source-type map, for the fuller picture the queue's scale can't afford — its response
says exactly which factors were considered (`temporal_change_considered`,
`gt_gnss_conflict_bonus_applied`) rather than silently doing less than it appears to.

---

## 2. AI Adjudication Copilot

**What it is.** For one real, open adjudication case, a recommendation —
`ACCEPT_SOURCE` / `NEED_FIELD_SURVEY` / `ESCALATE` — with the evidence behind it. Never
presented as a decision: every response carries `is_automated_recommendation: true` and a
`disclaimer` naming `POST /api/adjudication/resolve` as the only authoritative path.

**The decision ladder is the resolver's own ladder, reused, not reinvented.**
`copilot.recommend_for_case` imports `conflict/resolver.py`'s real `PRECEDENCE` table and
`ResolverConfig` (`belief_floor`, `uncertainty_ceiling`) directly — it does not declare a
second, independently-tuned notion of "authoritative" or "confident enough" that could drift
from what `ConflictResolver` itself actually applies during a run:

1. **Domain precedence** (including GNSS/ground-truth control, statutory rule R-CTL-01):
   if one option's source type outranks every other present option in `PRECEDENCE[family]`,
   recommend accepting it.
2. **Fusion weight margin**: if no precedence applies, but the case's real fused `belief`
   clears `ResolverConfig.belief_floor` with acceptable `uncertainty`, and the top two
   options' weights are decisively apart (`WEIGHT_MARGIN_THRESHOLD = 0.10`), recommend the
   higher-weighted source. In practice this rung rarely fires for anything actually *in* the
   queue — reaching the queue at all is proof a case failed exactly this gate — and it's kept
   for cases where custom `ResolverConfig` thresholds legitimately differ from a persisted
   case's original run.
3. **Statutory-scale disagreement**: severity ≥ `SEVERITY_FIELD_SURVEY_FLOOR` (0.85, matching
   rule R-GEO-01's 0.90) → recommend field verification, quoting the resolver's own real
   `why` rationale rather than inventing new prose.
4. **Otherwise, escalate** — explicitly stating which real numbers (belief, uncertainty,
   weight margin) made the case indecisive.

**Verified against all 500 real cases in `out/ms_proof`**: 139 cases carry a ground-truth
option and were correctly recommended `ACCEPT_SOURCE` on precedence (exactly matching the
count of cases containing a `ground_truth`/`gnss_cors` option, confirmed independently);
115 of the remaining, R-GEO-01-severity cases were recommended `NEED_FIELD_SURVEY`; the other
246 (moderate severity, no dominant source) were `ESCALATE` — 139 + 115 + 246 = 500, with no
case falling through un-recommended.

---

## 3. Evidence / Provenance Graph

**What it is.** `evidence_object`'s already-real output (confidence components, source
reliability, a geometrically-linked adjudication case if one exists), reshaped into an
explicit node/edge chain:

```
FINAL PARCEL/BUILDING -> DECISION -> CONFLICT/MATCH -> SOURCE FEATURE CLAIMS -> DATASET -> AUTHORITY
```

No new computation happens in `api/graph.py` — it composes `twin.evidence_object` and
`twin.index_provenance` and relabels the result. A `CONFLICT` node appears *only* when
`evidence_object` found a real case within its disclosed 30 m geometric-match threshold; its
absence means no such case was found, never that the check wasn't run. Verified against real
data: a parcel with zero recorded conflicts produces exactly 4 nodes / 3 edges (record,
decision, one dataset, one authority — no conflict branch); a building with a real, linked
conflict produces the full 9-node / 10-edge chain, including one `source_feature_claim` node
per real competing option and a `FROM_DATASET` edge to each option's real dataset.

---

## 4. What-If Land Impact Analysis

**What it is.** `POST /api/whatif/simulate` evaluates a proposed geometry — a redrawn
boundary, a footprint pending acceptance — against this run's real published parcels,
buildings, utilities and open adjudication cases, using the same shapely engine and
"reproject only what's needed" pattern already used elsewhere in this codebase
(`crs/engine.py`, `change/vector_change.py`'s encroachment check,
`matching/features.py`'s STRtree blocking). Nothing is ever written; every response carries
`"simulation": true, "authoritative_change_applied": false`.

**Real metric areas, not degrees-as-metres.** Only the small set of candidates an `STRtree`
query actually returns are reprojected to the appropriate local UTM zone
(`CrsEngine.metric_crs_for`) before computing intersection area — reprojecting every
candidate in a 218k-parcel/1.4M-building collection up front would be wasted work, since a
single proposed geometry can only ever intersect a tiny, geographically local subset.

**Performance, measured honestly.** The first version of this endpoint took **20.8 s** per
call against the full `chennai_metro` run — nearly all of it spent building shapely
geometries for a full `STRtree` over all 1.4M buildings before any bbox check happened. Two
optimisations were added, in this order, each measured before moving to the next:

1. A raw-coordinate bounding-box prefilter (`_raw_bounds`) rejects nearly all of a collection
   *before* any shapely object is constructed — this alone brought a warm call down to
   **~2.5 s**, but the prefilter's own per-feature coordinate walk was still O(n) per request.
2. That prefilter's bounds are now cached in-process, keyed by the stable identity of the
   collection list `FeatureStore`/`PostgisStore` already caches internally — so walking
   1.4M buildings' coordinates is paid **once per server process**, not once per request.
   Measured on the live `chennai_metro` deployment: **~11.5 s** on the very first call after
   a server (re)start, **~0.2-0.3 s** on every call after that.

This mirrors the store's own lazy-load-once pattern (`FeatureStore.load()`) rather than
introducing a new caching mechanism, and the one-time cost is disclosed in the module
docstring rather than presented as if every call were fast.

---

## What this layer does not claim

- The priority queue's bulk ranking does not check for a linked conflict or change record per
  item (performance-scoped, see §1) — follow up with `/api/risk/{identifier}` or
  `/api/evidence/{identifier}` for that.
- The copilot's recommendation is exactly as good as the evidence already in
  `adjudication_queue.json` — it does not re-run matching, re-fuse evidence, or consult
  anything not already computed by this pipeline run.
- The graph's dataset/authority nodes are as complete as this run's provenance catalogue
  (`pipeline.presets.default_layers`) — a dataset contributing to a record but absent from
  that catalogue is not silently dropped, but it will carry fewer fields (see
  `api/twin.py::digital_twin`'s equivalent disclosure).
- What-if's proposed-geometry impact is a spatial simulation only; it does not model legal,
  administrative, or statutory consequences of a boundary change, only what it would
  physically overlap.
