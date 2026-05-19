from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/aadt_bridge_key_diagnostic")

AADT_FILE = Path("artifacts/normalized/aadt.parquet")
USABLE_BINS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa/directional_scaffold_prototype_usable_bins_50ft.csv"
USABLE_SEGMENTS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa/directional_scaffold_prototype_usable_segments.csv"
SOURCE_BIN_GEOMETRY_FILE = OUTPUT_ROOT / "tables/current/signal_oriented_segment_bins_50ft_crash_ready.csv"
ROLE_ENRICHED_SEGMENTS_FILE = OUTPUT_ROOT / "tables/current/signal_oriented_roadway_segments_role_enriched.csv"
AADT_CONTEXT_DIR = OUTPUT_ROOT / "review/current/aadt_context_join"
AADT_CONTEXT_FILE = AADT_CONTEXT_DIR / "directional_bin_aadt_context.csv"
AADT_REVIEW_FILE = AADT_CONTEXT_DIR / "aadt_bin_review_candidates.csv"
AADT_STAGING_SCHEMA_FILE = OUTPUT_ROOT / "review/current/aadt_source_staging/aadt_source_schema.csv"
AADT_STAGING_FIELD_ROLES_FILE = OUTPUT_ROOT / "review/current/aadt_source_staging/aadt_source_field_role_candidates.csv"
AADT_STAGING_CRS_SANITY_FILE = OUTPUT_ROOT / "review/current/aadt_source_staging/aadt_source_crs_sanity.csv"

KEY_FIELD_TOKENS = ("id", "key", "link", "event", "edge", "source", "route", "rte", "name", "measure", "msr", "common")
AADT_CANDIDATE_FIELDS = [
    "LINKID",
    "EDGE_RTE_KEY",
    "RTE_NM",
    "MASTER_RTE_NM",
    "FROM_MEASURE",
    "TO_MEASURE",
    "TRANSPORT_EDGE_FROM_MSR",
    "TRANSPORT_EDGE_TO_MSR",
    "DIRECTIONALITY",
]
SPECIFIC_STABLE_TESTS = {
    "aadt_linkid_vs_stable_event_source": ("LINKID", ["event_source", "EVENT_SOURCE_ID", "event_source_id"]),
    "aadt_linkid_vs_stable_linkid_like": ("LINKID", ["LINKID", "linkid", "link_id", "LINK_ID"]),
    "aadt_edge_rte_key_vs_stable_edge_key_like": ("EDGE_RTE_KEY", ["stable_edge_key", "base_graph_edge_id", "source_bin_key", "road_component_id"]),
    "aadt_route_vs_stable_route_like": ("RTE_NM", ["route_name", "route_common", "stable_route_name_raw", "stable_route_name_normalized"]),
    "aadt_master_route_vs_stable_route_like": ("MASTER_RTE_NM", ["route_name", "route_common", "stable_route_name_raw", "stable_route_name_normalized"]),
}
CRASH_DIRECTION_FIELD_TOKENS = ("crash_direction", "veh_direction", "vehicle_direction", "direction_of_travel", "dir_of_travel")


class ProgressLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.started = time.perf_counter()
        self.path.write_text("", encoding="utf-8")

    def log(self, message: str) -> None:
        elapsed = time.perf_counter() - self.started
        timestamp = datetime.now(timezone.utc).isoformat()
        line = f"{timestamp}\t+{elapsed:,.3f}s\t{message}"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)


def _phase(logger: ProgressLogger, name: str, func: Any, *args: Any, **kwargs: Any) -> Any:
    logger.log(f"BEGIN {name}")
    started = time.perf_counter()
    result = func(*args, **kwargs)
    logger.log(f"END {name}; elapsed_s={time.perf_counter() - started:,.3f}; {_describe_result(result)}")
    return result


def _describe_result(result: Any) -> str:
    if isinstance(result, tuple):
        return "; ".join(_describe_result(item) for item in result)
    if isinstance(result, dict):
        return f"keys={len(result)}"
    if hasattr(result, "shape"):
        return f"rows={result.shape[0]}; columns={result.shape[1]}"
    return f"type={type(result).__name__}"


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS) and column != "signal_relative_direction"


def _read_csv(path: Path, *, usecols: list[str] | None = None, nrows: int | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    if usecols is not None:
        missing = [column for column in usecols if column not in header]
        if missing:
            raise ValueError(f"{path} is missing required columns: {missing}")
        direction_like = [column for column in usecols if _is_crash_direction_field(column)]
        if direction_like:
            raise ValueError(f"Refusing to read crash direction fields from {path}: {direction_like}")
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=usecols, nrows=nrows)


def _candidate_columns(path: Path) -> list[str]:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    return [column for column in header if any(token in column.lower() for token in KEY_FIELD_TOKENS) and not _is_crash_direction_field(column)]


def _load_stable_tables() -> dict[str, pd.DataFrame]:
    tables = {
        "usable_directional_bins": (USABLE_BINS_FILE, None),
        "usable_directional_segments": (USABLE_SEGMENTS_FILE, None),
        "crash_ready_base_bins": (SOURCE_BIN_GEOMETRY_FILE, None),
        "role_enriched_segments": (ROLE_ENRICHED_SEGMENTS_FILE, None),
        "aadt_directional_context": (AADT_CONTEXT_FILE, None),
    }
    loaded: dict[str, pd.DataFrame] = {}
    for name, (path, nrows) in tables.items():
        columns = _candidate_columns(path)
        loaded[name] = _read_csv(path, usecols=columns, nrows=nrows)
    return loaded


def _load_aadt_keys() -> pd.DataFrame:
    return pd.read_parquet(AADT_FILE, columns=[*AADT_CANDIDATE_FIELDS, "AADT", "AADT_YR"])


def _clean_text(value: Any) -> str:
    text = str(value or "").strip().upper()
    return "" if text in {"", "NAN", "NONE", "<NA>"} else text


def _exact_values(series: pd.Series) -> pd.Series:
    return series.map(_clean_text).mask(lambda s: s.eq(""))


def _numeric_canonical(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    return str(int(digits))


def _numeric_values(series: pd.Series) -> pd.Series:
    return series.map(_numeric_canonical).mask(lambda s: s.eq(""))


def normalize_route_name(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    text = text.replace("R-VA", " VA ")
    text = re.sub(r"\bU\s*\.?\s*S\s*\.?\b", " US ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    tokens = [token for token in text.split() if token]
    route_type = ""
    route_number = ""
    direction = ""
    for token in tokens:
        compact = re.sub(r"[^A-Z0-9]", "", token)
        if compact in {"ROUTE", "RTE", "RT", "HIGHWAY", "HWY", "VIRGINIA", "STATE"}:
            continue
        if compact in {"VA", "SR", "US", "I", "INTERSTATE", "SC", "CR", "BUS"}:
            route_type = "I" if compact == "INTERSTATE" else compact
            continue
        match = re.fullmatch(r"(VA|SR|US|I|SC|CR|BUS)?0*([0-9]+)([NSEW])?(?:B)?", compact)
        if match:
            if match.group(1):
                route_type = match.group(1)
            route_number = str(int(match.group(2)))
            if match.group(3):
                direction = match.group(3)
            continue
        if compact in {"N", "S", "E", "W", "NB", "SB", "EB", "WB"}:
            direction = compact[0]
    if not route_number:
        joined = "".join(tokens)
        match = re.search(r"(VA|SR|US|I|SC|CR|BUS)?0*([0-9]+)([NSEW])?(?:B)?", joined)
        if match:
            if match.group(1):
                route_type = match.group(1)
            route_number = str(int(match.group(2)))
            if match.group(3):
                direction = match.group(3)
    if route_number:
        bounded_type = route_type if route_type in {"I", "SC", "CR", "BUS"} else ""
        return f"{bounded_type}{route_number}{direction}"
    return re.sub(r"[^A-Z0-9]", "", text)


def _route_values(series: pd.Series) -> pd.Series:
    return series.map(normalize_route_name).mask(lambda s: s.eq(""))


def _route_like_columns(columns: list[str]) -> list[str]:
    return [
        column
        for column in columns
        if any(token in column.lower() for token in ("route", "rte", "route_name", "route_common"))
    ]


def _select_limited_route_groups(stable: dict[str, pd.DataFrame], aadt: pd.DataFrame, limit: int) -> list[str]:
    stable_groups: set[str] = set()
    for frame in stable.values():
        for column in _route_like_columns(list(frame.columns)):
            stable_groups.update(_route_values(frame[column]).dropna().unique().tolist())
    aadt_groups: set[str] = set()
    for column in [field for field in ("RTE_NM", "MASTER_RTE_NM") if field in aadt.columns]:
        aadt_groups.update(_route_values(aadt[column]).dropna().unique().tolist())
    def usable_group(group: str) -> bool:
        return bool(group) and group.rstrip("NSEW") != "0"

    groups = sorted(group for group in (stable_groups & aadt_groups) if usable_group(group))
    if not groups:
        groups = sorted(group for group in (stable_groups or aadt_groups) if usable_group(group))
    return groups[:limit]


def _filter_frame_to_route_groups(frame: pd.DataFrame, route_groups: set[str]) -> pd.DataFrame:
    route_columns = _route_like_columns(list(frame.columns))
    if not route_columns:
        return frame.head(0).copy()
    keep = pd.Series(False, index=frame.index)
    for column in route_columns:
        keep = keep | _route_values(frame[column]).isin(route_groups).fillna(False)
    return frame.loc[keep].copy()


def _limit_to_route_groups(stable: dict[str, pd.DataFrame], aadt: pd.DataFrame, limit: int | None) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, list[str]]:
    if not limit:
        return stable, aadt, []
    route_groups = _select_limited_route_groups(stable, aadt, limit)
    route_group_set = set(route_groups)
    stable_limited = {
        name: _filter_frame_to_route_groups(frame, route_group_set)
        for name, frame in stable.items()
    }
    aadt_keep = pd.Series(False, index=aadt.index)
    for column in [field for field in ("RTE_NM", "MASTER_RTE_NM") if field in aadt.columns]:
        aadt_keep = aadt_keep | _route_values(aadt[column]).isin(route_group_set).fillna(False)
    return stable_limited, aadt.loc[aadt_keep].copy(), route_groups


def _field_inventory(frame: pd.DataFrame, dataset: str, side: str) -> pd.DataFrame:
    rows = []
    for column in frame.columns:
        series = frame[column]
        exact = _exact_values(series).dropna()
        numeric = _numeric_values(series).dropna()
        route = _route_values(series).dropna()
        rows.append(
            {
                "side": side,
                "dataset": dataset,
                "field_name": column,
                "row_count": len(frame),
                "nonblank_count": int(exact.shape[0]),
                "unique_exact_count": int(exact.nunique()),
                "numeric_canonical_nonblank_count": int(numeric.shape[0]),
                "numeric_canonical_unique_count": int(numeric.nunique()),
                "route_normalized_nonblank_count": int(route.shape[0]),
                "route_normalized_unique_count": int(route.nunique()),
                "sample_values": " | ".join(exact.head(5).astype(str).tolist()),
            }
        )
    return pd.DataFrame(rows)


def _inventories(stable: dict[str, pd.DataFrame], aadt: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    stable_inventory = pd.concat([_field_inventory(frame, name, "stable") for name, frame in stable.items()], ignore_index=True)
    aadt_inventory = _field_inventory(aadt, "aadt", "aadt")
    return stable_inventory, aadt_inventory


def _match_matrix(stable: dict[str, pd.DataFrame], aadt: pd.DataFrame, *, mode: str) -> pd.DataFrame:
    rows = []
    aadt_fields = [field for field in AADT_CANDIDATE_FIELDS if field in aadt.columns]
    aadt_sets = {
        field: _normalizer(mode)(aadt[field]).dropna()
        for field in aadt_fields
    }
    aadt_unique = {field: set(values.tolist()) for field, values in aadt_sets.items()}
    for stable_dataset, frame in stable.items():
        for stable_field in frame.columns:
            stable_values = _normalizer(mode)(frame[stable_field]).dropna()
            stable_set = set(stable_values.tolist())
            if not stable_set:
                continue
            for aadt_field in aadt_fields:
                aadt_set = aadt_unique[aadt_field]
                common = stable_set & aadt_set
                rows.append(
                    {
                        "match_mode": mode,
                        "stable_dataset": stable_dataset,
                        "stable_field": stable_field,
                        "aadt_field": aadt_field,
                        "stable_nonblank_count": int(stable_values.shape[0]),
                        "stable_unique_count": int(len(stable_set)),
                        "aadt_unique_count": int(len(aadt_set)),
                        "common_unique_count": int(len(common)),
                        "stable_unique_match_share": round(len(common) / len(stable_set), 6) if stable_set else 0.0,
                        "aadt_unique_match_share": round(len(common) / len(aadt_set), 6) if aadt_set else 0.0,
                        "sample_common_values": " | ".join(sorted(common)[:10]),
                    }
                )
    return pd.DataFrame(rows).sort_values(["common_unique_count", "stable_unique_match_share"], ascending=[False, False])


def _normalizer(mode: str):
    if mode == "numeric_canonical":
        return _numeric_values
    if mode == "route_normalized":
        return _route_values
    return _exact_values


def _specific_bridge_diagnostic(stable: dict[str, pd.DataFrame], aadt: pd.DataFrame, test_name: str, aadt_field: str, stable_field_names: list[str]) -> pd.DataFrame:
    rows = []
    if aadt_field not in aadt.columns:
        return pd.DataFrame()
    aadt_exact = set(_exact_values(aadt[aadt_field]).dropna().tolist())
    aadt_numeric = set(_numeric_values(aadt[aadt_field]).dropna().tolist())
    aadt_route = set(_route_values(aadt[aadt_field]).dropna().tolist())
    for dataset, frame in stable.items():
        for stable_field in stable_field_names:
            if stable_field not in frame.columns:
                continue
            exact = set(_exact_values(frame[stable_field]).dropna().tolist())
            numeric = set(_numeric_values(frame[stable_field]).dropna().tolist())
            route = set(_route_values(frame[stable_field]).dropna().tolist())
            rows.append(
                {
                    "test_name": test_name,
                    "stable_dataset": dataset,
                    "stable_field": stable_field,
                    "aadt_field": aadt_field,
                    "exact_common_unique_count": len(exact & aadt_exact),
                    "exact_stable_unique_match_share": round(len(exact & aadt_exact) / len(exact), 6) if exact else 0.0,
                    "numeric_common_unique_count": len(numeric & aadt_numeric),
                    "numeric_stable_unique_match_share": round(len(numeric & aadt_numeric) / len(numeric), 6) if numeric else 0.0,
                    "route_common_unique_count": len(route & aadt_route),
                    "route_stable_unique_match_share": round(len(route & aadt_route) / len(route), 6) if route else 0.0,
                    "stable_unique_count": len(exact),
                    "aadt_unique_count": len(aadt_exact),
                    "sample_numeric_common_values": " | ".join(sorted(numeric & aadt_numeric)[:10]),
                }
            )
    return pd.DataFrame(rows).sort_values(["numeric_common_unique_count", "route_common_unique_count", "exact_common_unique_count"], ascending=[False, False, False])


def _route_measure_feasibility(stable: dict[str, pd.DataFrame], aadt: pd.DataFrame) -> pd.DataFrame:
    stable_measure_fields = []
    stable_route_fields = []
    for dataset, frame in stable.items():
        for column in frame.columns:
            lower = column.lower()
            if "measure" in lower or lower.endswith("_msr") or "from_msr" in lower or "to_msr" in lower:
                stable_measure_fields.append((dataset, column))
            if "route" in lower or "rte" in lower or column in {"route_name", "route_common", "stable_route_name_raw"}:
                stable_route_fields.append((dataset, column))
    aadt_measure_fields = [field for field in ["FROM_MEASURE", "TO_MEASURE", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"] if field in aadt.columns]
    rows = [
        {
            "diagnostic": "stable_measure_fields_found",
            "stable_route_field_count": len(stable_route_fields),
            "stable_measure_field_count": len(stable_measure_fields),
            "stable_route_fields": " | ".join(f"{dataset}.{field}" for dataset, field in stable_route_fields[:30]),
            "stable_measure_fields": " | ".join(f"{dataset}.{field}" for dataset, field in stable_measure_fields[:30]),
            "aadt_measure_fields": " | ".join(aadt_measure_fields),
            "route_measure_overlap_feasible": bool(stable_measure_fields and stable_route_fields and aadt_measure_fields),
            "notes": "No stable LRS measure fields were found; bin-distance fields are signal-relative feet and are not AADT route measures." if not stable_measure_fields else "Stable measure-like fields found; inspect exact semantics before use.",
        }
    ]
    return pd.DataFrame(rows)


def _route_mismatch_recovery(stable: dict[str, pd.DataFrame], aadt: pd.DataFrame, *, detail_output_dir: Path) -> pd.DataFrame:
    review_cols = [
        "reference_directional_bin_id",
        "source_bin_key",
        "base_segment_id",
        "stable_route_name_raw",
        "stable_route_name_normalized",
        "route_name",
        "route_common",
        "route_id",
        "event_source",
        "road_component_id",
        "aadt_context_status",
        "any_nearest_aadt_record_id",
        "any_aadt_route_name_raw",
        "any_aadt_route_name_normalized",
        "any_route_or_edge_match_status",
        "nearest_aadt_record_id",
        "nearest_aadt_distance_ft",
    ]
    header = pd.read_csv(AADT_REVIEW_FILE, nrows=0).columns.tolist()
    usecols = [column for column in review_cols if column in header]
    review = _read_csv(AADT_REVIEW_FILE, usecols=usecols)
    mismatch = review.loc[review["aadt_context_status"].eq("review_route_mismatch")].copy()
    aadt_linkids_numeric = set(_numeric_values(aadt["LINKID"]).dropna().tolist()) if "LINKID" in aadt.columns else set()
    aadt_routes = set(pd.concat([_route_values(aadt[field]).dropna() for field in ["RTE_NM", "MASTER_RTE_NM"] if field in aadt.columns], ignore_index=True).tolist())
    for field in ["event_source", "route_id", "road_component_id"]:
        if field in mismatch.columns:
            mismatch[f"{field}_numeric_canonical"] = _numeric_values(mismatch[field]).fillna("")
            mismatch[f"{field}_matches_aadt_linkid_numeric"] = mismatch[f"{field}_numeric_canonical"].isin(aadt_linkids_numeric)
    route_field = "stable_route_name_normalized"
    if route_field in mismatch.columns:
        mismatch["stable_route_exists_somewhere_in_aadt_routes"] = mismatch[route_field].fillna("").astype(str).isin(aadt_routes)
    else:
        mismatch["stable_route_exists_somewhere_in_aadt_routes"] = False
    key_cols = [c for c in mismatch.columns if c.endswith("_matches_aadt_linkid_numeric")]
    mismatch["recoverable_by_numeric_linkid_candidate"] = mismatch[key_cols].any(axis=1) if key_cols else False
    stable_route_raw = mismatch.get("stable_route_name_raw", pd.Series("", index=mismatch.index)).fillna("").astype(str).str.upper()
    nearest_route_raw = mismatch.get("any_aadt_route_name_raw", pd.Series("", index=mismatch.index)).fillna("").astype(str).str.upper()
    stable_route_norm = mismatch.get("stable_route_name_normalized", pd.Series("", index=mismatch.index)).fillna("").astype(str).str.upper()
    nearest_route_norm = mismatch.get("any_aadt_route_name_normalized", pd.Series("", index=mismatch.index)).fillna("").astype(str).str.upper()
    stable_is_interstate = stable_route_raw.str.contains(r"\bIS|INTERSTATE", regex=True) | stable_route_norm.str.startswith("I")
    nearest_is_interstate = nearest_route_raw.str.contains(r"\bIS|INTERSTATE", regex=True) | nearest_route_norm.str.startswith("I")
    mismatch["nearest_candidate_ramp_or_parallel_flag"] = nearest_route_raw.str.contains(r"RMP|RAMP|RV|DIST/COLL|DCR|COLL", regex=True)
    mismatch["nearest_candidate_interstate_conflict_flag"] = stable_is_interstate.ne(nearest_is_interstate)
    mismatch["route_formatting_recovery_possible_flag"] = mismatch["stable_route_exists_somewhere_in_aadt_routes"] & ~mismatch["recoverable_by_numeric_linkid_candidate"]
    grouped = (
        mismatch.groupby(["aadt_context_status"], dropna=False)
        .agg(
            route_mismatch_bin_count=("reference_directional_bin_id", "nunique"),
            bins_recoverable_by_numeric_linkid=("recoverable_by_numeric_linkid_candidate", "sum"),
            bins_where_stable_route_exists_in_aadt=("stable_route_exists_somewhere_in_aadt_routes", "sum"),
            bins_with_nearest_ramp_or_parallel_candidate=("nearest_candidate_ramp_or_parallel_flag", "sum"),
            bins_with_nearest_interstate_conflict=("nearest_candidate_interstate_conflict_flag", "sum"),
            bins_with_route_formatting_recovery_possible=("route_formatting_recovery_possible_flag", "sum"),
            unique_stable_routes=("stable_route_name_normalized", "nunique"),
            unique_nearest_aadt_routes=("any_aadt_route_name_normalized", "nunique"),
        )
        .reset_index()
    )
    detail_sample = mismatch.sort_values(["recoverable_by_numeric_linkid_candidate", "stable_route_exists_somewhere_in_aadt_routes"], ascending=[False, False]).head(200)
    grouped["sample_detail_rows_written"] = len(detail_sample)
    detail_sample.to_csv(detail_output_dir / "aadt_route_mismatch_recovery_detail_sample.csv", index=False)
    return grouped


def _recommendations(summary: pd.DataFrame, linkid_diag: pd.DataFrame, route_measure: pd.DataFrame, mismatch: pd.DataFrame) -> pd.DataFrame:
    best_link = pd.DataFrame()
    if not linkid_diag.empty:
        best_link = linkid_diag.sort_values(["numeric_stable_unique_match_share", "numeric_common_unique_count"], ascending=[False, False]).head(1)
    link_share = float(best_link.iloc[0]["numeric_stable_unique_match_share"]) if not best_link.empty else 0.0
    measure_feasible = bool(route_measure.iloc[0]["route_measure_overlap_feasible"]) if not route_measure.empty else False
    recoverable = int(mismatch.get("bins_recoverable_by_numeric_linkid", pd.Series([0])).iloc[0]) if not mismatch.empty else 0
    rows = []
    if link_share >= 0.8:
        priority = 1
        strategy = "key_first_join"
        rationale = "Numeric-canonical AADT LINKID has strong stable-side overlap; test this bridge before revising route/spatial rules."
    elif measure_feasible:
        priority = 1
        strategy = "route_measure_join"
        rationale = "Stable route and measure fields appear available; validate measure semantics and use route+measure before proximity."
    else:
        priority = 1
        strategy = "route_identity_repair_then_route_assisted_join"
        rationale = "No strong direct LINKID bridge or stable LRS measures were found in active stable tables; the high route-mismatch burden points to route identity/normalization limits and spatial-only nearest should remain review-only."
    rows.append(
        {
            "priority": priority,
            "recommended_strategy": strategy,
            "rationale": rationale,
            "numeric_linkid_best_stable_share": link_share,
            "route_measure_feasible": measure_feasible,
            "route_mismatch_bins_recoverable_by_key": recoverable,
        }
    )
    rows.append(
        {
            "priority": 2,
            "recommended_strategy": "route_assisted_nearest_fallback_only",
            "rationale": "Use route-assisted nearest only after stronger key evidence fails, with ambiguous/conflicting AADT values preserved as review.",
            "numeric_linkid_best_stable_share": link_share,
            "route_measure_feasible": measure_feasible,
            "route_mismatch_bins_recoverable_by_key": recoverable,
        }
    )
    rows.append(
        {
            "priority": 3,
            "recommended_strategy": "spatial_only_review_only",
            "rationale": "Spatial-only nearest candidates explain route mismatches but should not assign stable AADT without route/key support.",
            "numeric_linkid_best_stable_share": link_share,
            "route_measure_feasible": measure_feasible,
            "route_mismatch_bins_recoverable_by_key": recoverable,
        }
    )
    return pd.DataFrame(rows)


def _summary(
    stable_inventory: pd.DataFrame,
    aadt_inventory: pd.DataFrame,
    exact_matrix: pd.DataFrame,
    numeric_matrix: pd.DataFrame,
    linkid_diag: pd.DataFrame,
    edge_diag: pd.DataFrame,
    route_diag: pd.DataFrame,
    route_measure: pd.DataFrame,
    mismatch: pd.DataFrame,
    recommendations: pd.DataFrame,
) -> pd.DataFrame:
    independent_numeric = numeric_matrix.loc[
        ~numeric_matrix["stable_dataset"].eq("aadt_directional_context")
        & ~numeric_matrix["stable_field"].str.contains("aadt", case=False, na=False)
        & ~numeric_matrix["stable_field"].str.contains("signal_id", case=False, na=False)
        & ~numeric_matrix["stable_field"].str.contains("route|rte|name|common|distance|midpoint|bin_index|count|year", case=False, na=False)
        & ~numeric_matrix["aadt_field"].str.contains("measure|msr|route|rte|name|direction|year|aadt", case=False, na=False)
    ].copy()
    best_numeric = independent_numeric.head(1)
    best_route = route_diag.sort_values(["route_stable_unique_match_share", "route_common_unique_count"], ascending=[False, False]).head(1) if not route_diag.empty else pd.DataFrame()
    best_link = linkid_diag.head(1) if not linkid_diag.empty else pd.DataFrame()
    rows = [
        {"metric": "stable_candidate_fields_inventoried", "value": "", "count": int(len(stable_inventory))},
        {"metric": "aadt_candidate_fields_inventoried", "value": "", "count": int(len(aadt_inventory))},
        {"metric": "best_independent_numeric_canonical_pair", "value": _pair_label(best_numeric), "count": int(best_numeric.iloc[0]["common_unique_count"]) if not best_numeric.empty else 0},
        {"metric": "best_linkid_bridge_pair", "value": _specific_label(best_link), "count": int(best_link.iloc[0]["numeric_common_unique_count"]) if not best_link.empty else 0},
        {"metric": "best_route_name_pair", "value": _specific_label(best_route), "count": int(best_route.iloc[0]["route_common_unique_count"]) if not best_route.empty else 0},
        {"metric": "route_measure_matching_feasible", "value": bool(route_measure.iloc[0]["route_measure_overlap_feasible"]) if not route_measure.empty else False, "count": ""},
        {"metric": "route_mismatch_bins", "value": "", "count": int(mismatch["route_mismatch_bin_count"].sum()) if not mismatch.empty else 0},
        {"metric": "route_mismatch_bins_recoverable_by_numeric_linkid", "value": "", "count": int(mismatch["bins_recoverable_by_numeric_linkid"].sum()) if not mismatch.empty else 0},
        {"metric": "recommended_primary_strategy", "value": recommendations.iloc[0]["recommended_strategy"] if not recommendations.empty else "", "count": ""},
        {"metric": "crash_direction_fields_read_or_used", "value": False, "count": ""},
        {"metric": "aadt_join_logic_changed", "value": False, "count": ""},
        {"metric": "scaffold_assignment_access_speed_logic_changed", "value": False, "count": ""},
    ]
    return pd.DataFrame(rows)


def _pair_label(frame: pd.DataFrame) -> str:
    if frame.empty:
        return ""
    row = frame.iloc[0]
    return f"{row['stable_dataset']}.{row['stable_field']} -> AADT.{row['aadt_field']}"


def _specific_label(frame: pd.DataFrame) -> str:
    if frame.empty:
        return ""
    row = frame.iloc[0]
    return f"{row['stable_dataset']}.{row['stable_field']} -> AADT.{row['aadt_field']}"


def _findings(summary: pd.DataFrame, outputs: dict[str, Path]) -> str:
    def metric_value(name: str) -> Any:
        row = summary.loc[summary["metric"].eq(name)]
        if row.empty:
            return ""
        return row.iloc[0]["value"]

    def metric_count(name: str) -> Any:
        row = summary.loc[summary["metric"].eq(name)]
        if row.empty:
            return ""
        return row.iloc[0]["count"]

    lines = [
        "# AADT Bridge-Key Diagnostic Findings",
        "",
        "## Bounded Question",
        "",
        "Diagnose whether AADT should be joined by a direct bridge key, route+measure support, or route-assisted fallback before changing the current AADT context join.",
        "",
        "## Boundary Checks",
        "",
        "- crash direction fields read or used: False",
        "- AADT join logic changed: False",
        "- scaffold/catchment/assignment/access/speed logic changed: False",
        "",
        "## Main Results",
        "",
        f"- best independent numeric-canonical pair: {metric_value('best_independent_numeric_canonical_pair')} ({metric_count('best_independent_numeric_canonical_pair')} common unique values)",
        f"- best LINKID bridge pair: {metric_value('best_linkid_bridge_pair')} ({metric_count('best_linkid_bridge_pair')} common unique values)",
        f"- best route-name pair: {metric_value('best_route_name_pair')} ({metric_count('best_route_name_pair')} common unique values)",
        f"- route+measure matching feasible: {metric_value('route_measure_matching_feasible')}",
        f"- route-mismatch bins: {metric_count('route_mismatch_bins')}",
        f"- route-mismatch bins recoverable by numeric LINKID: {metric_count('route_mismatch_bins_recoverable_by_numeric_linkid')}",
        f"- recommended primary strategy: {metric_value('recommended_primary_strategy')}",
        "",
        "## Files Created",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
    ]
    return "\n".join(lines)


def build_aadt_bridge_key_diagnostic(*, output_root: Path = OUTPUT_ROOT, limit_route_groups: int | None = None) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    logger = ProgressLogger(out_dir / "aadt_bridge_key_diagnostic_progress.log")
    logger.log("START build_aadt_bridge_key_diagnostic")
    stable = _phase(logger, "_load_stable_tables", _load_stable_tables)
    aadt = _phase(logger, "_load_aadt_keys", _load_aadt_keys)
    limited_route_groups: list[str] = []
    if limit_route_groups:
        stable, aadt, limited_route_groups = _phase(logger, "_limit_to_route_groups", _limit_to_route_groups, stable, aadt, limit_route_groups)
        logger.log(f"LIMIT route_groups={len(limited_route_groups)}; values={limited_route_groups[:20]}")
    _ = _phase(logger, "_read_aadt_staging_schema", _read_csv, AADT_STAGING_SCHEMA_FILE)
    _ = _phase(logger, "_read_aadt_staging_field_roles", _read_csv, AADT_STAGING_FIELD_ROLES_FILE)
    _ = _phase(logger, "_read_aadt_staging_crs_sanity", _read_csv, AADT_STAGING_CRS_SANITY_FILE)
    stable_inventory, aadt_inventory = _phase(logger, "_inventories", _inventories, stable, aadt)
    exact_matrix = _phase(logger, "_exact_match_matrix", _match_matrix, stable, aadt, mode="exact")
    numeric_matrix = _phase(logger, "_numeric_match_matrix", _match_matrix, stable, aadt, mode="numeric_canonical")
    route_matrix = _phase(logger, "_route_match_matrix", _match_matrix, stable, aadt, mode="route_normalized")
    linkid_diag = _phase(logger, "_linkid_bridge_diagnostic", _specific_bridge_diagnostic, stable, aadt, "aadt_linkid_vs_stable_event_or_link_fields", "LINKID", ["event_source", "EVENT_SOURCE_ID", "event_source_id", "source_road_row_id", "LINKID", "linkid", "link_id", "LINK_ID", "route_id", "road_component_id"])
    edge_diag = _phase(logger, "_edge_rte_key_diagnostic", _specific_bridge_diagnostic, stable, aadt, "aadt_edge_rte_key_vs_stable_edge_key_fields", "EDGE_RTE_KEY", ["stable_edge_key", "base_graph_edge_id", "source_bin_key", "road_component_id", "base_segment_id"])
    route_diag = _phase(logger, "_route_name_match_diagnostic", _specific_bridge_diagnostic, stable, aadt, "aadt_routes_vs_stable_route_name_fields", "RTE_NM", ["route_name", "route_common", "stable_route_name_raw", "stable_route_name_normalized"])
    route_measure = _phase(logger, "_route_measure_feasibility", _route_measure_feasibility, stable, aadt)
    mismatch = _phase(logger, "_route_mismatch_recovery", _route_mismatch_recovery, stable, aadt, detail_output_dir=out_dir)
    recommendations = _recommendations(pd.DataFrame(), linkid_diag, route_measure, mismatch)
    summary = _summary(stable_inventory, aadt_inventory, exact_matrix, numeric_matrix, linkid_diag, edge_diag, route_diag, route_measure, mismatch, recommendations)

    outputs = {
        "summary_csv": out_dir / "aadt_bridge_key_diagnostic_summary.csv",
        "stable_side_key_inventory_csv": out_dir / "stable_side_key_inventory.csv",
        "aadt_side_key_inventory_csv": out_dir / "aadt_side_key_inventory.csv",
        "key_match_matrix_csv": out_dir / "aadt_key_match_matrix.csv",
        "numeric_key_match_matrix_csv": out_dir / "aadt_numeric_canonical_key_match_matrix.csv",
        "linkid_bridge_csv": out_dir / "aadt_linkid_bridge_diagnostic.csv",
        "edge_rte_key_csv": out_dir / "aadt_edge_rte_key_diagnostic.csv",
        "route_name_match_csv": out_dir / "aadt_route_name_match_diagnostic.csv",
        "route_measure_overlap_csv": out_dir / "aadt_route_measure_overlap_feasibility.csv",
        "route_mismatch_recovery_csv": out_dir / "aadt_route_mismatch_recovery_diagnostic.csv",
        "recommended_strategy_csv": out_dir / "aadt_bridge_key_recommended_join_strategy.csv",
        "findings_md": out_dir / "aadt_bridge_key_diagnostic_findings.md",
        "manifest_json": out_dir / "aadt_bridge_key_diagnostic_manifest.json",
        "progress_log": out_dir / "aadt_bridge_key_diagnostic_progress.log",
    }
    _write_csv(summary, outputs["summary_csv"])
    _write_csv(stable_inventory, outputs["stable_side_key_inventory_csv"])
    _write_csv(aadt_inventory, outputs["aadt_side_key_inventory_csv"])
    _write_csv(pd.concat([exact_matrix, route_matrix], ignore_index=True, sort=False), outputs["key_match_matrix_csv"])
    _write_csv(numeric_matrix, outputs["numeric_key_match_matrix_csv"])
    _write_csv(linkid_diag, outputs["linkid_bridge_csv"])
    _write_csv(edge_diag, outputs["edge_rte_key_csv"])
    _write_csv(route_diag, outputs["route_name_match_csv"])
    _write_csv(route_measure, outputs["route_measure_overlap_csv"])
    _write_csv(mismatch, outputs["route_mismatch_recovery_csv"])
    _write_csv(recommendations, outputs["recommended_strategy_csv"])
    _write_text(_findings(summary, outputs), outputs["findings_md"])
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only AADT bridge-key and route-identity diagnostic before revising AADT context join",
        "limit_route_groups": limit_route_groups,
        "limited_route_groups": limited_route_groups,
        "inputs": {
            "aadt": str(AADT_FILE),
            "usable_bins": str(USABLE_BINS_FILE),
            "usable_segments": str(USABLE_SEGMENTS_FILE),
            "source_bin_geometry": str(SOURCE_BIN_GEOMETRY_FILE),
            "role_enriched_segments": str(ROLE_ENRICHED_SEGMENTS_FILE),
            "aadt_context": str(AADT_CONTEXT_FILE),
            "aadt_review": str(AADT_REVIEW_FILE),
            "aadt_staging_schema": str(AADT_STAGING_SCHEMA_FILE),
            "aadt_staging_field_roles": str(AADT_STAGING_FIELD_ROLES_FILE),
            "aadt_staging_crs_sanity": str(AADT_STAGING_CRS_SANITY_FILE),
        },
        "crash_direction_fields_read_or_used": False,
        "aadt_join_logic_changed": False,
        "scaffold_assignment_access_speed_logic_changed": False,
        "summary": summary.to_dict(orient="records"),
        "outputs": {key: str(path) for key, path in outputs.items()},
    }
    _write_json(manifest, outputs["manifest_json"])
    logger.log("END build_aadt_bridge_key_diagnostic")
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only AADT bridge-key and route-identity diagnostic.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--limit-route-groups", type=int, default=None, help="Limit diagnostics to the first N normalized route groups for bounded smoke runs.")
    args = parser.parse_args(argv)
    outputs = build_aadt_bridge_key_diagnostic(output_root=args.output_root, limit_route_groups=args.limit_route_groups)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
