# Context Enrichment Rural/Urban Review

**Status: SUPPORTING REFERENCE.** This crash-context review remains in place and must not be treated as roadway-level geographic truth.

## Scope

This memo reviews the bounded crash-context rural/urban enrichment in `src/active/context_enrichment.py` for the latest rerun of `python -m src.active.context_enrichment`.

Latest rerun summary:

- `work/output/context_enrichment/runs/history/context_enrichment_run_summary_20260423_143606.json`

Latest rerun table paths used in this review:

- `work/output/context_enrichment/tables/history/signal_study_area_context_enriched_20260423_143553.csv`
- `work/output/context_enrichment/tables/history/approach_row_context_enriched_20260423_143551.csv`
- `work/output/context_enrichment/tables/history/classified_crash_context_enriched_20260423_143554.csv`

## Current rule

The enrichment remains bounded to crash-context evidence only:

- `Crash_AreaType <- crashes.parquet.AREA_TYPE`
- `Rural -> rural`
- `Urban -> urban`
- anything else -> `unresolved`

Dominant class remains allowed only when:

- at least `3` mapped rural/urban crashes are attached
- one class has share `>= 0.67`

Otherwise:

- both classes present -> `mixed`
- no attached classified crashes -> `no_classified_crash_context`
- sparse single-class evidence below the minimum count -> `unresolved`

## Latest output counts

- normalized crash `AREA_TYPE` completeness: `1.0`
- enriched classified-crash `Crash_AreaType` completeness: `1.0`
- signal RU status counts: `assigned=159`, `unresolved=4`
- signal dominant-class counts: `urban=151`, `rural=8`, `unresolved=4`
- signal reason counts: `dominant_share_ge_0_67_with_min3=159`, `fewer_than_3_classified_crashes=4`
- approach-row RU status counts: `assigned=159`, `no_classified_crash_context=15`, `unresolved=4`
- approach-row dominant-class counts: `urban=151`, `rural=8`, `unresolved=19`
- approach-row reason counts: `dominant_share_ge_0_67_with_min3=159`, `no_attached_classified_crashes=15`, `fewer_than_3_classified_crashes=4`
- mixed signals: `0`
- mixed approach rows: `0`

## Diagnostic read

- The rule is behaving as intended for this bounded slice. Completeness is full, and nearly all attached crash contexts resolve cleanly to a dominant urban or rural class.
- The unresolved signal cases are sparse single-class examples, not contradictory mixed evidence. Examples:
  - `signal_176`: `2` urban crashes, `0` rural, `0` unresolved
  - `signal_459`: `2` urban crashes, `0` rural, `0` unresolved
  - `signal_1726`: `2` urban crashes, `0` rural, `0` unresolved
  - `signal_1878`: `1` urban crash, `0` rural, `0` unresolved
- Approach rows with no attached classified crashes now remain explicit rather than blank. Representative examples include:
  - `signal_175` / row `13355`
  - `signal_228` / row `10565`
  - `signal_245` / row `5859`
  - `signal_256` / row `5554`

## Minimal corrections made

- sparse single-class unresolved cases now report `RU_ContextReason = fewer_than_3_classified_crashes` instead of the incorrect mixed-evidence reason
- approach rows with no attached classified crashes now carry explicit `RU_ContextStatus = no_classified_crash_context` and `RU_ContextReason = no_attached_classified_crashes`
- validation/reporting now exposes both signal-level and approach-row rural/urban status, reason, and dominant-class distributions

## Conclusion

The current rural/urban enrichment is bounded, interpretable, and aligned with the crash-context contract. The needed work in this pass was reporting and explicit unresolved handling, not a methodological change.
