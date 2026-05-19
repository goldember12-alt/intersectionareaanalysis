# Context Enrichment Access Alias Recommendation

**Status: SUPPORTING REFERENCE.** This context-enrichment planning note remains in place for later graph-first crash/access migration review.

## Scope

This memo evaluates whether any bounded, auditable route-alias logic is justified for access matching in the current `approach_shaped` context-enrichment slice.

Data reviewed:

- latest run summary: `work/output/context_enrichment/runs/history/context_enrichment_run_summary_20260423_143606.json`
- latest access points table: `work/output/context_enrichment/tables/history/access_assignment_points_20260423_143556.csv`
- latest approach-row context table: `work/output/context_enrichment/tables/history/approach_row_context_enriched_20260423_143551.csv`
- latest signal context table: `work/output/context_enrichment/tables/history/signal_study_area_context_enriched_20260423_143553.csv`
- latest review GeoJSONs for access points and approach rows under `work/output/context_enrichment/review/geojson/history/`

## Current route-conflict concentration

Route-conflict volume in the latest run:

- `288` route-conflict rows
- `246` unique access points

Top repeated conflict pairs by route-conflict rows:

| Access route | Study route | Rows | Unique points | Signals |
| --- | --- | ---: | ---: | ---: |
| `S-VA029PR RICHMOND HWY` | `R-VA US00001NB` | 27 | 20 | 8 |
| `S-VA020PR E HUNDRED RD` | `R-VA SR00010EB` | 18 | 16 | 3 |
| `S-VA043PR W BROAD ST` | `R-VA US00250EB` | 16 | 14 | 6 |
| `R-VA US00058WBALT001` | `R-VA US00058EBALT001` | 13 | 13 | 3 |
| `R-VA029SC00779SB` | `R-VA US00001NB` | 12 | 3 | 4 |
| `S-VA076PR JEFFERSON DAVIS HWY` | `R-VA US00001NB` | 11 | 11 | 4 |
| `S-VA122PR HAMPTON BLVD` | `R-VA SR00337EB` | 11 | 11 | 3 |
| `S-VA122PR HAMPTON BLVD` | `R-VA SR00337WB` | 11 | 10 | 4 |
| `S-VA076NP JEFFERSON DAVIS HWY` | `R-VA US00001NB` | 9 | 9 | 4 |
| `S-VA089PR WARRENTON RD` | `R-VA US00017NB` | 9 | 9 | 3 |

These top ten pairs account for a large minority of the unresolved access problem and are the right place to inspect any future alias idea first.

Route-conflicts are also concentrated on a small set of study routes:

- `R-VA US00001NB`: `50` route-conflict rows
- `R-VA US00250EB`: `30`
- `R-VA SR00337WB`: `20`
- `R-VA US00220NB`: `18`
- `R-VA SR00010EB`: `17`
- `R-VA US00019SB`: `17`
- `R-VA US00058EBALT001`: `17`

## Corridor-family read

### Same-corridor name/number families

These families often look like the same corridor in practice based on signal labels and local geometry, but they do **not** share compatible measure ranges with the current study-road rows.

Examples:

- `S-VA020PR E HUNDRED RD` vs `R-VA SR00010EB`
  - signal labels explicitly say `E. Hundred Rd`
  - nearest-row distances are essentially zero
  - access measures `0.13` to `1.45`
  - approach measures `19.99` to `21.23`
- `S-VA122PR HAMPTON BLVD` vs `R-VA SR00337EB`
  - nearest-row distances are essentially zero
  - access measures `1.28` to `2.58`
  - approach measures `30.32` to `31.96`
- `S-VA043NP W BROAD ST` vs `R-VA US00250EB`
  - nearest-row distances are essentially zero
  - access measures `2.94` to `4.05`
  - approach measures `157.93` to `159.78`
- `S-VA089PR WARRENTON RD` vs `R-VA US00017NB`
  - nearest-row distances are essentially zero
  - access measures `2.69` to `4.07`
  - approach measures `181.59` to `183.54`

Interpretation:

- these look like street-name versus numbered-route representations of the same corridor
- but the current access and study-road measure systems are not aligned
- a route-only alias rule would not make them eligible under the existing measure contract
- making them match would require a second methodological change beyond route identity, which is outside this bounded pass

### Same-corridor appearance but materially offset families

Examples:

- `S-VA029PR RICHMOND HWY` vs `R-VA US00001NB`
  - signal labels say `Richmond Highway`
  - approach common route is `US-1N`
  - nearest-row distances are typically `44` to `59` feet
  - access measures `2.45` to `4.10`
  - approach measures `187.05` to `189.59`
- `S-VA043PR W BROAD ST` vs `R-VA US00250EB`
  - nearest-row distances are typically `45` to `62` feet
  - measures are also incompatible

Interpretation:

- these still look like same-corridor naming in many cases
- but the offset distances increase the chance of frontage-road, side-lane, or parallel-facility confusion
- measure systems remain incompatible anyway
- this is not a clean bounded alias target

### Opposite-direction numeric-route families

These are the only route-conflict families that would mostly survive the current measure and distance checks if route identity were relaxed:

- `R-VA US00058WBALT001` vs `R-VA US00058EBALT001`: `13` rows
- `R-VA US00019NB` vs `R-VA US00019SB`: `2` rows
- `R-VA US00250WB` vs `R-VA US00250EB`: `2` rows

Across all `288` route-conflict rows:

- only `19` would pass measure support if route were ignored
- only `17` would pass both measure and distance with a unique candidate row
- all `17` come from the opposite-direction families above

Interpretation:

- these are not safe alias candidates
- they are exactly the cases where a relaxed route rule could collapse opposing carriageways or opposing flow
- the fact that they are measure-compatible makes them more dangerous, not safer

### Secondary/local versus parent-route families

Example:

- `R-VA029SC00779SB` vs `R-VA US00001NB`
  - `12` route-conflict rows but only `3` unique access points repeated across `4` study areas
  - nearest-row distances around `48` to `50` feet
  - access measures `0.78` to `0.82`
  - approach measures `187.05` to `189.17`

Interpretation:

- this does not read as a narrow street-name alias
- it looks more like a secondary/local route or frontage-style relation to the parent corridor
- it should remain unmatched

## Recommendation

### 1. Should access remain exact-route only for now?

Yes.

That is the strongest recommendation from the current evidence.

### 2. If not, what is the smallest defensible alias rule or alias table concept?

No production alias rule is defensible from this slice.

If a future experiment is needed, the smallest defensible concept is not a general alias rule. It would be a manually curated, family-specific review table that is tested outside production matching and still preserves:

- current distance threshold
- current unique-row requirement
- explicit family-by-family validation
- explicit do-not-merge exclusions for opposite-direction route pairs

Even that prototype would need measure-system proof first.

### 3. Which specific alias families, if any, look safe enough for a future bounded implementation?

None are safe enough for production implementation now.

Families worth manual review only, because they appear to reference the same corridor by name but fail the current measure contract, include:

- `E HUNDRED RD` with `SR00010EB`
- `HAMPTON BLVD` with `SR00337EB/WB`
- `W BROAD ST` with `US00250EB`
- `WARRENTON RD` with `US00017NB`
- `RICHMOND HWY` or `JEFFERSON DAVIS HWY` with `US00001NB`

These are candidates for documentation and manual corridor study, not for direct matching logic.

### 4. Which apparent aliases should explicitly NOT be merged?

- `R-VA US00058WBALT001` with `R-VA US00058EBALT001`
- `R-VA US00019NB` with `R-VA US00019SB`
- `R-VA US00250WB` with `R-VA US00250EB`
- `R-VA029SC00779SB` with `R-VA US00001NB`

Reason:

- the first three are opposite-direction route families and create direct cross-carriageway false-positive risk
- the last is not a clean same-name alias and behaves more like a local/secondary versus parent-route relationship

### 5. What validation would be required before any alias logic is promoted?

At minimum:

1. family-by-family evidence that the access-route measure system and study-road measure system are truly compatible, or a separately documented bounded measure-bridge rule
2. per-family counts of points that would newly match, newly remain rejected, and newly conflict
3. mapped spot checks across multiple signals for each candidate family
4. explicit review of opposing-direction and frontage-road false-positive risk
5. proof that the alias family does not silently broaden into street-name fuzzy matching

## Final recommendation

Keep access matching exact-route only for now.

The current route-conflict problem is real, but the evidence does not support a safe bounded alias rule. Most same-corridor-looking families fail measure compatibility, and the only families that *would* activate under route relaxation are the opposite-direction numeric-route cases that should remain unmatched.

Recommended next step:

- no production change
- document the repeated same-corridor name/number families
- if needed later, build a manual-review framework or a separate bounded alias prototype outside the active matching path
