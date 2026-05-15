# Roadway Graph Directional Assignment Prototype Milestone

**Status: CURRENT MILESTONE.** This document freezes the current roadway_graph directional assignment prototype after the CRS/export fix. It is a reproducible, roadway-derived assignment milestone for bounded descriptive work. It is not policy-ready final crash analysis.

## Purpose And Scope

The bounded question for this milestone is:

- can the graph-first roadway_graph / Step 5 workflow assign crash points to a stable, roadway-derived signal-relative directional universe without using crash direction fields or crash distributions?

The answer is yes for the current prototype universe. Upstream/downstream is inherited from roadway-derived directional catchments. Crashes do not define the scaffold, do not alter catchments, and do not repair blocked records.

Analysis should remain bounded to assigned rows within 0-2,500 ft of the TRUE reference signal:

- `0-1,000 ft`: high-priority descriptive subset
- `1,000-2,500 ft`: sensitivity subset
- `>2,500 ft`: review-only / assignment-only

## What Was Built

The milestone consists of these direct-entry roadway_graph layers:

1. `reference_signal_directional_scaffold`
   - creates reference-signal-centered downstream/upstream directional records from TRUE reference signals to defensible far anchors.
   - creates accepted divided physical records where pairing supports them and undivided pseudo-direction records where the centerline is shared.
   - preserves unpaired/blocked divided and review-only cases separately.

2. `reference_signal_directional_scaffold_qa`
   - creates the conservative prototype usable directional surface.
   - excludes blocked divided records, low-confidence recovery rows, unknown-role rows, and review-only records.
   - validates ID uniqueness, pair symmetry, and bin ordering.

3. `reference_signal_directional_bin_catchments`
   - builds roadway-only directional catchment polygons for usable directional bins.
   - exports catchments in `EPSG:3968` (`NAD83 / Virginia Lambert`) with `directional_bin_catchment_crs_metadata.json` as the authoritative CRS sidecar.
   - uses only roadway geometry and does not read crash data.

4. `crash_directional_catchment_assignment_prototype`
   - assigns normalized crash points only when a point is contained by exactly one usable directional catchment.
   - keeps multiple usable matches as ambiguous and no usable match as unresolved.
   - reads only `DOCUMENT_NBR` and crash geometry from normalized crashes.

5. `crash_directional_catchment_assignment_qa`
   - checks unique assignments, downstream/upstream balance, divided/undivided patterns, ambiguity, unresolved counts, and CRS consistency.

6. `crash_directional_assignment_analysis_readiness`
   - classifies uniquely assigned crashes into conservative cumulative distance windows.
   - keeps ambiguous and unresolved rows separate.
   - keeps long-distance assignments review-only.

7. `crash_directional_assignment_descriptive_summary`
   - summarizes readiness-gated unique assignments by window, signal, bin distance band, roadway representation, and long-distance review status.
   - treats `extended_0_2500ft` as sensitivity only.

## Stable Universe Definition

The stable universe for this milestone is:

- TRUE reference signals that survive the roadway_graph Step 5 directional scaffold QA.
- Prototype usable directional records only.
- Prototype usable directional bins only.
- Catchments with `catchment_status = usable`.
- Crash points that fall inside exactly one usable directional catchment.
- Upstream/downstream inherited from `signal_relative_direction` on the matched catchment.

The stable universe excludes:

- ambiguous crash-to-catchment matches
- unresolved crashes
- blocked, unstable, review-only, low-confidence recovery, and unknown-role directional records
- crash direction fields
- crash-derived direction, scaffold repair, or catchment repair

## Key Counts

Current stable scaffold and catchment counts:

| Metric | Count |
| --- | ---: |
| prototype usable TRUE reference signals | 976 |
| prototype usable directional records | 4,828 |
| prototype usable directional bins | 208,340 |
| catchments created | 208,340 |
| usable catchments | 200,061 |
| unstable/review catchments | 7,281 |
| blocked catchments | 998 |

Current crash assignment counts:

| Metric | Count |
| --- | ---: |
| normalized crash points considered | 379,272 |
| unique assigned crashes | 17,634 |
| ambiguous crashes kept separate | 1,055 |
| unresolved crashes kept separate | 360,583 |
| assigned downstream crashes | 8,791 |
| assigned upstream crashes | 8,843 |
| assigned divided physical crashes | 4,967 |
| assigned undivided pseudo-direction crashes | 12,667 |

Current readiness windows:

| Window | Count | Interpretation |
| --- | ---: | --- |
| `core_0_500ft` | 5,767 | safest first descriptive subset |
| `standard_0_1000ft` | 9,170 | high-priority descriptive subset |
| `extended_0_2500ft` | 13,216 | cumulative sensitivity ceiling |
| 1,000-2,500 ft sensitivity increment | 4,046 | sensitivity only |
| over 5,000 ft | 2,513 | long-distance review only |

The high-priority descriptive subset is 0-1,000 ft. The 1,000-2,500 ft increment is sensitivity only. Rows over 2,500 ft should remain review-only or assignment-only until functional relevance is reviewed.

## Methodological Boundaries

This milestone does not:

- use crash direction fields
- use crash distributions
- build or alter the scaffold from crashes
- repair catchments from crash patterns
- include blocked, unstable, or review-only directional records in assignment
- include ambiguous or unresolved crashes in unique-assignment summaries
- recover blocked divided records
- force divided pairs
- join access, speed, AADT, median, or other context
- make policy-ready downstream functional-area claims

Crash findings remain descriptive safety evidence only. They are not the sole basis for functional-area distance calculation.

## Known Limitations

Known unresolved limitations:

- blocked and unpaired divided directional records are preserved outside the usable assignment surface
- ambiguous crash matches remain separate and are not resolved by nearest-distance or tie-break rules
- unresolved crashes remain separate and should not be interpreted as absence of downstream relevance
- long-distance assignments over 2,500 ft are assignment-valid but not functionally accepted for descriptive conclusions
- access point context is not yet joined to the stable signal/crash universe
- speed, AADT, median, and roadway context are not yet joined to this directional assignment universe
- this remains a prototype descriptive layer, not a modeling-ready or policy-ready analysis table

## Recommended Next Phase

Before adding new context layers, review the proposal/design docs and define the context enrichment architecture for this stable universe.

Recommended next phase:

1. Review proposal and design docs for context variables and output units.
2. Define the context enrichment architecture around the stable signal/crash universe, not around legacy signal-centered outputs.
3. Add access point context to the stable signal/catchment/crash universe.
4. Add posted speed context to the same universe.
5. Preserve the same boundary rules: no crash direction, no crash-derived scaffold changes, no blocked records, and no policy-ready claims.

The first context outputs should remain descriptive and bounded to the 0-1,000 ft high-priority subset plus 1,000-2,500 ft sensitivity.

## Reproducibility

Run from the repository root with the bootstrap-reported Python interpreter:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph
<bootstrap-reported-python> -m src.active.roadway_graph.geometric_direction
<bootstrap-reported-python> -m src.active.roadway_graph.divided_carriageway_pairing
<bootstrap-reported-python> -m src.active.roadway_graph.roadway_role_classification
<bootstrap-reported-python> -m src.active.roadway_graph.divided_pairing_recovery
<bootstrap-reported-python> -m src.active.roadway_graph.reference_signal_directional_scaffold
<bootstrap-reported-python> -m src.active.roadway_graph.reference_signal_directional_scaffold_qa
<bootstrap-reported-python> -m src.active.roadway_graph.reference_signal_directional_bin_catchments
<bootstrap-reported-python> -m src.active.roadway_graph.crash_directional_catchment_assignment_prototype
<bootstrap-reported-python> -m src.active.roadway_graph.crash_directional_catchment_assignment_qa
<bootstrap-reported-python> -m src.active.roadway_graph.undivided_catchment_assignment_failure_diagnostic
<bootstrap-reported-python> -m src.active.roadway_graph.crash_directional_assignment_analysis_readiness
<bootstrap-reported-python> -m src.active.roadway_graph.crash_directional_assignment_descriptive_summary
```

The active CRS convention for this milestone is `EPSG:3968` (`NAD83 / Virginia Lambert`) with metre coordinates. Directional catchment GeoJSON outputs carry this CRS, and downstream modules also read the catchment CRS metadata sidecar.

## Manual Git Commands

Do not stage or commit automatically. Review the working tree first:

```powershell
git status
git diff -- docs/workflow/roadway_graph_directional_assignment_milestone.md docs/workflow/current_workflow_index.md docs/workflow/active_workflow.md docs/workflow/roadway_graph_workflow.md
git diff -- src/active/roadway_graph/crs_utils.py src/active/roadway_graph/reference_signal_directional_bin_catchments.py src/active/roadway_graph/crash_directional_catchment_assignment_prototype.py src/active/roadway_graph/crash_directional_catchment_assignment_qa.py src/active/roadway_graph/undivided_catchment_assignment_failure_diagnostic.py
```

Stage edited source and docs:

```powershell
git add docs/workflow/roadway_graph_directional_assignment_milestone.md
git add docs/workflow/current_workflow_index.md docs/workflow/active_workflow.md docs/workflow/roadway_graph_workflow.md
git add src/active/roadway_graph/crs_utils.py
git add src/active/roadway_graph/reference_signal_directional_bin_catchments.py
git add src/active/roadway_graph/crash_directional_catchment_assignment_prototype.py
git add src/active/roadway_graph/crash_directional_catchment_assignment_qa.py
git add src/active/roadway_graph/undivided_catchment_assignment_failure_diagnostic.py
git add src/active/roadway_graph/crash_directional_assignment_descriptive_summary.py
```

If regenerated manifests/findings are tracked or should be preserved for this milestone, stage only the current review/readout artifacts that document methodology and QA:

```powershell
git add work/output/roadway_graph/review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_crs_metadata.json
git add work/output/roadway_graph/review/current/reference_signal_directional_bin_catchments/catchment_crs_coordinate_sanity.csv
git add work/output/roadway_graph/review/current/reference_signal_directional_bin_catchments/reference_signal_directional_bin_catchments_findings.md
git add work/output/roadway_graph/review/current/reference_signal_directional_bin_catchments/reference_signal_directional_bin_catchments_manifest.json
git add work/output/roadway_graph/review/current/crash_directional_catchment_assignment_prototype/crash_directional_assignment_crs_sanity.csv
git add work/output/roadway_graph/review/current/crash_directional_catchment_assignment_prototype/crash_directional_catchment_assignment_findings.md
git add work/output/roadway_graph/review/current/crash_directional_catchment_assignment_prototype/crash_directional_catchment_assignment_manifest.json
git add work/output/roadway_graph/review/current/crash_directional_catchment_assignment_qa/assignment_crs_sanity_qa.csv
git add work/output/roadway_graph/review/current/crash_directional_catchment_assignment_qa/crash_directional_assignment_qa_findings.md
git add work/output/roadway_graph/review/current/crash_directional_catchment_assignment_qa/crash_directional_assignment_qa_manifest.json
git add work/output/roadway_graph/review/current/undivided_catchment_assignment_failure_diagnostic/catchment_crs_coordinate_sanity.csv
git add work/output/roadway_graph/review/current/undivided_catchment_assignment_failure_diagnostic/undivided_catchment_failure_findings.md
git add work/output/roadway_graph/review/current/undivided_catchment_assignment_failure_diagnostic/undivided_catchment_failure_manifest.json
git add work/output/roadway_graph/review/current/crash_directional_assignment_analysis_readiness/crash_directional_assignment_readiness_findings.md
git add work/output/roadway_graph/review/current/crash_directional_assignment_analysis_readiness/crash_directional_assignment_readiness_manifest.json
git add work/output/roadway_graph/analysis/current/crash_directional_assignment_descriptive_summary/crash_directional_assignment_descriptive_summary_findings.md
git add work/output/roadway_graph/analysis/current/crash_directional_assignment_descriptive_summary/crash_directional_assignment_descriptive_summary_manifest.json
```

Check staged scope:

```powershell
git status --short
git diff --cached --stat
git diff --cached -- docs/workflow/roadway_graph_directional_assignment_milestone.md
```

Suggested commit message:

```powershell
git commit -m "Document roadway graph directional assignment milestone"
```
