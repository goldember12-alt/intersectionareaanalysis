# Active Negative-Binomial Stabilization Diagnostic Findings

**Status:** internal technical modeling diagnostic only. This package does not create stakeholder-facing findings, predictions, rankings, causal claims, policy guidance, risk/danger/safety-performance claims, or downstream functional-area distance recommendations.

## Input

- Modeled rows: 2967 denominator-ready active signal-direction-window rows.
- Modeled assigned crashes: 12414.
- Outcome: `assigned_crash_count`.
- Offset: active `log_estimated_exposure`.
- Active exposure already reflects AADT v2 direction-factor policy; no additional `DIRECTION_FACTOR` was applied here.

## Estimated-Alpha Negative Binomial

- Estimated-alpha NB all models interpretable: False.
- First estimated-alpha NB model not marked interpretable: `NB1_window_direction_active`.
- NB4 fit success: True.
- NB4 converged: False.
- NB4 alpha estimate: 1.6289756314397278e-41.
- NB4 interpretable: False.
- NB4 interpretability note: unstable_or_incomplete_covariance.

## Fixed-Alpha NB Sensitivity

- Fixed-alpha NB fit success share across active sequence and alpha grid: 1.000.
- Fixed-alpha NB supports access-window interaction across alpha grid: True.
- Fixed-alpha NB supports simplified speed across alpha grid: True.

## Active vs Baseline

- Baseline estimated-alpha interpretable count in matched sequence: 0.
- Active estimated-alpha interpretable count in matched sequence: 2.
- Active v2/v5 did not stabilize estimated-alpha NB enough to replace robust/scaled Poisson.

## Readiness Decision

Decision: `active_robust_poisson_primary_nb_sensitivity`.

Recommended preferred active internal model family: active scaled and cluster-robust Poisson primary; fixed-alpha NB sensitivity.

Stakeholder reporting status: `not_ready`.
