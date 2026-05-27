# Active Context Refresh Findings

## Bounded Question

Refresh the accepted directional-bin context table using active speed v5 and active AADT denominator policy flags without changing scaffold, catchments, crash assignment, access context, or AADT joins.

## Key Counts

- total bins: 110710
- v4 stable speed bins before refresh: 84857
- active v5 stable speed bins after refresh: 105835
- stable AADT context bins: 106210
- represented assigned crashes: 13216
- reference signals represented: 971

## Active Policies

- speed context: `speed_v5_new_source_supplement`
- denominator policy: `v2_direction_factor_with_bidirectional_fallback`
- v1/v4 outputs are preserved as baseline/legacy comparison.
