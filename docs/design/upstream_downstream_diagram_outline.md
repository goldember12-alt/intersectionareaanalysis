# Outline for the Signal-Centered Upstream/Downstream Classification Diagram

## Diagram Title
Signal-Centered Upstream/Downstream Crash Classification Workflow

## Subtitle / Guiding Question
After upstream preprocessing and row-level local flow preparation, can a crash near a signal be classified upstream or downstream credibly, or should it stay unresolved?

## Figure Intent
Show the bounded signal-centered prototype that classifies crashes relative to signals only when signal association, row attachment, local flow, and along-row comparison are all credible.

## Core Reading Structure
- one broad centered classification spine
- no dominant sidebar; supporting notes stay in three compact clusters
- the same cluster pattern used in the directionality figure:
  `Inputs / Starts Here`, `Definitions / Prototype Mechanics`, and `Outputs / Review`

## Cluster A: Inputs / Starts Here
- the figure begins after upstream preprocessing already produced signals, study rows, crash points, and row-level local flow states
- signals already have nearest-row context
- crashes already carry route identity and location usable for bounded same-route matching
- posted-speed context is already available for the speed-informed approach-length step

## Main Classification Spine
1. Start with one signal.
2. Decision: is that signal eligible for this bounded prototype?
3. Set a speed-informed approach length.
4. Build a same-route local study area near the signal.
5. Keep crashes inside that study area.
6. Decision: is there a clear same-route eligible signal for the crash?
7. Attach the crash to that signal's nearest study row.
8. Decision: is row attachment credible?
9. Decision: is trusted local flow available on the attached row?
10. Compare crash and signal along one directed study row.
11. Decision: is the along-row comparison trustworthy?
12. Decision: does the crash fall before or after the signal along assigned flow?
13. Output `upstream`, `downstream`, or unresolved.
14. Show the strongest-confidence descriptive slice as a later filter on classified cases, not as a separate method branch.

## Cluster B: Definitions / Prototype Mechanics
- `Eligible signal`: signal whose nearest study row already has local flow from `StrictUnanimous` or `Empirical90Pct`
- same-route matching uses the current route-identity rule; ambiguous cases stay unresolved
- the study area is roadway-constrained: same-route row pieces near the signal, clipped to a speed-informed length, buffered, and joined by a small hub buffer
- row attachment must stay credible; leave unresolved when the crash is too far from the selected row
- `Directed study row` keeps the ordered-row-geometry idea but explains it plainly: the crash and signal must both project onto one usable row for comparison in assigned travel direction
- unresolved is expected when association, attachment, local flow, or along-row comparison is not trustworthy enough

## Cluster C: Outputs / Review
- output is crash-level `upstream`, `downstream`, or unresolved
- unresolved is retained by design
- the strongest-confidence descriptive slice is a later filter, typically classified cases with high attachment and strict empirical flow
- analyst review and spot-checking still matter for map-sensitive, borderline, or unusual cases
- the overall tone should stay conservative and semi-automated rather than universal

## Visual Posture
- keep the main classification spine visually dominant and centered
- keep support clusters close enough that the reader does not have to bounce across the page
- make the directed-row-line step legible on first pass with a plain-language box label and a precise nearby note
- integrate the bottom output / later-filter region into the flow instead of treating it as an appended footer

## Optional Caption
This bounded signal-centered workflow starts after preprocessing and row-level local flow preparation, builds a roadway-constrained same-route study area near each eligible signal, classifies crashes only when the local association and along-row comparison are credible, and keeps unresolved cases as an intentional output while applying the strongest-confidence descriptive slice only after classification.
