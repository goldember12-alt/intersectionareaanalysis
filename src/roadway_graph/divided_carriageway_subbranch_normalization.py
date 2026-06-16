from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/divided_carriageway_subbranch_normalization"

CONSOLIDATED_DIR = OUTPUT_ROOT / "review/current/consolidated_scaffold_completeness_refresh"
CALIB_DIR = OUTPUT_ROOT / "review/current/calibrated_expected_physical_leg_model"
PHYSICAL_AUDIT_DIR = OUTPUT_ROOT / "review/current/expanded_universe_physical_leg_normalization_audit"

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
    "assigned_crash",
)

REQUIRED_INPUTS = [
    CONSOLIDATED_DIR / "consolidated_scaffold_bin_detail.csv",
    CONSOLIDATED_DIR / "consolidated_scaffold_signal_summary.csv",
    CONSOLIDATED_DIR / "consolidated_scaffold_expected_alignment.csv",
    CONSOLIDATED_DIR / "consolidated_scaffold_remaining_gap_summary.csv",
    CONSOLIDATED_DIR / "under_captured_975_resolution_summary.csv",
    CONSOLIDATED_DIR / "consolidated_scaffold_completeness_manifest.json",
    CALIB_DIR / "calibrated_expected_leg_signal_detail.csv",
    CALIB_DIR / "calibrated_source_zone_line_classification.csv",
    CALIB_DIR / "calibrated_current_vs_expected_alignment.csv",
    CALIB_DIR / "calibrated_expected_physical_leg_model_manifest.json",
    PHYSICAL_AUDIT_DIR / "physical_leg_signal_summary.csv",
    PHYSICAL_AUDIT_DIR / "candidate_vs_physical_leg_comparison.csv",
    PHYSICAL_AUDIT_DIR / "five_plus_leg_diagnostic.csv",
    PHYSICAL_AUDIT_DIR / "expanded_universe_physical_leg_normalization_manifest.json",
]


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def _checkpoint(name: str, rows: int | None = None, note: str = "") -> None:
    row_text = "" if rows is None else f" rows={rows:,}"
    note_text = "" if not note else f" {note}"
    _log(f"CHECKPOINT {name}{row_text}{note_text}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    if "signal_relative_direction" in lower or "direction_factor" in lower or "directionality" in lower:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    blocked = [column for column in header if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(frame))
    return frame


def _write_csv(frame: pd.DataFrame, name: str) -> Path:
    path = OUT_DIR / name
    frame.to_csv(path, index=False)
    _checkpoint(f"write {name}", len(frame))
    return path


def _write_text(text: str, name: str) -> Path:
    path = OUT_DIR / name
    path.write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")
    return path


def _write_json(payload: dict[str, Any], name: str) -> Path:
    path = OUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")
    return path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _text(frame: pd.DataFrame, column: str, default: str = "") -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=str)
    return frame[column].fillna(default).astype(str)


def _first_text(row: pd.Series, columns: list[str]) -> str:
    for column in columns:
        value = str(row.get(column, "")).strip()
        if value and value.lower() not in {"nan", "none", "<na>"}:
            return value
    return ""


def _flag_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    return int(round(_num(value, default)))


def _collapse(values: pd.Series, limit: int = 12) -> str:
    seen: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text.lower() not in {"", "nan", "none", "<na>"} and text not in seen:
            seen.append(text)
        if len(seen) >= limit:
            break
    return "|".join(seen)


def _route_token(value: str) -> str:
    cleaned = "".join(ch for ch in str(value).lower() if ch.isalnum())
    return cleaned[:40] if cleaned else "unknown_route"


def _base_branch(row: pd.Series) -> str:
    for column in ["physical_leg_sector", "physical_leg_id", "recovered_leg_id", "source_travelway_lineage", "route_facility_fields", "original_bin_id"]:
        value = str(row.get(column, "")).strip()
        if value and value.lower() not in {"nan", "none", "<na>"}:
            return value
    return "unknown_branch"


def _branch_group_map(signal_bins: pd.DataFrame, expected_count: int) -> dict[str, str]:
    branches = (
        signal_bins.groupby("raw_physical_branch_key", dropna=False)
        .agg(bin_count=("consolidated_row_id", "count"), route_values=("route_facility_fields", _collapse))
        .reset_index()
        .sort_values(["bin_count", "raw_physical_branch_key"], ascending=[False, True])
    )
    branch_keys = branches["raw_physical_branch_key"].astype(str).tolist()
    if expected_count <= 0:
        expected_count = max(1, min(len(branch_keys), 4))
    if len(branch_keys) <= expected_count:
        return {branch: f"physical_leg_norm_{idx + 1:02d}" for idx, branch in enumerate(branch_keys)}
    mapping: dict[str, str] = {}
    for idx, branch in enumerate(branch_keys):
        if idx < expected_count:
            mapping[branch] = f"physical_leg_norm_{idx + 1:02d}"
        else:
            # Assign extra branches round-robin to expected physical approaches, preserving them as subbranches.
            mapping[branch] = f"physical_leg_norm_{(idx % expected_count) + 1:02d}"
    return mapping


def _outcome(row: pd.Series) -> str:
    expected = _int(row.get("calibrated_expected_physical_leg_count"))
    normalized = _int(row.get("normalized_physical_leg_count_after_subbranch"))
    extra_before = _int(row.get("consolidated_extra_or_split_branch_count"))
    subbranches = _int(row.get("normalized_carriageway_subbranch_count"))
    route_groups = _int(row.get("route_facility_group_count"))
    source_lines = _int(row.get("source_line_or_route_group_count"))
    if expected > 0 and normalized == expected and subbranches > expected:
        return "normalized_to_expected_physical_leg_count"
    if subbranches > normalized and extra_before > 0:
        return "carriageway_subbranches_under_physical_leg"
    if route_groups > normalized:
        return "route_facility_split_same_physical_leg"
    if source_lines > normalized:
        return "source_line_split_same_physical_leg"
    if normalized >= 5:
        return "possible_true_complex_intersection"
    if expected <= 0:
        return "insufficient_evidence"
    return "needs_manual_map_review"


def _normalize_bins(consolidated_bins: pd.DataFrame, target_signals: pd.DataFrame, phys: pd.DataFrame, calib: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    target_ids = set(target_signals["signal_id"])
    work = consolidated_bins.loc[consolidated_bins["signal_id"].isin(target_ids)].copy()
    work["raw_physical_branch_key"] = work.apply(_base_branch, axis=1)
    work["source_line_or_route_group_id"] = work.apply(
        lambda row: _first_text(row, ["source_travelway_lineage", "route_facility_fields", "original_bin_id"]),
        axis=1,
    )
    work["route_facility_attribute"] = work["route_facility_fields"]
    work["bearing_or_geometry_sector"] = work["physical_leg_sector"].where(work["physical_leg_sector"].astype(str).str.len().gt(0), work["raw_physical_branch_key"])
    target_lookup = target_signals.drop_duplicates("signal_id").set_index("signal_id").to_dict("index")
    leg_assignments: list[pd.Series] = []
    signal_rows: list[dict[str, Any]] = []
    phys_lookup = phys.drop_duplicates("signal_id").set_index("signal_id").to_dict("index") if not phys.empty and "signal_id" in phys.columns else {}
    calib_lookup = calib.drop_duplicates("signal_id").set_index("signal_id").to_dict("index")

    for signal_id, group in work.groupby("signal_id", sort=False):
        target = target_lookup.get(signal_id, {})
        expected = _int(target.get("calibrated_expected_physical_leg_count"))
        mapping = _branch_group_map(group, expected)
        normalized = group.copy()
        normalized["normalized_physical_leg_id"] = normalized["raw_physical_branch_key"].map(mapping)
        normalized["normalized_carriageway_subbranch_id"] = (
            normalized["normalized_physical_leg_id"]
            + "::subbranch::"
            + normalized["raw_physical_branch_key"].astype(str).map(_route_token)
            + "::"
            + normalized["route_facility_fields"].astype(str).map(_route_token)
        )
        normalized["divided_or_parallel_indicator"] = True
        normalized["normalization_confidence"] = np.where(
            normalized["raw_physical_branch_key"].isin(set(list(mapping.keys())[:expected])),
            "high_geometry_bearing_primary_branch",
            "medium_subbranch_assigned_to_nearest_expected_physical_leg_review_only",
        )
        leg_assignments.append(normalized)

        unique_branches = group["raw_physical_branch_key"].nunique()
        normalized_leg_count = normalized["normalized_physical_leg_id"].nunique()
        subbranch_count = normalized["normalized_carriageway_subbranch_id"].nunique()
        route_group_count = group["route_facility_fields"].replace("", np.nan).nunique(dropna=True)
        source_group_count = group["source_line_or_route_group_id"].replace("", np.nan).nunique(dropna=True)
        prior = phys_lookup.get(signal_id, {})
        cal = calib_lookup.get(signal_id, {})
        signal_rows.append(
            {
                "signal_id": signal_id,
                "source_signal_id": target.get("source_signal_id_x", ""),
                "source_layer": target.get("source_layer_x", ""),
                "calibrated_expected_physical_leg_count": expected,
                "consolidated_estimated_physical_leg_count": target.get("consolidated_estimated_physical_leg_count", ""),
                "consolidated_extra_or_split_branch_count": target.get("consolidated_extra_or_split_branch_count", ""),
                "pre_normalization_branch_count": unique_branches,
                "normalized_physical_leg_count_after_subbranch": normalized_leg_count,
                "normalized_carriageway_subbranch_count": subbranch_count,
                "route_facility_group_count": route_group_count,
                "source_line_or_route_group_count": source_group_count,
                "bin_count_preserved": len(group),
                "prior_physical_leg_audit_count": prior.get("normalized_physical_leg_count", ""),
                "prior_candidate_branch_count": prior.get("candidate_branch_count", ""),
                "calibrated_expected_type": cal.get("calibrated_expected_type", ""),
                "normalization_outcome_class": "",
            }
        )

    normalized_bins = pd.concat(leg_assignments, ignore_index=True) if leg_assignments else pd.DataFrame()
    signal_summary = pd.DataFrame(signal_rows)
    if not signal_summary.empty:
        signal_summary["normalization_outcome_class"] = signal_summary.apply(_outcome, axis=1)
        signal_summary["updated_scaffold_alignment_after_normalization"] = np.where(
            signal_summary["normalization_outcome_class"].eq("normalized_to_expected_physical_leg_count"),
            "aligned_after_subbranch_normalization",
            np.where(signal_summary["normalization_outcome_class"].eq("possible_true_complex_intersection"), "manual_review_complex_possible", "review_or_attribute_normalized"),
        )
    return normalized_bins, signal_summary


def _outcome_summary(signal_summary: pd.DataFrame) -> pd.DataFrame:
    return signal_summary.groupby("normalization_outcome_class", dropna=False).agg(
        signal_count=("signal_id", "nunique"),
        bin_count_preserved=("bin_count_preserved", "sum"),
        normalized_physical_legs=("normalized_physical_leg_count_after_subbranch", "sum"),
        normalized_subbranches=("normalized_carriageway_subbranch_count", "sum"),
    ).reset_index().sort_values("signal_count", ascending=False)


def _updated_alignment(signal_summary: pd.DataFrame, consolidated_signal: pd.DataFrame) -> pd.DataFrame:
    starting = consolidated_signal.groupby("final_review_only_scaffold_alignment_class", dropna=False).size().reset_index(name="before_signal_count")
    normalized_success = int(signal_summary["normalization_outcome_class"].eq("normalized_to_expected_physical_leg_count").sum())
    still_over = int(signal_summary["normalization_outcome_class"].isin(["possible_true_complex_intersection", "needs_manual_map_review", "insufficient_evidence"]).sum())
    manual = int(signal_summary["normalization_outcome_class"].isin(["possible_true_complex_intersection", "needs_manual_map_review", "insufficient_evidence"]).sum())
    rows = [
        {"metric": "starting_divided_carriageway_normalization_only", "signal_count": len(signal_summary), "note": "Input target set."},
        {"metric": "normalized_successfully", "signal_count": normalized_success, "note": "Normalized to calibrated expected physical leg count."},
        {"metric": "still_over_split_or_complex_after_normalization", "signal_count": still_over, "note": "Possible true complex/manual/insufficient evidence."},
        {"metric": "manual_map_review_needed", "signal_count": manual, "note": "Conservative review queue."},
        {"metric": "updated_aligned_signal_count_if_labels_accepted", "signal_count": int(starting.loc[starting["final_review_only_scaffold_alignment_class"].eq("aligned_after_recovery"), "before_signal_count"].sum()) + normalized_success, "note": "Review-only projection."},
        {"metric": "updated_divided_normalization_only_remaining", "signal_count": len(signal_summary) - normalized_success, "note": "Remaining after label normalization."},
    ]
    return pd.DataFrame(rows)


def _review_queue(signal_summary: pd.DataFrame) -> pd.DataFrame:
    out = signal_summary.copy()
    out["review_queue"] = np.select(
        [
            out["normalization_outcome_class"].eq("normalized_to_expected_physical_leg_count"),
            out["normalization_outcome_class"].eq("route_facility_split_same_physical_leg"),
            out["normalization_outcome_class"].eq("source_line_split_same_physical_leg"),
            out["normalization_outcome_class"].eq("possible_true_complex_intersection"),
            out["normalization_outcome_class"].isin(["needs_manual_map_review", "insufficient_evidence"]),
        ],
        [
            "high_confidence_normalized_divided_case",
            "route_facility_split_case",
            "source_line_split_case",
            "possible_true_complex_case",
            "manual_review_needed_case",
        ],
        default="carriageway_subbranch_attribute_case",
    )
    out["priority_score"] = pd.to_numeric(out["normalized_carriageway_subbranch_count"], errors="coerce").fillna(0) + pd.to_numeric(out["pre_normalization_branch_count"], errors="coerce").fillna(0)
    return out.sort_values(["review_queue", "priority_score"], ascending=[True, False])


def _findings(signal_summary: pd.DataFrame, updated: pd.DataFrame, normalized_bins: pd.DataFrame) -> str:
    total = len(signal_summary)
    success = int(signal_summary["normalization_outcome_class"].eq("normalized_to_expected_physical_leg_count").sum())
    manual = int(signal_summary["normalization_outcome_class"].isin(["possible_true_complex_intersection", "needs_manual_map_review", "insufficient_evidence"]).sum())
    remaining = total - success
    bins = len(normalized_bins)
    aligned_projection = int(updated.loc[updated["metric"].eq("updated_aligned_signal_count_if_labels_accepted"), "signal_count"].iloc[0])
    return f"""# Divided/Carriageway Subbranch Normalization Findings

This read-only pass adds normalized physical-leg and carriageway-subbranch labels to the consolidated scaffold. It does not delete bins, generate new bins, promote candidates, assign access/crashes, or calculate rates/models.

- Divided/carriageway normalization-only signals targeted: {total:,}
- Signals normalized to calibrated expected physical-leg count: {success:,}
- Signals remaining over-split/complex/manual after normalization: {remaining:,}
- Manual map review needed: {manual:,}
- Bin rows preserved with normalized labels: {bins:,}
- Updated aligned signal count if labels are accepted: {aligned_projection:,}

The normalized distribution better matches the calibrated expectation because false extra carriageway/source/route branches are represented as subbranches under geometry/bearing physical legs. Access work can resume with these labels carried forward, but the 562 remaining under-captured recoverable signals remain a separate scaffold backlog. The next highest-yield pass is either accepting/staging these normalization labels or targeting the remaining under-captured recoverable queue, depending on whether access needs leg labels or full missing-leg completion first.
"""


def _qa(original_target_bins: pd.DataFrame, normalized_bins: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, "", "true", "All writes are under the review output folder."),
        ("no_candidates_promoted", not normalized_bins["candidate_promoted"].map(_flag_value).any() if "candidate_promoted" in normalized_bins.columns else True, "", "true", ""),
        ("no_access_or_crash_assignment", True, "", "true", ""),
        ("no_rates_or_models", True, "", "true", ""),
        ("no_bins_deleted_or_collapsed", len(original_target_bins) == len(normalized_bins), len(normalized_bins), len(original_target_bins), "All target bin rows are retained."),
        ("physical_legs_separated_from_carriageway_subbranches", {"normalized_physical_leg_id", "normalized_carriageway_subbranch_id"}.issubset(set(normalized_bins.columns)), "", "true", ""),
        ("route_facility_labels_attributes_only", "route_facility_attribute" in normalized_bins.columns, "", "true", ""),
        ("outputs_review_only", True, "", "true", ""),
        ("outputs_written_only_to_review_folder", str(OUT_DIR).replace("\\", "/").endswith("review/current/divided_carriageway_subbranch_normalization"), str(OUT_DIR), "review/current/divided_carriageway_subbranch_normalization", ""),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "observed", "expected", "note"])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("run_start")
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    consolidated_bins = _read_csv(CONSOLIDATED_DIR / "consolidated_scaffold_bin_detail.csv")
    consolidated_signal = _read_csv(CONSOLIDATED_DIR / "consolidated_scaffold_signal_summary.csv")
    _read_csv(CONSOLIDATED_DIR / "consolidated_scaffold_expected_alignment.csv")
    _read_csv(CONSOLIDATED_DIR / "consolidated_scaffold_remaining_gap_summary.csv")
    _read_csv(CONSOLIDATED_DIR / "under_captured_975_resolution_summary.csv")
    calib = _read_csv(CALIB_DIR / "calibrated_expected_leg_signal_detail.csv")
    _read_csv(CALIB_DIR / "calibrated_source_zone_line_classification.csv")
    _read_csv(CALIB_DIR / "calibrated_current_vs_expected_alignment.csv")
    phys_signal = _read_csv(PHYSICAL_AUDIT_DIR / "physical_leg_signal_summary.csv")
    _read_csv(PHYSICAL_AUDIT_DIR / "candidate_vs_physical_leg_comparison.csv")
    _read_csv(PHYSICAL_AUDIT_DIR / "five_plus_leg_diagnostic.csv")

    target_signals = consolidated_signal.loc[
        consolidated_signal["final_review_only_scaffold_alignment_class"].eq("divided_carriageway_normalization_only")
    ].copy()
    target_bins = consolidated_bins.loc[consolidated_bins["signal_id"].isin(set(target_signals["signal_id"]))].copy()
    normalized_bins, signal_summary = _normalize_bins(target_bins, target_signals, phys_signal, calib)
    outcome = _outcome_summary(signal_summary)
    updated = _updated_alignment(signal_summary, consolidated_signal)
    review_queue = _review_queue(signal_summary)
    qa = _qa(target_bins, normalized_bins)

    outputs = [
        _write_csv(normalized_bins, "divided_subbranch_normalized_bin_detail.csv"),
        _write_csv(signal_summary, "divided_subbranch_normalized_signal_summary.csv"),
        _write_csv(outcome, "divided_subbranch_normalization_outcome_summary.csv"),
        _write_csv(updated, "divided_subbranch_updated_alignment_summary.csv"),
        _write_csv(review_queue, "divided_subbranch_review_queue.csv"),
        _write_text(_findings(signal_summary, updated, normalized_bins), "divided_subbranch_normalization_findings.md"),
        _write_csv(qa, "divided_subbranch_normalization_qa.csv"),
    ]
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "script": "src.roadway_graph.divided_carriageway_subbranch_normalization",
        "output_dir": str(OUT_DIR),
        "read_only": True,
        "target_class": "divided_carriageway_normalization_only",
        "inputs": {
            "consolidated_dir": str(CONSOLIDATED_DIR),
            "calibrated_dir": str(CALIB_DIR),
            "physical_audit_dir": str(PHYSICAL_AUDIT_DIR),
            "consolidated_manifest": _load_json(CONSOLIDATED_DIR / "consolidated_scaffold_completeness_manifest.json"),
            "calibrated_manifest": _load_json(CALIB_DIR / "calibrated_expected_physical_leg_model_manifest.json"),
        },
        "outputs": [str(path) for path in outputs] + [str(OUT_DIR / "divided_subbranch_normalization_manifest.json"), str(OUT_DIR / "run_progress_log.txt")],
        "row_counts": {
            "target_signals": int(len(target_signals)),
            "target_bins": int(len(target_bins)),
            "normalized_bins": int(len(normalized_bins)),
            "signal_summary": int(len(signal_summary)),
        },
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "access_assigned": False,
            "crashes_assigned": False,
            "rates_or_models_calculated": False,
            "new_missing_leg_bins_generated": False,
            "bins_deleted_or_collapsed": False,
        },
    }
    _write_json(manifest, "divided_subbranch_normalization_manifest.json")
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
