# Directed Signal-Leg Workflow

## Bounded Problem

Build a road-network-first divided-road scaffold:

- signal nodes
- oriented signal-anchored roadway legs
- 50-foot bins along each oriented leg
- access anchors used as termini where no adjacent signal anchor exists
- QA tables and GeoJSON review layers

This workflow is separate from `upstream_downstream_prototype`, `high_confidence_upstream_downstream_analysis`, and `context_enrichment`. It does not read crash data, assign crashes, infer true vehicle travel direction, or change crash classification logic.

## Command

Use the bootstrap-reported interpreter:

```powershell
<bootstrap-reported-python> -m src.active.directed_segments
```

Optional arguments:

```powershell
<bootstrap-reported-python> -m src.active.directed_segments --run-label <label>
<bootstrap-reported-python> -m src.active.directed_segments --study-slice-root work/output/stage1b_study_slice
<bootstrap-reported-python> -m src.active.directed_segments --normalized-root artifacts/normalized
<bootstrap-reported-python> -m src.active.directed_segments --output-root work/output/directed_segments
```

## Inputs

Required current inputs:

- `work/output/stage1b_study_slice/Study_Roads_Divided.parquet`
- `work/output/stage1b_study_slice/Study_Signals_NearestRoad.parquet`

Optional-but-used termination input:

- `artifacts/normalized/access.parquet`

The workflow uses road, signal, and access geometry in the project working CRS. It estimates each signal's position along the matched divided-road row, groups signals by route/carriageway, and creates oriented legs from each signal to nearby anchors.

## Orientation Rule

Orientation is only fixed anchor order:

- signal anchor to adjacent signal anchor by lower or higher route measure
- signal anchor to nearest same-route access point when no adjacent signal exists on that side
- signal anchor to road endpoint when no adjacent signal or access anchor exists on that side

`orientation_label`, `orientation_method`, and `qa_orientation_status` describe geometry ordering and QA status. They do not describe true vehicle travel direction. Crash data is not used for orientation inference or validation.

## Current Output Contract

Root:

- `work/output/directed_segments/`

Stable current tables:

- `tables/current/signal_nodes.csv`
- `tables/current/directed_signal_legs.csv`
- `tables/current/directed_signal_leg_bins_50ft.csv`
- `tables/current/rejected_or_unresolved_signal_legs.csv`
- `tables/current/orientation_review.csv`
- `tables/current/short_or_problem_legs.csv`
- `tables/current/anchor_summary.csv`
- `tables/current/signal_node_summary.csv`
- `tables/current/directed_signal_leg_summary.csv`

Stable current review layers:

- `review/geojson/current/signal_nodes.geojson`
- `review/geojson/current/directed_signal_legs.geojson`
- `review/geojson/current/directed_signal_leg_bins_50ft.geojson`
- `review/geojson/current/rejected_or_unresolved_signal_legs.geojson`
- `review/geojson/current/orientation_review.geojson`
- `review/geojson/current/access_anchors_used.geojson`

Run metadata and notes:

- `runs/current/run_summary.json`
- `review/current/superseded_signal_pair_outputs.txt`
- `README.md`

The workflow also writes timestamped history copies under:

- `tables/history/`
- `review/history/`
- `review/geojson/history/`
- `runs/history/`

The older signal-pair-only files may remain in `current/` as historical residue:

- `directed_signal_segments.*`
- `directed_segment_bins_50ft.*`
- `direction_conflict_review.*`
- `short_or_problem_segments.*`

Those files are superseded by the signal-leg outputs above.

## Current Run Baseline

The current signal-leg run on May 7, 2026 used:

- 16,495 divided-road rows
- 2,006 signal rows
- 70,595 access rows

It produced:

- 2,006 signal nodes
- 4,012 directed signal legs
- 2,816 `signal_to_signal` legs
- 106 `signal_to_access` legs
- 1,090 `signal_to_road_endpoint` support legs
- 555,503 directed 50-foot bin rows
- 106 access anchors used
- 0 rejected or unresolved signal-leg rows
- 1,408 short/problem leg rows
- 1,979 orientation review rows

Validation performed:

- input row counts
- output row counts
- signal-road match status counts
- leg-type and anchor-type counts
- 50-foot bin generation
- short/problem leg queue generation
- orientation review queue generation
- GeoJSON review layer export

Validation not yet performed:

- manual map spot checks
- comparison to an external roadway orientation source
- true vehicle travel direction review
- crash assignment or crash classification validation

