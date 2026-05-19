# Crash Directional Catchment Assignment QA

## Bounded Question

Read-only QA for crash-to-directional-catchment assignment outputs. This remains assignment-only and is not final crash analysis.

## QA Invariants

- Crash direction fields read or used: False
- Scaffold/catchment/assignment logic changed: False
- Assigned divided + undivided equals unique: True
- Assigned downstream + upstream equals unique: True
- Non-usable catchments in assignments: 0
- Ambiguous rows included in unique assignments: 0
- Unresolved rows included in unique assignments: 0

## Assignment Counts

- Total unique assignments: 17634
- Downstream: 8791
- Upstream: 8843
- Divided physical: 4967
- Undivided pseudo-direction: 12667
- Ambiguous: 1055
- Unresolved: 360583

## Top Reference Signals

- signal_001481: 223
- signal_002327: 203
- signal_001814: 188
- signal_001625: 149
- signal_003820: 149
- signal_002380: 121
- signal_000308: 113
- signal_001840: 113
- signal_001414: 111
- signal_002663: 109

## Top Ambiguous Reference Signals

- signal_001389: 52
- signal_002505: 45
- signal_003823: 42
- signal_003833: 42
- signal_003832: 41
- signal_003831: 40
- signal_001807: 33
- signal_002506: 32
- signal_001390: 31
- signal_001432: 28

## Distance Pattern

- 0000_to_0250ft: 3527
- 0500_to_1000ft: 3403
- over_5000ft: 2513
- 0250_to_0500ft: 2240
- 1500_to_2500ft: 2071
- 1000_to_1500ft: 1975
- 2500_to_5000ft: 1905

## Ambiguity Pattern

- candidate_catchment_count: 2 = 1040
- candidate_catchment_count: 4 = 13
- candidate_catchment_count: 3 = 2
- signal_relative_direction_set: downstream_of_reference_signal|upstream_of_reference_signal = 833
- signal_relative_direction_set: downstream_of_reference_signal = 120
- signal_relative_direction_set: upstream_of_reference_signal = 102
- reference_signal_scope: multiple_reference_signals = 662
- reference_signal_scope: same_reference_signal = 393
- bin_scope: same_bin = 474
- bin_scope: adjacent_bins = 359
- bin_scope: multiple_nonadjacent_bins = 222

## CRS QA

Catchment GeoJSON CRS `EPSG:3968` has projected-looking coordinate ranges: True; shared CRS handling: `catchment_crs_matches_authoritative_metadata`.
