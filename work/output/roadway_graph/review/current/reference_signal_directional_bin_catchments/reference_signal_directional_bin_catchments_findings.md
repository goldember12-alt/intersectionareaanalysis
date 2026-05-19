# Reference-Signal Directional Bin Catchments Findings

**Status:** Roadway-only catchment surface for prototype usable directional bins.

## Bounded Question

This module creates directional catchment polygons from the conservative prototype usable reference-signal-centered directional bins. It does not read crash data, read crash assignment outputs, use crash direction fields, infer direction from crashes, modify scaffold construction, recover blocked records, force divided pairs, or perform crash analysis.

## Catchment Surface

- Input usable directional bins: 208340
- Catchments created: 208340
- Usable catchments: 200061
- Unstable/review catchments: 7281
- Blocked catchments: 998
- Downstream catchments: 104268
- Upstream catchments: 104072
- Divided physical catchments: 14604
- Undivided pseudo-direction catchments: 193736

Divided physical records use a conservative two-sided buffer around the physical directional bin geometry. Undivided centerline pseudo-direction records use explicit local-vector side polygons: right side for A->B downstream and left side for B->A upstream, following the existing roadway-geometry convention. Bins remain indexed from the TRUE reference signal A.

## Geometry Stage QA

- Input undivided usable rows: 193736
- Undivided rows with source bin geometry after join: 193736
- Undivided rows with valid local vector: 192796
- Undivided rows with non-empty constructed polygon before export: 193736
- Undivided rows with non-empty polygon after GeoJSON reload: 193736
- Divided rows with non-empty polygon after GeoJSON reload: 14604
- Empty geometry counts by representation: {"divided_physical_carriageway": 0, "undivided_centerline_pseudo_direction": 0}

## QA Interpretation

Unstable/review catchments are retained and flagged when local geometry is near an anchor, too short, kinked, or otherwise unsuitable for forced side assignment. Crash direction fields are not used.

## CRS Convention

Catchment geometries are exported in the repository working projected CRS, `EPSG:3968` (`NAD83 / Virginia Lambert`) with metre coordinates. The companion `directional_bin_catchment_crs_metadata.json` is authoritative for downstream consumers if a GeoJSON reader reports a default geographic CRS.

## Recommendation

Usable catchments are ready for a later crash-point assignment prototype. Unstable_review and blocked catchments should stay excluded or review-only unless explicitly accepted after a separate audit.
