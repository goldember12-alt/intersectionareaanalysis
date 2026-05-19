# Network Analysis To Roadway Graph Documentation Patch Plan

## Bounded Question

Which current docs should be updated later to reflect useful Network-Dataset-inspired concepts without adopting ArcGIS Network Analyst?

This is a patch plan only. It does not modify current methodology docs.

## Proposed File-By-File Edits

### `docs/methodology/overview_methodology.md`

Add a short subsection under the graph-first scaffold explaining:

- connectivity is endpoint-supported, not geometry-implied
- visual crossings and near misses are review categories
- digitized direction, route measure direction, allowed travel direction, and inferred movement are separate concepts
- Network Analyst is a conceptual analogy, not the backend

### `docs/methodology/roadway_graph_methodology.md`

Add or revise methodology detail for:

- endpoint-supported connectivity
- node/junction QA categories
- build/rebuild QA after graph-rule changes
- one-way/couplet fields as support evidence only
- undivided centerline default and divided carriageway pairing distinction

### `docs/workflow/active_workflow.md`

Add operational wording that future graph-rule changes should report before/after build QA:

- node counts
- edge counts
- signal eligibility counts
- short fragments
- endpoint clusters
- near-miss endpoints
- crossing-without-junction candidates

### `docs/workflow/roadway_graph_workflow.md`

Add a validation section for graph-build QA inspired by Network Dataset build/rebuild discipline:

- run-level build summary
- before/after comparison when rules change
- node-type and edge-type summaries
- explicit unresolved/review-only categories

### `docs/workflow/roadway_graph_divided_carriageway_pairing.md`

Add a note that divided-pairing uses roadway geometry and accepted pairing evidence. It does not use digitized direction, route measure direction, one-way fields, or crash direction as final truth.

### `docs/workflow/roadway_graph_divided_pairing_recovery.md`

Add a note that route-stem and anchor clustering are candidate generation only. Endpoint/junction support and stable local geometry are needed before promotion.

### `docs/workflow/roadway_graph_roadway_role_classification.md`

Add a note that one-way/couplet/restriction-like fields belong in role/support evidence and should feed a separate reviewed one-way method, not generic divided-pairing recovery.

### `docs/design/current_design_index.md`

Add links to:

- `network_analysis_reference_audit.md`
- `network_analysis_methodology_update_recommendations.md`
- `network_analysis_to_roadway_graph_doc_patch_plan.md`
- `codex_native_review_without_qgis_plan.md`

## Draft Snippets For Later Patch

### Endpoint Connectivity

```markdown
Connectivity is endpoint-supported or source-junction-supported. A visual crossing, overlap, or near miss is not a graph junction unless source topology supports it. The workflow should preserve near-miss endpoints, unsplit intersections, crossing-without-junction cases, endpoint clusters, and source-missing-leg cases as review categories.
```

### Direction Separation

```markdown
Digitized line direction, route measure direction, configured allowed travel direction, and inferred vehicle movement are separate concepts. The current workflow may use line order for geometry operations and route/one-way fields as support evidence, but upstream/downstream interpretation must come from validated roadway geometry and pairing, not crash direction or unvalidated one-way assumptions.
```

### Build/Rebuild QA

```markdown
Every graph-rule change should be treated as a rebuild requiring before/after QA: node counts by type, edge counts by type, signal eligibility counts, short-fragment counts, endpoint/junction counts, unresolved/review-only categories, and field completeness for any support evidence introduced by the rule change.
```

## Non-Changes

- Do not add ArcGIS Network Analyst as a dependency.
- Do not require QGIS/manual GIS review for repository-native review outputs.
- Do not use Network Analyst service areas as downstream functional areas.
- Do not use one-way/restriction fields as current upstream/downstream truth.
