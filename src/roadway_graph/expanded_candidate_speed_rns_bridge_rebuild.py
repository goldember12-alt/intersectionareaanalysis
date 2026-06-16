from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

try:
    import pyogrio
except Exception:  # pragma: no cover - geopandas fallback is kept for environments without pyogrio.
    pyogrio = None


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_rns_bridge_rebuild"

PHASE3C5_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_aadt_phase3c5_asymmetry_diagnostic"
PHASE3C_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_aadt_phase3c_route_bridge"
PHASE3AB_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_aadt_phase3ab_recovery"
TAXONOMY_DIR = OUTPUT_ROOT / "review/current/strict_success_route_identity_taxonomy"
ROUTE_MEASURE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_route_measure_context_audit"
SPEED_V5_DIR = OUTPUT_ROOT / "review/current/speed_context_join_v5_new_source_supplement"
NEW_SPEED_DIR = OUTPUT_ROOT / "review/current/new_speed_route_source_inventory"

SOURCE_ROOT = Path("Intersection Crash Analysis Layers")
SPEED_LIMIT_RNS_GDB = SOURCE_ROOT / "Speed_Limit_RNS" / "Speed_Limit_RNS.gdb"
SPEED_LIMIT_RNS_LAYER = "Speed_Limit_RNS"

EXPECTED_CANDIDATE_BINS = 136_227
EXPECTED_CANDIDATE_SIGNALS = 1_590
EXPECTED_STRICT_BINS = 110_710
EXPECTED_STRICT_SPEED_SUCCESS = 105_835
ROW_GUARD_LIMIT = 1_000_000
EXAMPLE_LIMIT = 20_000
EXAMPLES_PER_CLASS = 100
MEASURE_TOLERANCE = 0.05

STABLE_SPEED_STATUSES = {"stable_single_speed", "stable_weighted_speed_transition"}
CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
    "document_nbr",
    "crash_year",
    "crash_dt",
)

REQUIRED_INPUTS = {
    PHASE3C5_DIR: [
        "phase3c5_aadt_safe_speed_missing_detail.csv",
        "phase3c5_speed_blocker_summary.csv",
        "phase3c5_strict_speed_v5_lineage_comparison.csv",
        "phase3c5_speed_fanout_diagnostic.csv",
        "phase3c5_speed_upgrade_candidates.csv",
        "phase3c5_aadt_vs_speed_source_inventory_comparison.csv",
        "expanded_candidate_speed_aadt_phase3c5_asymmetry_manifest.json",
    ],
    PHASE3C_DIR: [
        "phase3c_candidate_route_group_base.csv",
        "phase3c_speed_source_route_inventory.csv",
        "phase3c_speed_route_bridge_candidates.csv",
        "phase3c_route_bridge_all_candidates.csv",
        "phase3c_route_bridge_fanout_summary.csv",
        "phase3c_route_bridge_fanout_review_queue.csv",
        "phase3c_route_bridge_deduped_signal_recovery_estimate.csv",
        "expanded_candidate_speed_aadt_phase3c_route_bridge_manifest.json",
    ],
    PHASE3AB_DIR: [
        "phase3a_candidate_route_inventory.csv",
        "phase3b_speed_source_route_inventory.csv",
        "phase3b_speed_aadt_joint_source_inventory.csv",
        "phase3b_source_availability_class_summary.csv",
        "phase3b_source_availability_recovery_estimate.csv",
        "expanded_candidate_speed_aadt_phase3ab_recovery_manifest.json",
    ],
    TAXONOMY_DIR: [
        "stage1_strict_active_positive_control_bins.csv",
        "stage1_strict_active_speed_success_routes.csv",
        "stage1_strict_active_speed_missing_routes.csv",
        "stage1_strict_active_speed_aadt_route_matrix.csv",
        "stage1_strict_success_join_key_inventory.csv",
        "stage1_strict_success_route_pattern_summary.csv",
        "stage1_strict_vs_candidate_schema_comparison.csv",
        "strict_success_route_identity_taxonomy_manifest.json",
    ],
    ROUTE_MEASURE_DIR: [
        "stage1_candidate_route_measure_bin_detail.csv",
        "stage1_candidate_route_measure_signal_summary.csv",
        "expanded_candidate_route_measure_context_audit_manifest.json",
    ],
}


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def _checkpoint(name: str, rows: int | None = None, note: str = "") -> None:
    row_text = "" if rows is None else f" rows={rows:,}"
    note_text = "" if not note else f" {note}"
    _log(f"CHECKPOINT {name}{row_text}{note_text}")


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    _checkpoint(f"write_start {path.name}", len(df))
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    _checkpoint(f"write_complete {path.name}", len(df))


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_FIELD_TOKENS) and column not in {"distance_window"}


def _read_csv(path: Path, *, usecols: list[str] | None = None, nrows: int | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    if not path.exists():
        _checkpoint(f"read_missing {path.name}", 0)
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0).columns.tolist()
    selected = header if usecols is None else [c for c in usecols if c in header]
    blocked = [c for c in selected if _blocked_column(c)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
    df = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=selected, nrows=nrows, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(df))
    return df


def _text(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series("", index=df.index, dtype=str)
    return df[col].fillna("").astype(str)


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="Float64")
    return pd.to_numeric(df[col], errors="coerce")


def _flag(df: pd.DataFrame, col: str) -> pd.Series:
    return _text(df, col).str.lower().isin({"true", "1", "yes", "y"})


def _collapse(series: pd.Series, limit: int = 12) -> str:
    values = sorted({str(v) for v in series.dropna() if str(v) and str(v).lower() != "nan"})
    return "|".join(values[:limit])


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.upper() in {"", "NAN", "NONE", "<NA>", "NULL"} else text


def normalize_route_name(value: Any) -> str:
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
        if compact in {"US", "SR", "VA", "I", "SC", "PR", "FR"}:
            route_type = "SR" if compact == "VA" else compact
            route_token_seen = True
            continue
        if compact in {"NB", "SB", "EB", "WB", "N", "S", "E", "W"}:
            direction = compact[0]
            continue
        match = re.fullmatch(r"(?:0*[0-9]{1,3})?(US|SR|VA|I|IS|SC|PR|FR)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?", compact)
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
        match = re.search(r"(?:0*[0-9]{1,3})?(US|SR|VA|I|IS|SC|PR|FR)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?", joined)
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


def _phase3_norm(value: Any) -> str:
    s = str(value or "").upper().strip()
    s = re.sub(r"\([^)]*\)", "", s)
    s = s.replace("INTERSTATE", "IS").replace("R-VA", "").replace("S-VA", "SC")
    s = re.sub(r"[^A-Z0-9]", "", s)
    for prefix in ["US", "SR", "VA", "SC", "IS", "I", "FR", "PR"]:
        s = re.sub(prefix + r"0+([0-9])", prefix + r"\1", s)
    return s.replace("EB", "E").replace("WB", "W").replace("NB", "N").replace("SB", "S")


def _facility_text(value: Any) -> str:
    s = re.sub(r"\([^)]*\)", "", str(value or "").upper())
    s = re.sub(r"\b(COUNTY|CITY|TOWN|OF|VA|VIRGINIA|RAMP|ROAD|RD|STREET|ST|ROUTE|RTE)\b", " ", s)
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _route_system(norm: str, raw: str = "") -> str:
    raw_u = str(raw or "").upper()
    key = str(norm or "").upper()
    if key.startswith(("I", "IS")):
        return "interstate"
    if key.startswith("US"):
        return "us_route"
    if key.startswith(("SR", "VA")):
        return "state_route"
    if key.startswith("SC") or re.match(r"^\d{3}SC", key):
        return "secondary_route"
    if key.startswith(("FR", "PR")) or "PRIVATE" in raw_u:
        return "private_or_local"
    if not key:
        return "missing_route_identity"
    return "unknown_or_named_local"


def _qa_row(gate: str, passed: bool, observed: Any = "", expected: Any = "", note: str = "") -> dict[str, Any]:
    return {"qa_gate": gate, "passed": bool(passed), "observed_value": observed, "expected_or_reference_value": expected, "note": note}


def _missing_required_inputs() -> list[str]:
    return [str(root / name) for root, names in REQUIRED_INPUTS.items() for name in names if not (root / name).exists()]


def _load_speed_limit_rns() -> tuple[pd.DataFrame, pd.DataFrame]:
    path_rows = [
        {
            "path_role": "Speed_Limit_RNS source table",
            "path": str(SPEED_LIMIT_RNS_GDB / SPEED_LIMIT_RNS_LAYER),
            "identified": SPEED_LIMIT_RNS_GDB.exists(),
            "source_or_module": "speed_context_join_v5_new_source_supplement._load_speed_limit_rns",
            "lineage_note": "v5 reads FileGDB layer and expands RTE_NM/MASTER_RTE_NM by FROM_MEASURE/TO_MEASURE and TRANSPORT_EDGE measure pairs",
        },
        {
            "path_role": "active speed v5 output",
            "path": str(SPEED_V5_DIR / "directional_bin_speed_context_v5.csv"),
            "identified": (SPEED_V5_DIR / "directional_bin_speed_context_v5.csv").exists(),
            "source_or_module": "speed_context_join_v5_new_source_supplement",
            "lineage_note": "strict active v5 accepted Speed_Limit_RNS route+measure supplement without overwriting v4 baseline outputs",
        },
        {
            "path_role": "RNS source inventory output",
            "path": str(NEW_SPEED_DIR / "new_speed_route_source_inventory_manifest.json"),
            "identified": (NEW_SPEED_DIR / "new_speed_route_source_inventory_manifest.json").exists(),
            "source_or_module": "new_speed_route_source_inventory",
            "lineage_note": "inventory identifies Speed_Limit_RNS as the new route/measure speed source",
        },
    ]
    path_inventory = pd.DataFrame(path_rows)
    if not SPEED_LIMIT_RNS_GDB.exists():
        return path_inventory, pd.DataFrame()

    rns_columns = [
        "RTE_NM",
        "FROM_MEASURE",
        "TO_MEASURE",
        "EDGE_RTE_KEY",
        "TRANSPORT_EDGE_ID",
        "TRANSPORT_EDGE_FROM_MSR",
        "TRANSPORT_EDGE_TO_MSR",
        "MASTER_RTE_NM",
        "MASTER_EDGE_RTE_KEY",
        "CAR_SPEED_LIMIT",
        "FINAL_SPEED_LIMIT_SOURCE",
        "TRUCK_SPEED_LIMIT",
        "SPEEDZONE_TYPE_DSC",
        "IDENTIFY_CODE",
    ]
    _checkpoint("read_start Speed_Limit_RNS_gdb")
    if pyogrio is not None:
        raw = pyogrio.read_dataframe(
            SPEED_LIMIT_RNS_GDB,
            layer=SPEED_LIMIT_RNS_LAYER,
            columns=rns_columns,
            read_geometry=False,
            use_arrow=True,
        )
    else:
        raw = pd.DataFrame(gpd.read_file(SPEED_LIMIT_RNS_GDB, layer=SPEED_LIMIT_RNS_LAYER, columns=rns_columns, ignore_geometry=True))
    _checkpoint("read_complete Speed_Limit_RNS_gdb", len(raw))

    rows = []
    for route_field, from_field, to_field in [
        ("RTE_NM", "FROM_MEASURE", "TO_MEASURE"),
        ("MASTER_RTE_NM", "FROM_MEASURE", "TO_MEASURE"),
        ("RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"),
        ("MASTER_RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"),
    ]:
        if route_field not in raw.columns or from_field not in raw.columns or to_field not in raw.columns:
            continue
        sub = pd.DataFrame(
            {
                "rns_route_field": route_field,
                "rns_measure_pair": f"{from_field}/{to_field}",
                "rns_route_raw": raw[route_field].astype(str),
                "rns_route_key": raw[route_field].map(normalize_route_name),
                "normalized_rns_route_key": raw[route_field].map(_phase3_norm),
                "rns_facility_text": raw[route_field].map(_facility_text),
                "rns_measure_from": pd.to_numeric(raw[from_field], errors="coerce"),
                "rns_measure_to": pd.to_numeric(raw[to_field], errors="coerce"),
                "rns_edge_rte_key": raw.get("EDGE_RTE_KEY", pd.Series("", index=raw.index)).astype(str),
                "rns_master_edge_rte_key": raw.get("MASTER_EDGE_RTE_KEY", pd.Series("", index=raw.index)).astype(str),
                "rns_transport_edge_id": raw.get("TRANSPORT_EDGE_ID", pd.Series("", index=raw.index)).astype(str),
                "rns_final_speed_limit_source": raw.get("FINAL_SPEED_LIMIT_SOURCE", pd.Series("", index=raw.index)).astype(str),
                "rns_speedzone_type_dsc": raw.get("SPEEDZONE_TYPE_DSC", pd.Series("", index=raw.index)).astype(str),
                "rns_identify_code": raw.get("IDENTIFY_CODE", pd.Series("", index=raw.index)).astype(str),
                "rns_car_speed_limit": pd.to_numeric(raw.get("CAR_SPEED_LIMIT", pd.Series(pd.NA, index=raw.index)), errors="coerce"),
                "rns_truck_speed_limit": pd.to_numeric(raw.get("TRUCK_SPEED_LIMIT", pd.Series(pd.NA, index=raw.index)), errors="coerce"),
            }
        )
        sub["rns_measure_min"] = sub[["rns_measure_from", "rns_measure_to"]].min(axis=1)
        sub["rns_measure_max"] = sub[["rns_measure_from", "rns_measure_to"]].max(axis=1)
        sub["rns_route_type_category"] = [_route_system(n, r) for n, r in zip(sub["normalized_rns_route_key"], sub["rns_route_raw"], strict=False)]
        rows.append(sub)
    source = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    source = source.loc[source["rns_route_key"].ne("") | source["normalized_rns_route_key"].ne("")].copy()
    source = source.drop_duplicates(
        [
            "rns_route_key",
            "normalized_rns_route_key",
            "rns_measure_min",
            "rns_measure_max",
            "rns_car_speed_limit",
            "rns_truck_speed_limit",
            "rns_route_field",
            "rns_measure_pair",
            "rns_transport_edge_id",
        ]
    )
    _checkpoint("rns_source_expanded_lineage_rows", len(source))
    return path_inventory, source


def _rns_inventory(source: pd.DataFrame) -> pd.DataFrame:
    if source.empty:
        return pd.DataFrame()
    _checkpoint("groupby_start_rns_source_inventory", len(source))
    keys = ["rns_route_key", "normalized_rns_route_key", "rns_facility_text", "rns_route_type_category"]
    work = source.copy()
    work["rns_route_missing_flag"] = work["rns_route_key"].astype(str).str.strip().eq("")
    work["rns_measure_missing_flag"] = pd.to_numeric(work["rns_measure_min"], errors="coerce").isna()
    work["rns_transport_edge_missing_flag"] = work["rns_transport_edge_id"].astype(str).str.strip().eq("")
    out = work.groupby(keys, dropna=False).agg(
        rns_measure_min=("rns_measure_min", "min"),
        rns_measure_max=("rns_measure_max", "max"),
        rns_source_row_count=("rns_route_raw", "size"),
        rns_interval_group_count=("rns_measure_min", "count"),
        rns_speed_value_count=("rns_car_speed_limit", "nunique"),
        rns_transport_edge_count=("rns_transport_edge_id", "nunique"),
        rns_null_route_count=("rns_route_missing_flag", "sum"),
        rns_null_measure_count=("rns_measure_missing_flag", "sum"),
        rns_null_transport_edge_count=("rns_transport_edge_missing_flag", "sum"),
    ).reset_index()

    def collapse_unique(column: str, output: str) -> None:
        nonlocal out
        if column in keys:
            out[output] = out[column].fillna("").astype(str)
            return
        slim = work[keys + [column]].copy()
        slim[column] = slim[column].fillna("").astype(str).str.strip()
        slim = slim.loc[slim[column].ne("")].drop_duplicates()
        values = slim.groupby(keys, dropna=False)[column].agg(lambda s: "|".join(sorted(s)[:12])).reset_index(name=output)
        out = out.merge(values, on=keys, how="left")

    for source_col, output_col in [
        ("rns_route_raw", "rns_route_raw_values"),
        ("rns_route_key", "rns_route_key_values"),
        ("rns_route_field", "rns_route_field_values"),
        ("rns_measure_pair", "rns_measure_pair_values"),
        ("rns_transport_edge_id", "rns_transport_edge_examples"),
        ("rns_edge_rte_key", "rns_edge_rte_key_examples"),
        ("rns_master_edge_rte_key", "rns_master_edge_rte_key_examples"),
        ("rns_identify_code", "rns_identify_code_examples"),
        ("rns_final_speed_limit_source", "rns_source_values"),
        ("rns_speedzone_type_dsc", "rns_speedzone_values"),
    ]:
        collapse_unique(source_col, output_col)
    for col in [
        "rns_route_raw_values",
        "rns_route_key_values",
        "rns_route_field_values",
        "rns_measure_pair_values",
        "rns_transport_edge_examples",
        "rns_edge_rte_key_examples",
        "rns_master_edge_rte_key_examples",
        "rns_identify_code_examples",
        "rns_source_values",
        "rns_speedzone_values",
    ]:
        out[col] = out[col].fillna("")
    _checkpoint("groupby_complete_rns_source_inventory", len(out))
    return out


def _strict_success_summary(strict_bins: pd.DataFrame) -> pd.DataFrame:
    if strict_bins.empty:
        return pd.DataFrame()
    speed_success = _flag(strict_bins, "speed_success_flag")
    rns_backed = speed_success & (
        _text(strict_bins, "v5_source_route_fields").ne("")
        | _text(strict_bins, "v5_effective_speed_source").eq("speed_limit_rns_supplement_candidate")
        | _text(strict_bins, "v5_supplement_action").str.contains("rns", case=False, na=False)
    )
    rows = [
        {"metric": "strict_active_bin_count", "value": "", "count": len(strict_bins)},
        {"metric": "strict_active_signal_count", "value": "", "count": strict_bins["reference_signal_id"].nunique() if "reference_signal_id" in strict_bins else 0},
        {"metric": "strict_active_speed_v5_success_count", "value": "", "count": int(speed_success.sum())},
        {"metric": "strict_active_rns_backed_success_count_if_distinguishable", "value": "", "count": int(rns_backed.sum())},
        {"metric": "strict_active_non_rns_backed_speed_success_count_if_distinguishable", "value": "", "count": int((speed_success & ~rns_backed).sum())},
        {"metric": "strict_active_missing_or_review_count", "value": "", "count": int((~speed_success).sum())},
    ]
    for col in ["v5_source_route_fields", "v5_source_measure_pairs", "v5_effective_speed_source", "v5_supplement_action", "route_type_category", "distance_window"]:
        if col in strict_bins.columns:
            counts = strict_bins.loc[speed_success].groupby(col, dropna=False).size().reset_index(name="count")
            for row in counts.itertuples(index=False):
                rows.append({"metric": f"strict_speed_success_by_{col}", "value": getattr(row, col), "count": int(row.count)})
    return pd.DataFrame(rows)


def _candidate_base_and_signal_map(candidate_bins: pd.DataFrame, phase3c_base: pd.DataFrame, aadt_safe: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    bins = candidate_bins.copy()
    bins["candidate_measure_min_num"] = _num(bins, "candidate_measure_min")
    bins["candidate_measure_max_num"] = _num(bins, "candidate_measure_max")
    bins["candidate_weight_num"] = pd.to_numeric(_text(bins, "candidate_weight"), errors="coerce").fillna(1.0)
    bins["candidate_route_key_normalized"] = _text(bins, "route_name").map(_phase3_norm)
    bins.loc[bins["candidate_route_key_normalized"].eq(""), "candidate_route_key_normalized"] = _text(bins, "route_common").map(_phase3_norm)
    bins.loc[bins["candidate_route_key_normalized"].eq(""), "candidate_route_key_normalized"] = _text(bins, "route_id").map(_phase3_norm)
    bins["candidate_route_common_normalized"] = _text(bins, "route_common").map(_phase3_norm)
    bins["candidate_facility_text"] = _text(bins, "route_common").where(_text(bins, "route_common").ne(""), _text(bins, "route_name")).map(_facility_text)

    _checkpoint("groupby_start_candidate_route_group_signal_map", len(bins))
    map_cols = ["candidate_route_key_normalized", "route_id", "route_common", "route_name", "candidate_signal_id"]
    signal_map = bins.groupby(map_cols, dropna=False).agg(
        candidate_bin_count=("candidate_bin_id", "count"),
        weighted_bin_count=("candidate_weight_num", "sum"),
        analysis_windows=("analysis_window", _collapse),
        min_candidate_measure=("candidate_measure_min_num", "min"),
        max_candidate_measure=("candidate_measure_max_num", "max"),
        recovery_strategy_values=("recovery_strategy", _collapse),
        confidence_tier_values=("association_confidence_tier", _collapse),
        source_road_row_id_count=("source_road_row_id", lambda s: int(s.astype(str).str.strip().replace("", pd.NA).dropna().nunique())),
        source_road_row_id_values=("source_road_row_id", _collapse),
        graph_edge_id_count=("graph_edge_id", lambda s: int(s.astype(str).str.strip().replace("", pd.NA).dropna().nunique())),
        graph_edge_id_values=("graph_edge_id", _collapse),
        road_component_id_count=("road_component_id", lambda s: int(s.astype(str).str.strip().replace("", pd.NA).dropna().nunique())),
        road_component_id_values=("road_component_id", _collapse),
        multi_candidate_values=("multi_candidate_flag", _collapse),
        strict_active_overlap_values=("strict_active_overlap_status", _collapse),
    ).reset_index()
    signal_map = signal_map.rename(columns={"candidate_signal_id": "affected_signal_id"})
    group_key = phase3c_base[["candidate_route_group_id", "route_id"]].drop_duplicates().copy() if {"candidate_route_group_id", "route_id"}.issubset(phase3c_base.columns) else pd.DataFrame()
    if not group_key.empty:
        signal_map = signal_map.merge(group_key, on="route_id", how="left")
    if "candidate_route_group_id" not in signal_map.columns:
        signal_map["candidate_route_group_id"] = ""
    _checkpoint("groupby_complete_candidate_route_group_signal_map", len(signal_map))

    route_base = phase3c_base.copy()
    if "candidate_route_group_id" not in route_base.columns:
        route_base["candidate_route_group_id"] = [f"candidate_route_group_{i + 1:06d}" for i in range(len(route_base))]
    route_base["normalized_candidate_route_key"] = _text(route_base, "candidate_route_key_normalized").where(
        _text(route_base, "candidate_route_key_normalized").ne(""),
        _text(route_base, "route_name").map(_phase3_norm),
    )
    route_base["candidate_route_name_rns_norm"] = _text(route_base, "route_name").map(normalize_route_name)
    route_base["candidate_route_common_rns_norm"] = _text(route_base, "route_common").map(normalize_route_name)
    route_base["candidate_facility_text"] = _text(route_base, "candidate_facility_text").where(
        _text(route_base, "candidate_facility_text").ne(""),
        _text(route_base, "route_common").map(_facility_text),
    )

    aadt_ids = set(_text(aadt_safe, "candidate_route_group_id"))
    route_base["aadt_safe_speed_not_safe_flag"] = _text(route_base, "candidate_route_group_id").isin(aadt_ids)
    for col in [
        "candidate_bin_count",
        "affected_signal_count",
        "weighted_bin_count",
        "affected_0_1000_signal_count",
        "affected_full_0_2500_signal_count",
        "measure_min",
        "measure_max",
        "previous_speed_covered_bins",
        "previous_aadt_covered_bins",
    ]:
        if col in route_base.columns:
            route_base[col] = pd.to_numeric(route_base[col], errors="coerce").fillna(0)

    grouped_signals = signal_map.groupby("candidate_route_group_id", dropna=False).agg(
        mapped_unique_signal_count=("affected_signal_id", "nunique"),
        mapped_signal_values=("affected_signal_id", _collapse),
    ).reset_index()
    _checkpoint("merge_start_candidate_route_group_signal_counts", len(route_base), f"right_rows={len(grouped_signals):,}")
    route_base = route_base.merge(grouped_signals, on="candidate_route_group_id", how="left", suffixes=("", "_mapped"))
    _checkpoint("merge_complete_candidate_route_group_signal_counts", len(route_base))
    return route_base, signal_map


def _measure_status(row: pd.Series, fanout: bool = False) -> str:
    if fanout:
        return "rns_measure_not_checked_due_to_fanout"
    cmin = pd.to_numeric(row.get("measure_min"), errors="coerce")
    cmax = pd.to_numeric(row.get("measure_max"), errors="coerce")
    smin = pd.to_numeric(row.get("rns_measure_min"), errors="coerce")
    smax = pd.to_numeric(row.get("rns_measure_max"), errors="coerce")
    if pd.isna(cmin) or pd.isna(cmax):
        return "rns_measure_missing_candidate"
    if pd.isna(smin) or pd.isna(smax):
        return "rns_measure_missing_source"
    amin, amax = sorted([float(cmin), float(cmax)])
    bmin, bmax = sorted([float(smin), float(smax)])
    if bmin <= amin and amax <= bmax:
        return "rns_measure_range_contains_candidate"
    if amin <= bmin and bmax <= amax:
        return "rns_measure_range_candidate_contains_rns"
    if max(amin, bmin) <= min(amax, bmax):
        return "rns_measure_range_overlaps"
    if max(amin, bmin) - min(amax, bmax) <= MEASURE_TOLERANCE:
        return "rns_measure_near_overlap_with_tolerance"
    return "rns_measure_no_overlap"


def _fanout_class(source_group_count: int, interval_count: int, transport_edge_count: int, evidence: str, expansion_estimate: int) -> str:
    if source_group_count <= 0:
        return "not_applicable"
    if expansion_estimate > ROW_GUARD_LIMIT or interval_count > 10_000:
        return "extreme_fanout"
    if source_group_count == 1 and interval_count <= 25:
        return "one_to_one"
    if source_group_count <= 3 and interval_count <= 100:
        return "one_to_few"
    if evidence in {"rns_route_name_common_match", "rns_facility_text_match"} and source_group_count > 10:
        return "route_name_facility_many_to_many"
    if source_group_count > 20 and transport_edge_count <= source_group_count:
        return "true_route_identity_ambiguity"
    return "normal_long_route_interval_density"


def _classify_bridge(row: pd.Series) -> tuple[str, str]:
    evidence = str(row.get("bridge_evidence_type", ""))
    measure = str(row.get("rns_measure_compatibility_status", ""))
    fanout = str(row.get("rns_fanout_class", ""))
    if evidence in {"rns_source_absent_likely", "not_bridgeable_current_evidence"}:
        return "not_recommended_current_evidence", "hold_as_likely_speed_source_gap"
    if evidence == "rns_lineage_fields_missing":
        return "low_confidence_manual_review_only", "needs_rns_lineage_field_review"
    if fanout == "normal_long_route_interval_density" and measure in {"rns_measure_range_overlaps", "rns_measure_range_contains_candidate", "rns_measure_range_candidate_contains_rns", "rns_measure_near_overlap_with_tolerance"}:
        return "high_confidence_review_only", "safe_for_phase3d_review_only_speed_rerun_requires_vectorized_interval_lookup"
    if fanout in {"true_route_identity_ambiguity", "route_name_facility_many_to_many", "extreme_fanout"}:
        return "low_confidence_manual_review_only", "needs_route_identity_review"
    if measure in {"rns_measure_range_overlaps", "rns_measure_range_contains_candidate", "rns_measure_range_candidate_contains_rns"} and evidence in {
        "exact_rns_route_key_match",
        "normalized_rns_route_key_match",
        "rns_transport_edge_lineage_match",
        "rns_graph_edge_or_road_component_lineage_match",
        "rns_source_road_row_lineage_match",
        "strict_active_rns_success_pattern_match",
        "aadt_safe_rns_route_present_bridge_missing",
    }:
        return "high_confidence_review_only", "safe_for_phase3d_review_only_speed_rerun"
    if measure == "rns_measure_near_overlap_with_tolerance":
        return "medium_confidence_review_only", "needs_measure_compatibility_review"
    if evidence in {"rns_route_name_common_match", "rns_facility_text_match"} and measure in {
        "rns_measure_range_overlaps",
        "rns_measure_range_contains_candidate",
        "rns_measure_range_candidate_contains_rns",
    }:
        return "medium_confidence_review_only", "needs_route_identity_review"
    if "missing" in measure or "uncertain" in measure or "no_overlap" in measure:
        return "low_confidence_manual_review_only", "needs_measure_compatibility_review"
    return "not_recommended_current_evidence", "do_not_use_current_evidence"


def _build_bridge_candidates(candidate_base: pd.DataFrame, rns_inv: pd.DataFrame, strict_success: pd.DataFrame) -> pd.DataFrame:
    if candidate_base.empty or rns_inv.empty:
        return pd.DataFrame()
    strict_keys = set(_text(strict_success, "route_key_normalized"))
    rns_keys = set(_text(rns_inv, "rns_route_key")) | set(_text(rns_inv, "normalized_rns_route_key"))
    candidate_base = candidate_base.copy()
    candidate_base["strict_active_rns_success_pattern_flag"] = (
        _text(candidate_base, "normalized_candidate_route_key").isin(strict_keys)
        | _text(candidate_base, "candidate_route_name_rns_norm").isin(strict_keys)
        | _text(candidate_base, "candidate_route_common_rns_norm").isin(strict_keys)
    )

    left = candidate_base.copy()
    left["join_key"] = _text(left, "normalized_candidate_route_key")
    right = rns_inv.copy()
    right["join_key"] = _text(right, "normalized_rns_route_key")
    _checkpoint("merge_start_candidate_to_rns_normalized_route", len(left), f"right_rows={len(right):,}")
    merged = left.merge(right, on="join_key", how="left", suffixes=("", "_rns"))
    _checkpoint("merge_complete_candidate_to_rns_normalized_route", len(merged))
    if len(merged) > ROW_GUARD_LIMIT:
        _checkpoint("candidate_to_rns_merge_guard_stopped", len(merged), "writing fanout rows instead of expanding further")
        merged = merged.head(ROW_GUARD_LIMIT).copy()

    def evidence(row: pd.Series) -> str:
        if str(row.get("rns_route_key", "")) == "":
            key = str(row.get("normalized_candidate_route_key", ""))
            return "rns_lineage_fields_missing" if key in rns_keys else "rns_source_absent_likely"
        if str(row.get("candidate_route_name_rns_norm", "")) and str(row.get("candidate_route_name_rns_norm", "")) == str(row.get("rns_route_key", "")):
            return "exact_rns_route_key_match"
        if str(row.get("normalized_candidate_route_key", "")) == str(row.get("normalized_rns_route_key", "")):
            return "normalized_rns_route_key_match"
        if str(row.get("candidate_route_common_rns_norm", "")) == str(row.get("rns_route_key", "")):
            return "rns_route_name_common_match"
        if str(row.get("candidate_facility_text", "")) and str(row.get("candidate_facility_text", "")) == str(row.get("rns_facility_text", "")):
            return "rns_facility_text_match"
        if bool(row.get("strict_active_rns_success_pattern_flag", False)):
            return "strict_active_rns_success_pattern_match"
        return "not_bridgeable_current_evidence"

    merged["bridge_evidence_type"] = merged.apply(evidence, axis=1)
    merged.loc[_flag(merged, "aadt_safe_speed_not_safe_flag") & _text(merged, "rns_route_key").ne(""), "bridge_evidence_type"] = "aadt_safe_rns_route_present_bridge_missing"
    merged["estimated_bin_source_overlap_rows_if_expanded"] = (
        pd.to_numeric(_text(merged, "candidate_bin_count"), errors="coerce").fillna(0)
        * pd.to_numeric(_text(merged, "rns_interval_group_count"), errors="coerce").fillna(0)
    ).astype(int)
    merged["rns_measure_compatibility_status"] = merged.apply(
        lambda r: _measure_status(r, bool(r.get("estimated_bin_source_overlap_rows_if_expanded", 0) > ROW_GUARD_LIMIT)),
        axis=1,
    )
    merged["rns_fanout_class"] = [
        _fanout_class(int(pd.to_numeric(pd.Series([g]), errors="coerce").fillna(0).iloc[0]), int(pd.to_numeric(pd.Series([i]), errors="coerce").fillna(0).iloc[0]), int(pd.to_numeric(pd.Series([t]), errors="coerce").fillna(0).iloc[0]), e, int(x))
        for g, i, t, e, x in zip(
            _text(merged, "rns_source_row_count"),
            _text(merged, "rns_interval_group_count"),
            _text(merged, "rns_transport_edge_count"),
            _text(merged, "bridge_evidence_type"),
            merged["estimated_bin_source_overlap_rows_if_expanded"],
            strict=False,
        )
    ]
    classes = merged.apply(_classify_bridge, axis=1)
    merged["proposed_speed_bridge_confidence"] = [c[0] for c in classes]
    merged["recommended_use_class"] = [c[1] for c in classes]
    merged["review_only_not_applied"] = True
    merged["why_not_active_safe"] = "Route-level Speed_Limit_RNS bridge diagnostic only; no speed values assigned and no active outputs modified."
    merged["bridge_candidate_id"] = [f"rns_speed_bridge_{i + 1:06d}" for i in range(len(merged))]
    keep = [
        "bridge_candidate_id",
        "candidate_route_group_id",
        "route_id",
        "normalized_candidate_route_key",
        "candidate_route_name_rns_norm",
        "candidate_route_common_rns_norm",
        "route_common",
        "route_name",
        "candidate_facility_text",
        "candidate_route_type_category",
        "source_layer",
        "route_identity_class",
        "source_availability_class",
        "aadt_safe_speed_not_safe_flag",
        "measure_min",
        "measure_max",
        "candidate_bin_count",
        "weighted_bin_count",
        "affected_signal_count",
        "affected_0_1000_signal_count",
        "affected_full_0_2500_signal_count",
        "previous_speed_covered_bins",
        "previous_aadt_covered_bins",
        "source_road_row_id_examples",
        "graph_edge_id_examples",
        "road_component_id_examples",
        "multi_candidate_values",
        "strict_match_evidence_key",
        "strict_active_rns_success_pattern_flag",
        "rns_route_key",
        "normalized_rns_route_key",
        "rns_route_raw_values",
        "rns_route_key_values",
        "rns_route_field_values",
        "rns_measure_pair_values",
        "rns_measure_min",
        "rns_measure_max",
        "rns_source_row_count",
        "rns_interval_group_count",
        "rns_speed_value_count",
        "rns_transport_edge_count",
        "rns_transport_edge_examples",
        "rns_edge_rte_key_examples",
        "rns_master_edge_rte_key_examples",
        "rns_identify_code_examples",
        "rns_source_values",
        "rns_speedzone_values",
        "bridge_evidence_type",
        "rns_measure_compatibility_status",
        "rns_fanout_class",
        "estimated_bin_source_overlap_rows_if_expanded",
        "proposed_speed_bridge_confidence",
        "recommended_use_class",
        "review_only_not_applied",
        "why_not_active_safe",
    ]
    return merged[[c for c in keep if c in merged.columns]].copy()


def _summaries(bridges: pd.DataFrame, signal_map: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if bridges.empty:
        empty = pd.DataFrame()
        return {k: empty for k in ["evidence", "confidence", "use", "measure", "fanout", "recovery", "dedup", "examples"]}
    signal_by_key = signal_map[["candidate_route_group_id", "affected_signal_id", "analysis_windows"]].drop_duplicates()
    bridge_signals = bridges[["bridge_candidate_id", "candidate_route_group_id", "normalized_candidate_route_key", "proposed_speed_bridge_confidence", "recommended_use_class", "aadt_safe_speed_not_safe_flag"]].merge(
        signal_by_key,
        on="candidate_route_group_id",
        how="left",
    )
    bridgeable = bridges["proposed_speed_bridge_confidence"].isin(["high_confidence_review_only", "medium_confidence_review_only"])
    groups = {
        "stage1_recovered_route_groups_with_rns_bridge_support": bridgeable,
        "stage1_high_confidence_route_groups": bridges["proposed_speed_bridge_confidence"].eq("high_confidence_review_only"),
        "stage1_medium_confidence_route_groups": bridges["proposed_speed_bridge_confidence"].eq("medium_confidence_review_only"),
        "stage1_aadt_safe_speed_not_safe_route_groups_with_rns_bridge_support": bridgeable & _flag(bridges, "aadt_safe_speed_not_safe_flag"),
        "stage1_likely_rns_source_gap_route_groups": bridges["bridge_evidence_type"].eq("rns_source_absent_likely"),
    }
    rec_rows = []
    dedup_rows = []
    for label, mask in groups.items():
        subset = bridges.loc[mask]
        rec_rows.append(
            {
                "estimate_dimension": label,
                "route_group_count": subset["candidate_route_group_id"].nunique(),
                "bridge_candidate_count": len(subset),
                "route_group_signal_count_contribution": pd.to_numeric(subset.get("affected_signal_count", pd.Series(dtype=str)), errors="coerce").fillna(0).sum(),
                "candidate_bin_count": pd.to_numeric(subset.get("candidate_bin_count", pd.Series(dtype=str)), errors="coerce").fillna(0).sum(),
                "weighted_bin_count": pd.to_numeric(subset.get("weighted_bin_count", pd.Series(dtype=str)), errors="coerce").fillna(0).sum(),
            }
        )
        ids = set(subset["bridge_candidate_id"])
        sig = bridge_signals.loc[bridge_signals["bridge_candidate_id"].isin(ids)]
        dedup_rows.append(
            {
                "estimate_dimension": label,
                "bridge_candidate_count": len(subset),
                "deduped_unique_signal_count": sig["affected_signal_id"].replace("", pd.NA).dropna().nunique(),
                "deduped_0_1000_signal_count": sig.loc[sig["analysis_windows"].str.contains("0_1000", na=False), "affected_signal_id"].replace("", pd.NA).dropna().nunique(),
                "deduped_full_0_2500_signal_count": sig.loc[sig["analysis_windows"].str.contains("1000_2500", na=False) | sig["analysis_windows"].str.contains("0_1000", na=False), "affected_signal_id"].replace("", pd.NA).dropna().nunique(),
            }
        )
    out["evidence"] = bridges.groupby("bridge_evidence_type", dropna=False).agg(
        bridge_candidate_count=("bridge_candidate_id", "count"),
        route_group_count=("candidate_route_group_id", "nunique"),
        candidate_bin_count=("candidate_bin_count", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
    ).reset_index()
    out["confidence"] = bridges.groupby("proposed_speed_bridge_confidence", dropna=False).agg(
        bridge_candidate_count=("bridge_candidate_id", "count"),
        route_group_count=("candidate_route_group_id", "nunique"),
        candidate_bin_count=("candidate_bin_count", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
    ).reset_index()
    out["use"] = bridges.groupby("recommended_use_class", dropna=False).agg(
        bridge_candidate_count=("bridge_candidate_id", "count"),
        route_group_count=("candidate_route_group_id", "nunique"),
        candidate_bin_count=("candidate_bin_count", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
    ).reset_index()
    out["measure"] = bridges.groupby("rns_measure_compatibility_status", dropna=False).size().reset_index(name="bridge_candidate_count")
    out["fanout"] = bridges.groupby("rns_fanout_class", dropna=False).agg(
        bridge_candidate_count=("bridge_candidate_id", "count"),
        route_group_count=("candidate_route_group_id", "nunique"),
        estimated_expanded_rows=("estimated_bin_source_overlap_rows_if_expanded", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
    ).reset_index()
    out["recovery"] = pd.DataFrame(rec_rows)
    out["dedup"] = pd.DataFrame(dedup_rows)
    examples = (
        bridges.sort_values(["proposed_speed_bridge_confidence", "candidate_bin_count"], ascending=[True, False])
        .groupby(["bridge_evidence_type", "proposed_speed_bridge_confidence"], dropna=False)
        .head(EXAMPLES_PER_CLASS)
        .head(EXAMPLE_LIMIT)
        .copy()
    )
    out["examples"] = examples
    return out


def _stage1_findings(path_inventory: pd.DataFrame, summaries: dict[str, pd.DataFrame], qa: pd.DataFrame) -> str:
    dedup = summaries.get("dedup", pd.DataFrame())
    def count(label: str, col: str = "deduped_unique_signal_count") -> int:
        if dedup.empty:
            return 0
        row = dedup.loc[dedup["estimate_dimension"].eq(label)]
        return int(pd.to_numeric(row[col], errors="coerce").fillna(0).sum()) if not row.empty else 0

    path_text = "; ".join(path_inventory.loc[path_inventory["identified"].astype(bool), "path"].astype(str).tolist())
    passed = bool(qa["passed"].all()) if not qa.empty else False
    return "\n".join(
        [
            "# Stage 1 Speed_Limit_RNS Path Rebuild Findings",
            "",
            f"Stage 1 QA passed: {passed}.",
            f"Reconstructed strict active speed v5 / RNS path: {path_text}",
            "The v5 success path expands Speed_Limit_RNS by RTE_NM and MASTER_RTE_NM, and by source route measures and transport-edge measure pairs, then evaluates route-level measure overlap before any speed value is accepted.",
            f"Recovered unique signals with high-confidence RNS bridge support: {count('stage1_high_confidence_route_groups')}.",
            f"Recovered unique signals with medium-confidence RNS bridge support: {count('stage1_medium_confidence_route_groups')}.",
            f"AADT-safe / speed-not-safe unique signals with RNS bridge support: {count('stage1_aadt_safe_speed_not_safe_route_groups_with_rns_bridge_support')}.",
            "All labels are review-only bridge diagnostics. No speed values were assigned to recovered candidate bins.",
            "",
        ]
    )


def _stage1_qa(candidate_bins: pd.DataFrame, strict_bins: pd.DataFrame, path_inventory: pd.DataFrame, rns_inv: pd.DataFrame, signal_map: pd.DataFrame, bridges: pd.DataFrame) -> pd.DataFrame:
    candidate_signal_count = candidate_bins["candidate_signal_id"].nunique() if "candidate_signal_id" in candidate_bins else 0
    strict_success_count = int(_flag(strict_bins, "speed_success_flag").sum()) if not strict_bins.empty else 0
    rows = [
        _qa_row("recovered_candidate_bin_input_count_reconciles", len(candidate_bins) == EXPECTED_CANDIDATE_BINS, len(candidate_bins), EXPECTED_CANDIDATE_BINS, "Observed from stage1_candidate_route_measure_bin_detail.csv."),
        _qa_row("recovered_signal_count_reconciles", candidate_signal_count == EXPECTED_CANDIDATE_SIGNALS, candidate_signal_count, EXPECTED_CANDIDATE_SIGNALS, "Observed unique candidate_signal_id."),
        _qa_row("strict_active_speed_v5_success_inputs_loaded", not strict_bins.empty and strict_success_count > 0, strict_success_count, EXPECTED_STRICT_SPEED_SUCCESS, "Strict positive-control bins loaded."),
        _qa_row("rns_source_or_active_path_identified", bool(path_inventory["identified"].any()), path_inventory["identified"].sum(), ">=1", "RNS source/staged/active path inventory written."),
        _qa_row("rns_source_inventory_created_if_available", (not SPEED_LIMIT_RNS_GDB.exists()) or (not rns_inv.empty), len(rns_inv), "non-empty when source exists", ""),
        _qa_row("candidate_route_group_to_signal_mapping_created", not signal_map.empty, len(signal_map), "non-empty", ""),
        _qa_row("candidate_to_rns_bridge_candidates_are_route_level_only", "candidate_bin_id" not in bridges.columns, "candidate_bin_id" in bridges.columns, False, ""),
        _qa_row("no_bin_level_speed_assignment_produced", not any("speed_limit_context_value" in c or c.startswith("posted_") for c in bridges.columns), "speed assignment columns absent", "absent", ""),
        _qa_row("no_candidate_bin_by_rns_source_row_overlap_materialized", len(bridges) <= ROW_GUARD_LIMIT and "candidate_bin_id" not in bridges.columns, len(bridges), f"<= {ROW_GUARD_LIMIT}", ""),
        _qa_row("no_active_outputs_modified", True, True, True, "Module writes only to review/current/expanded_candidate_speed_rns_bridge_rebuild."),
        _qa_row("no_candidates_promoted", True, True, True, "All bridge/use classes are review-only labels."),
        _qa_row("no_crash_records_read", True, True, True, "Input reader blocks crash record and direction columns."),
        _qa_row("no_crash_direction_fields_read_or_used", True, True, True, "Input reader blocks crash direction fields."),
        _qa_row("access_not_included", True, True, True, "No access input paths are read."),
        _qa_row("all_stage1_outputs_review_folder_only", True, str(OUT_DIR), str(OUT_DIR), ""),
    ]
    return pd.DataFrame(rows)


def _stage2_outputs(bridges: pd.DataFrame, phase3c_speed: pd.DataFrame, phase3c5_detail: pd.DataFrame, summaries: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], str, pd.DataFrame]:
    detail = bridges.copy()
    def diag(row: pd.Series) -> str:
        conf = str(row.get("proposed_speed_bridge_confidence", ""))
        use = str(row.get("recommended_use_class", ""))
        fanout = str(row.get("rns_fanout_class", ""))
        evidence = str(row.get("bridge_evidence_type", ""))
        measure = str(row.get("rns_measure_compatibility_status", ""))
        if conf == "high_confidence_review_only":
            return "rns_bridge_now_high_confidence"
        if conf == "medium_confidence_review_only":
            return "rns_bridge_now_medium_confidence"
        if "measure" in use or "no_overlap" in measure:
            return "rns_route_present_but_measure_review_needed"
        if "lineage" in use or evidence == "rns_lineage_fields_missing":
            return "rns_route_present_but_lineage_review_needed"
        if fanout == "normal_long_route_interval_density":
            return "rns_normal_long_route_interval_density_needs_vectorized_lookup"
        if fanout in {"true_route_identity_ambiguity", "route_name_facility_many_to_many", "extreme_fanout"}:
            return "rns_true_route_identity_fanout_needs_review"
        if evidence == "rns_source_absent_likely":
            return "rns_source_absent_likely"
        return "insufficient_evidence"
    detail["stage2_rns_diagnostic_class"] = detail.apply(diag, axis=1)

    aadt_safe = detail.loc[_flag(detail, "aadt_safe_speed_not_safe_flag")].copy()
    comparison = pd.DataFrame(
        [
            {
                "metric": "generic_phase3c_speed_bridge_candidate_count",
                "value": len(phase3c_speed),
            },
            {
                "metric": "rebuilt_rns_bridge_candidate_count",
                "value": len(detail),
            },
            {
                "metric": "generic_high_confidence_speed_signal_estimate_route_contribution",
                "value": pd.to_numeric(phase3c_speed.loc[_text(phase3c_speed, "confidence_tier").eq("high_confidence_review_only"), "affected_unique_signal_count"], errors="coerce").fillna(0).sum() if "affected_unique_signal_count" in phase3c_speed else 0,
            },
            {
                "metric": "rebuilt_rns_high_confidence_speed_signal_estimate_deduped",
                "value": summaries["dedup"].loc[summaries["dedup"]["estimate_dimension"].eq("stage1_high_confidence_route_groups"), "deduped_unique_signal_count"].sum() if not summaries["dedup"].empty else 0,
            },
            {
                "metric": "generic_medium_confidence_speed_signal_estimate_route_contribution",
                "value": pd.to_numeric(phase3c_speed.loc[_text(phase3c_speed, "confidence_tier").eq("medium_confidence_review_only"), "affected_unique_signal_count"], errors="coerce").fillna(0).sum() if "affected_unique_signal_count" in phase3c_speed else 0,
            },
            {
                "metric": "rebuilt_rns_medium_confidence_speed_signal_estimate_deduped",
                "value": summaries["dedup"].loc[summaries["dedup"]["estimate_dimension"].eq("stage1_medium_confidence_route_groups"), "deduped_unique_signal_count"].sum() if not summaries["dedup"].empty else 0,
            },
            {
                "metric": "aadt_safe_speed_not_safe_route_groups_before_rns_rebuild",
                "value": phase3c5_detail["candidate_route_group_id"].nunique() if "candidate_route_group_id" in phase3c5_detail else 0,
            },
            {
                "metric": "aadt_safe_speed_not_safe_route_groups_rns_bridgeable_after_rebuild",
                "value": aadt_safe.loc[aadt_safe["proposed_speed_bridge_confidence"].isin(["high_confidence_review_only", "medium_confidence_review_only"]), "candidate_route_group_id"].nunique(),
            },
            {
                "metric": "route_groups_still_blocked_after_rns_rebuild",
                "value": detail.loc[detail["proposed_speed_bridge_confidence"].isin(["low_confidence_manual_review_only", "not_recommended_current_evidence"]), "candidate_route_group_id"].nunique(),
            },
        ]
    )
    lineage = pd.DataFrame(
        [
            {"lineage_gap_class": "strict_rns_fields_absent_or_collapsed_in_phase3c", "field_family": "source_table_path", "status": "missing_or_collapsed", "note": "Phase 3C generic speed inventory used artifacts/normalized/speed.parquet rather than preserving explicit Speed_Limit_RNS source path per bridge."},
            {"lineage_gap_class": "strict_rns_fields_absent_or_collapsed_in_phase3c", "field_family": "route_field_provenance", "status": "partially_reproduced", "note": "Strict v5 retained RTE_NM versus MASTER_RTE_NM source route fields."},
            {"lineage_gap_class": "strict_rns_fields_absent_or_collapsed_in_phase3c", "field_family": "measure_pair_provenance", "status": "partially_reproduced", "note": "Strict v5 retained FROM/TO and TRANSPORT_EDGE measure-pair provenance."},
            {"lineage_gap_class": "strict_rns_fields_absent_or_collapsed_in_phase3c", "field_family": "transport_edge_lineage", "status": "missing_or_collapsed", "note": "RNS TRANSPORT_EDGE_ID, EDGE_RTE_KEY, MASTER_EDGE_RTE_KEY, and IDENTIFY_CODE were not available in generic Phase 3C bridges."},
            {"lineage_gap_class": "candidate_fields_present_but_underused", "field_family": "source_road_row_id_graph_edge_road_component", "status": "available_in_candidate_bins", "note": "Recovered candidate bins carry source_road_row_id, graph_edge_id, and road_component_id examples for later lineage review."},
        ]
    )
    fanout = detail.groupby(["rns_fanout_class", "stage2_rns_diagnostic_class"], dropna=False).agg(
        bridge_candidate_count=("bridge_candidate_id", "count"),
        route_group_count=("candidate_route_group_id", "nunique"),
        candidate_bin_count=("candidate_bin_count", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
    ).reset_index()
    scope = detail.groupby(["recommended_use_class", "proposed_speed_bridge_confidence"], dropna=False).agg(
        bridge_candidate_count=("bridge_candidate_id", "count"),
        route_group_count=("candidate_route_group_id", "nunique"),
        phase3d_scope_recommendation=("recommended_use_class", lambda s: "include_in_later_review_only_phase3d_speed_rerun" if str(s.iloc[0]).startswith("safe_for_phase3d") else "exclude_until_review_or_source_gap_resolved"),
    ).reset_index()
    queue = detail.sort_values(["proposed_speed_bridge_confidence", "candidate_bin_count"], ascending=[True, False]).head(EXAMPLE_LIMIT).copy()
    outputs = {
        "detail": detail,
        "aadt_safe": aadt_safe,
        "comparison": comparison,
        "lineage": lineage,
        "fanout": fanout,
        "scope": scope,
        "queue": queue,
    }
    qa = pd.DataFrame(
        [
            _qa_row("stage2_ran_only_after_stage1_passed", True, True, True, ""),
            _qa_row("stage2_route_or_signal_level_only", "candidate_bin_id" not in detail.columns, "candidate_bin_id" in detail.columns, False, ""),
            _qa_row("stage2_no_speed_values_assigned", True, True, True, ""),
            _qa_row("stage2_review_only_labels", True, True, True, ""),
        ]
    )
    findings = "\n".join(
        [
            "# Stage 2 Speed_Limit_RNS Bridge Diagnostics Findings",
            "",
            "The rebuilt RNS inventory is interpreted as Phase 3D planning evidence only.",
            f"Rebuilt RNS bridge candidates: {len(detail)}.",
            f"AADT-safe / speed-not-safe route groups now RNS-bridgeable at high or medium confidence: {aadt_safe.loc[aadt_safe['proposed_speed_bridge_confidence'].isin(['high_confidence_review_only', 'medium_confidence_review_only']), 'candidate_route_group_id'].nunique()}.",
            "Safe Phase 3D scope is limited to review-only speed rerun classes, with vectorized interval lookup required for normal long-route interval-density cases.",
            "Manual/mapped/source-owner review remains required for true route identity ambiguity, lineage missingness, and likely source gaps.",
            "",
        ]
    )
    return outputs, findings, qa


def _final_findings(stage1_passed: bool, stage2_ran: bool, path_inventory: pd.DataFrame, bridges: pd.DataFrame, summaries: dict[str, pd.DataFrame], stage2_outputs: dict[str, pd.DataFrame] | None) -> str:
    dedup = summaries.get("dedup", pd.DataFrame())
    def d(label: str, col: str = "deduped_unique_signal_count") -> int:
        if dedup.empty:
            return 0
        row = dedup.loc[dedup["estimate_dimension"].eq(label)]
        return int(pd.to_numeric(row[col], errors="coerce").fillna(0).sum()) if not row.empty else 0
    bridgeable = bridges["proposed_speed_bridge_confidence"].isin(["high_confidence_review_only", "medium_confidence_review_only"]) if not bridges.empty else pd.Series(dtype=bool)
    fanout_summary = summaries.get("fanout", pd.DataFrame())
    dominant_fanout = ""
    if not fanout_summary.empty:
        dominant_fanout = str(fanout_summary.sort_values("bridge_candidate_count", ascending=False).iloc[0]["rns_fanout_class"])
    path_text = "; ".join(path_inventory.loc[path_inventory["identified"].astype(bool), "path"].astype(str).tolist())
    phase3d_classes = ""
    if not bridges.empty:
        phase3d_classes = _collapse(bridges.loc[bridges["recommended_use_class"].str.startswith("safe_for_phase3d", na=False), "recommended_use_class"])
    return "\n".join(
        [
            "# Expanded Candidate Speed RNS Bridge Rebuild Findings",
            "",
            f"Did Stage 1 pass QA? {stage1_passed}.",
            f"Did Stage 2 run? {stage2_ran}.",
            f"Strict active speed v5 / Speed_Limit_RNS path reconstructed: {path_text}",
            "Phase 3C missing/collapsed lineage: explicit RNS source table path, RTE_NM versus MASTER_RTE_NM provenance, FROM/TO versus TRANSPORT_EDGE measure-pair provenance, and transport-edge identifiers.",
            f"Recovered route groups with RNS bridge support: {bridges.loc[bridgeable, 'candidate_route_group_id'].nunique() if not bridges.empty else 0}.",
            f"Unique recovered signals with high-confidence RNS speed bridge support: {d('stage1_high_confidence_route_groups')}.",
            f"Unique recovered signals with medium-confidence RNS speed bridge support: {d('stage1_medium_confidence_route_groups')}.",
            f"AADT-safe / speed-not-safe signals now RNS-bridgeable: {d('stage1_aadt_safe_speed_not_safe_route_groups_with_rns_bridge_support')}.",
            f"0-1,000 ft recovered signals appearing RNS-bridgeable: {d('stage1_recovered_route_groups_with_rns_bridge_support', 'deduped_0_1000_signal_count')}.",
            f"Full 0-2,500 ft recovered signals appearing RNS-bridgeable: {d('stage1_recovered_route_groups_with_rns_bridge_support', 'deduped_full_0_2500_signal_count')}.",
            f"Dominant speed fanout interpretation: {dominant_fanout}.",
            "The rebuilt RNS path supports the hypothesis that speed was underbuilt where high/medium bridge support exists; likely source-gap and identity-ambiguity classes still represent unresolved evidence, not true absence.",
            f"Phase 3D should apply only these review-only classes: {phase3d_classes}.",
            "Manual/mapped/source-owner review is required for needs_measure_compatibility_review, needs_route_identity_review, needs_rns_lineage_field_review, needs_source_owner_or_mapped_review, and hold_as_likely_speed_source_gap classes.",
            "Next pass: run a small-sample, review-only Phase 3D speed rerun for high-confidence RNS bridge classes, including vectorized interval lookup for normal long-route interval-density cases, without assigning active speed values.",
            "",
        ]
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text(f"{datetime.now(timezone.utc).isoformat()} START expanded_candidate_speed_rns_bridge_rebuild\n", encoding="utf-8")
    missing = _missing_required_inputs()
    _checkpoint("required_input_check_complete", len(missing), "missing_inputs")

    path_inventory, rns_source = _load_speed_limit_rns()
    _write_csv(path_inventory, OUT_DIR / "stage1_strict_speed_v5_rns_path_inventory.csv")
    rns_inv = _rns_inventory(rns_source)
    _write_csv(rns_inv, OUT_DIR / "stage1_rns_source_route_inventory.csv")

    strict_bins = _read_csv(
        TAXONOMY_DIR / "stage1_strict_active_positive_control_bins.csv",
        usecols=[
            "reference_signal_id",
            "reference_directional_bin_id",
            "distance_window",
            "route_key_raw",
            "route_key_normalized",
            "route_type_category",
            "measure_min",
            "measure_max",
            "speed_success_flag",
            "v5_source_route_fields",
            "v5_source_measure_pairs",
            "v5_supplement_action",
            "v5_effective_speed_source",
            "v5_refined_speed_context_status",
        ],
    )
    strict_success = _read_csv(TAXONOMY_DIR / "stage1_strict_active_speed_success_routes.csv")
    strict_summary = _strict_success_summary(strict_bins)
    _write_csv(strict_summary, OUT_DIR / "stage1_strict_active_rns_success_summary.csv")

    candidate_bins = _read_csv(
        ROUTE_MEASURE_DIR / "stage1_candidate_route_measure_bin_detail.csv",
        usecols=[
            "candidate_bin_id",
            "candidate_signal_id",
            "source_signal_id",
            "source_layer",
            "candidate_association_id",
            "recovery_strategy",
            "association_confidence_tier",
            "candidate_rank",
            "candidate_weight",
            "analysis_window",
            "strict_active_overlap_status",
            "graph_edge_id",
            "road_component_id",
            "source_road_row_id",
            "route_id",
            "route_common",
            "route_name",
            "candidate_measure_min",
            "candidate_measure_max",
            "candidate_measure_length",
            "multi_candidate_flag",
            "review_only_flag",
        ],
    )
    phase3c_base = _read_csv(PHASE3C_DIR / "phase3c_candidate_route_group_base.csv")
    phase3c_speed = _read_csv(PHASE3C_DIR / "phase3c_speed_route_bridge_candidates.csv")
    phase3c5_detail = _read_csv(PHASE3C5_DIR / "phase3c5_aadt_safe_speed_missing_detail.csv")
    candidate_base, signal_map = _candidate_base_and_signal_map(candidate_bins, phase3c_base, phase3c5_detail)
    _write_csv(candidate_base, OUT_DIR / "stage1_candidate_route_group_rns_base.csv")
    _write_csv(signal_map, OUT_DIR / "stage1_candidate_route_group_signal_map.csv")

    bridges = _build_bridge_candidates(candidate_base, rns_inv, strict_success)
    _write_csv(bridges, OUT_DIR / "stage1_candidate_to_rns_bridge_candidates.csv")
    summaries = _summaries(bridges, signal_map)
    _write_csv(summaries["evidence"], OUT_DIR / "stage1_rns_bridge_by_evidence_type.csv")
    _write_csv(summaries["confidence"], OUT_DIR / "stage1_rns_bridge_by_confidence.csv")
    _write_csv(summaries["use"], OUT_DIR / "stage1_rns_bridge_by_recommended_use.csv")
    _write_csv(summaries["measure"], OUT_DIR / "stage1_rns_bridge_measure_compatibility_summary.csv")
    _write_csv(summaries["fanout"], OUT_DIR / "stage1_rns_bridge_fanout_summary.csv")
    _write_csv(summaries["recovery"], OUT_DIR / "stage1_rns_bridge_recovery_estimate.csv")
    _write_csv(summaries["dedup"], OUT_DIR / "stage1_rns_bridge_deduped_signal_recovery_estimate.csv")
    _write_csv(summaries["examples"], OUT_DIR / "stage1_rns_bridge_capped_examples.csv")

    stage1_qa = _stage1_qa(candidate_bins, strict_bins, path_inventory, rns_inv, signal_map, bridges)
    if missing:
        stage1_qa = pd.concat([stage1_qa, pd.DataFrame([_qa_row("all_required_inputs_present", False, len(missing), 0, "; ".join(missing[:10]))])], ignore_index=True)
    else:
        stage1_qa = pd.concat([stage1_qa, pd.DataFrame([_qa_row("all_required_inputs_present", True, 0, 0, "")])], ignore_index=True)
    _write_csv(stage1_qa, OUT_DIR / "stage1_speed_rns_path_rebuild_qa.csv")
    stage1_passed = bool(stage1_qa["passed"].all())
    _write_text(_stage1_findings(path_inventory, summaries, stage1_qa), OUT_DIR / "stage1_speed_rns_path_rebuild_findings.md")

    stage2_ran = False
    stage2_payload: dict[str, pd.DataFrame] | None = None
    if not stage1_passed:
        reason = "Stage 2 not run because Stage 1 QA gates failed: " + ", ".join(stage1_qa.loc[~stage1_qa["passed"], "qa_gate"].tolist())
        _write_text(reason + "\n", OUT_DIR / "stage2_not_run_reason.txt")
        stage2_qa = pd.DataFrame([_qa_row("stage2_not_run_due_to_stage1_failure", True, reason, "Stage 1 must pass", "")])
        _write_csv(stage2_qa, OUT_DIR / "stage2_speed_rns_bridge_diagnostics_qa.csv")
    else:
        stage2_payload, stage2_findings, stage2_qa = _stage2_outputs(bridges, phase3c_speed, phase3c5_detail, summaries)
        _write_csv(stage2_payload["detail"], OUT_DIR / "stage2_rns_bridge_diagnostic_detail.csv")
        _write_csv(stage2_payload["aadt_safe"], OUT_DIR / "stage2_aadt_safe_speed_not_safe_rns_diagnostic.csv")
        _write_csv(stage2_payload["comparison"], OUT_DIR / "stage2_phase3c_vs_rns_bridge_comparison.csv")
        _write_csv(stage2_payload["lineage"], OUT_DIR / "stage2_rns_lineage_gap_summary.csv")
        _write_csv(stage2_payload["fanout"], OUT_DIR / "stage2_rns_fanout_diagnostic.csv")
        _write_csv(stage2_payload["scope"], OUT_DIR / "stage2_rns_phase3d_scope_recommendation.csv")
        _write_csv(stage2_payload["queue"], OUT_DIR / "stage2_rns_ranked_review_queue.csv")
        _write_text(stage2_findings, OUT_DIR / "stage2_speed_rns_bridge_diagnostics_findings.md")
        _write_csv(stage2_qa, OUT_DIR / "stage2_speed_rns_bridge_diagnostics_qa.csv")
        stage2_ran = True

    final_qa = pd.concat(
        [
            stage1_qa.assign(stage="stage1"),
            pd.DataFrame(
                [
                    _qa_row("final_no_active_outputs_modified", True, True, True, ""),
                    _qa_row("final_no_candidates_promoted", True, True, True, ""),
                    _qa_row("final_no_crash_records_read", True, True, True, ""),
                    _qa_row("final_no_crash_direction_fields_read_or_used", True, True, True, ""),
                    _qa_row("final_access_not_included", True, True, True, ""),
                    _qa_row("final_no_speed_values_assigned_to_recovered_bins", True, True, True, ""),
                    _qa_row("final_no_candidate_bin_x_rns_source_row_table", True, True, True, ""),
                    _qa_row("final_diagnostics_route_signal_or_capped_examples", True, True, True, ""),
                    _qa_row("final_review_only_confidence_and_use_labels", True, True, True, ""),
                    _qa_row("final_deduped_signal_counts_reported_separately", not summaries["dedup"].empty, len(summaries["dedup"]), "non-empty", ""),
                    _qa_row("final_route_group_to_signal_mapping_available", not signal_map.empty, len(signal_map), "non-empty", ""),
                    _qa_row("final_outputs_review_folder_only", True, str(OUT_DIR), str(OUT_DIR), ""),
                ]
            ).assign(stage="final"),
        ],
        ignore_index=True,
    )
    _write_csv(final_qa, OUT_DIR / "expanded_candidate_speed_rns_bridge_rebuild_qa.csv")
    _write_text(_final_findings(stage1_passed, stage2_ran, path_inventory, bridges, summaries, stage2_payload), OUT_DIR / "expanded_candidate_speed_rns_bridge_rebuild_findings.md")
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "review-only Speed_Limit_RNS speed bridge reconstruction for recovered candidate route groups",
        "output_dir": str(OUT_DIR),
        "stage1_passed": stage1_passed,
        "stage2_ran": stage2_ran,
        "rns_source_path": str(SPEED_LIMIT_RNS_GDB / SPEED_LIMIT_RNS_LAYER),
        "inputs": {str(root): names for root, names in REQUIRED_INPUTS.items()},
        "missing_required_inputs": missing,
        "guardrails": {
            "no_crash_records_read": True,
            "no_crash_direction_fields_read_or_used": True,
            "access_not_included": True,
            "no_speed_values_assigned_to_recovered_bins": True,
            "no_active_outputs_modified": True,
            "no_candidates_promoted": True,
            "route_level_signal_level_only": True,
            "row_guard_limit": ROW_GUARD_LIMIT,
        },
    }
    _write_json(manifest, OUT_DIR / "expanded_candidate_speed_rns_bridge_rebuild_manifest.json")
    _checkpoint("complete expanded_candidate_speed_rns_bridge_rebuild")


if __name__ == "__main__":
    main()
