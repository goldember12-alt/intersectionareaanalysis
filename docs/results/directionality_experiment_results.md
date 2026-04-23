# Divided-Road Empirical Flow-Orientation Results

## Bounded Question

This experiment asks whether filtered crash evidence is strong enough to support local carriageway flow orientation on divided roads near signals.

The experiment is a bounded support method for later signal-relative interpretation such as approaching versus leaving or upstream versus downstream. It is not a universal roadway-direction engine.

## Current output contract note

This note preserves a coherent historical run summary from the pre-grouped flat layout.

The current module now writes grouped outputs under `work/output/directionality_experiment/`:

- `README.md`
- `tables/current/`
- `tables/history/`
- `review/current/`
- `review/history/`
- `review/geojson/current/`
- `review/geojson/history/`
- `review/geopackage/current/`
- `review/geopackage/history/`
- `runs/current/`
- `runs/history/`

Use the grouped `current/` lanes for new reruns.
Use the historical flat suffixed file paths below only when reproducing the specific 2026-04-14 run summarized in this note.

## Run Summarized

This note summarizes the latest coherent expanded run recorded in:

- `work/output/directionality_experiment/run_summary_20260414_155808.json`

Use the suffixed output files listed in that manifest when reproducing counts. The output folder contains multiple runs, and unsuffixed files are not guaranteed to all come from the same run.

## Method Summary

- Crashes are attached to study-road rows by exact `RTE_NM` and non-overlapping measure windows.
- `StrictUnanimous` assigns only when at least 2 crashes remain after filtering to single-vehicle, straight-ahead crashes with one clear parsed `DIRECTION_OF_TRAVEL_CD`, and all qualifying crashes agree.
- `Empirical90Pct` uses the same filtered crash subset but allows assignment when one direction holds at least 90% of qualifying crashes.
- `SingleVehicleSupport` exposes the same clean filtered evidence as an explicit support readout; in this run it did not add coverage beyond `Empirical90Pct`.
- `RouteNameFallback` is support-only and activates only after `Empirical90Pct` stays unresolved.

## Sample Size

| Scope | Corridor windows | Study-road rows | Signals | Attached crashes | Parseable broad crash DOT | Qualifying filtered crashes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Initial seed | 3 | 6 | 15 | 210 | 115 | 17 |
| Expanded sample | 171 | 380 | 773 | 10,813 | 7,069 | 653 |

Only 653 of 10,813 attached crashes in the expanded sample, 6.0%, survive the strict single-vehicle straight-ahead filter. That low retention is expected because the method is intentionally conservative.

## Initial Seed Results

The original three-corridor seed behaved as a useful proof of concept rather than a broad-coverage solution.

| Corridor | Strict result | Numerically supported read |
| --- | --- | --- |
| Norfolk `R-VA   SR00337WB` | assigned | 1 of 1 rows assigned `South` from 4 of 4 qualifying crashes, while the route-suffix support read was `West` |
| Hampton `S-VA114PR BIG BETHEL RD` | unresolved | 0 of 1 rows assigned; 5 qualifying crashes split `North` 4 and `South` 1 |
| HMMS `R-VA029SC00620EB` | assigned with gaps | 3 of 4 rows assigned `East`; 1 row stayed unresolved because it had no qualifying crashes |

Seed totals:

- `StrictUnanimous` assigned 4 of 6 rows, 66.7%.
- `CrashDOTOnly` assigned 0 of 6 rows.
- `RoadwayContext` assigned 5 of 6 rows.
- The seed already showed one direct empirical-versus-context disagreement: Norfolk assigned `South` empirically while the route suffix indicated `West`.

## Expanded Sample Results

### Primary strict baseline

- `StrictUnanimous` assigned 56 of 380 rows, 14.7%.
- 324 rows, 85.3%, remained unresolved under the strict baseline.
- 44 of 171 corridor windows had at least one strictly assigned row.
- Only 15 corridor windows were `continuous_assigned`; 29 were `assigned_with_gaps`; 127 were fully unresolved.

Strict unresolved reasons were concentrated in weak evidence rather than impossible geometry:

- 175 rows, 46.1%, had no qualifying crashes.
- 95 rows, 25.0%, had fewer than 2 qualifying crashes.
- 54 rows, 14.2%, had qualifying crashes that disagreed on direction.

### Conflict structure

Filtered empirical conflict was real but usually soft rather than fully ambiguous:

- 54 rows, 14.2%, had strict internal conflict.
- 1 row, 0.3%, was a hard conflict.
- 53 rows, 13.9%, were soft conflicts.
- Soft conflict breakdown:
  - 4 rows at `>=90%` dominant share
  - 8 rows at `80-89%`
  - 5 rows at `70-79%`
  - 18 rows at `60-69%`
  - 18 rows at `50-59%`

### Variant comparison

| Rule | Assigned rows | Assigned rate | Newly assigned vs. strict |
| --- | ---: | ---: | ---: |
| `StrictUnanimous` | 56 | 14.7% | 0 |
| `Empirical90Pct` | 60 | 15.8% | 4 |
| `SingleVehicleSupport` | 60 | 15.8% | 4 |
| `RouteNameFallback` | 224 | 58.9% | 224 |

What changed:

- `Empirical90Pct` added 4 rows beyond the strict baseline.
- Those 4 new assignments came from the strongest soft-conflict cases, with dominant shares from 90.9% to 96.5%.
- `SingleVehicleSupport` did not add any rows beyond the same 4 already picked up by `Empirical90Pct`.
- 96 rows, 25.3%, still remained unresolved after all bounded variants.

### Comparison with simpler baselines

The experiment supports keeping filtered empirical evidence primary and roadway context secondary.

- `CrashDOTOnly` assigned 66 of 380 rows, 17.4%, but 263 rows, 69.2%, had broad crash-DOT conflict.
- `RoadwayContext` assigned 361 of 380 rows, 95.0%, but that coverage is not trustworthy enough to stand alone:
- 58 rows, 15.3%, showed direct disagreement between the empirical dominant direction and roadway-context direction.
- On the 56 strictly assigned rows, roadway context agreed on 48 rows, conflicted on 6, and was absent on 2.

Single-vehicle-clean evidence was still useful even when the broad crash-DOT read was noisy:

- 50 rows had broad crash-DOT conflict but a clean single-vehicle support readout.
- Only 4 of those 50 changed the strict result, which is why the clean subset is diagnostically useful but not a separate high-coverage solution by itself.
- The review memo's `single_vehicle_clean_rows` target list is 4 rows because it only keeps the strict-unresolved cases that need follow-up.

## Supported Conclusions

- Strict unanimity is trustworthy but sparse. It yields high-confidence assignments, but only 56 of 380 expanded rows.
- A 90% dominant-share relaxation is promising but bounded. It improved coverage by only 4 rows, which is enough to keep exploring but not enough to replace the strict baseline wholesale.
- Single-vehicle-clean cases are diagnostically useful. They explain why filtered evidence can outperform broad crash-DOT reads, but in this run they did not produce any assignments beyond `Empirical90Pct`.
- Route-name fallback improves coverage, not truthfulness. It assigned 224 rows, but 58 rows still showed empirical-versus-context disagreement, so fallback should remain support-only.
- Unresolved cases should stay unresolved. Most strict failures came from no evidence or too little evidence, not from a method that was almost certainly wrong.

## Recommended Interpretation for the Active Workflow

- Treat `StrictUnanimous` as the current highest-trust row-level assignment.
- Treat `Empirical90Pct` as the most defensible bounded relaxation for manual review and possible downstream use.
- Treat `SingleVehicleSupport` as a diagnostic lens, especially where broad crash-DOT evidence is noisy.
- Treat `RouteNameFallback` as support-only context, not final truth.

## Historical Source Files

- `work/output/directionality_experiment/run_summary_20260414_155808.json`
- `work/output/directionality_experiment/assignment_table_20260414_155752.csv`
- `work/output/directionality_experiment/evidence_summary_20260414_155752.csv`
- `work/output/directionality_experiment/expanded_assignment_table_20260414_155752.csv`
- `work/output/directionality_experiment/expanded_rule_comparison_summary_20260414_155752.csv`
- `work/output/directionality_experiment/expanded_rule_transition_summary_20260414_155752.csv`
- `work/output/directionality_experiment/expanded_conflict_profile_summary_20260414_155752.csv`
- `work/output/directionality_experiment/expanded_review_support_bucket_summary_20260414_155752.csv`
- `work/output/directionality_experiment/review_support_summary_20260414_155752.md`
