# Roadway Graph Step 5 Eligibility Gating

**Status: CURRENT ACTIVE.** This is part of the current roadway_graph / Step 5 graph-first workflow.

## Bounded Question

This gating layer answers one pre-Step 5 question:

- which roadway graph signals and edges are source-sufficient enough to be eligible, conditionally eligible, or excluded from future Step 5 oriented segment work?

It does not read crash data, assign crashes, infer true vehicle direction, implement Step 5 oriented segments, modify old signal-centered crash/access modules, or fabricate missing Travelway geometries.

## Inputs

The gate is built during:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph
```

It uses only roadway graph outputs and the manual roadway graph diagnosis when present:

- normalized Travelway roads
- normalized signals
- graph adjacency and graph gap outputs created by `src.active.roadway_graph`
- `work/output/roadway_graph/review/current/manual_review_signal_classification.csv`

Crash data is not an input.

## Output Contract

Current table outputs:

- `work/output/roadway_graph/tables/current/signal_step5_eligibility.csv`
- `work/output/roadway_graph/tables/current/roadway_graph_edges_eligible.csv`

Current review outputs:

- `work/output/roadway_graph/review/current/step5_eligibility_summary.csv`
- `work/output/roadway_graph/review/current/step5_excluded_signals.csv`
- `work/output/roadway_graph/review/current/step5_candidate_signals.csv`

Current GeoJSON review outputs:

- `work/output/roadway_graph/review/geojson/current/step5_candidate_signals.geojson`
- `work/output/roadway_graph/review/geojson/current/step5_excluded_signals.geojson`
- `work/output/roadway_graph/review/geojson/current/step5_candidate_edges.geojson`

## Eligibility Status Values

`usable_for_step5` is a gate status:

- `TRUE`: usable as a future Step 5 input candidate under the current graph evidence
- `CONDITIONAL`: visible candidate only after manual review or graph-rule improvement
- `FALSE`: excluded from Step 5 by default

Future Step 5 implementation should consume only `TRUE` by default. Any use of `CONDITIONAL` rows must be explicit and documented.

## Signal Rules

The signal gate applies these rules:

- zero-edge and one-edge signals are `FALSE` by default unless manually promoted
- two-edge signals are `CONDITIONAL` unless review confirms a valid two-legged or one-roadway case
- signals manually classified as `source_roadway_incomplete` are `FALSE`
- signals with bad or questionable signal location are `FALSE` unless manually corrected or promoted
- signals with edge termination issues are `CONDITIONAL` until termination logic is fixed
- signals with more than four adjacent edges are `CONDITIONAL` pending review
- graph gap/count review flags make otherwise usable signals `CONDITIONAL`

The gate does not remove excluded records. Exclusions stay visible with `step5_exclusion_reason`, `requires_manual_review`, and notes.

## Edge Rules

The edge gate derives:

- `roadway_directionality_type` from source roadway division status only: `divided`, `undivided`, or `unknown`
- `edge_termination_anchor_type` from current graph endpoint node types
- `edge_termination_status` from the current endpoint anchor type
- `intermediate_intersection_crossed_flag = UNKNOWN` because the current graph has not yet implemented first-valid-anchor termination checks

An edge is:

- `TRUE` if at least one adjacent signal is `TRUE`
- `CONDITIONAL` if no adjacent signal is `TRUE` but at least one adjacent signal is `CONDITIONAL`
- `FALSE` if no adjacent signal is eligible or conditionally eligible

This is intentionally conservative. Edge eligibility is not a claim of true travel direction or final termination correctness.

## Current Run Readout

The current run produced:

| Gate result | Signals |
| --- | ---: |
| `TRUE` | 1,185 |
| `CONDITIONAL` | 2,660 |
| `FALSE` | 88 |

Main signal exclusion or review reasons:

| Reason | Signals |
| --- | ---: |
| `high_adjacent_edge_count_review_required` | 2,280 |
| blank / eligible | 1,185 |
| `two_edge_suspect_review_required` | 347 |
| `adjacent_leg_count_zero` | 63 |
| `graph_gap_review_required` | 29 |
| `source_roadway_incomplete` | 24 |
| `edge_termination_rule_unresolved` | 4 |
| `signal_location_questionable` | 1 |

Edge gate counts:

| Gate result | Edges |
| --- | ---: |
| `TRUE` | 4,132 |
| `CONDITIONAL` | 13,226 |
| `FALSE` | 16 |

These counts are descriptive gate counts, not model-ready sample counts.

## Validation Performed

Validation performed for this implementation:

- required output files were written under the roadway graph current table, review, and GeoJSON folders
- required fields are present in `signal_step5_eligibility.csv`
- required fields are present in `roadway_graph_edges_eligible.csv`
- signal eligibility counts reconcile to 3,933 normalized signal rows
- all manually diagnosed `source_roadway_incomplete` signals are excluded
- manual edge-termination examples are conditional, not fully eligible
- `src/active/roadway_graph/builder.py` compiles with the bootstrap-reported interpreter

Not validated yet:

- first-valid-anchor termination logic
- intermediate non-signalized intersection crossing detection
- manual promotion workflow
- any crash, access, or true-direction assignment

## Step 5 Boundary

This gate creates a defensible Step 5 input universe. It does not implement Step 5. Future Step 5 work should start from `signal_step5_eligibility.csv` and refuse `FALSE` rows by default.

The current gate keeps `CONDITIONAL` rows visible because many cases may become usable after a specific graph-rule improvement, source correction, or manual promotion. That visibility should not be interpreted as readiness.
