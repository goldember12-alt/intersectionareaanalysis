# Crash Directional Assignment Analysis Readiness

## Bounded Question

Classify uniquely assigned directional crashes into conservative analysis-readiness windows. This is assignment-only filtering and not final crash analysis.

## QA

- Crash direction fields read or used: False
- Assignment/scaffold/catchment logic changed: False
- Unique assignments classified: 17634
- Ambiguous kept separate: 1055
- Unresolved kept separate: 360583

## Window Counts

- core_0_500ft / 0_to_250ft: 3527
- standard_0_1000ft / 500_to_1000ft: 3403
- long_distance_review / over_5000ft: 2513
- core_0_500ft / 250_to_500ft: 2240
- extended_0_2500ft / 1500_to_2500ft: 2071
- extended_0_2500ft / 1000_to_1500ft: 1975
- assignment_valid_but_functional_relevance_uncertain / 2500_to_5000ft: 1905

## Downstream/Upstream By Window

- assignment_valid_but_functional_relevance_uncertain / 2500_to_5000ft: downstream 857, upstream 1048
- core_0_500ft / 0_to_250ft: downstream 1803, upstream 1724
- core_0_500ft / 250_to_500ft: downstream 1081, upstream 1159
- extended_0_2500ft / 1000_to_1500ft: downstream 1030, upstream 945
- extended_0_2500ft / 1500_to_2500ft: downstream 1002, upstream 1069
- long_distance_review / over_5000ft: downstream 1261, upstream 1252
- standard_0_1000ft / 500_to_1000ft: downstream 1757, upstream 1646

## Divided/Undivided By Window

- divided_physical_carriageway / core_0_500ft / 0_to_250ft: 1415
- divided_physical_carriageway / extended_0_2500ft / 1000_to_1500ft: 725
- divided_physical_carriageway / extended_0_2500ft / 1500_to_2500ft: 496
- divided_physical_carriageway / assignment_valid_but_functional_relevance_uncertain / 2500_to_5000ft: 99
- divided_physical_carriageway / core_0_500ft / 250_to_500ft: 819
- divided_physical_carriageway / standard_0_1000ft / 500_to_1000ft: 1385
- divided_physical_carriageway / long_distance_review / over_5000ft: 28
- undivided_centerline_pseudo_direction / core_0_500ft / 0_to_250ft: 2112
- undivided_centerline_pseudo_direction / extended_0_2500ft / 1000_to_1500ft: 1250
- undivided_centerline_pseudo_direction / extended_0_2500ft / 1500_to_2500ft: 1575
- undivided_centerline_pseudo_direction / assignment_valid_but_functional_relevance_uncertain / 2500_to_5000ft: 1806
- undivided_centerline_pseudo_direction / core_0_500ft / 250_to_500ft: 1421
- undivided_centerline_pseudo_direction / standard_0_1000ft / 500_to_1000ft: 2018
- undivided_centerline_pseudo_direction / long_distance_review / over_5000ft: 2485

## Long-Distance Review

- Over 5000 ft review rows: 2513
- signal_001814: 115
- signal_001625: 95
- signal_001840: 85
- signal_000056: 84
- signal_001223: 68
- signal_000409: 66
- signal_001348: 61
- signal_001662: 58
- signal_001216: 56
- signal_001626: 56
- signal_000308: 53
- signal_002453: 52
- signal_001872: 49
- signal_001775: 47
- signal_001358: 47
- signal_001309: 45
- signal_001879: 43
- signal_002551: 41
- signal_001841: 39
- signal_002351: 37

## Recommendation

The safest first descriptive upstream/downstream subset is `core_0_500ft` / `include_core_summary`, with `standard_0_1000ft` suitable as a next conservative summary and `extended_0_2500ft` reserved for sensitivity. Rows over 2500 ft should remain assignment-only or review-focused until functional relevance is reviewed.
