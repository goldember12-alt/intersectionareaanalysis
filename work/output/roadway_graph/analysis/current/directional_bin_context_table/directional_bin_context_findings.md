# Directional Bin Context Table Findings

## Bounded Question

Assemble the read-only 0-2,500 ft directional-bin context universe from accepted crash, access, speed v4, AADT v3, roadway urban/rural source recovery, and crash-level AREA_TYPE context without changing source context joins or upstream/downstream interpretation.

## Roadway Urban/Rural Source Decision

- decision: source_not_found
- method: include null urban/rural fields and urban_rural_context_status=source_not_found in combined table; add Census urban area, VDOT classification, or another documented roadway/area source later
- source recovery defensible roadway-level sources: 0
- roadway-level urban/rural source was not found.
- roadway_urban_rural_class is null and roadway_urban_rural_context_status is source_not_found.
- crash AREA_TYPE was not used as roadway-level urban/rural truth.

## Crash-Level AREA_TYPE Context

- crash AREA_TYPE values found: Rural | Urban
- assigned crashes with AREA_TYPE: 13216
- assigned urban crashes: 11915
- assigned rural crashes: 1301
- assigned unknown area type crashes: 0
- bins with urban/rural crash summaries: 8552
- signals with urban/rural crash summaries: 859
- crash AREA_TYPE was used only for assigned crash context and assigned-crash summary counts.
- no-crash bins were not populated with crash AREA_TYPE-derived urban/rural values.

## Key Counts

- total bins: 110710
- 0-1,000 ft bins: 66074
- 1,000-2,500 ft bins: 44636
- bins with assigned crashes: 8552
- bins with access context: 110710
- bins with stable speed context: 84857
- bins with stable AADT context: 106210
- bins with roadway urban/rural context: 0
- bins with complete core context: 0
- crashes represented: 13216
- reference signals represented: 971

## Context Limitations

- Roadway-level urban/rural context is not populated because no defensible roadway-level source was found.
- Crash AREA_TYPE cannot populate no-crash bins and is not a roadway-level policy variable.
- Speed review/missing statuses are preserved; only stable speed statuses should be used as usable speed context.
- AADT review/missing statuses are preserved; only stable route-measure AADT statuses should be used as usable AADT context.
- The table is ready as a prototype descriptive analysis universe, not a modeling-ready or policy-claim table.

## Files Created

- `work\output\roadway_graph\analysis\current\directional_bin_context_table\directional_bin_context.csv`
- `work\output\roadway_graph\analysis\current\directional_bin_context_table\directional_bin_context_0_1000ft.csv`
- `work\output\roadway_graph\analysis\current\directional_bin_context_table\directional_bin_context_1000_2500ft.csv`
- `work\output\roadway_graph\analysis\current\directional_bin_context_table\directional_crash_context.csv`
- `work\output\roadway_graph\analysis\current\directional_bin_context_table\reference_signal_context_summary.csv`
- `work\output\roadway_graph\analysis\current\directional_bin_context_table\crash_area_type_context_summary.csv`
- `work\output\roadway_graph\analysis\current\directional_bin_context_table\crash_area_type_by_distance_window.csv`
- `work\output\roadway_graph\analysis\current\directional_bin_context_table\crash_area_type_by_signal_relative_direction.csv`
- `work\output\roadway_graph\analysis\current\directional_bin_context_table\crash_area_type_by_roadway_representation.csv`
- `work\output\roadway_graph\analysis\current\directional_bin_context_table\context_completeness_by_bin.csv`
- `work\output\roadway_graph\analysis\current\directional_bin_context_table\context_completeness_by_reference_signal.csv`
- `work\output\roadway_graph\analysis\current\directional_bin_context_table\context_completeness_by_distance_window.csv`
- `work\output\roadway_graph\analysis\current\directional_bin_context_table\context_completeness_by_signal_relative_direction.csv`
- `work\output\roadway_graph\analysis\current\directional_bin_context_table\combined_context_join_qa.csv`
- `work\output\roadway_graph\analysis\current\directional_bin_context_table\directional_bin_context_findings.md`
- `work\output\roadway_graph\analysis\current\directional_bin_context_table\directional_bin_context_manifest.json`
