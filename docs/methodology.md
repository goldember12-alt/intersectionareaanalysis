# Methodology Summary

The project supports Virginia downstream functional-area analysis at signalized intersections.

The current methodology is canonical-cache first. The final core cache integrates signal, travelway, approach, corridor, bin, distance-band, access, crash, speed, AADT, exposure, and directionality context. Review outputs are diagnostic evidence only and are not data parents for ordinary analysis.

Important doctrine:
- Upstream/downstream directionality is cache-derived; crash direction fields are not used to derive it.
- Access context is combined-source, spatial-only, and exclusive within signal/approach/direction distance bands.
- Crash assignment is spatial-primary, 50 ft, band-exclusive within crash/signal/approach/direction, equal fractional, and total-preserving.
- Exposure is currently a daily VMT proxy unless later MVP logic defines final crash-period exposure.
- Unresolved and source-limited cases are preserved with flags rather than hidden.
