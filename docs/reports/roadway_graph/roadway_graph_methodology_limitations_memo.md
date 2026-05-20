# Roadway Graph Methodology and Limitations Memo

**Status: PLANNING MEMO.** This memo documents the accepted roadway-graph descriptive table package and the first stakeholder-safe aggregate AADT-normalized prototype summaries. It is not a final report, policy document, model specification, unit-rate analysis, fixed-band rate analysis, or causal analysis.

## Executive Summary

The current roadway-graph prototype creates a stable 0-2,500 ft roadway-derived directional-bin universe around TRUE reference signals. It uses roadway graph evidence to define directional bins before crashes, access points, speed, AADT, and crash-level urban/rural context are summarized.

The accepted universe contains 110,710 directional bins, 13,216 assigned crashes, and 971 reference signals. The high-priority window is 0-1,000 ft, with 9,170 assigned crashes. The sensitivity window is 1,000-2,500 ft, with 4,046 assigned crashes. Rows beyond 2,500 ft are excluded from the current descriptive universe and remain review-only.

The current product can support descriptive review, table-driven stakeholder discussion, context-completeness review, aggregate-only AADT-normalized prototype discussion with caveats, and planning for later figures or modeling-readiness work. It cannot support policy guidance, unit-level crash-rate claims, fixed-band rate claims, regression results, causal language, safety-performance/risk/danger rankings, or final downstream functional area recommendations.

## Current Roadway-Graph Product

The bounded product is a graph-first roadway-derived directional context package for signalized intersections. The active method is:

full Travelway graph -> signal graph association -> signal eligibility gating -> TRUE reference signals -> signal-to-anchor segments -> roadway role classification -> crash-ready segment/bin subset -> divided carriageway pairing where geometry supports it -> undivided roads treated as shared centerline by default -> roadway-derived directional scaffold -> roadway-only directional catchments -> conservative crash assignment -> readiness-gated assigned-crash universe -> access, speed, AADT, and crash-level urban/rural context enrichment.

The current product is descriptive and prototype-ready. It is not policy-ready or modeling-ready.

Current accepted output roots:

- `work/output/roadway_graph/analysis/current/directional_bin_context_table/`
- `work/output/roadway_graph/analysis/current/directional_context_descriptive_summaries/`
- `work/output/roadway_graph/analysis/current/signal_context_review_queue/`
- `work/output/roadway_graph/analysis/current/directional_context_distance_band_profiles/`
- `work/output/roadway_graph/analysis/current/signal_direction_context_profiles/`
- `work/output/roadway_graph/analysis/current/stakeholder_context_table_package/`
- `work/output/roadway_graph/analysis/current/descriptive_crash_rate_suppression_review/`

## Directional-Bin Universe

The directional-bin universe is one row per accepted roadway-derived directional bin in the 0-2,500 ft analysis window around TRUE reference signals. Bins are directional because they inherit signal-relative orientation from the roadway graph scaffold, not from crash direction fields.

Current accepted windows:

- 0-1,000 ft: high-priority descriptive window.
- 1,000-2,500 ft: sensitivity descriptive window.
- Greater than 2,500 ft: excluded from the current descriptive universe and preserved only as review-only context where it exists upstream.

Upstream and downstream are interpreted from roadway graph directionality relative to the reference signal. Context variables do not redefine upstream/downstream, and crash direction fields are not used.

Accepted directional crash counts:

- upstream assigned crashes: 6,543
- downstream assigned crashes: 6,673
- assigned crashes in 0-1,000 ft: 9,170
- assigned crashes in 1,000-2,500 ft: 4,046

## Context Layers

The current context table joins descriptive evidence to the accepted directional-bin scaffold.

Crashes:
Assigned crashes are summarized only after the roadway-derived scaffold exists. Ambiguous and unresolved crashes remain outside the assigned-crash universe. Crash direction fields are not read or used.

Access:
Access points are summarized as bin context, including counts within the catchment and within 100 ft and 250 ft. Access context is descriptive. It does not define upstream/downstream and is not used to create policy claims.

Speed v4:
Speed context is joined from the current speed v4 identity-enriched workflow. Stable speed context is available for 84,857 bins. Missing or review speed statuses remain visible because filling them would hide uncertainty.

AADT v3:
AADT context is joined from the current AADT v3 identity/route-measure workflow. Stable AADT context is available for 106,210 bins. The report package now includes only stakeholder-safe aggregate AADT-normalized prototype summaries copied from the suppression review output. Unit-level rates remain QA-only and suppressed.

Crash-level AREA_TYPE urban/rural:
Assigned crashes include crash-level AREA_TYPE context: 11,915 urban crashes and 1,301 rural crashes. This is crash-record context only. It is not roadway-level rural/suburban/urban truth and should not be used as a policy geography variable.

## Descriptive Analysis Outputs

The accepted descriptive table package contains:

- first-stage summaries by window, direction, reference signal, signal-direction-window, distance band, roadway representation, speed, AADT, access exposure, crash AREA_TYPE, and context completeness
- signal-level and signal-direction review-priority queues
- fixed distance-band profiles for 0-250 ft, 250-500 ft, 500-1,000 ft, 1,000-1,500 ft, and 1,500-2,500 ft
- signal-direction profiles at signal-direction, signal-direction-window, and signal-direction-distance-band grains
- a compact stakeholder table package with overview, top review queue, top signal-direction profiles, distance-band summary, context-completeness summary, limitations, table index, QA, and manifest
- stakeholder-safe aggregate AADT-normalized prototype summaries by analysis window and by signal-relative direction, with exact Poisson/Garwood 95% confidence intervals

Distance-band assigned crash distribution:

- 0-250 ft: 3,527
- 250-500 ft: 2,240
- 500-1,000 ft: 3,403
- 1,000-1,500 ft: 1,975
- 1,500-2,500 ft: 2,071

## What the Results Can Support

The current product can support:

- descriptive review of the accepted 0-2,500 ft directional-bin universe
- comparison of counts across upstream/downstream, distance windows, fixed distance bands, roadway representation, access context, speed context, AADT context, and crash-level AREA_TYPE
- signal review-priority planning
- identification of context-completeness gaps before stakeholder-facing reporting
- planning for later figures and report exhibits
- aggregate-only descriptive AADT-normalized prototype discussion with explicit caveats
- planning for later modeling-readiness requirements

## What the Results Cannot Support

The current product cannot support:

- unit-level crash-rate presentation as stakeholder findings
- fixed distance-band rates or raw bin-level rates
- regression, predictive, or causal analysis
- safety-performance rankings
- danger or risk rankings
- policy guidance language
- final downstream functional area distance recommendations
- roadway-level rural/suburban/urban analysis
- claims that crash occurrence alone defines downstream functional area distance

## Known Limitations

- Crash direction fields were not read or used.
- Context fields do not redefine upstream/downstream.
- Rows beyond 2,500 ft are excluded from the accepted descriptive universe.
- Ambiguous and unresolved crashes are excluded from the assigned-crash universe.
- Roadway-level rural/suburban/urban context remains unavailable.
- Crash AREA_TYPE is crash-level context only and applies only to assigned crashes.
- Speed and AADT missing/review statuses remain visible and unresolved.
- Aggregate prototype rates use a provisional bidirectional AADT assumption.
- `DIRECTION_FACTOR` was not applied.
- Missing/review AADT was excluded from denominator values.
- All 2,967 reviewed unit-level rate rows were suppressed from stakeholder unit-rate display and remain QA-only.
- Blocked divided records outside the accepted universe are not summarized here.
- Review-priority queues are for manual review planning only.
- Report figures have been generated, including SVG-only aggregate rate exhibits.

## Recommended Use

Use the current product as a stable descriptive evidence package. The most appropriate near-term uses are table review, context QA, stakeholder exhibit planning, and manual review-priority planning.

When discussing the signal review queue, use review-priority language only. Do not describe rows as dangerous, risky, high-performing, low-performing, or causal.

When discussing crash counts, describe them as assigned-crash counts in the accepted universe. When discussing rates, use only the aggregate prototype summaries and state the required caveats. Do not present unit-level rates as stakeholder findings or normalized safety outcomes.

## Next Steps Before Stakeholder-Facing Report

Recommended next steps before a stakeholder-facing roadway-graph report:

1. Review the stakeholder table package and QA outputs manually.
2. Select which figure and table exhibits should be created first.
3. Confirm the exact audience and scope for the first roadway-graph report.
4. Manually review the aggregate rate exhibit caveats and suppression rules before broader rate sensitivity work.
5. Define any additional QA required before public-facing language.
6. Keep fixed-band rate sensitivity and modeling-readiness requirements separate from descriptive report preparation.
