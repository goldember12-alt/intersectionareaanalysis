# Roadway Graph Divided and Undivided Directional Framework Audit

**Status: CURRENT ACTIVE.** This is a current roadway_graph result/readout summary retained under workflow for this pass.

## Bounded Question

This audit asks how Travelway and current roadway graph fields can support a better roadway role and directional framework for divided and undivided road records.

It does not modify builder logic, read crash records, assign crashes, infer direction from crashes, or revise divided-carriageway pairing.

The bounded design question is:

- using roadway source attributes and current roadway graph outputs only, what role classes and future geometric pairing recovery checks should govern divided, undivided, ramp, frontage, service, auxiliary, and one-way candidate rows?

## Inputs Reviewed

Roadway-only sources reviewed:

- `artifacts/normalized/roads.parquet`
- `work/output/roadway_graph/tables/current/roadway_graph_edges.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_roadway_segments_crash_ready.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_roadway_segments_divided_pairing_enriched.csv`
- `work/output/roadway_graph/tables/current/divided_carriageway_pair_candidates.csv`

The Step 5 segment file above is the no-crash roadway segment subset despite its historical filename. Crash records and crash-assignment outputs were not read.

Supporting tables were written to:

- `work/output/roadway_graph/review/current/roadway_role_framework_audit/`

## Supporting Tables

| Table | Purpose |
| --- | --- |
| `roadway_role_field_inventory.csv` | All normalized Travelway and graph-edge fields, grouped by likely role in roadway classification. |
| `key_field_distinct_summary.csv` | Compact distinct counts and top values for Travelway and graph-edge key fields. |
| `travelway_key_field_value_counts.csv` | Full value counts for key Travelway fields. |
| `roadway_graph_edge_key_field_value_counts.csv` | Full value counts for key current graph edge fields. |
| `divided_pairing_status_summary.csv` | Current paired/unpaired/not-applicable status counts. |
| `divided_pairing_crosstab_by_field.csv` | Paired/unpaired crosstabs by facility, median, route, type, access, and anchor fields. |
| `divided_unpaired_concentration_top_values.csv` | Top paired/unpaired concentration values by field. |
| `divided_pairing_top_route_concentrations.csv` | Top route-name, route-stem, route-common, and route-id concentrations. |
| `proposed_roadway_role_schema.csv` | Proposed roadway role class definitions. |
| `audit_input_and_metric_summary.csv` / `audit_pairing_metric_summary.csv` | Input and derived row-count checks. |

## Field Inventory Findings

Travelway contains enough roadway-source fields to separate role classification from later direction assignment. The useful field families are:

| Use | Fields |
| --- | --- |
| Road role and facility type | `RIM_FACILI`, `RIM_FACI_1`, `RTE_TYPE_N`, `RTE_CATEGO`, `RTE_RAMP_C`, `RIM_ACCESS`, `RIM_COUPLE`, `RIM_TRAVEL` |
| Divided and median status | `RIM_MEDIAN`, `RIM_MEDI_1` through `RIM_MEDI_9`, `MEDIAN_WID`, `MEDIAN_W_1`, `MEDIAN_COV`, `MEDIAN_IND`, `MEDIAN_OPP`, `PAVED_MDN_`, `PAVED_MDN1`, `UNPVD_MDN_`, `UNPVD_MDN1` |
| Lane and carriageway clues | `LANE_THRU_`, `LANE_THRU1`, `LANE_THR_1`, `LANE_REVER`, `LANE_THR_2` through `LANE_THR_4`, `PAVEMENT_W`, `PAVEMENT_1`, `THRU_TRVL_`, `THRU_TRVL1` |
| Shoulder and curb context | `RIM_SHOULD`, `RIM_SHOU_1` through `RIM_SHOU_3`, `PAVED_SHLD`, `PAVED_SH_1`, `UNPAVED_SH`, `UNPAVED__1`, `RIM_CURB_T`, `RIM_CURB_1` through `RIM_CURB_3` |
| Route identity | `RTE_NM`, `RTE_COMMON`, `RTE_ID`, `EVENT_SOUR`, `EVENT_SO_1`, `EVENT_SO_2` |
| Measure direction and linear referencing | `FROM_MEASURE`, `TO_MEASURE`, `RTE_FROM_M`, `RTE_TO_MSR`, `RTE_MEASUR`, `EVENT_LOCA`, `EVENT_COMP`, `LOCATION_V`, `LOCATION_C`, `LOCATION_1`, `LOC_COMP_D`, `LOC_COMP_1` |
| Status and review | `CURRENCY_D`, `RIM_REVIEW`, `LRM_CURREN`, `CHANGE_STA`, `CHANGE_S_1`, `Stage1_SourceGDB`, `Stage1_SourceLayer` |

Important interpretation: these fields can classify the roadway record role, but they do not by themselves establish true vehicle direction near a signal. Measure direction is source linear-reference direction and must stay separate from vehicle movement.

## Distinct Value Summary

Normalized Travelway roads:

| Field | Key counts |
| --- | --- |
| `RIM_FACILI` | 140,654 rows; 118,291 `3-Two-Way Undivided`; 16,468 `4-Two-Way Divided`; 5,843 `1-One-Way Undivided`; 27 `2-One-Way Divided`; 23 reversible; 2 trail. |
| `RIM_MEDIAN` | 124,057 no median/less than 4 ft; 8,999 curbed barrier; 6,287 grass median; 960 Jersey/guardrail; 280 painted median; 14 painted center turn lane. |
| `RTE_TYPE_N` | 103,682 secondary; 12,101 street; 10,936 U.S.; 9,746 state; 2,649 interstate; 926 frontage road. |
| `RTE_CATEGO` | 100,816 secondary; 11,119 urban streets; 9,761 US highway primary; 7,959 state highway primary; 2,809 interstate ramp; 1,908 non-interstate ramp; 503 non-interstate frontage road; 408 interstate frontage road. |
| `RTE_RAMP_C` | 135,759 blank; 2,907 `A`; 1,559 `B`; other ramp codes are much smaller. |
| `RIM_ACCESS` | 136,160 no limited access; 3,004 full access control; 1,490 partial access control. |
| `RIM_COUPLE` | 234 `Y`; this is a small but important one-way-pair/couplet signal. |
| `RTE_MEASUR` | 128,551 `OSM`; 12,103 `OUM`. |
| `RTE_NM` / `RTE_COMMON` / `RTE_ID` | High-cardinality route identity fields: 72,704 distinct `RTE_NM`, 74,025 distinct `RTE_COMMON`, and 74,025 distinct `RTE_ID`. Full counts are in the support tables. |
| `EVENT_SOUR` | 130,258 distinct source event identifiers; useful as lineage, not as a broad corridor grouping key. |

Current roadway graph edges:

| Field | Key counts |
| --- | --- |
| `facility_text` | 9,707 two-way divided; 6,828 two-way undivided; 817 one-way undivided; 10 one-way divided; 8 reversible; 4 trail. |
| `roadway_division_status` | 9,717 divided; 7,645 undivided; 12 unknown. |
| `logical_segment_mode` | 9,717 `divided_source_carriageway`; 7,645 `undivided_centerline_or_logical_segment`; 12 `unknown_review`. |
| `median_text` | 7,629 no median; 6,619 curbed barrier; 2,857 grass median; 130 Jersey/guardrail; 126 painted median; 8 painted center turn lane. |
| `rte_type_name` | 8,307 secondary; 4,039 U.S.; 3,665 state; 967 street; 265 interstate; 110 frontage road. |
| `rte_category` | 353 non-interstate ramp edges; 344 interstate ramp edges; 90 non-interstate frontage-road edges; 18 interstate frontage-road edges. These are role candidates that should be separated before divided-pairing recovery. |

## Paired and Unpaired Divided Rows

The corrected divided-pairing audit uses only rows where `divided_pairing_status` is `paired` or `unpaired`:

| Metric | Count |
| --- | ---: |
| Divided rows analyzed | 2,293 |
| Paired rows | 810 |
| Accepted pair candidate records | 405 |
| Unpaired rows | 1,483 |

All 2,293 rows have `facility_text = 4-Two-Way Divided`. The unpaired issue is therefore not explained by mixed facility values within the current pairing scope.

Median distribution is broad rather than isolated to a single median class:

| Median | Paired | Unpaired | Unpaired share |
| --- | ---: | ---: | ---: |
| Curbed barrier / mountable curb | 586 | 1,019 | 63.5% |
| Grass median | 218 | 392 | 64.3% |
| Painted median | 6 | 32 | 84.2% |
| Jersey barrier / guard rail | 0 | 4 | 100.0% |

The strongest concentration signal is route/type category:

| Type/category | Paired | Unpaired | Interpretation |
| --- | ---: | ---: | --- |
| `Secondary Route` / `Secondary` | 0 | 649 | Current pairing does not recover these divided rows. They are a major future review/recovery queue. |
| `Street Route` / `Urban Streets` | 0 | 109 | Same issue; likely includes urban divided boulevards, service/frontage-like facilities, or source representation differences. |
| `U.S. Route` / `US Highway Primary` | 456 | 382 | Pairing works materially better, but not completely. |
| `State Route` / `State Highway Primary` | 354 | 301 | Pairing works materially better, but not completely. |
| Partial access control | 41 | 226 | Higher unpaired share than private-access rows; likely includes limited-access edges, ramps, or unusual termini. |
| Full access control | 0 | 14 | Small but all unpaired; should be classified before pairing recovery. |

Top unpaired route concentrations include both normal primary corridors and local/secondary/street-coded corridors. Examples include `US-60E`, `US-1N`, `US-60W`, `US-460E`, `US-17N`, `VA-10E`, and `Big Bethel RD` variants. High unpaired counts are therefore not only a route-name parsing problem; they reflect a mixture of route-stem strictness, source class, endpoint scope, and side-score ambiguity.

## Interpretation of Unpaired Concentration

Unpaired divided rows are not concentrated in a questionable source facility class. They are all current `4-Two-Way Divided` rows.

They are moderately concentrated by:

- route type/category, especially secondary and street categories that are all unpaired in the current scope;
- access-control class, where partial/full access rows have higher unresolved shares;
- route identity, where some corridor families have no accepted pairs while others pair well;
- endpoint and reciprocal-scope conditions already diagnosed in the prior unresolved-pairing memo.

This points to a framework problem rather than a simple threshold problem. Recovery should first classify roadway role, then run pairing only for rows that are plausible mainline divided carriageways or reviewed one-way pair candidates.

## Proposed Roadway Role Schema

| Role | Primary evidence | Directional treatment |
| --- | --- | --- |
| `mainline_divided_carriageway` | Divided facility/median source fields plus compatible same-corridor geometry. Exclude ramps, frontage/service roads, and auxiliary lanes first. | Physical carriageway record. Can support later signal-relative direction only after pairing or another reviewed source of side/direction evidence. |
| `undivided_centerline` | Undivided facility/median status; no opposite bracketing carriageway; current logical centerline mode. | Logical centerline only. Later crash/event direction or side-of-centerline evidence is required for movement interpretation. |
| `ramp_or_connector` | `RTE_RAMP_C`, ramp categories, ramp/interchange route type/name, or connector geometry. | Connector class. Do not use as opposite divided carriageway unless a later bounded movement method is designed. |
| `frontage_or_service_road` | Frontage-road categories/type, service/access-road naming, parallel but separate route identity. | Separate road role. Parallelism to a mainline is not enough to pair as an opposite carriageway. |
| `turn_lane_or_auxiliary` | Center turn-lane median value, reversible/auxiliary/lane-specific fields, short intersection-adjacent component behavior. | Auxiliary context only by default; generally not a mainline directional scaffold. |
| `one_way_pair_candidate` | One-way facility, `RIM_COUPLE = Y`, reciprocal route suffixes, or parallel one-way couplet geometry. | Candidate logical pair, not automatically divided. Needs one-way-specific review and rules. |
| `unknown_review` | Missing, conflicting, or weak role evidence; source incomplete; geometry inconsistent. | No directional claim. Keep unresolved until reviewed. |

Recommended precedence:

1. Detect explicit ramps/connectors from `RTE_RAMP_C`, `RTE_CATEGO`, and `RTE_TYPE_N`.
2. Detect frontage/service roads before generic divided pairing.
3. Detect turn-lane/auxiliary records and reversible records.
4. Detect one-way pair candidates from `RIM_FACILI`, `RIM_COUPLE`, route suffixes, and parallel geometry.
5. Classify remaining divided rows as `mainline_divided_carriageway` candidates.
6. Classify remaining undivided rows as `undivided_centerline`.
7. Send conflicts to `unknown_review`.

## Proposed Pairing Recovery Strategy

Do not revise pairing yet. The future recovery strategy should be layered and reviewable:

### 1. Route-Stem Relaxation

Create normalized route stems from `RTE_NM` and `RTE_COMMON` that remove only direction suffixes and obvious business/alternate suffix variants under strict rules. Use route-stem relaxation as a candidate generator, not as acceptance evidence.

Guardrails:

- same reference signal or same local anchor cluster required;
- compatible `RTE_CATEGO` / `RTE_TYPE_N` role required;
- no ramp/frontage/service/auxiliary role unless explicitly reviewing that role;
- preserve original `RTE_ID` and `EVENT_SOUR` as lineage fields.

### 2. Anchor Clustering

Cluster local anchors around each reference signal by spatial proximity and route role. Treat a paired carriageway search as a local same-corridor problem, not a statewide route-id problem.

Useful cluster keys:

- `reference_signal_id`;
- route stem;
- anchor type and anchor id;
- opposite anchor type;
- source component id;
- local bearing band.

This should help distinguish valid opposite-carriageway candidates from nearby cross-streets and service roads.

### 3. Local Path-Based Side Scoring

Build a local reference path or axis for each signal/route-stem/anchor cluster. Score candidate carriageways by their side of that local path, not just by pairwise segment side scores.

The side score should require:

- opposite signs on the local axis;
- adequate lateral separation;
- stable side assignment along overlapping portions;
- no excessive crossing of the reference axis;
- no same-component/self-pair.

This is the likely remedy for ambiguous side-score rows.

### 4. Parallelism and Overlap Scoring

Score candidate pairs on geometry similarity:

- bearing similarity;
- overlapping projection range along the local axis;
- lateral distance band;
- comparable segment length or explainable endpoint truncation;
- continuous near-parallel behavior rather than a brief crossing.

Parallelism is support evidence only. It must be combined with role and anchor checks because frontage roads, ramps, and service roads can be parallel to mainlines.

### 5. Endpoint Classification

Before accepting a recovered pair, classify why each row ends:

- same signal boundary;
- valid non-signal roadway intersection boundary;
- non-TRUE signal boundary used only as a boundary;
- road endpoint/dead end;
- ramp/frontage/service merge/diverge;
- source-incomplete or missing-opposite-geometry case.

Endpoint classes should decide whether a missing reciprocal is acceptable, recoverable, or review-only. This prevents forced pairs where Travelway simply lacks the opposite geometry or where the row is a one-sided facility.

## Design Recommendation

The next implementation should not be a looser version of the current divided-pairing function. It should be a roadway-role pre-classification pass followed by role-specific candidate generation.

Recommended sequence:

1. Add a roadway-role audit/prototype table using existing Travelway and graph fields only.
2. Review route/type concentrations for secondary and street divided rows, because these dominate unpaired rows and currently have zero accepted pairs.
3. Build a route-stem candidate queue, not accepted recoveries.
4. Add local anchor clustering and path-based side scoring for the candidate queue.
5. Review mapped samples before promoting any new recovered pairing rules.

## Validation Status

Checked:

- normalized Travelway road count: 140,654 rows;
- current roadway graph edge count: 17,374 rows;
- no-crash Step 5 roadway segment count: 4,305 rows;
- divided pairing scope: 2,293 paired/unpaired rows;
- current paired/unpaired counts: 810 paired, 1,483 unpaired;
- distinct values and counts for requested key fields;
- paired/unpaired crosstabs by facility, median, route type/category, access class, route identity, and anchor/problem fields.

Not checked:

- crash data;
- crash assignment outputs;
- mapped QGIS spot checks of newly proposed role classes;
- correctness of any proposed recovered pair;
- builder logic behavior under a changed schema.

Remaining uncertainty:

- whether secondary and street divided unpaired rows are true divided mainline carriageways, frontage/service roads, local boulevards, one-way pair candidates, or source representation artifacts;
- whether route-stem relaxation introduces too many false candidates without role filtering;
- whether a local reference-axis method can resolve the ambiguous side-score group without manual calibration;
- whether some source Travelway rows need source-data repair rather than code recovery.

## Proposal Alignment

This supports the proposal-facing need for a stable roadway scaffold before crash/access/context evidence is attached. It remains roadway-only and descriptive. It does not create modeling-ready outputs, assign crashes, or claim downstream functional area guidance.
