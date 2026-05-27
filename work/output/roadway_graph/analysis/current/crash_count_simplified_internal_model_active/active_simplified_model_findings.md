# Active Simplified Internal Crash-Count Model Findings

**Status:** internal technical review only. These outputs are exploratory model diagnostics using active v2/v5 inputs. They are not external decision outputs, causal evidence, risk rankings, safety-performance rankings, policy guidance, or downstream functional-area distance recommendations.

## Input

- Modeled rows: 2967 denominator-ready signal-direction-window rows.
- Modeled assigned crashes: 12414.
- Active speed context: v5 Speed_Limit_RNS supplement.
- Active exposure: AADT v2 direction-factor denominator already present in the active modeling matrix.

## Access Interaction

- Access interaction improves AIC: True.
- Delta AIC for S2 versus S1: -26.26894125230956.

## Simplified Speed

- Simplified speed improves AIC: True.
- Delta AIC for S3 versus S2: -16.438615127505727.
- Missing/review speed rows modeled explicitly: 181.

## Overdispersion

- S3 scaled-Poisson Pearson overdispersion ratio: 6.893940265871291.
- Overdispersion remains present: True.

## Inference Recommendation

Scaled and cluster-robust Poisson remain the primary internal-review family. Fixed-alpha negative-binomial fits are retained as sensitivity evidence only. Estimated-alpha NB stabilization should be rerun under active v2/v5 before any NB interpretation.
