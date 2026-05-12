# Directed Signal-Leg QGIS Review Layers

## Bounded purpose

These layers support manual GIS QA of the current directed signal-leg scaffold before any gating rules, crash assignment, crash reads, or true vehicle-direction inference.

The export reads only existing directed segment outputs under `work/output/directed_segments/` and joins review CSV fields onto existing leg, bin, signal, and access-anchor geometry where available.

## Command

Use the bootstrap-reported interpreter:

```powershell
<bootstrap-reported-python> -m src.active.directed_segments.qgis_review_layers
```

Optional root override:

```powershell
<bootstrap-reported-python> -m src.active.directed_segments.qgis_review_layers --output-root work/output/directed_segments
```

## Current outputs

GeoJSON review layers are written to:

- `work/output/directed_segments/review/geojson/current/`

The layer inventory is written to:

- `work/output/directed_segments/review/current/qgis_review_layer_inventory.csv`

Rows that cannot be exported because a review row does not join to usable geometry are written to:

- `work/output/directed_segments/review/current/gis_export_unresolved_rows.csv`

The zero-length/invalid-geometry review layer uses source signal or anchor point geometry so unresolved line cases remain locatable in QGIS.
