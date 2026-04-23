# Outline for the Divided-Road Flow-Orientation Decision Diagram

## Diagram Title

Empirical Flow Orientation on Divided-Road Study Rows

## One-Sentence Purpose Statement

This diagram explains the bounded supporting method used to infer local carriageway flow orientation on divided-road study rows so later signal-relative upstream/downstream classification could rely on empirical local flow rather than geometry alone.

## Recommended Figure Type

* Primary structure: top-to-bottom decision tree
* Secondary structure: one narrow side panel for definitions and one smaller side branch for diagnostic/support-only paths

## Main Boxes And Decisions In Order

### Box 1

Start with one divided-road study row in the signal-adjacent study slice

Short box note:

* Row unit = one `Study\\\_Roads\\\_Divided` segment with a route name and a from/to measure interval

### Box 2

Gather attached crash evidence for that row

Short box note:

* Attach crashes by exact route-name match plus row measure interval

### Box 3

Filter to qualifying empirical crash evidence

Short box note:

* Keep only crashes with one clear parsed direction of travel
* Keep only single-vehicle crashes
* Keep only `Going Straight Ahead` crashes

### Decision Diamond 1

At least 2 qualifying crashes?

`Yes` branch:

* continue to Decision Diamond 2

`No` branch:

* go to Outcome U1

### Decision Diamond 2

Do all qualifying crashes agree on one direction?

`Yes` branch:

* go to Outcome A1

`No` branch:

* continue to Decision Diamond 3

### Decision Diamond 3

Does one direction account for at least 90% of the qualifying crashes?

`Yes` branch:

* go to Outcome A2

`No` branch:

* go to Outcome U2

## Main Outcomes

### Outcome A1

Assign local flow orientation with `StrictUnanimous`

Short outcome note:

* Primary empirical assignment
* Strongest bounded rule

### Outcome A2

Assign local flow orientation with `Empirical90Pct`

Short outcome note:

* Primary empirical assignment
* Bounded relaxation of the strict rule

### Outcome U1

Unresolved under the main empirical rules because the row does not have enough qualifying crash evidence

### Outcome U2

Unresolved under the main empirical rules because qualifying crashes conflict without reaching the 90% dominant-share threshold

## Separate Diagnostic / Support-Only Side Branch

This should appear as a smaller parallel branch off Box 3 or as a right-side companion panel, not as part of the main assignment spine.

### Side Box S1

Check broader crash-DOT-only picture for comparison

Short note:

* Uses any crash with one clear parsed direction of travel
* Not the main truth source

### Side Box S2

Read `SingleVehicleSupport` diagnostically

Short note:

* Same filtered single-vehicle straight-ahead subset as the main empirical rules
* Useful for showing where the clean subset stays directional even when the broader crash-DOT-only picture is noisy
* Do not depict as a major additive assignment path in the current sample

### Side Box S3

Read `RouteNameFallback` as support-only context

Short note:

* Activates only after `Empirical90Pct` stays unresolved
* Based on route-name suffix or route-common directional tokens
* Secondary and review-sensitive
* Does not override strong empirical evidence

### Side Outcome S4

Support-only signal noted, but empirical assignment still remains the preferred answer when available

## Final Bottom Box

Use the assigned local flow orientation as supporting input to the later signal-centered upstream/downstream workflow

Short note:

* This experiment solved a bounded subproblem
* It did not become the main project architecture

## Decision Labels To Put On The Figure

* Diamond 1:

  * `Yes: at least 2 qualifying crashes`
  * `No: too little clean evidence`
* Diamond 2:

  * `Yes: full agreement`
  * `No: internal conflict`
* Diamond 3:

  * `Yes: dominant share >= 90%`
  * `No: keep unresolved`

## Definitions / Legend Side Panel

Include these as a right-side panel or footer legend, not inside the main flow boxes.

### Qualifying Crash

* One clear parsed direction of travel
* Single-vehicle
* `Going Straight Ahead`

### `StrictUnanimous`

* At least 2 qualifying crashes
* All qualifying crashes agree on one direction

### `Empirical90Pct`

* Same qualifying subset
* At least 2 qualifying crashes
* One direction accounts for at least 90% of the qualifying crashes

### Hard Conflict

* Qualifying evidence conflicts without a meaningful dominant direction

### Soft Conflict

* Qualifying evidence conflicts, but one direction still leads

### High-Dominant-Share Soft Conflict

* Conflict remains, but one direction still holds >= 90% share

### `SingleVehicleSupport`

* Diagnostic readout showing where the clean filtered subset stays directional against broader crash-DOT conflict

### `RouteNameFallback`

* Support-only secondary context
* Used only after the relaxed empirical rule stays unresolved

### Unresolved Posture

* Unresolved is acceptable
* Do not force labels when empirical evidence is sparse or conflicted

## Suggested Color Logic

* Dark green: `StrictUnanimous`
* Medium green: `Empirical90Pct`
* Gray: unresolved outcomes
* Blue or teal side branch: diagnostic/support-only readouts
* Amber outline: conflict-related callouts

## Recommended Visual Hierarchy

* Put only the main assignment spine in large boxes and diamonds.
* Keep `SingleVehicleSupport` and `RouteNameFallback` visually smaller so the viewer understands they are diagnostic/support-only rather than the main workflow.
* Put the rule thresholds and qualifying-crash definition in a side legend, not repeated inside each box.
* Keep counts and current sample findings out of the main boxes; place those in a caption or speaker notes instead.
* The bottom-most takeaway should clearly state that this diagram explains a supporting subproblem, not the whole project.

## What To Leave Out Of The Diagram

* Full file names and CSV inventories
* Expanded-sample counts for every bucket
* GIS review priority scoring details
* Internal field names beyond one or two helpful labels
* Corridor continuity subdiagnostics

## Optional Caption

The empirical directionality experiment asked whether filtered crash evidence could support local carriageway flow orientation on divided-road study rows. The strict rule was conservative and sparse, the 90% rule added a small number of useful rows, support-only context stayed secondary, and unresolved remained acceptable.
