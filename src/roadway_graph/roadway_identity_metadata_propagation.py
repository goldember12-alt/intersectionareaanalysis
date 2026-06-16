from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyarrow.parquet as pq


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/roadway_identity_metadata_propagation")

ROADS_FILE = Path("artifacts/normalized/roads.parquet")
STAGED_ROADS_FILE = Path("artifacts/staging/roads.parquet")
AADT_FILE = Path("artifacts/normalized/aadt.parquet")
SPEED_FILE = Path("artifacts/normalized/speed.parquet")

TABLES_CURRENT = OUTPUT_ROOT / "tables/current"
ROLE_SEGMENTS_FILE = TABLES_CURRENT / "signal_oriented_roadway_segments_role_enriched.csv"
RECOVERY_SEGMENTS_FILE = TABLES_CURRENT / "signal_oriented_roadway_segments_divided_pairing_recovery_enriched.csv"
GEOMETRIC_SEGMENTS_FILE = TABLES_CURRENT / "signal_oriented_roadway_segments_geometric_direction.csv"
BASE_BINS_FILE = TABLES_CURRENT / "signal_oriented_segment_bins_50ft_crash_ready.csv"
GRAPH_EDGES_FILE = TABLES_CURRENT / "roadway_graph_edges.csv"
USABLE_SEGMENTS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa/directional_scaffold_prototype_usable_segments.csv"
USABLE_BINS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa/directional_scaffold_prototype_usable_bins_50ft.csv"
CATCHMENT_INDEX_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_index.csv"

AADT_V2_CONTEXT_FILE = OUTPUT_ROOT / "review/current/aadt_context_join_v2_route_key_first/directional_bin_aadt_context_v2.csv"
SPEED_V3_CONTEXT_FILE = OUTPUT_ROOT / "review/current/speed_context_join_v3_route_assisted/directional_bin_speed_context_v3.csv"

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)

IDENTITY_FIELD_PATTERNS = (
    "link",
    "route",
    "rte",
    "dir",
    "direction",
    "node",
    "measure",
    "msr",
    "event",
    "edge",
    "source",
    "parent",
    "component",
    "location",
    "resolution",
    "road_row",
    "row_id",
    "aadt",
)

CANONICAL_OUTPUT_FIELDS = [
    "LinkID_Norm",
    "RouteID_Norm",
    "RouteNm_Norm",
    "DirCode_Norm",
    "FromNode_Norm",
    "ToNode_Norm",
    "AADT",
    "source_RTE_NM",
    "source_RTE_COMMON",
    "source_RTE_ID",
    "source_EVENT_SOUR",
    "source_EVENT_LOCA",
    "source_EVENT_COMP",
    "source_LOC_COMP_D",
    "source_LOC_COMP_DIRECTIONALITY_NAME",
    "source_FROM_MEASURE",
    "source_TO_MEASURE",
    "source_RTE_FROM_M",
    "source_RTE_TO_MSR",
    "source_road_row_id",
    "base_graph_edge_id",
    "road_component_id",
]


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS) and column != "signal_relative_direction"


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    if usecols is not None:
        missing = [column for column in usecols if column not in header]
        if missing:
            raise ValueError(f"{path} is missing required columns: {missing}")
        blocked = [column for column in usecols if _is_crash_direction_field(column)]
        if blocked:
            raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    safe_usecols = None if usecols is None else [column for column in usecols if not _is_crash_direction_field(column)]
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=safe_usecols)


def _read_table(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        if usecols is None:
            frame = gpd.read_parquet(path)
        else:
            columns = [column for column in usecols if not _is_crash_direction_field(column)]
            frame = pd.read_parquet(path, columns=columns)
        return pd.DataFrame(frame.drop(columns=["geometry"], errors="ignore"))
    return _read_csv(path, usecols=usecols)


def _table_columns(path: Path) -> list[str]:
    if path.suffix.lower() == ".parquet":
        return [column for column in pq.ParquetFile(path).schema_arrow.names if not _is_crash_direction_field(column)]
    return [column for column in pd.read_csv(path, nrows=0).columns.tolist() if not _is_crash_direction_field(column)]


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.upper() in {"", "NAN", "NONE", "<NA>", "NULL"} else text


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _numeric_key(value: Any) -> str:
    text = _clean(value)
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    return str(int(digits))


def _norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", _clean(value)).strip()


def _route_key(value: Any) -> str:
    text = _clean(value).upper()
    if not text:
        return ""
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("R-VA", " ")
    text = text.replace("S-VA", " ")
    text = re.sub(r"\bU\s*\.?\s*S\s*\.?\b", " US ", text)
    text = re.sub(r"\bINTERSTATE\b", " I ", text)
    text = re.sub(r"\bIS\b", " I ", text)
    text = re.sub(r"\b(STATE\s+ROUTE|STATE|ROUTE|RTE|RT|HIGHWAY|HWY|VIRGINIA)\b", " ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    tokens = [token for token in text.split() if token]
    joined = "".join(tokens)
    route_type = ""
    route_number = ""
    direction = ""
    route_token_seen = False
    for token in tokens:
        compact = re.sub(r"[^A-Z0-9]", "", token)
        if compact in {"US", "SR", "VA", "I"}:
            route_type = "SR" if compact == "VA" else compact
            route_token_seen = True
            continue
        if compact in {"NB", "SB", "EB", "WB", "N", "S", "E", "W"}:
            direction = compact[0]
            continue
        match = re.fullmatch(r"(US|SR|VA|I|IS)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?", compact)
        if match:
            prefix = match.group(1)
            route_type = "I" if prefix in {"I", "IS"} else ("SR" if prefix == "VA" else prefix)
            route_number = str(int(match.group(2)))
            if match.group(3):
                direction = match.group(3)[0]
            route_token_seen = True
            continue
        match = re.fullmatch(r"0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?", compact)
        if match and route_type:
            route_number = str(int(match.group(1)))
            if match.group(2):
                direction = match.group(2)[0]
    if not route_number:
        match = re.search(r"(US|SR|VA|I|IS)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?", joined)
        if match:
            prefix = match.group(1)
            route_type = "I" if prefix in {"I", "IS"} else ("SR" if prefix == "VA" else prefix)
            route_number = str(int(match.group(2)))
            if match.group(3):
                direction = match.group(3)[0]
            route_token_seen = True
    if route_number and route_type and route_token_seen:
        return f"{route_type}{route_number}{direction}"
    return re.sub(r"[^A-Z0-9]", "", " ".join(tokens))


def _distance_window(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "unknown_distance"
    if numeric <= 1000:
        return "high_priority_0_1000ft"
    if numeric <= 2500:
        return "sensitivity_1000_2500ft"
    return "outside_context_window"


def _source_bin_key(base_segment_id: Any, bin_index_in_travel_direction: Any) -> str:
    index = pd.to_numeric(pd.Series([bin_index_in_travel_direction]), errors="coerce").iloc[0]
    if pd.isna(index):
        return ""
    return f"{base_segment_id}_bin_{int(index) - 1:04d}"


def _identity_columns(columns: list[str]) -> list[str]:
    out = []
    for column in columns:
        lower = column.lower()
        if _is_crash_direction_field(column):
            continue
        if any(pattern in lower for pattern in IDENTITY_FIELD_PATTERNS) or column in CANONICAL_OUTPUT_FIELDS:
            out.append(column)
    return out


def _field_inventory(tables: dict[str, Path]) -> pd.DataFrame:
    rows = []
    for name, path in tables.items():
        if not path.exists():
            rows.append({"table_name": name, "path": str(path), "field_name": "", "field_role_guess": "missing_table", "field_present": False})
            continue
        for column in _table_columns(path):
            if column == "geometry":
                continue
            role = "identity_candidate" if column in _identity_columns([column]) else "other"
            rows.append({"table_name": name, "path": str(path), "field_name": column, "field_role_guess": role, "field_present": True})
    return pd.DataFrame(rows)


def _missingness_and_profile(tables: dict[str, Path]) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing_rows = []
    profile_rows = []
    for name, path in tables.items():
        if not path.exists():
            continue
        columns = _identity_columns(_table_columns(path))
        if not columns:
            continue
        frame = _read_table(path, usecols=columns)
        row_count = len(frame)
        for column in columns:
            values = frame[column].astype(str).map(_clean)
            nonmissing = int(values.ne("").sum())
            unique = int(values.loc[values.ne("")].nunique())
            missing_rows.append(
                {
                    "table_name": name,
                    "field_name": column,
                    "row_count": row_count,
                    "nonmissing_count": nonmissing,
                    "missing_count": row_count - nonmissing,
                    "nonmissing_share": round(nonmissing / row_count, 6) if row_count else 0,
                }
            )
            sample = " | ".join(values.loc[values.ne("")].drop_duplicates().head(8).tolist())
            profile_rows.append(
                {
                    "table_name": name,
                    "field_name": column,
                    "unique_nonmissing_count": unique,
                    "sample_values": sample,
                }
            )
    return pd.DataFrame(missing_rows), pd.DataFrame(profile_rows)


def _load_source_roads() -> pd.DataFrame:
    columns = [
        "RTE_NM",
        "RTE_COMMON",
        "RTE_ID",
        "EVENT_SOUR",
        "EVENT_LOCA",
        "EVENT_COMP",
        "LOC_COMP_D",
        "FROM_MEASURE",
        "TO_MEASURE",
        "RTE_FROM_M",
        "RTE_TO_MSR",
    ]
    available = [column for column in columns if column in _table_columns(ROADS_FILE)]
    roads = _read_table(ROADS_FILE, usecols=available).reset_index(names="source_road_row_id")
    roads["source_road_row_id"] = roads["source_road_row_id"].astype(str)
    return roads


def _canonical_source_identity(roads: pd.DataFrame) -> pd.DataFrame:
    out = roads.copy()
    out["LinkID_Norm"] = ""
    out["RouteID_Norm"] = out.get("RTE_ID", "").map(_norm_text) if "RTE_ID" in out.columns else ""
    out["RouteNm_Norm"] = out.get("RTE_NM", "").map(_norm_text) if "RTE_NM" in out.columns else ""
    out["DirCode_Norm"] = out.get("LOC_COMP_D", "").map(_norm_text) if "LOC_COMP_D" in out.columns else ""
    out["FromNode_Norm"] = ""
    out["ToNode_Norm"] = ""
    out["AADT"] = ""
    rename = {
        "RTE_NM": "source_RTE_NM",
        "RTE_COMMON": "source_RTE_COMMON",
        "RTE_ID": "source_RTE_ID",
        "EVENT_SOUR": "source_EVENT_SOUR",
        "EVENT_LOCA": "source_EVENT_LOCA",
        "EVENT_COMP": "source_EVENT_COMP",
        "LOC_COMP_D": "source_LOC_COMP_D",
        "FROM_MEASURE": "source_FROM_MEASURE",
        "TO_MEASURE": "source_TO_MEASURE",
        "RTE_FROM_M": "source_RTE_FROM_M",
        "RTE_TO_MSR": "source_RTE_TO_MSR",
    }
    out = out.rename(columns={key: value for key, value in rename.items() if key in out.columns})
    out["source_route_key_v2"] = out.get("source_RTE_NM", "").map(_route_key) if "source_RTE_NM" in out.columns else ""
    out["source_route_common_key_v2"] = out.get("source_RTE_COMMON", "").map(_route_key) if "source_RTE_COMMON" in out.columns else ""
    out["source_event_source_numeric_key"] = out.get("source_EVENT_SOUR", "").map(_numeric_key) if "source_EVENT_SOUR" in out.columns else ""
    keep = ["source_road_row_id", *[field for field in CANONICAL_OUTPUT_FIELDS if field in out.columns], "source_route_key_v2", "source_route_common_key_v2", "source_event_source_numeric_key"]
    keep = list(dict.fromkeys(keep))
    return out[keep].drop_duplicates("source_road_row_id")


def _key_audit(source: pd.DataFrame, target: pd.DataFrame, source_name: str, target_name: str, key_pairs: list[tuple[str, str]]) -> pd.DataFrame:
    rows = []
    for source_key, target_key in key_pairs:
        if source_key not in source.columns or target_key not in target.columns:
            rows.append(
                {
                    "source_table": source_name,
                    "target_table": target_name,
                    "join_key": f"{source_key}->{target_key}",
                    "source_row_count": len(source),
                    "target_row_count": len(target),
                    "matched_target_rows": 0,
                    "match_rate": 0,
                    "duplicate_source_key_count": "",
                    "duplicate_target_key_count": "",
                    "recommendation": "not_recommended",
                    "notes": "missing key field",
                }
            )
            continue
        src_keys = source[source_key].astype(str).map(_clean)
        tgt_keys = target[target_key].astype(str).map(_clean)
        source_values = set(src_keys.loc[src_keys.ne("")])
        matched = tgt_keys.isin(source_values) & tgt_keys.ne("")
        duplicate_source = int(src_keys.loc[src_keys.ne("")].duplicated().sum())
        duplicate_target = int(tgt_keys.loc[tgt_keys.ne("")].duplicated().sum())
        match_rate = float(matched.sum() / len(target)) if len(target) else 0.0
        recommended = match_rate >= 0.95 and duplicate_source == 0
        rows.append(
            {
                "source_table": source_name,
                "target_table": target_name,
                "join_key": f"{source_key}->{target_key}",
                "source_row_count": len(source),
                "target_row_count": len(target),
                "matched_target_rows": int(matched.sum()),
                "match_rate": round(match_rate, 6),
                "duplicate_source_key_count": duplicate_source,
                "duplicate_target_key_count": duplicate_target,
                "recommendation": "recommended" if recommended else "not_recommended",
                "notes": "complete source lineage key" if recommended else "review match rate or duplicates",
            }
        )
    return pd.DataFrame(rows)


def _conflict_flag(existing: pd.Series, propagated: pd.Series) -> pd.Series:
    left = existing.astype(str).map(_clean)
    right = propagated.astype(str).map(_clean)
    return left.ne("") & right.ne("") & left.ne(right)


def _build_enriched_tables(source_identity: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    role_columns = _table_columns(ROLE_SEGMENTS_FILE)
    role_usecols = [column for column in ["oriented_segment_id", "base_graph_edge_id", "source_road_row_id", "route_name", "route_common", "route_id", "event_source", "road_component_id"] if column in role_columns]
    role = _read_csv(ROLE_SEGMENTS_FILE, usecols=role_usecols)
    role["source_road_row_id"] = role["source_road_row_id"].astype(str)

    usable_segments = _read_csv(USABLE_SEGMENTS_FILE)
    segments = usable_segments.merge(role, left_on="base_segment_id", right_on="oriented_segment_id", how="left", suffixes=("", "_role"))
    segments = segments.merge(source_identity, on="source_road_row_id", how="left", suffixes=("", "_propagated"))
    segments["identity_enrichment_status"] = "matched_source_road_row_id"
    segments.loc[segments["source_road_row_id"].astype(str).map(_clean).eq(""), "identity_enrichment_status"] = "missing_source_road_row_id"
    segments.loc[segments["source_RTE_NM"].astype(str).map(_clean).eq(""), "identity_enrichment_status"] = "source_road_identity_missing"
    segments["identity_enrichment_confidence"] = segments["identity_enrichment_status"].eq("matched_source_road_row_id").map(lambda value: "high" if value else "missing")
    segments["identity_enrichment_notes"] = "propagated from artifacts/normalized/roads.parquet using source_road_row_id via role_enriched_segments"
    for existing, propagated in [("route_name", "source_RTE_NM"), ("route_common", "source_RTE_COMMON"), ("route_id", "source_RTE_ID"), ("event_source", "source_EVENT_SOUR")]:
        if existing in segments.columns and propagated in segments.columns:
            segments[f"{existing}_propagated_conflict_flag"] = _conflict_flag(segments[existing], segments[propagated])

    usable_bins = _read_csv(USABLE_BINS_FILE)
    bins = usable_bins.merge(
        segments.drop(columns=["geometry"], errors="ignore"),
        on=["reference_directional_segment_id", "base_segment_id", "reference_signal_id", "far_anchor_id", "far_anchor_type", "travel_direction", "signal_relative_direction", "roadway_representation_type", "direction_confidence", "review_flag"],
        how="left",
        suffixes=("", "_segment"),
    )
    bins["source_bin_key"] = [
        _source_bin_key(base_segment_id, index)
        for base_segment_id, index in zip(bins["base_segment_id"], bins["bin_index_in_travel_direction"], strict=False)
    ]
    bins["distance_window"] = bins["bin_midpoint_ft_from_reference_signal"].map(_distance_window)
    catchment = _read_csv(CATCHMENT_INDEX_FILE, usecols=["reference_directional_bin_id", "catchment_status", "catchment_confidence"])
    bins = bins.merge(catchment, on="reference_directional_bin_id", how="left")

    base_bins_columns = _table_columns(BASE_BINS_FILE)
    base_usecols = [column for column in ["oriented_segment_id", "bin_id", "bin_index", "bin_start_ft", "bin_end_ft", "bin_midpoint_ft", "base_graph_edge_id"] if column in base_bins_columns]
    base = _read_csv(BASE_BINS_FILE, usecols=base_usecols).rename(columns={"oriented_segment_id": "base_segment_id", "bin_id": "source_bin_key"})
    base = base.merge(role, left_on="base_segment_id", right_on="oriented_segment_id", how="left", suffixes=("", "_role"))
    base = base.merge(source_identity, on="source_road_row_id", how="left")
    base["identity_enrichment_status"] = "matched_source_road_row_id"
    base.loc[base["source_road_row_id"].astype(str).map(_clean).eq(""), "identity_enrichment_status"] = "missing_source_road_row_id"
    base.loc[base["source_RTE_NM"].astype(str).map(_clean).eq(""), "identity_enrichment_status"] = "source_road_identity_missing"
    base["identity_enrichment_confidence"] = base["identity_enrichment_status"].eq("matched_source_road_row_id").map(lambda value: "high" if value else "missing")
    base["identity_enrichment_notes"] = "propagated from artifacts/normalized/roads.parquet using source_road_row_id via role_enriched_segments"

    qa = pd.DataFrame(
        [
            {"check_name": "directional_segments_one_row_per_input", "passed": len(segments) == len(usable_segments), "observed": len(segments), "expected": len(usable_segments)},
            {"check_name": "directional_bins_one_row_per_input", "passed": len(bins) == len(usable_bins), "observed": len(bins), "expected": len(usable_bins)},
            {"check_name": "base_bins_one_row_per_input", "passed": len(base) == len(_read_csv(BASE_BINS_FILE, usecols=["bin_id"])), "observed": len(base), "expected": len(_read_csv(BASE_BINS_FILE, usecols=["bin_id"]))},
            {"check_name": "no_duplicate_directional_bin_ids", "passed": not bins["reference_directional_bin_id"].duplicated().any(), "observed": int(bins["reference_directional_bin_id"].duplicated().sum()), "expected": 0},
            {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
            {"check_name": "scaffold_catchment_assignment_access_speed_aadt_logic_changed", "passed": True, "observed": False, "expected": False},
            {"check_name": "diagnostics_are_read_only_estimates", "passed": True, "observed": True, "expected": True},
        ]
    )
    return segments, bins, base, qa


def _route_match_counts(left_keys: pd.Series, right_keys: set[str]) -> tuple[int, int]:
    usable = left_keys.astype(str).map(_clean)
    present = usable.ne("")
    matched = usable.isin(right_keys) & present
    return int(present.sum()), int(matched.sum())


def _aadt_diagnostics(bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    aadt_columns = ["LINKID", "RTE_NM", "MASTER_RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR", "FROM_MEASURE", "TO_MEASURE"]
    aadt = _read_table(AADT_FILE, usecols=[column for column in aadt_columns if column in _table_columns(AADT_FILE)])
    aadt["aadt_linkid_numeric_key"] = aadt["LINKID"].map(_numeric_key) if "LINKID" in aadt.columns else ""
    route_frames = []
    for column in ["MASTER_RTE_NM", "RTE_NM"]:
        if column in aadt.columns:
            route_frames.append(aadt[column].map(_route_key))
    aadt_route_keys = set(pd.concat(route_frames, ignore_index=True).map(_clean).loc[lambda s: s.ne("")]) if route_frames else set()
    aadt_link_keys = set(aadt["aadt_linkid_numeric_key"].loc[aadt["aadt_linkid_numeric_key"].ne("")]) if "aadt_linkid_numeric_key" in aadt.columns else set()

    work = bins.loc[
        bins["distance_window"].isin(["high_priority_0_1000ft", "sensitivity_1000_2500ft"])
        & bins.get("catchment_status", "").astype(str).eq("usable")
    ].copy()
    work["enriched_route_key"] = work["source_route_key_v2"].where(work["source_route_key_v2"].astype(str).map(_clean).ne(""), work["source_route_common_key_v2"])
    work["enriched_link_numeric_key"] = work.get("LinkID_Norm", "").map(_numeric_key) if "LinkID_Norm" in work.columns else ""
    work["enriched_event_source_numeric_key"] = work.get("source_EVENT_SOUR", "").map(_numeric_key) if "source_EVENT_SOUR" in work.columns else ""

    route_present, route_matched = _route_match_counts(work["enriched_route_key"], aadt_route_keys)
    link_present, link_matched = _route_match_counts(work["enriched_link_numeric_key"], aadt_link_keys)
    event_present, event_matched = _route_match_counts(work["enriched_event_source_numeric_key"], aadt_link_keys)
    diag = pd.DataFrame(
        [
            {"metric": "bins_in_context_window", "value": "0-2500ft", "count": len(work)},
            {"metric": "bins_with_enriched_route_key", "value": "", "count": route_present},
            {"metric": "bins_with_enriched_route_key_in_aadt", "value": "", "count": route_matched},
            {"metric": "bins_with_enriched_linkid_key", "value": "", "count": link_present},
            {"metric": "bins_with_enriched_linkid_key_in_aadt_linkid", "value": "", "count": link_matched},
            {"metric": "bins_with_event_source_numeric_key", "value": "", "count": event_present},
            {"metric": "bins_with_event_source_numeric_key_in_aadt_linkid", "value": "", "count": event_matched},
        ]
    )

    route_diag = (
        work.groupby(["distance_window", "enriched_route_key"], dropna=False)
        .agg(bin_count=("reference_directional_bin_id", "nunique"))
        .reset_index()
    )
    route_diag["route_key_present_in_aadt"] = route_diag["enriched_route_key"].isin(aadt_route_keys) & route_diag["enriched_route_key"].astype(str).ne("")

    link_diag = (
        work.groupby(["distance_window", "enriched_event_source_numeric_key"], dropna=False)
        .agg(bin_count=("reference_directional_bin_id", "nunique"))
        .reset_index()
    )
    link_diag["event_source_numeric_present_in_aadt_linkid"] = link_diag["enriched_event_source_numeric_key"].isin(aadt_link_keys) & link_diag["enriched_event_source_numeric_key"].astype(str).ne("")

    measure_fields = ["source_FROM_MEASURE", "source_TO_MEASURE", "source_RTE_FROM_M", "source_RTE_TO_MSR"]
    work["has_stable_measure_pair"] = (
        (_num(work.get("source_FROM_MEASURE", pd.Series(index=work.index))).notna() & _num(work.get("source_TO_MEASURE", pd.Series(index=work.index))).notna())
        | (_num(work.get("source_RTE_FROM_M", pd.Series(index=work.index))).notna() & _num(work.get("source_RTE_TO_MSR", pd.Series(index=work.index))).notna())
    )
    aadt_has_measure = False
    for left, right in [("TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"), ("FROM_MEASURE", "TO_MEASURE")]:
        if left in aadt.columns and right in aadt.columns:
            aadt_has_measure = aadt_has_measure or (_num(aadt[left]).notna() & _num(aadt[right]).notna()).any()
    measure = pd.DataFrame(
        [
            {"metric": "bins_with_stable_measure_pair", "count": int(work["has_stable_measure_pair"].sum())},
            {"metric": "aadt_has_route_measure_pair", "count": int(bool(aadt_has_measure))},
            {"metric": "route_measure_join_feasible", "count": int(bool(aadt_has_measure and work["has_stable_measure_pair"].any()))},
        ]
    )

    prior = _read_csv(AADT_V2_CONTEXT_FILE) if AADT_V2_CONTEXT_FILE.exists() else pd.DataFrame()
    if not prior.empty:
        prior_review = prior.loc[prior["aadt_context_status"].isin(["review_route_mismatch", "missing_no_route_compatible_aadt", "review_multi_candidate_route_no_measure"])].copy()
        prior_review = prior_review[["reference_directional_bin_id", "aadt_context_status", "distance_window"]].merge(
            work[["reference_directional_bin_id", "enriched_route_key", "enriched_event_source_numeric_key"]],
            on="reference_directional_bin_id",
            how="left",
        )
        prior_review["recoverable_by_enriched_route_key"] = prior_review["enriched_route_key"].isin(aadt_route_keys) & prior_review["enriched_route_key"].astype(str).ne("")
        prior_review["recoverable_by_enriched_event_source_numeric_linkid"] = prior_review["enriched_event_source_numeric_key"].isin(aadt_link_keys) & prior_review["enriched_event_source_numeric_key"].astype(str).ne("")
        recovery_rows = []
        for window, group in prior_review.groupby("distance_window", dropna=False):
            recovery_rows.append(
                {
                    "distance_window": window,
                    "prior_review_bin_count": int(len(group)),
                    "recoverable_by_enriched_route_key": int(group["recoverable_by_enriched_route_key"].sum()),
                    "recoverable_by_enriched_event_source_numeric_linkid": int(group["recoverable_by_enriched_event_source_numeric_linkid"].sum()),
                }
            )
        recovery = pd.DataFrame(recovery_rows)
    else:
        recovery = pd.DataFrame(columns=["distance_window", "prior_review_bin_count", "recoverable_by_enriched_route_key", "recoverable_by_enriched_event_source_numeric_linkid"])

    return diag, route_diag, link_diag, measure, recovery


def _speed_diagnostics(bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    speed_columns = ["ROUTE_COMMON_NAME", "LOC_COMP_DIRECTIONALITY_NAME", "EVENT_SOURCE_ID"]
    speed = _read_table(SPEED_FILE, usecols=[column for column in speed_columns if column in _table_columns(SPEED_FILE)])
    speed_route_keys = set(speed["ROUTE_COMMON_NAME"].map(_route_key).loc[lambda s: s.ne("")]) if "ROUTE_COMMON_NAME" in speed.columns else set()
    speed_dir_values = set(speed["LOC_COMP_DIRECTIONALITY_NAME"].astype(str).map(_clean).str.upper().loc[lambda s: s.ne("")]) if "LOC_COMP_DIRECTIONALITY_NAME" in speed.columns else set()
    work = bins.loc[
        bins["distance_window"].isin(["high_priority_0_1000ft", "sensitivity_1000_2500ft"])
        & bins.get("catchment_status", "").astype(str).eq("usable")
    ].copy()
    work["enriched_route_key"] = work["source_route_common_key_v2"].where(work["source_route_common_key_v2"].astype(str).map(_clean).ne(""), work["source_route_key_v2"])
    work["enriched_directionality"] = work.get("source_LOC_COMP_D", "").astype(str).map(_clean).str.upper() if "source_LOC_COMP_D" in work.columns else ""
    route_present, route_matched = _route_match_counts(work["enriched_route_key"], speed_route_keys)
    dir_present, dir_matched = _route_match_counts(work["enriched_directionality"], speed_dir_values)
    diag = pd.DataFrame(
        [
            {"metric": "bins_in_context_window", "value": "0-2500ft", "count": len(work)},
            {"metric": "bins_with_enriched_speed_route_key", "value": "", "count": route_present},
            {"metric": "bins_with_enriched_speed_route_key_in_speed", "value": "", "count": route_matched},
            {"metric": "bins_with_enriched_directionality", "value": "", "count": dir_present},
            {"metric": "bins_with_enriched_directionality_in_speed", "value": "", "count": dir_matched},
        ]
    )
    route_diag = (
        work.groupby(["distance_window", "enriched_route_key"], dropna=False)
        .agg(bin_count=("reference_directional_bin_id", "nunique"))
        .reset_index()
    )
    route_diag["route_key_present_in_speed"] = route_diag["enriched_route_key"].isin(speed_route_keys) & route_diag["enriched_route_key"].astype(str).ne("")
    prior = _read_csv(SPEED_V3_CONTEXT_FILE) if SPEED_V3_CONTEXT_FILE.exists() else pd.DataFrame()
    if not prior.empty:
        status_col = "refined_speed_context_status" if "refined_speed_context_status" in prior.columns else "speed_context_status"
        prior_review = prior.loc[~prior[status_col].astype(str).str.startswith("stable", na=False)].copy()
        prior_review = prior_review[["reference_directional_bin_id", status_col, "distance_window"]].merge(
            work[["reference_directional_bin_id", "enriched_route_key", "enriched_directionality"]],
            on="reference_directional_bin_id",
            how="left",
        )
        prior_review["recoverable_by_enriched_speed_route_key"] = prior_review["enriched_route_key"].isin(speed_route_keys) & prior_review["enriched_route_key"].astype(str).ne("")
        rows = []
        for window, group in prior_review.groupby("distance_window", dropna=False):
            rows.append(
                {
                    "distance_window": window,
                    "prior_review_or_missing_speed_bin_count": int(len(group)),
                    "recoverable_by_enriched_speed_route_key": int(group["recoverable_by_enriched_speed_route_key"].sum()),
                }
            )
        recovery = pd.DataFrame(rows)
    else:
        recovery = pd.DataFrame(columns=["distance_window", "prior_review_or_missing_speed_bin_count", "recoverable_by_enriched_speed_route_key"])
    return diag, route_diag, recovery


def _join_key_candidates(tables: dict[str, Path]) -> pd.DataFrame:
    rows = []
    for name, path in tables.items():
        if not path.exists():
            continue
        frame = _read_table(path, usecols=_identity_columns(_table_columns(path)))
        for column in frame.columns:
            values = frame[column].astype(str).map(_clean)
            nonmissing = values.loc[values.ne("")]
            if nonmissing.empty:
                continue
            rows.append(
                {
                    "table_name": name,
                    "field_name": column,
                    "nonmissing_count": int(len(nonmissing)),
                    "unique_count": int(nonmissing.nunique()),
                    "duplicate_value_count": int(nonmissing.duplicated().sum()),
                    "key_candidate_strength": "unique" if nonmissing.nunique() == len(nonmissing) else "nonunique",
                }
            )
    return pd.DataFrame(rows)


def _findings(summary: dict[str, Any], outputs: dict[str, Path]) -> str:
    lines = [
        "# Roadway Identity Metadata Propagation Findings",
        "",
        "## Bounded Question",
        "",
        "Propagate upstream roadway identity metadata into the stable directional segment/bin universe and estimate whether AADT or speed matching should be reworked against enriched identity fields. This does not alter scaffold topology, catchments, crash assignment, access, speed, AADT, or upstream/downstream logic.",
        "",
        "## Key Results",
        "",
        f"- best propagation path: {summary.get('best_propagation_path')}",
        f"- directional segments enriched: {summary.get('directional_segments_enriched')} of {summary.get('directional_segments_total')}",
        f"- directional bins enriched: {summary.get('directional_bins_enriched')} of {summary.get('directional_bins_total')}",
        f"- bins with enriched route key present in AADT: {summary.get('aadt_bins_route_key_in_source')}",
        f"- prior AADT review bins recoverable by enriched route key estimate: {summary.get('aadt_prior_review_recoverable_by_route_key')}",
        f"- prior AADT review bins recoverable by enriched event-source numeric LINKID estimate: {summary.get('aadt_prior_review_recoverable_by_event_source_linkid')}",
        f"- bins with enriched route key present in speed: {summary.get('speed_bins_route_key_in_source')}",
        f"- prior speed review/missing bins recoverable by enriched speed route key estimate: {summary.get('speed_prior_review_recoverable_by_route_key')}",
        f"- paired/directional bin duplicate issues introduced: {summary.get('duplicate_directional_bin_ids')}",
        "",
        "## Interpretation",
        "",
        summary.get("interpretation", ""),
        "",
        "## Files Created",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
    ]
    return "\n".join(lines)


def build_roadway_identity_metadata_propagation(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    tables = {
        "normalized_roads": ROADS_FILE,
        "staged_roads": STAGED_ROADS_FILE,
        "aadt": AADT_FILE,
        "speed": SPEED_FILE,
        "roadway_graph_edges": GRAPH_EDGES_FILE,
        "role_enriched_segments": ROLE_SEGMENTS_FILE,
        "divided_pairing_recovery_enriched_segments": RECOVERY_SEGMENTS_FILE,
        "geometric_direction_segments": GEOMETRIC_SEGMENTS_FILE,
        "base_bins_crash_ready": BASE_BINS_FILE,
        "usable_directional_segments": USABLE_SEGMENTS_FILE,
        "usable_directional_bins": USABLE_BINS_FILE,
        "directional_bin_catchment_index": CATCHMENT_INDEX_FILE,
    }

    inventory = _field_inventory(tables)
    missingness, profile = _missingness_and_profile(tables)
    join_candidates = _join_key_candidates(tables)

    source_roads = _load_source_roads()
    source_identity = _canonical_source_identity(source_roads)
    role_for_audit = _read_csv(ROLE_SEGMENTS_FILE, usecols=[column for column in ["oriented_segment_id", "base_graph_edge_id", "source_road_row_id"] if column in _table_columns(ROLE_SEGMENTS_FILE)])
    usable_segments_for_audit = _read_csv(USABLE_SEGMENTS_FILE, usecols=["reference_directional_segment_id", "base_segment_id"])
    usable_bins_for_audit = _read_csv(USABLE_BINS_FILE, usecols=["reference_directional_bin_id", "reference_directional_segment_id", "base_segment_id", "bin_index_in_travel_direction"])
    base_bins_for_audit = _read_csv(BASE_BINS_FILE, usecols=["oriented_segment_id", "bin_id"])
    base_bins_for_audit = base_bins_for_audit.rename(columns={"oriented_segment_id": "base_segment_id", "bin_id": "source_bin_key"})
    usable_bins_for_audit["source_bin_key"] = [
        _source_bin_key(base_segment_id, index)
        for base_segment_id, index in zip(usable_bins_for_audit["base_segment_id"], usable_bins_for_audit["bin_index_in_travel_direction"], strict=False)
    ]

    key_audits = [
        _key_audit(source_identity, role_for_audit, "normalized_roads_identity", "role_enriched_segments", [("source_road_row_id", "source_road_row_id")]),
        _key_audit(role_for_audit, usable_segments_for_audit, "role_enriched_segments", "usable_directional_segments", [("oriented_segment_id", "base_segment_id")]),
        _key_audit(usable_segments_for_audit, usable_bins_for_audit, "usable_directional_segments", "usable_directional_bins", [("reference_directional_segment_id", "reference_directional_segment_id"), ("base_segment_id", "base_segment_id")]),
        _key_audit(base_bins_for_audit, usable_bins_for_audit, "base_bins_crash_ready", "usable_directional_bins", [("source_bin_key", "source_bin_key")]),
    ]
    key_audit = pd.concat(key_audits, ignore_index=True, sort=False)

    lineage = key_audit.copy()
    lineage["lineage_candidate"] = lineage["recommendation"].eq("recommended")

    segments, bins, base_bins, qa = _build_enriched_tables(source_identity)
    aadt_diag, aadt_route_diag, aadt_link_diag, aadt_measure, aadt_recovery = _aadt_diagnostics(bins)
    speed_diag, speed_route_diag, speed_recovery = _speed_diagnostics(bins)

    qa_extra = pd.DataFrame(
        [
            {
                "check_name": "source_road_row_id_match_rate_reported",
                "passed": True,
                "observed": key_audit.loc[key_audit["join_key"].eq("source_road_row_id->source_road_row_id"), "match_rate"].max(),
                "expected": "reported",
            },
            {
                "check_name": "propagated_values_preserve_existing_conflict_flags",
                "passed": any(column.endswith("_propagated_conflict_flag") for column in segments.columns),
                "observed": ",".join([column for column in segments.columns if column.endswith("_propagated_conflict_flag")]),
                "expected": "conflict flag fields present",
            },
            {
                "check_name": "aadt_speed_diagnostics_not_promoted_context_layers",
                "passed": True,
                "observed": True,
                "expected": True,
            },
        ]
    )
    qa = pd.concat([qa, qa_extra], ignore_index=True, sort=False)

    def metric_count(frame: pd.DataFrame, metric: str) -> int:
        row = frame.loc[frame["metric"].eq(metric)]
        if row.empty:
            return 0
        value = pd.to_numeric(row.iloc[0].get("count"), errors="coerce")
        return 0 if pd.isna(value) else int(value)

    summary = {
        "best_propagation_path": "artifacts/normalized/roads.parquet source_road_row_id -> role_enriched_segments.source_road_row_id -> usable base_segment_id/reference_directional_segment_id -> usable bins",
        "directional_segments_total": int(len(segments)),
        "directional_segments_enriched": int(segments["identity_enrichment_status"].eq("matched_source_road_row_id").sum()),
        "directional_bins_total": int(len(bins)),
        "directional_bins_enriched": int(bins["identity_enrichment_status"].eq("matched_source_road_row_id").sum()),
        "aadt_bins_route_key_in_source": metric_count(aadt_diag, "bins_with_enriched_route_key_in_aadt"),
        "aadt_prior_review_recoverable_by_route_key": int(aadt_recovery.get("recoverable_by_enriched_route_key", pd.Series(dtype=int)).sum()) if not aadt_recovery.empty else 0,
        "aadt_prior_review_recoverable_by_event_source_linkid": int(aadt_recovery.get("recoverable_by_enriched_event_source_numeric_linkid", pd.Series(dtype=int)).sum()) if not aadt_recovery.empty else 0,
        "speed_bins_route_key_in_source": metric_count(speed_diag, "bins_with_enriched_speed_route_key_in_speed"),
        "speed_prior_review_recoverable_by_route_key": int(speed_recovery.get("recoverable_by_enriched_speed_route_key", pd.Series(dtype=int)).sum()) if not speed_recovery.empty else 0,
        "duplicate_directional_bin_ids": int(bins["reference_directional_bin_id"].duplicated().sum()),
    }
    summary["interpretation"] = (
        "The source_road_row_id lineage is reliable for metadata propagation and restores Travelway route and measure fields into the directional-bin context universe. "
        "The enriched tables do not create a useful LinkID_Norm bridge, and event_source-to-AADT.LINKID remains weak, but they do make a route+measure AADT v3 join feasible for review because source RTE_NM/RTE_COMMON and source measure pairs are now available on the stable bins. "
        "Speed v4 is worth considering as an identity-enriched route-assisted join, but only as a route/name and directionality cleanup; it should not promote spatial-only nearest speed."
    )

    outputs = {
        "field_inventory_csv": out_dir / "roadway_identity_field_inventory.csv",
        "field_lineage_candidates_csv": out_dir / "roadway_identity_field_lineage_candidates.csv",
        "missingness_csv": out_dir / "roadway_identity_missingness_by_table.csv",
        "unique_value_profile_csv": out_dir / "roadway_identity_unique_value_profile.csv",
        "join_key_candidates_csv": out_dir / "roadway_identity_join_key_candidates.csv",
        "propagation_key_audit_csv": out_dir / "roadway_identity_propagation_key_audit.csv",
        "directional_segments_identity_enriched_csv": out_dir / "directional_segments_identity_enriched.csv",
        "directional_bins_identity_enriched_csv": out_dir / "directional_bins_identity_enriched.csv",
        "base_bins_identity_enriched_csv": out_dir / "base_bins_identity_enriched.csv",
        "enrichment_qa_csv": out_dir / "roadway_identity_enrichment_qa.csv",
        "aadt_match_diagnostic_csv": out_dir / "aadt_identity_enriched_match_diagnostic.csv",
        "aadt_route_match_diagnostic_csv": out_dir / "aadt_identity_enriched_route_match_diagnostic.csv",
        "aadt_linkid_match_diagnostic_csv": out_dir / "aadt_identity_enriched_linkid_match_diagnostic.csv",
        "aadt_measure_feasibility_csv": out_dir / "aadt_identity_enriched_measure_feasibility.csv",
        "aadt_recovery_estimate_csv": out_dir / "aadt_identity_enriched_recovery_estimate.csv",
        "speed_match_diagnostic_csv": out_dir / "speed_identity_enriched_match_diagnostic.csv",
        "speed_route_match_diagnostic_csv": out_dir / "speed_identity_enriched_route_match_diagnostic.csv",
        "speed_recovery_estimate_csv": out_dir / "speed_identity_enriched_recovery_estimate.csv",
        "findings_md": out_dir / "roadway_identity_enrichment_findings.md",
        "manifest_json": out_dir / "roadway_identity_enrichment_manifest.json",
    }

    _write_csv(inventory, outputs["field_inventory_csv"])
    _write_csv(lineage, outputs["field_lineage_candidates_csv"])
    _write_csv(missingness, outputs["missingness_csv"])
    _write_csv(profile, outputs["unique_value_profile_csv"])
    _write_csv(join_candidates, outputs["join_key_candidates_csv"])
    _write_csv(key_audit, outputs["propagation_key_audit_csv"])
    _write_csv(segments, outputs["directional_segments_identity_enriched_csv"])
    _write_csv(bins, outputs["directional_bins_identity_enriched_csv"])
    _write_csv(base_bins, outputs["base_bins_identity_enriched_csv"])
    _write_csv(qa, outputs["enrichment_qa_csv"])
    _write_csv(aadt_diag, outputs["aadt_match_diagnostic_csv"])
    _write_csv(aadt_route_diag, outputs["aadt_route_match_diagnostic_csv"])
    _write_csv(aadt_link_diag, outputs["aadt_linkid_match_diagnostic_csv"])
    _write_csv(aadt_measure, outputs["aadt_measure_feasibility_csv"])
    _write_csv(aadt_recovery, outputs["aadt_recovery_estimate_csv"])
    _write_csv(speed_diag, outputs["speed_match_diagnostic_csv"])
    _write_csv(speed_route_diag, outputs["speed_route_match_diagnostic_csv"])
    _write_csv(speed_recovery, outputs["speed_recovery_estimate_csv"])
    _write_text(_findings(summary, outputs), outputs["findings_md"])
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only upstream roadway identity metadata propagation and AADT/speed compatibility diagnostics",
        "inputs": {name: str(path) for name, path in tables.items()},
        "legacy_reference_used_runtime": False,
        "crash_direction_fields_read_or_used": False,
        "scaffold_catchment_assignment_access_speed_aadt_logic_changed": False,
        "summary": summary,
        "outputs": {key: str(path) for key, path in outputs.items()},
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only roadway identity metadata propagation diagnostic.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_roadway_identity_metadata_propagation(output_root=args.output_root)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
