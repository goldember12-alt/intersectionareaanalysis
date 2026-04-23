# Signal-Centered Upstream/Downstream Prototype Decision Flow

This file is a plain-language source artifact for a later visual decision diagram.
It describes the current bounded signal-centered prototype, not a statewide production workflow.

## Decision flow

1. Start with a signal.
   Keep only signals whose own nearest study-road row already has local flow orientation from `StrictUnanimous` or `Empirical90Pct`.

2. Define a bounded study area around that signal.
   Compare a simple `250` meter circle against a more roadway-constrained approach-shaped area.
   The current preferred shape clips nearby same-route study-road rows to a bounded approach length, buffers those row pieces, and unions them with a small hub buffer at the signal.

3. Assign a bounded approach length.
   Use a nearest speed join from the posted-speed layer when available.
   Round to a small AASHTO/VDOT-style lookup and use the desired functional distance as a transparent approach-length proxy.
   Fall back to a default `35 mph` lookup when no usable speed is nearby.

4. Gather nearby crashes inside that study area.
   At this stage a crash is only a location, not a movement.

5. Check whether the crash has a plausible signal association.
   Prefer the nearest eligible signal on the same route.
   Leave unresolved if there is no same-route eligible signal or if two same-route signals are nearly equally near the crash.

6. Attach the crash to a plausible local carriageway row.
   The current prototype attaches the crash to the selected signal's own nearest study-road row.
   Leave unresolved if the crash is too far from that row to make the attachment credible.

7. Determine local flow orientation for the attached row.
   Use `StrictUnanimous` first.
   If strict flow is unavailable, use `Empirical90Pct`.
   Do not promote route-name fallback into this first crash-classification prototype.

8. Put the signal and the crash onto the same ordered row geometry.
   Project both locations onto the attached row so they can be compared along a single line.

9. Compare crash position to signal position along the assigned flow.
   If the crash lies before the signal along traffic flow, classify it as `upstream`.
   If it lies after the signal along traffic flow, classify it as `downstream`.

10. Leave unresolved when the ordering is not trustworthy.
   Examples include:
   - no clear signal association
   - no usable attached row
   - no strict or empirical90 flow
   - crash too far from the attached row
   - crash and signal projecting to nearly the same along-row position

## Provenance rule

Every prototype classification should preserve:

- which signal study area was used
- which attached row was used
- which flow source supplied the row orientation
- whether the final result is `upstream`, `downstream`, or `unresolved`
- why unresolved was chosen when no trustworthy classification was available
