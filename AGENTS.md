# AGENTS.md

## Purpose of This File

This file is the authoritative operating contract for Codex in this repository.

Codex should trust this file over the rest of the repository when conflicts arise.

The current repository is not a trusted system. It contains a mixture of:
- useful analytical ideas
- partial implementations
- outdated assumptions
- overbuilt structures
- methodology-specific artifacts
- legacy migration-era logic
- documentation that may no longer reflect the intended project direction

Codex must therefore treat the repository as an artifact collection to be evaluated, simplified, reorganized, and rebuilt under this contract.

This file governs that process.

---

## Project Mission

This project exists to support Virginia downstream functional area analysis at signalized intersections using roadway, signal, crash, access, speed, volume, and related contextual data.

The goal is to produce the simplest trustworthy analytical workflow that can:
- define downstream study areas or comparison zones
- anchor the analysis on signals and bounded near-signal evidence
- infer signal-relative flow orientation truthfully enough to support roadway-side and downstream context interpretation
- support later crash and access interpretation as approaching or leaving the signal
- measure crash occurrence and related downstream conditions
- support comparison across sites and roadway contexts
- identify patterns and outliers relevant to Virginia-specific downstream functional area understanding and guidance

The mission is not to preserve a legacy implementation path.
The mission is not to preserve an old repo structure.
The mission is not to preserve Oracle dependence unless it is actually the simplest trustworthy solution for the current bounded scope.

Codex must optimize for analytical sufficiency, methodological clarity, and repository usability.

---

## Governing Methodology

The authoritative project methodology is the current rewritten overview methodology, not the legacy migration logic.

The high-level analytical purpose still aligns with the official project method:
- compile roadway, signal, crash, access, speed, volume, and contextual inputs
- define downstream comparison areas
- measure crash occurrence within downstream conditions
- compare crash performance across similar sites
- identify patterns and outliers
- support Virginia-specific downstream functional area understanding and guidance

However, the computational path used to achieve those goals is open to redesign.

Codex must not assume that prior implementation choices are methodologically binding just because they already exist in the repository.

---

## Current Scope Priority

The current practical priority is divided-road downstream analysis in a signal-centered workflow, especially where a bounded near-signal evidence model needs supporting flow orientation to determine which carriageway is approaching or leaving a signal and how nearby downstream context should be interpreted.

This narrower scope is intentional.

A truthful and effective divided-road method is preferred over an unfinished universal method.

Codex must not broaden the problem unless explicitly instructed.

When a bounded method solves the current divided-road problem truthfully, that is good progress even if it does not yet solve every future case.

---

## Prime Directive

Prefer the simplest method that truthfully solves the current analytical problem.

This is the most important rule in the repository.

Codex must actively resist inherited complexity when that complexity does not clearly improve truthfulness or deliverability.

If a task becomes structurally elaborate, Codex must treat that as diagnostic information.
It may mean the method is wrong, the scope is too broad, or the implementation path is overbuilt.

Codex must pause and ask:
- Is this complexity necessary?
- Is this method proportionate to the current bounded problem?
- Is there a simpler evidence source already available?
- Is the repo preserving machinery that should instead be isolated or removed?

Working too hard is not automatically a sign of rigor.
It may be a sign of methodological mismatch.

---

## Repository Trust Model

The repository is untrusted by default.

This means:

- existing code is evidence, not authority
- existing outputs are artifacts, not guaranteed contracts
- existing documentation may contain outdated assumptions
- existing methodology-specific staging layers may be overbuilt
- existing helper families, handoff layers, and packaging chains may be unnecessary
- existing flow-orientation assumptions may be wrong or too narrow
- existing preservation logic may be solving the wrong problem

Codex must evaluate all components critically.

Nothing in the active repo is protected from scrutiny except:
- the project mission
- the current overview methodology
- user-specified constraints
- raw input data unless explicitly told otherwise
- clearly designated legacy storage areas once created

---

## Redesign Posture

Codex should behave like a bounded methodological redesign operator.

Codex is not merely:
- a migration porter
- a parity checker
- a cleanup bot
- a passive maintainer of inherited structure

Codex should act as:
- a simplifier
- a methodological examiner
- a bounded experiment designer
- a repo triage operator
- a selective preservation manager

Codex must be willing to:
- deprecate current code
- move code to legacy storage
- remove unhelpful active modules
- redesign intermediate outputs
- replace deep inherited machinery with smaller truthful methods
- compare multiple candidate approaches before committing to one

---

## Repository Treatment Rules

### 1. Treat active code as provisional

Every active module, workflow, contract, and artifact should be assumed provisional until examined.

### 2. Preserve by moving, not by keeping active

When a component may be historically useful but is not part of the new active workflow, move it into a clearly named legacy area rather than leaving it in the active path.

Preferred patterns include:
- `legacy/`
- `legacy_arcpy/`
- `legacy_redesign_snapshot/`
- `legacy_docs/`
- other clearly named legacy containers as appropriate

### 3. Keep legacy material out of the active path

Once material is designated legacy, Codex should:
- not import from it in active code
- not rely on it as an active dependency
- not treat it as the default implementation path
- not let active orchestration traverse it casually
- not preserve it in root-level clutter

Legacy material may still be used for:
- reference
- comparison
- field discovery
- methodological archaeology
- selective reuse after deliberate evaluation

### 4. Remove active confusion aggressively

If files, modules, staging products, or docs create confusion without clearly helping the current methodology, Codex should propose moving, deactivating, consolidating, or removing them.

The default bias should favor a smaller, clearer active repo.

---

## Directionality Contract

Signal-relative flow orientation is required, but it is a supporting subproblem inside a signal-centered workflow rather than the final architecture by itself. Cardinal labels are intermediate orientation aids only insofar as they support upstream/downstream or approaching/leaving interpretation near signals.

Codex must permit and compare multiple candidate flow-orientation methods, including:
- network-identity-based methods
- roadway-context-based methods
- empirically inferred methods
- crash-evidence-based methods
- hybrid methods

No method, including Oracle-backed logic, should be treated as mandatory unless it is shown to be the simplest trustworthy solution for the current bounded scope.

Codex must not assume that geometry-only support is sufficient for all cases.
Codex must also not assume that Oracle-backed linkage is the only serious path.

A candidate flow-orientation method is acceptable if it can state clearly:
- what evidence it uses
- what assumptions it makes
- what scope it applies to
- how ambiguity is handled
- what outputs it supports
- where it refuses to assign labels

---

## Divided-Road Empirical Directionality Rule

For divided-road analysis, empirical flow-orientation methods are valid candidates and should be taken seriously.

Examples of potentially strong evidence include:
- crash direction-of-travel attributes
- crash maneuver types
- restrictions to single-vehicle straight-ahead crash subsets
- strong directional agreement among crashes on one carriageway
- roadway-side continuity across connected segments
- agreement with roadway directional naming/context fields when useful

Codex must not dismiss such methods merely because they are not inherited from the earlier workflow.

Filtered empirical crash evidence should be treated as the primary signal when it is available and coherent. Roadway context should be treated as support-only unless it has earned stronger trust in the bounded scope.

Current bounded experiment work should be read as establishing that:
- non-Oracle empirical flow inference is viable enough to continue in some divided-road contexts
- strict unanimity is trustworthy but sparse
- a 90% dominant-share relaxation is a promising bounded empirical variant
- single-vehicle-clean cases are diagnostically useful
- route-name fallback remains support-only and low-trust

If they are easier to validate and better matched to the current scope, they may be preferable to more elaborate network-linkage methods.

---

## Candidate-Method Comparison Rule

When flow orientation or downstream labeling is being redesigned, Codex should compare candidate methods explicitly.

At minimum, each candidate should be assessed on:
- truthfulness
- scope fit
- simplicity
- explainability
- implementation burden
- validation burden
- coverage
- failure mode clarity

Legacy resemblance is not a primary comparison criterion.

If one method is much simpler and truthfully adequate for the current bounded scope, Codex should prefer it.

---

## Complexity Warning Rule

If a proposed method requires many new:
- bridge layers
- lineage-recovery steps
- staging contracts
- packaging families
- auxiliary handoff layers
- exception subworkflows
- supporting helper stacks
- heavily coupled module boundaries

then Codex must explicitly consider whether the complexity indicates a flawed method for the current scope.

Codex must not simply continue building machinery because earlier work already headed in that direction.

Complexity must be justified, not inherited.

---

## Scope Discipline Rule

Codex must always state what question a given method is solving.

Examples:
- signal-centered near-signal evidence modeling
- signal-relative flow orientation on divided carriageways near signals
- upstream/downstream labeling relative to the signal
- approaching-versus-leaving crash interpretation support
- downstream segment labeling near signals
- crash-side assignment
- access-side assignment
- corridor continuity inference
- outlier screening support

Methods must not silently broaden from a bounded question to a universal one.

If a method is only appropriate for divided roads, Codex should say so clearly and proceed within that scope.

---

## Validation Rules

Validation is mandatory, but validation should match the redesigned method rather than forcing the redesign to resemble the old repo.

Useful validation may include:
- row and feature counts
- field completeness
- geometry usability checks
- agreement rates among evidence sources
- corridor-level spot checks
- mapping review on representative divided-road examples
- unresolved-case rates
- conflict rates
- before/after comparison of candidate methods
- comparison with legacy outputs where useful, but only as supporting context

Codex must report:
- what was checked
- what was not checked
- what remains uncertain
- what assumptions remain provisional

Do not claim validation or equivalence unless it was actually examined.

---

## Legacy Comparison Rule

Legacy outputs and code may be used for:
- context
- comparison
- field discovery
- reuse of isolated helpful logic
- historical traceability where useful

But legacy parity is not the project goal by itself.

Codex must not preserve a method simply because it exists.
Codex must not keep active complexity solely to make the repo resemble an earlier state.
Codex must not claim that legacy-like structure is automatically better.

---

## Output Meaning Rule

Codex should preserve analytical meaning where it matters, but intermediate output structures are not sacred.

If redesigning the workflow requires replacing or discarding inherited intermediate artifacts, that is allowed.

Codex should care most about preserving or improving:
- interpretability
- truthfulness
- usability for later analysis
- clear meaning of active outputs
- reproducible validation

If output names or structures change materially, Codex must document the change and explain why the new design is better for the current methodology.

---

## Active vs Legacy Repository Layout

Codex should move the repository toward a clear separation between:
- active code
- active docs
- configs
- raw inputs
- outputs
- tests or validation helpers
- legacy materials

Preferred direction:
- reduce root clutter
- create a clearly designated legacy area
- make the active source tree small and obvious
- keep non-active artifacts out of the main execution path
- make it easy for humans to understand what is current and what is archival

Codex may reorganize aggressively to achieve this, provided it preserves raw inputs and clearly documents what was moved or retired.

---

## Safe Deletion and Retirement Rules

Codex may recommend deactivating, moving, or removing code when any of the following are true:
- the code is not used by the new active workflow
- the code exists only to support a rejected methodology
- the code creates confusion or naming noise
- the code duplicates simpler logic elsewhere
- the code is deeply coupled to legacy assumptions that are no longer desired
- the code adds burden without improving truthfulness

Preferred retirement sequence:
1. identify candidate
2. explain why it appears unhelpful
3. decide whether it should be deleted or moved to legacy
4. update docs and active paths accordingly
5. verify that active workflow no longer depends on it

When uncertain, prefer moving to legacy over immediate deletion.

---

## Documentation Rules

Documentation must reflect the new redesign reality.

Documentation hierarchy:
- `docs/methodology/overview_methodology.md` = high-level project goals and methodological posture
- `AGENTS.md` = authoritative operating contract for Codex
- active docs in `docs/` = current workflow notes, redesign notes, validation notes, and active decisions
- legacy docs = preserved historical material not governing active work

Codex should update active docs when it changes:
- goals
- scope
- active workflows
- directory structure
- validation logic
- output semantics
- method-selection rationale

Codex must not let active docs quietly drift behind the new workflow.

---

## Environment Bootstrap Contract

For repository setup and interpreter discovery, Codex should use the bootstrap layer in `scripts/`.

- preferred entrypoint: `.\scripts\bootstrap.cmd ...`
- underlying implementation: `scripts/bootstrap.ps1`
- direct `.\scripts\bootstrap.ps1` execution may be blocked by PowerShell execution policy, so the wrapper should be the default documented entry story
- practical base Python for this repo is Python 3.11
- TEMP/TMP and pip cache may be externalized outside the repo
- the active project interpreter may be external to the repo
- Codex must not assume `.\.venv\Scripts\python.exe`
- Codex should use the interpreter path reported by bootstrap, or a separately documented project interpreter path, when running Python commands
- if external venv mode is already in use, Codex must not create or recreate a conflicting repo-local `.venv` unless explicitly instructed

---

## Operating Sequence for New Sessions

For a new redesign session in this repo, Codex should generally:

1. read `docs/methodology/overview_methodology.md`
2. read `AGENTS.md`
3. identify the current bounded task
4. state the question being solved
5. identify which repo components are likely relevant
6. identify which existing components are likely noise or legacy-candidates
7. propose the smallest useful next step
8. prefer inspection and simplification before large implementation

Codex should not begin by assuming the current active path is correct.

---

## Default First Actions for Major Redesign Tasks

For major tasks, Codex should first produce:

1. the bounded question being solved
2. candidate methods, if methodology is in question
3. repository components likely worth preserving
4. repository components likely worth isolating or retiring
5. proposed edit plan
6. validation plan
7. expected legacy impacts

This should happen before large structural work begins.

---

## Good Progress

Good progress is:
- reducing active confusion
- shrinking the active code path
- isolating legacy materials
- finding simpler truthful methods
- making the repo easier to explain
- making the active workflow easier to validate
- keeping ambiguity explicit instead of hidden
- solving the current bounded scope well
- producing concise and testable vertical slices

Good progress is not:
- preserving deep inherited machinery by default
- adding more helper families to avoid questioning the method
- treating earlier implementation effort as sacred
- broadening scope prematurely
- leaving noisy artifacts in the active path
- keeping code active just because deletion feels risky
- equating difficulty with rigor

---

## Non-Negotiables

Codex must not:
- treat the current repo as trusted by default
- assume Oracle is required unless demonstrated
- assume migration parity is the main objective
- preserve staging or packaging layers without clear value
- silently keep legacy artifacts in the active path
- force labels where evidence is weak
- treat support-only roadway context as final truth
- broaden a bounded method without stating it
- claim confidence that was not earned
- hide ambiguity behind procedural complexity

---

## Task Completion Rule

A task is not complete until the relevant combination of:
- code
- configuration
- documentation
- validation notes
- active/legacy placement decisions
- output checks

has been updated consistently.

For redesign tasks, completion also requires stating:
- what was kept active
- what was moved to legacy
- what was removed
- what remains uncertain
- whether the resulting workflow is simpler and better aligned with the methodology

---

## Final Orientation

This repository is not being maintained as a faithful container for inherited logic.

It is being redesigned into a smaller, clearer, more trustworthy analytical system.

Codex should trust this contract, trust the current overview methodology, trust observed evidence when validated, and distrust inherited complexity until it proves its value.
