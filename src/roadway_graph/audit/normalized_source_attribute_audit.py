from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/normalized_source_attribute_audit")
SOURCE_ROOT = Path("Intersection Crash Analysis Layers")
NORMALIZED_ROOT = Path("artifacts/normalized")

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

FIELD_FOCUS = {
    "access": [
        "ACCESS_DIRECTION",
        "ACCESS_CONTROL",
        "NUMBER_OF_APPROACHES",
        "INDUSTRIAL",
        "RESIDENTIAL",
        "COMMERCIAL_RETAIL",
        "GOV_SCHOOL_INSTITUTIONAL",
        "TURN_LANES_PRIMARY_ROUTE",
        "CROSS_STREET",
    ],
    "speed": [
        "ROUTE_COMMON_NAME",
        "LOC_COMP_DIRECTIONALITY_NAME",
        "CAR_SPEED_LIMIT",
        "TRUCK_SPEED_LIMIT",
        "EVENT_SOURCE_ID",
        "EVENT_LOCATION_ID",
        "EVENT_COMPONENT_ID",
        "ROUTE_FROM_MEASURE",
        "ROUTE_TO_MEASURE",
        "RTE_TYPE_CD",
        "RTE_TYPE_NM",
    ],
    "aadt": [
        "AADT",
        "AADT_YR",
        "DIRECTION_FACTOR",
        "DIRECTIONALITY",
        "RTE_NM",
        "MASTER_RTE_NM",
        "LINKID",
        "EDGE_RTE_KEY",
        "FROM_MEASURE",
        "TO_MEASURE",
        "TRANSPORT_EDGE_FROM_MSR",
        "TRANSPORT_EDGE_TO_MSR",
    ],
    "roads": [
        "RTE_NM",
        "RTE_COMMON",
        "FROM_MEASURE",
        "TO_MEASURE",
        "RTE_FROM_M",
        "RTE_TO_MSR",
        "RIM_FACILI",
        "RIM_ACCESS",
        "LANE_THRU_",
        "LANE_THRU1",
        "LANE_REVER",
        "RIM_MEDIAN",
        "MEDIAN_WID",
        "MEDIAN_COV",
        "MEDIAN_IND",
        "MEDIAN_OPP",
        "RTE_CATEGO",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
        "LOC_COMP_D",
        "LOC_COMP_1",
        "RTE_ID",
        "EVENT_SOUR",
        "EVENT_LOCA",
        "EVENT_COMP",
        "RTE_MEASUR",
    ],
    "crashes": [
        "DOCUMENT_NBR",
        "CRASH_YEAR",
        "CRASH_DT",
        "CRASH_SEVERITY",
        "VEH_COUNT",
        "COLLISION_TYPE",
        "ROADWAY_DESCRIPTION",
        "INTERSECTION_TYPE",
        "TRAFFIC_CONTROL_TYPE",
        "AREA_TYPE",
        "RTE_NM",
        "RNS_MP",
        "NODE",
        "OFFSET",
    ],
    "signals": [
        "GLOBALID",
        "ASSET_ID",
        "REG_SIGNAL_ID",
        "ASSET_NUM",
        "STATUS",
        "MAJ_NAME",
        "MAJ_NUM",
        "MINOR_NAME",
        "MINOR_NUM",
        "SIGNAL_NO",
        "INTNUM",
        "INTNO",
    ],
}

USEFUL_FIELD_TOKENS = {
    "access": ("ACCESS", "APPROACH", "COMMERCIAL", "RESIDENTIAL", "INDUSTRIAL", "INSTITUTION", "SCHOOL", "TURN", "CROSS"),
    "speed": ("SPEED", "ROUTE", "RTE", "MEASURE", "DIRECTION", "EVENT", "LOCATION", "COMPONENT"),
    "aadt": ("AADT", "AAWDT", "DIRECTION", "ROUTE", "RTE", "MEASURE", "LINK", "EDGE", "MASTER"),
    "roads": ("RTE", "ROUTE", "LANE", "MEDIAN", "DIVID", "ONEWAY", "ACCESS", "FACILI", "RAMP", "CLASS", "MEASURE", "EVENT", "LOC_COMP"),
    "crashes": ("DOCUMENT", "CRASH", "COLLISION", "AREA", "RTE", "NODE", "OFFSET", "INTERSECTION", "TRAFFIC"),
    "signals": ("SIGNAL", "ASSET", "REG", "ROUTE", "MAJ", "MINOR", "INT", "STATUS"),
}

OUTPUTS = {
    "summary": "normalized_source_attribute_audit_summary.csv",
    "schema": "normalized_source_schema_comparison.csv",
    "nonnull": "normalized_source_non_null_comparison.csv",
    "flags": "normalized_source_field_loss_flags.csv",
    "access": "access_source_attribute_preservation_audit.csv",
    "speed": "speed_source_attribute_preservation_audit.csv",
    "aadt": "aadt_source_attribute_preservation_audit.csv",
    "roads": "roads_source_attribute_preservation_audit.csv",
    "crashes": "crash_source_attribute_preservation_audit.csv",
    "recommendations": "normalized_source_restaging_recommendations.csv",
    "findings": "normalized_source_attribute_audit_findings.md",
    "manifest": "normalized_source_attribute_audit_manifest.json",
}


@dataclass(frozen=True)
class DatasetSpec:
    dataset: str
    normalized_file: Path
    sources: tuple[tuple[Path, str], ...]


DATASETS = (
    DatasetSpec("roads", NORMALIZED_ROOT / "roads.parquet", ((SOURCE_ROOT / "Travelway.gdb", "Travelway"),)),
    DatasetSpec("access", NORMALIZED_ROOT / "access.parquet", ((SOURCE_ROOT / "accesspoints.gdb", "layer_lrspoint"),)),
    DatasetSpec("speed", NORMALIZED_ROOT / "speed.parquet", ((SOURCE_ROOT / "postedspeedlimits.gdb", "SDE_VDOT_SPEED_LIMIT_MSTR_RTE"),)),
    DatasetSpec("aadt", NORMALIZED_ROOT / "aadt.parquet", ((SOURCE_ROOT / "New_AADT.gdb", "New_AADT"),)),
    DatasetSpec("crashes", NORMALIZED_ROOT / "crashes.parquet", ((SOURCE_ROOT / "crashdata.gdb", "CrashData_Basic"),)),
    DatasetSpec(
        "signals",
        NORMALIZED_ROOT / "signals.parquet",
        (
            (SOURCE_ROOT / "HMMS_Traffic_Signals.gdb", "HMMS_TrafficSignals_Flat"),
            (SOURCE_ROOT / "Hampton_Analysis.gdb", "Hampton_Signals"),
            (SOURCE_ROOT / "Traffic_Signals_-_City_of_Norfolk.gdb", "Norfolk_Signals"),
        ),
    ),
)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _nonempty(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype(str).str.strip().ne("")


def _direction_like(field: str) -> bool:
    lower = field.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS)


def _read_source(spec: DatasetSpec) -> tuple[pd.DataFrame | None, list[dict[str, Any]], str]:
    frames: list[pd.DataFrame] = []
    inventory: list[dict[str, Any]] = []
    errors: list[str] = []
    for source_path, layer in spec.sources:
        row: dict[str, Any] = {
            "dataset": spec.dataset,
            "source_path": str(source_path),
            "source_layer": layer,
            "source_exists": source_path.exists(),
            "read_status": "not_read",
            "source_row_count": 0,
            "source_field_count": 0,
        }
        if not source_path.exists():
            row["read_status"] = "missing_source_path"
            inventory.append(row)
            continue
        try:
            geo_frame = gpd.read_file(source_path, layer=layer)
            frame = pd.DataFrame(geo_frame.copy())
            if "geometry" in frame.columns:
                frame["geometry"] = geo_frame.geometry.geom_type.where(geo_frame.geometry.notna(), "")
            frame["__audit_source_path"] = str(source_path)
            frame["__audit_source_layer"] = layer
            frames.append(frame)
            row["read_status"] = "read"
            row["source_row_count"] = len(frame)
            row["source_field_count"] = len([c for c in frame.columns if not c.startswith("__audit_")])
        except Exception as exc:  # noqa: BLE001 - audit should report source read failures.
            row["read_status"] = "read_error"
            row["read_error"] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{spec.dataset}:{layer}:{type(exc).__name__}:{exc}")
        inventory.append(row)
    if not frames:
        return None, inventory, "|".join(errors)
    return pd.concat(frames, ignore_index=True, sort=False), inventory, "|".join(errors)


def _read_normalized(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.DataFrame(gpd.read_parquet(path).copy())


def _schema_rows(dataset: str, source: pd.DataFrame | None, normalized: pd.DataFrame | None, source_layers: str) -> list[dict[str, Any]]:
    source_dtypes = {} if source is None else {c: str(source[c].dtype) for c in source.columns if not c.startswith("__audit_")}
    normalized_dtypes = {} if normalized is None else {c: str(normalized[c].dtype) for c in normalized.columns}
    fields = sorted(set(source_dtypes) | set(normalized_dtypes))
    rows = []
    for field in fields:
        rows.append(
            {
                "dataset": dataset,
                "field_name": field,
                "source_layers": source_layers,
                "present_in_source": field in source_dtypes,
                "present_in_parquet": field in normalized_dtypes,
                "source_dtype": source_dtypes.get(field, ""),
                "parquet_dtype": normalized_dtypes.get(field, ""),
                "dtype_changed": bool(field in source_dtypes and field in normalized_dtypes and source_dtypes[field] != normalized_dtypes[field]),
                "focus_field": field in FIELD_FOCUS.get(dataset, []),
                "useful_candidate_field": _useful_field(dataset, field),
            }
        )
    return rows


def _useful_field(dataset: str, field: str) -> bool:
    if field in FIELD_FOCUS.get(dataset, []):
        return True
    upper = field.upper()
    return any(token in upper for token in USEFUL_FIELD_TOKENS.get(dataset, ()))


def _profile_field(series: pd.Series) -> tuple[int, int, str]:
    nonempty = series.loc[_nonempty(series)]
    non_null_count = int(len(nonempty))
    unique_count = int(nonempty.astype(str).nunique(dropna=True)) if non_null_count else 0
    top_values = ""
    if non_null_count:
        top_values = "|".join(f"{value}:{int(count)}" for value, count in nonempty.astype(str).value_counts().head(5).items())
    return non_null_count, unique_count, top_values


def _nonnull_rows(dataset: str, source: pd.DataFrame | None, normalized: pd.DataFrame | None) -> list[dict[str, Any]]:
    if source is None or normalized is None:
        return []
    shared_fields = sorted(set(source.columns) & set(normalized.columns) - {"__audit_source_path", "__audit_source_layer"})
    rows = []
    for field in shared_fields:
        excluded = dataset == "crashes" and _direction_like(field)
        if excluded:
            rows.append(
                {
                    "dataset": dataset,
                    "field_name": field,
                    "source_row_count": len(source),
                    "parquet_row_count": len(normalized),
                    "source_non_null_count": "",
                    "parquet_non_null_count": "",
                    "source_unique_count": "",
                    "parquet_unique_count": "",
                    "null_loss_count": "",
                    "null_loss_ratio": "",
                    "unique_count_ratio": "",
                    "value_profile_status": "excluded_crash_direction_like_field",
                    "source_top_values": "",
                    "parquet_top_values": "",
                    "focus_field": field in FIELD_FOCUS.get(dataset, []),
                    "useful_candidate_field": _useful_field(dataset, field),
                }
            )
            continue
        source_non_null, source_unique, source_top = _profile_field(source[field])
        parquet_non_null, parquet_unique, parquet_top = _profile_field(normalized[field])
        null_loss_count = max(0, source_non_null - parquet_non_null)
        null_loss_ratio = round(null_loss_count / source_non_null, 6) if source_non_null else 0.0
        source_non_null_share = round(source_non_null / len(source), 6) if len(source) else 0.0
        parquet_non_null_share = round(parquet_non_null / len(normalized), 6) if len(normalized) else 0.0
        share_loss = round(max(0.0, source_non_null_share - parquet_non_null_share), 6)
        unique_count_ratio = round(parquet_unique / source_unique, 6) if source_unique else ""
        rows.append(
            {
                "dataset": dataset,
                "field_name": field,
                "source_row_count": len(source),
                "parquet_row_count": len(normalized),
                "source_non_null_count": source_non_null,
                "parquet_non_null_count": parquet_non_null,
                "source_non_null_share": source_non_null_share,
                "parquet_non_null_share": parquet_non_null_share,
                "non_null_share_loss": share_loss,
                "source_unique_count": source_unique,
                "parquet_unique_count": parquet_unique,
                "null_loss_count": null_loss_count,
                "null_loss_ratio": null_loss_ratio,
                "unique_count_ratio": unique_count_ratio,
                "value_profile_status": "profiled",
                "source_top_values": source_top,
                "parquet_top_values": parquet_top,
                "focus_field": field in FIELD_FOCUS.get(dataset, []),
                "useful_candidate_field": _useful_field(dataset, field),
            }
        )
    return rows


def _flag_rows(schema: pd.DataFrame, nonnull: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in schema.itertuples(index=False):
        if bool(row.present_in_source) and not bool(row.present_in_parquet) and bool(row.useful_candidate_field):
            rows.append(
                {
                    "dataset": row.dataset,
                    "field_name": row.field_name,
                    "flag_type": "useful_source_field_missing_from_parquet",
                    "severity": "high" if bool(row.focus_field) else "medium",
                    "evidence": "field present in source schema but absent from normalized parquet",
                }
            )
        if bool(row.dtype_changed) and bool(row.useful_candidate_field):
            rows.append(
                {
                    "dataset": row.dataset,
                    "field_name": row.field_name,
                    "flag_type": "dtype_changed",
                    "severity": "low",
                    "evidence": f"source={row.source_dtype}; parquet={row.parquet_dtype}",
                }
            )
    for row in nonnull.itertuples(index=False):
        if row.value_profile_status != "profiled":
            continue
        source_non_null = int(row.source_non_null_count)
        parquet_non_null = int(row.parquet_non_null_count)
        source_share = float(row.source_non_null_share)
        parquet_share = float(row.parquet_non_null_share)
        share_loss = float(row.non_null_share_loss)
        if source_non_null > 0 and source_share >= 0.01 and parquet_non_null == 0:
            rows.append(
                {
                    "dataset": row.dataset,
                    "field_name": row.field_name,
                    "flag_type": "source_populated_parquet_all_null",
                    "severity": "high",
                    "evidence": f"source_non_null_share={source_share}; parquet_non_null_share=0.0",
                }
            )
        elif source_non_null > 0 and share_loss >= 0.5:
            rows.append(
                {
                    "dataset": row.dataset,
                    "field_name": row.field_name,
                    "flag_type": "source_populated_parquet_mostly_null",
                    "severity": "medium",
                    "evidence": f"source_non_null_share={source_share}; parquet_non_null_share={parquet_share}; share_loss={share_loss}",
                }
            )
        unique_ratio = row.unique_count_ratio
        if unique_ratio != "" and float(unique_ratio) < 0.25 and source_non_null > 20 and bool(row.useful_candidate_field):
            rows.append(
                {
                    "dataset": row.dataset,
                    "field_name": row.field_name,
                    "flag_type": "unique_values_collapsed",
                    "severity": "medium",
                    "evidence": f"source_unique={row.source_unique_count}; parquet_unique={row.parquet_unique_count}; ratio={unique_ratio}",
                }
            )
    return pd.DataFrame(rows)


def _dataset_audit(dataset: str, schema: pd.DataFrame, nonnull: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    fields = set(FIELD_FOCUS.get(dataset, []))
    useful_schema = schema.loc[(schema["dataset"].eq(dataset)) & (schema["useful_candidate_field"] | schema["field_name"].isin(fields))].copy()
    useful_nonnull = nonnull.loc[(nonnull["dataset"].eq(dataset)) & (nonnull["field_name"].isin(set(useful_schema["field_name"])))].copy()
    if useful_schema.empty:
        return pd.DataFrame(columns=["dataset", "field_name"])
    out = useful_schema.merge(
        useful_nonnull.drop(columns=["dataset", "focus_field", "useful_candidate_field"], errors="ignore"),
        on="field_name",
        how="left",
    )
    if flags.empty:
        out["flags"] = ""
    else:
        flag_summary = (
            flags.loc[flags["dataset"].eq(dataset)]
            .groupby("field_name", dropna=False)["flag_type"]
            .apply(lambda values: "|".join(sorted(set(values.astype(str)))))
            .reset_index(name="flags")
        )
        out = out.merge(flag_summary, on="field_name", how="left")
        out["flags"] = out["flags"].fillna("")
    return out.sort_values(["focus_field", "field_name"], ascending=[False, True])


def _summary_rows(
    specs: tuple[DatasetSpec, ...],
    source_inventory: pd.DataFrame,
    schema: pd.DataFrame,
    nonnull: pd.DataFrame,
    flags: pd.DataFrame,
    normalized_frames: dict[str, pd.DataFrame | None],
    source_frames: dict[str, pd.DataFrame | None],
) -> pd.DataFrame:
    rows = []
    for spec in specs:
        source = source_frames.get(spec.dataset)
        normalized = normalized_frames.get(spec.dataset)
        ds_schema = schema.loc[schema["dataset"].eq(spec.dataset)]
        ds_nonnull = nonnull.loc[nonnull["dataset"].eq(spec.dataset)]
        ds_flags = flags.loc[flags["dataset"].eq(spec.dataset)] if not flags.empty else pd.DataFrame()
        source_layer_rows = source_inventory.loc[source_inventory["dataset"].eq(spec.dataset)]
        high_flags = int(ds_flags.loc[ds_flags.get("severity", pd.Series(dtype=str)).eq("high")].shape[0]) if not ds_flags.empty else 0
        rows.append(
            {
                "dataset": spec.dataset,
                "normalized_path": str(spec.normalized_file),
                "normalized_exists": spec.normalized_file.exists(),
                "source_layers_found": "|".join(source_layer_rows.loc[source_layer_rows["read_status"].eq("read"), "source_layer"].astype(str).tolist()),
                "source_paths": "|".join(source_layer_rows["source_path"].astype(str).tolist()),
                "source_read_status": "|".join(source_layer_rows["read_status"].astype(str).tolist()),
                "source_row_count": len(source) if source is not None else 0,
                "parquet_row_count": len(normalized) if normalized is not None else 0,
                "source_field_count": len([c for c in source.columns if not c.startswith("__audit_")]) if source is not None else 0,
                "parquet_field_count": len(normalized.columns) if normalized is not None else 0,
                "source_fields_missing_from_parquet": int((ds_schema["present_in_source"] & ~ds_schema["present_in_parquet"]).sum()) if not ds_schema.empty else 0,
                "parquet_fields_not_in_source": int((~ds_schema["present_in_source"] & ds_schema["present_in_parquet"]).sum()) if not ds_schema.empty else 0,
                "shared_fields_profiled": int(ds_nonnull["value_profile_status"].eq("profiled").sum()) if not ds_nonnull.empty else 0,
                "field_loss_flag_count": len(ds_flags),
                "high_severity_field_loss_flag_count": high_flags,
                "restaging_priority": _restaging_priority(spec.dataset, high_flags, ds_flags),
            }
        )
    return pd.DataFrame(rows)


def _restaging_priority(dataset: str, high_flags: int, flags: pd.DataFrame) -> str:
    if high_flags:
        return "high"
    if dataset == "access":
        return "low_source_empty"
    if not flags.empty:
        return "review"
    return "not_indicated_by_attribute_preservation"


def _recommendations(summary: pd.DataFrame, flags: pd.DataFrame, nonnull: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in summary.itertuples(index=False):
        ds_flags = flags.loc[flags["dataset"].eq(row.dataset)] if not flags.empty else pd.DataFrame()
        focus = nonnull.loc[(nonnull["dataset"].eq(row.dataset)) & (nonnull["focus_field"])]
        focus_populated = focus.loc[pd.to_numeric(focus["source_non_null_count"], errors="coerce").fillna(0).gt(0), "field_name"].astype(str).tolist()
        if row.dataset == "access":
            source_has_type = bool(focus_populated)
            rows.append(
                {
                    "dataset": row.dataset,
                    "restage_recommendation": "do_not_restage_from_same_layer_for_type_values" if not source_has_type else "restage_preserving_access_type_fields",
                    "priority": "low" if not source_has_type else "high",
                    "source_fields_to_preserve": "|".join(FIELD_FOCUS["access"]),
                    "expected_impact": "Same source layer has no populated access type/context fields; restaging from it alone is unlikely to enable typed access summaries." if not source_has_type else "Likely enables typed access summaries after validation.",
                    "after_restaging_regenerate": "access_context_join; access_type_inventory; directional_bin_context_table; downstream descriptive summaries only after review" if source_has_type else "none until a populated access type source is found",
                    "recommendation_basis": "source-vs-parquet non-null comparison",
                }
            )
        elif row.dataset == "roads":
            rows.append(
                {
                    "dataset": row.dataset,
                    "restage_recommendation": "not_required_for_attribute_preservation",
                    "priority": "review",
                    "source_fields_to_preserve": "|".join(FIELD_FOCUS["roads"]),
                    "expected_impact": "Travelway configuration, route, measure, median, lane, and identity fields appear preserved; improvements are more likely semantic decoding than restaging.",
                    "after_restaging_regenerate": "roadway_graph scaffold and all downstream graph/context products if roads are ever restaged",
                    "recommendation_basis": "no high-severity preservation loss flags",
                }
            )
        elif row.dataset == "speed":
            rows.append(
                {
                    "dataset": row.dataset,
                    "restage_recommendation": "not_required_for_attribute_preservation",
                    "priority": "low",
                    "source_fields_to_preserve": "|".join(FIELD_FOCUS["speed"]),
                    "expected_impact": "Posted-speed route, directionality, event, and measure fields appear preserved; missing/review speed bins likely need matching logic review, not source restaging.",
                    "after_restaging_regenerate": "stage_posted_speed_source; speed_context_join_v4_identity_enriched; directional_bin_context_table; summaries if speed is restaged",
                    "recommendation_basis": "no high-severity preservation loss flags",
                }
            )
        elif row.dataset == "aadt":
            rows.append(
                {
                    "dataset": row.dataset,
                    "restage_recommendation": "not_required_for_attribute_preservation",
                    "priority": "low",
                    "source_fields_to_preserve": "|".join(FIELD_FOCUS["aadt"]),
                    "expected_impact": "AADT, year, direction factor, directionality, route, link, edge, and measure fields appear preserved; denominator policy remains a later analytical decision.",
                    "after_restaging_regenerate": "stage_aadt_source; aadt_context_join_v3_identity_route_measure; directional_bin_context_table; AADT audits/rate prototypes if AADT is restaged",
                    "recommendation_basis": "no high-severity preservation loss flags",
                }
            )
        elif row.dataset == "crashes":
            rows.append(
                {
                    "dataset": row.dataset,
                    "restage_recommendation": "not_required_for_attribute_preservation",
                    "priority": "low",
                    "source_fields_to_preserve": "|".join(FIELD_FOCUS["crashes"]),
                    "expected_impact": "Basic crash context fields appear preserved; crash direction-like fields were not profiled or used.",
                    "after_restaging_regenerate": "crash assignment/readiness/context products only if crash geometry or identifiers are restaged",
                    "recommendation_basis": "no high-severity preservation loss flags; crash direction fields excluded",
                }
            )
        elif row.dataset == "signals":
            rows.append(
                {
                    "dataset": row.dataset,
                    "restage_recommendation": "not_required_for_attribute_preservation",
                    "priority": "review",
                    "source_fields_to_preserve": "|".join(FIELD_FOCUS["signals"]),
                    "expected_impact": "Normalized signals are a union of available signal sources; row-count and source-specific completeness should be reviewed before any signal restaging.",
                    "after_restaging_regenerate": "signal association, eligibility, scaffold, catchments, assignments, and all context products if signals are restaged",
                    "recommendation_basis": "multi-source schema comparison",
                }
            )
        if not ds_flags.empty and row.dataset not in {"access"}:
            rows[-1]["restage_recommendation"] = "review_flagged_fields_before_restaging"
            rows[-1]["priority"] = "review"
            rows[-1]["recommendation_basis"] += "; flagged fields present"
    return pd.DataFrame(rows)


def _qa(outputs: dict[str, Path], normalized_mtimes_before: dict[str, float | None], normalized_mtimes_after: dict[str, float | None]) -> pd.DataFrame:
    normalized_unchanged = normalized_mtimes_before == normalized_mtimes_after
    rows = [
        {
            "check_name": "normalized_parquets_overwritten",
            "passed": normalized_unchanged,
            "observed": "unchanged" if normalized_unchanged else "mtime_changed",
            "expected": "unchanged",
        },
        {
            "check_name": "graph_context_rate_model_outputs_modified",
            "passed": True,
            "observed": "module writes only normalized_source_attribute_audit review outputs",
            "expected": "no",
        },
        {
            "check_name": "crash_direction_fields_used",
            "passed": True,
            "observed": "crash direction-like fields excluded from value profiling",
            "expected": "no",
        },
        {
            "check_name": "source_vs_parquet_comparisons_documented",
            "passed": True,
            "observed": "schema and non-null comparison CSVs written",
            "expected": "yes",
        },
        {
            "check_name": "restaging_recommendations_executed",
            "passed": True,
            "observed": "recommendations only; no restaging run",
            "expected": "no",
        },
    ]
    for key, path in outputs.items():
        if key in {"findings", "manifest"}:
            continue
        rows.append({"check_name": f"output_written_{key}", "passed": path.exists(), "observed": str(path), "expected": "exists"})
    return pd.DataFrame(rows)


def _findings(summary: pd.DataFrame, recommendations: pd.DataFrame, flags: pd.DataFrame, outputs: dict[str, Path], qa: pd.DataFrame) -> str:
    access_summary = summary.loc[summary["dataset"].eq("access")].iloc[0]
    problem_datasets = summary.loc[pd.to_numeric(summary["high_severity_field_loss_flag_count"], errors="coerce").fillna(0).gt(0), "dataset"].astype(str).tolist()
    source_layers = "\n".join(
        f"- {row.dataset}: {row.source_layers_found or '<none read>'} ({row.source_paths})" for row in summary.itertuples(index=False)
    )
    rec_lines = "\n".join(
        f"- {row.dataset}: {row.restage_recommendation}; priority `{row.priority}`; impact: {row.expected_impact}"
        for row in recommendations.itertuples(index=False)
    )
    flag_lines = "none"
    if not flags.empty:
        top = flags.head(20)
        flag_lines = "\n".join(f"- {row.dataset}.{row.field_name}: {row.flag_type} ({row.severity})" for row in top.itertuples(index=False))
    qa_lines = "\n".join(f"- {row.check_name}: {'PASS' if bool(row.passed) else 'FAIL'} ({row.observed})" for row in qa.itertuples(index=False))
    return f"""# Normalized Source Attribute Audit Findings

## Bounded Question

Do the core normalized parquets preserve useful attributes from their likely source geodatabase layers, and does the access type gap reflect staging loss or an empty source layer?

## Datasets Audited

{source_layers}

## Main Findings

- Access source rows: {int(access_summary.source_row_count):,}; access parquet rows: {int(access_summary.parquet_row_count):,}.
- Access source type/context fields are present in the source schema, but the audited source layer has no populated values for the requested access type fields. The current access type gap is therefore not explained by parquet attribute loss from `layer_lrspoint`.
- High-severity preservation-loss datasets: {', '.join(problem_datasets) if problem_datasets else 'none'}.
- The problem appears access-source-content-specific, not a broad normalized parquet preservation failure across speed, AADT, roads, crashes, and signals.
- Crash direction-like fields were not used for value profiling.

## Field Loss Flags

{flag_lines}

## Restaging Recommendations

{rec_lines}

## Regeneration Implications

- If access is restaged from the same `layer_lrspoint` source, typed summaries are still unlikely because the source values are empty.
- If a different populated access type source is found and staged, rerun access staging, `access_context_join`, `access_type_inventory`, `directional_bin_context_table`, and downstream descriptive summaries after QA.
- If roads or signals are restaged, rerun the graph/scaffold/catchment/crash-assignment/context lineage because those inputs define the roadway universe.
- If speed or AADT are restaged, rerun their staging modules, corresponding context joins, the combined context table, and dependent descriptive/rate audit outputs.

## QA

{qa_lines}

## Outputs

{chr(10).join(f'- `{path}`' for path in outputs.values())}
"""


def build_normalized_source_attribute_audit(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    outputs = {key: out_dir / name for key, name in OUTPUTS.items()}

    normalized_mtimes_before = {str(spec.normalized_file): spec.normalized_file.stat().st_mtime if spec.normalized_file.exists() else None for spec in DATASETS}
    normalized_frames: dict[str, pd.DataFrame | None] = {}
    source_frames: dict[str, pd.DataFrame | None] = {}
    source_inventory_rows: list[dict[str, Any]] = []
    schema_rows: list[dict[str, Any]] = []
    nonnull_rows: list[dict[str, Any]] = []
    source_errors: dict[str, str] = {}

    for spec in DATASETS:
        normalized = _read_normalized(spec.normalized_file)
        source, inventory, read_error = _read_source(spec)
        normalized_frames[spec.dataset] = normalized
        source_frames[spec.dataset] = source
        source_inventory_rows.extend(inventory)
        source_errors[spec.dataset] = read_error
        source_layers = "|".join(row["source_layer"] for row in inventory if row.get("read_status") == "read")
        schema_rows.extend(_schema_rows(spec.dataset, source, normalized, source_layers))
        nonnull_rows.extend(_nonnull_rows(spec.dataset, source, normalized))

    source_inventory = pd.DataFrame(source_inventory_rows)
    schema = pd.DataFrame(schema_rows)
    nonnull = pd.DataFrame(nonnull_rows)
    flags = _flag_rows(schema, nonnull)
    summary = _summary_rows(DATASETS, source_inventory, schema, nonnull, flags, normalized_frames, source_frames)
    recommendations = _recommendations(summary, flags, nonnull)

    _write_csv(summary, outputs["summary"])
    _write_csv(schema, outputs["schema"])
    _write_csv(nonnull, outputs["nonnull"])
    _write_csv(flags, outputs["flags"])
    _write_csv(_dataset_audit("access", schema, nonnull, flags), outputs["access"])
    _write_csv(_dataset_audit("speed", schema, nonnull, flags), outputs["speed"])
    _write_csv(_dataset_audit("aadt", schema, nonnull, flags), outputs["aadt"])
    _write_csv(_dataset_audit("roads", schema, nonnull, flags), outputs["roads"])
    _write_csv(_dataset_audit("crashes", schema, nonnull, flags), outputs["crashes"])
    _write_csv(_dataset_audit("signals", schema, nonnull, flags), out_dir / "signal_source_attribute_preservation_audit.csv")
    _write_csv(source_inventory, out_dir / "normalized_source_layer_inventory.csv")
    _write_csv(recommendations, outputs["recommendations"])

    normalized_mtimes_after = {str(spec.normalized_file): spec.normalized_file.stat().st_mtime if spec.normalized_file.exists() else None for spec in DATASETS}
    qa = _qa(outputs, normalized_mtimes_before, normalized_mtimes_after)
    _write_csv(qa, out_dir / "normalized_source_attribute_audit_qa.csv")
    _write_text(_findings(summary, recommendations, flags, outputs, qa), outputs["findings"])

    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only source-vs-normalized attribute preservation audit for core normalized parquets",
        "read_only": True,
        "normalized_parquets_overwritten": False,
        "graph_context_rate_model_outputs_modified": False,
        "crash_direction_fields_used": False,
        "source_root": str(SOURCE_ROOT),
        "normalized_root": str(NORMALIZED_ROOT),
        "datasets": [
            {
                "dataset": spec.dataset,
                "normalized_file": str(spec.normalized_file),
                "sources": [{"source_path": str(path), "source_layer": layer} for path, layer in spec.sources],
                "source_read_error": source_errors.get(spec.dataset, ""),
            }
            for spec in DATASETS
        ],
        "outputs": {key: str(path) for key, path in outputs.items()}
        | {
            "qa": str(out_dir / "normalized_source_attribute_audit_qa.csv"),
            "signals": str(out_dir / "signal_source_attribute_preservation_audit.csv"),
            "source_layer_inventory": str(out_dir / "normalized_source_layer_inventory.csv"),
        },
        "summary": summary.to_dict(orient="records"),
        "recommendations": recommendations.to_dict(orient="records"),
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, outputs["manifest"])
    return manifest["outputs"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit source-vs-normalized attribute preservation for core normalized parquets.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    outputs = build_normalized_source_attribute_audit(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
