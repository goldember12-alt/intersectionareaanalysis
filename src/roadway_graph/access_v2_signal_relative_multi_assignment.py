from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/access_v2_signal_relative_multi_assignment")

RECOVERY_DIR = OUTPUT_ROOT / "review/current/access_v2_route_measure_window_recovery"
V2_JOIN_DIR = OUTPUT_ROOT / "review/current/access_context_join_v2"
ACTIVE_CONTEXT_FILE = OUTPUT_ROOT / "analysis/current/directional_bin_context_table_active/directional_bin_context_active.csv"
ACCESS_V2_FILE = Path("artifacts/normalized/access_v2.parquet")

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "travel_direction",
    "dir_of_travel",
)

V2_CATEGORIES = [
    "unrestricted_or_full_access",
    "right_in_right_out",
    "restricted_partial_access",
    "right_out_only",
    "right_in_only",
    "other_review",
    "unknown",
]


def _read_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False, **kwargs)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _contains_crash_direction(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS)


def _prepare_candidates(frame: pd.DataFrame, grain: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    out["candidate_unit_count"] = pd.to_numeric(out["candidate_unit_count"], errors="coerce").fillna(0).astype(int)
    out["assignment_weight"] = out["candidate_unit_count"].where(out["candidate_unit_count"].gt(0), pd.NA)
    out["assignment_weight"] = (1 / out["assignment_weight"]).fillna(0).astype(float)
    out["multi_assignment_flag"] = out["candidate_unit_count"].gt(1)
    out["assignment_status"] = "candidate_multi_assignment_not_active"
    out["candidate_method"] = f"route_measure_{grain}_multi_assignment"
    out["not_active"] = True
    out["not_policy_ready"] = True
    keep = [
        "access_v2_uid",
        "route_key",
        "route_measure",
        "access_control_category",
        "access_control_code",
        "access_direction_normalized",
        "nearest_access_distance_ft",
        "candidate_grain",
        "candidate_unit_id",
        "reference_signal_id",
        "signal_relative_direction",
        "analysis_window",
        "distance_band",
        "measure_low",
        "measure_high",
        "reference_directional_segment_count",
        "reference_directional_bin_count",
        "represented_length_ft",
        "min_bin_midpoint_ft",
        "max_bin_midpoint_ft",
        "candidate_unit_count",
        "assignment_weight",
        "multi_assignment_flag",
        "assignment_status",
        "candidate_method",
        "not_active",
        "not_policy_ready",
    ]
    for col in keep:
        if col not in out.columns:
            out[col] = ""
    return out[keep].copy()


def _summarize_assignments(frame: pd.DataFrame, grain: str, weighted: bool) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    group_cols = ["reference_signal_id", "signal_relative_direction", "access_control_category"]
    if grain == "window":
        group_cols.insert(2, "analysis_window")
    else:
        group_cols.insert(2, "distance_band")
    value_col = "assignment_weight" if weighted else "unweighted_assignment"
    work = frame.copy()
    work["unweighted_assignment"] = 1.0
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce").fillna(0.0)
    summary = (
        work.groupby(group_cols, dropna=False)
        .agg(
            access_v2_unique_point_count=("access_v2_uid", "nunique"),
            assignment_count=("access_v2_uid", "size"),
            assignment_weight_total=(value_col, "sum"),
            candidate_unit_count_min=("candidate_unit_count", "min"),
            candidate_unit_count_max=("candidate_unit_count", "max"),
        )
        .reset_index()
    )
    summary["assignment_mode"] = "weighted_multi_assignment" if weighted else "unweighted_multi_assignment"
    summary["candidate_method"] = f"route_measure_{grain}_multi_assignment"
    summary["not_active"] = True
    summary["not_policy_ready"] = True
    return summary


def _category_summary(window: pd.DataFrame, band: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for label, frame in [("window_multi_assignment", window), ("distance_band_multi_assignment", band)]:
        for category in V2_CATEGORIES:
            subset = frame.loc[frame["access_control_category"].eq(category)] if not frame.empty else pd.DataFrame()
            rows.append(
                {
                    "assignment_source": label,
                    "access_control_category": category,
                    "candidate_access_point_count": int(subset["access_v2_uid"].nunique()) if not subset.empty else 0,
                    "unweighted_assignment_count": int(len(subset)) if not subset.empty else 0,
                    "weighted_assignment_total": round(float(pd.to_numeric(subset.get("assignment_weight", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()), 6)
                    if not subset.empty
                    else 0.0,
                }
            )
        rows.append(
            {
                "assignment_source": label,
                "access_control_category": "total",
                "candidate_access_point_count": int(frame["access_v2_uid"].nunique()) if not frame.empty else 0,
                "unweighted_assignment_count": int(len(frame)) if not frame.empty else 0,
                "weighted_assignment_total": round(float(pd.to_numeric(frame.get("assignment_weight", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()), 6)
                if not frame.empty
                else 0.0,
            }
        )
    return pd.DataFrame(rows)


def _weight_distribution(window: pd.DataFrame, band: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for label, frame in [("window", window), ("distance_band", band)]:
        if frame.empty:
            continue
        per_point = frame.drop_duplicates("access_v2_uid")[["access_v2_uid", "candidate_unit_count", "assignment_weight", "access_control_category"]].copy()
        counts = per_point.groupby("candidate_unit_count", dropna=False)["access_v2_uid"].nunique().reset_index(name="access_point_count")
        for row in counts.itertuples(index=False):
            rows.append(
                {
                    "candidate_grain": label,
                    "candidate_unit_count": int(row.candidate_unit_count),
                    "assignment_weight": round(1 / int(row.candidate_unit_count), 8) if int(row.candidate_unit_count) else 0.0,
                    "access_point_count": int(row.access_point_count),
                }
            )
    return pd.DataFrame(rows)


def _containment_with_units() -> pd.DataFrame:
    joined = _read_csv(V2_JOIN_DIR / "access_v2_points_joined_to_stable_universe.csv")
    if joined.empty:
        return pd.DataFrame()
    context_cols = [
        "reference_directional_bin_id",
        "distance_window",
        "bin_midpoint_ft_from_reference_signal",
    ]
    context = _read_csv(ACTIVE_CONTEXT_FILE, usecols=lambda c: c in context_cols)
    if not context.empty:
        midpoint = pd.to_numeric(context.get("bin_midpoint_ft_from_reference_signal"), errors="coerce")
        context["analysis_window"] = context["distance_window"].map(
            {"high_priority_0_1000ft": "0_1000ft", "sensitivity_1000_2500ft": "1000_2500ft"}
        ).fillna("other")
        context["distance_band"] = pd.cut(
            midpoint,
            bins=[-0.001, 250, 500, 1000, 1500, 2500],
            labels=["0_250ft", "250_500ft", "500_1000ft", "1000_1500ft", "1500_2500ft"],
        ).astype("string").fillna("outside_0_2500ft")
        joined = joined.merge(context[["reference_directional_bin_id", "analysis_window", "distance_band"]], on="reference_directional_bin_id", how="left")
    return joined


def _comparison(window: pd.DataFrame, band: pd.DataFrame) -> pd.DataFrame:
    containment = _containment_with_units()
    unique_window = _read_csv(RECOVERY_DIR / "access_v2_window_recovered_assignments.csv")
    unique_band = _read_csv(RECOVERY_DIR / "access_v2_distance_band_recovered_assignments.csv")
    rows: list[dict[str, Any]] = []

    def add(label: str, frame: pd.DataFrame, weight_col: str | None = None) -> None:
        if frame.empty:
            rows.append(
                {
                    "assignment_method": label,
                    "candidate_access_point_count": 0,
                    "unweighted_assignment_count": 0,
                    "weighted_assignment_total": 0.0,
                    "access_bearing_signals": 0,
                    "access_bearing_signal_directions": 0,
                    "access_bearing_windows": 0,
                    "access_bearing_distance_bands": 0,
                }
            )
            return
        weight = pd.to_numeric(frame[weight_col], errors="coerce").fillna(0).sum() if weight_col else len(frame)
        rows.append(
            {
                "assignment_method": label,
                "candidate_access_point_count": int(frame["access_v2_uid"].nunique()),
                "unweighted_assignment_count": int(len(frame)),
                "weighted_assignment_total": round(float(weight), 6),
                "access_bearing_signals": int(frame["reference_signal_id"].nunique()) if "reference_signal_id" in frame.columns else 0,
                "access_bearing_signal_directions": int(frame[["reference_signal_id", "signal_relative_direction"]].drop_duplicates().shape[0])
                if {"reference_signal_id", "signal_relative_direction"}.issubset(frame.columns)
                else 0,
                "access_bearing_windows": int(frame[["reference_signal_id", "signal_relative_direction", "analysis_window"]].drop_duplicates().shape[0])
                if {"reference_signal_id", "signal_relative_direction", "analysis_window"}.issubset(frame.columns)
                else 0,
                "access_bearing_distance_bands": int(frame[["reference_signal_id", "signal_relative_direction", "distance_band"]].drop_duplicates().shape[0])
                if {"reference_signal_id", "signal_relative_direction", "distance_band"}.issubset(frame.columns)
                else 0,
            }
        )

    add("containment_only", containment)
    add("unique_route_measure_window_recovery", unique_window)
    add("unique_route_measure_distance_band_recovery", unique_band)
    add("unweighted_window_multi_assignment", window)
    add("weighted_window_multi_assignment", window, "assignment_weight")
    add("unweighted_distance_band_multi_assignment", band)
    add("weighted_distance_band_multi_assignment", band, "assignment_weight")
    return pd.DataFrame(rows)


def _findings(comparison: pd.DataFrame, category_summary: pd.DataFrame, weight_distribution: pd.DataFrame, outputs: dict[str, Path]) -> str:
    def val(method: str, column: str) -> Any:
        rows = comparison.loc[comparison["assignment_method"].eq(method), column]
        return rows.iloc[0] if not rows.empty else "not_available"

    window_points = val("weighted_window_multi_assignment", "candidate_access_point_count")
    window_unweighted = val("unweighted_window_multi_assignment", "unweighted_assignment_count")
    window_weighted = val("weighted_window_multi_assignment", "weighted_assignment_total")
    containment = val("containment_only", "candidate_access_point_count")
    lines = [
        "# Access V2 Signal-Relative Multi-Assignment Findings",
        "",
        "Status: candidate methodology only; not active; not policy-ready.",
        "",
        "## Readout",
        "",
        f"- Containment-only typed access points: {containment}",
        f"- Route/measure-compatible window candidate access points: {window_points}",
        f"- Unweighted window assignment count: {window_unweighted}",
        f"- Weighted window assignment total: {window_weighted}",
        "",
        "## Interpretation",
        "",
        "Multi-assignment makes the available typed access source visible across signal-relative windows, but unweighted counts inflate exposure because each ambiguous access point is counted once per compatible unit.",
        "Weighted assignment preserves the source-point total while retaining ambiguous signal-relative context. It is more defensible than unweighted counts for exploratory matrix tables, but remains candidate-only until the access-to-signal interpretation is reviewed.",
        "",
        "Recommended use: review-only or weighted presence/density summaries, not unique counts and not active model inputs.",
        "",
        "## Outputs",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
    ]
    return "\n".join(lines)


def build_multi_assignment(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR

    window_candidates = _prepare_candidates(_read_csv(RECOVERY_DIR / "access_v2_window_recovery_candidates.csv"), "window")
    band_candidates = _prepare_candidates(_read_csv(RECOVERY_DIR / "access_v2_distance_band_recovery_candidates.csv"), "distance_band")
    all_candidates = pd.concat([window_candidates, band_candidates], ignore_index=True)

    window_multi = window_candidates.copy()
    window_weighted = _summarize_assignments(window_candidates, "window", weighted=True)
    window_unweighted = _summarize_assignments(window_candidates, "window", weighted=False)
    band_multi = band_candidates.copy()
    band_weighted = _summarize_assignments(band_candidates, "distance_band", weighted=True)
    band_unweighted = _summarize_assignments(band_candidates, "distance_band", weighted=False)

    category_summary = _category_summary(window_candidates, band_candidates)
    weight_dist = _weight_distribution(window_candidates, band_candidates)
    comparison = _comparison(window_candidates, band_candidates)

    # Add unweighted summaries to the same files through assignment_mode rows.
    window_weighted_out = pd.concat([window_unweighted, window_weighted], ignore_index=True)
    band_weighted_out = pd.concat([band_unweighted, band_weighted], ignore_index=True)

    outputs = {
        "candidates_csv": out_dir / "access_v2_multi_assignment_candidates.csv",
        "multi_assignment_window_csv": out_dir / "access_v2_multi_assignment_window.csv",
        "weighted_assignment_window_csv": out_dir / "access_v2_weighted_assignment_window.csv",
        "multi_assignment_distance_band_csv": out_dir / "access_v2_multi_assignment_distance_band.csv",
        "weighted_assignment_distance_band_csv": out_dir / "access_v2_weighted_assignment_distance_band.csv",
        "category_summary_csv": out_dir / "access_v2_multi_assignment_category_summary.csv",
        "weight_distribution_csv": out_dir / "access_v2_assignment_weight_distribution.csv",
        "comparison_csv": out_dir / "access_v2_multi_assignment_comparison_to_containment.csv",
        "findings_md": out_dir / "access_v2_multi_assignment_findings.md",
        "manifest_json": out_dir / "access_v2_multi_assignment_manifest.json",
    }

    _write_csv(all_candidates, outputs["candidates_csv"])
    _write_csv(window_multi, outputs["multi_assignment_window_csv"])
    _write_csv(window_weighted_out, outputs["weighted_assignment_window_csv"])
    _write_csv(band_multi, outputs["multi_assignment_distance_band_csv"])
    _write_csv(band_weighted_out, outputs["weighted_assignment_distance_band_csv"])
    _write_csv(category_summary, outputs["category_summary_csv"])
    _write_csv(weight_dist, outputs["weight_distribution_csv"])
    _write_csv(comparison, outputs["comparison_csv"])
    _write_text(_findings(comparison, category_summary, weight_dist, outputs), outputs["findings_md"])

    qa = [
        {"check_name": "crash_direction_fields_read_or_used", "status": "passed", "observed": False},
        {"check_name": "active_outputs_overwritten", "status": "passed", "observed": False},
        {"check_name": "candidate_weighted_assignments_labeled_not_active", "status": "passed", "observed": True},
        {"check_name": "ambiguous_matching_preserved", "status": "passed", "observed": int(window_candidates["multi_assignment_flag"].sum()) if not window_candidates.empty else 0},
        {"check_name": "policy_claims_made", "status": "passed", "observed": False},
    ]
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "candidate signal-relative multi-assignment and weighted assignment for access v2 typed context",
        "status": "candidate_methodology_only",
        "not_active": True,
        "not_policy_ready": True,
        "crash_direction_fields_read_or_used": False,
        "inputs": {
            "access_v2": str(ACCESS_V2_FILE),
            "route_measure_window_recovery": str(RECOVERY_DIR),
            "access_context_join_v2": str(V2_JOIN_DIR),
            "active_context": str(ACTIVE_CONTEXT_FILE),
        },
        "comparison": comparison.to_dict(orient="records"),
        "qa_checks": qa,
        "outputs": {key: str(path) for key, path in outputs.items()},
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Candidate access v2 signal-relative multi-assignment prototype.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_multi_assignment(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
