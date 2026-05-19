# Codex-Native Review Without QGIS Plan

## Purpose

This plan describes how repository-native review can temporarily substitute for QGIS inspection while preserving current methodology boundaries.

It does not claim to replace later visual review. It provides tabular, geometry-derived, static artifacts that can identify likely false positives, rank candidates, and keep unresolved cases visible.

## Applicable Current Review

The first use is divided-pairing recovery review:

- input recovery candidates
- input recovery-enriched segment rows
- input accepted-pair outputs
- input roadway role classification
- input roadway graph nodes/edges as support context

The generated review folder is:

`work/output/roadway_graph/review/current/codex_native_divided_pairing_recovery_review/`

## Repository-Native Review Methods

Use only:

- Python
- pandas / GeoPandas / Shapely
- CSV summaries
- GeoJSON subsets
- markdown readouts
- optional static PNG plots
- optional lightweight HTML maps if a library is already available

Do not use:

- crash data
- crash direction fields
- crash distributions
- ArcGIS Network Analyst
- QGIS/manual map inspection as a required step

## Review Checks

### Candidate Metrics

Summarize candidates by:

- recovery method
- roadway role
- prior pairing status
- confidence
- route type/category
- anchor type
- recovery reason
- unresolved reason / likely blocker

### False-Positive Screen

Flag candidates that look like:

- cross-streets
- ramps/connectors
- frontage/service roads
- same-side or self-pairs
- weak projected overlap
- unstable side separation
- suspicious endpoint or non-TRUE opposite-anchor cases

### Ranked Review Queue

Rank candidates using:

- recovery confidence
- bearing/parallelism score
- projected overlap
- side score
- lateral separation
- false-positive flag count

The queue should include enough fields for later human inspection: segment IDs, reference signal, route names/stems, anchor types, length, bearing similarity, overlap, lateral separation, side-score stability, role class, prior pairing status, recovery reason, and recovery method.

### Still-Unresolved Diagnostics

Classify unresolved rows into likely blockers:

- route-stem/scope issue
- ambiguous side geometry
- missing opposite Travelway geometry
- endpoint/one-sided edge
- opposite anchor outside TRUE reference scope
- one-way/couplet candidate
- non-mainline role exclusion
- unknown

## Limits

Codex-native review cannot fully replace visual inspection because:

- tabular scores can miss context such as grade separation, lane geometry, unusual intersections, or source digitization artifacts
- local tangent sampling can misread curves, short segments, and intersection flares
- static GeoJSON subsets still require a viewer for final geometry interpretation
- one-way/couplet cases may require source-field review and visual confirmation

## What Eventually Needs Visual Confirmation

Later QGIS or equivalent visual review should check:

- whether low-confidence candidates are true opposite carriageways
- whether false-positive flags correctly identify cross-streets, ramps, frontage roads, and same-side pairs
- whether still-unresolved endpoint clusters reflect missing source geometry, unsplit intersections, or valid one-sided roads
- whether one-way/couplet candidates need a separate method

## Current Recommendation

Use Codex-native review to triage and document recovery behavior now. Do not promote recovered candidates into the default geometric direction model until a later visual review or stronger repository-native validation produces high-confidence evidence.
