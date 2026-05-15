# Endpoint/Junction QA Methodology Recommendations

## Recommendation

Update current roadway_graph methodology docs in a later documentation patch to make endpoint/junction QA an explicit graph-build validation surface. Do not make ArcGIS Network Analyst or QGIS a production dependency, and do not automatically repair geometry from this diagnostic.

## Recommended Documentation Changes

- Add endpoint-supported connectivity language: shared endpoints and explicit source-supported junctions are connectivity evidence; crossings and near misses are review evidence.
- Add node/junction QA as a first-class validation step after roadway graph builds and after any graph-rule change.
- Add review categories for `near_miss_endpoint`, `endpoint_cluster`, `unsplit_intersection_candidate`, `crossing_without_supported_junction`, `source_missing_leg_candidate`, `signal_offset_candidate`, and `divided_carriageway_representation_issue`.
- Explain source-missing-leg handling separately from valid dead ends and one-sided edges.
- State the no-automatic-repair policy: do not snap endpoints, split lines, connect crossings, or promote divided pairs without reviewed source support.
- Require build/rebuild QA comparisons after graph construction rule changes: node counts by type, edge counts, adjacent-edge signal counts, signal offset counts, endpoint clusters, near-miss endpoints, unsplit/crossing review candidates, and Step 5 eligibility counts.

## What Should Not Change

- Do not treat crossing geometry as supported graph connectivity.
- Do not use crash direction fields or crash distributions for endpoint/junction QA.
- Do not promote low-confidence divided-pairing recovery candidates.
- Do not replace the repository-native Python/GeoPandas roadway_graph workflow with ArcGIS Network Analyst.

## Why

The divided-pairing recovery review found no promotable high/medium candidates. The next bottleneck is graph topology, source-leg completeness, and endpoint/junction evidence. Making those categories explicit will improve validation without broadening the method or hiding unresolved cases.
