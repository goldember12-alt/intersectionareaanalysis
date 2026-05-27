# Active Report Figure Refresh Findings

## Bounded Question

Refresh report tables and figures using active speed v5 and active AADT v2 denominator outputs, without modifying scaffold, catchments, crash assignment, access, speed, or AADT joins.

## Outputs

- active figures created: 18
- active figure data tables: 18
- stable speed bins shown: 105835
- represented assigned crashes: 13216
- active estimated exposure: 7108955359.70
- active aggregate descriptive rate per million: 1.746248

## Guardrails

The figures are descriptive active v2/v5 report assets. Rates use estimated exposure, apply `DIRECTION_FACTOR` where valid, and use bidirectional fallback where null. They are not causal, risk, safety-performance, policy, or downstream-distance guidance.

Baseline v1/v4 figure directories were retained and not overwritten.
