# Doc Classification 2026-04-16

This inventory distinguishes three things:

1. current working-tree status
2. recommended disposition for a bounded recovery stage
3. why a file should be kept active, kept local-only, or deferred

It does not assume that every current doc belongs in committed history immediately.
The recommended dispositions below reflect the post-edit state after this bounded recovery pass.

## Minimal repair set review

| path | current status | recommended disposition | reason |
|---|---|---|---|
| `.gitignore` | tracked file with working-tree modification | keep as-is | the `docs/` unmasking repair is correct and should be retained |
| `src/active/__main__.py` | tracked file with working-tree modification | keep as-is | `check-parity` exposure is a justified minimal CLI repair |
| `README.md` | working-tree addition | keep with edits | useful repo map; should accurately describe the redesign docs as working-tree recovery material |
| `docs/README.md` | working-tree addition | keep with edits | useful docs index; should stay scoped to files that actually exist in the working tree |
| `docs/methodology/overview_methodology.md` | working-tree addition | keep as-is | strongest current methodology document; directly aligned with the redesign posture |
| `docs/recovery_audit_20260416.md` | working-tree addition | keep with edits | valuable audit record, but it must match the present working tree rather than the earlier draft state |

## Active docs classification

| path | current status | recommended disposition | reason |
|---|---|---|---|
| `docs/README.md` | working-tree addition | keep now | current index is useful and now explicitly frames this tree as working-tree redesign documentation |
| `docs/methodology/overview_methodology.md` | working-tree addition | keep now | this is the clearest high-level redesign guidance in the repo |
| `docs/workflow/active_workflow.md` | untracked working-tree doc | keep now | central workflow note; now explicitly distinguishes expected regenerated outputs from outputs actually present in the working tree |
| `docs/recovery_audit_20260416.md` | working-tree addition | keep now | now distinguishes committed `c209803` from current working-tree repairs and no longer claims a root methodology shim exists |
| `docs/repo_redesign_plan.md` | untracked working-tree doc | keep now | still useful redesign structure guidance and now points to `docs/methodology/overview_methodology.md` |
| `docs/methodology/flow_method_comparison.md` | untracked working-tree doc | keep now | strong bounded-method note; consistent with the current redesign posture |
| `docs/workflow/staging_and_normalization_contract.md` | untracked working-tree doc | keep now | useful staging contract; now narrowed to the current required minimal slice while leaving supplemental inputs explicitly non-active |
| `docs/results/directionality_experiment_results.md` | untracked working-tree doc | keep now | valuable historical experiment summary based on surviving suffixed outputs and run summaries |
| `docs/design/flow_decision_diagram_outline.md` | untracked working-tree doc | keep now | concise current design artifact; aligns with bounded directionality support framing |
| `docs/design/upstream_downstream_diagram_outline.md` | untracked working-tree doc | keep now | concise current design artifact for the signal-centered prototype |
| `docs/design/upstream_downstream_decision_flow.md` | untracked working-tree doc | keep now | plain-language current prototype description; useful active reference |
| `docs/diagrams/directionality_decision_diagram.dot` | untracked working-tree source artifact | keep now | editable diagram source for the active directionality outline |
| `docs/diagrams/upstream_downstream_decision_diagram.dot` | untracked working-tree source artifact | keep now | editable diagram source for the active upstream/downstream outline |
| `docs/diagrams/directionality_decision_diagram.svg` | untracked generated visual | leave untracked for now | derived from the `.dot` source and regenerable |
| `docs/diagrams/upstream_downstream_decision_diagram.svg` | untracked generated visual | leave untracked for now | derived from the `.dot` source and regenerable |

## Legacy docs classification

| path | current status | recommended disposition | reason |
|---|---|---|---|
| `legacy/docs/AGENTS_legacy.md` | untracked local legacy doc | worth tracking now | preserves the prior operating contract and explains the migration-first posture that the redesign moved away from |
| `legacy/docs/overview_methodology_legacy.md` | untracked local legacy doc | worth tracking now | preserves the prior methodology framing for traceability against the current redesign |
| `legacy/docs/current_handoff.md` | untracked local legacy doc | keep local-only for now | useful archaeological note, but it asserts outputs exist that are missing now and is too stale to stage as current reference |
| `legacy/docs/src_file_classification.md` | untracked local legacy doc | keep local-only for now | useful prior reclassification snapshot, but it is tied to an earlier package/path state |
| `legacy/docs/stage1_portability.md` | untracked local legacy doc | keep local-only for now | historical command ladder for the portability branch; clearly not active guidance |
| `legacy/docs/stage1b_study_slice.md` | untracked local legacy doc | keep local-only for now | detailed historical Stage 1B slice contract; too migration-era to stage in the bounded keep set |
| `legacy/docs/stage2_oracle_safe_branch_architecture_summary.md` | untracked local legacy doc | keep local-only for now | useful Oracle-safe branch archaeology, but not needed in the immediate staging set |
| `legacy/docs/stage2_oracle_safe_branch_packaging_ladder_cleanup_plan.md` | untracked local legacy doc | keep local-only for now | detailed legacy cleanup planning for the Oracle-safe ladder; reference-only |
| `legacy/docs/stage2_oracle_safe_branch_traceability_map.md` | untracked local legacy doc | keep local-only for now | dense historical traceability note; useful only if that branch is revisited |
| `legacy/docs/Legacy/README.md` | untracked local legacy doc | keep local-only for now | legacy ArcPy docs index; helpful archive metadata, but not part of the immediate keep set |
| `legacy/docs/Legacy/oracle_gis_relationship_notes.md` | untracked local legacy doc | keep local-only for now | potentially useful background note, but still branch-specific and not needed in the first bounded staging batch |
| `legacy/docs/Legacy/phase_state_contract.md` | untracked local legacy doc | keep local-only for now | detailed ArcPy-era operational contract; archival reference rather than current guidance |
| `legacy/docs/Legacy/thirdstep_figures_issue_review.md` | untracked local legacy doc | keep local-only for now | issue-specific historical note with limited present value |
| `legacy/docs/Legacy/workflow.md` | untracked local legacy doc | keep local-only for now | ArcPy-era run instructions; useful archive reference only |
| `legacy/docs/Legacy/Intersection_Functional_Area_Analysis_VTRC (2).pptx` | untracked local binary archive | likely archival noise | large binary reference with unclear immediate recovery value; do not stage in the first bounded batch |

## Recommended bounded staging set

Recommended to stage now after review:

- `.gitignore`
- `AGENTS.md`
- `src/active/__main__.py`
- `README.md`
- `docs/README.md`
- `docs/methodology/overview_methodology.md`
- `docs/workflow/active_workflow.md`
- `docs/recovery_audit_20260416.md`
- `docs/repo_redesign_plan.md`
- `docs/methodology/flow_method_comparison.md`
- `docs/workflow/staging_and_normalization_contract.md`
- `docs/results/directionality_experiment_results.md`
- `docs/design/flow_decision_diagram_outline.md`
- `docs/design/upstream_downstream_diagram_outline.md`
- `docs/design/upstream_downstream_decision_flow.md`
- `docs/diagrams/directionality_decision_diagram.dot`
- `docs/diagrams/upstream_downstream_decision_diagram.dot`
- `docs/doc_classification_20260416.md`
- `legacy/docs/AGENTS_legacy.md`
- `legacy/docs/overview_methodology_legacy.md`

Recommended to leave untracked for now:

- generated `docs/diagrams/*.svg`
- all `legacy/docs/` files not explicitly listed above

Recommended legacy migration targets later, not now:

- none from `docs/` in this bounded pass

The current docs tree is mixed but salvageable.
The conservative move is to stage the active redesign docs and only the two most important legacy contract/history docs, while leaving the rest of `legacy/docs/` as local archive material until a later archival pass is justified.
