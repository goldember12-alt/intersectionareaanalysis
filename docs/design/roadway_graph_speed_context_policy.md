# Roadway Graph Speed Context Policy

**Status: CURRENT ACTIVE.** This memo promotes the speed v5 new-source supplement as the active speed context policy going forward.

## Bounded Question

Which posted-speed context should be treated as active for future roadway-derived directional-bin context refreshes, without overwriting accepted speed v4 outputs or rerunning downstream products in this task?

## Active Policy

`speed_v5_new_source_supplement` is active going forward.

Speed v5 uses `Speed_Limit_RNS` as a supplemental speed source and requires route+measure evidence for stable recovery. This source provides stronger route+measure support for the current roadway-derived directional-bin universe than speed v4. Where v5 provides stable speed assignment, `Speed_Limit_RNS` route+measure evidence is preferred.

Speed v4 identity-enriched outputs are retained as baseline and legacy comparison artifacts. They are not deleted, overwritten, or treated as the active speed context after this promotion.

## Promotion Summary

- v4 stable speed bins: 84,857
- v5 stable speed bins: 105,835
- newly recovered stable bins from v4 missing/review: 20,978
- v5 missing/review bins remaining: 4,875
- v4 stable bins confirmed by v5: 29,067
- v4 stable bins conflicting with v5: 2,809
- crash rows inheriting stable v5 speed: 12,750
- reference signals with stable v5 speed: 940

## Conflict Policy

V4/v5 conflicts are preserved as QA comparison evidence. They are not blockers to v5 promotion because the accepted decision is that `Speed_Limit_RNS` route+measure evidence is the stronger source for future speed context.

Remaining v5 review and missing statuses remain visible. No speed values are imputed, and no stable speed label is forced where route+measure evidence is weak, absent, or conflicting.

## Active Outputs

The policy promotion record lives under:

`work/output/roadway_graph/review/current/active_speed_context_policy/`

Key outputs:

- `active_speed_context_policy_summary.csv`
- `active_speed_context_policy_rules.csv`
- `active_speed_context_v4_v5_comparison.csv`
- `active_speed_context_conflict_summary.csv`
- `active_speed_context_downstream_refresh_requirements.csv`
- `active_speed_context_policy_findings.md`
- `active_speed_context_policy_manifest.json`

## Downstream Refresh Requirements

The active downstream refresh now writes a v2/v5 combined directional-bin context table under:

`work/output/roadway_graph/analysis/current/directional_bin_context_table_active/`

The preserved baseline combined table under `directional_bin_context_table/` still reflects the previously accepted speed v4 context.

Before downstream products are described as using active v5 speed, refresh:

- `directional_bin_context_table`
- descriptive context summaries
- signal/context review queues where speed status is used
- fixed distance-band and signal-direction profiles
- stakeholder table packages and report tables/figures that use speed context
- rate outputs after both active AADT denominator v2 and active speed v5 are integrated
- modeling readiness datasets and internal models before interpreting speed terms under v5

## QA Boundaries

- Speed v4 outputs were not overwritten.
- `artifacts/normalized/speed.parquet` was not overwritten.
- Scaffold, catchments, crash assignment, access joins, AADT joins, rates, and models were not modified.
- Crash direction fields were not read or used.
- Speed v5 is labeled active for future refreshes.
- Speed v4 remains available as baseline/legacy comparison.
