# Thirdstep Figures Review: Noted Issues, Flags, and Likely Origins

## Scope

This review is based on the following materials from the latest run:

- generated figures `Fig0` through `Fig12`
- `thirdstepfigures_summary.csv`
- `thirdstepfigures_debug_sample.csv`
- `QC_ThirdStep_Summary.csv`
- `DirectionalCrashType_Counts_Top.csv`
- the full pipeline run log from the successful `thirdstep` execution

The goal of this document is to identify what looks correct, what clearly looks wrong or incomplete, which flags matter most, and where each issue most logically originates in the pipeline.

---

## Executive Summary

The run appears **structurally successful but analytically incomplete**.

The segmentation, zoning, fallback inheritance, GeoPandas directional labeling, and ArcPy writeback all ran to completion. The final dataset exists and the high-level directional breakdown is internally plausible enough to support debugging. However, the figures reveal that the dataset used for figure generation has a critical content problem:

- **all crash counts are zero**
- **all access counts are zero**
- therefore all derived crash/access density and crash-rate figures collapse to zero

This means the current figures are useful mainly for:

- directional mix
n- zone mix
- direction-source mix
- QC flag prevalence
- Delta_M distribution

They are **not yet valid** for any safety-performance interpretation involving crashes, accesses, or rates.

The dominant substantive issue in the final dataset is still the Oracle-driven directional ambiguity problem:

- `OracleAmbiguous = 10,031`
- `OracleNoMatch = 4,679`
- `NodeMissing = 4,679`
- `UnknownDirection = 4,259`
- `TrimmedByNeighbor = 5,748`

So the run produced a usable structural output, but not yet a clean downstream analytical dataset.

---

## High-Confidence Findings

## 1. The figures dataset contains no crash or access events

This is confirmed directly by `thirdstepfigures_summary.csv`:

- `SegmentRowsUsed = 18,718`
- `TotalCrashCount = 0`
- `TotalAccessCount = 0`

It is also confirmed by the debug sample:

- `Crash_Total` sums to `0`
- `Access_Count` sums to `0`
- `Crash_Up`, `Crash_Down`, and `Crash_At` all sum to `0`
- `Crash_Density_1k = 0` for all sampled rows
- `Access_Density_1k = 0` for all sampled rows
- `Crash_Rate_MVMT = 0` for all sampled rows

### Most logical source

This does **not** look like a figures-script problem by itself. The figures script is reading fields that are already zero in the underlying table. The more likely origins are upstream:

1. **Phase V initial crash/access assignment did not persist usable counts into the final output fields expected by `thirdstepfigures.py`**.
2. The counts may exist in differently named fields that the figures script is not reading.
3. The counts may have been created earlier, then lost during:
   - GeoPandas export/reload,
   - writeback,
   - summary-field join,
   - or final field overwrite.
4. The recent-year crash filter may have over-filtered unexpectedly, but that would not explain `Access_Count = 0` everywhere too.

### Best working hypothesis

The strongest hypothesis is a **field-contract mismatch** between the final `Final_Functional_Segments` schema and the field names used by `thirdstepfigures.py`.

Because both crashes and accesses are zero everywhere, the problem is probably not random data sparsity. It is much more likely that the figures script is reading the wrong final fields, or the writeback step never populated the final count fields that the figures script expects.

---

## 2. Directional role mix is structurally plausible, but still dominated by downstream labels

From the figures:

- `Downstream` is the dominant final role by a large margin.
- `Unknown` is the second-largest bucket.
- `Upstream` and `AtSignal` are much smaller but still substantial.

This is consistent with the debug sample proportions:

- `Downstream`: 2,745 / 5,000
- `Unknown`: 980 / 5,000
- `Upstream`: 694 / 5,000
- `AtSignal`: 581 / 5,000

And consistent with the full bar chart counts shown in the exported figure.

### Interpretation

This distribution is not inherently wrong. A large downstream bucket can be expected when many segments fall beyond the signal along the dominant through movement. But the relatively large `Unknown` category means the directional classifier is still failing on a meaningful share of the network.

### Most logical source of the elevated `Unknown`

The run log and QC table point to Oracle/node-direction reliability problems rather than a segmentation-collapse problem:

- `UnknownDirection = 4,259`
- `OracleAmbiguous = 10,031`
- `OracleNoMatch = 4,679`
- `NodeMissing = 4,679`

So the `Unknown` role population is most logically stemming from:

- unresolved Oracle ambiguity
- missing Oracle topology keys
- missing usable node basis for directional inference
- inability to get a reliable order/orientation on some road segments

---

## 3. Zone split looks plausible and internally consistent

The `Directional Role Mix by Zone` figure appears coherent:

- Zone 1 and Zone 2 both contain many downstream segments
- Zone 1 has noticeably more `AtSignal` than Zone 2
- Zone 1 has somewhat more `Upstream` than Zone 2
- Zone 2 still has a large downstream share

This makes sense conceptually if:

- Zone 1 is the tighter critical area near the intersection influence region
- Zone 2 is the outer functional extension

### Why this likely reflects real structure

The zone-based directional figure is one of the few plots that does **not** depend on crash/access counts. It depends mainly on:

- successful functional area creation in Phase II
- successful road segmentation in Phase IV
- successful directional labeling in Phase VII

Since those phases all completed and the zone mix appears non-degenerate, the zone construction itself is probably not the core issue right now.

---

## 4. Direction source distribution shows heavy reliance on Oracle node topology, with almost no route-order use

The direction source figure shows:

- `OracleNodeTopology` dominates
- `NoReliableDirection` is the second-largest group
- `MeasureTolerance` is substantial
- `OracleRouteOrder` is essentially absent

The debug sample supports this:

- `OracleNodeTopology = 3,437 / 5,000`
- `NoReliableDirection = 980 / 5,000`
- `MeasureTolerance = 581 / 5,000`
- `OracleRouteOrder = 2 / 5,000`

### Interpretation

This tells a fairly clear story:

1. The current pipeline is relying mostly on Oracle node topology when it can.
2. When topology does not yield a clean answer, a large number of rows still end up without a reliable direction.
3. Route-order logic is almost never contributing.

### Most logical source

This most likely stems from the Oracle matching patch doing exactly what it was intended to do:

- be stricter about measure-based candidate acceptance
- collapse duplicates
- avoid overconfident route-order matches

That is safer than the earlier behavior, but it also reveals that the current Oracle data/key situation is still not rich enough to resolve many cases cleanly.

### Practical implication

If `OracleRouteOrder` is nearly absent, then route-order logic is currently not an important rescue path. The real leverage point is improving:

- Oracle key coverage
- node completeness
- measure consistency
- or tolerance logic for near-signal segments

---

## 5. Delta_M distribution is highly right-skewed and probably includes many segments far beyond ideal directional confidence range

The `Delta_M` histogram shows:

- a heavy concentration near zero
- a very long positive tail
- some extremely large values reaching roughly 14,000+

This is not surprising in a segmented network, but it matters because your patched Oracle logic is explicitly penalizing or rejecting candidates far from the signal measure.

### Most logical source

Large `Delta_M` values likely come from one or more of the following:

- long downstream functional extents
- segmentation pieces that remain in the study area but are far from the controlling signal measure
- mis-associated signal/segment pairings in some cases
- or normal geometry on longer corridors

### Why this matters

The run log showed:

- `measure_guard_rejections = 375,997`
- `AmbiguousFarFromMeasure = 8,654`

So the long-tailed measure-offset distribution is strongly linked to the dominant Oracle ambiguity mode.

### Interpretation

The strict measure guard is probably catching many legitimately risky matches, but it may also now be rejecting some borderline-but-correct candidates. This is not obviously a bug. It is a sign that the current Oracle resolution problem is centered on **measure consistency and candidate separation**, not just route naming.

---

## 6. QC flag prevalence is a major issue, especially Oracle ambiguity and neighbor trimming

From `QC_ThirdStep_Summary.csv`:

- `MissingLinkID = 3`
- `OverlapClaim = 0`
- `UnknownDirection = 4,259`
- `TrimmedByNeighbor = 5,748`
- `OracleNoMatch = 4,679`
- `OracleAmbiguous = 10,031`
- `NodeMissing = 4,679`
- `RouteMismatch = 0`
- `AADTConflict = 2,322`
- `SuspiciousShortSegment = 0`

### What looks good

These are positive signs:

- `MissingLinkID = 3` is extremely low
- `OverlapClaim = 0` means claim-cleaning worked well
- `RouteMismatch = 0` means the soft-penalty route logic removed hard mismatch fallout
- `SuspiciousShortSegment = 0` suggests sliver cleanup worked well

### What still looks problematic

These are the major remaining flags:

- `OracleAmbiguous = 10,031`
- `TrimmedByNeighbor = 5,748`
- `OracleNoMatch = 4,679`
- `NodeMissing = 4,679`
- `UnknownDirection = 4,259`
- `AADTConflict = 2,322`

### Most logical origins by flag

#### OracleAmbiguous
Most likely from:

- multiple valid Oracle candidates per segment
- insufficient separation after candidate clustering
- large `Delta_M` values causing measure-based rejection of otherwise plausible candidates
- near-ties in candidate score

This aligns with the run log breakdown:

- `AmbiguousFarFromMeasure = 8,654`
- `AmbiguousMeasureTie = 1,377`

#### OracleNoMatch
Most likely from:

- no usable Oracle candidate for the segment link ID
- incomplete Oracle coverage
- missing or mismatched GIS key linkage
- segments that inherited enough metadata to survive pipeline steps, but not enough to join cleanly to Oracle

#### NodeMissing
Most likely from:

- the base road data never having valid `FromNode_Norm` / `ToNode_Norm`
- Oracle GIS-key enrichment not supplying a usable node basis for those records
- or node information being available in Oracle only for some subset of link IDs

This is especially important because the run log already showed that the base roadway system expected `FromNode_Norm` and `ToNode_Norm` to be absent originally.

#### UnknownDirection
Most likely from:

- unresolved Oracle ambiguity
- missing node basis
- segments for which measure ordering cannot confidently imply upstream/downstream
- a deliberate refusal by the patched logic to overstate confidence

#### TrimmedByNeighbor
Most likely from:

- the signal ownership deconfliction logic in Phase III
- closely spaced signals whose functional areas overlap
- aggressive trimming rules used to avoid duplicate claim ownership

This may be a valid structural outcome rather than an error, but the count is large enough that it deserves spatial review.

#### AADTConflict
Most likely from:

- disagreement between inherited road metadata and AADT-enriched metadata
- tied or conflicting AADT candidates in dense route environments
- multi-candidate AADT route buckets, which the run log explicitly showed were very common

This is likely a metadata consistency problem, not the main directional-labeling problem.

---

## Figure-by-Figure Notes

## Fig0 — Segment Count by Final Flow Role

### What it shows
A non-degenerate directional classification with `Downstream` dominant.

### What is useful here
Useful for understanding role distribution.

### What it cannot prove
It does not prove the roles are correct, only that the classifier produced them.

### Likely issue signal
The large `Unknown` bucket means a sizable share of the network still lacks reliable direction.

---

## Fig1 — Directional Role Mix by Zone

### What it shows
Zone-based directional composition looks coherent.

### What is useful here
This is one of the more trustworthy figures because it does not depend on crash/access counts.

### Likely issue signal
The much lower `AtSignal` share in Zone 2 makes sense. No obvious anomaly.

---

## Fig2 — Crash Density by Flow Role (Clipped)

### What it shows
All values are zero.

### Interpretation
This figure is not analytically valid yet. It is diagnosing a missing-data issue, not real crash density.

### Most logical origin
Crash count fields are absent, zeroed, overwritten, or mismapped before figure generation.

---

## Fig3 — Access Density by Flow Role (Clipped)

### What it shows
All values are zero.

### Interpretation
Same issue as Fig2.

### Most logical origin
Access count fields are absent, zeroed, overwritten, or mismapped before figure generation.

---

## Fig4 — Crash Direction Composition by Zone

### What it shows
No bars at all.

### Interpretation
This is a downstream consequence of total crash counts being zero.

### Most logical origin
Missing or zero crash directional count fields in the final dataset.

---

## Fig5 — Direction Source Distribution

### What it shows
A heavy reliance on `OracleNodeTopology`, then `NoReliableDirection`, then `MeasureTolerance`, with almost no `OracleRouteOrder`.

### Interpretation
This is a valuable diagnostic. It suggests the patched Oracle logic is working as a conservative resolver, but not yet as a high-coverage resolver.

### Most logical issue stem
Oracle topology is doing most of the work; route-order logic is not materially rescuing unresolved cases.

---

## Fig6 — Projected Measure Offset from Signal (Delta_M)

### What it shows
A very right-skewed distribution with a long tail.

### Interpretation
This supports the run-log evidence that many segments are far from the signal in measure space, which directly feeds `AmbiguousFarFromMeasure`.

### Most logical issue stem
Not necessarily a bug. More likely the combination of:

- legitimate long functional extents
- strict measure guard
- and some signal/segment pairings that remain ambiguous

---

## Fig7 — Final QC Flag Counts

### What it shows
The major flags are:

- TrimmedByNeighbor
- UnknownDirection
- effectively no MissingLinkID / OverlapClaim / CrashFarSnap

### Interpretation
This is useful and mostly credible.

### Important limitation
This figure does not include all Oracle-specific QC counts unless the script explicitly pulled them in. The CSV summary is more complete than the figure.

---

## Fig8 — Crash Density for Flagged vs Non-Flagged Segments

### What it shows
All values are zero.

### Interpretation
Not valid yet for evaluation.

### Most logical origin
Same crash-count field problem as Figs 2 and 4.

---

## Fig9 — AADT vs Crash Density by Flow Role

### What it shows
Points spread across AADT, but all crash densities are zero.

### Interpretation
This is actually useful as a diagnostic: AADT is present, but crash density is not.

### Most logical implication
AADT is surviving into the final figures dataset, but crash counts are not.

That narrows the likely bug to crash/access count persistence rather than a total dataset construction failure.

---

## Fig10 — Crash Rate (MVMT) by Speed Environment and Flow Role

### What it shows
No visible bars.

### Interpretation
Not usable yet because crash rate is zero everywhere.

### Most logical origin
Same missing crash count issue. The denominator fields (`AADT`, length, VMT proxies) appear to exist, but the numerator is zero.

---

## Fig11 — Top 1 Directional Crash-Type Counts

### What it shows
Only a single bar:

- `Access 1 = 6860`

### Why this is suspicious
This is not a crash-type figure in any meaningful sense if the only populated top count comes from `Cnt_Access_1`.

The uploaded CSV confirms this exactly:

- `Count_Field = Cnt_Access_1`
- `Crash_Count = 6860`
- `Crash_Type_Direction = Access 1`

### Interpretation
This figure is mislabeled or conceptually mixed.

### Most logical origin
The selection logic for “top directional crash types” is probably sweeping in all `Cnt_*` fields, including access-related counts, instead of restricting itself to crash-only directional count fields.

This is a **figure logic issue**, not a pipeline data issue.

---

## Fig12 — QC_ThirdStep Top Counts

### What it shows
Largest values include:

- `QCFlag | OracleAmbiguous`
- `QCFlag | TrimmedByNeighbor`
- `QCFlag | OracleNoMatch`
- `QCFlag | NodeMissing`
- `QCFlag | UnknownDirection`
- `QCFlag | AADTConflict`

### Interpretation
This is one of the most informative figures. It clearly identifies the main unresolved problems in the current output.

### Most logical implication
The pipeline’s next debugging focus should remain on Oracle ambiguity, node completeness, and directional reliability, not on segmentation or missing link IDs.

---

## Logical Issue Tree

## A. Zero crash and access densities

### Symptom
All crash/access plots collapse to zero.

### Most likely stems
1. Final output fields not populated.
2. Figures script reading wrong field names.
3. Count fields dropped or zeroed during writeback.
4. Crash/access summaries exist only in intermediate layers, not the final feature class.

### Least likely stem
A real-world absence of crashes and accesses. That is not plausible.

---

## B. High Oracle ambiguity and no-match counts

### Symptom
`OracleAmbiguous = 10,031`, `OracleNoMatch = 4,679`.

### Most likely stems
1. Oracle candidate multiplicity remains high even after clustering.
2. Measure guard is appropriately conservative but leaves many unresolved rows.
3. Oracle GIS keys do not provide full clean coverage of segment link IDs.
4. Route order is not contributing enough to resolve ties.

---

## C. High node missing count

### Symptom
`NodeMissing = 4,679`.

### Most likely stems
1. Base roadway data lacks native from/to node fields.
2. Oracle enrichment is incomplete for those rows.
3. Direction inference still depends heavily on node topology.

### Consequence
This directly worsens `OracleNoMatch` and `UnknownDirection`.

---

## D. High trimmed-by-neighbor count

### Symptom
`TrimmedByNeighbor = 5,748`.

### Most likely stems
1. Dense signal spacing.
2. Functional-area overlap rules doing substantial trimming.
3. Conservative ownership deconfliction in Phase III.

### Interpretation
This may be correct behavior, but the count is high enough that it deserves map review in several sample corridors.

---

## E. AADT conflict count

### Symptom
`AADTConflict = 2,322`.

### Most likely stems
1. Many multi-candidate AADT route buckets.
2. Disagreement between road inheritance and AADT-based fallback.
3. Dense route environments and tied measure windows.

### Interpretation
This is a secondary metadata quality issue. It matters, but it is not the main blocker right now.

---

## What Looks Encouraging

Several things are clearly improved or at least stable:

- segmentation completed successfully
- overlap-claim cleanup appears effective (`OverlapClaim = 0`)
- sliver control appears effective (`SuspiciousShortSegment = 0`)
- link-ID loss is negligible (`MissingLinkID = 3`)
- route mismatch is no longer a dominant issue (`RouteMismatch = 0`)
- AADT is surviving into the figures dataset
- direction-source diagnostics are rich enough to support focused Oracle debugging

So the project is past the point of catastrophic structural failure. The remaining issues are now more concentrated and diagnosable.

---

## Priority Fix Order

## Priority 1 — Fix crash/access field persistence into the final output

Before interpreting any safety figures, confirm in `Final_Functional_Segments` whether these final fields actually exist and contain values:

- `Crash_Total`
- `Crash_Up`
- `Crash_Down`
- `Crash_At`
- `Access_Count`
- any `Cnt_*` crash fields expected by the figures script

If the values are zero there too, the problem is upstream of the figures script.
If the values are populated there, then `thirdstepfigures.py` is reading the wrong fields.

This is the single highest-priority fix because it blocks all crash/access analytics.

---

## Priority 2 — Audit Oracle ambiguity spatially

Map and inspect samples of:

- `OracleAmbiguous`
- `OracleNoMatch`
- `NodeMissing`
- `UnknownDirection`
- especially `AmbiguousFarFromMeasure`

This will tell you whether the patched logic is too conservative or whether the Oracle keys/topology are truly insufficient.

---

## Priority 3 — Trace node availability from Oracle inputs to final output

Because `NodeMissing` and `OracleNoMatch` are numerically aligned, node availability should be treated as a central dependency.

Confirm:

- whether Oracle GIS keys contain begin/end nodes for those unmatched rows
- whether those fields are being joined correctly
- whether they are surviving into the GeoPandas labeling stage

---

## Priority 4 — Clean figure logic for directional crash-type summaries

`Fig11` should not present `Access 1` as a crash type unless that is explicitly intended.
Restrict the chart to actual crash directional count fields only.

---

## Priority 5 — Sample-review TrimmedByNeighbor corridors

This flag may be valid, but the count is large enough that you should verify it visually in a few representative areas.

---

## Bottom Line

The current run produced a **valid structural output** and a **useful diagnostic package**, but not yet a fully analysis-ready crash dataset.

### Most important confirmed problems

1. **Crash and access counts are zero in the figures dataset.**
2. **Oracle ambiguity remains the dominant unresolved directional-labeling problem.**
3. **Node completeness is still a major dependency and likely bottleneck.**
4. **Neighbor trimming is substantial and worth spot-checking.**
5. **The “top directional crash types” figure is currently logically mis-specified.**

### Most important confirmed strengths

1. Segmentation and writeback now complete successfully.
2. Link-ID loss is nearly eliminated.
3. Overlap-claim cleanup looks good.
4. Route mismatch is no longer the dominant source of failure.
5. The directional and zone figures are at least useful for structural debugging.

