# Access Context Join Findings

## Bounded Question

Attach access-point context to the stable roadway-derived directional bin/crash universe without changing scaffold, catchments, assignment, readiness, or upstream/downstream labels.

## Files Created

- `work\output\roadway_graph\review\current\access_context_join\access_context_join_summary.csv`
- `work\output\roadway_graph\review\current\access_context_join\directional_bin_access_context.csv`
- `work\output\roadway_graph\review\current\access_context_join\directional_bin_access_context_0_1000ft.csv`
- `work\output\roadway_graph\review\current\access_context_join\directional_bin_access_context_1000_2500ft.csv`
- `work\output\roadway_graph\review\current\access_context_join\directional_crash_access_context.csv`
- `work\output\roadway_graph\review\current\access_context_join\reference_signal_access_context_summary.csv`
- `work\output\roadway_graph\review\current\access_context_join\access_points_joined_to_stable_universe.csv`
- `work\output\roadway_graph\review\current\access_context_join\access_points_ambiguous_bin_matches.csv`
- `work\output\roadway_graph\review\current\access_context_join\access_points_unmatched_or_outside_stable_universe.csv`
- `work\output\roadway_graph\review\current\access_context_join\access_context_by_signal_relative_direction.csv`
- `work\output\roadway_graph\review\current\access_context_join\access_context_by_distance_window.csv`
- `work\output\roadway_graph\review\current\access_context_join\access_context_by_access_category.csv`
- `work\output\roadway_graph\review\current\access_context_join\access_context_join_qa.csv`
- `work\output\roadway_graph\review\current\access_context_join\access_context_join_findings.md`
- `work\output\roadway_graph\review\current\access_context_join\access_context_join_manifest.json`

## Method Boundaries

- crash direction fields read or used: False
- access direction used for upstream/downstream: False
- scaffold/catchment/assignment/readiness logic changed: False
- speed or AADT joined: False
- main context universe: usable catchment-backed bins with midpoint <= 2,500 ft

## Readout

- access features considered: 70595
- access features matched to at least one stable bin: 3040
- ambiguous access matches: 251
- unmatched access features: 67555
- bins with access within catchment: 3262
- bins with access within 100 ft: 4578
- bins with access within 250 ft: 4771
- crashes inheriting access context: 13216
- reference signals with access context rows: 971

## QA

- QA checks passed: 14 of 14

## Recommended Next Step

Review access-context QA and spot-check ambiguous access matches before promoting a downstream descriptive summary. Speed context should remain blocked until a posted-speed source is recovered or restaged.
