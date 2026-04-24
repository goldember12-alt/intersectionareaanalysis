# Context Enrichment AADT and StudyAreaID Policy Recommendation

## Scope

This memo recommends the smallest correct next-step policy for:

1. AADT enrichment in the current signal-centered divided-road slice
2. paired-row `StudyAreaID` behavior in `signal_study_area_summary__approach_shaped.csv`

It uses the completed diagnostics and does not broaden into statewide or legacy logic.

## AADT recommendation

### Current state

The current exact-overlap rule is behaving as documented, but it is not usable in this slice:

- route-supported bounding-box candidate pairs: `613`
- route-supported exact geometry intersections: `15`
- route-supported positive line-overlap pairs: `0`

The failure is therefore not route support. It is the requirement for exact shared line overlap between two line datasets that are usually offset or only point-touching.

### Option comparison

#### 1. Same-route nearest geometry within a conservative distance threshold

What it would do:

- keep only exact same-route candidates
- keep only candidates within a small geometry distance threshold
- after latest-year filtering, choose the nearest candidate

Evidence used:

- exact route support
- geometry proximity only

Observed behavior in this slice:

- `<= 1 ft`: `47` candidate rows, `41` matched, `6` ambiguous
- `<= 2 ft`: `101` candidate rows, `86` matched, `15` ambiguous
- `<= 3 ft`: `177` candidate rows, `142` matched, `35` ambiguous

Risks:

- route-only proximity is still too ambiguous on repeated or parallel same-route linework
- no measure support means the nearest line can still be the wrong same-route feature

Assessment:

- bounded and simple
- not strong enough by itself
- too much ambiguity at the thresholds that produce useful coverage

#### 2. Same-route projection or midpoint support

What it would do:

- choose the same-route AADT feature nearest to a projected point or midpoint on the approach row

Evidence used:

- exact route support
- a single-point geometric proximity surrogate

Risks:

- it is still a proximity-only rule
- it does not add independent evidence beyond nearest-geometry support
- it can still choose the wrong same-route feature where repeated geometry exists

Assessment:

- still bounded
- not materially better than nearest same-route geometry
- not recommended as a separate fallback family

#### 3. Same-route measure-range support only

What it would do:

- keep exact same-route candidates
- require positive overlap between:
  - `ApproachRoad_FROM_MEASURE` / `ApproachRoad_TO_MEASURE`
  - `TRANSPORT_EDGE_FROM_MSR` / `TRANSPORT_EDGE_TO_MSR`
- after latest-year filtering, choose the unique largest measure overlap

Evidence used:

- exact route support
- documented study-road measure ranges
- documented AADT transport-edge measure ranges

Observed behavior in this slice:

- `178` approach rows have at least one same-route measure-supported candidate
- `171` would match uniquely
- `7` would remain ambiguous

Why this is not sufficient by itself:

- selected winner distance distribution is still too broad:
  - median selected distance: about `883.7 ft`
  - `116` selected rows are more than `100 ft` away
  - `80` selected rows are more than `1,000 ft` away
  - max selected distance: about `34,949 ft`

Risks:

- route name plus measure overlap alone is not local enough
- some route/measure combinations recur far away and would produce false local matches

Assessment:

- stronger than geometry-only proximity
- not trustworthy without a local spatial gate

#### 4. Buffered overlap with a very small tolerance

What it would do:

- buffer the approach-row geometry by a very small distance
- treat same-route AADT geometries intersecting that buffer as candidates

Evidence used:

- exact route support
- tiny spatial tolerance instead of exact line overlap

Observed behavior in this slice:

- functionally similar to the same-route distance-threshold family above
- the core benefit is recovering near-parallel or slightly offset linework
- the core weakness is still ambiguity if no measure support is added

Assessment:

- bounded and auditable
- useful only as the spatial side of a combined rule
- not recommended by itself

#### 5. Same-route measure overlap plus tiny spatial distance gate

What it would do:

- keep exact same-route candidates only
- require positive measure overlap between the documented approach-road range and AADT transport-edge range
- require very small local geometry distance
- after latest-year filtering, choose the unique largest measure overlap and then the unique nearest candidate

Observed behavior in this slice:

- `<= 1 ft`: `46` candidate rows, `46` matched, `0` ambiguous
- `<= 2 ft`: `99` candidate rows, `96` matched, `3` ambiguous
- `<= 3 ft`: `172` candidate rows, `168` matched, `4` ambiguous
- `<= 5 ft`: identical to `<= 3 ft`

Important edge-case evidence:

- the `<= 3 ft` selected winner distance distribution stays tightly local:
  - median selected distance: about `1.93 ft`
  - p90 selected distance: about `2.82 ft`
  - max selected distance: about `2.92 ft`
- the six rows still unresolved at `<= 3 ft` do not have “almost local” missed candidates
  - nearest measure-supported candidates are about `60 ft`, `123 ft`, `453 ft`, `656 ft`, `709 ft`, and `2,880 ft`
- the remaining four ambiguous rows are duplicate-row artifacts, not competing nearby links
  - each ambiguous case collapses to one unique `LINKID`

Risks:

- it is a contract change, so it must be documented explicitly before adoption
- it still needs transparent unresolved handling for the six no-local-support rows
- candidate deduplication by local key plus `LINKID` should be added if this fallback is implemented, because the remaining ambiguous cases are repeated rows for the same link

Assessment:

- this is the only fallback family that is both locally constrained and measure-supported
- it stays within the bounded contract because it uses already-documented route fields, study-road measures, and AADT measure fields
- it appears likely to produce meaningful AADT matches in this slice without forcing statewide logic

### Recommended AADT next step

The smallest defensible next-step policy is:

1. stop treating exact line overlap as the only viable future path for this slice
2. keep current AADT outputs disabled until the fallback is explicitly approved in the docs
3. if AADT is re-enabled, use one bounded fallback only:
   - exact route support
   - positive numeric `AADT`
   - latest non-null `AADT_YR`
   - positive measure overlap on documented study-road and AADT transport-edge measures
   - local geometry distance `<= 3.0 ft`
   - unique largest measure overlap
   - unique nearest candidate after the measure filter
   - unresolved otherwise
4. if that fallback is implemented, deduplicate identical same-link candidates before ambiguity evaluation

### Recommendation status

- recommended immediate policy: keep current AADT disabled until the contract is updated
- recommended next design to implement after approval: bounded measure-plus-distance fallback with `<= 3.0 ft`

## StudyAreaID recommendation

### Current finding

The duplicate `StudyAreaID` rows are not a downstream key conflict. They are an upstream additive paired-row artifact:

- `140` duplicated `StudyAreaID` values
- each duplicated group has exactly two rows
- identifier fields agree across every group
- summed crash and attachment counts reconcile to the crash-classification source for the duplicated groups

### Recommended policy

This should be both documented and corrected upstream.

#### Why upstream correction is warranted

The source file is named and used like a one-row-per-study-area summary, but it is not one-row-per-study-area. That is a source-contract issue, not just a downstream convenience issue.

#### Smallest upstream correction

Upstream, emit one row per `StudyAreaID` in `signal_study_area_summary__approach_shaped.csv` by:

- keeping the non-null `FlowDirectionUsed`
- keeping the non-null `FlowProvenanceUsed`
- summing the prototype count fields across the paired rows
- failing if duplicate multiplicity is not exactly two or identifier fields conflict

This mirrors the downstream repair that the module is already forced to perform and is the smallest correction consistent with the evidence.

#### Downstream handling until upstream is fixed

- keep the current downstream collapse
- keep the explicit validation reporting
- treat it as a temporary source-artifact repair, not normal summary behavior

### Minimal documentation need

Future readers should be able to see, in active docs, that:

- the upstream summary currently emits additive paired rows
- downstream collapse exists because the source is not yet one-row-per-study-area
- the intended active contract is still one row per `StudyAreaID`

## Recommended next coding step

`c) bounded AADT fallback implementation`, but only after the contract is updated to authorize the measure-plus-distance rule.

If the team wants the strictly smallest code change before that, the next operational step is `b) upstream summary fix`.
