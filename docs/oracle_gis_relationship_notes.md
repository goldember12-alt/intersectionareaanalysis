# Oracle–GIS Relationship Notes

## 1. ArcGIS layer structure

`Final_Functional_Segments` contains these key fields relevant to Oracle interaction:

- `LINKID`
- `MASTER_RTE_NM`
- `FromNode_Norm`
- `ToNode_Norm`
- `AADT`
- `SegMid_M`
- `Signal_M`
- `Delta_M`
- `Flow_Role`

It also contains segment-level crash/access outputs such as:

- `Cnt_Crash_Up`
- `Cnt_Crash_Down`
- `Cnt_Crash_At`
- `Cnt_Access`

## 2. Oracle table structure

From `rns.eyroadxx`, the important Oracle fields identified are:

- `TMSLINKID`
- `RTE_NM`
- `BEGINNODE`
- `ENDNODE`
- `LINKSEQUENCE`
- `ROUTEMILEPOINT`
- `BEGINOFFSET`
- `ENDOFFSET`
- `AVERAGEDAILYTRAFFIC`
- `RURALURBANDESIGNATION`
- likely useful cross-section fields from columns BL to BV

These Oracle fields are much closer to a route/network reference system than a finished GIS segmentation output.

## 3. How the two datasets relate

### 3.1 `LINKID` in GIS is related to `TMSLINKID` in Oracle, but not one-to-one

This is the most important finding.

You tested `LINKID = 601180` in ArcGIS and got 3 segment rows:

- 1 row with `MASTER_RTE_NM = R-VA US00011SB`
- 2 rows with `MASTER_RTE_NM = R-VA US00011NB`

But in Oracle, `TMSLINKID = 601180` returned 81 rows, all with:

- `RTE_NM = R-VA US00011NB`

So:

1. ArcGIS `LINKID` is not a unique key for one segment.
2. Oracle `TMSLINKID` is not a one-row lookup key.
3. One GIS link can correspond to many Oracle rows.
4. The GIS side can contain both directions for a given `LINKID`.
5. The Oracle `TMSLINKID` you tested only represented the NB side.

### 3.2 Direction is not uniquely carried by `LINKID`

This is the second major finding.

For `601180`:

- ArcGIS had both NB and SB.
- Oracle `TMSLINKID = 601180` had only NB.

That means you cannot assume `LINKID == TMSLINKID` is enough to identify the correct Oracle record set.

You likely need at least:

- `LINKID / TMSLINKID`
- plus `MASTER_RTE_NM / RTE_NM`

to distinguish direction.

## 4. What Oracle appears to represent

### 4.1 Oracle rows look like ordered network pieces along a route

For `TMSLINKID = 601180`, Oracle rows showed:

- increasing `LINKSEQUENCE`
- generally increasing `ROUTEMILEPOINT`
- changing `BEGINNODE` and `ENDNODE`

This strongly suggests `rns.eyroadxx` stores an ordered sequence of route/network records, not one flat road-segment lookup row.

So Oracle is probably useful for:

- route direction
- ordered traversal along a route
- node-to-node connectivity
- locating a segment relative to an intersection

rather than as a simple attribute table keyed only by `TMSLINKID`.

### 4.2 `BEGINNODE / ENDNODE` are likely the most valuable upstream/downstream fields

If you eventually know the node representing the intersection, then Oracle can likely support logic like:

- `ENDNODE = intersection node` → approach to the intersection
- `BEGINNODE = intersection node` → departure from the intersection

That would be a much stronger upstream/downstream basis than simply using map orientation.

### 4.3 `LINKSEQUENCE` and `ROUTEMILEPOINT` may provide a backup directional ordering

Even if node matching is messy, these fields appear to provide route order:

- lower `LINKSEQUENCE / ROUTEMILEPOINT` = earlier along route
- higher `LINKSEQUENCE / ROUTEMILEPOINT` = later along route

For direction-coded routes like `US00011NB`, that may let you determine whether something is before or after an intersection along the coded direction.

## 5. What is currently missing on the GIS side

### 5.1 The most useful ArcGIS directional fields were blank for your test case

For `LINKID = 601180`, these fields were blank in `Final_Functional_Segments`:

- `FromNode_Norm`
- `ToNode_Norm`
- `SegMid_M`
- `Signal_M`
- `Delta_M`
- `Flow_Role`

That means your current GIS output is not yet carrying enough resolved route-position information for that test segment.

So even though the GIS schema is designed to hold directional logic, the values are not yet consistently populated.

## 6. Practical interpretation

### 6.1 Oracle is richer for network reference; GIS is richer for spatial segmentation

Right now the division looks like this:

**ArcGIS is best for:**

1. actual segment geometries
2. signal proximity
3. crash counts by segment
4. final mapped outputs

**Oracle is best for:**

1. route identity
2. coded travel direction
3. node-based topology
4. ordered progression along route
5. potentially reliable AADT and roadway attributes

That means Oracle should probably be treated as a reference network table, not just a CSV of attributes to blindly join by `LINKID`.

## 7. Most likely join logic going forward

### 7.1 A simple `LINKID` join is not enough

Your working relationship is probably something like:

**Primary join dimensions**

- `LINKID ↔ TMSLINKID`
- `MASTER_RTE_NM ↔ RTE_NM`

**Secondary disambiguation fields**

- node fields: `FromNode_Norm / ToNode_Norm ↔ BEGINNODE / ENDNODE`
- or route-position fields: `SegMid_M, Signal_M, Delta_M ↔ ROUTEMILEPOINT, LINKSEQUENCE`

That is, Oracle may help identify where along the route a GIS segment lies, not just what link ID it has.

## 8. Plain-language version

`Final_Functional_Segments` is a segment-level GIS output around intersections, while `rns.eyroadxx` is a route/network reference table in Oracle.

`LINKID` in GIS relates to `TMSLINKID` in Oracle, but the relationship is not one-to-one. A single `TMSLINKID` can correspond to many Oracle rows, and a single GIS `LINKID` can appear in multiple directional segment records.

Therefore, Oracle should not be joined to GIS by `LINKID` alone. Direction and position must also be considered, likely using `MASTER_RTE_NM / RTE_NM` plus node or route-order fields such as `BEGINNODE`, `ENDNODE`, `LINKSEQUENCE`, and `ROUTEMILEPOINT`.

## 9. Recommended extraction design before building the giant CSV

Before building the giant CSV, define the Oracle extraction in two layers.

### Layer 1: broad lookup export

Export for all relevant `TMSLINKID`s:

- `TMSLINKID`
- `RTE_NM`
- `BEGINNODE`
- `ENDNODE`
- `LINKSEQUENCE`
- `ROUTEMILEPOINT`
- `BEGINOFFSET`
- `ENDOFFSET`
- `AVERAGEDAILYTRAFFIC`
- `RURALURBANDESIGNATION`
- desired BL–BV fields

### Layer 2: matching logic

Later decide how a GIS segment chooses the correct Oracle row subset using:

1. route name match
2. directional match
3. node match
4. or measure/sequence proximity

## 10. Bottom line

- Oracle contains useful topology/order information for upstream/downstream.
- `LINKID` alone is not a safe join key.
- The GIS schema is set up for directional logic, but some of the needed fields are not yet populated in your current output.
- The safest next design move is to treat Oracle as a network-reference dataset and explicitly define the GIS↔Oracle matching rules before building the full CSV export.
