# Roadway Graph QGIS Review Layers

**Status: CURRENT ACTIVE.** This is the current roadway_graph review-layer guide.

## Bounded Purpose

These layers support manual QGIS review of the current `roadway_graph` QA outputs before Step 5 oriented segments, crash assignment, access assignment, or true vehicle-direction inference.

The export reads existing tables and GeoJSON layers under `work/output/roadway_graph/` and joins QA fields onto existing signal-point and adjacent-edge geometry.

## Command

Use the bootstrap-reported interpreter:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.qgis_review_layers
```

Optional root override:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.qgis_review_layers --output-root work/output/roadway_graph
```

## Outputs

Targeted GeoJSON layers are written to:

- `work/output/roadway_graph/review/geojson/current/`

Layer inventory:

- `work/output/roadway_graph/review/current/qgis_graph_review_layer_inventory.csv`

Rows that cannot be mapped to a requested geometry layer:

- `work/output/roadway_graph/review/current/qgis_graph_review_unmapped_rows.csv`

Some review groups, such as zero-edge and least-suitable Step 5 candidates, do not have adjacent edge geometry by definition. Those are exported as signal-point layers where appropriate, and missing edge joins are logged for edge-only layers.
