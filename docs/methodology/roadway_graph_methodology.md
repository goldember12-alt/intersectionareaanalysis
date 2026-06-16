# Roadway Graph Methodology: Stable-Lineage Signal-Relative Scaffold

**Status: CURRENT ACTIVE.** This is the primary methodology document for the current roadway-graph scaffold. It describes the stable-lineage, recovery-first signal-relative scaffold used before crash/catchment assignment.

## Bounded Purpose

The roadway graph methodology builds and validates a signal-relative roadway scaffold for downstream functional area analysis.

This phase answers no-crash questions:

- which represented signals have defensible roadway evidence;
- which physical intersection approaches belong to each represented signal;
- which divided carriageways, ramps, route/facility changes, and source-line splits are subbranches rather than separate physical legs;
- which 50-foot bins are available in 0-1,000 ft primary and 1,000-2,500 ft sensitivity windows;
- which bins have route/measure identity, speed, AADT/exposure readiness, and stable Travelway lineage;
- which remaining losses are source/data limitations or holdouts.

It does not answer:

- which crashes belong to a signal or bin;
- final upstream/downstream crash interpretation;
- crash rates;
- regression/modeling claims;
- final policy distances.

## Current Review-Only Universe

The current review-only represented universe contains:

- base staged signals: 3,933
- represented signals: 2,739
- represented share: about 69.6%
- speed+AADT-ready signals: 2,739
- scaffold bins: 262,329

Final calibrated physical-leg distribution:

- one-leg: 234
- two-leg: 195
- three-leg: 798
- four-leg: 1,511
- five-plus: 1
- two-leg-or-less combined: 429

The distribution is plausible for the current represented universe: four-leg intersections dominate, three-leg intersections are common, five-plus over-splitting is near zero, and two-leg-or-less cases are carried with source/geometry explanation flags.

## Physical-Leg Definition

A physical leg is a signalized-intersection approach. It is not a graph edge, source Travelway row, route name, route/facility label, carriageway, or candidate association.

The scaffold separates:

- physical leg: geometry/bearing-defined signal approach;
- carriageway subbranch: divided carriageway, parallel one-way pair, ramp/slip lane, or source split under a physical approach;
- route/facility attributes: labels that describe a branch but should not define a physical leg by themselves;
- source lineage: stable Travelway/source-row evidence used to trace a bin back to source geometry.

Divided carriageways, ramps, route/facility changes, and source-line splits should generally be represented as subbranches or QA attributes under a physical leg unless source and geometry evidence supports a distinct physical approach.

## Intersection-Zone and Bearing Logic

Intersection-zone geometry is central to scaffold recovery and QA.

The method uses source Travelway, graph/reference, and candidate-bin evidence near the intersection zone to identify:

- expected physical approaches;
- missing source-to-candidate sectors;
- over-split bearing sectors;
- divided/carriageway subbranches;
- route/facility discontinuities;
- offset signal anchor problems;
- grade/mainline contamination;
- insufficient source geometry evidence.

Bearing and geometry are primary evidence. Route/facility labels are QA attributes. They can support a classification, but they should not be the primary grouping key for physical-leg definition.

## Recovery Branches

The scaffold recovery tree has three branches.

### Branch A: Direct Missing-Leg Recovery

Direct missing-leg recovery targets defensible source Travelway legs absent from the scaffold. It includes:

- ready-class intersection-zone missing-leg recovery;
- route/facility discontinuity recovery;
- offset-anchor recovery;
- offset/intersection-zone staged recovery;
- final cleanup missing-leg recovery.

Branch A is complete after final context refresh. Recovered bins remain review-only until a later explicit promotion decision.

### Branch B: Divided/Carriageway Normalization

Divided/carriageway normalization corrects false over-splitting by adding normalized physical-leg and subbranch labels while preserving every bin row.

It includes:

- divided/carriageway subbranch normalization;
- adjacent bearing-sector merge;
- candidate branch artifact grouping;
- ramp/slip-lane subbranch normalization where evidence supports it;
- source-line split same-physical-leg normalization.

Branch B is complete enough to proceed. Remaining uncertain cases are not forced; they are carried as Branch C limitations or manual-review classes.

### Branch C: Source Limitation and Holdout

Branch C contains cases where available source geometry, signal source records, or intersection complexity do not support additional defensible recovery.

Current remaining ledger:

- source_limited_holdout: 281
- grade_separated_or_mainline_contamination: 49
- still_insufficient_geometry_evidence: 54

Branch C is reduced to source/manual/external-data limitations for current purposes. These records should remain visible in downstream outputs.

## Stable Travelway Lineage

Stable Travelway lineage must be persisted at scaffold/bin generation time.

The stable-lineage scaffold regeneration validated the current requirement:

- regenerated signals: 2,739
- regenerated bins: 262,329
- high-confidence stable Travelway lineage: 262,327
- low-confidence lineage: 2
- unmatched bins: 0
- prior unmatched bins recovered: 111,200 / 111,200

Required lineage fields:

- `stable_travelway_id`
- `stable_signal_id`
- `source_signal_id`
- `stable_bin_id`
- `source_layer`
- `source_route_id`
- `source_route_name`
- `source_route_common`
- `source_measure_start`
- `source_measure_end`
- `source_feature_local_fid`
- `geometry_hash`
- `lineage_match_method`
- `lineage_confidence`

GeoPackage `fid` is package-local and should be preserved only as `source_feature_local_fid`. It is not sufficient as stable lineage by itself.

Stable lineage supports:

- source-specific map review;
- access-to-Travelway diagnostics;
- source/data limitation reporting;
- future crash/catchment assignment;
- reproducible review and paper exhibits.

## Speed, AADT, and Exposure Context

The current represented universe is speed+AADT-ready for all 2,739 represented signals. Speed and AADT/exposure are review-only context assignments attached after scaffold recovery and lineage validation.

Context should not be used to force scaffold recovery. It is a readiness layer that indicates whether a signal/bin can support downstream descriptive or comparison-ready analysis once access and crash/catchment methods are finalized.

## Access Methodology Boundary

Access is a context layer, not a scaffold-recovery driver.

Current evidence shows strong access source coverage limitations and major-route bias:

- untyped source points: 70,595
- typed v2 source points: 28,762
- nearly all access source points appear to be on major route classes.

Current access doctrine:

- Untyped access remains the broad count/density layer.
- Typed v2 access remains an enrichment layer.
- Spatial 100 ft catchment is the conservative primary review product.
- Conservative Travelway-windowed access is source-identity sensitivity/enrichment evidence.
- Broad Travelway-normalized access is source-coverage diagnostic evidence only because it has long-route overcapture risk.
- Multi-assignment is allowed; forcing one access point to one signal/bin is too strict.
- Unweighted/double-counted and source-preserving weighted products remain separate.

Typed v2 category mapping currently treats raw `R` and `RC` as `right_in_right_out`. Raw `I`, `M`, `S`, `AS`, and `AU` remain `other_review`. Raw codes must be preserved beside corrected categories.

## Crash Boundary

The roadway graph methodology does not read crash records and does not assign crashes.

Crash assignment, crash catchments, upstream/downstream interpretation, crash rates, and modeling should only be added after:

- the stable-lineage scaffold is selected as the target universe;
- access doctrine is documented;
- source/data limitation flags are carried forward;
- analysis windows and output units are explicitly defined.

Crash findings should inform downstream functional area guidance. They should not be treated as the sole basis for calculating downstream functional area distance.

## Map-Review Lessons

Manual review is part of the methodology because it reveals source-system and ownership limits that automated geometry alone can miss.

Current examples:

- `signal_000045`: demonstrated the need for stable source Travelway lineage. FID 52369 remains candidate/ambiguous; FID 46419 is the best match for 50 bins.
- `signal_002692`: complex multi-signal ownership and source-signal limitation; do not force opposite carriageway onto the wrong signal.
- Wellington Road / University Boulevard: HMMS source signal exists in normalized/staged records but not the represented universe; this is a signal-source lineage and complex exclusion issue.

## Validation Expectations

Each scaffold or context refresh should report:

- signal counts and bin counts;
- physical-leg distribution;
- expected-vs-represented alignment;
- recovered bins and normalized bins by stream;
- source/data limitation counts;
- stable Travelway lineage completeness;
- route/measure, speed, AADT/exposure readiness;
- geometry availability;
- access source coverage and assignment rule caveats when access is included;
- confirmation that crash records and crash direction fields were not used unless the task explicitly allows them.

Review should focus on:

- two-leg-or-less explanation classes;
- grade/mainline holdouts;
- still-insufficient source geometry;
- source signal lineage exclusions;
- access source coverage gaps;
- broad Travelway-normalized overcapture risk.

## Relationship To Prior Work

The older directed-segment and Step 5 graph-foundation workflows are superseded for current scaffold methodology. They remain useful as historical references and comparison prototypes, especially for documenting why divided-road-only or nearest-route assumptions were insufficient.

Current work should not restore old TRUE-reference, divided-pairing-next, or crash-direction-dependent assumptions unless a bounded task explicitly re-evaluates them.
