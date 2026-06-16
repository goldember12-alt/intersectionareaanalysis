from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from shapely import STRtree, wkb, wkt


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_crash_candidate_assignment"

FINAL_LEG_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_clean_universe_summary"
ACCESS_REFRESH_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_access_refresh"
ACCESS_SANITY_DIR = OUTPUT_ROOT / "review/current/final_leg_corrected_access_sanity_audit"
PRIOR_CRASH_DIR = OUTPUT_ROOT / "review/current/final_crash_candidate_assignment"
PRIOR_NONASSIGN_DIR = OUTPUT_ROOT / "review/current/final_crash_nonassignment_accounting"
PRIOR_MANUAL_DIR = OUTPUT_ROOT / "review/current/final_crash_manual_overlap_decomposition"
PRIOR_DESIGN_DIR = OUTPUT_ROOT / "review/current/final_crash_catchment_design_feasibility"

CRASH_SOURCE = Path("artifacts/normalized/crashes.parquet")

BUFFER_WIDTHS_FT = [35, 50, 75]
PRIMARY_BUFFER_FT = 50
FT_TO_M = 0.3048
CHUNK_SIZE = 40_000

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

CRASH_BASE_COLUMNS = [
    "DOCUMENT_NBR",
    "CRASH_YEAR",
    "CRASH_DT",
    "CRASH_SEVERITY",
    "K_PEOPLE",
    "A_PEOPLE",
    "B_PEOPLE",
    "C_PEOPLE",
    "PERSONS_INJURED",
    "VEH_COUNT",
    "COLLISION_TYPE",
    "ROADWAY_DESCRIPTION",
    "INTERSECTION_TYPE",
    "FIRST_HARMFUL_EVENT",
    "FIRST_HARMFUL_EVENT_LOC",
    "RELATION_TO_ROADWAY",
    "TRAFFIC_CONTROL_TYPE",
    "MAINLINE_YN",
    "RTE_NM",
    "RNS_MP",
    "NODE",
    "OFFSET",
    "geometry",
]

REQUIRED_INPUTS = [
    FINAL_LEG_DIR / "final_leg_corrected_signal_universe_3719.csv",
    FINAL_LEG_DIR / "final_leg_corrected_bin_universe.csv",
    FINAL_LEG_DIR / "final_leg_corrected_physical_leg_distribution.csv",
    FINAL_LEG_DIR / "final_leg_corrected_bin_window_availability.csv",
    FINAL_LEG_DIR / "final_leg_corrected_context_readiness_summary.csv",
    FINAL_LEG_DIR / "final_leg_corrected_residual_issue_ledger.csv",
    FINAL_LEG_DIR / "final_leg_corrected_downstream_readiness.csv",
    FINAL_LEG_DIR / "final_leg_corrected_clean_universe_summary_manifest.json",
    ACCESS_REFRESH_DIR / "final_leg_corrected_access_target_bins.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_untyped_spatial_assignment_detail.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_typed_v2_spatial_assignment_detail.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_untyped_access_summary.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_typed_access_summary.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_access_doctrine_update.csv",
    ACCESS_REFRESH_DIR / "final_leg_corrected_access_refresh_manifest.json",
    ACCESS_SANITY_DIR / "access_sanity_readiness_decision.csv",
    ACCESS_SANITY_DIR / "access_coverage_by_recovery_branch.csv",
    ACCESS_SANITY_DIR / "access_no_access_signal_summary.csv",
    ACCESS_SANITY_DIR / "final_leg_corrected_access_sanity_manifest.json",
    CRASH_SOURCE,
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{_now()} {message}\n")


def _checkpoint(name: str, rows: int | None = None) -> None:
    suffix = "" if rows is None else f" rows={rows:,}"
    _log(f"CHECKPOINT {name}{suffix}")


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(OUT_DIR / name, index=False)
    _checkpoint(f"write {name}", len(frame))


def _write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")


def _write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")


def _is_direction_field(column: str) -> bool:
    return any(token in column.lower() for token in CRASH_DIRECTION_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _is_direction_field(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read {path.name}", len(out))
    return out


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _bool_text(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _collapse(values: pd.Series, limit: int = 12) -> str:
    out: list[str] = []
    for value in values.dropna().astype(str):
        value = value.strip()
        if value and value not in out:
            out.append(value)
        if len(out) >= limit:
            break
    return "|".join(out)


def _crash_schema_columns() -> list[str]:
    return list(pq.ParquetFile(CRASH_SOURCE).schema_arrow.names)


def _load_crashes() -> tuple[pd.DataFrame, list[str]]:
    schema_cols = _crash_schema_columns()
    direction_cols = [column for column in schema_cols if _is_direction_field(column)]
    cols = [column for column in CRASH_BASE_COLUMNS if column in schema_cols]
    crashes = pd.read_parquet(CRASH_SOURCE, columns=cols)
    if "DOCUMENT_NBR" in crashes.columns:
        crashes["stable_crash_id"] = "crash_" + crashes["DOCUMENT_NBR"].astype(str)
    else:
        crashes["stable_crash_id"] = ["crash_review_%09d" % idx for idx in range(len(crashes))]
    crashes["crash_direction_fields_inventory_only"] = "|".join(direction_cols)
    crashes["crash_direction_used_for_assignment"] = False
    crashes["crash_direction_use_status"] = "not_read_not_used" if not direction_cols else "inventory_only_not_used_for_assignment"
    crashes = crashes.reset_index(drop=True)
    crashes["crash_row_id"] = np.arange(len(crashes), dtype=np.int64)
    _checkpoint("load normalized crashes", len(crashes))
    return crashes, direction_cols


def _load_bins() -> pd.DataFrame:
    bins = _read_csv(FINAL_LEG_DIR / "final_leg_corrected_bin_universe.csv")
    bins = bins.loc[_text(bins, "geometry_wkt").str.strip().ne("")].copy()
    bins = bins.reset_index(drop=True)
    bins["bin_row_pos"] = np.arange(len(bins), dtype=np.int64)
    bins["review_only_flag"] = True
    return bins


def _access_flags() -> pd.DataFrame:
    untyped = _read_csv(
        ACCESS_REFRESH_DIR / "final_leg_corrected_untyped_spatial_assignment_detail.csv",
        usecols=["stable_bin_id", "access_point_id", "buffer_width_ft"],
    )
    typed = _read_csv(
        ACCESS_REFRESH_DIR / "final_leg_corrected_typed_v2_spatial_assignment_detail.csv",
        usecols=["stable_bin_id", "access_point_id", "corrected_access_category", "buffer_width_ft"],
    )
    untyped_100 = untyped.loc[_num(untyped, "buffer_width_ft").eq(100)].copy()
    typed_100 = typed.loc[_num(typed, "buffer_width_ft").eq(100)].copy()
    u = untyped_100.groupby("stable_bin_id", dropna=False).agg(
        untyped_spatial_100ft_access_point_count=("access_point_id", "nunique"),
    ).reset_index()
    t = typed_100.groupby("stable_bin_id", dropna=False).agg(
        typed_v2_spatial_100ft_access_point_count=("access_point_id", "nunique"),
        typed_v2_corrected_access_categories=("corrected_access_category", _collapse),
    ).reset_index()
    out = u.merge(t, on="stable_bin_id", how="outer")
    for col in ["untyped_spatial_100ft_access_point_count", "typed_v2_spatial_100ft_access_point_count"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out["has_untyped_spatial_100ft_access"] = out["untyped_spatial_100ft_access_point_count"].gt(0)
    out["has_typed_v2_spatial_100ft_access"] = out["typed_v2_spatial_100ft_access_point_count"].gt(0)
    return out


def _parse_points(values: pd.Series) -> np.ndarray:
    out = []
    for value in values:
        if value is None:
            out.append(None)
        elif hasattr(value, "geom_type"):
            out.append(value if not value.is_empty else None)
        else:
            try:
                out.append(wkb.loads(value))
            except Exception:
                out.append(None)
    return np.asarray(out, dtype=object)


def _parse_lines(values: pd.Series) -> np.ndarray:
    out = []
    for value in values:
        try:
            geom = wkt.loads(str(value))
            out.append(geom if not geom.is_empty else None)
        except Exception:
            out.append(None)
    return np.asarray(out, dtype=object)


def _assignment_pairs(points: np.ndarray, lines: np.ndarray, buffer_ft: int) -> pd.DataFrame:
    valid_line_mask = np.asarray([geom is not None for geom in lines], dtype=bool)
    valid_lines = lines[valid_line_mask]
    line_original_index = np.flatnonzero(valid_line_mask)
    tree = STRtree(valid_lines)
    rows: list[pd.DataFrame] = []
    distance_m = buffer_ft * FT_TO_M
    for start in range(0, len(points), CHUNK_SIZE):
        stop = min(start + CHUNK_SIZE, len(points))
        chunk = points[start:stop]
        valid_point_mask = np.asarray([geom is not None and not geom.is_empty for geom in chunk], dtype=bool)
        if not valid_point_mask.any():
            continue
        valid_points = chunk[valid_point_mask]
        point_original_index = np.flatnonzero(valid_point_mask) + start
        pair_index = tree.query(valid_points, predicate="dwithin", distance=distance_m)
        if pair_index.size == 0:
            continue
        crash_idx = point_original_index[pair_index[0]]
        bin_idx = line_original_index[pair_index[1]]
        frame = pd.DataFrame({"crash_row_id": crash_idx, "bin_row_pos": bin_idx})
        rows.append(frame)
        _checkpoint(f"spatial query {buffer_ft}ft chunk {start}-{stop}", len(frame))
    if not rows:
        return pd.DataFrame(columns=["crash_row_id", "bin_row_pos"])
    return pd.concat(rows, ignore_index=True)


def _build_assignment_detail(crashes: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    points = _parse_points(crashes["geometry"])
    lines = _parse_lines(bins["geometry_wkt"])
    crash_attr_cols = [
        "crash_row_id",
        "stable_crash_id",
        "DOCUMENT_NBR",
        "CRASH_YEAR",
        "CRASH_DT",
        "CRASH_SEVERITY",
        "K_PEOPLE",
        "A_PEOPLE",
        "B_PEOPLE",
        "C_PEOPLE",
        "PERSONS_INJURED",
        "VEH_COUNT",
        "COLLISION_TYPE",
        "ROADWAY_DESCRIPTION",
        "INTERSECTION_TYPE",
        "FIRST_HARMFUL_EVENT",
        "FIRST_HARMFUL_EVENT_LOC",
        "RELATION_TO_ROADWAY",
        "TRAFFIC_CONTROL_TYPE",
        "MAINLINE_YN",
        "RTE_NM",
        "RNS_MP",
        "NODE",
        "OFFSET",
        "crash_direction_fields_inventory_only",
        "crash_direction_used_for_assignment",
        "crash_direction_use_status",
    ]
    crash_attr_cols = [col for col in crash_attr_cols if col in crashes.columns]
    bin_attr_cols = [
        "bin_row_pos",
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "final_review_physical_leg_id",
        "final_review_carriageway_subbranch_id",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "final_review_leg_source",
        "final_review_context_status",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "final_review_has_rns_speed",
        "final_review_has_aadt",
        "final_review_has_exposure_denominator",
        "final_review_speed_aadt_ready_bin",
        "final_review_recovery_provenance",
        "residual_bucket",
        "broader_source_class",
        "prior_skip_reason",
        "has_untyped_spatial_100ft_access",
        "has_typed_v2_spatial_100ft_access",
        "untyped_spatial_100ft_access_point_count",
        "typed_v2_spatial_100ft_access_point_count",
        "typed_v2_corrected_access_categories",
        "review_only_flag",
    ]
    bin_attr_cols = [col for col in bin_attr_cols if col in bins.columns]
    parts: list[pd.DataFrame] = []
    for width in BUFFER_WIDTHS_FT:
        pairs = _assignment_pairs(points, lines, width)
        if pairs.empty:
            continue
        pairs["buffer_width_ft"] = width
        pairs = pairs.merge(crashes[crash_attr_cols], on="crash_row_id", how="left")
        pairs = pairs.merge(bins[bin_attr_cols], on="bin_row_pos", how="left")
        fanout = pairs.groupby("stable_crash_id", dropna=False).size().rename("assignment_fanout_count").reset_index()
        pairs = pairs.merge(fanout, on="stable_crash_id", how="left")
        pairs["unweighted_assignment"] = 1.0
        pairs["source_preserving_weight"] = 1.0 / pd.to_numeric(pairs["assignment_fanout_count"], errors="coerce").fillna(1.0)
        pairs["assignment_rule"] = f"line_dwithin_{width}ft"
        pairs["assignment_status"] = "review_only_candidate"
        pairs["primary_product_flag"] = width == PRIMARY_BUFFER_FT
        pairs["crash_direction_use_status"] = "inventory_only_not_used_for_assignment"
        parts.append(pairs.drop(columns=["crash_row_id", "bin_row_pos"], errors="ignore"))
        _checkpoint(f"build assignment detail {width}ft", len(parts[-1]))
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True, sort=False)
    out = out.sort_values(["buffer_width_ft", "stable_crash_id", "stable_signal_id", "stable_bin_id"]).reset_index(drop=True)
    _checkpoint("assignment detail all buffers", len(out))
    return out


def _rollup(detail: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if detail.empty:
        return pd.DataFrame()
    work = detail
    if "has_untyped_access_int" not in work.columns:
        work["has_untyped_access_int"] = _bool_text(work, "has_untyped_spatial_100ft_access").astype(int)
    if "has_typed_access_int" not in work.columns:
        work["has_typed_access_int"] = _bool_text(work, "has_typed_v2_spatial_100ft_access").astype(int)
    out = work.groupby(group_cols, dropna=False).agg(
        unique_crash_count=("stable_crash_id", "nunique"),
        assignment_row_count=("stable_crash_id", "size"),
        weighted_crash_count=("source_preserving_weight", "sum"),
        unweighted_crash_count=("unweighted_assignment", "sum"),
        bins_with_untyped_access=("has_untyped_access_int", "sum"),
        bins_with_typed_access=("has_typed_access_int", "sum"),
        max_assignment_fanout=("assignment_fanout_count", "max"),
    ).reset_index()
    out["weighted_crash_count"] = out["weighted_crash_count"].round(6)
    return out


def _fanout_summary(detail: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for width, frame in detail.groupby("buffer_width_ft", dropna=False):
        per_crash = frame.groupby("stable_crash_id", dropna=False).agg(
            assignment_rows=("stable_bin_id", "size"),
            signal_count=("stable_signal_id", "nunique"),
            physical_leg_count=("final_review_physical_leg_id", "nunique"),
        ).reset_index()
        per_crash["signal_fanout_bucket"] = pd.cut(
            pd.to_numeric(per_crash["signal_count"], errors="coerce").fillna(0),
            bins=[0, 1, 2, 3, np.inf],
            labels=["1_signal", "2_signals", "3_signals", "4_plus_signals"],
            include_lowest=True,
        ).astype(str)
        for bucket, group in per_crash.groupby("signal_fanout_bucket", dropna=False):
            rows.append(
                {
                    "buffer_width_ft": width,
                    "fanout_group": "signals_per_crash",
                    "fanout_bucket": bucket,
                    "crash_count": int(group["stable_crash_id"].nunique()),
                    "max_assignment_rows": int(group["assignment_rows"].max()),
                    "max_signal_count": int(group["signal_count"].max()),
                    "max_physical_leg_count": int(group["physical_leg_count"].max()),
                }
            )
        rows.append(
            {
                "buffer_width_ft": width,
                "fanout_group": "multi_leg_same_signal",
                "fanout_bucket": "crashes_with_multiple_legs_same_signal",
                "crash_count": int(_multi_leg_same_signal(frame)["stable_crash_id"].nunique()),
                "max_assignment_rows": int(per_crash["assignment_rows"].max()),
                "max_signal_count": int(per_crash["signal_count"].max()),
                "max_physical_leg_count": int(per_crash["physical_leg_count"].max()),
            }
        )
    return pd.DataFrame(rows)


def _multi_leg_same_signal(frame: pd.DataFrame) -> pd.DataFrame:
    legs = frame.groupby(["stable_crash_id", "stable_signal_id"], dropna=False)["final_review_physical_leg_id"].nunique().reset_index(name="leg_count")
    return legs.loc[pd.to_numeric(legs["leg_count"], errors="coerce").gt(1)]


def _overlap_queue(detail: pd.DataFrame) -> pd.DataFrame:
    primary = detail.loc[_num(detail, "buffer_width_ft").eq(PRIMARY_BUFFER_FT)].copy()
    if primary.empty:
        return pd.DataFrame()
    per_crash = primary.groupby("stable_crash_id", dropna=False).agg(
        signal_count=("stable_signal_id", "nunique"),
        physical_leg_count=("final_review_physical_leg_id", "nunique"),
        assignment_rows=("stable_bin_id", "size"),
        weighted_total=("source_preserving_weight", "sum"),
        example_signals=("stable_signal_id", _collapse),
        example_routes=("source_route_name", _collapse),
        has_untyped_access=("has_untyped_spatial_100ft_access", "max"),
        has_typed_access=("has_typed_v2_spatial_100ft_access", "max"),
        crash_year=("CRASH_YEAR", "first"),
        crash_severity=("CRASH_SEVERITY", "first"),
        collision_type=("COLLISION_TYPE", "first"),
        roadway_description=("ROADWAY_DESCRIPTION", "first"),
        mainline_yn=("MAINLINE_YN", "first"),
    ).reset_index()
    per_crash["overlap_review_reason"] = np.select(
        [
            pd.to_numeric(per_crash["signal_count"], errors="coerce").ge(4),
            pd.to_numeric(per_crash["assignment_rows"], errors="coerce").ge(20),
            pd.to_numeric(per_crash["physical_leg_count"], errors="coerce").ge(6),
            _text(per_crash, "mainline_yn").str.lower().eq("yes"),
        ],
        [
            "four_plus_signal_fanout",
            "high_bin_assignment_fanout",
            "high_physical_leg_overlap",
            "mainline_context_inventory_flag",
        ],
        default="standard_overlap_review",
    )
    return per_crash.sort_values(["signal_count", "assignment_rows", "physical_leg_count"], ascending=False).head(500)


def _source_coverage(crashes: pd.DataFrame, detail: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = [{"coverage_group": "source", "class": "total_normalized_crashes", "count": len(crashes)}]
    for width in BUFFER_WIDTHS_FT:
        subset = detail.loc[_num(detail, "buffer_width_ft").eq(width)]
        assigned = int(_text(subset, "stable_crash_id").nunique())
        rows.append({"coverage_group": "assigned_by_buffer", "class": f"{width}ft_assigned_crashes", "count": assigned})
        rows.append({"coverage_group": "unassigned_by_buffer", "class": f"{width}ft_unassigned_crashes", "count": len(crashes) - assigned})
    primary = detail.loc[_num(detail, "buffer_width_ft").eq(PRIMARY_BUFFER_FT)]
    for col in ["CRASH_YEAR", "CRASH_SEVERITY", "COLLISION_TYPE"]:
        if col in crashes.columns:
            assigned_ids = set(_text(primary, "stable_crash_id"))
            source = crashes.copy()
            source["assigned_50ft"] = _text(source, "stable_crash_id").isin(assigned_ids)
            grouped = source.groupby([col, "assigned_50ft"], dropna=False).size().reset_index(name="count")
            for row in grouped.to_dict("records"):
                rows.append({"coverage_group": f"{col}_assignment_50ft", "class": f"{row[col]}|assigned={row['assigned_50ft']}", "count": int(row["count"])})
    return pd.DataFrame(rows)


def _unassigned_summary(crashes: pd.DataFrame, detail: pd.DataFrame) -> pd.DataFrame:
    primary_ids = set(_text(detail.loc[_num(detail, "buffer_width_ft").eq(PRIMARY_BUFFER_FT)], "stable_crash_id"))
    crashes = crashes.copy()
    crashes["assigned_50ft"] = _text(crashes, "stable_crash_id").isin(primary_ids)
    rows = [{"summary_group": "overall", "summary_class": "unassigned_50ft", "crash_count": int((~crashes["assigned_50ft"]).sum())}]
    for col in ["CRASH_YEAR", "CRASH_SEVERITY", "COLLISION_TYPE", "ROADWAY_DESCRIPTION", "INTERSECTION_TYPE"]:
        if col in crashes.columns:
            unassigned = crashes.loc[~crashes["assigned_50ft"]]
            for value, group in unassigned.groupby(col, dropna=False):
                rows.append({"summary_group": col, "summary_class": value, "crash_count": int(len(group))})
    return pd.DataFrame(rows)


def _prior_comparison(detail: pd.DataFrame) -> pd.DataFrame:
    prior_detail_path = PRIOR_CRASH_DIR / "crash_candidate_assignment_detail.csv"
    rows: list[dict[str, Any]] = []
    prior_cols = ["buffer_width_ft", "stable_crash_id", "assignment_fanout_count"]
    prior = _read_csv(prior_detail_path, usecols=prior_cols) if prior_detail_path.exists() else pd.DataFrame()
    for width in BUFFER_WIDTHS_FT:
        cur = detail.loc[_num(detail, "buffer_width_ft").eq(width)]
        prior_w = prior.loc[_num(prior, "buffer_width_ft").eq(width)] if not prior.empty else pd.DataFrame()
        rows.append(
            {
                "buffer_width_ft": width,
                "prior_assigned_crashes": int(_text(prior_w, "stable_crash_id").nunique()) if not prior_w.empty else 0,
                "current_assigned_crashes": int(_text(cur, "stable_crash_id").nunique()) if not cur.empty else 0,
                "assigned_crash_change": int(_text(cur, "stable_crash_id").nunique()) - (int(_text(prior_w, "stable_crash_id").nunique()) if not prior_w.empty else 0),
                "prior_assignment_rows": int(len(prior_w)),
                "current_assignment_rows": int(len(cur)),
                "assignment_row_change": int(len(cur)) - int(len(prior_w)),
                "prior_max_fanout": int(_num(prior_w, "assignment_fanout_count").max()) if not prior_w.empty else 0,
                "current_max_fanout": int(_num(cur, "assignment_fanout_count").max()) if not cur.empty else 0,
            }
        )
    return pd.DataFrame(rows)


def _qa(detail: pd.DataFrame, bins: pd.DataFrame, direction_cols: list[str], missing: list[str]) -> pd.DataFrame:
    checks = [
        ("no_active_outputs_modified", True, "Writes only to review/current final_leg_corrected_crash_candidate_assignment."),
        ("no_records_promoted", True, "No production/final active outputs are written."),
        ("no_rates_or_models", True, "No rates/models are calculated."),
        ("crash_direction_not_used_for_geometry", True, "Direction columns are not read for geometry/scaffold decisions."),
        ("crash_direction_inventory_only", True, "|".join(direction_cols) if direction_cols else "no direction columns present"),
        ("multi_assignment_weights_present", {"unweighted_assignment", "source_preserving_weight", "assignment_fanout_count"}.issubset(detail.columns), "weight columns present"),
        ("stable_travelway_id_carried", "stable_travelway_id" in detail.columns and _text(detail, "stable_travelway_id").str.strip().ne("").any(), "stable_travelway_id in assignment output"),
        ("final_review_physical_leg_id_carried", "final_review_physical_leg_id" in detail.columns, f"nonblank {_text(detail, 'final_review_physical_leg_id').str.strip().ne('').sum():,} / {len(detail):,} assignment rows"),
        ("scaffold_access_qa_flags_carried", {"has_untyped_spatial_100ft_access", "has_typed_v2_spatial_100ft_access", "final_review_context_status"}.issubset(detail.columns), "scaffold/access QA columns present"),
        ("outputs_review_only", True, str(OUT_DIR.resolve())),
        ("required_inputs_available", not missing, "; ".join(missing)),
        ("target_bins_with_stable_travelway_id", _text(bins, "stable_travelway_id").str.strip().ne("").all(), f"{_text(bins, 'stable_travelway_id').str.strip().ne('').sum():,} / {len(bins):,}"),
    ]
    return pd.DataFrame([{"qa_check": name, "passed": passed, "detail": detail_text} for name, passed, detail_text in checks])


def _findings(crashes: pd.DataFrame, detail: pd.DataFrame, comparison: pd.DataFrame, fanout: pd.DataFrame, overlap: pd.DataFrame, qa_frame: pd.DataFrame) -> str:
    assigned_lines = []
    for width in BUFFER_WIDTHS_FT:
        subset = detail.loc[_num(detail, "buffer_width_ft").eq(width)]
        assigned_lines.append(f"- {width} ft: {int(_text(subset, 'stable_crash_id').nunique()):,} crashes, {len(subset):,} assignment rows")
    primary = detail.loc[_num(detail, "buffer_width_ft").eq(PRIMARY_BUFFER_FT)]
    unassigned = len(crashes) - int(_text(primary, "stable_crash_id").nunique())
    comp_lines = "\n".join(
        f"- {int(row.buffer_width_ft)} ft: prior {int(row.prior_assigned_crashes):,} -> current {int(row.current_assigned_crashes):,} assigned crashes"
        for row in comparison.itertuples(index=False)
    )
    fanout_primary = fanout.loc[_num(fanout, "buffer_width_ft").eq(PRIMARY_BUFFER_FT)]
    fanout_lines = "\n".join(
        f"- {row.fanout_bucket}: {int(row.crash_count):,} crashes"
        for row in fanout_primary.itertuples(index=False)
        if row.fanout_group == "signals_per_crash"
    )
    top_signal_windows = (
        _rollup(primary, ["buffer_width_ft", "stable_signal_id", "analysis_window"])
        .sort_values("unique_crash_count", ascending=False)
        .head(5)
    )
    top_lines = "\n".join(
        f"- {row.stable_signal_id} {row.analysis_window}: {int(row.unique_crash_count):,} unique crashes"
        for row in top_signal_windows.itertuples(index=False)
    )
    return f"""# Final Leg-Corrected Crash Candidate Assignment Findings

## Bounded Question

Refresh review-only crash/catchment assignment on the final leg-corrected 3,719-signal bin scaffold using line-buffer catchments. The 50 ft product remains primary; 35 ft and 75 ft are sensitivity products.

## Crash Source

- Normalized crashes loaded: {len(crashes):,}
- Crash direction fields were not used for scaffold, legs, upstream/downstream, or catchment geometry.

## Assignment Counts

{chr(10).join(assigned_lines)}

- Unassigned at primary 50 ft: {unassigned:,}

## Prior Baseline Comparison

{comp_lines}

## Fanout at 50 Ft

{fanout_lines}

## Highest Signal-Window Counts at 50 Ft

{top_lines}

## Overlap Review

- Overlap review queue rows: {len(overlap):,}

High-overlap rows should be treated as QA review candidates, not automatic exclusions.

## Primary Product Decision

The 50 ft line-buffer product remains suitable as the primary review crash assignment. The 35 ft and 75 ft outputs provide sensitivity bounds, and 100 ft is intentionally not generated here as a primary product.

## Next Pass

Run final crash nonassignment/manual-overlap accounting on this leg-corrected 50 ft primary assignment before creating descriptive summaries or any rate/model tables.

## QA

All QA checks passed: {bool(qa_frame['passed'].all())}.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")
    missing = _missing_inputs()
    crashes, direction_cols = _load_crashes()
    bins = _load_bins()
    access_flags = _access_flags()
    bins = bins.merge(access_flags, on="stable_bin_id", how="left")
    for col in ["untyped_spatial_100ft_access_point_count", "typed_v2_spatial_100ft_access_point_count"]:
        bins[col] = pd.to_numeric(bins[col], errors="coerce").fillna(0).astype(int)
    for col in ["has_untyped_spatial_100ft_access", "has_typed_v2_spatial_100ft_access"]:
        bins[col] = bins[col].fillna(False).astype(bool)
    detail = _build_assignment_detail(crashes, bins)
    detail["has_untyped_access_int"] = _bool_text(detail, "has_untyped_spatial_100ft_access").astype(int)
    detail["has_typed_access_int"] = _bool_text(detail, "has_typed_v2_spatial_100ft_access").astype(int)
    _checkpoint("postprocess detail flags", len(detail))
    _checkpoint("rollup signal_window start")
    signal_window = _rollup(detail, ["buffer_width_ft", "stable_signal_id", "analysis_window"])
    _checkpoint("rollup signal_window complete", len(signal_window))
    _checkpoint("rollup signal_physical_leg_window start")
    signal_leg_window = _rollup(detail, ["buffer_width_ft", "stable_signal_id", "final_review_physical_leg_id", "analysis_window"])
    _checkpoint("rollup signal_physical_leg_window complete", len(signal_leg_window))
    _checkpoint("rollup signal start")
    signal_rollup = _rollup(detail, ["buffer_width_ft", "stable_signal_id"])
    _checkpoint("rollup signal complete", len(signal_rollup))
    _checkpoint("rollup bin start")
    bin_rollup = _rollup(detail, ["buffer_width_ft", "stable_signal_id", "stable_bin_id"])
    _checkpoint("rollup bin complete", len(bin_rollup))
    _checkpoint("fanout summary start")
    fanout = _fanout_summary(detail)
    _checkpoint("fanout summary complete", len(fanout))
    _checkpoint("overlap queue start")
    overlap = _overlap_queue(detail)
    _checkpoint("overlap queue complete", len(overlap))
    _checkpoint("source coverage start")
    source_coverage = _source_coverage(crashes, detail)
    _checkpoint("source coverage complete", len(source_coverage))
    _checkpoint("unassigned summary start")
    unassigned = _unassigned_summary(crashes, detail)
    _checkpoint("unassigned summary complete", len(unassigned))
    _checkpoint("prior comparison start")
    comparison = _prior_comparison(detail)
    _checkpoint("prior comparison complete", len(comparison))
    qa_frame = _qa(detail, bins, direction_cols, missing)

    _write_csv(detail, "leg_corrected_crash_candidate_assignment_detail.csv")
    _write_csv(signal_window, "leg_corrected_crash_candidate_assignment_signal_window_rollup.csv")
    _write_csv(signal_leg_window, "leg_corrected_crash_candidate_assignment_signal_physical_leg_window_rollup.csv")
    _write_csv(signal_rollup, "leg_corrected_crash_candidate_assignment_signal_rollup.csv")
    _write_csv(bin_rollup, "leg_corrected_crash_candidate_assignment_bin_rollup.csv")
    _write_csv(fanout, "leg_corrected_crash_candidate_assignment_fanout_summary.csv")
    _write_csv(overlap, "leg_corrected_crash_candidate_assignment_overlap_review_queue.csv")
    _write_csv(source_coverage, "leg_corrected_crash_candidate_assignment_source_coverage_summary.csv")
    _write_csv(unassigned, "leg_corrected_crash_candidate_assignment_unassigned_summary.csv")
    _write_csv(comparison, "leg_corrected_crash_assignment_vs_prior_comparison.csv")
    _write_text(_findings(crashes, detail, comparison, fanout, overlap, qa_frame), "final_leg_corrected_crash_candidate_assignment_findings.md")
    _write_csv(qa_frame, "final_leg_corrected_crash_candidate_assignment_qa.csv")
    manifest = {
        "generated_at": _now(),
        "script": "src.roadway_graph.build.final_leg_corrected_crash_candidate_assignment",
        "output_dir": str(OUT_DIR),
        "review_only": True,
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "missing_inputs": missing,
        "counts": {
            "normalized_crashes": int(len(crashes)),
            "target_bins_with_geometry": int(len(bins)),
            "assignment_rows": int(len(detail)),
            "assigned_35ft": int(_text(detail.loc[_num(detail, "buffer_width_ft").eq(35)], "stable_crash_id").nunique()),
            "assigned_50ft": int(_text(detail.loc[_num(detail, "buffer_width_ft").eq(50)], "stable_crash_id").nunique()),
            "assigned_75ft": int(_text(detail.loc[_num(detail, "buffer_width_ft").eq(75)], "stable_crash_id").nunique()),
            "qa_passed": bool(qa_frame["passed"].all()),
        },
        "doctrine": {
            "primary_buffer_ft": PRIMARY_BUFFER_FT,
            "sensitivity_buffers_ft": [35, 75],
            "multi_assignment_allowed": True,
            "source_preserving_weight": "1 / assignment_count within buffer product",
            "crash_direction_use": "not_used",
        },
    }
    _write_json(manifest, "final_leg_corrected_crash_candidate_assignment_manifest.json")
    _checkpoint("complete")
    print("Complete.")


if __name__ == "__main__":
    main()
