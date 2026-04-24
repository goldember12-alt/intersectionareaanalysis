# Divided-Road Local Flow-Orientation Method Comparison

## Bounded question

The current bounded question is:

- for divided roadways near signalized intersections, what is the simplest truthful way to support a signal-centered near-signal evidence model with enough local flow-orientation inference that crashes can later be interpreted as approaching or leaving the signal, or upstream or downstream relative to it, using the reduced active slice

This plan is for bounded comparison only.
It is not a statewide method, not a full roadway flow-orientation framework, and not an Oracle redesign.

## Reduced-slice dependency map

Base slice outputs:

- `Study_Roads_Divided`
- `Study_Signals`
- `Study_Signals_NearestRoad`

These are still roadway-centered intermediate outputs, but conceptually they support a signal-centered near-signal evidence model rather than a standalone roadway-direction engine.

Evidence available alongside the reduced slice:

- normalized `crashes`
- optional AADT diagnostic source
- optional traffic-volume GeoJSON and shapefile diagnostics

Immediate rule:

- no candidate method may require link restoration, Oracle prep, Stage 1C packaging, or downstream segment-ladder reconstruction in order to be tested first

## Candidate methods

### 1. Crash direction-of-travel only

- Evidence used: crash direction-of-travel attributes near the divided study roads and nearest-road signal context
- Strengths: direct observed travel evidence; simple to explain; low implementation burden
- Weaknesses: mixed crash types can point across maneuvers rather than along carriageway travel; sparse coverage on low-crash corridors
- Assumptions: crash direction-of-travel is recorded consistently enough to represent carriageway travel direction
- Data dependencies: reduced slice outputs plus normalized `crashes`
- Ambiguity risks: turning crashes, crossing crashes, offset-location noise, and thin sample sizes can create false agreement
- Validation burden: low to moderate
- Refuse to assign when: crash count is too small, strong directional disagreement exists, or crash locations do not land cleanly on one carriageway-side context

### 2. Crash direction-of-travel plus single-vehicle plus straight-ahead subset

- Evidence used: crash direction-of-travel filtered to single-vehicle and straight-ahead style cases, then compared within the reduced slice
- Strengths: strongest direct empirical candidate for a first bounded experiment; cleaner than all-crash direction evidence; easier to defend corridor by corridor; best current primary signal for later approaching-versus-leaving interpretation
- Weaknesses: coverage drops; some corridors may have too few qualifying crashes
- Assumptions: the filtered subset is more likely to reflect true carriageway travel than turning or multi-vehicle conflict cases
- Data dependencies: reduced slice outputs plus normalized `crashes`
- Ambiguity risks: low-volume corridors may remain unresolved; crash coding quality still matters
- Validation burden: moderate
- Refuse to assign when: filtered crashes are absent, too sparse, or internally contradictory

### 3. Roadway naming or directional-context support

- Evidence used: route naming, directional suffixes, route IDs, and related roadway context carried on study roads and nearest-road signal context
- Strengths: available without crash density; cheap to compute; useful as support and conflict flagging
- Weaknesses: naming may be incomplete, non-directional, or inconsistent with carriageway-specific interpretation; not strong enough to be treated as truth by itself in the current bounded scope
- Assumptions: naming conventions correlate with carriageway orientation often enough to be helpful
- Data dependencies: reduced slice outputs only
- Ambiguity risks: route names may describe corridor identity rather than carriageway side; suffix conventions are inconsistent
- Validation burden: low
- Refuse to assign when: naming is absent, non-directional, contradictory, or only corridor-level rather than carriageway-level

### 4. Supplemental traffic-volume support

- Evidence used: traffic-volume GeoJSON or shapefile lineage fields plus optional AADT-side bridge diagnostics
- Strengths: may add route or direction support where crash evidence is sparse; useful comparison candidate
- Weaknesses: current bounded inspections do not show a solved direct bridge-key path; support value is still provisional
- Assumptions: traffic-volume lineage can support carriageway interpretation without reopening Oracle-shaped architecture
- Data dependencies: optional diagnostics plus reduced slice outputs where joinability is justified
- Ambiguity risks: apparent direction fields may still be network-support fields rather than trustworthy carriageway labels
- Validation burden: moderate to high
- Refuse to assign when: the support is only indirect, only route-level, or requires forced join assumptions

### 5. Hybrid empirical method

- Evidence used: filtered crash direction evidence as primary, roadway naming/context as secondary support, traffic-volume support as tertiary tie-break or conflict flag only
- Strengths: best likely balance of truthfulness and coverage once simpler candidates are understood
- Weaknesses: easiest place for hidden complexity to creep back in; requires clear evidence hierarchy
- Assumptions: evidence sources should not be treated as equal; strong evidence must dominate weak support
- Data dependencies: reduced slice outputs, normalized `crashes`, and optional diagnostics
- Ambiguity risks: weak support can be mistaken for final truth if hierarchy is not explicit
- Validation burden: moderate
- Refuse to assign when: strong evidence conflicts, only weak support exists, or tie-break logic becomes ad hoc

## Validation standard

### Truthful enough

For this bounded phase, truthful enough means:

- assigned labels are backed by explicit strong evidence, not convenience
- unresolved cases remain unresolved instead of being forced
- corridor-level continuity is plausible on mapped spot checks
- conflict cases are visible and countable
- assigned coverage is less important than assignment honesty
- cardinal labels are used only as intermediate orientation aids for later signal-relative interpretation

### Strong vs weak evidence

Strong evidence:

- filtered crash direction-of-travel evidence with internal agreement on one carriageway-side interpretation
- repeated agreement among multiple qualifying crashes on the same study-road context

Weak evidence:

- roadway naming or directional suffix support by itself
- traffic-volume directional fields that have not yet proved carriageway-level truth
- any single-source support field that cannot explain ambiguity clearly

### Success and unresolved definitions

Successful assignment:

- one carriageway-side or interim cardinal label is supported by strong evidence strongly enough to support later signal-relative interpretation
- no competing strong evidence points the other way
- nearest-road and corridor continuity checks do not immediately contradict the label

Unresolved:

- no strong evidence is present
- strong evidence conflicts
- only weak support exists
- the study-road context is too sparse or too ambiguous for a truthful label

### First sample corridors

Use three small corridor buckets first, each with about 3 to 5 consecutive divided-road signals:

- one Norfolk city-signal divided arterial corridor
- one Hampton city-signal divided arterial corridor
- one VDOT or HMMS divided arterial corridor outside the city-only signal inventories

Exact named corridors should be chosen only after the reduced slice is rebuilt in the active Python environment, using the actual `Study_Roads_Divided` and `Study_Signals_NearestRoad` outputs.

### Metrics to report

- study-road rows inspected
- signal count inspected
- qualifying crash count
- assigned count
- unresolved count
- assigned rate
- unresolved rate
- strong-evidence conflict rate
- weak-support-only count
- corridor continuity breaks
- spot-check findings by corridor

### Initial acceptance targets

- strong-evidence conflict rate on assigned cases: ideally 5% or less
- unresolved rate: acceptable up to 40% in the first bounded pass
- weak-support-only assignments: 0

If the method needs weak-support-only assignments to look complete, it is not ready.

## Current Read After Bounded Empirical Work

The recent bounded empirical work should now be read as an answer to a supporting subproblem rather than as the final architecture.

Current practical conclusions:

- local non-Oracle flow inference is viable enough to continue in at least some divided-road contexts
- strict unanimity is trustworthy but sparse
- a 90% dominant-share relaxation is a promising bounded empirical variant
- single-vehicle-clean cases are diagnostically useful
- route-name fallback remains support-only and low-trust

That is enough to treat local flow orientation as a viable supporting input into a later signal-centered upstream/downstream workflow. It is not a reason to reframe the project as a general roadway-directionality engine.

## Recommended first experiment

Test first:

- crash direction-of-travel plus single-vehicle plus straight-ahead subset

Why:

- it is the simplest strong-evidence candidate for divided roads
- it avoids reopening Oracle-shaped architecture
- it is easier to validate honestly than a traffic-volume-led or fully hybrid method
- roadway naming can still be used as support and conflict flagging without becoming the primary label source
- it best fits the current goal of inferring signal-relative flow orientation conservatively enough for later approaching-versus-leaving classification

Bounded data subset:

- the three initial corridor buckets above
- reduced slice outputs for those corridors
- normalized crashes within the same bounded corridor or signal context

Required outputs:

- one corridor-level assignment table with assigned and unresolved labels
- one evidence summary per corridor
- one conflict summary
- one map-review or spot-check note per corridor

## Next implementation sequence

1. Rebuild the reduced slice with `stage-inputs`, `normalize-stage`, `build-study-slice`, and `enrich-study-signals-nearest-road`.
2. Choose the first three bounded divided-road corridors from the rebuilt slice outputs.
3. Define the crash filtering rule for the single-vehicle straight-ahead evidence subset.
4. Attach filtered crash evidence to the bounded corridor subset and summarize agreement by study-road context.
5. Produce assigned versus unresolved orientation labels with no hybrid tie-breaking beyond support flagging.
6. Review corridor maps and conflict rows manually.
7. Compare the filtered-crash candidate against crash-direction-only and roadway-context-only summaries on the same subset.

## Not yet

Do not touch yet:

- statewide flow-orientation labeling
- Oracle revival
- link restoration
- segment lineage inheritance
- Stage 1C crash or access ladders
- packaging or handoff families
- any method that forces labels for coverage
