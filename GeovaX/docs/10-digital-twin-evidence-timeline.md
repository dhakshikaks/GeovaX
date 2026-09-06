# 10 · Digital twin, explainable evidence, and temporal intelligence

Three read views added on top of the existing harmonisation pipeline and its published
outputs — no new pipeline stage, no new persistence format, no synthetic data. Each view is
a function of what `pipeline/harmonise.py` already computed for a run: the confidence
components already baked into every parcel and building record, the Dempster-Shafer fusion
already recorded in the adjudication queue, the source catalogue already served by
`/api/provenance`, and the change records already written to `changes.json`. The code lives
in `backend/GeovaX/api/twin.py`; the routes are `GET /api/twin/{ulpin}`,
`GET /api/evidence/{identifier}` and `GET /api/timeline/{ulpin}` (see
[04 · API reference](04-api.md)).

This document states plainly what is real, what is *derived* (computed here from real inputs
but not itself a persisted pipeline output), and what remains a disclosed gap — the same
honesty convention the rest of this project's docs follow.

---

## 1. Land Digital Twin

**What it is.** One assembled view of a parcel: its ULPIN identity, every building linked to
it (`buildings.parcel_ulpin`, already written by `stage_structures`), and every source
dataset that contributed to either, each carrying the real authority, licence, CRS, declared
accuracy, vintage and transformation this run's provenance catalogue records for it.

**Why a dataset-level twin, not a feature-level one.** The platform's own schema
(`db/schema.sql`) defines `source_feature` and `source_claim` tables for exactly this kind of
per-claim audit trail, but `db/store.py`'s own module docstring discloses that no pipeline
stage writes to them today — claims exist only in memory during a run. Building the twin at
the dataset level (`contributing_datasets` cross-referenced against `/api/provenance`'s
catalogue) is therefore the most granular view that can be built from what is actually
persisted, and the response says so explicitly (`provenance_scope_note`) rather than
implying a feature-by-feature trail that doesn't exist yet.

**What's genuinely new here vs. what already existed.** `contributing_datasets` and
`building_count` were already on every parcel record; `/api/provenance` already served the
catalogue. Nothing computed a join between them, resolved *which* buildings and *which*
datasets belong to *this* parcel, or attached the nearby utility network by real distance.
`api/twin.py::digital_twin` does exactly that join, once, on request.

**Utility linkage.** The one real utility dataset in the catalogue (CMWSSB transmission
mains) isn't fused into the matching pipeline — there's only one source, and fusion needs
independent corroboration to mean anything (`scripts/build_utilities_layer.py`'s own
docstring). The twin instead reports the nearest utility segment within 75 m of the parcel's
centroid, computed by real geodesic distance (`crs/engine.py::haversine_m`), labelled as
proximity, not as an asserted service connection.

---

## 2. Explainable AI Evidence

**What it is.** For a given parcel or building, the six confidence dimensions the pipeline
already computed — reconstructed from the record's own stored `conf_positional`,
`conf_source_agreement`, `conf_topological`, `conf_attribute_completeness`,
`conf_temporal_currency`, `conf_lineage_integrity` fields into a real `ConfidenceReport`
object (`core/models.py`) — plus the Dempster-Shafer source-reliability weights
(`core/registry.py::SourceRegistry`) this run's own priors compute for its contributing
datasets, plus, where one exists, the real adjudication-queue case behind an unresolved
conflict.

**Deterministic, not templated.** `evidence_object` rebuilds a `ConfidenceReport` from the
persisted `conf_*` fields and calls its real `.composite`, `.grade`, `.weakest()` and
`.explain()` — the exact same computation the pipeline used to produce those fields in the
first place — and cross-checks the result against the stored `confidence` value
(`composite_matches_stored_record`). This is a re-derivation, not a re-statement: if it ever
disagreed with the stored value, that would be a real bug surfaced to the caller, not hidden.
The six per-dimension explanations (`CONFIDENCE_DIMENSION_MEANING`) describe what each score
literally measures, drawn from the scorer's own docstrings — no dimension gets an invented
explanation.

**The conflict-linkage problem, and how it's solved honestly.** `adjudication_queue.json`'s
`entity_id` is a pre-ULPIN matching-stage cluster id (e.g. `C00000010`) with no persisted key
back to the harmonised parcel or building it concerns — clustering happens before ULPIN
minting (`stage_cluster` precedes `stage_resolve` and `stage_assemble`). What *is* published,
in the same CRS as every harmonised feature, is the case's own disputed boundary
(`adjudication_queue.geojson`). `link_adjudication_case` finds the nearest such boundary by
real centroid distance (`haversine_m`) and returns a match only inside a disclosed 30 m
threshold — chosen because the statutory rule that escalates a case (R-GEO-01) only fires
past 10 m of disagreement, so a genuine match can legitimately sit that far from a record's
own resolved centroid. Every linked case in the response carries a `matched_by` string
stating the real distance and that this is a **derived** spatial join, never presented as an
identity lookup. Verified against real data: two independent buildings in `out/ms_proof`
matched their true escalated case at a **measured 0.00 m** — Dempster-Shafer geometry fusion
always emits one source's real boundary verbatim (`conflict/evidence.py::fuse_geometry`),
never an average, so an exact match is the expected outcome for a correctly-linked case, not
a coincidence.

Where no case can be linked within threshold despite a nonzero `conflicts` count, the
response says so (`"most likely auto-resolved by statutory rule or evidence fusion rather
than escalated to human review"`) instead of omitting the field or inventing a case.

---

## 3. Temporal Land Intelligence

**What it is.** A chronological trail for a parcel, built from three real signal types:

1. **Source observations** — each contributing dataset's real vintage
   (`pipeline.harmonise._parse_vintage`, the same function the pipeline itself uses to turn
   `LayerSpec.vintage` into a claim's `observed_on`), so an event date always matches what the
   pipeline itself would have recorded for that claim.
2. **Pipeline stage timestamps** — real entries from `store.ledger.history(dataset_id)`, the
   same hash-chained ledger `/api/lineage` reads.
3. **Linked change-detection records** — `changes.json` entries whose `entity_id` matches a
   raw identifier still carried on the harmonised record (see below).

**Why change events carry no date.** Change detection runs source-to-source
(`ChangeDetector`, `mode="cross_source"`) before ULPIN minting, and a `ChangeRecord` has no
independent observation timestamp of its own beyond the two source vintages already listed
separately as source-observation events. Rather than assign a change event today's date, or
average the two source dates, the timeline lists it undated, after the dated events, with a
disclosure note explaining why — the project's established "say so rather than fabricate"
convention (see the honest-zero patterns throughout `web-gis/src/app/page.tsx` and
`docs/09-roadmap.md`).

**The identifier-linkage problem, and how it's solved.** `ChangeRecord.entity_id` is the raw
identifier of one side's *source* feature (verified against real data: a GCC building's own
`door_number`, e.g. `"G-086-23-00578"`, is exactly what a linked change record's `entity_id`
equals), not the harmonised `entity_id`/`ulpin` — because change detection, like matching,
runs before ULPIN minting. `link_changes` recovers the connection generically: it collects
every string/int property value already present on the harmonised record (which includes
door numbers and any other raw passthrough attribute a schema crosswalk didn't rename) and
matches a change record's `entity_id` against that set exactly. No fuzzy matching, no
fabricated confidence in the link — either the identifier is there or it isn't, and when it
isn't, the timeline (and the evidence endpoint's `change_evidence`) say so explicitly.

**Honest unavailability.** If a parcel has no dataset with a parseable vintage, no ledger
entry, and no linkable change record, `parcel_timeline` returns
`{"available": false, "reason": "..."}` rather than an empty-but-technically-successful event
list that could be mistaken for "nothing happened."

---

## Frontend integration

All three views are added to the existing "Telemetry" tab of the right-hand sidebar
(`web-gis/src/app/page.tsx`, the `rightPanelTab === 'parcel'` branch) — the panel that
already renders when a parcel is selected on the map or from the ward list. Nothing about the
map, the 2D/3D or MAP/SAT toggles, layer controls, navigation, or any other tab was touched.
The three new sections are inserted as three additional cards, immediately after the existing
"Parcel Harmonization Evidence" card and before the "Launch In-App FMB CAD Studio" button,
using the identical visual idiom already established there (`border: 1px solid #1a4480`
outer box, `#1a4480` dark-navy uppercase header bar, `#f4f6f9`/`#f8f9fa` body, the existing
CSS variable palette) — no new colours, fonts, or component library.

A single `useEffect` keyed on `selectedParcel.ulpin` fetches all three endpoints in parallel
the moment a parcel is selected, following the same inline-`fetch`-to-`127.0.0.1:8000`
pattern every other call in this file already uses, and discards a response if the user
selects a different parcel (or clears the selection) before it lands — the same class of
race the existing `updateMapDataToken` guards against at the ward level, applied here at the
single-parcel scope.

---

## Tests

`tests/test_twin.py` exercises `api/twin.py`'s pure functions directly against fixtures whose
field values are copied verbatim from a real published run (`out/ms_proof/`) — including the
exact geometry that makes the adjudication-linkage test recover a real, specific escalated
case rather than an invented one — following this repo's existing convention
(`test_pipeline_units.py`) of testing real-shaped small objects rather than loading a
multi-hundred-megabyte corpus per test run. Twelve tests cover: dataset/building linkage and
role attribution, unknown-identifier 404 behaviour, exact reconstruction of a record's stored
confidence composite, successful and unsuccessful adjudication-case linkage (both are
asserted, since "correctly reports no link" is as important a behaviour as "correctly finds
one"), raw-identifier change linkage (including a negative case), registry-derived source
reliability ordering, and both the available and honestly-unavailable timeline paths.

The full pipeline output was additionally exercised end-to-end: all three endpoints were
called through `FastAPI TestClient` and through a live `uvicorn` process against both the
small `out/ms_proof` run and the full `out/chennai_metro` run (218k parcels, 1.4M buildings;
each endpoint responded in under 300 ms), and the existing Playwright suite
(`web-gis/e2e/app.spec.ts`) — which drives the real browser against the real backend, with no
mocking — was run in full afterwards: the two tests that exercise the exact tab these
features were added to (parcel selection opening a populated dossier; tab switching between
Court Cases/Dossier/Telemetry) passed, and the full existing backend suite (96 tests before
this work, 108 after) shows no regression.

## What this does not claim

- Per-source-feature (claim-level) provenance below the dataset level — not persisted by any
  pipeline stage today; see `db/store.py`'s own scope disclosure.
- A guaranteed link from every conflicted record to its adjudication case — only a
  geometrically-close one within a stated, disclosed threshold.
- A continuous bitemporal survey history — `harmonised_parcel.valid_from/valid_to` exist in
  `db/schema.sql` but are not populated by the file-backed pipeline output this reference
  deployment runs; the timeline is a provenance trail (what fed this record, when it was
  processed, what was detected as changed), not a version-controlled parcel history.
