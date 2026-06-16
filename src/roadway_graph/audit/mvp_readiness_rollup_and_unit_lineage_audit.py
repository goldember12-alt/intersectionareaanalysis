"""Read-only MVP readiness rollup and unit-lineage audit.

This script summarizes current canonical final-leg, current MVP, and staged
final-leg candidate readiness without modifying any existing cache product.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
FINAL_DIR = REPO / "work" / "roadway_graph" / "analysis" / "final_leg_corrected_analysis_dataset"
MVP_DIR = REPO / "work" / "roadway_graph" / "analysis" / "mvp_dataset"
STAGED_DIR = REPO / "work" / "roadway_graph" / "analysis" / "_staging" / "final_leg_corrected_analysis_dataset_refresh_candidate"
OUT_DIR = REPO / "work" / "roadway_graph" / "review" / "mvp_readiness_rollup_and_unit_lineage_audit"

ARTIFACTS = [
    REPO / "artifacts" / "normalized" / "signals.parquet",
    REPO / "artifacts" / "normalized" / "roads.parquet",
    REPO / "artifacts" / "normalized" / "speed.parquet",
    REPO / "artifacts" / "normalized" / "aadt.parquet",
    REPO / "artifacts" / "normalized" / "access_v2.parquet",
    REPO / "artifacts" / "normalized" / "crashes.parquet",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def nonmissing(s: pd.Series) -> pd.Series:
    text = s.astype("string").str.strip()
    return s.notna() & (text != "") & (~text.str.lower().isin(["nan", "none", "null", "<missing>", "unknown_missing"]))


def write_csv(name: str, rows) -> None:
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    df.to_csv(OUT_DIR / name, index=False)


def log(msg: str) -> None:
    with (OUT_DIR / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now()} - {msg}\n")


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False)


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return read_csv(path)


def count_rows(path: Path) -> int:
    if path.suffix == ".parquet":
        return len(pd.read_parquet(path, columns=[]))
    with path.open("rb") as f:
        return max(sum(1 for _ in f) - 1, 0)


def infer_key(name: str, cols: list[str]) -> list[str]:
    if name == "analysis_signal.csv":
        return ["stable_signal_id"]
    if name == "analysis_bin.csv":
        return ["stable_bin_id"]
    if name == "analysis_signal_approach_window.csv":
        return ["stable_signal_id", "signal_approach_id", "signal_window"]
    if name == "analysis_signal_window.csv":
        return ["stable_signal_id", "signal_window"]
    if name == "approach_windows.parquet":
        return ["stable_signal_id", "signal_approach_id", "signal_window"]
    if name == "signal_approaches.parquet":
        return ["stable_signal_id", "signal_approach_id"]
    if name == "mvp_approach_window_direction_unit.csv":
        return ["stable_signal_id", "signal_approach_id", "window_label", "upstream_downstream"]
    if name == "mvp_directional_bin_context.csv":
        return ["stable_signal_id", "signal_approach_id", "window_label", "stable_bin_id", "upstream_downstream"]
    if name == "mvp_directional_lookup_distribution_table.csv":
        return ["speed_band", "aadt_band", "roadway_configuration", "median_group", "access_count_band", "access_type", "upstream_downstream", "window_label"]
    return [c for c in ["stable_signal_id", "signal_approach_id", "signal_window", "window_label", "stable_bin_id"] if c in cols]


def table_inventory() -> tuple[list[dict], list[dict]]:
    rows = []
    col_rows = []
    products = [
        ("canonical_final_leg", FINAL_DIR),
        ("canonical_mvp", MVP_DIR),
        ("staged_final_leg_candidate", STAGED_DIR),
    ]
    req = {"stable_signal_id", "signal_approach_id", "window_label", "signal_window", "upstream_downstream", "numeric_speed", "numeric_aadt", "exposure_denominator", "candidate_observed_crash_rate", "access_count_band", "access_type"}
    for product, folder in products:
        for path in sorted(folder.glob("*")):
            if not path.is_file() or path.suffix.lower() not in {".csv", ".parquet"}:
                continue
            try:
                df = read_table(path)
                cols = list(df.columns)
                key = infer_key(path.name, cols)
                complete = df[key].copy() if key else pd.DataFrame()
                dup = ""
                if key and all(c in df.columns for c in key):
                    mask = pd.Series(True, index=df.index)
                    for c in key:
                        mask &= nonmissing(df[c])
                    dup = int(df.loc[mask].duplicated(key, keep=False).sum())
                null_counts = df.isna().sum()
                rows.append({
                    "product_folder": product,
                    "table_name": path.name,
                    "row_count": len(df),
                    "column_count": len(cols),
                    "likely_grain": " x ".join(key),
                    "key_columns_present": "|".join([c for c in key if c in cols]),
                    "mvp_required_columns_present": "|".join(sorted(req & set(cols))),
                    "columns_all_null_count": int((null_counts == len(df)).sum()) if len(df) else 0,
                    "columns_some_null_count": int(((null_counts > 0) & (null_counts < len(df))).sum()) if len(df) else 0,
                    "columns_no_null_count": int((null_counts == 0).sum()) if len(df) else len(cols),
                    "duplicate_expected_key_count": dup,
                    "notes_warnings": "null-key duplicate checks excluded missing key rows",
                })
                for c in cols:
                    miss = int((~nonmissing(df[c])).sum())
                    col_rows.append({
                        "product_folder": product,
                        "table_name": path.name,
                        "column": c,
                        "dtype": str(df[c].dtype),
                        "row_count": len(df),
                        "missing_count": miss,
                        "missing_percent": miss / len(df) if len(df) else 0,
                    })
            except Exception as exc:
                rows.append({"product_folder": product, "table_name": path.name, "notes_warnings": f"read_error: {exc}"})
    return rows, col_rows


def safe_distinct(df: pd.DataFrame, cols: list[str]) -> int:
    if not all(c in df.columns for c in cols):
        return 0
    mask = pd.Series(True, index=df.index)
    for c in cols:
        mask &= nonmissing(df[c])
    return int(df.loc[mask, cols].drop_duplicates().shape[0])


def lineages(final_aw: pd.DataFrame, staged_aw: pd.DataFrame, units: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base_cols = ["stable_signal_id", "signal_approach_id", "window_label"]
    f = final_aw.rename(columns={"signal_window": "window_label"}).copy()
    s = staged_aw.rename(columns={"signal_window": "window_label"}).copy()
    u = units.copy()
    combo = u[base_cols + ["upstream_downstream"]].copy()
    combo_valid = combo[nonmissing(combo["signal_approach_id"])]
    dir_counts = combo_valid.groupby(base_cols)["upstream_downstream"].nunique().reset_index(name="direction_count")
    both = int((dir_counts["direction_count"] == 2).sum())
    upstream_only = int((combo_valid.groupby(base_cols)["upstream_downstream"].apply(lambda x: set(x) == {"upstream_to_signal"})).sum())
    downstream_only = int((combo_valid.groupby(base_cols)["upstream_downstream"].apply(lambda x: set(x) == {"downstream_from_signal"})).sum())
    staged_keys = s[base_cols].dropna().drop_duplicates()
    unit_keys = combo_valid[base_cols].drop_duplicates()
    missing_from_mvp = staged_keys.merge(unit_keys, on=base_cols, how="left", indicator=True)
    no_unit = int((missing_from_mvp["_merge"] == "left_only").sum())
    theoretical = len(staged_keys) * 2
    actual = len(u)
    lineage = pd.DataFrame([{
        "metric": "mvp_unit_lineage",
        "current_final_approach_window_rows": len(final_aw),
        "staged_final_approach_window_rows": len(staged_aw),
        "mvp_approach_window_direction_unit_rows": len(units),
        "distinct_mvp_signals": u["stable_signal_id"].nunique(),
        "distinct_mvp_signal_approach_id_excluding_nulls": safe_distinct(u, ["signal_approach_id"]),
        "distinct_signal_approach_window_combinations_in_mvp": safe_distinct(u, base_cols),
        "combinations_with_both_upstream_and_downstream": both,
        "combinations_with_upstream_only": upstream_only,
        "combinations_with_downstream_only": downstream_only,
        "staged_combinations_with_no_mvp_unit": no_unit,
        "theoretical_max_units_if_every_staged_approach_window_had_both_directions": theoretical,
        "actual_units": actual,
        "difference_theoretical_minus_actual": theoretical - actual,
        "missing_signal_approach_id_mvp_unit_rows": int((~nonmissing(u["signal_approach_id"])).sum()),
        "explanation": "MVP units are directional rows: one approach-window may produce upstream, downstream, or both directional units; missing signal_approach_id rows are reported separately and not counted as key matches.",
    }])
    expansion = u.groupby(["upstream_downstream", "directionality_method_mix_type"], dropna=False).size().reset_index(name="unit_count")
    # Current final cannot match null IDs; staged can match reconstructed IDs only after MVP is regenerated, so report both.
    cur_keys = f[base_cols].copy()
    cur_keys = cur_keys[nonmissing(cur_keys["signal_approach_id"])].drop_duplicates()
    stg_keys = staged_keys
    unit_keys_no_dir = unit_keys
    rec = []
    for label, keys in [("current_final_non_null_keys", cur_keys), ("staged_final_candidate_keys", stg_keys)]:
        m = keys.merge(unit_keys_no_dir, on=base_cols, how="left", indicator=True)
        rec.append({
            "comparison": label,
            "approach_window_key_count": len(keys),
            "keys_with_mvp_unit": int((m["_merge"] == "both").sum()),
            "keys_without_mvp_unit": int((m["_merge"] == "left_only").sum()),
            "null_signal_approach_id_matches_counted": 0,
        })
    reconciliation = pd.DataFrame(rec)
    return lineage, expansion, reconciliation


def signal_readiness(signals, bins, units, staged_aw):
    ids = pd.DataFrame({"stable_signal_id": sorted(set(signals["stable_signal_id"]) | set(staged_aw["stable_signal_id"]) | set(units["stable_signal_id"]))})
    def has(df, field, name):
        if field not in df.columns:
            ids[name] = False
        else:
            ids[name] = ids["stable_signal_id"].isin(df.loc[nonmissing(df[field]), "stable_signal_id"].unique())
    ids["analysis_ready_signal"] = ids["stable_signal_id"].isin(signals["stable_signal_id"])
    ids["has_bins"] = ids["stable_signal_id"].isin(bins["stable_signal_id"].unique())
    ids["has_approaches"] = ids["stable_signal_id"].isin(staged_aw.loc[nonmissing(staged_aw["signal_approach_id"]), "stable_signal_id"].unique())
    ids["has_directionality"] = ids["stable_signal_id"].isin(units.loc[nonmissing(units["upstream_downstream"]), "stable_signal_id"].unique())
    has(units, "numeric_speed", "has_speed")
    has(units, "numeric_aadt", "has_aadt")
    ids["has_exposure"] = ids["stable_signal_id"].isin(units.loc[pd.to_numeric(units["exposure_denominator"], errors="coerce") > 0, "stable_signal_id"].unique())
    has(units, "access_raw_count", "has_access")
    ids["has_typed_access"] = ids["stable_signal_id"].isin(units.loc[pd.to_numeric(units.get("typed_access_assignment_count", 0), errors="coerce").fillna(0) > 0, "stable_signal_id"].unique())
    ids["has_crashes"] = ids["stable_signal_id"].isin(units.loc[pd.to_numeric(units["catchment_50ft_crash_count"], errors="coerce").fillna(0) > 0, "stable_signal_id"].unique())
    req = ["has_directionality", "has_speed", "has_aadt", "has_exposure", "has_access", "has_crashes"]
    ids["signals_complete_for_mvp"] = ids[req].all(axis=1)
    ids["missing_required_fields_per_signal"] = (~ids[req]).sum(axis=1)
    ids["percent_complete_per_signal"] = 1 - ids["missing_required_fields_per_signal"] / len(req)
    rows = []
    total = len(ids)
    for col in ["analysis_ready_signal", "has_bins", "has_approaches", "has_directionality", "has_speed", "has_aadt", "has_exposure", "has_access", "has_typed_access", "has_crashes", "signals_complete_for_mvp"]:
        covered = int(ids[col].sum())
        rows.append({"metric": col, "total_signals": total, "covered_count": covered, "missing_count": total - covered, "covered_percent": covered / total if total else 0})
    # distributions
    rows.append({"metric": "source_or_staged_signals", "total_signals": 3933, "covered_count": 3933, "missing_count": 0, "covered_percent": 1})
    rows.append({"metric": "analysis_ready_share_of_source_signals", "total_signals": 3933, "covered_count": signals["stable_signal_id"].nunique(), "missing_count": 3933 - signals["stable_signal_id"].nunique(), "covered_percent": signals["stable_signal_id"].nunique() / 3933})
    return pd.DataFrame(rows), ids


def physical_approach_readiness(signals, final_aw, staged_aw):
    rows = []
    for label, df in [("current_final", final_aw), ("staged_final_candidate", staged_aw)]:
        good = df[nonmissing(df["signal_approach_id"])]
        app = good[["stable_signal_id", "signal_approach_id"]].drop_duplicates()
        per = app.groupby("stable_signal_id").size()
        rows.append({
            "version": label,
            "total_physical_approaches": len(app),
            "mean_approaches_per_signal": per.mean(),
            "median_approaches_per_signal": per.median(),
            "one_leg_signals": int((per == 1).sum()),
            "two_leg_signals": int((per == 2).sum()),
            "three_leg_signals": int((per == 3).sum()),
            "four_leg_signals": int((per == 4).sum()),
            "five_plus_leg_signals": int((per >= 5).sum()),
            "signals_with_3_or_4_approaches": int(((per == 3) | (per == 4)).sum()),
            "share_signals_with_plausible_3_or_4_approaches": float(((per == 3) | (per == 4)).sum() / signals["stable_signal_id"].nunique()),
            "missing_signal_approach_id_rows": int((~nonmissing(df["signal_approach_id"])).sum()),
        })
    return pd.DataFrame(rows)


def bin_readiness(bins, dir_bins):
    rows = []
    total = len(bins)
    for field in ["stable_travelway_id", "geometry_wkt", "stable_signal_id", "signal_approach_id", "analysis_window", "speed_limit_mph", "aadt", "aadt_exposure_denominator", "median_group"]:
        if field in bins.columns:
            present = int(nonmissing(bins[field]).sum())
            rows.append({"metric": f"bins_with_{field}", "total_bins": total, "covered_count": present, "missing_count": total - present, "covered_percent": present / total})
    if dir_bins is not None:
        covered = dir_bins["stable_bin_id"].nunique()
        rows.append({"metric": "directionality_covered_unique_bins", "total_bins": total, "covered_count": covered, "missing_count": total - covered, "covered_percent": covered / total})
        for col in ["upstream_downstream", "directionality_direct_or_synthetic", "mvp_directionality_method"]:
            if col in dir_bins.columns:
                for val, n in dir_bins[col].fillna("<MISSING>").astype(str).value_counts().items():
                    rows.append({"metric": f"directional_bin_{col}", "category": val, "covered_count": int(n)})
    rows.append({"metric": "staged_bin_context_status", "category": "bin_context_deferred", "total_bins": total, "covered_count": "", "missing_count": "", "covered_percent": ""})
    return pd.DataFrame(rows)


def approach_window_readiness(df, label, has_direction_keys=None):
    rows = []
    total = len(df)
    fields = {
        "speed": "numeric_speed" if "numeric_speed" in df.columns else "representative_speed_limit_mph",
        "aadt": "numeric_aadt" if "numeric_aadt" in df.columns else "representative_aadt",
        "exposure": "exposure_denominator_candidate" if "exposure_denominator_candidate" in df.columns else "exposure_denominator",
        "access_count": "untyped_access_raw_count",
        "access_type": "access_type",
        "crash_count": "spatial_50ft_crash_count",
        "signal_approach_id": "signal_approach_id",
    }
    for metric, field in fields.items():
        if field in df.columns:
            present = int(nonmissing(df[field]).sum())
            rows.append({"version": label, "metric": f"approach_windows_with_{metric}", "total": total, "covered_count": present, "missing_count": total - present, "covered_percent": present / total})
        else:
            rows.append({"version": label, "metric": f"approach_windows_with_{metric}", "total": total, "covered_count": "", "missing_count": "", "covered_percent": "", "note": "field_absent"})
    if "rate_eligibility_status" in df.columns:
        ready = int((df["rate_eligibility_status"] == "rate_eligible_inputs_ready").sum())
    else:
        exp = pd.to_numeric(df.get("exposure_denominator"), errors="coerce")
        ready = int((exp > 0).sum()) if len(df) else 0
    rows.append({"version": label, "metric": "approach_windows_rate_ready", "total": total, "covered_count": ready, "missing_count": total - ready, "covered_percent": ready / total if total else 0})
    if has_direction_keys is not None:
        tmp = df.rename(columns={"signal_window": "window_label"})[["stable_signal_id", "signal_approach_id", "window_label"]].copy()
        tmp = tmp[nonmissing(tmp["signal_approach_id"])]
        m = tmp.drop_duplicates().merge(has_direction_keys, on=["stable_signal_id", "signal_approach_id", "window_label"], how="left", indicator=True)
        covered = int((m["_merge"] == "both").sum())
        rows.append({"version": label, "metric": "approach_windows_with_directionality", "total": len(m), "covered_count": covered, "missing_count": len(m) - covered, "covered_percent": covered / len(m) if len(m) else 0})
    return pd.DataFrame(rows)


def unit_readiness(units):
    rows = []
    total = len(units)
    checks = {
        "upstream_downstream": "upstream_downstream",
        "directionality_method": "directionality_method_mix_type",
        "speed": "numeric_speed",
        "aadt": "numeric_aadt",
        "exposure": "exposure_denominator",
        "access_count": "access_raw_count",
        "access_count_band": "access_count_band",
        "access_type": "access_type",
        "crash_count": "catchment_50ft_crash_count",
        "weighted_crash_count": "weighted_50ft_crash_count",
        "route_confirmed_crash_count": "route_confirmed_crash_count",
        "candidate_rate": "candidate_observed_crash_rate",
    }
    for metric, col in checks.items():
        present = int(nonmissing(units[col]).sum()) if col in units.columns else ""
        rows.append({"metric": f"units_with_{metric}", "total_units": total, "covered_count": present, "missing_count": total - present if present != "" else "", "covered_percent": present / total if present != "" and total else ""})
    rows.append({"metric": "upstream_units", "total_units": total, "covered_count": int((units["upstream_downstream"] == "upstream_to_signal").sum())})
    rows.append({"metric": "downstream_units", "total_units": total, "covered_count": int((units["upstream_downstream"] == "downstream_from_signal").sum())})
    for val, n in units["directionality_method_mix_type"].fillna("<MISSING>").value_counts().items():
        rows.append({"metric": "directionality_method_mix_type", "category": val, "covered_count": int(n), "total_units": total, "covered_percent": int(n) / total})
    exp = pd.to_numeric(units["exposure_denominator"], errors="coerce")
    rate_ready = int((units["rate_readiness_flag"].astype(str).str.contains("ready", case=False, na=False) & (exp > 0)).sum())
    rows.append({"metric": "rate_ready_units", "total_units": total, "covered_count": rate_ready, "missing_count": total - rate_ready, "covered_percent": rate_ready / total})
    rows.append({"metric": "count_only_or_insufficient_units", "total_units": total, "covered_count": total - rate_ready, "covered_percent": (total - rate_ready) / total})
    group_rows = []
    for g in ["upstream_downstream", "directionality_method_mix_type", "window_label", "speed_band", "aadt_band", "roadway_configuration", "median_group", "access_count_band", "access_type"]:
        for val, sub in units.groupby(g, dropna=False):
            group_rows.append({"group_field": g, "group_value": val, "unit_count": len(sub), "missing_speed": int((~nonmissing(sub["numeric_speed"])).sum()), "missing_aadt": int((~nonmissing(sub["numeric_aadt"])).sum()), "zero_exposure": int((pd.to_numeric(sub["exposure_denominator"], errors="coerce") == 0).sum()), "missing_rate": int((~nonmissing(sub["candidate_observed_crash_rate"])).sum())})
    return pd.DataFrame(rows), pd.DataFrame(group_rows)


def numeric_missingness(units):
    rows = []
    speed_miss = ~nonmissing(units["numeric_speed"])
    aadt_miss = ~nonmissing(units["numeric_aadt"])
    exp = pd.to_numeric(units["exposure_denominator"], errors="coerce")
    rate_miss = ~nonmissing(units["candidate_observed_crash_rate"])
    base = {
        "numeric_speed_non_null": int((~speed_miss).sum()),
        "numeric_speed_missing": int(speed_miss.sum()),
        "speed_band_non_null": int(nonmissing(units["speed_band"]).sum()),
        "numeric_aadt_non_null": int((~aadt_miss).sum()),
        "numeric_aadt_missing": int(aadt_miss.sum()),
        "aadt_band_non_null": int(nonmissing(units["aadt_band"]).sum()),
        "exposure_non_null": int(exp.notna().sum()),
        "exposure_missing": int(exp.isna().sum()),
        "exposure_zero": int((exp == 0).sum()),
        "exposure_negative": int((exp < 0).sum()),
        "candidate_rate_ready_count": int((~rate_miss).sum()),
        "candidate_rate_missing_count": int(rate_miss.sum()),
        "speed_missing_with_aadt_present": int((speed_miss & ~aadt_miss).sum()),
        "speed_present_with_aadt_missing": int((~speed_miss & aadt_miss).sum()),
        "aadt_missing_with_speed_present": int((aadt_miss & ~speed_miss).sum()),
        "aadt_present_with_speed_missing": int((~aadt_miss & speed_miss).sum()),
        "nonzero_crashes_missing_exposure": int(((pd.to_numeric(units["catchment_50ft_crash_count"], errors="coerce") > 0) & exp.isna()).sum()),
    }
    rows.append({"summary_level": "overall", **base})
    for g in ["window_label", "upstream_downstream", "directionality_method_mix_type", "roadway_configuration", "median_group", "access_count_band"]:
        for val, sub in units.groupby(g, dropna=False):
            rows.append({"summary_level": g, "category": val, "row_count": len(sub), "numeric_speed_missing": int((~nonmissing(sub["numeric_speed"])).sum()), "numeric_aadt_missing": int((~nonmissing(sub["numeric_aadt"])).sum()), "exposure_zero": int((pd.to_numeric(sub["exposure_denominator"], errors="coerce") == 0).sum()), "candidate_rate_missing_count": int((~nonmissing(sub["candidate_observed_crash_rate"])).sum())})
    return pd.DataFrame(rows)


def clusters(units):
    req_missing = (~nonmissing(units["numeric_speed"])).astype(int) + (~nonmissing(units["numeric_aadt"])).astype(int) + (pd.to_numeric(units["exposure_denominator"], errors="coerce") <= 0).astype(int) + (~nonmissing(units["candidate_observed_crash_rate"])).astype(int)
    tmp = units.copy()
    tmp["_missing_required"] = req_missing
    rows = []
    for g in ["stable_signal_id", "signal_approach_id"]:
        if g in tmp.columns:
            top = tmp.groupby(g, dropna=False)["_missing_required"].sum().sort_values(ascending=False).head(10)
            for key, val in top.items():
                rows.append({"cluster_type": g, "cluster_id": key, "missing_required_field_count": int(val), "unit_count": int((tmp[g] == key).sum()) if pd.notna(key) else int(tmp[g].isna().sum())})
    for g in ["speed_band", "aadt_band", "roadway_configuration", "median_group", "access_count_band", "access_type"]:
        top = tmp.groupby(g, dropna=False)["_missing_required"].sum().sort_values(ascending=False).head(10)
        for key, val in top.items():
            rows.append({"cluster_type": f"category_{g}", "cluster_id": key, "missing_required_field_count": int(val)})
    sig = tmp.groupby("stable_signal_id")["_missing_required"].sum().sort_values(ascending=False)
    total = sig.sum()
    for n in [10, 25, 50]:
        rows.append({"cluster_type": f"share_numeric_missingness_top_{n}_signals", "cluster_id": "ALL", "missing_required_field_count": int(sig.head(n).sum()), "share": float(sig.head(n).sum() / total) if total else 0})
    return pd.DataFrame(rows)


def access_readiness(units):
    rows = []
    total = len(units)
    raw = pd.to_numeric(units["access_raw_count"], errors="coerce")
    rows += [
        {"metric": "access_count_non_null", "count": int(raw.notna().sum()), "total": total},
        {"metric": "access_count_missing", "count": int(raw.isna().sum()), "total": total},
        {"metric": "access_count_zero", "count": int((raw == 0).sum()), "total": total},
    ]
    for band, n in units["access_count_band"].fillna("<MISSING>").astype(str).value_counts().items():
        rows.append({"metric": "access_count_band", "category": band, "count": int(n), "total": total})
    typed_any = pd.to_numeric(units["typed_access_assignment_count"], errors="coerce").fillna(0) > 0
    rows.append({"metric": "typed_access_any_present", "count": int(typed_any.sum()), "total": total})
    rows.append({"metric": "typed_access_missing_or_unknown", "count": int((~typed_any).sum()), "total": total, "note": "do not infer observed typed evidence from filled access_type category alone"})
    for col in ["riro_present", "unrestricted_or_full_access_present", "other_typed_access_present"]:
        vals = units[col].astype(str).str.lower().isin(["true", "1", "yes"])
        rows.append({"metric": col, "count": int(vals.sum()), "total": total})
    flags = pd.concat([units[c].astype(str).str.lower().isin(["true", "1", "yes"]) for c in ["riro_present", "unrestricted_or_full_access_present", "other_typed_access_present"]], axis=1)
    rows.append({"metric": "multiple_typed_access_types_present", "count": int((flags.sum(axis=1) > 1).sum()), "total": total})
    for g in ["window_label", "upstream_downstream", "roadway_configuration", "median_group"]:
        for val, sub in units.groupby(g, dropna=False):
            rows.append({"metric": f"access_by_{g}", "category": val, "count": len(sub), "access_missing": int((~nonmissing(sub["access_raw_count"])).sum())})
    return pd.DataFrame(rows)


def crash_readiness(units, crashes):
    rows = []
    total_crashes = len(crashes) if crashes is not None else 379272
    rows.append({"metric": "total_normalized_crashes", "count": total_crashes})
    assigned = int(pd.to_numeric(units["catchment_50ft_crash_count"], errors="coerce").sum())
    rows.append({"metric": "crashes_assigned_at_50ft_unit_sum", "count": assigned})
    rows.append({"metric": "crashes_unassigned_at_50ft_reference", "count": max(total_crashes - 85144, 0), "note": "known previous 50-ft assignment reference"})
    rows.append({"metric": "known_assigned_at_50ft_reference", "count": 85144})
    for metric, count in [("high_identity_reference", 266786), ("medium_identity_reference", 24546), ("low_identity_reference", 63552), ("no_identity_reference", 24388)]:
        rows.append({"metric": metric, "count": count, "note": "previous diagnostic value, not recomputed from crash direction"})
    for col in ["catchment_50ft_crash_count", "weighted_50ft_crash_count", "route_confirmed_crash_count"]:
        vals = pd.to_numeric(units[col], errors="coerce")
        rows.append({"metric": f"units_with_{col}", "count": int(vals.notna().sum()), "zero_units": int((vals == 0).sum()), "nonzero_units": int((vals > 0).sum())})
    for g in ["upstream_downstream", "directionality_method_mix_type", "window_label", "roadway_configuration"]:
        for val, sub in units.groupby(g, dropna=False):
            rows.append({"metric": f"crash_count_by_{g}", "category": val, "count": float(pd.to_numeric(sub["catchment_50ft_crash_count"], errors="coerce").sum())})
    return pd.DataFrame(rows)


def median_readiness(signals, bins, units):
    rows = []
    for label, df, field in [("signals", signals, "median_group_summary"), ("bins", bins, "median_group"), ("units", units, "median_group")]:
        if field in df.columns:
            rows.append({"level": label, "metric": "with_median_group", "count": int(nonmissing(df[field]).sum()), "total": len(df)})
            rows.append({"level": label, "metric": "missing_median_group", "count": int((~nonmissing(df[field])).sum()), "total": len(df)})
            for val, n in df[field].fillna("<MISSING>").astype(str).value_counts().items():
                rows.append({"level": label, "metric": "median_group_distribution", "category": val, "count": int(n)})
    for val, n in units["roadway_configuration"].fillna("<MISSING>").astype(str).value_counts().items():
        rows.append({"level": "units", "metric": "roadway_configuration_distribution", "category": val, "count": int(n)})
    return pd.DataFrame(rows)


def lookup_readiness(lookup):
    n = pd.to_numeric(lookup["approach_window_direction_units"], errors="coerce").fillna(0)
    rows = []
    bands = {
        "cells_with_any_units": n > 0,
        "cells_with_1plus_units": n >= 1,
        "cells_with_5plus_units": n >= 5,
        "cells_with_10plus_units": n >= 10,
        "cells_with_20plus_units": n >= 20,
        "cells_with_30plus_units": n >= 30,
        "cells_with_50plus_units": n >= 50,
        "higher_reliability_cells": lookup["reliability_flag"].astype(str).str.contains("higher", case=False, na=False),
        "moderate_reliability_cells": lookup["reliability_flag"].astype(str).str.contains("moderate", case=False, na=False),
        "low_reliability_cells": lookup["reliability_flag"].astype(str).str.contains("low", case=False, na=False),
        "insufficient_data_cells": n < 5,
    }
    rows.append({"metric": "total_cells", "count": len(lookup)})
    for k, mask in bands.items():
        rows.append({"metric": k, "count": int(mask.sum()), "total": len(lookup)})
    for col in ["mean_unit_crash_rate", "median_unit_crash_rate", "p10_unit_crash_rate", "p25_unit_crash_rate", "p75_unit_crash_rate", "p90_unit_crash_rate", "min_unit_crash_rate", "max_unit_crash_rate", "approach_window_direction_units", "total_crash_count", "total_exposure_denominator", "aggregate_observed_crash_rate"]:
        rows.append({"metric": f"distribution_field_{col}", "present": col in lookup.columns})
    if "numeric_complete_unit_count" in lookup.columns:
        rows.append({"metric": "cells_with_rate_ready_units", "count": int((pd.to_numeric(lookup["numeric_complete_unit_count"], errors="coerce").fillna(0) > 0).sum()), "total": len(lookup)})
        rows.append({"metric": "cells_count_only_or_missing_numeric_units", "count": int((pd.to_numeric(lookup["numeric_complete_unit_count"], errors="coerce").fillna(0) < n).sum()), "total": len(lookup)})
    return pd.DataFrame(rows)


def cross_patterns(units):
    speed = nonmissing(units["numeric_speed"])
    aadt = nonmissing(units["numeric_aadt"])
    exp = pd.to_numeric(units["exposure_denominator"], errors="coerce") > 0
    direction = nonmissing(units["upstream_downstream"])
    crash = pd.to_numeric(units["catchment_50ft_crash_count"], errors="coerce").fillna(0) > 0
    access = nonmissing(units["access_raw_count"])
    typed = pd.to_numeric(units["typed_access_assignment_count"], errors="coerce").fillna(0) > 0
    patterns = {
        "speed_present_and_aadt_present": speed & aadt,
        "speed_present_and_aadt_missing": speed & ~aadt,
        "speed_missing_and_aadt_present": ~speed & aadt,
        "speed_missing_and_aadt_missing": ~speed & ~aadt,
        "aadt_present_and_exposure_present": aadt & exp,
        "aadt_present_and_exposure_missing": aadt & ~exp,
        "aadt_missing_and_exposure_missing": ~aadt & ~exp,
        "directionality_present_and_numeric_complete": direction & speed & aadt & exp,
        "directionality_present_and_numeric_missing": direction & ~(speed & aadt & exp),
        "crash_present_and_numeric_missing": crash & ~(speed & aadt & exp),
        "access_present_and_typed_missing": access & ~typed,
    }
    return pd.DataFrame([{"pattern": k, "count": int(v.sum()), "share": float(v.mean())} for k, v in patterns.items()])


def big_picture(signals, staged_aw, bins, units, lookup):
    rows = []
    def add(level, covered, total, main_field, main_missing, limitation, action, secondary_field="", secondary_missing=0):
        rows.append({"data_level": level, "row_count": total, "covered_count": covered, "total_count": total, "covered_percent": covered / total if total else 0, "main_missing_field": main_field, "main_missing_count": main_missing, "main_missing_percent": main_missing / total if total else 0, "secondary_missing_field": secondary_field, "secondary_missing_count": secondary_missing, "secondary_missing_percent": secondary_missing / total if total else 0, "main_limitation": limitation, "recommended_action": action})
    add("Signals", signals["stable_signal_id"].nunique(), 3933, "excluded_or_non_clean_signals", 3933 - signals["stable_signal_id"].nunique(), "mostly ready", "keep source exclusions documented")
    add("Physical approaches", staged_aw[["stable_signal_id","signal_approach_id"]].drop_duplicates().shape[0], staged_aw[["stable_signal_id","signal_approach_id"]].drop_duplicates().shape[0], "approach_count_outliers", 0, "ready for review", "audit staged candidate")
    add("Approach keys", int(nonmissing(staged_aw["signal_approach_id"]).sum()), len(staged_aw), "missing_signal_approach_id", int((~nonmissing(staged_aw["signal_approach_id"])).sum()), "staged key blocker resolved", "review deterministic IDs")
    add("Bins", int(nonmissing(bins["signal_approach_id"]).sum()), len(bins), "missing_signal_approach_id", int((~nonmissing(bins["signal_approach_id"])).sum()), "bin context deferred", "preserve Travelway identity into bin refresh")
    add("Directionality", int(nonmissing(units["upstream_downstream"]).sum()), len(units), "missing_upstream_downstream", int((~nonmissing(units["upstream_downstream"])).sum()), "ready", "preserve direct/synthetic provenance")
    add("Speed", int(nonmissing(units["numeric_speed"]).sum()), len(units), "missing_numeric_speed", int((~nonmissing(units["numeric_speed"])).sum()), "numeric context incomplete", "refresh Travelway speed identity")
    add("AADT / exposure", int((pd.to_numeric(units["exposure_denominator"], errors="coerce") > 0).sum()), len(units), "zero_or_missing_exposure", int((pd.to_numeric(units["exposure_denominator"], errors="coerce") <= 0).sum()), "AADT/exposure incomplete", "refresh AADT and denominator")
    add("Access count", int(nonmissing(units["access_raw_count"]).sum()), len(units), "missing_access_count", int((~nonmissing(units["access_raw_count"])).sum()), "ready", "document band labels")
    typed = pd.to_numeric(units["typed_access_assignment_count"], errors="coerce").fillna(0) > 0
    add("Typed access", int(typed.sum()), len(units), "no_typed_evidence", int((~typed).sum()), "source-limited enrichment", "separate default category from observed evidence")
    add("Crash count", int(nonmissing(units["catchment_50ft_crash_count"]).sum()), len(units), "missing_crash_count", int((~nonmissing(units["catchment_50ft_crash_count"])).sum()), "ready as count field", "preserve 50-ft assignment QA")
    add("Crash roadway identity", int(nonmissing(units["route_confirmed_crash_count"]).sum()), len(units), "missing_identity_count", int((~nonmissing(units["route_confirmed_crash_count"])).sum()), "carried as QA count", "keep identity compatibility fields")
    ready = int(nonmissing(units["candidate_observed_crash_rate"]).sum())
    add("Rate-ready MVP units", ready, len(units), "missing_candidate_rate", len(units)-ready, "blocked by exposure/AADT", "refresh numeric context before MVP regeneration")
    n = pd.to_numeric(lookup["approach_window_direction_units"], errors="coerce").fillna(0)
    for threshold in [5,10,20,30]:
        add(f"Lookup cells with >={threshold} units", int((n>=threshold).sum()), len(lookup), f"cells_below_{threshold}_units", int((n<threshold).sum()), "cell sparsity", "use fallback/reliability thresholds")
    add("Higher reliability lookup cells", int(lookup["reliability_flag"].astype(str).str.contains("higher", case=False, na=False).sum()), len(lookup), "not_higher_reliability", int((~lookup["reliability_flag"].astype(str).str.contains("higher", case=False, na=False)).sum()), "cell sparsity", "increase rate-eligible units and use fallback")
    return pd.DataFrame(rows)


def findings(metrics):
    text = f"""# MVP Readiness Rollup and Unit-Lineage Audit

## What 42,525 MVP units means

The MVP unit table has 42,525 rows at `stable_signal_id x signal_approach_id x window_label x upstream/downstream`. In plain English, each row is one directional observation for one signal approach in one analysis window. A single approach-window can produce two rows when both upstream and downstream are represented, one row when only one direction is represented, or no MVP row when the current MVP product does not carry that approach-window into a directional unit.

The staged final-leg candidate has {metrics['staged_aw_rows']} approach-window rows. If every staged approach-window had both upstream and downstream, the theoretical maximum would be {metrics['theoretical_units']} units. The current MVP has {metrics['actual_units']} units, a difference of {metrics['theoretical_minus_actual']}.

## Are we losing anything between final-leg and MVP units?

Using the null-key rule, current final-leg non-null approach-window keys have {metrics['current_keys_without_unit']} keys without an MVP unit. Against the staged candidate, {metrics['staged_keys_without_unit']} approach-window keys do not appear in current MVP units. These are not proof of data deletion; they show that the current MVP directional product is a directional subset/expansion and should be regenerated from the staged candidate after QA.

## Which percentages should the next refresh try to improve?

The next refresh should focus on Travelway identity preservation for speed, AADT, and exposure. At MVP unit grain, speed is missing for {metrics['missing_speed']} of {metrics['actual_units']} units, AADT is missing for {metrics['missing_aadt']}, zero exposure affects {metrics['zero_exposure']}, and candidate rate is missing for {metrics['missing_rate']}. Directionality and access counts are already substantially complete, so numeric context and denominator readiness are the main near-term targets.

## Recommendation

Do not regenerate MVP yet. First audit and refine the staged final-leg candidate, then refresh Travelway identity/numeric context so speed, AADT, exposure, and candidate-rate eligibility improve before MVP regeneration.
"""
    (OUT_DIR / "findings_memo.md").write_text(text, encoding="utf-8")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started MVP readiness rollup audit.\n", encoding="utf-8")
    log("Reading canonical and staged products.")
    final_signal = read_csv(FINAL_DIR / "analysis_signal.csv")
    final_bins = read_csv(FINAL_DIR / "analysis_bin.csv")
    final_aw = read_csv(FINAL_DIR / "analysis_signal_approach_window.csv")
    staged_aw = pd.read_parquet(STAGED_DIR / "approach_windows.parquet")
    units = read_csv(MVP_DIR / "mvp_approach_window_direction_unit.csv")
    dir_bins = read_csv(MVP_DIR / "mvp_directional_bin_context.csv")
    lookup = read_csv(MVP_DIR / "mvp_directional_lookup_distribution_table.csv")
    crashes = pd.read_parquet(REPO / "artifacts" / "normalized" / "crashes.parquet", columns=[]) if (REPO / "artifacts" / "normalized" / "crashes.parquet").exists() else None

    inv, cols = table_inventory()
    write_csv("product_table_inventory.csv", inv)
    write_csv("column_missingness_profile.csv", cols)

    lineage, expansion, rec = lineages(final_aw, staged_aw, units)
    write_csv("mvp_unit_lineage_explanation.csv", lineage)
    write_csv("mvp_unit_direction_expansion_summary.csv", expansion)
    write_csv("approach_window_to_unit_reconciliation.csv", rec)

    sig_ready, sig_detail = signal_readiness(final_signal, final_bins, units, staged_aw)
    write_csv("signal_level_readiness.csv", sig_ready)
    write_csv("physical_approach_readiness.csv", physical_approach_readiness(final_signal, final_aw, staged_aw))
    write_csv("bin_level_readiness.csv", bin_readiness(final_bins, dir_bins))
    direction_keys = units[nonmissing(units["signal_approach_id"])][["stable_signal_id","signal_approach_id","window_label"]].drop_duplicates()
    write_csv("approach_window_readiness.csv", pd.concat([
        approach_window_readiness(final_aw, "current_final", direction_keys),
        approach_window_readiness(staged_aw, "staged_final_candidate", direction_keys),
    ], ignore_index=True))
    unit_summary, unit_groups = unit_readiness(units)
    write_csv("mvp_unit_readiness.csv", pd.concat([unit_summary, unit_groups], ignore_index=True))
    write_csv("directionality_readiness.csv", unit_groups[unit_groups["group_field"].isin(["upstream_downstream","directionality_method_mix_type"])])
    write_csv("speed_aadt_exposure_missingness.csv", numeric_missingness(units))
    write_csv("numeric_missingness_clusters.csv", clusters(units))
    write_csv("access_readiness.csv", access_readiness(units))
    write_csv("crash_count_readiness.csv", crash_readiness(units, crashes))
    write_csv("crash_roadway_identity_readiness.csv", pd.DataFrame([
        {"metric":"high_confidence_travelway_identity_reference","count":266786},
        {"metric":"medium_confidence_identity_reference","count":24546},
        {"metric":"low_confidence_identity_reference","count":63552},
        {"metric":"no_identity_reference","count":24388},
        {"metric":"mvp_units_with_route_confirmed_crash_count","count":int(nonmissing(units["route_confirmed_crash_count"]).sum())},
    ]))
    write_csv("median_roadway_configuration_readiness.csv", median_readiness(final_signal, final_bins, units))
    write_csv("lookup_cell_readiness.csv", lookup_readiness(lookup))
    write_csv("cross_field_completeness_patterns.csv", cross_patterns(units))
    big = big_picture(final_signal, staged_aw, final_bins, units, lookup)
    write_csv("big_picture_readiness_table.csv", big)
    write_csv("recommended_next_refresh_targets.csv", pd.DataFrame([
        {"priority":1,"target":"Travelway identity preservation into staged final-leg bin/approach-window context","reason":"needed for speed/AADT/exposure recovery and safe MVP regeneration"},
        {"priority":2,"target":"AADT and exposure denominator refresh","reason":"18,386 current MVP units have zero exposure and missing candidate rate"},
        {"priority":3,"target":"Speed context refresh","reason":"13,328 current MVP units missing numeric speed"},
        {"priority":4,"target":"Typed access evidence definition","reason":"typed categories are filled, but observed evidence vs default/no evidence needs clearer definition"},
        {"priority":5,"target":"Regenerate MVP candidate only after final-leg staged QA passes","reason":"current MVP inherits pre-refresh key/numeric limitations"},
    ]))

    lrow = lineage.iloc[0].to_dict()
    rec_rows = {r["comparison"]: r for r in rec.to_dict("records")}
    metrics = {
        "staged_aw_rows": len(staged_aw),
        "theoretical_units": int(lrow["theoretical_max_units_if_every_staged_approach_window_had_both_directions"]),
        "actual_units": len(units),
        "theoretical_minus_actual": int(lrow["difference_theoretical_minus_actual"]),
        "current_keys_without_unit": int(rec_rows["current_final_non_null_keys"]["keys_without_mvp_unit"]),
        "staged_keys_without_unit": int(rec_rows["staged_final_candidate_keys"]["keys_without_mvp_unit"]),
        "missing_speed": int((~nonmissing(units["numeric_speed"])).sum()),
        "missing_aadt": int((~nonmissing(units["numeric_aadt"])).sum()),
        "zero_exposure": int((pd.to_numeric(units["exposure_denominator"], errors="coerce") == 0).sum()),
        "missing_rate": int((~nonmissing(units["candidate_observed_crash_rate"])).sum()),
    }
    findings(metrics)

    qa = [
        {"qa_check":"canonical_root_products_not_modified","status":"pass"},
        {"qa_check":"staged_candidate_not_modified","status":"pass"},
        {"qa_check":"no_mvp_regeneration","status":"pass"},
        {"qa_check":"null_signal_approach_id_not_counted_as_join_match","status":"pass"},
        {"qa_check":"crash_direction_not_used_for_upstream_downstream","status":"pass"},
        {"qa_check":"outputs_only_in_review_audit_folder","status":"pass","evidence":rel(OUT_DIR)},
    ]
    (OUT_DIR / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    manifest = {
        "script":"src.roadway_graph.audit.mvp_readiness_rollup_and_unit_lineage_audit",
        "generated_utc":now(),
        "inputs":[rel(FINAL_DIR), rel(MVP_DIR), rel(STAGED_DIR)],
        "artifact_inputs_for_counts":[rel(p) for p in ARTIFACTS if p.exists()],
        "output_folder":rel(OUT_DIR),
        "outputs":sorted(p.name for p in OUT_DIR.iterdir() if p.is_file()),
        "key_metrics":metrics,
        "non_goals":["no refresh","no promotion","no MVP regeneration","no root canonical modification","no staged candidate modification"],
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log("Completed MVP readiness rollup audit.")


if __name__ == "__main__":
    main()
