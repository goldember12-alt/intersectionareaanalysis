# Access Route-Conflict Promotion Batch 001 Comparison

## Bounded Change

This batch promoted only these explicit reviewed same-corridor include pairs:

- `S-VA082PR SPOTSWOOD TRL` -> `R-VA US00033EB`
- `S-VA080NP FRANKLIN RD` -> `R-VA US00220NB`
- `S-VA095PR PORTERFIELD HWY` -> `R-VA US00019SB`

No production matching logic was changed. The existing reviewed-family include logic consumed the updated seed-family CSV.

Run command:

```powershell
python -m src.active.context_enrichment --run-label access-route-conflict-promotion-batch-001
```

## Assignment Counts

| Status | Before | After | Delta |
| --- | ---: | ---: | ---: |
| `matched` | 110 | 129 | +19 |
| `route_conflict` | 233 | 210 | -23 |
| `near_signal` | 16 | 20 | +4 |
| `measure_conflict` | 3 | 3 | 0 |

Recovered route conflicts split into:

- `19` newly `matched`
- `4` newly `near_signal`

One promoted-family row remains `route_conflict`: `S-VA080NP FRANKLIN RD` at `signal_1302` is `30.35` ft from the reviewed row, beyond the explicit `5` ft local threshold.

## Changed Access Rows

| Access point | Study area | Access route | Before | After | After position | Study row | Family |
| --- | --- | --- | --- | --- | --- | ---: | --- |
| `7a17dec1-849e-4ab3-bc3d-006d75fde9ad` | `signal_1289` | `S-VA080NP FRANKLIN RD` | `route_conflict` | `near_signal` | `near_signal` | 16244 | `franklin_rd_np__us00220nb` |
| `cac0abb7-aeb3-4d33-a6a2-efc909a1f895` | `signal_1299` | `S-VA080NP FRANKLIN RD` | `route_conflict` | `near_signal` | `near_signal` | 16244 | `franklin_rd_np__us00220nb` |
| `d8c0a16d-d9a5-4586-bcc7-e8600cc9fc5c` | `signal_1299` | `S-VA080NP FRANKLIN RD` | `route_conflict` | `matched` | `downstream` | 16244 | `franklin_rd_np__us00220nb` |
| `fbba82f6-6935-42e1-b871-4feef6005e90` | `signal_1299` | `S-VA080NP FRANKLIN RD` | `route_conflict` | `matched` | `downstream` | 16244 | `franklin_rd_np__us00220nb` |
| `f76d25fe-4977-4bad-a969-635fe2ef6f6b` | `signal_1302` | `S-VA080NP FRANKLIN RD` | `route_conflict` | `near_signal` | `near_signal` | 16244 | `franklin_rd_np__us00220nb` |
| `90aab423-558e-453a-815e-b441a103b7af` | `signal_1305` | `S-VA080NP FRANKLIN RD` | `route_conflict` | `matched` | `upstream` | 16244 | `franklin_rd_np__us00220nb` |
| `6473b1d4-2155-4968-9032-bc987041eaf4` | `signal_1314` | `S-VA082PR SPOTSWOOD TRL` | `route_conflict` | `matched` | `downstream` | 6445 | `spotswood_trl__us00033eb` |
| `06177940-7bb2-4c90-b1dd-c1d0116c75e8` | `signal_1314` | `S-VA082PR SPOTSWOOD TRL` | `route_conflict` | `matched` | `upstream` | 6445 | `spotswood_trl__us00033eb` |
| `839c043d-32ee-4259-97c8-1e518f17e28d` | `signal_1314` | `S-VA082PR SPOTSWOOD TRL` | `route_conflict` | `matched` | `upstream` | 6445 | `spotswood_trl__us00033eb` |
| `611ea453-bc61-49f8-8d53-923173dd6b46` | `signal_1315` | `S-VA082PR SPOTSWOOD TRL` | `route_conflict` | `matched` | `downstream` | 6445 | `spotswood_trl__us00033eb` |
| `dcb5c484-2b4a-4301-963a-1a5f0a2903a7` | `signal_1315` | `S-VA082PR SPOTSWOOD TRL` | `route_conflict` | `matched` | `downstream` | 6445 | `spotswood_trl__us00033eb` |
| `99a1d7a5-59c6-41a6-8c30-346e42ae1acf` | `signal_1315` | `S-VA082PR SPOTSWOOD TRL` | `route_conflict` | `matched` | `upstream` | 6445 | `spotswood_trl__us00033eb` |
| `8f53799e-4feb-47bd-8d8d-e20114cedaf5` | `signal_1315` | `S-VA082PR SPOTSWOOD TRL` | `route_conflict` | `matched` | `downstream` | 6445 | `spotswood_trl__us00033eb` |
| `611ea453-bc61-49f8-8d53-923173dd6b46` | `signal_1316` | `S-VA082PR SPOTSWOOD TRL` | `route_conflict` | `matched` | `upstream` | 6445 | `spotswood_trl__us00033eb` |
| `1ee6fbdf-ab00-4bbc-ac31-dd72fe2b63c9` | `signal_1399` | `S-VA095PR PORTERFIELD HWY` | `route_conflict` | `matched` | `downstream` | 15333 | `porterfield_hwy__us00019sb` |
| `0229b15b-3a12-4f5a-8f4a-9361f43e7c37` | `signal_1399` | `S-VA095PR PORTERFIELD HWY` | `route_conflict` | `near_signal` | `near_signal` | 15333 | `porterfield_hwy__us00019sb` |
| `e7f0bdd5-5860-4b24-9608-21f8cf730f26` | `signal_1399` | `S-VA095PR PORTERFIELD HWY` | `route_conflict` | `matched` | `upstream` | 15333 | `porterfield_hwy__us00019sb` |
| `61063a94-9f98-4d6f-9142-17e7df823032` | `signal_1399` | `S-VA095PR PORTERFIELD HWY` | `route_conflict` | `matched` | `upstream` | 15333 | `porterfield_hwy__us00019sb` |
| `4d755e31-5eba-48fa-a012-42c5693f90b3` | `signal_1399` | `S-VA095PR PORTERFIELD HWY` | `route_conflict` | `matched` | `upstream` | 15333 | `porterfield_hwy__us00019sb` |
| `4b64e1d8-9e94-43aa-b675-7422534acbea` | `signal_1400` | `S-VA095PR PORTERFIELD HWY` | `route_conflict` | `matched` | `downstream` | 15333 | `porterfield_hwy__us00019sb` |
| `0f5247a9-0a11-44b9-9af7-f7fc0c2eb5c6` | `signal_1400` | `S-VA095PR PORTERFIELD HWY` | `route_conflict` | `matched` | `downstream` | 15333 | `porterfield_hwy__us00019sb` |
| `1ee6fbdf-ab00-4bbc-ac31-dd72fe2b63c9` | `signal_1400` | `S-VA095PR PORTERFIELD HWY` | `route_conflict` | `matched` | `upstream` | 15333 | `porterfield_hwy__us00019sb` |
| `0229b15b-3a12-4f5a-8f4a-9361f43e7c37` | `signal_1400` | `S-VA095PR PORTERFIELD HWY` | `route_conflict` | `matched` | `upstream` | 15333 | `porterfield_hwy__us00019sb` |

## Signals With Changed Access Counts

| Study area | Signal label | Total | Downstream | Upstream | Near signal | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `signal_1289` | Franklin Rd / Indian Grave Rd | `1->1` | `0->0` | `0->0` | `0->1` | `partial->matched` |
| `signal_1299` | Franklin Rd / Old Rocky Mount Rd | `3->3` | `0->2` | `0->0` | `0->1` | `partial->matched` |
| `signal_1302` | Franklin Rd / Pheasant Ridge Rd | `2->2` | `0->0` | `0->0` | `0->1` | `partial->partial` |
| `signal_1305` | Franklin Rd / Buck Mountain Rd | `4->4` | `0->0` | `0->1` | `0->0` | `partial->partial` |
| `signal_1314` | Spotswood Trl / Island Ford Rd/Stover Dr | `4->4` | `0->1` | `0->2` | `0->0` | `partial->partial` |
| `signal_1315` | Spotswood Trl / Mt. Olivet Church Rd/Resort Rd | `5->5` | `0->3` | `0->1` | `0->0` | `partial->partial` |
| `signal_1316` | Spotswood Trail / Rockingham Pike/East Point Road | `2->2` | `0->0` | `0->1` | `0->0` | `partial->partial` |
| `signal_1399` | Porterfield Hwy / Chantilly Way | `6->6` | `0->1` | `0->3` | `0->1` | `partial->partial` |
| `signal_1400` | Porterfield Hwy / Elementary Dr | `8->8` | `0->2` | `0->2` | `0->0` | `partial->partial` |

## Guardrails Preserved

- No other candidate families were promoted.
- Excluded families remain excluded.
- The promoted `S-VA080NP FRANKLIN RD` pair still refused the one reviewed-family row outside the `5` ft threshold.
- The 11 `S-VA122PR HAMPTON BLVD` / `R-VA SR00337WB` wrong-carriageway-risk rows remain refused.
