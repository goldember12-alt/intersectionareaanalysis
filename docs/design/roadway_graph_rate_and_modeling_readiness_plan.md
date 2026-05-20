# Roadway Graph Rate and Modeling Readiness Plan

**Status: DESIGN PLANNING ONLY.** This memo defines what would be required to responsibly support crash rates, AADT-normalized comparisons, regression, predictive modeling, or causal analysis later. It does not implement rates, models, figures, regressions, causal analysis, or policy guidance.

## Purpose

The current roadway-graph product is a stable descriptive universe, not a rate-ready or modeling-ready dataset. This memo records the evidence, denominator, analysis-unit, validation, and language requirements that must be satisfied before later work attempts items the current package explicitly prohibits.

The bounded question is:

What must be added, audited, and reviewed before the accepted 0-2,500 ft roadway-derived directional-bin context universe can support crash-rate prototypes or statistical modeling?

## Current Prohibition List

The current descriptive package cannot yet support:

1. Crash rates or AADT-normalized crash comparisons.
2. Regression, predictive, or causal analysis.
3. Safety-performance rankings.
4. Danger or risk rankings.
5. Policy guidance language.
6. Final downstream functional area distance recommendations.
7. Roadway-level rural/suburban/urban analysis.
8. Claims that crash occurrence alone defines downstream functional area distance.

These prohibitions remain active until a later reviewed readiness package explicitly changes them.

## Current Evidence Base

The accepted descriptive universe is:

- 110,710 directional bins.
- 13,216 assigned crashes.
- 971 reference signals.
- 84,857 stable speed bins.
- 106,210 stable AADT bins.
- 6,543 upstream crashes.
- 6,673 downstream crashes.
- 9,170 crashes in 0-1,000 ft.
- 4,046 crashes in 1,000-2,500 ft.
- 11,915 crash-level urban crashes and 1,301 crash-level rural crashes.

Current QA confirms:

- crash direction fields were not read or used
- context fields do not redefine upstream/downstream
- >2,500 ft rows are excluded from the descriptive universe
- ambiguous and unresolved crashes are excluded from the assigned-crash universe
- crash AREA_TYPE is crash-level context only
- roadway-level rural/suburban/urban source is not available
- speed and AADT review/missing statuses are preserved

## Requirements for Crash Rates and AADT-Normalized Comparisons

### Valid Analysis Unit Options

Any rate prototype must first choose one analysis unit and use it consistently:

- signal + signal-relative direction + analysis window
- signal + signal-relative direction + fixed distance band
- signal + approach/directional segment + analysis window
- signal + approach/directional segment + fixed distance band
- corridor or route-context aggregate, only if duplicate signal-relative exposure can be controlled

Raw bin-level rates should not be the first prototype. The 50-ft bin grain creates many low-denominator and low-count rows, increasing instability and making small denominator differences dominate apparent rates.

### Exposure Denominator Requirements

Rate denominators must be explicitly defined before any rate is computed. Minimum required denominator fields:

- AADT value and source/status
- represented length in miles or feet
- crash study period length in years
- directional exposure assumption
- whether AADT is directional, bidirectional, or adjusted by a direction factor
- whether duplicated exposure appears in upstream and downstream views of the same physical roadway

For VMT-like exposure, the basic denominator concept should be documented as:

AADT x represented segment length x crash study period days, with unit conversion stated explicitly.

No module should compute a rate until denominator fields and unit conversions are audited.

### Crash Study Period Requirements

The crash numerator must be tied to a documented study period:

- start and end dates
- number of full years or days represented
- whether crashes are filtered by year, severity, type, or assignment readiness
- whether partial-year data are excluded or prorated
- how duplicate crash assignments are prevented

The current descriptive package carries assigned crashes, but a rate prototype must independently confirm the crash study period and denominator period alignment.

### AADT Stability and Coverage Requirements

AADT-normalized comparisons require:

- stable AADT status only, unless a separate reviewed rule allows otherwise
- AADT year availability and reasonableness checks
- review of AADT values by roadway representation and distance window
- coverage summaries at the chosen analysis unit
- explicit treatment where a unit has mixed AADT values
- exclusion or flagging of units with missing/review AADT context

The current 106,210 stable AADT bins are promising for descriptive coverage, but rate readiness depends on the chosen aggregation grain and denominator behavior, not only bin count.

### Bin Length and VMT-Like Exposure Requirements

The rate prototype must preserve actual represented length rather than assume each bin is exactly 50 ft. Required checks:

- represented length is positive
- represented length sums are plausible by analysis unit
- truncated bins near anchors or boundaries are handled correctly
- divided carriageways and undivided shared centerlines are not mixed without a documented exposure rule
- distance bands use summed represented length rather than nominal band width when possible

### Aggregation Grain Recommendations

Recommended first rate prototype grain:

signal + signal-relative direction + analysis window, using 0-1,000 ft and 1,000-2,500 ft windows.

Reason:

- fewer sparse units than raw bins
- preserves upstream/downstream interpretation
- aligns with high-priority and sensitivity windows
- allows AADT and length denominator QA before finer distance-band rates

Recommended second prototype grain:

signal + signal-relative direction + fixed distance band, after the window-level prototype passes denominator QA.

### Missing/Review AADT Treatment

Missing or review AADT rows must not be silently filled. Acceptable treatments to evaluate later:

- exclude from rate prototype and report excluded numerator/denominator counts
- include as non-rate descriptive rows only
- create a separate sensitivity table for review-status AADT, without treating it as rate-ready
- aggregate only units whose denominator coverage exceeds a documented threshold

Every rate table must report:

- stable AADT bin count
- missing/review AADT bin count
- denominator completeness share
- crash count excluded for denominator reasons

### Duplicate Signal-Relative Exposure Risks

The same physical roadway length can appear in multiple signal-relative contexts when neighboring reference signals view the same roadway from different anchors. Before rates are computed, the workflow must audit:

- whether exposure is duplicated across reference signals
- whether a corridor segment appears as downstream for one signal and upstream for another
- whether duplicate exposure is acceptable for signal-centered descriptive rates
- whether corridor-level rates need de-duplicated roadway exposure

Signal-centered rates may intentionally allow signal-relative duplication, but the memo and table labels must say so.

### Unresolved/Ambiguous Crash Treatment

The numerator must specify whether it includes only assigned crashes or whether any recovery of unresolved/ambiguous crashes has been reviewed. Current rate prototypes should use only the accepted assigned-crash universe and report:

- assigned crashes included
- ambiguous/unresolved crashes excluded
- reason unresolved crashes remain excluded
- sensitivity risk if excluded unresolved cases are not randomly distributed

### Minimum Denominator Rules

Before any rate is reported, define minimum denominator rules such as:

- minimum represented length per unit
- minimum stable AADT coverage share
- minimum nonzero AADT threshold
- minimum crash study period completeness
- minimum number of bins per unit, where applicable
- flag or suppress rates where denominator is too small

Minimum denominator rules should be treated as QA gates, not as data-cleaning afterthoughts.

### Uncertainty and Confidence Interval Needs

Any rate prototype should include uncertainty fields before comparison language is allowed:

- crash count
- denominator
- rate
- confidence interval or exact interval for low counts
- indicator for low denominator or low count
- clear note that intervals are descriptive uncertainty, not proof of effect

Low-count Poisson intervals or related exact methods may be appropriate for an early prototype. The choice should be documented before implementation.

### Why Raw Bin-Level Rates May Be Unstable

Raw bin-level rates are likely unstable because:

- many bins have zero crashes
- crash counts per 50-ft bin are sparse
- denominator length is short
- AADT variation may be small relative to count noise
- small geometry or assignment differences can dominate apparent rates
- adjacent bins within the same signal/corridor are not independent

Raw bin-level rates should be avoided until coarser rate prototypes and denominator audits are reviewed.

### Recommended First Rate Prototype Scope

Recommended first prototype:

- analysis unit: reference signal + signal-relative direction + analysis window
- windows: 0-1,000 ft and 1,000-2,500 ft
- numerator: accepted assigned crashes only
- denominator: stable AADT x represented length x study period
- outputs: readiness audit first, then a clearly labeled descriptive rate prototype only if audit passes
- exclusions: missing/review AADT, unresolved crashes, >2,500 ft rows, roadway-level urban/rural claims

Do not use this prototype for policy guidance or safety-performance ranking.

## Requirements for Regression or Predictive Modeling

### Modeling Unit Options

Potential modeling units:

- signal + signal-relative direction + analysis window
- signal + signal-relative direction + fixed distance band
- signal-level aggregate with separate upstream/downstream counts
- segment-level aggregate, if duplicate signal-relative exposure is resolved
- corridor-level aggregate, only after de-duplicated exposure is designed

The first modeling-readiness dataset should use the same unit as the first rate prototype unless there is a documented reason to diverge.

### Target and Outcome Definitions

Possible outcomes:

- assigned crash count
- downstream assigned crash count
- upstream assigned crash count
- 0-1,000 ft assigned crash count
- 1,000-2,500 ft assigned crash count
- crash-type-specific counts, only if crash type coding is audited later

Outcomes must not be review-priority scores. The current review queue is a manual review tool, not a statistical target.

### Exposure Offset Requirements

Count models should include an exposure offset when comparing counts across units with different AADT or represented length. The offset should be based on the reviewed denominator, such as log(VMT-like exposure), where valid.

Rows without valid exposure should either be excluded from modeling or retained only in non-rate descriptive outputs.

### Candidate Covariates

Candidate covariates to audit before modeling:

- signal-relative direction
- analysis window or distance band
- roadway representation type
- access counts within catchment, 100 ft, and 250 ft
- stable speed band or assigned speed
- stable AADT band or AADT value, if not already used only as exposure
- speed/AADT review or missing flags
- divided versus undivided representation
- crash-level AREA_TYPE summaries, with caution that these are not roadway-level geographic variables
- future roadway-level rural/suburban/urban source, if added and validated
- corridor or route identity, if used for clustering or fixed effects

Covariates must not redefine upstream/downstream.

### Context Completeness Flags

Modeling-readiness outputs must carry:

- stable AADT coverage share
- stable speed coverage share
- missing/review AADT count
- missing/review speed count
- access context completeness
- roadway urban/rural source status
- unresolved/ambiguous crash exclusion counts if available

Completeness flags should be used for QA, filtering, sensitivity analysis, or missingness indicators, not silently dropped.

### Train/Test or Validation Requirements

Predictive modeling requires a validation design before fitting:

- train/test split or cross-validation plan
- grouped split by signal, corridor, or route where non-independence is likely
- evaluation metric appropriate for count data
- baseline model for comparison
- out-of-sample performance reporting

Without validation, a fitted model should be described only as exploratory descriptive modeling, not predictive.

### Overdispersion and Zero-Inflation Checks

Crash count models must check:

- variance relative to mean
- excess zero counts
- influential high-count units
- fit residuals by signal, corridor, window, and roadway representation
- whether negative binomial or zero-inflated families are more appropriate than Poisson

These checks should be part of modeling readiness, not optional post-processing.

### Low-Count Handling

Low-count units require:

- minimum count/denominator flags
- no ranking by fitted value without uncertainty
- no strong interpretation of sparse cells
- aggregation or hierarchical modeling consideration if sparse cells dominate

The model should avoid overfitting fine distance bands or rare context combinations.

### Missing/Review Context Handling

Missing/review speed and AADT statuses must be handled explicitly:

- exclude from model-ready rows
- include missingness flags in a sensitivity model
- impute only after a documented imputation plan and validation
- report how many crashes and bins are affected

No model should silently treat review/missing context as stable context.

### Non-Independence and Repeated Signal/Corridor Issues

The roadway-graph universe is signal-centered. Units may be correlated because:

- a signal contributes multiple directions and windows
- neighboring signals may share roadway exposure
- bins along the same corridor are spatially adjacent
- upstream for one reference signal may be downstream for another

Later modeling should consider:

- clustered standard errors
- mixed effects by signal or corridor
- route/corridor fixed effects
- grouped validation splits
- de-duplicated corridor exposure if the unit becomes corridor-level

### Modeling Families to Consider Later

Potential families, after readiness review:

- Poisson count model with exposure offset
- negative binomial count model with exposure offset
- zero-inflated count model, if justified by zero-inflation checks
- hurdle model, if presence/absence and count intensity need separate treatment
- mixed-effects or hierarchical count model, if repeated signal/corridor structure is material
- regularized predictive count model, only with validation and clear predictive purpose

These are candidates only. No model family is approved until the denominator and modeling-readiness dataset are reviewed.

### Why the Current Review Queue Is Not a Model Target

The review queue is a manual prioritization tool built from crash burden, context completeness, directional imbalance, access context, and related flags. It is not an observed safety outcome and should not be used as a dependent variable.

Using review-priority tier as a model target would train a model to reproduce a hand-built review heuristic, not crash occurrence, crash frequency, or any policy-relevant outcome.

## Requirements for Causal Analysis

### Why the Current Descriptive Data Is Not Causal

The current product is cross-sectional descriptive evidence assembled after roadway graph scaffolding. It does not assign treatment, establish counterfactual conditions, control confounding, or prove temporal ordering between roadway/access/context changes and crashes.

Therefore, the current data cannot support statements that a context variable caused a crash pattern or that a distance band is causally safer or less safe.

### Additional Design Required

Causal analysis would require:

- explicit treatment definition
- credible comparison group
- temporal ordering between treatment and outcome
- pre/post periods where applicable
- exposure denominator stability
- confounder measurement
- sensitivity checks for unobserved confounding
- documented inclusion/exclusion criteria

### Possible Future Quasi-Experimental Designs

Potential designs to evaluate later:

- before/after study around access or roadway changes, with exposure adjustment
- difference-in-differences where comparable untreated sites exist
- matched comparison of signals with similar roadway/exposure context
- interrupted time series for locations with known intervention dates
- regression discontinuity only if a defensible threshold assignment mechanism exists

These designs require additional data and design review. They are not enabled by the current descriptive package alone.

### Treatment and Comparison Requirements

A causal design must define:

- what the treatment is
- when the treatment occurred
- which signals/segments are treated
- which signals/segments are valid comparisons
- why the comparison group is credible
- whether spillover or shared corridor exposure affects comparisons

### Temporal Ordering Requirements

Causal claims require crash dates, treatment dates, denominator years, and context source dates to align. AADT year, roadway/access change dates, speed change dates, and crash periods must be checked before causal language is allowed.

### Confounding and Sensitivity Checks

At minimum, later causal work would need to address:

- traffic volume and exposure differences
- speed differences
- roadway representation and geometry
- access density and access type
- signal/corridor context
- geographic context from a validated roadway-level source
- regression to the mean
- incomplete or missing context

Sensitivity analyses should report whether conclusions change under alternative inclusion rules, denominator rules, matching choices, or unresolved-crash assumptions.

## Recommended Staged Path

Do not jump from the current descriptive package directly to rates or models. The recommended staged path is:

1. `exposure_denominator_readiness_audit.py`
   - Audit AADT, represented length, study period, denominator completeness, duplicated exposure, and minimum denominator feasibility.
   - Output should be QA/readiness tables only, not rates.

2. `directional_context_exposure_table.py`
   - Build an exposure-ready table at a reviewed analysis unit after the denominator audit passes.
   - Preserve stable/missing/review denominator flags.

3. `descriptive_crash_rate_prototype.py`
   - Compute a first descriptive rate prototype only after exposure table review.
   - Recommended first grain: reference signal + signal-relative direction + analysis window.
   - Include uncertainty and suppression/flag rules.

4. `modeling_readiness_dataset.py`
   - Build a model-readiness dataset with outcomes, exposure offsets, candidate covariates, completeness flags, and clustering IDs.
   - Do not fit models in this module.

5. `modeling_specification_memo.md`
   - Document target outcomes, model families, inclusion rules, offset, validation design, missing data handling, and interpretation limits before fitting.

6. Optional prototype model only after review.
   - Fit only the reviewed model specification.
   - Report exploratory or predictive status honestly.
   - Do not convert model outputs into policy guidance without a separate reviewed policy/research interpretation step.

## Language Guardrails

Use:

- descriptive count
- assigned crash count
- exposure denominator
- denominator completeness
- rate prototype
- AADT-normalized comparison, if denominator QA passes
- exploratory model
- predictive model, only with validation
- association, only for non-causal modeling
- review priority
- uncertainty interval
- readiness audit
- sensitivity check

Avoid until explicitly supported:

- dangerous
- risky
- safest
- safety performance
- high-risk location
- crash rate, unless a reviewed denominator has been computed
- expected crashes, unless a reviewed model supports it
- caused by
- impact of
- effect of
- policy recommendation
- recommended downstream functional area distance
- optimal distance
- proven
- significant, unless tied to a reviewed statistical test and context

## Decision Point

Recommended decision:

Continue with the descriptive report and figure package first. Do not begin rate/modeling-readiness implementation until the descriptive report package has been reviewed and the analysis audience agrees on the first rate/modeling question.

The first later step should be an exposure denominator readiness audit, not a rate table or model.
