# Network Analysis Reference Audit

## Bounded Question

This audit asks whether the ArcGIS Network Dataset / Network Analyst reference materials in `C:\Users\Jameson.Clements\Documents\source\NetworksGIS\DetailedVersionOfNetworks\NetworkAnalysis` contain concepts, fields, or workflow checks that could improve the current `roadway_graph` methodology.

It does not change the roadway graph methodology. It does not implement code. It does not modify generated outputs. It does not read crash data.

## Reference Materials Reviewed

- `11A Network Dataset Theory.pptx`
- `11B Network Dataset Creation.pptx`
- `11C Network Dataset Rebuild.pptx`
- `11D NetworkDataset Use.pptx`
- `Network Anlaysis Answers.docx`

These materials are instructional examples for creating, building, rebuilding, and using a small ArcGIS transportation network dataset. They are not a VDOT production Network Dataset specification. The useful value is conceptual: how ArcGIS formalizes connectivity, restrictions, costs, travel modes, junction inspection, and build/rebuild QA.

## Current Project Context

The active method remains graph-first:

full Travelway graph -> signal graph association -> eligibility gating -> TRUE reference signals -> signal-to-anchor segments -> roadway role classification -> crash-ready segment/bin subset -> divided carriageway pairing where geometry supports it -> undivided roads treated as shared centerline by default -> crashes added only after roadway scaffold is clean -> upstream/downstream interpreted using roadway geometry, not crash direction.

## Immediately Useful Ideas

### Endpoint Connectivity As An Explicit Rule

The Network Dataset materials emphasize that overlapping lines do not automatically connect. Lines connect where the network recognizes a junction, especially at endpoints or configured connectivity points. This aligns strongly with the current graph-first issue set.

Immediate implication for `roadway_graph` design:

- distinguish endpoint-shared connectivity from simple geometric crossing
- preserve `road_intersection` nodes only when source evidence supports a true connection
- add or strengthen diagnostics for cases where roads cross, touch, overlap, or nearly touch but do not create a supported graph junction
- keep unsplit-intersection and near-miss endpoint cases visible as review categories rather than silently repairing them

This is already consistent with the current edge-termination refinement, which refuses to treat simple crossings as true intersections. The Network Dataset framing gives a clearer vocabulary for that rule.

### Junction Layers As QA Evidence

The materials show Network Dataset junctions as a visible layer for inspecting connectivity. This maps directly to our `roadway_graph_nodes.csv` and QGIS node review layers.

Immediate implication:

- make node-type QA a first-class review concept
- compare counts and mapped examples of `road_intersection`, `road_endpoint`, `signal`, and `unresolved`
- flag suspicious cases such as endpoint clusters, isolated endpoints near other endpoints, and lines crossing without a node

This does not require Network Analyst adoption. It suggests better QA naming and review framing for the Python graph.

### One-Way Restrictions Should Be Direction-Specific Support Evidence

The creation deck defines one-way restrictions with separate along/against evaluators using an `ONEWAY` field:

- along restricted when `ONEWAY` is in `N`, `TF`, or `T`
- against restricted when `ONEWAY` is in `N`, `FT`, or `F`

This is relevant because our current method treats line order as source geometry order, not vehicle movement. If Travelway contains one-way or route-direction fields, they may support a later reviewed one-way method, but they should not be used to infer upstream/downstream now.

Immediate implication:

- keep `RIM_COUPLE`, `RIM_FACILI`, and `LANE_REVER` as role/directionality support fields
- search for any Travelway field equivalent to `ONEWAY`, `FT`, `TF`, `F`, `T`, or one-way restrictions before designing a one-way pair method
- separate "digitized direction", "route measure direction", and "allowed vehicle travel direction"

### Build/Rebuild QA Is A Good Mental Model

The ArcGIS materials separate creating a network dataset from building or rebuilding it after attributes change. They also recommend testing whether connectivity and restrictions work after build.

Immediate implication:

- treat graph construction QA as a build validation step, not as optional reporting
- after any future graph-rule change, compare node counts, edge counts, zero/one/two/high-edge signal counts, short-fragment counts, endpoint/junction counts, and restriction-support field completeness
- keep run metadata that states which graph attributes were used

The current workflow already has run summaries and review outputs; Network Dataset practice supports making this more explicit.

## Possible Future Validation Experiments

### Small ArcGIS Network Analyst Subset

Network Analyst could be used on a small, reviewed subset as a validation tool, not as a replacement pipeline.

Candidate experiment:

- select 10 to 30 TRUE reference signals plus known under-connected, over-connected, ramp/frontage, and divided-carriageway cases
- build a small ArcGIS Network Dataset from the same Travelway subset
- configure endpoint connectivity only unless a reviewed case explicitly needs another connectivity policy
- configure one-way restrictions only if a reliable source field is found
- run short routes or service-area traces from signal-adjacent junctions to nearby anchors
- compare ArcGIS junctions and reachable edges against `roadway_graph` nodes, signal-adjacent edges, and Step 5 candidate rows

The experiment should report disagreement categories, not attempt to declare ArcGIS as truth.

### Under-Connected Travelway Diagnosis

ArcGIS Network Dataset logic may help explain under-connected Travelway cases by making the difference between source geometry incompleteness and network-connectivity configuration more visible.

Potential categories:

- missing road leg in Travelway source
- line present but not split at the intersection
- endpoint near miss
- overlapping or crossing line without a network junction
- grade separation or ramp case where non-connectivity is correct
- signal point offset from the actual junction
- divided carriageway represented as separate one-way edges requiring pair logic

This can improve review language without changing the current graph-first method.

### Cost/Impedance Sanity Checks

The materials use distance, free-flow time, congested time, speed, AADT, and lane count as cost fields for service areas. For the current roadway scaffold, impedance should not drive core graph construction. It may be useful later for validation or proposal-facing context.

Possible limited use:

- compare geometry length to measure-derived length where available
- use posted speed or speed-limit context only for future downstream band families, not for graph adjacency
- use AADT, speed, and lanes as later contextual variables, not as graph repair evidence

## Concepts That Should Not Be Adopted Now

### Replacing GeoPandas With Network Analyst

Network Analyst should not replace the reproducible Python/GeoPandas pipeline. ArcGIS configuration is harder to diff, harder to run headlessly across environments, and easier to change through GUI state. The current project needs transparent, versioned, reproducible outputs with visible unresolved cases.

### Service Areas As Downstream Functional Areas

The Network Analyst service-area example is about reachable population by travel cost. That is not the same as signal-relative downstream functional area. Service areas may be useful for unrelated accessibility analysis, but they would overcomplicate the current project if imported as a downstream-area definition.

### Travel Time Or Congestion Costs As Core Graph Criteria

The current bounded question is roadway scaffold construction near signals. Distance, speed, congestion time, and capacity are not needed to decide whether a signal has usable adjacent roadway geometry. These fields should remain contextual or future validation inputs.

### Automatic Network Repair

ArcGIS can help reveal connectivity problems, but the current method should not automatically invent missing legs, split every geometric crossing, or force connectivity where the source does not support it. Missing source roadway evidence should remain unresolved or review-only.

### Treating Digitized Direction As Vehicle Direction

The materials show digitized direction as a display concept and one-way restrictions as configured rules. That distinction is important. Our current method should not treat line order, from/to vertex order, or route measure direction as true vehicle travel direction.

## Answers To The Requested Questions

### 1. Relevant Network Dataset Concepts

Relevant concepts are:

- edges, junctions, and connectivity
- endpoint connectivity
- visible junction inspection
- direction-specific one-way restrictions
- digitized direction as a separate concept from travel direction
- cost/impedance attributes
- travel modes
- create once, build/rebuild after attribute or rule changes
- post-build route tests for connectivity and restrictions

The most relevant concepts are connectivity, junction QA, endpoint behavior, one-way restriction logic, and build/rebuild validation.

### 2. Concepts Not Relevant Or Too Complex Now

Not relevant or too complex for the current roadway graph methodology:

- service area analysis as an analysis unit
- population summarization within service areas
- congestion-time equations as graph construction rules
- travel-mode modeling as a replacement for signal-relative segment/bin construction
- broad impedance optimization
- ArcGIS Online network sources
- GUI-configured Network Dataset state as the production analytical backend

### 3. Specific Handling Ideas

Graph junctions:

- use Network Dataset junction logic as a QA analogy
- keep only source-supported junctions as true graph intersections
- add review categories for unsplit intersections, crossing-without-junction, endpoint clusters, and near misses

Endpoint connectivity:

- endpoint connectivity is immediately relevant
- current endpoint-shared node logic should be compared against near-miss and unsplit cases
- do not assume overlapping lines connect

One-way restrictions:

- relevant as support evidence for a future reviewed one-way method
- compare Travelway one-way/couplet/lane-reversal fields to ArcGIS-style along/against restrictions
- do not use one-way rules to infer upstream/downstream in the current methodology

Digitized direction:

- useful only as a source geometry property
- separate it from route measure direction and vehicle travel direction
- preserve line order for geometry handling, not interpretation

Divided versus undivided representation:

- relevant because Network Datasets model separate edges and restrictions, while our method must distinguish divided carriageways from undivided shared centerlines
- use Travelway facility, median, couplet, ramp, and route-type fields to classify roles before any pairing recovery

Impedance/cost fields:

- useful for future validation or proposal-facing distance/time bands
- not needed for graph adjacency or Step 5 eligibility

Build/rebuild QA:

- directly useful as a workflow discipline
- every graph-rule change should have before/after build QA and spot checks

### 4. Under-Connected Travelway Cases

Yes. Network Dataset logic can help explain under-connected cases by distinguishing:

- missing source geometry
- endpoint near misses
- unsplit intersections
- geometric crossings without true junctions
- grade separation
- signal-location mismatch
- divided carriageway representation issues

It cannot solve missing Travelway legs by itself. It can make the failure mode clearer.

### 5. Network Analyst As A Small Validation Tool

Yes, but only as a small external validation experiment.

Recommended use:

- build a tiny reviewed subset
- compare ArcGIS junctions/reachable routes with Python graph nodes/edges
- use disagreement categories to improve QA and documentation

Not recommended:

- using Network Analyst as the production graph builder
- depending on ArcGIS Online network sources
- using service areas as the downstream functional area method

### 6. Travelway Fields To Compare

Fields already used or referenced in `roadway_graph` that should be compared to Network Dataset examples:

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

Fields to search for or confirm in source Travelway before a Network Dataset comparison:

- one-way restriction equivalent to `ONEWAY`
- explicit from-to or to-from travel permission
- digitized direction field
- route direction or route side field
- measure direction fields
- begin/end node fields
- facility type
- divided/undivided status
- lane count
- speed
- AADT or linkable AADT key

## Risks Of Relying On Network Analyst

- GUI configuration may not be fully visible in Git.
- ArcGIS environment and license requirements reduce reproducibility.
- Network build state can drift from source tables unless exported and checked.
- ArcGIS Online network sources could introduce undocumented data and assumptions.
- Travel modes and impedance settings may answer accessibility questions rather than the bounded downstream functional area scaffold question.
- Automated routability can hide unresolved source geometry problems that the current method intentionally exposes.
- One-way and cost rules can create a false sense of directional certainty if their source fields are not validated.

## Recommendation

Use the Network Dataset materials as design reference for QA language and small validation experiments.

Do not adopt Network Analyst as the production methodology. Do not change `roadway_graph` yet. The strongest immediate value is to improve future diagnostics around endpoint connectivity, junction construction, one-way support fields, digitized direction, and build/rebuild QA.

