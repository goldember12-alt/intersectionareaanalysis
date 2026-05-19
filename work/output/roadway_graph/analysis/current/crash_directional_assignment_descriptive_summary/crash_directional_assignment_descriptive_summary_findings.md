# Crash Directional Assignment Descriptive Summary Findings

## Bounded Question

Summarize readiness-gated, uniquely assigned roadway-derived directional crash assignments without reading crash direction fields or changing scaffold, catchment, assignment, or readiness logic.

## Files Read

- work\output\roadway_graph\review\current\crash_directional_assignment_analysis_readiness\crash_directional_assignment_readiness_by_crash.csv
- work\output\roadway_graph\review\current\crash_directional_assignment_analysis_readiness\crash_directional_assignment_readiness_summary.csv
- work\output\roadway_graph\review\current\crash_directional_assignment_analysis_readiness\assignments_by_functional_distance_window.csv
- work\output\roadway_graph\review\current\crash_directional_assignment_analysis_readiness\ambiguous_assignment_readiness_summary.csv
- work\output\roadway_graph\review\current\crash_directional_assignment_analysis_readiness\unresolved_assignment_readiness_summary.csv

## Files Created

- work\output\roadway_graph\analysis\current\crash_directional_assignment_descriptive_summary\directional_summary_core_0_500ft.csv
- work\output\roadway_graph\analysis\current\crash_directional_assignment_descriptive_summary\directional_summary_standard_0_1000ft.csv
- work\output\roadway_graph\analysis\current\crash_directional_assignment_descriptive_summary\directional_summary_extended_0_2500ft.csv
- work\output\roadway_graph\analysis\current\crash_directional_assignment_descriptive_summary\directional_summary_by_reference_signal.csv
- work\output\roadway_graph\analysis\current\crash_directional_assignment_descriptive_summary\directional_summary_by_signal_and_window.csv
- work\output\roadway_graph\analysis\current\crash_directional_assignment_descriptive_summary\directional_summary_by_bin_distance_band.csv
- work\output\roadway_graph\analysis\current\crash_directional_assignment_descriptive_summary\directional_summary_by_roadway_representation.csv
- work\output\roadway_graph\analysis\current\crash_directional_assignment_descriptive_summary\directional_summary_upstream_downstream_ratio.csv
- work\output\roadway_graph\analysis\current\crash_directional_assignment_descriptive_summary\directional_summary_top_reference_signals.csv
- work\output\roadway_graph\analysis\current\crash_directional_assignment_descriptive_summary\long_distance_review_summary.csv
- work\output\roadway_graph\analysis\current\crash_directional_assignment_descriptive_summary\ambiguity_and_unresolved_context_summary.csv
- work\output\roadway_graph\analysis\current\crash_directional_assignment_descriptive_summary\crash_directional_assignment_descriptive_summary_findings.md
- work\output\roadway_graph\analysis\current\crash_directional_assignment_descriptive_summary\crash_directional_assignment_descriptive_summary_manifest.json

## QA

- Crash direction fields read or used: False
- Assignment/scaffold/catchment/readiness logic changed: False
- Ambiguous and unresolved crashes included in unique-assignment summaries: False
- QA checks passed: 13 of 13

## Conservative Windows

- core_0_500ft: total 5767; downstream 2884 (0.500); upstream 2883 (0.500); divided 2234; undivided 3533; signals 783
- standard_0_1000ft: total 9170; downstream 4641 (0.506); upstream 4529 (0.494); divided 3619; undivided 5551; signals 829
- extended_0_2500ft: total 13216; downstream 6673 (0.505); upstream 6543 (0.495); divided 4840; undivided 8376; signals 859 (sensitivity only)

## Top Reference Signals By Core Assigned Crashes

- signal_002327: 96 core crashes; downstream 28; upstream 68
- signal_000378: 80 core crashes; downstream 37; upstream 43
- signal_001481: 65 core crashes; downstream 29; upstream 36
- signal_002295: 65 core crashes; downstream 29; upstream 36
- signal_001428: 58 core crashes; downstream 28; upstream 30
- signal_003853: 46 core crashes; downstream 18; upstream 28
- signal_001619: 46 core crashes; downstream 34; upstream 12
- signal_002189: 45 core crashes; downstream 36; upstream 9
- signal_003204: 36 core crashes; downstream 30; upstream 6
- signal_003835: 35 core crashes; downstream 9; upstream 26

## Extreme Upstream/Downstream Imbalance

- signal_002189: 45 core crashes; downstream 36; upstream 9; ratio 4.0
- signal_003204: 36 core crashes; downstream 30; upstream 6; ratio 5.0
- signal_001997: 30 core crashes; downstream 28; upstream 2; ratio 14.0
- signal_001958: 27 core crashes; downstream 24; upstream 3; ratio 8.0
- signal_003136: 25 core crashes; downstream 5; upstream 20; ratio 0.25
- signal_002171: 23 core crashes; downstream 4; upstream 19; ratio 0.210526
- signal_002464: 23 core crashes; downstream 22; upstream 1; ratio 22.0
- signal_003710: 20 core crashes; downstream 2; upstream 18; ratio 0.111111
- signal_001961: 19 core crashes; downstream 2; upstream 17; ratio 0.117647
- signal_003816: 19 core crashes; downstream 3; upstream 16; ratio 0.1875

## Long-Distance Review

- Rows over 2500 ft: 4418
- Rows over 5000 ft: 2513
- These rows remain assignment-only or review-focused and are not included in first descriptive conclusions.

## Ambiguous And Unresolved Context

- Ambiguous kept separate: 1055
- Unresolved kept separate: 360583
- Both groups are excluded from unique-assignment summaries.

## Interpretation

This remains a descriptive prototype. It is not policy-ready final analysis and does not estimate functional-area distances from crash findings.
