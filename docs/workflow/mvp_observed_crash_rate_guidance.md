# MVP Observed Crash-Rate Guidance

Status: review-only workflow note.

The MVP observed crash-rate lookup should use the canonical analysis dataset first, then the MVP directional feasibility package:

`work/output/roadway_graph/analysis/current/mvp_directional_observed_crash_rate_feasibility/`

## Current MVP Posture

Downstream/upstream is a required MVP input category. The MVP directional rate distribution dataset includes both direct divided/one-way directionality and synthetic undivided centerline interpretations in the usable directional analysis set. Synthetic rows must retain method/provenance flags so users can distinguish direct-only, synthetic-only, and mixed direct/synthetic cells.

Recommended MVP version:

1. Use `mvp_directional_rate_distribution_dataset/` as the distribution source for directional lookup cells.
2. Require downstream/upstream in the exact lookup cell.
3. Display direct/synthetic composition as a reliability note for every returned cell.
4. Return distribution statistics, not only a mean rate.
5. Return insufficient evidence when fallback cells remain sparse or exposure is missing.

## Lookup Fallback

Use the fallback hierarchy from:

`mvp_directional_rate_distribution_dataset/mvp_directional_lookup_fallback_hierarchy.csv`

The intended order is exact directional cell, collapse access type, collapse median group, collapse access count band, collapse downstream/upstream to a non-directional cell, broad roadway/speed/AADT cell, then insufficient evidence.

## Caveats

- Crash direction fields are not used.
- Synthetic undivided centerline directionality is an MVP directional interpretation and must be flagged as synthetic.
- Candidate observed rates are review-only aggregates, not production rates or models.
- Sparse and low-N cells must be flagged in any lookup UI or table.
- Numeric AADT/speed/exposure completeness is now the main blocker for broader rate readiness.
