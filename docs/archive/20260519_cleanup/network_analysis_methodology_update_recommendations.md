# Network Analysis Methodology Update Recommendations

## Bounded Question

Should ArcGIS Network Dataset / Network Analyst concepts change the current roadway_graph methodology?

Recommendation: adopt selected concepts as language, QA categories, and validation checks. Do not implement ArcGIS Network Analyst, do not make ArcGIS a dependency, and do not treat Network Analyst routing as current upstream/downstream truth.

## What Should Change

### Endpoint-Supported Connectivity

Current roadway_graph methodology should more explicitly say that connectivity is endpoint-supported or source-junction-supported, not geometry-implied. Crossing, overlapping, or nearly touching lines are review evidence until source topology supports a junction.

Recommended language:

- shared endpoints and explicit source-supported junctions are connectivity evidence
- visual crossings without a supported junction remain review-only
- near-miss endpoints and unsplit intersections are graph-build QA categories, not automatic repair targets

### Junction/Node QA As First-Class Validation

Roadway graph node QA should become a first-class validation surface. Network Dataset junction layers are a useful analogy because they make connectivity visible after a build.

Recommended QA categories:

- `endpoint_cluster`
- `near_miss_endpoint`
- `unsplit_intersection_candidate`
- `crossing_without_junction`
- `source_missing_leg`
- `isolated_endpoint_near_signal`
- `grade_separation_or_ramp_ambiguity`

### Build/Rebuild QA Discipline

After graph-rule changes, docs should require before/after build QA. This does not mean ArcGIS rebuilds; it means the Python graph run should be treated as a build artifact that needs validation.

Recommended before/after metrics:

- node counts by node type
- edge counts by edge type
- zero/one/two/high adjacent-edge signal counts
- TRUE/CONDITIONAL/FALSE signal eligibility counts
- short-fragment counts
- endpoint/junction counts
- near-miss and crossing-without-junction counts, when diagnostics exist
- field completeness for role/restriction support fields

### Direction Concepts

Docs should explicitly separate:

- digitized direction: source line vertex order
- route measure direction: increasing/decreasing measure behavior
- configured allowed travel direction: one-way/restriction evidence if validated
- inferred vehicle movement: not currently inferred from crash distributions
- signal-relative upstream/downstream: interpreted from roadway geometry/pairing only after scaffold validation

### One-Way And Restriction Fields

One-way, couplet, lane-reversal, and restriction-like fields should be support evidence for a future reviewed method, not current upstream/downstream truth.

Recommended stance:

- keep `RIM_COUPLE`, `RIM_FACILI`, `LANE_REVER`, route type/category, and any future one-way field as support evidence
- do not treat those fields as final direction
- design one-way/couplet handling as a separate reviewed method

### Network Analyst As Conceptual Analogy

Network Analyst is useful as a conceptual validation analogy:

- endpoint connectivity
- junction visibility
- along/against restriction logic
- build/rebuild validation
- route tests on tiny reviewed subsets

It should not be the production backend.

## What Should Not Change

- Do not replace the Python/GeoPandas roadway_graph workflow.
- Do not use ArcGIS Online network sources.
- Do not use service areas as downstream functional area definitions.
- Do not use Network Analyst route direction as upstream/downstream direction.
- Do not auto-repair missing Travelway legs, unsplit intersections, or near-miss endpoints.
- Do not use crash direction fields or crash distributions for current direction inference.

## Why

The current project needs reproducible, reviewable outputs with explicit unresolved cases. ArcGIS Network Dataset concepts are valuable because they sharpen graph-build QA language, but ArcGIS Network Analyst would introduce GUI state, licensing requirements, hidden configuration risk, and a routing/service-area frame that is not the current bounded question.

## Recommendation

Update methodology and workflow docs in a later documentation patch to adopt the QA vocabulary and direction-concept separation above. Keep the production method repository-native.
