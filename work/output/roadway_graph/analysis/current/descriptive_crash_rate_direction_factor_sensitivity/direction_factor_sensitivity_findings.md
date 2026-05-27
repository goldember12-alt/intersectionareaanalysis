# Direction Factor Exposure Sensitivity Findings

**Status:** sensitivity analysis only. This does not replace descriptive crash-rate prototype v1, does not change the accepted bidirectional denominator policy, does not modify the AADT join, and is not a safety-performance, causal, policy, or ranking output.

## Bounded Question

How much do approved window-grain descriptive exposure and rates change if valid non-null AADT `DIRECTION_FACTOR` values are applied, while null factors retain v1 bidirectional AADT treatment?

## V2 Rule

For stable AADT denominator bins, valid `DIRECTION_FACTOR` values where `0 < factor <= 1` are applied to AADT. Null factors retain v1 bidirectional AADT treatment and are flagged. Invalid factors retain v1 treatment and are flagged for review. The adjusted AADT is length-weighted back to `reference_signal_id + signal_relative_direction + analysis_window` before computing v2 exposure and descriptive rates.

## Coverage

- Units evaluated: 2,967.
- Units with factor applied: 2,751.
- Units using null-factor bidirectional fallback: 594.
- Units with invalid factor: 0.
- Non-ready v1 units preserved without v2 rates: 255.

## V1 To V2 Change

- V1 estimated exposure: 12,162,169,675.11.
- V2 direction-factor adjusted exposure: 7,108,955,359.70.
- Aggregate exposure ratio v2/v1: 0.584514.
- V1 aggregate descriptive rate per million: 1.020706.
- V2 aggregate descriptive rate per million: 1.746248.
- Aggregate rate ratio v2/v1: 1.710824.

## Interpretation

The v2 result is `plausible_enough_for_internal_review_with_source_documentation_needed`. It is directionally plausible as an internal sensitivity because applying factors generally lowers exposure and raises descriptive rates, which matches the prior AADT direction-factor audit. It remains review-only because source documentation is still needed before treating `DIRECTION_FACTOR` as an accepted denominator policy.

## Validation

The QA table confirms no crash direction fields were read or used, v1 outputs were not overwritten, null-factor fallback rows are flagged, no models/regressions were fit, no raw-bin or fixed-band rates were created, and all v2 rates remain at the approved window grain.
