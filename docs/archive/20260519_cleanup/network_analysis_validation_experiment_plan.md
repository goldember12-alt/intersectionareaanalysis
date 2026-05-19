# Network Analysis Validation Experiment Plan

## Bounded Question

Can ArcGIS Network Dataset / Network Analyst behavior validate a small subset of the current Travelway-based `roadway_graph` scaffold without replacing the reproducible Python/GeoPandas workflow?

This is a future experiment plan only. It does not change methodology, code, or generated outputs.

## Purpose

Use ArcGIS Network Dataset logic as an external comparison tool for a small reviewed subset where connectivity behavior is hard to explain from the current Python graph alone.

The experiment should answer:

- do ArcGIS junctions agree with our `road_intersection` and `road_endpoint` nodes?
- do both systems identify the same under-connected cases?
- are disagreements caused by missing source geometry, unsplit intersections, endpoint near misses, grade separation, one-way/couplet representation, or signal-location problems?
- can one-way restriction logic be validated from Travelway fields without treating digitized direction as vehicle direction?

## Non-Goals

- Do not replace the GeoPandas pipeline.
- Do not use crash data.
- Do not use ArcGIS Online network sources.
- Do not use service areas as downstream functional area definitions.
- Do not infer upstream/downstream from ArcGIS route direction.
- Do not repair Travelway geometry automatically.
- Do not promote findings into methodology until reviewed.

## Candidate Subset

Use a deliberately small subset, such as 10 to 30 signals, selected from existing roadway graph review categories:

- clean TRUE reference signals
- zero-edge or one-edge signals
- two-edge suspect signals
- more-than-four adjacent-edge signals
- known edge-termination issue examples
- divided-carriageway pairing examples
- unpaired divided mainline examples
- ramp/frontage/service-road examples
- possible one-way pair candidates

The subset should be selected from roadway and signal scaffold outputs only. Crash records should not be used.

## Inputs

Candidate inputs:

- normalized Travelway roads for the selected area
- normalized signal points for the selected area
- current `roadway_graph` node and edge review outputs for comparison
- source Travelway fields relevant to facility, median, route, measures, ramps, access, couplets, and lane reversal

Fields to preserve for comparison:

- `RTE_NM`
- `RTE_ID`
- `EVENT_SOUR`
- `RTE_COMMON`
- `FROM_MEASURE`
- `TO_MEASURE`
- `RTE_FROM_M`
- `RTE_TO_MSR`
- `RIM_FACILI`
- `RIM_MEDIAN`
- `RIM_COUPLE`
- `RTE_CATEGO`
- `RTE_TYPE_N`
- `RTE_RAMP_C`
- `RIM_ACCESS`
- `LANE_REVER`
- `MEDIAN_WID`
- `MEDIAN_W_1`

Fields to search for before the experiment:

- explicit one-way restriction field
- from-to or to-from travel permission
- digitized direction field
- route direction field
- begin/end node fields
- lane count
- speed
- AADT or AADT linkage key

## Experiment Steps

1. Select the reviewed signal subset and document why each signal is included.
2. Clip or export only the needed Travelway and signal rows for the subset.
3. Build an ArcGIS feature dataset using a projected CRS suitable for distance checks.
4. Create a local ArcGIS Network Dataset from the Travelway subset.
5. Use endpoint connectivity as the baseline rule.
6. Add one-way restrictions only if a validated source field exists.
7. Add distance cost only as a neutral trace cost.
8. Build the Network Dataset.
9. Map and export or record Network Dataset junctions and edges for review.
10. Run route tests between selected signal-adjacent junctions and nearby anchors.
11. If one-way restrictions are configured, run paired along/against tests.
12. Compare ArcGIS results with Python `roadway_graph` nodes, signal-adjacent edges, and Step 5 candidate status.
13. Classify every disagreement.
14. Write a read-only validation memo before proposing any methodology change.

## Comparison Metrics

Recommended metrics:

- selected signal count
- Travelway source row count in subset
- ArcGIS edge count
- ArcGIS junction count
- Python graph node count in subset
- Python graph edge count in subset
- signals where both systems agree on usable connectivity
- signals where both systems agree on under-connectivity
- signals where ArcGIS connects but Python does not
- signals where Python connects but ArcGIS does not
- endpoint near-miss count
- crossing-without-junction count
- unsplit-intersection candidate count
- grade-separation or ramp ambiguity count
- one-way restriction test pass/fail count, if tested

## Disagreement Categories

Use these categories:

- `source_roadway_missing_leg`
- `endpoint_near_miss`
- `unsplit_intersection`
- `crossing_without_true_junction`
- `grade_separation_or_ramp_ambiguity`
- `signal_location_mismatch`
- `divided_carriageway_pairing_issue`
- `one_way_or_couplet_representation_issue`
- `route_measure_or_digitized_direction_conflict`
- `arcgis_configuration_difference`
- `python_graph_rule_difference`
- `unresolved_review_required`

## Expected Useful Outcomes

The most useful outcome is not a replacement network. It is a clearer explanation of difficult graph cases.

Expected outputs from a future experiment:

- a small comparison table by signal
- a disagreement-category summary
- mapped examples of endpoint near misses and unsplit intersections
- recommendations for future diagnostics
- explicit statement of what ArcGIS did not validate

## Acceptance Criteria

The experiment is useful if it:

- uses only local source data
- avoids crash data
- preserves current methodology boundaries
- explains at least some under-connected cases more clearly
- identifies whether one-way support fields are usable or not
- produces disagreement categories that can become future QA fields

The experiment is not useful if it:

- depends on ArcGIS Online network sources
- requires broad manual GUI state that cannot be documented
- hides unresolved cases
- treats route success as proof of downstream functional-area correctness
- expands into production replacement before the subset is reviewed

## Recommendation

Run this only after the current roadway graph review priorities are stable enough to choose representative subset cases. The first experiment should be validation-only, small, local, and read-only.

