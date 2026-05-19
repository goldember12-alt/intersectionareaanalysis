# Directional Scaffold QA Findings

**Status:** Read-only QA and conservative prototype usable surface for the reference-signal-centered directional scaffold.

## Bounded Question

This module validates the current directional scaffold candidates and separates non-review, non-blocked records into a prototype usable surface for later crash assignment by direction. It does not read crash data, read crash assignment outputs, use crash direction fields, infer direction from crashes, repair geometry, force divided pairs, or change scaffold construction logic.

## Prototype Usable Surface

- Prototype usable directional segments: 4828
- Prototype usable 50-ft bins: 208340
- TRUE reference signals represented: 976
- Usable downstream records: 2414
- Usable upstream records: 2414
- Usable divided physical records: 810
- Usable undivided pseudo-direction records: 4018
- Usable non-TRUE/non-signal/endpoint far-anchor records: 4285

Method-allowed anchor relaxation is retained in the usable surface when the record is otherwise non-review and non-blocked.

## Exclusions

- Excluded directional segments: 2972
- Excluded directional bins: 96212

Main exclusion reasons:

- review_flag_true: 2972 segments
- divided_physical_direction_not_accepted_or_unpaired: 2966 segments
- roadway_representation_not_prototype_usable: 2966 segments
- low_confidence_divided_recovery_review_only: 88 segments
- unknown_roadway_role: 6 segments

## QA Results

- ID uniqueness failures: 0
- Prototype pair symmetry failures: 0
- Prototype bin ordering failures: 0
- Blocked/review/low-confidence recovery/unknown-role leakage into usable surface: 0

## Recommendation

The prototype usable directional surface is ready for a later crash-assignment-by-direction prototype, provided that later module still remains spatial/directional-assignment only and keeps excluded rows out.
