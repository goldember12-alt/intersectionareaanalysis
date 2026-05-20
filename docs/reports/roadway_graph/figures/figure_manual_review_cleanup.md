# Figure Manual Review Cleanup

**Status:** copied roadway-graph report figure cleanup only. Work/output report figures were preserved.

## Kept

- `11_aggregate_rate_by_direction.svg`
- `10_aggregate_rate_by_window.svg`
- `05_speed_context_coverage_by_distance.svg`
- `07_aadt_context_coverage_by_distance.svg`
- `09_crash_area_type_composition.svg`

## Revised

- `01_accepted_universe_summary.svg`: stakeholder-facing table labels now use Measure, Value, and Included universe / notes.
- `02_assigned_crashes_by_distance_and_direction.svg`: distance-band bars are stacked by roadway-graph signal-relative direction.
- `04_access_context_by_distance_and_direction.svg`: access context bars are stacked by roadway-graph signal-relative direction.
- `03_roadway_representation_by_distance.svg`: legend was moved above the chart area to avoid bar overlap.

## Removed / Archived

Moved to `archive/removed_after_manual_review/`:

- `ex03_upstream_downstream_assigned_crashes.svg`
- `ex04_window_summary.svg`
- `ex05_signal_review_priority_tiers.svg`
- `ex06_top_signal_review_queue.svg`
- `ex11_context_completeness_summary.svg`

## Created

- `06_speed_context_coverage_by_distance_and_direction.svg`
- `08_aadt_context_coverage_by_distance_and_direction.svg`

Supporting copied figure data was written under `figure_data/` in this folder.

## Docs / Index References

Updated copied report references in:

- `docs/reports/roadway_graph/roadway_graph_descriptive_report_draft.md`
- `docs/reports/roadway_graph/roadway_graph_figure_index.md`
- `docs/reports/roadway_graph/roadway_graph_figure_inventory_and_specs.md`
- `docs/reports/roadway_graph/roadway_graph_report_qa.md`
- `docs/reports/roadway_graph/README.md`

Removed stakeholder references to the archived upstream/downstream standalone, window summary, signal review, top review queue, and context completeness figures.

## QA

- No files under `work/output/roadway_graph/report/current/` were intentionally modified; `git status --short work/output/roadway_graph/report/current` was clean after cleanup.
- Crash direction fields were not read or used.
- No rows over 2,500 ft were used in regenerated copied figures.
- Rate methodology was not changed.
- `11_aggregate_rate_by_direction.svg` and `10_aggregate_rate_by_window.svg` remain in the copied package.
- New speed and AADT direction-by-distance coverage figures exist.
- Standalone upstream/downstream and signal review figures were archived.
- Context completeness summary was archived.
- Roadway representation legend was regenerated above the chart area.

## Remaining Manual Review Concerns

- The access context stacked figure uses summed `access_count_within_catchment` from accepted bins, matching the descriptive context field; it should remain descriptive and not be interpreted as a policy distance or access effect.
- The copied context relationship figures are now consolidated under `docs/reports/roadway_graph/figures/` with the other report SVGs.

