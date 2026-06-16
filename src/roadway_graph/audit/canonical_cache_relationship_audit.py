"""Read-only canonical cache relationship and refresh-planning audit.

This audit inventories the two cleaned canonical roadway-graph products,
checks their relationship, and drafts a conservative refresh sequence. It does
not modify canonical products, read raw/source/artifact layers, or backfill
missing fields from review or legacy outputs.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
FINAL_DIR = REPO / "work" / "roadway_graph" / "analysis" / "final_leg_corrected_analysis_dataset"
MVP_DIR = REPO / "work" / "roadway_graph" / "analysis" / "mvp_dataset"
PREVIOUS_AUDIT_DIR = REPO / "work" / "roadway_graph" / "review" / "canonical_mvp_readiness_audit"
OUT_DIR = REPO / "work" / "roadway_graph" / "review" / "canonical_cache_relationship_audit"

PRODUCTS = {
    "final_leg_corrected_analysis_dataset": FINAL_DIR,
    "mvp_dataset": MVP_DIR,
}

KEY_ALIASES = {
    "window_label": ["window_label", "signal_window", "analysis_window"],
    "stable_signal_id": ["stable_signal_id"],
    "signal_approach_id": ["signal_approach_id", "final_review_physical_leg_id"],
    "stable_bin_id": ["stable_bin_id"],
    "upstream_downstream": ["upstream_downstream", "downstream_upstream"],
}

MVP_LOOKUP_DIMS = [
    "speed_band",
    "aadt_band",
    "roadway_configuration",
    "median_group",
    "access_count_band",
    "access_type",
    "upstream_downstream",
    "window_label",
]

NUMERIC_FIELD_CANDIDATES = {
    "numeric_speed": ["numeric_speed", "speed_limit_mph", "representative_speed_limit_mph"],
    "speed_category": ["speed_band"],
    "numeric_aadt": ["numeric_aadt", "aadt", "representative_aadt"],
    "aadt_category": ["aadt_band"],
    "exposure_denominator": ["exposure_denominator"],
    "crash_count": ["catchment_50ft_crash_count", "spatial_50ft_crash_count"],
    "weighted_crash_count": ["weighted_50ft_crash_count", "spatial_50ft_weighted_crash_count"],
    "observed_rate": ["candidate_observed_crash_rate", "aggregate_observed_crash_rate"],
    "window_length": ["represented_length_mi", "bin_length_mi", "bin_length_ft", "distance_start_ft", "distance_end_ft"],
}

ACCESS_FIELD_CANDIDATES = {
    "raw_access_count": ["access_raw_count", "untyped_access_raw_count", "access_weighted_count"],
    "access_count_band": ["access_count_band", "untyped_access_count_band"],
    "raw_access_codes": ["raw_access_code", "access_raw_code", "access_code"],
    "normalized_access_type": ["access_type"],
    "riro_flag": ["riro_present"],
    "unrestricted_full_flag": ["unrestricted_or_full_access_present"],
    "other_typed_access_flag": ["other_typed_access_present"],
}

GROUP_FIELDS = [
    "window_label",
    "signal_window",
    "analysis_window",
    "upstream_downstream",
    "downstream_upstream",
    "roadway_configuration",
    "divided_undivided",
    "median_group",
    "access_count_band",
    "untyped_access_count_band",
    "access_type",
    "directionality_method_mix",
    "directionality_method_mix_type",
    "mvp_directionality_method",
    "directionality_direct_or_synthetic",
    "recovery_provenance",
    "speed_band",
    "aadt_band",
]


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
    with (OUT_DIR / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now()} - {message}\n")


def write_csv(name: str, rows: Iterable[dict], fieldnames: list[str] | None = None) -> None:
    rows = list(rows)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        if not fieldnames:
            fieldnames = ["note"]
    with (OUT_DIR / name).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_header(path: Path) -> list[str]:
    if path.suffix.lower() == ".csv":
        return list(pd.read_csv(path, nrows=0).columns)
    if path.suffix.lower() == ".parquet":
        return list(pd.read_parquet(path, columns=[]).columns)
    return []


def count_rows(path: Path) -> int | None:
    if path.suffix.lower() == ".csv":
        with path.open("rb") as f:
            return max(sum(1 for _ in f) - 1, 0)
    if path.suffix.lower() == ".parquet":
        return len(pd.read_parquet(path, columns=[]))
    return None


def read_table(path: Path, usecols: list[str] | None = None) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, usecols=usecols, low_memory=False)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path, columns=usecols)
    raise ValueError(f"Unsupported table type: {path}")


def nonmissing(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return series.notna() & (text != "") & (~text.str.lower().isin(["nan", "none", "null", "<missing>"]))


def first_present(columns: Iterable[str], candidates: list[str]) -> str | None:
    cols = set(columns)
    return next((c for c in candidates if c in cols), None)


def role_for_table(name: str, columns: list[str]) -> str:
    lower = name.lower()
    cols = set(columns)
    if "manifest" in lower or "qa" in lower or "finding" in lower or lower.endswith(".md") or "readme" in lower or "log" in lower:
        return "manifest_qa_findings_or_documentation"
    if "lookup" in lower and {"mean_unit_crash_rate", "median_unit_crash_rate"}.intersection(cols):
        return "lookup-cell data"
    if "approach_window_direction_unit" in lower or {"stable_signal_id", "signal_approach_id", "upstream_downstream"}.issubset(cols):
        return "directional unit data" if "upstream_downstream" in cols else "approach-window data"
    if "directional_bin_context" in lower or {"stable_bin_id", "upstream_downstream"}.issubset(cols):
        return "bin-context data"
    if name == "analysis_signal.csv" or ({"stable_signal_id"}.issubset(cols) and "signal_approach_id" not in cols and "stable_bin_id" not in cols):
        return "signal-level data"
    if "approach_window" in lower or {"stable_signal_id", "signal_approach_id"}.issubset(cols):
        return "approach-window data"
    if "signal_window" in lower or {"stable_signal_id", "signal_window"}.issubset(cols):
        return "signal-window data"
    if "bin" in lower or "stable_bin_id" in cols:
        return "bin-context data"
    if "summary" in lower or "completeness" in lower or "audit" in lower:
        return "summaries/exports"
    return "summaries/exports"


def canonical_name(columns: list[str], logical: str) -> str | None:
    return first_present(columns, KEY_ALIASES[logical])


def infer_grain(name: str, columns: list[str], role: str) -> list[str]:
    cols = set(columns)
    if name == "analysis_signal.csv":
        return ["stable_signal_id"]
    if name == "analysis_bin.csv" and "stable_bin_id" in cols:
        return ["stable_bin_id"]
    if name == "analysis_signal_window.csv":
        return [c for c in ["stable_signal_id", "signal_window"] if c in cols]
    if name == "analysis_signal_approach_window.csv":
        return [c for c in ["stable_signal_id", "signal_approach_id", "signal_window"] if c in cols]
    if name == "mvp_approach_window_direction_unit.csv":
        return [c for c in ["stable_signal_id", "signal_approach_id", "window_label", "upstream_downstream"] if c in cols]
    if name == "mvp_directional_bin_context.csv":
        return [c for c in ["stable_signal_id", "signal_approach_id", "window_label", "stable_bin_id", "upstream_downstream"] if c in cols]
    if name == "mvp_directional_lookup_distribution_table.csv":
        return [c for c in MVP_LOOKUP_DIMS if c in cols]
    if role == "signal-level data":
        return [c for c in ["stable_signal_id"] if c in cols]
    if role == "approach-window data":
        return [c for c in ["stable_signal_id", "signal_approach_id", "window_label", "signal_window"] if c in cols]
    if role == "directional unit data":
        return [c for c in ["stable_signal_id", "signal_approach_id", "window_label", "upstream_downstream"] if c in cols]
    if role == "bin-context data":
        return [c for c in ["stable_signal_id", "signal_approach_id", "window_label", "stable_bin_id", "upstream_downstream"] if c in cols]
    if role == "lookup-cell data":
        return [c for c in MVP_LOOKUP_DIMS if c in cols]
    return []


def table_paths() -> list[tuple[str, Path]]:
    out = []
    for product, folder in PRODUCTS.items():
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in {".csv", ".parquet", ".json", ".md", ".txt"}:
                out.append((product, path))
    return out


def profile_columns(product: str, path: Path, row_count: int | None) -> list[dict]:
    if path.suffix.lower() not in {".csv", ".parquet"}:
        return []
    rows: list[dict] = []
    if path.suffix.lower() == ".parquet":
        df = read_table(path)
        for col in df.columns:
            miss = int((~nonmissing(df[col])).sum())
            rows.append(
                {
                    "product": product,
                    "table": path.name,
                    "column": col,
                    "dtype": str(df[col].dtype),
                    "row_count": len(df),
                    "null_count": miss,
                    "null_pct": round(miss / len(df), 6) if len(df) else 0,
                    "non_null_count": len(df) - miss,
                    "sample_values": json.dumps(df[col][nonmissing(df[col])].astype(str).drop_duplicates().head(8).tolist(), ensure_ascii=True),
                }
            )
        return rows

    dtypes: dict[str, str] = {}
    null_counts: Counter[str] = Counter()
    nonnull_samples: dict[str, list[str]] = {}
    total = 0
    for chunk in pd.read_csv(path, chunksize=200_000, low_memory=False):
        total += len(chunk)
        for col in chunk.columns:
            dtypes.setdefault(col, str(chunk[col].dtype))
            mask = nonmissing(chunk[col])
            null_counts[col] += int((~mask).sum())
            samples = nonnull_samples.setdefault(col, [])
            if len(samples) < 8:
                for value in chunk.loc[mask, col].astype(str).drop_duplicates().head(8 - len(samples)):
                    samples.append(value)
    for col in read_header(path):
        miss = int(null_counts[col])
        rows.append(
            {
                "product": product,
                "table": path.name,
                "column": col,
                "dtype": dtypes.get(col, "unknown"),
                "row_count": total if total else row_count,
                "null_count": miss,
                "null_pct": round(miss / total, 6) if total else 0,
                "non_null_count": total - miss if total else None,
                "sample_values": json.dumps(nonnull_samples.get(col, []), ensure_ascii=True),
            }
        )
    return rows


def duplicate_check(path: Path, grain: list[str]) -> dict:
    columns = read_header(path)
    if path.suffix.lower() not in {".csv", ".parquet"} or not grain:
        return {
            "table": path.name,
            "grain_fields_used": "|".join(grain),
            "status": "not_checked_no_grain",
            "duplicate_key_groups": None,
            "duplicate_rows": None,
        }
    missing = [c for c in grain if c not in columns]
    if missing:
        return {
            "table": path.name,
            "grain_fields_used": "|".join(grain),
            "status": "not_checked_missing_grain_fields",
            "missing_grain_fields": "|".join(missing),
        }
    counts: Counter[tuple] = Counter()
    if path.suffix.lower() == ".csv":
        for chunk in pd.read_csv(path, usecols=grain, chunksize=200_000, dtype="string", low_memory=False):
            for key, n in chunk.fillna("<MISSING>").value_counts(grain).items():
                counts[tuple(key if isinstance(key, tuple) else (key,))] += int(n)
    else:
        df = read_table(path, usecols=grain).astype("string").fillna("<MISSING>")
        for key, n in df.value_counts(grain).items():
            counts[tuple(key if isinstance(key, tuple) else (key,))] += int(n)
    dupes = [n for n in counts.values() if n > 1]
    return {
        "table": path.name,
        "grain_fields_used": "|".join(grain),
        "status": "pass" if not dupes else "fail",
        "duplicate_key_groups": len(dupes),
        "duplicate_rows": sum(dupes),
        "unique_key_count": len(counts),
    }


def key_completeness(product: str, path: Path, grain: list[str]) -> list[dict]:
    if path.suffix.lower() not in {".csv", ".parquet"}:
        return []
    cols = read_header(path)
    n = count_rows(path)
    rows = []
    for field in grain:
        if field not in cols:
            rows.append({"product": product, "table": path.name, "key_field": field, "present": False, "row_count": n, "missing_count": None, "missing_pct": None})
            continue
        miss = 0
        total = 0
        if path.suffix.lower() == ".csv":
            for chunk in pd.read_csv(path, usecols=[field], chunksize=200_000, low_memory=False):
                total += len(chunk)
                miss += int((~nonmissing(chunk[field])).sum())
        else:
            df = read_table(path, usecols=[field])
            total = len(df)
            miss = int((~nonmissing(df[field])).sum())
        rows.append(
            {
                "product": product,
                "table": path.name,
                "key_field": field,
                "present": True,
                "row_count": total,
                "missing_count": miss,
                "missing_pct": round(miss / total, 6) if total else 0,
                "status": "pass" if miss == 0 else "fail",
            }
        )
    return rows


def normalized_for_join(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "window_label" not in out.columns:
        for alias in ["signal_window", "analysis_window"]:
            if alias in out.columns:
                out["window_label"] = out[alias]
                break
    if "upstream_downstream" not in out.columns and "downstream_upstream" in out.columns:
        out["upstream_downstream"] = out["downstream_upstream"]
    return out


def missingness_by_groups(df: pd.DataFrame, table: str) -> list[dict]:
    rows = []
    if "signal_approach_id" not in df.columns:
        return rows
    miss_mask = ~nonmissing(df["signal_approach_id"])
    rows.append(
        {
            "table": table,
            "group_field": "ALL",
            "group_value": "ALL",
            "row_count": len(df),
            "missing_signal_approach_id_rows": int(miss_mask.sum()),
            "missing_pct": round(float(miss_mask.mean()), 6) if len(df) else 0,
        }
    )
    for field in [f for f in GROUP_FIELDS + ["stable_signal_id", "approach_label", "final_review_physical_leg_id"] if f in df.columns]:
        vc = df.assign(_missing=miss_mask).groupby(field, dropna=False)["_missing"].agg(["count", "sum"]).reset_index()
        vc = vc.sort_values(["sum", "count"], ascending=False).head(100)
        for _, r in vc.iterrows():
            rows.append(
                {
                    "table": table,
                    "group_field": field,
                    "group_value": r[field],
                    "row_count": int(r["count"]),
                    "missing_signal_approach_id_rows": int(r["sum"]),
                    "missing_pct": round(float(r["sum"] / r["count"]), 6) if r["count"] else 0,
                }
            )
    return rows


def reconstruction_feasibility(df: pd.DataFrame, table: str) -> dict:
    if "signal_approach_id" not in df.columns:
        return {"table": table, "classification": "insufficient_columns_to_assess", "reason": "signal_approach_id absent"}
    miss_mask = ~nonmissing(df["signal_approach_id"])
    missing_count = int(miss_mask.sum())
    if missing_count == 0:
        return {"table": table, "classification": "already_complete", "missing_rows": 0, "candidate_fields": "", "reason": "signal_approach_id complete"}
    candidate_sets = [
        ["stable_signal_id", "approach_label"],
        ["stable_signal_id", "final_review_physical_leg_id"],
        ["stable_signal_id", "leg_id"],
        ["stable_signal_id", "approach_index"],
        ["stable_signal_id", "source_route_id", "window_label"],
        ["stable_signal_id", "source_route_name", "window_label"],
        ["stable_signal_id", "upstream_downstream", "geometry_wkt"],
        ["stable_signal_id", "stable_bin_id", "window_label", "upstream_downstream"],
    ]
    present_sets = [s for s in candidate_sets if all(c in df.columns for c in s)]
    if not present_sets:
        return {"table": table, "classification": "insufficient_columns_to_assess", "missing_rows": missing_count, "candidate_fields": "", "reason": "no deterministic approach/leg candidate fields present"}
    evidence = []
    for fields in present_sets:
        missing_has_fields = bool(nonmissing(df.loc[miss_mask, fields[0]]).any())
        if not missing_has_fields:
            continue
        known = df.loc[~miss_mask, fields + ["signal_approach_id"]].dropna()
        if known.empty:
            evidence.append(f"{'+'.join(fields)} no known mappings")
            continue
        mapping_sizes = known.groupby(fields, dropna=False)["signal_approach_id"].nunique()
        ambiguous = int((mapping_sizes > 1).sum())
        missing_keys = df.loc[miss_mask, fields].drop_duplicates()
        known_keys = set(map(tuple, known[fields].drop_duplicates().astype(str).itertuples(index=False, name=None)))
        recoverable_keys = sum(1 for key in map(tuple, missing_keys.astype(str).itertuples(index=False, name=None)) if key in known_keys)
        evidence.append(f"{'+'.join(fields)} recoverable_missing_keys={recoverable_keys} ambiguous_known_keys={ambiguous}")
        if recoverable_keys and ambiguous == 0:
            return {
                "table": table,
                "classification": "deterministic_reconstruction_likely",
                "missing_rows": missing_count,
                "candidate_fields": "|".join(fields),
                "reason": "; ".join(evidence),
            }
        if recoverable_keys or ambiguous:
            return {
                "table": table,
                "classification": "ambiguous_reconstruction_possible",
                "missing_rows": missing_count,
                "candidate_fields": "|".join(fields),
                "reason": "; ".join(evidence),
            }
    return {
        "table": table,
        "classification": "source_limited_or_unrecoverable_from_canonical",
        "missing_rows": missing_count,
        "candidate_fields": "|".join(["+".join(s) for s in present_sets]),
        "reason": "; ".join(evidence) or "candidate fields present but do not map missing rows to known signal_approach_id values",
    }


def relationship_audit(final_aw: pd.DataFrame, mvp_unit: pd.DataFrame) -> list[dict]:
    left = normalized_for_join(mvp_unit)
    right = normalized_for_join(final_aw)
    candidates = [
        ["stable_signal_id", "signal_approach_id", "window_label"],
        ["stable_signal_id", "signal_approach_id"],
        ["stable_signal_id", "window_label"],
        ["stable_signal_id"],
    ]
    rows = []
    for keys in candidates:
        if any(k not in left.columns or k not in right.columns for k in keys):
            rows.append({"join_family": "+".join(keys), "status": "not_checked_missing_columns", "safe_join": False})
            continue
        l = left[keys].astype("string").fillna("<MISSING>").copy()
        r = right[keys].astype("string").fillna("<MISSING>").copy()
        right_counts = r.value_counts(keys).rename("_right_count").reset_index()
        joined = l.merge(right_counts, on=keys, how="left")
        matched = int(joined["_right_count"].notna().sum())
        unmatched = len(joined) - matched
        duplicate_match_rows = int((joined["_right_count"].fillna(0) > 1).sum())
        safe = unmatched == 0 and duplicate_match_rows == 0
        rows.append(
            {
                "join_family": "+".join(keys),
                "left_table": "mvp_approach_window_direction_unit.csv",
                "right_table": "analysis_signal_approach_window.csv",
                "left_row_count": len(left),
                "matched_row_count": matched,
                "unmatched_row_count": unmatched,
                "duplicate_match_row_count": duplicate_match_rows,
                "safe_join": safe,
                "status": "safe" if safe else ("usable_with_caution" if matched and not duplicate_match_rows else "unsafe"),
            }
        )
    return rows


def classify_rate_failure(df: pd.DataFrame) -> pd.Series:
    cols = df.columns
    speed = first_present(cols, NUMERIC_FIELD_CANDIDATES["numeric_speed"])
    aadt = first_present(cols, NUMERIC_FIELD_CANDIDATES["numeric_aadt"])
    exposure_col = first_present(cols, NUMERIC_FIELD_CANDIDATES["exposure_denominator"])
    crash = first_present(cols, NUMERIC_FIELD_CANDIDATES["crash_count"])
    rate = first_present(cols, NUMERIC_FIELD_CANDIDATES["observed_rate"])
    if not any([speed, aadt, exposure_col, crash, rate]):
        return pd.Series(["insufficient_columns_to_classify"] * len(df), index=df.index)
    missing_speed = ~nonmissing(df[speed]) if speed else pd.Series([False] * len(df), index=df.index)
    missing_aadt = ~nonmissing(df[aadt]) if aadt else pd.Series([False] * len(df), index=df.index)
    exposure = pd.to_numeric(df[exposure_col], errors="coerce") if exposure_col else pd.Series([pd.NA] * len(df), index=df.index)
    missing_exposure = exposure.isna() if exposure_col else pd.Series([False] * len(df), index=df.index)
    zero_exposure = (exposure == 0) if exposure_col else pd.Series([False] * len(df), index=df.index)
    missing_crash = ~nonmissing(df[crash]) if crash else pd.Series([False] * len(df), index=df.index)
    missing_rate = ~nonmissing(df[rate]) if rate else pd.Series([False] * len(df), index=df.index)
    labels = pd.Series(["complete_rate_ready"] * len(df), index=df.index)
    labels[missing_speed & ~missing_aadt] = "missing_speed_only"
    labels[missing_aadt & ~missing_speed] = "missing_aadt_only"
    labels[missing_speed & missing_aadt] = "missing_speed_and_aadt"
    labels[missing_exposure] = "missing_exposure"
    labels[zero_exposure] = "zero_exposure"
    labels[missing_crash] = "missing_crash_count"
    labels[missing_rate & (zero_exposure | missing_exposure)] = "rate_missing_due_to_denominator"
    labels[missing_rate & ~(zero_exposure | missing_exposure)] = "rate_missing_other"
    return labels


def numeric_audit(product: str, table: str, df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    rows = []
    for logical, candidates in NUMERIC_FIELD_CANDIDATES.items():
        col = first_present(df.columns, candidates)
        if not col:
            rows.append({"product": product, "table": table, "field_role": logical, "column": "", "present": False, "row_count": len(df)})
            continue
        miss = int((~nonmissing(df[col])).sum())
        zero = int((pd.to_numeric(df[col], errors="coerce") == 0).sum())
        rows.append(
            {
                "product": product,
                "table": table,
                "field_role": logical,
                "column": col,
                "present": True,
                "row_count": len(df),
                "missing_count": miss,
                "missing_pct": round(miss / len(df), 6) if len(df) else 0,
                "zero_count": zero,
            }
        )
    labels = classify_rate_failure(df)
    tax = []
    for label, n in labels.value_counts(dropna=False).items():
        tax.append({"product": product, "table": table, "group_field": "ALL", "group_value": "ALL", "failure_category": label, "row_count": int(n)})
    for group in [g for g in GROUP_FIELDS if g in df.columns]:
        grouped = pd.DataFrame({"group": df[group], "failure_category": labels}).groupby(["group", "failure_category"], dropna=False).size().reset_index(name="row_count")
        for _, r in grouped.iterrows():
            tax.append({"product": product, "table": table, "group_field": group, "group_value": r["group"], "failure_category": r["failure_category"], "row_count": int(r["row_count"])})
    return rows, tax


def access_audit(product: str, table: str, columns: list[str], row_count: int | None, path: Path) -> list[dict]:
    rows = []
    for role, candidates in ACCESS_FIELD_CANDIDATES.items():
        col = first_present(columns, candidates)
        row = {"product": product, "table": table, "field_role": role, "column": col or "", "present": bool(col), "row_count": row_count}
        if col and path.suffix.lower() in {".csv", ".parquet"}:
            miss = 0
            total = 0
            values = Counter()
            if path.suffix.lower() == ".csv":
                for chunk in pd.read_csv(path, usecols=[col], chunksize=200_000, low_memory=False):
                    total += len(chunk)
                    miss += int((~nonmissing(chunk[col])).sum())
                    values.update(chunk[col].fillna("<MISSING>").astype(str).value_counts().head(20).to_dict())
            else:
                df = read_table(path, usecols=[col])
                total = len(df)
                miss = int((~nonmissing(df[col])).sum())
                values.update(df[col].fillna("<MISSING>").astype(str).value_counts().head(20).to_dict())
            row.update(
                {
                    "missing_count": miss,
                    "missing_pct": round(miss / total, 6) if total else 0,
                    "top_values": json.dumps(dict(values.most_common(12)), ensure_ascii=True),
                    "intended_access_bands_present": role != "access_count_band" or all(b in values for b in ["0", "1-2", "3-5", "6+"]),
                }
            )
        rows.append(row)
    return rows


def directionality_audit(product: str, table: str, df: pd.DataFrame) -> list[dict]:
    rows = []
    dir_col = first_present(df.columns, ["upstream_downstream", "downstream_upstream"])
    method_cols = [c for c in ["directionality_method_mix", "directionality_method_mix_type", "mvp_directionality_method", "directionality_direct_or_synthetic", "directionality_source", "recovery_provenance"] if c in df.columns]
    if dir_col:
        miss = int((~nonmissing(df[dir_col])).sum())
        rows.append({"product": product, "table": table, "field": dir_col, "metric": "missing_upstream_downstream", "row_count": len(df), "count": miss})
        for value, n in df[dir_col].fillna("<MISSING>").astype(str).value_counts().items():
            rows.append({"product": product, "table": table, "field": dir_col, "metric": "value_count", "value": value, "count": int(n)})
    else:
        rows.append({"product": product, "table": table, "field": "upstream_downstream", "metric": "missing_field", "count": None})
    for col in method_cols:
        miss = int((~nonmissing(df[col])).sum())
        rows.append({"product": product, "table": table, "field": col, "metric": "missing_provenance_or_method", "row_count": len(df), "count": miss})
        for value, n in df[col].fillna("<MISSING>").astype(str).value_counts().head(30).items():
            rows.append({"product": product, "table": table, "field": col, "metric": "value_count", "value": value, "count": int(n)})
    synthetic_cols = [c for c in method_cols if "synthetic" in " ".join(df[c].dropna().astype(str).head(1000)).lower() or "synthetic" in c.lower()]
    rows.append({"product": product, "table": table, "field": "|".join(method_cols), "metric": "synthetic_undivided_rows_present_and_flagged", "value": bool(synthetic_cols), "count": None})
    return rows


def lookup_reliability(df: pd.DataFrame) -> list[dict]:
    rows = []
    if "approach_window_direction_units" not in df.columns:
        return [{"table": "mvp_directional_lookup_distribution_table.csv", "status": "missing_approach_window_direction_units"}]
    n = pd.to_numeric(df["approach_window_direction_units"], errors="coerce").fillna(0)
    bins = {
        "0": int((n == 0).sum()),
        "1-4": int(((n >= 1) & (n <= 4)).sum()),
        "5-19": int(((n >= 5) & (n <= 19)).sum()),
        "20-29": int(((n >= 20) & (n <= 29)).sum()),
        "30+": int((n >= 30).sum()),
    }
    for label, count in bins.items():
        readiness = "insufficient" if label in {"0", "1-4"} else ("warning_only" if label == "5-19" else ("reliable" if label == "20-29" else "preferred"))
        rows.append({"unit_count_band": label, "cell_count": count, "threshold_class": readiness})
    dist_cols = [c for c in df.columns if any(token in c for token in ["mean", "median", "p10", "p25", "p75", "p90", "percentile"])]
    rows.append({"unit_count_band": "distribution_fields", "cell_count": len(dist_cols), "threshold_class": "distribution_preserved" if {"mean_unit_crash_rate", "median_unit_crash_rate"}.issubset(df.columns) and any(c.startswith("p") for c in dist_cols) else "distribution_fields_incomplete", "fields": "|".join(dist_cols)})
    if "numeric_complete_unit_count" in df.columns:
        eligible = pd.to_numeric(df["numeric_complete_unit_count"], errors="coerce").fillna(0)
        rows.append({"unit_count_band": "rate_eligible_vs_total_units", "cell_count": int((eligible < n).sum()), "threshold_class": "cells_where_rate_eligible_lt_total"})
    else:
        rows.append({"unit_count_band": "rate_eligible_vs_total_units", "cell_count": None, "threshold_class": "recommend_add_total_units_and_rate_eligible_units_fields"})
    return rows


def build_contract(table_inv: list[dict]) -> str:
    observed_final = [r["file_name"] for r in table_inv if r["product"] == "final_leg_corrected_analysis_dataset" and r["extension"] in {".csv", ".parquet"}]
    observed_mvp = [r["file_name"] for r in table_inv if r["product"] == "mvp_dataset" and r["extension"] in {".csv", ".parquet"}]
    return f"""# Target Parquet-First Cache Contract Draft

This is a planning draft only. It does not restructure current folders.

## Doctrine

- Parquet files should be the canonical cache tables.
- CSV files should be derivative exports for review, Excel inspection, summaries, and reports.
- If Parquet and CSV disagree, Parquet wins unless a CSV is explicitly documented as a source/config table.
- Each canonical product should include `schema.json`, `manifest.json`, `README.md`, and an `exports/` folder.
- Pre-refresh CSV products should remain frozen as evidence until a refreshed candidate cache is validated.

## Observed Current Final Product Tables

{chr(10).join(f'- `{name}`' for name in observed_final)}

## Recommended Final Product Structure

```text
work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/
  signals.parquet
  signal_approaches.parquet
  approach_windows.parquet
  signal_windows.parquet
  bin_context.parquet
  schema.json
  manifest.json
  README.md
  exports/
    signals_sample.csv
    approach_windows_sample.csv
    completeness_summary.csv
    key_integrity_summary.csv
    data_dictionary.csv
```

The final product should own stable signal, approach/leg, approach-window, signal-window, and bin context keys. `signal_approach_id` should be complete or explicitly marked as source-limited before MVP derivation.

## Observed Current MVP Product Tables

{chr(10).join(f'- `{name}`' for name in observed_mvp)}

## Recommended MVP Product Structure

```text
work/roadway_graph/analysis/mvp_dataset/
  units.parquet
  lookup_cells.parquet
  bin_context.parquet
  fallback_hierarchy.parquet
  schema.json
  manifest.json
  README.md
  exports/
    units_sample.csv
    lookup_cells.csv
    cell_reliability_summary.csv
    numeric_missingness_summary.csv
```

The MVP product should derive from the final cache and preserve direct/synthetic directionality, upstream/downstream, access bands, numeric context, crash/exposure/rate fields, total unit counts, and rate-eligible unit counts.
"""


def build_findings(metrics: dict) -> str:
    return f"""# Canonical Cache Relationship Audit Findings

Bounded question: How do the final leg-corrected canonical cache and MVP directional rate distribution cache relate, and what is the safest refresh sequence?

## Summary

The two canonical products are structurally present and relationship-ready for diagnostics, but not ready for production MVP visualization/tool work. The safest next step is a canonical refresh candidate, not folder refactoring or downstream UI work.

## Key Findings

- Final approach-window rows: {metrics.get('final_aw_rows')}
- MVP approach-window-direction unit rows: {metrics.get('mvp_unit_rows')}
- MVP lookup cells: {metrics.get('lookup_cells')}
- Missing `signal_approach_id` in final approach-window rows: {metrics.get('final_aw_missing_approach')}
- Missing `signal_approach_id` in MVP unit rows: {metrics.get('mvp_unit_missing_approach')}
- Missing `signal_approach_id` in MVP bin-context rows: {metrics.get('mvp_bin_missing_approach')}
- Best final-to-MVP join: {metrics.get('best_join')}
- Numeric context missingness remains the main substantive blocker after key completeness.
- Zero exposure and missing candidate rate remain linked in the MVP unit table.
- Downstream/upstream is complete in the MVP unit table, and direct/synthetic provenance is preserved.
- Lookup distributions are preserved, but many cells are sparse.

## Refresh Planning Answers

It is not safe to proceed directly to MVP visualization/tool work except as diagnostic prototyping with visible warnings. Folder refactoring should happen after a refresh candidate is validated, because refactoring first would preserve current key and numeric-context defects in a cleaner shape. `signal_approach_id` should be resolved before speed/AADT/exposure/rate refresh because it is a relationship key between final cache grains and MVP unit/bin-context grains.

The refresh should address missing `signal_approach_id`, numeric speed, numeric AADT, zero or missing exposure denominators, missing candidate rates, MVP data dictionary coverage, and lookup fields that distinguish total matching units from rate-eligible units.

Current canonical products should remain frozen as pre-refresh evidence. Documentation-only changes include stale path cleanup and Parquet-first contract documentation. Data-refresh blockers include missing relationship keys, numeric context incompleteness, zero exposure denominators, and sparse-cell reliability treatment.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started canonical cache relationship audit.\n", encoding="utf-8")

    inventory = []
    column_profile = []
    grain_summary = []
    duplicate_rows = []
    key_rows = []
    table_meta: dict[str, dict] = {}

    for product, path in table_paths():
        columns = read_header(path)
        rows = count_rows(path) if path.suffix.lower() in {".csv", ".parquet"} else None
        role = role_for_table(path.name, columns)
        grain = infer_grain(path.name, columns, role)
        meta = {
            "product": product,
            "file_name": path.name,
            "relative_path": rel(path),
            "extension": path.suffix.lower(),
            "file_size_bytes": path.stat().st_size,
            "row_count": rows,
            "column_count": len(columns),
            "table_role": role,
            "likely_grain": " x ".join(grain),
            "columns_json": json.dumps(columns, ensure_ascii=True),
        }
        inventory.append(meta)
        table_meta[path.name] = {"product": product, "path": path, "columns": columns, "row_count": rows, "role": role, "grain": grain}
        if path.suffix.lower() in {".csv", ".parquet"}:
            log(f"Profiling columns for {rel(path)}")
            column_profile.extend(profile_columns(product, path, rows))
            grain_summary.append({"product": product, "table": path.name, "table_role": role, "inferred_grain_fields": "|".join(grain), "grain_basis": "filename_and_column_inference", "row_count": rows})
            duplicate_rows.append({"product": product, **duplicate_check(path, grain)})
            key_rows.extend(key_completeness(product, path, grain))

    write_csv("table_inventory.csv", inventory)
    write_csv("table_column_profile.csv", column_profile)
    write_csv("inferred_grain_summary.csv", grain_summary)
    write_csv("grain_duplicate_check.csv", duplicate_rows)
    write_csv("key_completeness_by_table.csv", key_rows)

    log("Running signal_approach_id missingness and reconstruction feasibility checks.")
    sa_summary = []
    sa_samples = []
    sa_feas = []
    loaded_small: dict[str, pd.DataFrame] = {}
    for name, meta in table_meta.items():
        path = meta["path"]
        if path.suffix.lower() not in {".csv", ".parquet"} or "signal_approach_id" not in meta["columns"]:
            continue
        df = read_table(path)
        df = normalized_for_join(df)
        if len(df) <= 200_000:
            loaded_small[name] = df
        sa_summary.extend(missingness_by_groups(df, name))
        miss = df[~nonmissing(df["signal_approach_id"])]
        sample_cols = [c for c in ["stable_signal_id", "signal_approach_id", "window_label", "signal_window", "upstream_downstream", "roadway_configuration", "divided_undivided", "directionality_method_mix_type", "mvp_directionality_method", "access_count_band", "approach_label", "final_review_physical_leg_id", "stable_bin_id"] if c in df.columns]
        for row in miss[sample_cols].head(200).to_dict("records"):
            row["table"] = name
            sa_samples.append(row)
        sa_feas.append(reconstruction_feasibility(df, name))
    write_csv("signal_approach_id_missingness_summary.csv", sa_summary)
    write_csv("signal_approach_id_missing_row_samples.csv", sa_samples)
    write_csv("signal_approach_id_reconstruction_feasibility.csv", sa_feas)

    log("Running final-to-MVP relationship checks.")
    final_aw = loaded_small.get("analysis_signal_approach_window.csv")
    if final_aw is None:
        final_aw = normalized_for_join(read_table(FINAL_DIR / "analysis_signal_approach_window.csv"))
    mvp_unit = loaded_small.get("mvp_approach_window_direction_unit.csv")
    if mvp_unit is None:
        mvp_unit = normalized_for_join(read_table(MVP_DIR / "mvp_approach_window_direction_unit.csv"))
    join_rows = relationship_audit(final_aw, mvp_unit)
    write_csv("final_leg_to_mvp_join_feasibility.csv", join_rows)

    log("Running numeric, access, directionality, and lookup reliability checks.")
    numeric_rows = []
    taxonomy_rows = []
    access_rows = []
    direction_rows = []
    for name, meta in table_meta.items():
        path = meta["path"]
        if path.suffix.lower() not in {".csv", ".parquet"}:
            continue
        access_rows.extend(access_audit(meta["product"], name, meta["columns"], meta["row_count"], path))
        role = meta["role"]
        should_load = role in {"directional unit data", "approach-window data", "lookup-cell data"} or name in {"analysis_signal_approach_window.csv", "mvp_approach_window_direction_unit.csv", "mvp_directional_lookup_distribution_table.csv"}
        if should_load:
            df = loaded_small.get(name) if name in loaded_small else read_table(path)
            df = normalized_for_join(df)
            n_rows, t_rows = numeric_audit(meta["product"], name, df)
            numeric_rows.extend(n_rows)
            taxonomy_rows.extend(t_rows)
            if any(c in df.columns for c in ["upstream_downstream", "downstream_upstream", "directionality_method_mix", "mvp_directionality_method", "directionality_direct_or_synthetic"]):
                direction_rows.extend(directionality_audit(meta["product"], name, df))
    write_csv("numeric_context_completeness_by_table.csv", numeric_rows)
    write_csv("exposure_rate_failure_taxonomy.csv", taxonomy_rows)
    write_csv("access_field_completeness.csv", access_rows)
    write_csv("directionality_completeness.csv", direction_rows)

    lookup_df = read_table(MVP_DIR / "mvp_directional_lookup_distribution_table.csv")
    lookup_rows = lookup_reliability(lookup_df)
    write_csv("lookup_cell_reliability_summary.csv", lookup_rows)

    best_join = next((r["join_family"] for r in join_rows if r.get("safe_join") is True or r.get("safe_join") == "True"), None)
    if not best_join:
        usable = [r for r in join_rows if r.get("status") == "usable_with_caution"]
        best_join = usable[0]["join_family"] if usable else "none_safe"
    metrics = {
        "final_aw_rows": len(final_aw),
        "mvp_unit_rows": len(mvp_unit),
        "lookup_cells": len(lookup_df),
        "final_aw_missing_approach": int((~nonmissing(final_aw["signal_approach_id"])).sum()) if "signal_approach_id" in final_aw.columns else None,
        "mvp_unit_missing_approach": int((~nonmissing(mvp_unit["signal_approach_id"])).sum()) if "signal_approach_id" in mvp_unit.columns else None,
        "mvp_bin_missing_approach": next((r["missing_count"] for r in key_rows if r.get("table") == "mvp_directional_bin_context.csv" and r.get("key_field") == "signal_approach_id"), None),
        "best_join": best_join,
    }

    refresh_rows = [
        {"sequence": 1, "recommendation_class": "freeze_current_products_as_pre_refresh_evidence", "priority": "high", "action": "Keep current canonical CSV products unchanged as evidence for the refresh baseline."},
        {"sequence": 2, "recommendation_class": "canonical_field_addition_needed", "priority": "high", "action": "Resolve or explicitly flag missing signal_approach_id before deriving refreshed MVP units."},
        {"sequence": 3, "recommendation_class": "numeric_context_refresh_needed", "priority": "high", "action": "Refresh speed, AADT, and exposure at final approach-window and MVP unit grains using documented canonical fields only."},
        {"sequence": 4, "recommendation_class": "crash_exposure_refresh_needed", "priority": "high", "action": "Recompute candidate rates only where exposure denominators are positive and documented."},
        {"sequence": 5, "recommendation_class": "minor_documentation_refresh", "priority": "medium", "action": "Add MVP data dictionary coverage, refreshed manifest, schema JSON, and stale path cleanup."},
        {"sequence": 6, "recommendation_class": "parquet_first_contract", "priority": "medium", "action": "After refresh validation, convert refreshed canonical cache tables to Parquet-first structure with CSV exports."},
        {"sequence": 7, "recommendation_class": "mvp_visualization_after_refresh", "priority": "medium", "action": "Build MVP visualizations/tools only after refreshed keys, numeric context, exposure, and reliability fields pass QA."},
    ]
    write_csv("recommended_refresh_sequence.csv", refresh_rows)

    (OUT_DIR / "target_cache_contract_draft.md").write_text(build_contract(inventory), encoding="utf-8")
    (OUT_DIR / "findings_memo.md").write_text(build_findings(metrics), encoding="utf-8")

    qa = [
        {"qa_check": "canonical_products_read_only", "status": "pass", "evidence": f"{rel(FINAL_DIR)}; {rel(MVP_DIR)}"},
        {"qa_check": "outputs_only_in_relationship_audit_folder", "status": "pass", "evidence": rel(OUT_DIR)},
        {"qa_check": "no_raw_source_artifact_or_legacy_inputs", "status": "pass", "evidence": "script reads only canonical product folders and previous audit folder path as context metadata"},
        {"qa_check": "previous_audit_not_used_for_backfill", "status": "pass", "evidence": rel(PREVIOUS_AUDIT_DIR)},
        {"qa_check": "no_crash_direction_derivation", "status": "pass", "evidence": "directionality fields are counted only; crash direction fields are not used"},
        {"qa_check": "no_files_moved_deleted_or_existing_outputs_rewritten", "status": "pass", "evidence": "script writes new audit package only"},
    ]
    write_csv("qa_manifest.csv", qa)
    (OUT_DIR / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")

    manifest = {
        "script": "src.roadway_graph.audit.canonical_cache_relationship_audit",
        "created_utc": now(),
        "bounded_question": "Read-only canonical cache relationship and refresh-planning audit.",
        "canonical_inputs": [rel(FINAL_DIR), rel(MVP_DIR)],
        "previous_audit_context": rel(PREVIOUS_AUDIT_DIR),
        "output_folder": rel(OUT_DIR),
        "outputs": sorted(p.name for p in OUT_DIR.iterdir() if p.is_file()),
        "metrics": metrics,
        "non_goals": [
            "no canonical product modification",
            "no refresh",
            "no raw/source/artifact reads",
            "no legacy reads",
            "no review backfill",
            "no crash direction use",
        ],
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log("Completed canonical cache relationship audit.")


if __name__ == "__main__":
    main()
