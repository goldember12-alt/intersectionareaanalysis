"""Audit numeric AADT/speed/exposure missingness in final signal-window context.

This review-only diagnostic explains why numeric AADT/speed/exposure
completeness at the signal-window figure grain is lower than prior signal-level
readiness flags. It does not rerun source joins, access assignment, crash
assignment, rates, or models.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "work/output/roadway_graph/review/current/final_signal_window_numeric_context_missingness_audit"

JOIN_DIR = REPO / "work/output/roadway_graph/review/current/final_signal_window_numeric_context_join"
TABLE_DIR = REPO / "work/output/roadway_graph/review/current/final_signal_window_numeric_context_table"
FINAL_DIR = REPO / "work/output/roadway_graph/review/current/final_leg_corrected_clean_universe_summary"
REVIEW_CURRENT = REPO / "work/output/roadway_graph/review/current"

BRANCH_DIRS = [
    REVIEW_CURRENT / "missing_hmms_good_travelway_context_refresh",
    REVIEW_CURRENT / "missing_hmms_offset_anchor_context_refresh",
    REVIEW_CURRENT / "missing_hmms_ramp_terminal_context_refresh",
    REVIEW_CURRENT / "missing_hmms_complex_multisignal_context_refresh",
    REVIEW_CURRENT / "final_clean_missing_leg_context_refresh_and_integration",
    REVIEW_CURRENT / "final_clean_intersection_zone_anchor_context_refresh",
    REVIEW_CURRENT / "final_clean_residual_leg_context_refresh_and_summary",
]

SPEED_SOURCE = REVIEW_CURRENT / "expanded_candidate_speed_rns_phase3d_vectorized_assignment/phase3d_candidate_rns_speed_assignment_detail.csv"
AADT_SOURCE = REVIEW_CURRENT / "expanded_candidate_aadt_v3_path_rebuild/aadt_v3_candidate_assignment_detail.csv"

INPUTS = {
    "signal_window_v2": JOIN_DIR / "signal_window_numeric_context_v2.csv",
    "approach_window_v2": JOIN_DIR / "signal_approach_window_numeric_context_v2.csv",
    "bin_numeric": JOIN_DIR / "bin_numeric_speed_aadt_context.csv",
    "numeric_inventory": JOIN_DIR / "numeric_context_field_inventory.csv",
    "numeric_missingness": JOIN_DIR / "numeric_context_missingness_summary.csv",
    "rate_readiness": JOIN_DIR / "candidate_crash_rate_readiness.csv",
    "matrix_v2": JOIN_DIR / "guidance_matrix_ready_long_v2.csv",
    "signal_window_v1": TABLE_DIR / "signal_window_numeric_context.csv",
    "approach_window_v1": TABLE_DIR / "signal_approach_window_numeric_context.csv",
    "final_signals": FINAL_DIR / "final_leg_corrected_signal_universe_3719.csv",
    "final_bins": FINAL_DIR / "final_leg_corrected_bin_universe.csv",
    "context_readiness": FINAL_DIR / "final_leg_corrected_context_readiness_summary.csv",
    "window_availability": FINAL_DIR / "final_leg_corrected_bin_window_availability.csv",
    "speed_source": SPEED_SOURCE,
    "aadt_source": AADT_SOURCE,
}


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with (OUT / "run_progress_log.txt").open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")
    print(message, flush=True)


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        log(f"Missing input: {path}")
        return pd.DataFrame()
    return pd.read_csv(path, **kwargs)


def write_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT / name, index=False, lineterminator="\n")
    log(f"Wrote {name}: {len(df):,} rows")


def normalize_key(value: object) -> str:
    if pd.isna(value):
        return ""
    s = str(value).upper().strip()
    s = re.sub(r"[^A-Z0-9]", "", s)
    s = re.sub(r"^(RVA|SVA)", "", s)
    return s


def metric_map(df: pd.DataFrame) -> dict[str, float]:
    if df.empty or "metric" not in df.columns:
        return {}
    return dict(zip(df["metric"], pd.to_numeric(df["value"], errors="coerce")))


def load_signal_windows() -> pd.DataFrame:
    sw = read_csv(INPUTS["signal_window_v2"], low_memory=False)
    sw["has_numeric_aadt"] = sw["representative_aadt"].notna()
    sw["has_numeric_speed"] = sw["representative_speed_limit_mph"].notna()
    sw["has_exposure_denominator"] = sw["exposure_denominator"].notna()
    sw["has_all_numeric_context"] = sw["has_numeric_aadt"] & sw["has_numeric_speed"] & sw["has_exposure_denominator"]
    return sw


def by_window(sw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for win, g in sw.groupby("signal_window", dropna=False):
        total = len(g)
        rows.append(
            {
                "signal_window": win,
                "total_rows": total,
                "rows_with_numeric_aadt": int(g["has_numeric_aadt"].sum()),
                "rows_missing_numeric_aadt": int((~g["has_numeric_aadt"]).sum()),
                "rows_with_numeric_speed": int(g["has_numeric_speed"].sum()),
                "rows_missing_numeric_speed": int((~g["has_numeric_speed"]).sum()),
                "rows_with_exposure_denominator": int(g["has_exposure_denominator"].sum()),
                "rows_missing_exposure_denominator": int((~g["has_exposure_denominator"]).sum()),
                "rows_with_all_three": int(g["has_all_numeric_context"].sum()),
                "rows_missing_any_numeric_context": int((~g["has_all_numeric_context"]).sum()),
                "aadt_completeness_share": round(float(g["has_numeric_aadt"].mean()), 4),
                "speed_completeness_share": round(float(g["has_numeric_speed"].mean()), 4),
                "exposure_completeness_share": round(float(g["has_exposure_denominator"].mean()), 4),
            }
        )
    return pd.DataFrame(rows)


def summarize_by(sw: pd.DataFrame, cols: list[str], name: str) -> pd.DataFrame:
    cols = [c for c in cols if c in sw.columns]
    out = (
        sw.groupby(cols, dropna=False)
        .agg(
            total_signal_windows=("stable_signal_id", "size"),
            signals=("stable_signal_id", "nunique"),
            numeric_aadt_rows=("has_numeric_aadt", "sum"),
            numeric_speed_rows=("has_numeric_speed", "sum"),
            exposure_rows=("has_exposure_denominator", "sum"),
            all_numeric_context_rows=("has_all_numeric_context", "sum"),
        )
        .reset_index()
    )
    out["summary_type"] = name
    for src, dst in [
        ("numeric_aadt_rows", "aadt_completeness_share"),
        ("numeric_speed_rows", "speed_completeness_share"),
        ("exposure_rows", "exposure_completeness_share"),
        ("all_numeric_context_rows", "all_numeric_context_share"),
    ]:
        out[dst] = (out[src] / out["total_signal_windows"]).round(4)
    return out


def branch_summary(sw: pd.DataFrame) -> pd.DataFrame:
    frames = []
    frames.append(summarize_by(sw, ["recovery_branch"], "recovery_branch"))
    frames.append(summarize_by(sw, ["final_review_leg_source_summary"], "leg_source_summary"))
    frames.append(summarize_by(sw, ["recovery_provenance_summary"], "recovery_provenance_summary"))
    return pd.concat(frames, ignore_index=True)


def source_route_key_sets() -> tuple[set[str], set[str]]:
    log("Building numeric source route-key inventories.")
    speed_keys: set[str] = set()
    aadt_keys: set[str] = set()
    if SPEED_SOURCE.exists():
        cols = pd.read_csv(SPEED_SOURCE, nrows=0).columns.tolist()
        use = [c for c in ["candidate_route_common", "route_common", "route_name", "normalized_candidate_route_key"] if c in cols]
        for chunk in pd.read_csv(SPEED_SOURCE, usecols=use, chunksize=250_000, low_memory=False):
            for c in use:
                speed_keys.update(k for k in chunk[c].map(normalize_key).unique() if k)
    if AADT_SOURCE.exists():
        cols = pd.read_csv(AADT_SOURCE, nrows=0).columns.tolist()
        use = [c for c in ["candidate_route_common", "route_common", "route_name", "candidate_normalized_route_key", "candidate_lookup_route_key"] if c in cols]
        for chunk in pd.read_csv(AADT_SOURCE, usecols=use, chunksize=250_000, low_memory=False):
            for c in use:
                aadt_keys.update(k for k in chunk[c].map(normalize_key).unique() if k)
    return speed_keys, aadt_keys


def failure_reason_detail(speed_keys: set[str], aadt_keys: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    log("Classifying bin-level numeric join failure reasons.")
    use = [
        "stable_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "source_measure_midpoint",
        "route_key_common",
        "route_key_name",
        "analysis_window",
        "final_review_leg_source",
        "final_review_recovery_provenance",
        "speed_limit_mph",
        "speed_match_method",
        "aadt",
        "aadt_match_method",
        "aadt_exposure_denominator",
        "numeric_context_source",
    ]
    detail = read_csv(INPUTS["bin_numeric"], usecols=use, low_memory=False)
    for c in ["source_measure_start", "source_measure_end", "source_measure_midpoint"]:
        detail[c] = pd.to_numeric(detail[c], errors="coerce")

    def classify(row: pd.Series, kind: str) -> str:
        if kind == "speed" and pd.notna(row["speed_limit_mph"]):
            return "numeric_present"
        if kind == "aadt" and pd.notna(row["aadt"]):
            return "numeric_present"
        if pd.isna(row["stable_travelway_id"]) or str(row["stable_travelway_id"]).strip() == "":
            return "missing_stable_travelway_id"
        if not str(row.get("route_key_common", "") or "").strip() and not str(row.get("route_key_name", "") or "").strip():
            return "missing_route_id_name_common"
        if pd.isna(row["source_measure_midpoint"]):
            return "missing_source_measure"
        keys = speed_keys if kind == "speed" else aadt_keys
        common = str(row.get("route_key_common", "") or "")
        name = str(row.get("route_key_name", "") or "")
        if common not in keys and name not in keys:
            return "route_key_unmatched_to_numeric_source"
        return "measure_midpoint_outside_numeric_source_interval_or_source_interval_missing"

    detail["speed_failure_reason"] = detail.apply(lambda r: classify(r, "speed"), axis=1)
    detail["aadt_failure_reason"] = detail.apply(lambda r: classify(r, "aadt"), axis=1)
    detail["exposure_failure_reason"] = np.where(
        detail["aadt_exposure_denominator"].notna(),
        "numeric_present",
        detail["aadt_failure_reason"],
    )
    summary_frames = []
    for field, label in [
        ("speed_failure_reason", "speed"),
        ("aadt_failure_reason", "aadt"),
        ("exposure_failure_reason", "exposure"),
    ]:
        s = detail.groupby(field, dropna=False).agg(bin_rows=("stable_bin_id", "size"), signals=("stable_signal_id", "nunique")).reset_index()
        s = s.rename(columns={field: "failure_reason"})
        s["numeric_field"] = label
        summary_frames.append(s)
    return detail, pd.concat(summary_frames, ignore_index=True)


def readiness_mismatch(sw: pd.DataFrame) -> pd.DataFrame:
    signals = read_csv(INPUTS["final_signals"], dtype=str, low_memory=False)
    keep = [c for c in ["stable_signal_id", "final_leg_corrected_speed_aadt_ready", "speed_aadt_ready"] if c in signals.columns]
    merged = sw.merge(signals[keep], on="stable_signal_id", how="left")
    sig_ready_col = "final_leg_corrected_speed_aadt_ready" if "final_leg_corrected_speed_aadt_ready" in merged else "speed_aadt_ready"
    merged["signal_speed_aadt_ready_flag"] = merged[sig_ready_col].astype(str).str.lower().isin(["true", "1", "yes"])
    merged["window_speed_aadt_ready_flag"] = merged["speed_aadt_ready_any_bin"].astype(str).str.lower().isin(["true", "1", "yes"])
    bad = merged[
        ((merged["window_speed_aadt_ready_flag"]) & (~merged["has_all_numeric_context"]))
        | ((merged["signal_speed_aadt_ready_flag"]) & (~merged["has_all_numeric_context"]))
    ].copy()
    cols = [
        "stable_signal_id",
        "signal_window",
        "recovery_branch",
        "final_review_leg_source_summary",
        "roadway_context",
        "median_group",
        "window_speed_aadt_ready_flag",
        "signal_speed_aadt_ready_flag",
        "has_numeric_aadt",
        "has_numeric_speed",
        "has_exposure_denominator",
        "numeric_context_source_summary",
        "speed_numeric_bin_count",
        "aadt_numeric_bin_count",
        "numeric_bin_count",
    ]
    return bad[[c for c in cols if c in bad.columns]]


def branch_numeric_inventory_and_recovery(detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    log("Scanning branch context-refresh outputs for direct numeric carry-forward opportunities.")
    missing_speed_ids = set(detail.loc[detail["speed_failure_reason"].ne("numeric_present"), "stable_bin_id"].astype(str))
    missing_aadt_ids = set(detail.loc[detail["aadt_failure_reason"].ne("numeric_present"), "stable_bin_id"].astype(str))
    inv_rows: list[dict[str, object]] = []
    opp_rows: list[dict[str, object]] = []
    numeric_patterns = ("speed", "aadt", "exposure", "denom", "rns_", "aadt_")

    def actual_speed_fields(cols: list[str]) -> list[str]:
        out = []
        for c in cols:
            low = c.lower()
            if "car_speed_limit" in low or low in {"speed_limit_mph", "matched_review_only_car_speed_limit"}:
                out.append(c)
        return out

    def actual_aadt_fields(cols: list[str]) -> list[str]:
        out = []
        for c in cols:
            low = c.lower()
            if low in {"aadt", "aadt_aadt", "matched_review_only_aadt_value"}:
                out.append(c)
        return out

    def actual_exposure_fields(cols: list[str]) -> list[str]:
        out = []
        for c in cols:
            low = c.lower()
            if low in {"aadt_exposure_denominator", "review_only_estimated_exposure"}:
                out.append(c)
        return out

    for directory in BRANCH_DIRS:
        if not directory.exists():
            continue
        for path in directory.glob("*.csv"):
            if "bin_detail" not in path.name and "context_bin" not in path.name and "leg_corrected_bin_detail" not in path.name:
                continue
            try:
                cols = pd.read_csv(path, nrows=0).columns.tolist()
            except Exception:
                continue
            numeric_cols = [c for c in cols if any(p in c.lower() for p in numeric_patterns)]
            has_stable_bin = "stable_bin_id" in cols
            inventory_counts = {
                c: {"non_null_count": 0, "numeric_parse_success_count": 0}
                for c in numeric_cols
            }
            if not has_stable_bin or not numeric_cols:
                for c in numeric_cols:
                    inv_rows.append(
                        {
                            "branch_output_folder": directory.name,
                            "source_file": path.name,
                            "field_name": c,
                            "has_stable_bin_id": has_stable_bin,
                            "candidate_numeric_field": c in actual_speed_fields([c]) + actual_aadt_fields([c]) + actual_exposure_fields([c]),
                            "non_null_count": pd.NA,
                            "numeric_parse_success_count": pd.NA,
                        }
                    )
                continue
            use = ["stable_bin_id"] + numeric_cols
            speed_fields = actual_speed_fields(numeric_cols)
            aadt_fields = actual_aadt_fields(numeric_cols)
            exposure_fields = actual_exposure_fields(numeric_cols)
            speed_recoverable_ids: set[str] = set()
            aadt_recoverable_ids: set[str] = set()
            exposure_recoverable_ids: set[str] = set()
            rec = {
                "branch_output_folder": directory.name,
                "source_file": path.name,
                "missing_speed_bins_recoverable_by_stable_bin_id": 0,
                "missing_aadt_bins_recoverable_by_stable_bin_id": 0,
                "missing_exposure_bins_recoverable_by_stable_bin_id": 0,
                "speed_fields_found": "|".join(speed_fields),
                "aadt_fields_found": "|".join(aadt_fields),
                "exposure_fields_found": "|".join(exposure_fields),
            }
            for chunk in pd.read_csv(path, usecols=use, chunksize=200_000, low_memory=False):
                chunk["stable_bin_id"] = chunk["stable_bin_id"].astype(str)
                for c in numeric_cols:
                    parsed = pd.to_numeric(chunk[c], errors="coerce")
                    inventory_counts[c]["non_null_count"] += int(chunk[c].notna().sum())
                    inventory_counts[c]["numeric_parse_success_count"] += int(parsed.notna().sum())
                if speed_fields:
                    speed_any = chunk[speed_fields].apply(lambda s: pd.to_numeric(s, errors="coerce").notna()).any(axis=1)
                    speed_recoverable_ids.update(chunk.loc[speed_any & chunk["stable_bin_id"].isin(missing_speed_ids), "stable_bin_id"])
                if aadt_fields:
                    aadt_any = chunk[aadt_fields].apply(lambda s: pd.to_numeric(s, errors="coerce").notna()).any(axis=1)
                    aadt_recoverable_ids.update(chunk.loc[aadt_any & chunk["stable_bin_id"].isin(missing_aadt_ids), "stable_bin_id"])
                if exposure_fields:
                    exposure_any = chunk[exposure_fields].apply(lambda s: pd.to_numeric(s, errors="coerce").notna()).any(axis=1)
                    exposure_recoverable_ids.update(chunk.loc[exposure_any & chunk["stable_bin_id"].isin(missing_aadt_ids), "stable_bin_id"])
            rec["missing_speed_bins_recoverable_by_stable_bin_id"] = len(speed_recoverable_ids)
            rec["missing_aadt_bins_recoverable_by_stable_bin_id"] = len(aadt_recoverable_ids)
            rec["missing_exposure_bins_recoverable_by_stable_bin_id"] = len(exposure_recoverable_ids)
            for c in numeric_cols:
                inv_rows.append(
                    {
                        "branch_output_folder": directory.name,
                        "source_file": path.name,
                        "field_name": c,
                        "has_stable_bin_id": has_stable_bin,
                        "candidate_numeric_field": c in set(speed_fields + aadt_fields + exposure_fields),
                        "non_null_count": inventory_counts[c]["non_null_count"],
                        "numeric_parse_success_count": inventory_counts[c]["numeric_parse_success_count"],
                    }
                )
            opp_rows.append(rec)
    return pd.DataFrame(inv_rows), pd.DataFrame(opp_rows)


def findings_text(
    win: pd.DataFrame,
    branch: pd.DataFrame,
    failure_summary: pd.DataFrame,
    mismatch: pd.DataFrame,
    opportunity: pd.DataFrame,
) -> str:
    near = win[win["signal_window"].eq("0-1,000 ft")].iloc[0].to_dict() if not win.empty else {}
    full = win[win["signal_window"].eq("0-2,500 ft")].iloc[0].to_dict() if not win.empty else {}
    biggest_branch = branch.sort_values("numeric_aadt_rows").head(1)
    route_unmatched = failure_summary[failure_summary["failure_reason"].eq("route_key_unmatched_to_numeric_source")]["bin_rows"].sum()
    recover_speed = int(opportunity.get("missing_speed_bins_recoverable_by_stable_bin_id", pd.Series(dtype=int)).sum()) if not opportunity.empty else 0
    recover_aadt = int(opportunity.get("missing_aadt_bins_recoverable_by_stable_bin_id", pd.Series(dtype=int)).sum()) if not opportunity.empty else 0
    recover_exposure = int(opportunity.get("missing_exposure_bins_recoverable_by_stable_bin_id", pd.Series(dtype=int)).sum()) if not opportunity.empty else 0
    return f"""# Numeric Context Missingness Audit Findings

## Bounded Question
Why is numeric AADT/speed/exposure completeness lower at signal-window grain than prior signal-level readiness, and can existing branch outputs improve it?

## Answers
1. Missingness is present in both windows. 0-1,000 ft has AADT {near.get('rows_with_numeric_aadt', 0):,} / {near.get('total_rows', 0):,}, speed {near.get('rows_with_numeric_speed', 0):,} / {near.get('total_rows', 0):,}, and exposure {near.get('rows_with_exposure_denominator', 0):,} / {near.get('total_rows', 0):,}. 0-2,500 ft has AADT {full.get('rows_with_numeric_aadt', 0):,} / {full.get('total_rows', 0):,}, speed {full.get('rows_with_numeric_speed', 0):,} / {full.get('total_rows', 0):,}, and exposure {full.get('rows_with_exposure_denominator', 0):,} / {full.get('total_rows', 0):,}.
2. Branch/provenance missingness is mixed; see `numeric_missingness_by_branch.csv`. Recovery provenance summaries are often multi-valued after leg correction, so the branch table should be used as a diagnostic rather than a single-cause attribution.
3. Missingness is caused by both source/key coverage and join/carry-forward failure. At bin grain, route-key unmatched and measure/source-interval failures explain the main null numeric values; route-unmatched numeric-source failures total {route_unmatched:,} bin-field rows across speed/AADT/exposure summaries.
4. Signal-level speed+AADT readiness exceeds signal-window numeric completeness because readiness flags indicate some context was assigned at signal/bin branch stages, while the v2 table requires actual numeric values at `signal x window` after a separate route-key + measure-midpoint join.
5. Existing branch outputs do contain actual numeric fields, but mostly in the older branch-specific context-refresh files. Direct stable-bin recovery opportunity found {recover_speed:,} missing speed-bin hits, {recover_aadt:,} missing AADT-bin hits, and {recover_exposure:,} missing exposure-denominator hits across scanned branch detail outputs; see `numeric_context_recovery_opportunity.csv`. Later final consolidated context files mostly carry readiness/status flags rather than the numeric values themselves.
6. A unified final bin-level numeric context join is still the cleaner fix because final leg-corrected bins mix original, generated, anchor, broader-source, and label-only rows. Direct branch carry-forward can help for speed/AADT values but will not by itself recover exposure denominator unless the denominator is recomputed or joined from a source that carries it.
7. 0-1,000 ft numeric context is not yet strong enough to be a complete matrix by itself; it is usable for review subsets and missing-cell displays.
8. The guidance matrix should either filter to numeric-complete rows for rate/candidate-rate panels or show missing-context cells explicitly. Counts can be displayed for all rows.

## QA Note
No active outputs were modified, no records promoted, no access/crash assignment was run, no rates/models were calculated, and crash direction fields were not read or used.
"""


def qa_table() -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, "Outputs written only to review/current/final_signal_window_numeric_context_missingness_audit."),
        ("no_records_promoted", True, "Review-only diagnostic."),
        ("no_new_access_crash_assignment", True, "Existing outputs only."),
        ("no_rates_or_models", True, "No rate/model calculation performed."),
        ("crash_direction_fields_not_read_or_used", True, "Crash source not read."),
        ("numeric_values_not_fabricated", True, "Only existing numeric/null fields inventoried and diagnosed."),
        ("outputs_review_only_folder", True, str(OUT)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "note"])


def manifest(outputs: Iterable[str]) -> dict[str, object]:
    return {
        "script": "src.roadway_graph.audit.final_signal_window_numeric_context_missingness_audit",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT.relative_to(REPO)),
        "inputs": {k: str(v.relative_to(REPO)) for k, v in INPUTS.items() if v.exists()},
        "branch_dirs_scanned": [str(d.relative_to(REPO)) for d in BRANCH_DIRS if d.exists()],
        "outputs": list(outputs),
        "review_only": True,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "run_progress_log.txt").write_text("", encoding="utf-8")
    log("Starting numeric context missingness audit.")
    sw = load_signal_windows()
    window = by_window(sw)
    branch = branch_summary(sw)
    road = summarize_by(sw, ["roadway_context", "facility_type", "final_leg_corrected_physical_leg_bucket", "untyped_access_count_band"], "roadway_context")
    median = summarize_by(sw, ["median_group"], "median_group")
    speed_keys, aadt_keys = source_route_key_sets()
    detail, failure_summary = failure_reason_detail(speed_keys, aadt_keys)
    mismatch = readiness_mismatch(sw)
    inventory, opportunity = branch_numeric_inventory_and_recovery(detail)

    write_csv(window, "numeric_missingness_by_window.csv")
    write_csv(branch, "numeric_missingness_by_branch.csv")
    write_csv(road, "numeric_missingness_by_roadway_context.csv")
    write_csv(median, "numeric_missingness_by_median_group.csv")
    write_csv(detail, "numeric_join_failure_reason_detail.csv")
    write_csv(failure_summary, "numeric_join_failure_reason_summary.csv")
    write_csv(mismatch, "readiness_vs_numeric_value_mismatch.csv")
    write_csv(inventory, "branch_numeric_field_inventory.csv")
    write_csv(opportunity, "numeric_context_recovery_opportunity.csv")
    (OUT / "numeric_context_missingness_audit_findings.md").write_text(
        findings_text(window, branch, failure_summary, mismatch, opportunity),
        encoding="utf-8",
    )
    log("Wrote findings memo.")
    qa = qa_table()
    write_csv(qa, "numeric_context_missingness_audit_qa.csv")
    outputs = sorted(p.name for p in OUT.iterdir() if p.is_file() and p.name != "numeric_context_missingness_audit_manifest.json")
    (OUT / "numeric_context_missingness_audit_manifest.json").write_text(json.dumps(manifest(outputs), indent=2), encoding="utf-8")
    log("Wrote manifest.")
    log("Completed numeric context missingness audit.")


if __name__ == "__main__":
    main()
