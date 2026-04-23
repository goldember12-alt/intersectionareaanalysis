from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .config import load_runtime_config


OUTPUT_FOLDER_NAME = "upstream_downstream_prototype"
ANALYSIS_FOLDER_NAME = "high_confidence_descriptive_analysis"
TABLES_CURRENT_SUBDIR = ("tables", "current")
TABLES_HISTORY_SUBDIR = ("tables", "history")
REVIEW_CURRENT_SUBDIR = ("review", "current")
REVIEW_HISTORY_SUBDIR = ("review", "history")
REVIEW_GEOJSON_CURRENT_SUBDIR = ("review", "geojson", "current")
REVIEW_GEOJSON_HISTORY_SUBDIR = ("review", "geojson", "history")
RUNS_CURRENT_SUBDIR = ("runs", "current")
RUNS_HISTORY_SUBDIR = ("runs", "history")
SELECTED_CASE_STUDY_SIGNAL_IDS = [454, 894, 1876]
CASE_STUDY_SPECS = {
    454: {
        "role": "Balanced two-sided example",
        "why_selected": "User-selected signal with an even upstream/downstream split in the strongest-confidence subset.",
        "method_note": "Shows a compact case where the same high-confidence method retains both approaching-side and leaving-side crashes around one directed row.",
    },
    894: {
        "role": "Higher-volume upstream-leaning example",
        "why_selected": "User-selected signal with a larger high-confidence crash count and a clear upstream majority.",
        "method_note": "Useful for showing that the first descriptive slice can reveal a directional skew without widening beyond strict empirical flow support.",
    },
    1876: {
        "role": "Downstream-leaning example",
        "why_selected": "User-selected signal with a downstream majority and a smaller, readable crash set.",
        "method_note": "Useful for map communication because the selected crashes remain bounded and directional even where the signal label itself is sparse.",
    },
}
SPEED_LOOKUP_ROWS = [
    (25, 155, 355),
    (30, 200, 450),
    (35, 250, 550),
    (40, 305, 680),
    (45, 360, 810),
    (50, 425, 950),
    (55, 495, 1100),
]


def _round_share(series: pd.Series) -> pd.Series:
    return series.round(4)


def _round_pct(series: pd.Series) -> pd.Series:
    return (series * 100.0).round(1)


def _output_subdir(output_dir: Path, *parts: str) -> Path:
    path = output_dir.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _prepare_output_path(path: Path, history_dir: Path | None = None) -> Path:
    if not path.exists():
        return path
    try:
        path.unlink()
        return path
    except PermissionError:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if history_dir is not None:
            history_dir.mkdir(parents=True, exist_ok=True)
            return history_dir / f"{path.stem}_{stamp}{path.suffix}"
        return path.with_name(f"{path.stem}_{stamp}{path.suffix}")


def _write_csv_frame(frame: pd.DataFrame, path: Path, history_dir: Path | None = None) -> Path:
    resolved = _prepare_output_path(path, history_dir=history_dir)
    frame.to_csv(resolved, index=False)
    return resolved


def _write_json_object(payload: dict[str, object], path: Path, history_dir: Path | None = None) -> Path:
    resolved = _prepare_output_path(path, history_dir=history_dir)
    resolved.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return resolved


def _write_text_file(content: str, path: Path, history_dir: Path | None = None) -> Path:
    resolved = _prepare_output_path(path, history_dir=history_dir)
    resolved.write_text(content, encoding="utf-8")
    return resolved


def _read_geojson(path: Path) -> gpd.GeoDataFrame:
    frame = gpd.read_file(path)
    return gpd.GeoDataFrame(frame, geometry="geometry", crs=frame.crs)


def _load_sources(output_dir: Path) -> dict[str, Path]:
    return {
        "classified_all": output_dir / "review" / "geojson" / "current" / "classified_all.geojson",
        "classified_high_confidence": output_dir / "review" / "geojson" / "current" / "classified_high_confidence.geojson",
        "study_areas_approach_shaped": output_dir / "review" / "geojson" / "current" / "study_areas__approach_shaped.geojson",
        "signals": output_dir / "review" / "geojson" / "current" / "signals.geojson",
        "approach_rows": output_dir / "review" / "geojson" / "current" / "approach_rows.geojson",
        "strongest_classified_summary": output_dir / "tables" / "current" / "strongest_classified_summary.csv",
        "strongest_classified_by_signal": output_dir / "tables" / "current" / "strongest_classified_by_signal.csv",
        "review_summary": output_dir / "review" / "current" / "review_summary.md",
        "run_summary": output_dir / "runs" / "current" / "run_summary.json",
    }


def _build_active_subset(classified_all: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    mask = (
        classified_all["ClassificationStatus"].eq("classified")
        & classified_all["AttachmentConfidence"].eq("high")
        & classified_all["FlowProvenance"].eq("strict_empirical")
    )
    subset = classified_all.loc[mask].copy()
    return gpd.GeoDataFrame(subset, geometry="geometry", crs=classified_all.crs)


def _build_overall_summary(active_subset: gpd.GeoDataFrame) -> pd.DataFrame:
    crash_count = int(len(active_subset))
    upstream_count = int(active_subset["SignalRelativeClass"].eq("upstream").sum())
    downstream_count = int(active_subset["SignalRelativeClass"].eq("downstream").sum())
    overall = pd.DataFrame(
        [
            {
                "AnalysisSubsetName": "high_confidence_classified",
                "StudyAreaType": active_subset["StudyAreaType"].mode().iat[0],
                "FlowProvenance": active_subset["FlowProvenance"].mode().iat[0],
                "FlowProvenanceUsed": active_subset["FlowProvenanceUsed"].mode().iat[0],
                "TotalHighConfidenceCrashes": crash_count,
                "UpstreamCount": upstream_count,
                "DownstreamCount": downstream_count,
                "UpstreamShare": upstream_count / crash_count if crash_count else 0.0,
                "DownstreamShare": downstream_count / crash_count if crash_count else 0.0,
                "UpstreamPct": (upstream_count / crash_count * 100.0) if crash_count else 0.0,
                "DownstreamPct": (downstream_count / crash_count * 100.0) if crash_count else 0.0,
                "SignalsRepresented": int(active_subset["Signal_RowID"].nunique()),
                "StudyAreasRepresented": int(active_subset["StudyAreaID"].nunique()),
            }
        ]
    )
    overall["UpstreamShare"] = _round_share(overall["UpstreamShare"])
    overall["DownstreamShare"] = _round_share(overall["DownstreamShare"])
    overall["UpstreamPct"] = overall["UpstreamPct"].round(1)
    overall["DownstreamPct"] = overall["DownstreamPct"].round(1)
    return overall


def _build_signal_summary(active_subset: gpd.GeoDataFrame) -> pd.DataFrame:
    summary = (
        active_subset.groupby(
            [
                "StudyAreaID",
                "Signal_RowID",
                "REG_SIGNAL_ID",
                "SIGNAL_NO",
                "SignalLabel",
                "SignalRouteName",
                "AssignedSpeedMph",
                "StudyAreaType",
                "FlowProvenance",
                "FlowProvenanceUsed",
            ],
            dropna=False,
        )
        .agg(
            TotalHighConfidenceCrashes=("Crash_RowID", "size"),
            UpstreamCount=("SignalRelativeClass", lambda values: int(pd.Series(values).eq("upstream").sum())),
            DownstreamCount=("SignalRelativeClass", lambda values: int(pd.Series(values).eq("downstream").sum())),
        )
        .reset_index()
    )
    summary["UpstreamShare"] = _round_share(summary["UpstreamCount"] / summary["TotalHighConfidenceCrashes"])
    summary["DownstreamShare"] = _round_share(summary["DownstreamCount"] / summary["TotalHighConfidenceCrashes"])
    summary["UpstreamPct"] = _round_pct(summary["UpstreamCount"] / summary["TotalHighConfidenceCrashes"])
    summary["DownstreamPct"] = _round_pct(summary["DownstreamCount"] / summary["TotalHighConfidenceCrashes"])
    return summary.sort_values(
        ["TotalHighConfidenceCrashes", "Signal_RowID"],
        ascending=[False, True],
    ).reset_index(drop=True)


def _build_speed_summary(active_subset: gpd.GeoDataFrame) -> pd.DataFrame:
    summary = (
        active_subset.groupby(["AssignedSpeedMph"], dropna=False)
        .agg(
            TotalHighConfidenceCrashes=("Crash_RowID", "size"),
            SignalsRepresented=("Signal_RowID", "nunique"),
            UpstreamCount=("SignalRelativeClass", lambda values: int(pd.Series(values).eq("upstream").sum())),
            DownstreamCount=("SignalRelativeClass", lambda values: int(pd.Series(values).eq("downstream").sum())),
        )
        .reset_index()
        .sort_values(["AssignedSpeedMph"], ascending=[True])
    )
    summary["UpstreamShare"] = _round_share(summary["UpstreamCount"] / summary["TotalHighConfidenceCrashes"])
    summary["DownstreamShare"] = _round_share(summary["DownstreamCount"] / summary["TotalHighConfidenceCrashes"])
    summary["UpstreamPct"] = _round_pct(summary["UpstreamCount"] / summary["TotalHighConfidenceCrashes"])
    summary["DownstreamPct"] = _round_pct(summary["DownstreamCount"] / summary["TotalHighConfidenceCrashes"])
    return summary


def _build_route_summary(active_subset: gpd.GeoDataFrame) -> pd.DataFrame:
    summary = (
        active_subset.groupby(["SignalRouteName"], dropna=False)
        .agg(
            TotalHighConfidenceCrashes=("Crash_RowID", "size"),
            SignalsRepresented=("Signal_RowID", "nunique"),
            UpstreamCount=("SignalRelativeClass", lambda values: int(pd.Series(values).eq("upstream").sum())),
            DownstreamCount=("SignalRelativeClass", lambda values: int(pd.Series(values).eq("downstream").sum())),
        )
        .reset_index()
        .sort_values(["TotalHighConfidenceCrashes", "SignalRouteName"], ascending=[False, True])
    )
    summary["UpstreamShare"] = _round_share(summary["UpstreamCount"] / summary["TotalHighConfidenceCrashes"])
    summary["DownstreamShare"] = _round_share(summary["DownstreamCount"] / summary["TotalHighConfidenceCrashes"])
    summary["UpstreamPct"] = _round_pct(summary["UpstreamCount"] / summary["TotalHighConfidenceCrashes"])
    summary["DownstreamPct"] = _round_pct(summary["DownstreamCount"] / summary["TotalHighConfidenceCrashes"])
    return summary


def _build_case_studies(signal_summary: pd.DataFrame) -> pd.DataFrame:
    case_rows: list[dict[str, object]] = []
    signal_lookup = signal_summary.set_index("Signal_RowID", drop=False)
    missing_ids = [signal_id for signal_id in SELECTED_CASE_STUDY_SIGNAL_IDS if signal_id not in signal_lookup.index]
    if missing_ids:
        raise ValueError(f"Selected case-study signals are missing from the high-confidence subset: {missing_ids}")

    for rank, signal_id in enumerate(SELECTED_CASE_STUDY_SIGNAL_IDS, start=1):
        row = signal_lookup.loc[signal_id]
        spec = CASE_STUDY_SPECS[int(signal_id)]
        case_rows.append(
            {
                "CaseStudyRank": rank,
                "CaseStudyRole": spec["role"],
                "StudyAreaID": row["StudyAreaID"],
                "Signal_RowID": int(row["Signal_RowID"]),
                "REG_SIGNAL_ID": row["REG_SIGNAL_ID"],
                "SIGNAL_NO": row["SIGNAL_NO"],
                "SignalLabel": row["SignalLabel"],
                "SignalRouteName": row["SignalRouteName"],
                "AssignedSpeedMph": row["AssignedSpeedMph"],
                "TotalHighConfidenceCrashes": int(row["TotalHighConfidenceCrashes"]),
                "UpstreamCount": int(row["UpstreamCount"]),
                "DownstreamCount": int(row["DownstreamCount"]),
                "UpstreamShare": float(row["UpstreamShare"]),
                "DownstreamShare": float(row["DownstreamShare"]),
                "UpstreamPct": float(row["UpstreamPct"]),
                "DownstreamPct": float(row["DownstreamPct"]),
                "WhySelected": spec["why_selected"],
                "MethodologicalNote": spec["method_note"],
            }
        )
    return pd.DataFrame(case_rows)


def _write_case_study_layers(
    output_dir: Path,
    case_studies: pd.DataFrame,
    active_subset: gpd.GeoDataFrame,
    study_areas: gpd.GeoDataFrame,
    signals: gpd.GeoDataFrame,
    approach_rows: gpd.GeoDataFrame,
) -> dict[str, str]:
    review_geojson_dir = _output_subdir(output_dir, *REVIEW_GEOJSON_CURRENT_SUBDIR)
    review_geojson_history_dir = _output_subdir(output_dir, *REVIEW_GEOJSON_HISTORY_SUBDIR)

    selected_signal_ids = set(case_studies["Signal_RowID"].astype(int))
    selected_study_area_ids = set(case_studies["StudyAreaID"].astype(str))

    case_signal_layer = signals.loc[signals["Signal_RowID"].isin(selected_signal_ids)].copy()
    case_signal_layer = case_signal_layer.sort_values(["Signal_RowID"]).drop_duplicates(subset=["Signal_RowID"], keep="first")
    case_crash_layer = active_subset.loc[active_subset["Signal_RowID"].isin(selected_signal_ids)].copy()
    case_study_area_layer = study_areas.loc[study_areas["StudyAreaID"].isin(selected_study_area_ids)].copy()
    case_study_area_layer = case_study_area_layer.sort_values(["StudyAreaID"]).drop_duplicates(subset=["StudyAreaID"], keep="first")
    case_approach_row_layer = approach_rows.loc[approach_rows["StudyAreaID"].isin(selected_study_area_ids)].copy()

    outputs = {
        "selected_signal_case_study_signals": _prepare_output_path(
            review_geojson_dir / "selected_signal_case_study_signals.geojson",
            history_dir=review_geojson_history_dir,
        ),
        "selected_signal_case_study_high_confidence_crashes": _prepare_output_path(
            review_geojson_dir / "selected_signal_case_study_high_confidence_crashes.geojson",
            history_dir=review_geojson_history_dir,
        ),
        "selected_signal_case_study_study_areas": _prepare_output_path(
            review_geojson_dir / "selected_signal_case_study_study_areas.geojson",
            history_dir=review_geojson_history_dir,
        ),
        "selected_signal_case_study_approach_rows": _prepare_output_path(
            review_geojson_dir / "selected_signal_case_study_approach_rows.geojson",
            history_dir=review_geojson_history_dir,
        ),
    }

    case_signal_layer.to_file(outputs["selected_signal_case_study_signals"], driver="GeoJSON")
    case_crash_layer.to_file(outputs["selected_signal_case_study_high_confidence_crashes"], driver="GeoJSON")
    case_study_area_layer.to_file(outputs["selected_signal_case_study_study_areas"], driver="GeoJSON")
    case_approach_row_layer.to_file(outputs["selected_signal_case_study_approach_rows"], driver="GeoJSON")

    return {name: str(path) for name, path in outputs.items()}


def _json_ready_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    clean = frame.astype(object).where(pd.notna(frame), None)
    return clean.to_dict(orient="records")


def _build_output_layout_readme(output_files: dict[str, str], output_dir: Path) -> str:
    current_sections = [
        ("tables/current", TABLES_CURRENT_SUBDIR),
        ("review/current", REVIEW_CURRENT_SUBDIR),
        ("review/geojson/current", REVIEW_GEOJSON_CURRENT_SUBDIR),
        ("runs/current", RUNS_CURRENT_SUBDIR),
    ]
    lines = [
        "# High-Confidence Upstream/Downstream Analysis Outputs",
        "",
        "This folder contains the downstream descriptive-analysis step built from the grouped current outputs of `work/output/upstream_downstream_prototype/`.",
        "",
        "## Current outputs",
    ]
    for label, parts in current_sections:
        section_path = output_dir.joinpath(*parts)
        matching = sorted(
            str(Path(path).relative_to(output_dir))
            for path in output_files.values()
            if Path(path).exists() and section_path in Path(path).parents
        )
        lines.append(f"- `{label}`")
        if not matching:
            lines.append("  - none written in this run")
            continue
        for relative_path in matching:
            lines.append(f"  - `{relative_path}`")
    lines.extend(
        [
            "",
            "## History folders",
            "- `tables/history/`, `review/history/`, `review/geojson/history/`, and `runs/history/` are fallback/collision locations used only when a stable current target cannot be replaced safely.",
            "- `history/` is not the main active archive lane; active outputs belong in `current/`.",
            "",
            "## QGIS note",
            "- The GeoJSON files under `review/geojson/current/` are QGIS-support layers written by Python.",
            "- Any case-study PNG map exports are still expected to be manual QGIS products rather than Python outputs.",
        ]
    )
    return "\n".join(lines) + "\n"


def _build_methodology_memo(overall_summary: pd.DataFrame, case_studies: pd.DataFrame) -> str:
    overall = overall_summary.iloc[0]
    selected_signal_text = ", ".join(
        f"{row.SignalLabel} ({row.StudyAreaID})" for row in case_studies.itertuples(index=False)
    )

    lines = [
        "# High-Confidence Upstream/Downstream Methodology Memo",
        "",
        "## Purpose",
        "This memo describes the first forward-facing descriptive analysis from the refined upstream/downstream prototype.",
        "The goal of this first slice is not to cover every crash near every signal. It is to show what the method produces when it is limited to the most credible signal-relative classifications.",
        "",
        "## 1. Signal-centered anchor and eligible signals",
        "The workflow starts from signals, not from crashes and not from roadway rows alone.",
        "It does not keep every signal in the source inventory. A signal only enters this prototype if its nearest study-road row already has a trusted local direction of travel from the empirical directionality experiment.",
        "Operationally, the nearest study-road row is the row chosen by a nearest-row search against the study-road network. If more than one row ties at the minimum distance, the prototype breaks the tie in a stable way using distance, route identifiers, measure fields, source field, and row ID.",
        "At the signal-screening stage, trusted local flow currently means that the nearest row received either a `StrictUnanimous` direction assignment or an `Empirical90Pct` direction assignment. The strongest-confidence descriptive slice later narrows this further to the strict rule only.",
        "",
        "## 2. Empirical flow-orientation rules",
        "The empirical directionality step uses a deliberately narrow crash subset. A crash contributes to local flow evidence only if its direction-of-travel field can be parsed to one clear cardinal direction, the crash is single-vehicle (`VEH_COUNT = 1`), and the coded vehicle maneuver is `1. Going Straight Ahead`.",
        "### `StrictUnanimous`",
        "This is the strictest empirical rule. The row must have at least 2 qualifying crashes, and all qualifying crashes must point in the same parsed cardinal direction. If the qualifying crashes disagree, or if fewer than 2 qualify, the row is left unresolved under this rule.",
        "### `Empirical90Pct`",
        "This rule uses the same qualifying crash subset and still requires at least 2 qualifying crashes. It assigns a direction when one direction accounts for at least 90% of those qualifying crashes. It is a bounded relaxation of the strict rule, not a general catch-all fallback.",
        "",
        "## 3. Approach-shaped study areas",
        "The active study area is not a simple circle around the signal. It is a roadway-constrained polygon built from same-route study-road rows near the signal.",
        "For each eligible signal, the prototype collects same-route study-road rows within 75 meters of the signal and ensures that the signal's own attached row is included if needed. Each included row is clipped to the signal's speed-informed approach length around the signal, buffered laterally by 18 meters, and unioned with a 20 meter hub buffer around the signal itself.",
        "The result is a roadway-shaped petal or cross-like polygon that follows the local corridor rather than a generic radius.",
        "",
        "## 4. Speed-informed approach length",
        "The approach length comes from nearby posted-speed data when it is available. The prototype joins each signal to the nearest speed segment within 50 meters and reads the posted speed from that segment.",
        "If no usable posted speed is found, or if the joined value is below 15 mph, the prototype falls back to 35 mph.",
        "That assigned speed is then rounded to the nearest value in a bounded lookup table covering 25, 30, 35, 40, 45, 50, and 55 mph. The prototype uses the table's desired functional distance as the per-signal approach length. This is a bounded stopping-distance-style rule, not an arbitrary fixed-radius rule.",
        "",
        "## 5. Crash admission into the study area",
        "A crash enters this slice only if its crash point falls inside one of the approach-shaped study-area polygons.",
        "Admission alone does not guarantee a usable classification. The crash still has to be associated to a signal, attached to a row credibly, and compared to that signal along a row with usable flow support.",
        "",
        "## 6. Signal association",
        "When a crash falls inside a study area, the prototype does not simply attach it to the polygon it touched first. It compares the crash to the eligible signals represented inside that study-area window and chooses the nearest same-route eligible signal.",
        "Here, same-route means that the crash route name matches the candidate signal's study-road route name.",
        "If there is no same-route eligible candidate, the crash remains unresolved. If the two nearest same-route candidates are too close to call, the crash also remains unresolved. The current ambiguity threshold is 15 meters.",
        "",
        "## 7. Row attachment and attachment confidence",
        "After a signal is chosen, the crash is evaluated against that signal's attached study-road row, which is the nearest study-road row previously assigned to the signal.",
        "Attachment confidence is based on crash-to-row distance. `high` means the crash is within 25 meters of the selected row. `medium` means more than 25 meters but no more than 50 meters. Beyond 50 meters, the crash is left unresolved for row attachment.",
        "",
        "## 8. Flow provenance",
        "The local direction of travel used for classification comes from the separate empirical directionality work, not from geometry alone.",
        "For the first descriptive analysis, the active subset keeps only `strict_empirical` flow provenance. In practice, that means the attached row's usable direction came from the `StrictUnanimous` rule. Rows supported only by the weaker `Empirical90Pct` variant, or left unresolved, are intentionally excluded from this strongest-confidence slice.",
        "",
        "## 9. Upstream/downstream classification",
        "The crash and the selected signal are projected onto the same attached row geometry. That row already has an empirically assigned direction of travel.",
        "If the crash lies before the signal along that directed row, the crash is classified as `upstream`. If it lies after the signal, it is classified as `downstream`.",
        "If the row geometry is not usable as a single ordered line, if the crash is too far from the row, if local flow support is unavailable, or if the projected crash and signal positions fall within 5 meters of one another on the row, the crash remains unresolved instead of being forced into a label.",
        "",
        "## 10. Exact strongest-confidence subset used here",
        "The first descriptive analysis is intentionally limited to crashes that:",
        "- were admitted by the roadway-constrained approach-shaped study area",
        "- received an `upstream` or `downstream` classification",
        "- were attached to the selected signal's row with `high` attachment confidence",
        "- relied on strict empirical flow provenance rather than weaker support logic",
        "",
        "The exact active filter is:",
        "- `StudyAreaType = approach_shaped`",
        "- `ClassificationStatus = classified`",
        "- `AttachmentConfidence = high`",
        "- `FlowProvenance = strict_empirical`",
        "",
        "## 11. Top-line findings from the strongest-confidence subset",
        f"- High-confidence classified crashes: {int(overall['TotalHighConfidenceCrashes'])}",
        f"- Upstream crashes: {int(overall['UpstreamCount'])} ({float(overall['UpstreamPct']):.1f}%)",
        f"- Downstream crashes: {int(overall['DownstreamCount'])} ({float(overall['DownstreamPct']):.1f}%)",
        f"- Signals represented: {int(overall['SignalsRepresented'])}",
        "",
        "These counts describe the strongest-confidence subset only. Broader prototype outputs still contain lower-confidence and unresolved cases for review, but those cases are intentionally outside this first descriptive slice.",
        "",
        "## 12. Selected case-study support",
        "Three user-selected case-study signals were prepared to support manual QGIS maps from the same strongest-confidence subset.",
        f"Selected signals: {selected_signal_text}.",
        "",
        "## 13. Interpretation posture",
        "This is a bounded first descriptive slice, not the final full crash universe near signals.",
        "Unresolved cases and lower-confidence support paths are intentionally excluded so the first outward-facing tables and maps stay conservative, explainable, and trustworthy.",
        "",
    ]
    return "\n".join(lines)


def _build_method_details() -> str:
    lookup_lines = [
        "| Assigned speed (mph) | Functional distance limit (ft) | Functional distance used for approach length (ft) |",
        "| --- | ---: | ---: |",
    ]
    for speed_mph, dist_lim_ft, dist_des_ft in SPEED_LOOKUP_ROWS:
        lookup_lines.append(f"| {speed_mph} | {dist_lim_ft} | {dist_des_ft} |")

    lines = [
        "# High-Confidence Method Details",
        "",
        "This companion note records the operational definitions used by the high-confidence upstream/downstream outputs.",
        "",
        "## Directionality evidence subset",
        "- Direction-of-travel must parse to one clear cardinal direction from `DIRECTION_OF_TRAVEL_CD`.",
        "- The crash must be single-vehicle (`VEH_COUNT = 1`).",
        "- The coded maneuver must be `1. Going Straight Ahead`.",
        "- At least 2 qualifying crashes are required before either empirical direction rule can assign a row direction.",
        "",
        "## Empirical direction rules",
        "- `StrictUnanimous`: assign only when all qualifying crashes on the row agree on one direction.",
        "- `Empirical90Pct`: assign only when one direction accounts for at least 90% of the same qualifying crashes.",
        "- If the qualifying crashes disagree and do not meet the 90% threshold, the row remains unresolved under these empirical rules.",
        "",
        "## Signal eligibility and study-area geometry",
        "- Signals are eligible only when their nearest study-road row already has an empirical direction assignment.",
        "- The nearest study-road row comes from a nearest-row search against the study-road network, with a stable tie-break if multiple rows share the minimum distance.",
        "- Same-route study-road rows within 75 meters of the signal are gathered for the approach-shaped geometry.",
        "- Each included row is clipped to the per-signal approach length around the signal, buffered by 18 meters, and unioned with a 20 meter hub buffer around the signal.",
        "",
        "## Speed assignment and approach length",
        "- Speed is taken from the nearest posted-speed segment within 50 meters of the signal when available.",
        "- If no usable value is found, or the joined value is below 15 mph, the prototype falls back to 35 mph.",
        "- The assigned speed is rounded to the nearest value in the bounded lookup below, and the desired functional distance becomes the approach length.",
        "",
        *lookup_lines,
        "",
        "## Crash admission and signal association",
        "- A crash is admitted only when its point geometry falls within an approach-shaped study-area polygon.",
        "- The crash is then matched to the nearest same-route eligible signal inside that study-area window.",
        "- If there is no same-route eligible signal, the crash remains unresolved.",
        "- If the two nearest same-route signals are within 15 meters of each other relative to the crash, the crash remains unresolved for signal association.",
        "",
        "## Row attachment and classification thresholds",
        "- Attachment is evaluated against the selected signal's attached study-road row.",
        "- `high` attachment confidence: crash-to-row distance <= 25 meters.",
        "- `medium` attachment confidence: crash-to-row distance > 25 meters and <= 50 meters.",
        "- `unresolved` attachment: crash-to-row distance > 50 meters, unusable row geometry, or missing credible flow support.",
        "- If the projected crash and projected signal positions are within 5 meters of one another on the row, the crash remains unresolved rather than being forced to upstream or downstream.",
        "",
        "## Strongest-confidence descriptive filter",
        "- `StudyAreaType = approach_shaped`",
        "- `ClassificationStatus = classified`",
        "- `AttachmentConfidence = high`",
        "- `FlowProvenance = strict_empirical`",
        "",
    ]
    return "\n".join(lines)


def _build_case_study_notes(case_studies: pd.DataFrame) -> str:
    lines = [
        "# Selected Signal Case-Study Notes",
        "",
        "These short notes are intended as a writing scaffold for screenshots or QGIS map exports.",
        "",
    ]
    for row in case_studies.itertuples(index=False):
        lines.extend(
            [
                f"## {row.StudyAreaID} - {row.SignalLabel}",
                f"- Assigned speed: {int(row.AssignedSpeedMph)} mph",
                f"- High-confidence crashes: {int(row.TotalHighConfidenceCrashes)}",
                f"- Upstream: {int(row.UpstreamCount)}",
                f"- Downstream: {int(row.DownstreamCount)}",
                f"- Why this is useful: {row.MethodologicalNote}",
                "",
            ]
        )
    return "\n".join(lines)


def _validate_against_existing_outputs(
    active_subset: gpd.GeoDataFrame,
    classified_high_confidence: gpd.GeoDataFrame,
    overall_summary: pd.DataFrame,
    signal_summary: pd.DataFrame,
    strongest_summary_path: Path,
    strongest_by_signal_path: Path,
) -> None:
    if len(active_subset) != len(classified_high_confidence):
        raise ValueError(
            f"Derived strongest subset row count {len(active_subset)} does not match classified_high_confidence rows {len(classified_high_confidence)}."
        )

    strongest_summary = pd.read_csv(strongest_summary_path)
    expected_overall = strongest_summary.iloc[0]
    actual_overall = overall_summary.iloc[0]
    if int(actual_overall["TotalHighConfidenceCrashes"]) != int(expected_overall["CrashCount"]):
        raise ValueError("Derived overall crash count does not match strongest_classified_summary.csv.")
    if int(actual_overall["UpstreamCount"]) != int(expected_overall["UpstreamCount"]):
        raise ValueError("Derived upstream count does not match strongest_classified_summary.csv.")
    if int(actual_overall["DownstreamCount"]) != int(expected_overall["DownstreamCount"]):
        raise ValueError("Derived downstream count does not match strongest_classified_summary.csv.")
    if int(actual_overall["SignalsRepresented"]) != int(expected_overall["SignalCount"]):
        raise ValueError("Derived signal count does not match strongest_classified_summary.csv.")

    strongest_by_signal = pd.read_csv(strongest_by_signal_path).sort_values(
        ["StudyAreaID", "Signal_RowID"],
        ascending=[True, True],
    ).reset_index(drop=True)
    comparable = signal_summary[
        ["StudyAreaID", "Signal_RowID", "SignalLabel", "TotalHighConfidenceCrashes", "UpstreamCount", "DownstreamCount"]
    ].rename(columns={"TotalHighConfidenceCrashes": "CrashCount"}).sort_values(
        ["StudyAreaID", "Signal_RowID"],
        ascending=[True, True],
    ).reset_index(drop=True)
    merged = strongest_by_signal.merge(
        comparable,
        on=["StudyAreaID", "Signal_RowID", "SignalLabel"],
        how="outer",
        suffixes=("_expected", "_actual"),
        indicator=True,
    )
    mismatch = merged.loc[
        (merged["_merge"] != "both")
        | (merged["CrashCount_expected"] != merged["CrashCount_actual"])
        | (merged["UpstreamCount_expected"] != merged["UpstreamCount_actual"])
        | (merged["DownstreamCount_expected"] != merged["DownstreamCount_actual"])
    ]
    if not mismatch.empty:
        raise ValueError("Derived signal summary does not match strongest_classified_by_signal.csv.")


def run_high_confidence_upstream_downstream_analysis() -> int:
    config = load_runtime_config()
    prototype_output_dir = config.output_dir / OUTPUT_FOLDER_NAME
    analysis_output_dir = prototype_output_dir / ANALYSIS_FOLDER_NAME
    analysis_output_dir.mkdir(parents=True, exist_ok=True)
    tables_current_dir = _output_subdir(analysis_output_dir, *TABLES_CURRENT_SUBDIR)
    tables_history_dir = _output_subdir(analysis_output_dir, *TABLES_HISTORY_SUBDIR)
    review_current_dir = _output_subdir(analysis_output_dir, *REVIEW_CURRENT_SUBDIR)
    review_history_dir = _output_subdir(analysis_output_dir, *REVIEW_HISTORY_SUBDIR)
    _output_subdir(analysis_output_dir, *REVIEW_GEOJSON_CURRENT_SUBDIR)
    _output_subdir(analysis_output_dir, *REVIEW_GEOJSON_HISTORY_SUBDIR)
    runs_current_dir = _output_subdir(analysis_output_dir, *RUNS_CURRENT_SUBDIR)
    runs_history_dir = _output_subdir(analysis_output_dir, *RUNS_HISTORY_SUBDIR)

    source_paths = _load_sources(prototype_output_dir)
    classified_all = _read_geojson(source_paths["classified_all"])
    classified_high_confidence = _read_geojson(source_paths["classified_high_confidence"])
    study_areas = _read_geojson(source_paths["study_areas_approach_shaped"])
    signals = _read_geojson(source_paths["signals"])
    approach_rows = _read_geojson(source_paths["approach_rows"])

    active_subset = _build_active_subset(classified_all)
    overall_summary = _build_overall_summary(active_subset)
    signal_summary = _build_signal_summary(active_subset)
    speed_summary = _build_speed_summary(active_subset)
    route_summary = _build_route_summary(active_subset)
    case_studies = _build_case_studies(signal_summary)

    _validate_against_existing_outputs(
        active_subset,
        classified_high_confidence,
        overall_summary,
        signal_summary,
        source_paths["strongest_classified_summary"],
        source_paths["strongest_classified_by_signal"],
    )

    qgis_outputs = _write_case_study_layers(
        analysis_output_dir,
        case_studies,
        active_subset,
        study_areas,
        signals,
        approach_rows,
    )

    memo_text = _build_methodology_memo(overall_summary, case_studies)
    method_details_text = _build_method_details()
    case_study_notes_text = _build_case_study_notes(case_studies)

    output_files = {
        "overall_summary": str(
            _write_csv_frame(
                overall_summary,
                tables_current_dir / "high_confidence_overall_summary.csv",
                history_dir=tables_history_dir,
            )
        ),
        "by_signal": str(
            _write_csv_frame(
                signal_summary,
                tables_current_dir / "high_confidence_by_signal.csv",
                history_dir=tables_history_dir,
            )
        ),
        "by_assigned_speed": str(
            _write_csv_frame(
                speed_summary,
                tables_current_dir / "high_confidence_by_assigned_speed.csv",
                history_dir=tables_history_dir,
            )
        ),
        "by_route": str(
            _write_csv_frame(
                route_summary,
                tables_current_dir / "high_confidence_by_route.csv",
                history_dir=tables_history_dir,
            )
        ),
        "case_studies": str(
            _write_csv_frame(
                case_studies,
                tables_current_dir / "high_confidence_case_studies.csv",
                history_dir=tables_history_dir,
            )
        ),
        "methodology_memo": str(
            _write_text_file(
                memo_text,
                review_current_dir / "high_confidence_methodology_memo.md",
                history_dir=review_history_dir,
            )
        ),
        "method_details": str(
            _write_text_file(
                method_details_text,
                review_current_dir / "high_confidence_method_details.md",
                history_dir=review_history_dir,
            )
        ),
        "case_study_notes": str(
            _write_text_file(
                case_study_notes_text,
                review_current_dir / "selected_signal_case_study_notes.md",
                history_dir=review_history_dir,
            )
        ),
    }
    output_files.update(qgis_outputs)

    metadata = {
        "analysis_subset_name": "high_confidence_classified",
        "subset_definition": {
            "study_area_type": "approach_shaped",
            "classification_status": "classified",
            "attachment_confidence": "high",
            "flow_provenance": "strict_empirical",
            "flow_provenance_used": "StrictUnanimous",
            "signal_relative_classes": ["upstream", "downstream"],
        },
        "source_files": {name: str(path) for name, path in source_paths.items()},
        "output_files": output_files.copy(),
        "topline_counts": _json_ready_records(overall_summary)[0],
        "case_studies": _json_ready_records(case_studies),
    }
    metadata_path = _write_json_object(
        metadata,
        runs_current_dir / "high_confidence_analysis_metadata.json",
        history_dir=runs_history_dir,
    )
    output_files["analysis_metadata"] = str(metadata_path)
    readme_path = _write_text_file(
        _build_output_layout_readme(output_files, analysis_output_dir),
        analysis_output_dir / "README.md",
    )
    output_files["readme"] = str(readme_path)
    metadata["output_files"] = output_files
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    return 0


def main() -> int:
    return run_high_confidence_upstream_downstream_analysis()


if __name__ == "__main__":
    raise SystemExit(main())
