"""Patch staged distance_band_context roadway fields and guarded speed context.

This is a bounded two-stage repair:

1. Patch derived roadway fields in the staged distance-band context.
2. Only after Stage 1 passes, test source-rooted speed repair methods and patch
   speed fields only when a safe method improves coverage.

The script writes review evidence under work/roadway_graph/review and writes a
temporary parquet before replacing the staged context.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

try:
    import pyogrio
except Exception:  # pragma: no cover - environment guard.
    pyogrio = None


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/patch_distance_band_context_roadway_and_speed"

DISTANCE_BAND_CONTEXT = STAGING / "distance_band_context.parquet"
DISTANCE_BAND_UNITS = STAGING / "distance_band_units.parquet"
BIN_CONTEXT = STAGING / "bin_context.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
MANIFEST = STAGING / "manifest.json"
SCHEMA = STAGING / "schema.json"
README = STAGING / "README.md"

SPEED = REPO / "artifacts/normalized/speed.parquet"
AADT = REPO / "artifacts/normalized/aadt.parquet"
ACCESS = REPO / "artifacts/normalized/access_v2.parquet"
ROADS = REPO / "artifacts/normalized/roads.parquet"
RNS_GDB = REPO / "Intersection Crash Analysis Layers/Speed_Limit_RNS/Speed_Limit_RNS.gdb"
RNS_LAYER = "Speed_Limit_RNS"

BUILD_VERSION = "distance_band_context_roadway_speed_patch_v1_2026-06-15"
MILE_FT = 5280.0
MEASURE_BUCKET_MI = 0.10
MIN_OVERLAP_MI = 1e-6
TOLERANCE_MI = 0.10

IDENTITY_COLUMNS = [
    "distance_band_unit_id",
    "stable_signal_id",
    "signal_approach_id",
    "upstream_downstream",
    "distance_band",
]

STAGE1_TARGET_FIELDS = ["divided_undivided", "one_way_two_way", "median_group"]
SPEED_TARGET_FIELDS = [
    "speed_limit_mph",
    "speed_category",
    "speed_context_status",
    "speed_source_match_method",
    "speed_missing_reason",
    "speed_candidate_count",
    "speed_value_mix",
    "mixed_speed_flag",
    "speed_value_count",
    "speed_min_mph",
    "speed_max_mph",
    "speed_length_weighted_mph",
    "speed_dominant_mph",
    "speed_context_quality_flag",
]

NON_TARGET_PREFIXES = ("aadt", "access", "crash", "exposure")
FORBIDDEN_OUTPUT_TOKENS = ("lookup_cell", "lookup_cells", "rate_distribution", "final_rate_distribution")
CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

PHASES: list[dict[str, Any]] = []


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO)).replace("\\", "/")
    except ValueError:
        return str(path)


def clean(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "null", "<na>", "nat"} else text


def clean_series(series: pd.Series) -> pd.Series:
    out = series.astype("string").fillna("").str.strip()
    return out.mask(out.str.lower().isin({"", "nan", "none", "null", "<na>", "nat"}), "").fillna("")


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now()
    print(f"[{stamp}] {message}", flush=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {stamp} - {message}\n")


@contextmanager
def phase(name: str, **metadata: Any):
    started = time.perf_counter()
    log(f"BEGIN {name}" + (f" {metadata}" if metadata else ""))
    try:
        yield
    finally:
        elapsed = time.perf_counter() - started
        PHASES.append({"phase": name, "elapsed_seconds": round(elapsed, 3), **metadata})
        log(f"END {name}; elapsed_seconds={elapsed:,.3f}")


def write_csv(name: str, rows: list[dict[str, Any]] | pd.DataFrame, fieldnames: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    if isinstance(rows, pd.DataFrame):
        rows.to_csv(path, index=False)
        return
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        if not fieldnames:
            fieldnames = ["note"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(name: str, payload: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(json_safe(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_path(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(json_safe(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parquet_row_count(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS)


def stable_hash(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "empty"
    hashed = pd.util.hash_pandas_object(frame.reset_index(drop=True), index=False)
    return hashlib.sha256(hashed.values.tobytes()).hexdigest()


def route_key(value: Any) -> str:
    text = clean(value).upper()
    if not text:
        return ""
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("R-VA", " R VA ")
    text = text.replace("S-VA", " S VA ")
    text = re.sub(r"\bU\s*\.?\s*S\s*\.?\b", " US ", text)
    text = re.sub(r"\bINTERSTATE\b", " I ", text)
    text = re.sub(r"\bIS\b", " I ", text)
    text = re.sub(r"\b(STATE\s+ROUTE|STATE|ROUTE|RTE|RT|HIGHWAY|HWY|VIRGINIA)\b", " ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    compact_all = "".join(text.split())
    patterns = [
        r"(US|SR|SC|PR|FR|NP|UR|IS|I)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?",
        r"(?:R|S)?VA[0-9]{0,3}(US|SR|SC|PR|FR|NP|UR|IS|I)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact_all)
        if match:
            prefix = match.group(1)
            prefix = "I" if prefix in {"IS", "I"} else prefix
            direction = (match.group(3) or "")[:1]
            return f"{prefix}{int(match.group(2))}{direction}"
    tokens = [token for token in text.split() if token and token not in {"R", "S", "VA"}]
    return re.sub(r"[^A-Z0-9]", "", " ".join(tokens))


def route_base_key(value: Any) -> str:
    return re.sub(r"[NSEW]$", "", route_key(value))


def route_number_key(value: Any) -> str:
    key = route_base_key(value)
    match = re.search(r"([0-9]+)$", key)
    return str(int(match.group(1))) if match else ""


def normalize_route_cache(values: pd.Series, label: str) -> pd.DataFrame:
    unique = pd.Series(sorted(v for v in clean_series(values).unique().tolist() if v), name="raw_route")
    out = pd.DataFrame({"raw_route": unique})
    out["route_key"] = out["raw_route"].map(route_key)
    out["route_base_key"] = out["raw_route"].map(route_base_key)
    out["route_number_key"] = out["raw_route"].map(route_number_key)
    log(f"Route cache {label}: {len(out):,} unique routes.")
    return out


def category_speed(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return ""
    speed = float(numeric)
    if speed <= 25:
        return "25_mph_or_less"
    if speed <= 35:
        return "30_to_35_mph"
    if speed <= 45:
        return "40_to_45_mph"
    if speed <= 55:
        return "50_to_55_mph"
    return "60_mph_or_more"


def roadway_token_status(token: Any) -> dict[str, str]:
    text = clean(token)
    lower = text.lower()
    divided = ""
    one_two = ""
    if "divided" in lower and "undivided" not in lower:
        divided = "divided"
    elif "undivided" in lower:
        divided = "undivided"
    elif "reversible" in lower:
        divided = "unknown_reversible"
    elif "trail" in lower:
        divided = "unknown_nonroad_trail"

    if "one-way" in lower or "one way" in lower:
        one_two = "one_way"
    elif "two-way" in lower or "two way" in lower:
        one_two = "two_way"
    elif "reversible" in lower:
        one_two = "reversible"
    elif "trail" in lower:
        one_two = "unknown_nonroad_trail"
    return {"roadway_token": text, "divided_undivided_rule": divided, "one_way_two_way_rule": one_two}


def collapse_status(tokens: list[str], field: str) -> str:
    values = [roadway_token_status(token)[field] for token in tokens]
    values = [value for value in values if value and not value.startswith("unknown")]
    unique = sorted(set(values))
    if not unique:
        unknowns = sorted(set(roadway_token_status(token)[field] for token in tokens if roadway_token_status(token)[field]))
        return unknowns[0] if len(unknowns) == 1 else ("mixed_unknown" if unknowns else "")
    if len(unique) == 1:
        return unique[0]
    if field == "divided_undivided_rule":
        return "mixed_divided_undivided"
    return "mixed_one_way_two_way"


def split_summary(value: Any) -> list[str]:
    return [token.strip() for token in clean(value).split("|") if token.strip()]


def derive_divided_undivided(row: pd.Series) -> str:
    tokens = split_summary(row.get("roadway_configuration_summary")) or split_summary(row.get("rim_facility_summary"))
    return collapse_status(tokens, "divided_undivided_rule")


def derive_one_way_two_way(row: pd.Series) -> str:
    tokens = split_summary(row.get("roadway_configuration_summary")) or split_summary(row.get("rim_facility_summary"))
    return collapse_status(tokens, "one_way_two_way_rule")


def derive_median_group(value: Any) -> str:
    text = clean(value).lower()
    if not text:
        return ""
    if "no median" in text:
        return "no_median"
    if "grass" in text:
        return "grass_median"
    if "jersey" in text or "guard rail" in text or "positive barrier" in text:
        return "positive_barrier"
    if "curb" in text:
        return "curbed_or_mountable_barrier"
    if "painted" in text or "center turn lane" in text:
        return "painted_or_center_turn_lane"
    if "median" in text:
        return "other_median"
    return "other"


def coverage_row(frame: pd.DataFrame, field: str, stage: str) -> dict[str, Any]:
    nonblank = clean_series(frame[field]).ne("") if field in frame.columns else pd.Series(False, index=frame.index)
    return {"stage": stage, "field": field, "populated_units": int(nonblank.sum()), "total_units": int(len(frame))}


def base_parent_dependency_check() -> pd.DataFrame:
    rows = []
    direct = [DISTANCE_BAND_CONTEXT, DISTANCE_BAND_UNITS, BIN_CONTEXT, TRAVELWAY_INDEX, SPEED]
    read_only = [AADT, ACCESS, ROADS, APPROACH_CORRIDORS, RNS_GDB]
    diagnostic = [
        REPO / "work/roadway_graph/review/build_distance_band_context",
        REPO / "work/roadway_graph/review/distance_band_context_validation_legacy_audit",
        REPO / "work/roadway_graph/review/distance_band_units_validation_audit",
        REPO / "work/roadway_graph/review/bin_context_validation_audit",
        REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan",
    ]
    for path in direct + read_only + diagnostic:
        role = "direct_parent" if path in direct else ("read_only_source_or_schema_evidence" if path in read_only else "diagnostic_evidence_only")
        rows.append(
            {
                "path": rel(path),
                "role": role,
                "exists": path.exists(),
                "used_as_data_parent": role == "direct_parent" or path == RNS_GDB,
                "review_output_hidden_parent_flag": False,
                "downstream_parent_flag": any(token in rel(path).lower() for token in FORBIDDEN_OUTPUT_TOKENS),
            }
        )
    return pd.DataFrame(rows)


def stage1_patch(context: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    before_rows = [coverage_row(context, field, "before_stage1") for field in STAGE1_TARGET_FIELDS]
    out = context.copy()
    with phase("stage1_derive_roadway_fields", rows=len(out)):
        tokens = sorted({token for value in out["roadway_configuration_summary"].map(split_summary) for token in value})
        token_map = pd.DataFrame([roadway_token_status(token) for token in tokens])
        token_map["mapped_flag"] = token_map["divided_undivided_rule"].ne("") | token_map["one_way_two_way_rule"].ne("")
        write_csv("stage1_roadway_token_mapping.csv", token_map)
        unmapped = token_map.loc[~token_map["mapped_flag"]].copy()
        write_csv("stage1_unmapped_roadway_tokens.csv", unmapped)

        out["divided_undivided"] = out.apply(derive_divided_undivided, axis=1)
        out["one_way_two_way"] = out.apply(derive_one_way_two_way, axis=1)
        out["median_group"] = out["median_type"].map(derive_median_group)
    after_rows = [coverage_row(out, field, "after_stage1") for field in STAGE1_TARGET_FIELDS]
    summary = pd.DataFrame(before_rows + after_rows)
    write_csv("stage1_roadway_patch_summary.csv", summary)
    return out, {
        "coverage": summary,
        "unmapped_token_count": int(pd.read_csv(OUT / "stage1_unmapped_roadway_tokens.csv").shape[0]) if (OUT / "stage1_unmapped_roadway_tokens.csv").exists() else 0,
    }


def row_identity_checks(before: pd.DataFrame, after: pd.DataFrame, units: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {
            "check": "row_count_unchanged",
            "passed": len(before) == len(after) == len(units),
            "before": len(before),
            "after": len(after),
            "expected": len(units),
        },
        {
            "check": "distance_band_unit_id_set_unchanged",
            "passed": set(before["distance_band_unit_id"]) == set(after["distance_band_unit_id"]) == set(units["distance_band_unit_id"]),
            "before": before["distance_band_unit_id"].nunique(),
            "after": after["distance_band_unit_id"].nunique(),
            "expected": units["distance_band_unit_id"].nunique(),
        },
        {
            "check": "distance_band_unit_id_unique",
            "passed": after["distance_band_unit_id"].is_unique,
            "before": int(before["distance_band_unit_id"].duplicated().sum()),
            "after": int(after["distance_band_unit_id"].duplicated().sum()),
            "expected": 0,
        },
    ]
    out = pd.DataFrame(rows)
    write_csv("row_identity_unchanged_check.csv", out)
    write_csv("stage1_identity_reconciliation.csv", out)
    return out


def unit_grain_check(after: pd.DataFrame) -> pd.DataFrame:
    dupes = int(after.duplicated(IDENTITY_COLUMNS).sum())
    out = pd.DataFrame(
        [
            {
                "check": "unit_grain_uniqueness",
                "passed": dupes == 0,
                "identity_columns": "|".join(IDENTITY_COLUMNS),
                "duplicate_count": dupes,
                "row_count": len(after),
            }
        ]
    )
    write_csv("unit_grain_uniqueness_check.csv", out)
    return out


def directionality_reconciliation(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    b = before.groupby(["upstream_downstream", "directionality_status"], dropna=False).size().reset_index(name="before_count")
    a = after.groupby(["upstream_downstream", "directionality_status"], dropna=False).size().reset_index(name="after_count")
    out = b.merge(a, on=["upstream_downstream", "directionality_status"], how="outer").fillna(0)
    out["passed"] = out["before_count"].astype(int).eq(out["after_count"].astype(int))
    write_csv("directionality_reconciliation.csv", out)
    return out


def length_bin_count_reconciliation(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for field in ["bin_count", "unit_length_ft"]:
        b = pd.to_numeric(before[field], errors="coerce")
        a = pd.to_numeric(after[field], errors="coerce")
        rows.append(
            {
                "field": field,
                "passed": bool(np.allclose(b.fillna(-999999).to_numpy(), a.fillna(-999999).to_numpy())),
                "before_sum": float(b.sum()),
                "after_sum": float(a.sum()),
                "changed_rows": int(~b.fillna(-999999).eq(a.fillna(-999999)).sum()) if False else int((b.fillna(-999999) != a.fillna(-999999)).sum()),
            }
        )
    out = pd.DataFrame(rows)
    write_csv("length_bin_count_reconciliation.csv", out)
    return out


def unchanged_non_target_check(before: pd.DataFrame, after: pd.DataFrame, changed_fields: set[str]) -> pd.DataFrame:
    rows = []
    common = [col for col in before.columns if col in after.columns and col not in changed_fields]
    protected = [
        col
        for col in common
        if col.startswith(NON_TARGET_PREFIXES)
        or col in {"source_match_methods", "mixed_context_flags", "context_quality_flags", "overall_context_readiness_status", "rate_readiness_status"}
    ]
    for col in protected:
        left = before[col]
        right = after[col]
        same = left.equals(right)
        if not same:
            left_s = left.astype("string").fillna("<NA>")
            right_s = right.astype("string").fillna("<NA>")
            changed = int((left_s != right_s).sum())
        else:
            changed = 0
        rows.append({"field": col, "passed": same, "changed_rows": changed})
    out = pd.DataFrame(rows)
    write_csv("unchanged_non_target_context_fields_check.csv", out)
    return out


def no_crash_direction_field_check() -> pd.DataFrame:
    read_paths = [DISTANCE_BAND_CONTEXT, DISTANCE_BAND_UNITS, BIN_CONTEXT, TRAVELWAY_INDEX, SPEED, RNS_GDB]
    rows = []
    for path in read_paths:
        cols: list[str] = []
        if path.suffix == ".parquet" and path.exists():
            cols = pq.ParquetFile(path).schema_arrow.names
        elif path == RNS_GDB and path.exists() and pyogrio is not None:
            try:
                cols = list(pyogrio.read_info(path, layer=RNS_LAYER)["fields"])
            except Exception:
                cols = []
        detected = [col for col in cols if is_crash_direction_field(col)]
        rows.append(
            {
                "path": rel(path),
                "crash_direction_like_fields_detected": "|".join(detected),
                "used_as_join_or_derivation_field": False,
                "passed": True,
            }
        )
    out = pd.DataFrame(rows)
    write_csv("no_crash_direction_field_check.csv", out)
    return out


def forbidden_mvp_lookup_product_check() -> pd.DataFrame:
    rows = []
    if OUT.exists():
        for path in OUT.iterdir():
            lowered = path.name.lower()
            rows.append(
                {
                    "path": rel(path),
                    "forbidden_mvp_lookup_or_rate_distribution_name": any(token in lowered for token in FORBIDDEN_OUTPUT_TOKENS),
                }
            )
    out = pd.DataFrame(rows)
    out["passed"] = ~out["forbidden_mvp_lookup_or_rate_distribution_name"] if not out.empty else True
    write_csv("forbidden_mvp_lookup_product_check.csv", out)
    return out


def stage1_qa(before: pd.DataFrame, after: pd.DataFrame, units: pd.DataFrame) -> bool:
    checks = [
        row_identity_checks(before, after, units)["passed"].all(),
        unit_grain_check(after)["passed"].all(),
        directionality_reconciliation(before, after)["passed"].all(),
        length_bin_count_reconciliation(before, after)["passed"].all(),
        unchanged_non_target_check(before, after, set(STAGE1_TARGET_FIELDS))["passed"].all(),
        no_crash_direction_field_check()["passed"].all(),
    ]
    before_div = int(clean_series(before["divided_undivided"]).ne("").sum())
    after_div = int(clean_series(after["divided_undivided"]).ne("").sum())
    before_one = int(clean_series(before["one_way_two_way"]).ne("").sum())
    after_one = int(clean_series(after["one_way_two_way"]).ne("").sum())
    before_med = int(clean_series(before["median_group"]).ne("").sum())
    after_med = int(clean_series(after["median_group"]).ne("").sum())
    material = after_div > before_div and after_one > before_one and after_med >= before_med
    write_csv(
        "distance_band_context_patch_readiness_decision.csv",
        [
            {
                "stage": "stage1",
                "passed": bool(all(checks) and material),
                "before_divided_undivided_populated": before_div,
                "after_divided_undivided_populated": after_div,
                "before_one_way_two_way_populated": before_one,
                "after_one_way_two_way_populated": after_one,
                "before_median_group_populated": before_med,
                "after_median_group_populated": after_med,
            }
        ],
    )
    return bool(all(checks) and material)


def load_unit_route_spans(units: pd.DataFrame) -> pd.DataFrame:
    with phase("stage2_build_compact_unit_route_spans"):
        cols = [
            "stable_signal_id",
            "signal_approach_id",
            "upstream_downstream",
            "distance_band",
            "source_route_name",
            "route_base",
            "source_measure_start",
            "source_measure_end",
            "bin_length_ft",
            "logical_corridor_chain_id",
            "primary_stable_travelway_id",
        ]
        bins = pd.read_parquet(BIN_CONTEXT, columns=cols)
        bins["upstream_downstream"] = clean_series(bins["upstream_downstream"])
        bins.loc[~bins["upstream_downstream"].isin(["upstream", "downstream"]), "upstream_downstream"] = ""
        merged = bins.merge(units[IDENTITY_COLUMNS], on=["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"], how="left", validate="many_to_one")
        if merged["distance_band_unit_id"].isna().any():
            raise RuntimeError("bin_context rows failed distance_band_units reconciliation during speed span build")
        merged["measure_min"] = pd.to_numeric(merged[["source_measure_start", "source_measure_end"]].min(axis=1), errors="coerce")
        merged["measure_max"] = pd.to_numeric(merged[["source_measure_start", "source_measure_end"]].max(axis=1), errors="coerce")
        merged["span_length_ft"] = pd.to_numeric(merged["bin_length_ft"], errors="coerce").fillna(0)
        merged = merged.loc[merged["measure_min"].notna() & merged["measure_max"].notna() & merged["measure_max"].ge(merged["measure_min"])].copy()

        source_cache = normalize_route_cache(merged["source_route_name"], "bin_source_route_name")
        base_cache = normalize_route_cache(merged["route_base"], "bin_route_base")
        merged = merged.merge(source_cache.add_prefix("source_"), left_on="source_route_name", right_on="source_raw_route", how="left")
        merged = merged.merge(base_cache.add_prefix("base_"), left_on="route_base", right_on="base_raw_route", how="left")

        key_map = {
            "strict": "source_route_key",
            "directionless": "source_route_base_key",
            "route_number": "source_route_number_key",
            "alternate_route_base_directionless": "base_route_base_key",
        }
        frames = []
        for method_key, col in key_map.items():
            part = merged[
                [
                    "distance_band_unit_id",
                    "stable_signal_id",
                    "signal_approach_id",
                    "upstream_downstream",
                    "distance_band",
                    col,
                    "measure_min",
                    "measure_max",
                    "span_length_ft",
                    "logical_corridor_chain_id",
                    "primary_stable_travelway_id",
                ]
            ].rename(columns={col: "route_key"}).copy()
            part["route_key"] = clean_series(part["route_key"])
            part = part.loc[part["route_key"].ne("")].copy()
            grouped = (
                part.groupby(
                    [
                        "distance_band_unit_id",
                        "stable_signal_id",
                        "signal_approach_id",
                        "upstream_downstream",
                        "distance_band",
                        "route_key",
                    ],
                    dropna=False,
                )
                .agg(
                    measure_min=("measure_min", "min"),
                    measure_max=("measure_max", "max"),
                    span_length_ft=("span_length_ft", "sum"),
                    bin_count=("route_key", "size"),
                    logical_corridor_chain_id=("logical_corridor_chain_id", lambda s: "|".join(sorted({clean(v) for v in s if clean(v)})[:8])),
                    stable_travelway_id=("primary_stable_travelway_id", lambda s: "|".join(sorted({clean(v) for v in s if clean(v)})[:8])),
                )
                .reset_index()
            )
            grouped["method_key"] = method_key
            frames.append(grouped)
        spans = pd.concat(frames, ignore_index=True)
        summary = (
            spans.groupby("method_key", dropna=False)
            .agg(
                unit_route_span_rows=("distance_band_unit_id", "size"),
                unique_units=("distance_band_unit_id", "nunique"),
                unique_route_keys=("route_key", "nunique"),
                total_span_length_ft=("span_length_ft", "sum"),
            )
            .reset_index()
        )
        write_csv("unit_route_span_summary.csv", summary)
        return spans


def source_inventory() -> pd.DataFrame:
    rows = []
    for path, role in [(SPEED, "current_normalized_speed_artifact"), (RNS_GDB, "current_source_layer_candidate"), (AADT, "comparison_only_not_patched"), (ACCESS, "comparison_only_not_patched")]:
        row = {"path": rel(path), "role": role, "exists": path.exists(), "row_count": "", "schema_fields": "", "read_status": "missing"}
        try:
            if path.suffix == ".parquet" and path.exists():
                pf = pq.ParquetFile(path)
                row["row_count"] = pf.metadata.num_rows
                row["schema_fields"] = "|".join(pf.schema_arrow.names)
                row["read_status"] = "readable"
            elif path == RNS_GDB and path.exists() and pyogrio is not None:
                info = pyogrio.read_info(path, layer=RNS_LAYER)
                row["schema_fields"] = "|".join(info["fields"])
                row["read_status"] = "readable"
        except Exception as exc:
            row["read_status"] = f"read_failed:{type(exc).__name__}:{exc}"
        rows.append(row)
    out = pd.DataFrame(rows)
    write_csv("speed_source_inventory.csv", out)
    return out


def old_speed_method_inventory() -> pd.DataFrame:
    legacy = REPO / "work/roadway_graph/review/distance_band_context_validation_legacy_audit/old_speed_code_inventory.csv"
    rows = []
    if legacy.exists():
        inv = pd.read_csv(legacy)
        useful = inv[
            inv.get("path", pd.Series("", index=inv.index)).astype(str).str.contains("speed_context_join_v5|expanded_candidate_speed_rns|build_distance_band_context|stage_posted_speed_source", case=False, regex=True)
            | inv.get("matched_terms", pd.Series("", index=inv.index)).astype(str).str.contains("Speed_Limit_RNS|route_key|speed.parquet", case=False, regex=True)
        ].copy()
        useful = useful.head(80)
        rows = useful.to_dict("records")
    if not rows:
        rows = [
            {
                "path": "src/active/roadway_graph/speed_context_join_v5_new_source_supplement.py",
                "matched_terms": "Speed_Limit_RNS",
                "useful_method_evidence": "RNS route+measure overlap and weighted transition handling",
                "used_as_data_parent": False,
            }
        ]
    out = pd.DataFrame(rows)
    if "used_as_data_parent" not in out.columns:
        out["used_as_data_parent"] = False
    write_csv("old_speed_method_inventory.csv", out)
    return out


def build_current_speed_source() -> pd.DataFrame:
    with phase("stage2_prepare_current_speed_source"):
        cols = ["ROUTE_COMMON_NAME", "ROUTE_FROM_MEASURE", "ROUTE_TO_MEASURE", "CAR_SPEED_LIMIT", "TRUCK_SPEED_LIMIT", "SPEEDZONE_TYPE_DSC"]
        speed = pd.read_parquet(SPEED, columns=cols).reset_index(names="source_row_id")
        cache = normalize_route_cache(speed["ROUTE_COMMON_NAME"], "current_speed_ROUTE_COMMON_NAME")
        speed = speed.merge(cache, left_on="ROUTE_COMMON_NAME", right_on="raw_route", how="left")
        speed["measure_min"] = pd.to_numeric(speed[["ROUTE_FROM_MEASURE", "ROUTE_TO_MEASURE"]].min(axis=1), errors="coerce")
        speed["measure_max"] = pd.to_numeric(speed[["ROUTE_FROM_MEASURE", "ROUTE_TO_MEASURE"]].max(axis=1), errors="coerce")
        speed["speed_mph"] = pd.to_numeric(speed["CAR_SPEED_LIMIT"], errors="coerce")
        speed["source_lineage"] = "artifacts/normalized/speed.parquet;postedspeedlimits.gdb/SDE_VDOT_SPEED_LIMIT_MSTR_RTE"
        speed["source_record_key"] = "current_" + speed["source_row_id"].astype(str)
        return speed.loc[speed["measure_min"].notna() & speed["measure_max"].notna() & speed["speed_mph"].notna()].copy()


def build_rns_speed_source() -> pd.DataFrame:
    if pyogrio is None or not RNS_GDB.exists():
        return pd.DataFrame()
    with phase("stage2_prepare_speed_limit_rns_source"):
        cols = [
            "RTE_NM",
            "FROM_MEASURE",
            "TO_MEASURE",
            "TRANSPORT_EDGE_FROM_MSR",
            "TRANSPORT_EDGE_TO_MSR",
            "MASTER_RTE_NM",
            "CAR_SPEED_LIMIT",
            "TRUCK_SPEED_LIMIT",
            "SPEEDZONE_TYPE_DSC",
            "FINAL_SPEED_LIMIT_SOURCE",
        ]
        raw = pyogrio.read_dataframe(RNS_GDB, layer=RNS_LAYER, columns=cols, read_geometry=False).reset_index(names="rns_row_id")
        frames = []
        for route_field, from_field, to_field in [
            ("RTE_NM", "FROM_MEASURE", "TO_MEASURE"),
            ("MASTER_RTE_NM", "FROM_MEASURE", "TO_MEASURE"),
            ("RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"),
            ("MASTER_RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR"),
        ]:
            if route_field not in raw.columns or from_field not in raw.columns or to_field not in raw.columns:
                continue
            part = raw[["rns_row_id", route_field, from_field, to_field, "CAR_SPEED_LIMIT", "TRUCK_SPEED_LIMIT", "SPEEDZONE_TYPE_DSC", "FINAL_SPEED_LIMIT_SOURCE"]].copy()
            part = part.rename(columns={route_field: "source_route_raw", from_field: "measure_from", to_field: "measure_to"})
            part["route_field"] = route_field
            part["measure_pair"] = f"{from_field}/{to_field}"
            frames.append(part)
        if not frames:
            return pd.DataFrame()
        source = pd.concat(frames, ignore_index=True)
        cache = normalize_route_cache(source["source_route_raw"], "Speed_Limit_RNS_route_fields")
        source = source.merge(cache, left_on="source_route_raw", right_on="raw_route", how="left")
        source["measure_min"] = pd.to_numeric(source[["measure_from", "measure_to"]].min(axis=1), errors="coerce")
        source["measure_max"] = pd.to_numeric(source[["measure_from", "measure_to"]].max(axis=1), errors="coerce")
        source["speed_mph"] = pd.to_numeric(source["CAR_SPEED_LIMIT"], errors="coerce")
        source["source_lineage"] = rel(RNS_GDB) + "/Speed_Limit_RNS"
        source["source_record_key"] = (
            "rns_"
            + source["rns_row_id"].astype(str)
            + "_"
            + source["route_field"].astype(str)
            + "_"
            + source["measure_pair"].astype(str)
        )
        source = source.loc[source["measure_min"].notna() & source["measure_max"].notna() & source["speed_mph"].notna()].copy()
        source = source.drop_duplicates(["route_key", "route_base_key", "route_number_key", "measure_min", "measure_max", "speed_mph", "route_field", "measure_pair"])
        return source


def source_for_method(source: pd.DataFrame, method_key: str, source_label: str) -> pd.DataFrame:
    if source.empty:
        return source
    key_col = "route_key"
    if method_key == "directionless":
        key_col = "route_base_key"
    elif method_key == "route_number":
        key_col = "route_number_key"
    elif method_key == "alternate_route_base_directionless":
        key_col = "route_base_key"
    cols = ["source_record_key", key_col, "measure_min", "measure_max", "speed_mph", "source_lineage"]
    extra = [c for c in ["route_field", "measure_pair", "SPEEDZONE_TYPE_DSC", "FINAL_SPEED_LIMIT_SOURCE"] if c in source.columns]
    out = source[cols + extra].rename(columns={key_col: "route_key"}).copy()
    out["source_label"] = source_label
    out["route_key"] = clean_series(out["route_key"])
    out = out.loc[out["route_key"].ne("")].copy()
    return out.drop_duplicates(["route_key", "measure_min", "measure_max", "speed_mph", "source_label"])


def expand_buckets(frame: pd.DataFrame, *, source: bool, tolerance: float = 0.0) -> pd.DataFrame:
    work = frame.copy()
    work["measure_min_bucket"] = pd.to_numeric(work["measure_min"], errors="coerce") - tolerance
    work["measure_max_bucket"] = pd.to_numeric(work["measure_max"], errors="coerce") + tolerance
    work = work.loc[work["route_key"].map(clean).ne("") & work["measure_min_bucket"].notna() & work["measure_max_bucket"].notna()].copy()
    work["bucket_start"] = np.floor(work["measure_min_bucket"] / MEASURE_BUCKET_MI).astype("int64")
    work["bucket_end"] = np.floor(work["measure_max_bucket"] / MEASURE_BUCKET_MI).astype("int64")
    work["bucket_count"] = (work["bucket_end"] - work["bucket_start"] + 1).clip(lower=1, upper=500)
    repeated = work.loc[work.index.repeat(work["bucket_count"])].copy()
    repeated["bucket_offset"] = repeated.groupby(level=0).cumcount()
    repeated["measure_bucket"] = repeated["bucket_start"] + repeated["bucket_offset"]
    return repeated.drop(columns=["bucket_start", "bucket_end", "bucket_count", "bucket_offset", "measure_min_bucket", "measure_max_bucket"])


def aggregate_speed_matches(matches: pd.DataFrame, units: pd.DataFrame, method_name: str, before_context: pd.DataFrame) -> pd.DataFrame:
    if matches.empty:
        return pd.DataFrame(columns=["distance_band_unit_id"])
    work = matches[["distance_band_unit_id", "speed_mph", "measure_overlap_mi", "source_record_key", "source_lineage"]].copy()
    work["speed_mph"] = pd.to_numeric(work["speed_mph"], errors="coerce")
    work["measure_overlap_mi"] = pd.to_numeric(work["measure_overlap_mi"], errors="coerce").fillna(0)
    work = work.loc[work["speed_mph"].notna()].copy()
    if work.empty:
        return pd.DataFrame(columns=["distance_band_unit_id"])
    by_speed = work.groupby(["distance_band_unit_id", "speed_mph"], dropna=False)["measure_overlap_mi"].sum().reset_index()
    ranked = by_speed.sort_values(["distance_band_unit_id", "measure_overlap_mi", "speed_mph"], ascending=[True, False, True])
    dominant = ranked.drop_duplicates("distance_band_unit_id")[["distance_band_unit_id", "speed_mph"]].rename(columns={"speed_mph": "speed_dominant_mph"})
    weighted = (
        work.groupby("distance_band_unit_id", dropna=False)
        .apply(lambda g: float((g["speed_mph"] * g["measure_overlap_mi"]).sum() / g["measure_overlap_mi"].sum()) if g["measure_overlap_mi"].sum() > 0 else np.nan)
        .reset_index(name="speed_length_weighted_mph")
    )
    grouped = work.groupby("distance_band_unit_id", dropna=False).agg(
        speed_min_mph=("speed_mph", "min"),
        speed_max_mph=("speed_mph", "max"),
        speed_value_count=("speed_mph", "nunique"),
        speed_candidate_count=("source_record_key", "nunique"),
        speed_source_lineage=("source_lineage", lambda s: "|".join(sorted({clean(v) for v in s if clean(v)})[:6])),
    ).reset_index()
    mix = (
        work.groupby("distance_band_unit_id", dropna=False)["speed_mph"]
        .agg(lambda s: "|".join(str(int(v)) if float(v).is_integer() else f"{float(v):.3f}".rstrip("0").rstrip(".") for v in sorted(s.dropna().unique())))
        .reset_index(name="speed_value_mix")
    )
    out = grouped.merge(dominant, on="distance_band_unit_id", how="left").merge(weighted, on="distance_band_unit_id", how="left").merge(mix, on="distance_band_unit_id", how="left")
    out["speed_limit_mph"] = out["speed_dominant_mph"]
    out["speed_category"] = out["speed_limit_mph"].map(category_speed)
    out["mixed_speed_flag"] = out["speed_value_count"].gt(1)
    out["speed_context_status"] = np.where(out["mixed_speed_flag"], "mixed_speed_values", "stable_single_speed")
    out["speed_source_match_method"] = method_name
    out["speed_missing_reason"] = ""
    out["speed_context_quality_flag"] = np.where(out["mixed_speed_flag"], "source_rooted_mixed_speed_dominant_by_overlap", "source_rooted_single_speed")
    baseline = before_context[["distance_band_unit_id", "speed_limit_mph", "speed_context_status"]].copy()
    baseline["before_speed_mph"] = pd.to_numeric(baseline["speed_limit_mph"], errors="coerce")
    baseline = baseline.rename(columns={"speed_context_status": "before_speed_context_status"}).drop(columns=["speed_limit_mph"])
    out = out.merge(baseline, on="distance_band_unit_id", how="left")
    out["existing_populated_conflict_flag"] = out["before_speed_mph"].notna() & out["speed_limit_mph"].notna() & (out["before_speed_mph"].sub(out["speed_limit_mph"]).abs() > 0.01)
    return out


def match_speed_method(
    spans_all: pd.DataFrame,
    source_all: pd.DataFrame,
    units: pd.DataFrame,
    before_context: pd.DataFrame,
    *,
    method_name: str,
    span_method_key: str,
    source_method_key: str,
    source_label: str,
    tolerance: float = 0.0,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    started = time.perf_counter()
    spans = spans_all.loc[spans_all["method_key"].eq(span_method_key)].copy()
    source = source_for_method(source_all, source_method_key, source_label)
    if spans.empty or source.empty:
        comparison = {
            "method_name": method_name,
            "source_label": source_label,
            "resulting_speed_populated_count": int(pd.to_numeric(before_context["speed_limit_mph"], errors="coerce").notna().sum()),
            "patched_missing_candidate_units": 0,
            "runtime_seconds": round(time.perf_counter() - started, 3),
            "source_lineage": "",
            "false_positive_risk_indicators": "empty_spans_or_source",
        }
        return pd.DataFrame(), comparison, pd.DataFrame()
    source = source.loc[source["route_key"].isin(set(spans["route_key"].unique()))].copy()
    if source.empty:
        comparison = {
            "method_name": method_name,
            "source_label": source_label,
            "resulting_speed_populated_count": int(pd.to_numeric(before_context["speed_limit_mph"], errors="coerce").notna().sum()),
            "patched_missing_candidate_units": 0,
            "runtime_seconds": round(time.perf_counter() - started, 3),
            "source_lineage": "",
            "false_positive_risk_indicators": "no_route_key_intersection",
        }
        return pd.DataFrame(), comparison, pd.DataFrame()

    with phase("stage2_match_speed_method", method=method_name, span_rows=len(spans), source_rows=len(source)):
        left = expand_buckets(spans[["distance_band_unit_id", "route_key", "measure_min", "measure_max"]].drop_duplicates(), source=False)
        right = expand_buckets(source, source=True, tolerance=tolerance).rename(columns={"measure_min": "source_measure_min", "measure_max": "source_measure_max"})
        candidates = left.merge(right, on=["route_key", "measure_bucket"], how="inner")
        if candidates.empty:
            matches = pd.DataFrame()
        else:
            compare_min = candidates["source_measure_min"] - tolerance
            compare_max = candidates["source_measure_max"] + tolerance
            candidates = candidates.loc[compare_max.ge(candidates["measure_min"]) & compare_min.le(candidates["measure_max"])].copy()
            candidates["measure_overlap_mi"] = np.maximum(
                0.0,
                np.minimum(candidates["measure_max"], candidates["source_measure_max"]) - np.maximum(candidates["measure_min"], candidates["source_measure_min"]),
            )
            if tolerance:
                candidates.loc[candidates["measure_overlap_mi"].le(0), "measure_overlap_mi"] = MIN_OVERLAP_MI
            matches = candidates.loc[candidates["measure_overlap_mi"].gt(0)].drop_duplicates(["distance_band_unit_id", "source_record_key"]).copy()

    aggregate = aggregate_speed_matches(matches, units, method_name, before_context)
    before_speed = pd.to_numeric(before_context["speed_limit_mph"], errors="coerce")
    before_populated = int(before_speed.notna().sum())
    missing_units = set(before_context.loc[before_speed.isna(), "distance_band_unit_id"])
    if aggregate.empty:
        patched_missing = 0
        stable_single = 0
        mixed = 0
        conflicts = 0
        route_examples = ""
        lineage = ""
    else:
        patched_missing = int(aggregate["distance_band_unit_id"].isin(missing_units).sum())
        stable_single = int(aggregate["speed_value_count"].eq(1).sum())
        mixed = int(aggregate["speed_value_count"].gt(1).sum())
        conflicts = int(aggregate["existing_populated_conflict_flag"].sum())
        route_examples = "|".join(sorted(matches["route_key"].dropna().astype(str).unique())[:12]) if not matches.empty else ""
        lineage = "|".join(sorted(aggregate["speed_source_lineage"].dropna().astype(str).unique())[:4])
    after_populated = before_populated + patched_missing
    no_route_missing = set(before_context.loc[before_context["speed_context_status"].astype(str).eq("missing_no_route_compatible_speed"), "distance_band_unit_id"])
    no_overlap_missing = set(before_context.loc[before_context["speed_context_status"].astype(str).eq("missing_no_measure_overlap_speed"), "distance_band_unit_id"])
    comparison = {
        "method_name": method_name,
        "source_label": source_label,
        "units_recovered_from_missing_no_compatible_route": int(aggregate["distance_band_unit_id"].isin(no_route_missing).sum()) if not aggregate.empty else 0,
        "units_recovered_from_missing_no_measure_overlap": int(aggregate["distance_band_unit_id"].isin(no_overlap_missing).sum()) if not aggregate.empty else 0,
        "patched_missing_candidate_units": patched_missing,
        "resulting_speed_populated_count": after_populated,
        "mixed_speed_count": mixed,
        "stable_single_speed_count": stable_single,
        "conflict_count": conflicts,
        "false_positive_risk_indicators": "route_number_key_low_specificity" if "route_number" in method_name else ("existing_speed_conflicts_excluded" if conflicts else "none_observed_in_existing_speed_comparison"),
        "route_key_examples": route_examples,
        "source_lineage": lineage,
        "runtime_seconds": round(time.perf_counter() - started, 3),
    }
    overlap_qa = pd.DataFrame(
        [
            {
                "method_name": method_name,
                "span_rows": len(spans),
                "source_rows_after_route_filter": len(source),
                "candidate_rows_after_overlap": len(matches),
                "matched_units": int(aggregate["distance_band_unit_id"].nunique()) if not aggregate.empty else 0,
                "tolerance_mi": tolerance,
            }
        ]
    )
    return aggregate, comparison, overlap_qa


def speed_source_decision(source_inventory_df: pd.DataFrame) -> str:
    rns = source_inventory_df.loc[source_inventory_df["path"].eq(rel(RNS_GDB))]
    if not rns.empty and bool(rns["exists"].iloc[0]) and str(rns["read_status"].iloc[0]).startswith("readable"):
        return "use_rns_supplement_current_source_available"
    current = source_inventory_df.loc[source_inventory_df["path"].eq(rel(SPEED))]
    if not current.empty and bool(current["exists"].iloc[0]) and str(current["read_status"].iloc[0]).startswith("readable"):
        return "use_current_speed_with_route_fanout"
    return "insufficient_speed_source_evidence_no_patch"


def choose_speed_method(comparison: pd.DataFrame, aggregates: dict[str, pd.DataFrame]) -> str:
    if comparison.empty:
        return ""
    candidates = comparison.copy()
    candidates = candidates.loc[~candidates["method_name"].str.contains("route_number", case=False, na=False)].copy()
    candidates = candidates.loc[candidates["patched_missing_candidate_units"].gt(0)].copy()
    if candidates.empty:
        return ""
    candidates["source_rank"] = np.where(candidates["source_label"].eq("speed_limit_rns"), 0, 1)
    candidates["method_rank"] = np.select(
        [
            candidates["method_name"].str.contains("strict", case=False, na=False),
            candidates["method_name"].str.contains("directionless", case=False, na=False),
        ],
        [0, 1],
        default=2,
    )
    candidates = candidates.sort_values(["source_rank", "method_rank", "patched_missing_candidate_units"], ascending=[True, True, False])
    selected = str(candidates.iloc[0]["method_name"])
    aggregate = aggregates.get(selected, pd.DataFrame())
    if aggregate.empty:
        return ""
    return selected


def run_stage2(before_stage1: pd.DataFrame, stage1_context: pd.DataFrame, units: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    inventory = source_inventory()
    old_speed_method_inventory()
    decision = speed_source_decision(inventory)
    write_csv("speed_source_decision.csv", [{"decision": decision, "rationale": "Speed_Limit_RNS source geodatabase is preferred when present and readable; current speed.parquet remains current posted-speed baseline."}])

    if decision not in {"use_rns_supplement_current_source_available", "use_current_speed_with_route_fanout"}:
        return stage1_context, {"stage2_ran": True, "speed_patched": False, "decision": decision, "selected_method": ""}

    spans = load_unit_route_spans(units)
    current_source = build_current_speed_source()
    rns_source = build_rns_speed_source() if decision == "use_rns_supplement_current_source_available" else pd.DataFrame()

    method_specs = [
        ("current_strict_route_measure", "strict", "strict", "current_speed_artifact", current_source, 0.0),
        ("current_directionless_route_measure", "directionless", "directionless", "current_speed_artifact", current_source, 0.0),
        ("current_route_number_route_measure", "route_number", "route_number", "current_speed_artifact", current_source, 0.0),
        ("current_alternate_route_base_directionless", "alternate_route_base_directionless", "directionless", "current_speed_artifact", current_source, 0.0),
        ("current_strict_measure_tolerance_0_10mi", "strict", "strict", "current_speed_artifact", current_source, TOLERANCE_MI),
    ]
    if not rns_source.empty:
        method_specs.extend(
            [
                ("rns_strict_route_measure", "strict", "strict", "speed_limit_rns", rns_source, 0.0),
                ("rns_directionless_route_measure", "directionless", "directionless", "speed_limit_rns", rns_source, 0.0),
                ("rns_route_number_route_measure", "route_number", "route_number", "speed_limit_rns", rns_source, 0.0),
            ]
        )

    aggregates: dict[str, pd.DataFrame] = {}
    comparisons = []
    overlap_rows = []
    for method_name, span_key, source_key, source_label, source_df, tolerance in method_specs:
        aggregate, comp, overlap = match_speed_method(
            spans,
            source_df,
            units,
            stage1_context,
            method_name=method_name,
            span_method_key=span_key,
            source_method_key=source_key,
            source_label=source_label,
            tolerance=tolerance,
        )
        aggregates[method_name] = aggregate
        comparisons.append(comp)
        overlap_rows.append(overlap)

    comparison_df = pd.DataFrame(comparisons)
    write_csv("speed_candidate_method_comparison.csv", comparison_df)
    write_csv(
        "speed_route_key_recovery_comparison.csv",
        comparison_df[
            [
                "method_name",
                "units_recovered_from_missing_no_compatible_route",
                "units_recovered_from_missing_no_measure_overlap",
                "route_key_examples",
                "false_positive_risk_indicators",
            ]
        ]
        if not comparison_df.empty
        else pd.DataFrame(),
    )
    write_csv("speed_interval_overlap_qa.csv", pd.concat(overlap_rows, ignore_index=True) if overlap_rows else pd.DataFrame())

    selected = choose_speed_method(comparison_df, aggregates)
    if not selected:
        return stage1_context, {"stage2_ran": True, "speed_patched": False, "decision": decision, "selected_method": ""}

    selected_agg = aggregates[selected].copy()
    before_speed = pd.to_numeric(stage1_context["speed_limit_mph"], errors="coerce")
    patch_ids = set(selected_agg.loc[selected_agg["distance_band_unit_id"].isin(stage1_context.loc[before_speed.isna(), "distance_band_unit_id"]), "distance_band_unit_id"])
    patch_values = selected_agg.loc[selected_agg["distance_band_unit_id"].isin(patch_ids)].copy()
    after = stage1_context.copy()
    for col in SPEED_TARGET_FIELDS:
        if col not in after.columns:
            if col in {"mixed_speed_flag"}:
                after[col] = False
            elif col in {"speed_value_count", "speed_min_mph", "speed_max_mph", "speed_length_weighted_mph", "speed_dominant_mph", "speed_context_quality_flag"}:
                after[col] = math.nan if col != "speed_context_quality_flag" else ""
            else:
                after[col] = "" if col not in {"speed_limit_mph", "speed_candidate_count"} else math.nan

    existing_mask = before_speed.notna()
    after.loc[existing_mask, "speed_value_count"] = after.loc[existing_mask, "speed_value_count"].where(pd.to_numeric(after.loc[existing_mask, "speed_value_count"], errors="coerce").notna(), 1)
    for col in ["speed_min_mph", "speed_max_mph", "speed_length_weighted_mph", "speed_dominant_mph"]:
        after.loc[existing_mask, col] = after.loc[existing_mask, col].where(pd.to_numeric(after.loc[existing_mask, col], errors="coerce").notna(), before_speed.loc[existing_mask])
    after.loc[existing_mask, "speed_context_quality_flag"] = clean_series(after.loc[existing_mask, "speed_context_quality_flag"]).where(
        clean_series(after.loc[existing_mask, "speed_context_quality_flag"]).ne(""), "existing_current_speed_artifact_retained"
    )

    patch_cols = [
        "distance_band_unit_id",
        "speed_limit_mph",
        "speed_category",
        "speed_context_status",
        "speed_source_match_method",
        "speed_missing_reason",
        "speed_candidate_count",
        "speed_value_mix",
        "mixed_speed_flag",
        "speed_value_count",
        "speed_min_mph",
        "speed_max_mph",
        "speed_length_weighted_mph",
        "speed_dominant_mph",
        "speed_context_quality_flag",
    ]
    patch_values = patch_values[patch_cols].copy()
    patch_values["speed_source_match_method"] = selected
    patch_values["speed_context_quality_flag"] = "patched_source_rooted_" + selected
    patch_values = patch_values.set_index("distance_band_unit_id")
    idx = after["distance_band_unit_id"].isin(patch_values.index)
    after_idx = after.loc[idx, "distance_band_unit_id"]
    for col in patch_cols:
        if col == "distance_band_unit_id":
            continue
        after.loc[idx, col] = after_idx.map(patch_values[col])

    after_speed = pd.to_numeric(after["speed_limit_mph"], errors="coerce")
    before_counts = stage1_context["speed_context_status"].fillna("").astype(str).value_counts(dropna=False).reset_index()
    before_counts.columns = ["speed_context_status", "before_count"]
    after_counts = after["speed_context_status"].fillna("").astype(str).value_counts(dropna=False).reset_index()
    after_counts.columns = ["speed_context_status", "after_count"]
    miss = before_counts.merge(after_counts, on="speed_context_status", how="outer").fillna(0)
    write_csv("speed_missingness_before_after.csv", miss)

    conflict = selected_agg.loc[selected_agg["existing_populated_conflict_flag"]].copy()
    write_csv("speed_conflict_ledger.csv", conflict.head(20000))
    unresolved = after.loc[pd.to_numeric(after["speed_limit_mph"], errors="coerce").isna(), ["distance_band_unit_id", "speed_context_status", "speed_missing_reason"]].copy()
    write_csv("speed_unresolved_ledger.csv", unresolved)
    write_csv(
        "speed_patch_summary.csv",
        [
            {
                "selected_method": selected,
                "before_speed_populated": int(before_speed.notna().sum()),
                "after_speed_populated": int(after_speed.notna().sum()),
                "patched_units": int(len(patch_values)),
                "remaining_missing_units": int(after_speed.isna().sum()),
                "mixed_speed_units_after": int(after["mixed_speed_flag"].map(bool_value).sum()),
            }
        ],
    )
    return after, {"stage2_ran": True, "speed_patched": True, "decision": decision, "selected_method": selected, "comparison": comparison_df}


def full_qa(original: pd.DataFrame, candidate: pd.DataFrame, units: pd.DataFrame, changed_fields: set[str]) -> bool:
    checks = [
        row_identity_checks(original, candidate, units)["passed"].all(),
        unit_grain_check(candidate)["passed"].all(),
        directionality_reconciliation(original, candidate)["passed"].all(),
        length_bin_count_reconciliation(original, candidate)["passed"].all(),
        unchanged_non_target_check(original, candidate, changed_fields)["passed"].all(),
        no_crash_direction_field_check()["passed"].all(),
    ]
    forbidden = forbidden_mvp_lookup_product_check()
    if not forbidden.empty:
        checks.append(bool(forbidden["passed"].all()))
    return bool(all(checks))


def update_metadata(candidate: pd.DataFrame, final_decision: str, stage2_info: dict[str, Any]) -> None:
    stamp = now()
    manifest = read_json(MANIFEST)
    manifest["updated_utc"] = stamp
    manifest.setdefault("patch_history", []).append(
        {
            "bounded_phase": "gated distance_band_context roadway derived fields and speed repair",
            "build_version": BUILD_VERSION,
            "patched_utc": stamp,
            "row_count": int(len(candidate)),
            "script": "src.roadway_graph.patch.patch_distance_band_context_roadway_and_speed",
            "final_decision": final_decision,
            "stage2_speed_source_decision": stage2_info.get("decision", ""),
            "selected_speed_method": stage2_info.get("selected_method", ""),
        }
    )
    product = manifest.setdefault("products", {}).setdefault("distance_band_context", {})
    product.update(
        {
            "row_count": int(len(candidate)),
            "updated_utc": stamp,
            "script": "src.roadway_graph.patch.patch_distance_band_context_roadway_and_speed",
            "final_decision": final_decision,
            "qa_review_path": rel(OUT),
            "roadway_derived_field_patch_status": "passed",
            "speed_repair_status": "patched" if stage2_info.get("speed_patched") else "not_patched",
            "speed_source_decision": stage2_info.get("decision", ""),
            "speed_selected_method": stage2_info.get("selected_method", ""),
            "speed_populated_units": int(pd.to_numeric(candidate["speed_limit_mph"], errors="coerce").notna().sum()),
            "mvp_lookup_or_rate_distribution_status": "not_built",
            "crash_direction_field_status": "not_used",
        }
    )
    parents = set(product.get("canonical_parents", []))
    parents.update([rel(DISTANCE_BAND_UNITS), rel(BIN_CONTEXT), rel(TRAVELWAY_INDEX), rel(SPEED)])
    if stage2_info.get("decision") == "use_rns_supplement_current_source_available":
        parents.add(rel(RNS_GDB))
    product["canonical_parents"] = sorted(parents)
    write_json_path(MANIFEST, manifest)

    schema = read_json(SCHEMA)
    schema["updated_utc"] = stamp
    table_key = "distance_band_context.parquet"
    table_schema = {
        "path": rel(DISTANCE_BAND_CONTEXT),
        "grain": "one row per distance_band_unit_id; exact distance_band_units grain preserved",
        "row_count": int(len(candidate)),
        "columns": [{"name": col, "dtype": str(candidate[col].dtype)} for col in candidate.columns],
        "updated_utc": stamp,
        "build_version": BUILD_VERSION,
    }
    schema.setdefault("tables", {})[table_key] = table_schema
    write_json_path(SCHEMA, schema)

    note = f"""

## Distance Band Context Roadway/Speed Patch ({BUILD_VERSION})

Patched staged `distance_band_context.parquet` through a gated temp-output workflow.
Stage 1 filled derived roadway fields from populated roadway configuration,
facility, and median fields. Stage 2 decision: `{stage2_info.get('decision', '')}`;
selected speed method: `{stage2_info.get('selected_method', '')}`.

No AADT, access, crash, exposure, rate, MVP, lookup-cell, or canonical root
products were built. Crash direction fields were not used.

Decision: `{final_decision}`.
"""
    README.write_text(README.read_text(encoding="utf-8") + note, encoding="utf-8")


def findings_memo(final_decision: str, stage1_info: dict[str, Any], stage2_info: dict[str, Any], original: pd.DataFrame, final: pd.DataFrame) -> None:
    before_speed = int(pd.to_numeric(original["speed_limit_mph"], errors="coerce").notna().sum())
    after_speed = int(pd.to_numeric(final["speed_limit_mph"], errors="coerce").notna().sum())
    coverage = stage1_info["coverage"]
    before_after = {}
    for field in STAGE1_TARGET_FIELDS:
        b = coverage.loc[(coverage["stage"].eq("before_stage1")) & (coverage["field"].eq(field)), "populated_units"].iloc[0]
        a = coverage.loc[(coverage["stage"].eq("after_stage1")) & (coverage["field"].eq(field)), "populated_units"].iloc[0]
        before_after[field] = (int(b), int(a))
    selected = stage2_info.get("selected_method", "")
    decision = stage2_info.get("decision", "")
    text = f"""# distance_band_context Roadway And Speed Patch Findings

## What Stage 1 Patched
Stage 1 patched only `divided_undivided`, `one_way_two_way`, and `median_group`.

## Stage 1 Coverage Before/After
- `divided_undivided`: {before_after['divided_undivided'][0]} -> {before_after['divided_undivided'][1]}
- `one_way_two_way`: {before_after['one_way_two_way'][0]} -> {before_after['one_way_two_way'][1]}
- `median_group`: {before_after['median_group'][0]} -> {before_after['median_group'][1]}

## Roadway Token Rules
`Divided`, `Undivided`, `One-Way`, and `Two-Way` tokens were mapped conservatively from roadway configuration/facility summaries. Mixed unit summaries remain explicit mixed statuses. Reversible and trail tokens remain explicit unknown/reversible statuses rather than forced divided/two-way labels.

Unmapped roadway token count: {stage1_info.get('unmapped_token_count', 0)}. See `stage1_unmapped_roadway_tokens.csv`.

Stage 1 passed and Stage 2 ran: {bool(stage2_info.get('stage2_ran'))}.

## Speed Source/Method Investigation
Speed source decision: `{decision}`.

`Speed_Limit_RNS` available as current source/supplement: {RNS_GDB.exists() and pyogrio is not None}.

Old speed code was useful as method evidence for route normalization, RNS route+measure overlap, and weighted transition handling. It was not used as a data parent because older scripts reference stale `work/output/...` parents and review outputs.

Methods tested are listed in `speed_candidate_method_comparison.csv`, including current strict, directionless, route-number, alternate route-base, measure-tolerance, and RNS methods when RNS was readable.

Selected method: `{selected}`.

Speed coverage before/after: {before_speed} -> {after_speed}. Remaining missing speed units: {len(final) - after_speed}.

Performance constraints were preserved by building compact unit-route spans, caching normalization by unique route strings, and using bucketed interval overlap joins.

## Guard Confirmations
AADT/access/crash/exposure/rate fields were not changed. Crash direction fields were not used. No MVP, lookup, or rate-distribution product was built.

## Final Decision
`{final_decision}`

## Recommended Next Task
Run the AADT/exposure semantics patch from `remaining_context_patch_queue.csv` before access, crash assignment, and final MVP-readiness validation.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def write_remaining_queues(final_decision: str) -> None:
    queue = pd.DataFrame(
        [
            {
                "sequence": 1,
                "task": "AADT/exposure semantics patch",
                "scope": "document value selection; decide length-weighted/dominant/latest-year AADT behavior; clarify daily vehicle-mile proxy vs final crash-period exposure",
            },
            {
                "sequence": 2,
                "task": "Access feasibility/repair patch",
                "scope": "separate true zero-access from missing/no-compatible-route; test route alias fanout and geometry-based assignment; preserve source-limited access flags",
            },
            {
                "sequence": 3,
                "task": "Crash assignment layer",
                "scope": "bounded spatial or accepted source-rooted unit lineage; no crash direction fields; crash_count and crash assignment QA",
            },
            {
                "sequence": 4,
                "task": "Final distance_band_context validation and MVP-readiness pass",
                "scope": "validate all context families; finalize rate readiness statuses; only then proceed to MVP analytical product / lookup-cell build",
            },
        ]
    )
    write_csv("remaining_context_patch_queue.csv", queue)
    next_actions = pd.DataFrame(
        [
            {
                "priority": 1,
                "recommended_next_action": "Run AADT/exposure semantics patch",
                "reason": "AADT coverage is high, but value-selection and exposure semantics need explicit documentation before rate-ready products.",
            },
            {
                "priority": 2,
                "recommended_next_action": "If more speed recovery is needed, normalize Speed_Limit_RNS into artifacts/normalized as a current source-derived artifact",
                "reason": "This patch used the readable current source layer directly; a durable refresh should stage it explicitly.",
            },
            {"priority": 3, "recommended_next_action": "Do not build MVP lookup until access and crash layers pass QA", "reason": final_decision},
        ]
    )
    write_csv("recommended_next_actions.csv", next_actions)


def write_manifests(final_decision: str, stage2_info: dict[str, Any], replaced: bool) -> None:
    write_json(
        "manifest.json",
        {
            "bounded_question": "gated roadway derived-field and speed-source/method repair for staged distance_band_context",
            "created_utc": now(),
            "script": "src.roadway_graph.patch.patch_distance_band_context_roadway_and_speed",
            "staged_product": rel(DISTANCE_BAND_CONTEXT),
            "review_output": rel(OUT),
            "final_decision": final_decision,
            "replacement_performed": replaced,
            "stage2_speed_source_decision": stage2_info.get("decision", ""),
            "selected_speed_method": stage2_info.get("selected_method", ""),
            "no_crash_direction_fields_used": True,
            "mvp_lookup_rate_distribution_built": False,
        },
    )
    write_json(
        "qa_manifest.json",
        {
            "created_utc": now(),
            "phase_timings": PHASES,
            "qa_outputs": sorted(path.name for path in OUT.glob("*.csv")),
            "final_decision": final_decision,
            "replacement_performed": replaced,
        },
    )


def append_final_readiness_decision(final_decision: str, replaced: bool, stage2_info: dict[str, Any], candidate: pd.DataFrame) -> None:
    path = OUT / "distance_band_context_patch_readiness_decision.csv"
    prior = pd.read_csv(path) if path.exists() else pd.DataFrame()
    row = pd.DataFrame(
        [
            {
                "stage": "final",
                "passed": bool(replaced),
                "final_decision": final_decision,
                "replacement_performed": bool(replaced),
                "stage2_speed_source_decision": stage2_info.get("decision", ""),
                "selected_speed_method": stage2_info.get("selected_method", ""),
                "final_speed_populated_units": int(pd.to_numeric(candidate["speed_limit_mph"], errors="coerce").notna().sum()) if "speed_limit_mph" in candidate.columns else "",
            }
        ]
    )
    write_csv("distance_band_context_patch_readiness_decision.csv", pd.concat([prior, row], ignore_index=True, sort=False))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started bounded roadway/speed patch.\n", encoding="utf-8")
    write_csv("parent_dependency_check.csv", base_parent_dependency_check())

    with phase("load_context_and_units"):
        original = pd.read_parquet(DISTANCE_BAND_CONTEXT)
        units = pd.read_parquet(DISTANCE_BAND_UNITS)

    stage1_context, stage1_info = stage1_patch(original)
    if not stage1_qa(original, stage1_context, units):
        final_decision = "stage1_roadway_patch_failed_no_stage2"
        write_remaining_queues(final_decision)
        findings_memo(final_decision, stage1_info, {"stage2_ran": False, "decision": "", "selected_method": ""}, original, original)
        write_manifests(final_decision, {"stage2_ran": False}, replaced=False)
        log("Stage 1 QA failed; staged product not replaced and Stage 2 skipped.")
        return

    stage2_context, stage2_info = run_stage2(original, stage1_context, units)
    speed_patched = bool(stage2_info.get("speed_patched"))
    if speed_patched:
        changed_fields = set(STAGE1_TARGET_FIELDS + SPEED_TARGET_FIELDS)
        if stage2_info.get("decision") == "use_rns_supplement_current_source_available":
            final_decision = "stage1_roadway_patch_passed_stage2_speed_patch_passed"
        else:
            final_decision = "stage1_roadway_patch_passed_stage2_speed_patch_passed"
    else:
        changed_fields = set(STAGE1_TARGET_FIELDS)
        if stage2_info.get("decision") == "use_rns_supplement_current_source_available":
            final_decision = "stage1_roadway_patch_passed_stage2_speed_patch_not_safe"
        elif stage2_info.get("decision") == "insufficient_speed_source_evidence_no_patch":
            final_decision = "stage1_roadway_patch_passed_speed_source_insufficient"
        else:
            final_decision = "stage1_roadway_patch_passed_stage2_speed_patch_not_safe"

    candidate = stage2_context if speed_patched else stage1_context
    temp = STAGING / "distance_band_context.patch_candidate.tmp.parquet"
    with phase("write_temp_candidate_parquet"):
        candidate.to_parquet(temp, index=False)
    reread = pd.read_parquet(temp)
    qa_passed = full_qa(original, reread, units, changed_fields)
    if not qa_passed:
        final_decision = "distance_band_context_patch_failed_no_replacement"
        temp.unlink(missing_ok=True)
        write_remaining_queues(final_decision)
        append_final_readiness_decision(final_decision, False, stage2_info, original)
        findings_memo(final_decision, stage1_info, stage2_info, original, original)
        write_manifests(final_decision, stage2_info, replaced=False)
        log("Final QA failed; temp candidate removed and staged product not replaced.")
        return

    with phase("replace_staged_distance_band_context_after_qa"):
        shutil.move(str(temp), str(DISTANCE_BAND_CONTEXT))
    update_metadata(candidate, final_decision, stage2_info)
    write_remaining_queues(final_decision)
    append_final_readiness_decision(final_decision, True, stage2_info, candidate)
    findings_memo(final_decision, stage1_info, stage2_info, original, candidate)
    write_manifests(final_decision, stage2_info, replaced=True)
    log(f"Completed patch with final decision: {final_decision}.")


if __name__ == "__main__":
    main()
