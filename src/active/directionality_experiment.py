from __future__ import annotations

import importlib.util
import json
import numbers
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

from .config import load_runtime_config


OUTPUT_FOLDER_NAME = "directionality_experiment"
TABLES_CURRENT_SUBDIR = ("tables", "current")
TABLES_HISTORY_SUBDIR = ("tables", "history")
REVIEW_CURRENT_SUBDIR = ("review", "current")
REVIEW_HISTORY_SUBDIR = ("review", "history")
REVIEW_GEOJSON_CURRENT_SUBDIR = ("review", "geojson", "current")
REVIEW_GEOJSON_HISTORY_SUBDIR = ("review", "geojson", "history")
REVIEW_GEOPACKAGE_CURRENT_SUBDIR = ("review", "geopackage", "current")
REVIEW_GEOPACKAGE_HISTORY_SUBDIR = ("review", "geopackage", "history")
RUNS_CURRENT_SUBDIR = ("runs", "current")
RUNS_HISTORY_SUBDIR = ("runs", "history")
PRIMARY_MIN_QUALIFYING_CRASHES = 2
PRIMARY_MANEUVER = "1. Going Straight Ahead"
EMPIRICAL_DOMINANT_SHARE_THRESHOLD = 0.90
SINGLE_VEHICLE_SUPPORT_DOMINANT_SHARE_THRESHOLD = 0.90
EXPANDED_MIN_SIGNALS_PER_CORRIDOR = 3
CONTIGUITY_GAP_TOLERANCE = 0.01

CARDINAL_LABELS = ("North", "South", "East", "West")
CARDINAL_WORD_PATTERN = re.compile(r"\b(NORTH|SOUTH|EAST|WEST)(?:BOUND)?\b", re.IGNORECASE)
ROUTE_SUFFIX_PATTERN = re.compile(r"(NB|SB|EB|WB)\s*$", re.IGNORECASE)
ROUTE_COMMON_TOKEN_PATTERN = re.compile(r"\b(?:BUS\s+VA|US|VA|SC)-?\d+[A-Z0-9-]*([NSEW])\b", re.IGNORECASE)
CARDINAL_WORD_TO_LABEL = {
    "NORTH": "North",
    "SOUTH": "South",
    "EAST": "East",
    "WEST": "West",
}
CARDINAL_TOKEN_TO_LABEL = {
    "N": "North",
    "S": "South",
    "E": "East",
    "W": "West",
}
ROUTE_SUFFIX_TO_LABEL = {
    "NB": "North",
    "SB": "South",
    "EB": "East",
    "WB": "West",
}
STRICT_RULE_NAME = "StrictUnanimous"
EMPIRICAL_90_RULE_NAME = "Empirical90Pct"
SINGLE_VEHICLE_SUPPORT_RULE_NAME = "SingleVehicleSupport"
ROUTE_NAME_FALLBACK_RULE_NAME = "RouteNameFallback"


@dataclass(frozen=True)
class CorridorWindow:
    scope_name: str
    corridor_source: str
    corridor_key: str
    corridor_name: str
    route_name: str
    window_from_measure: float
    window_to_measure: float
    selected_signals: tuple[str, ...] = ()


INITIAL_CORRIDORS: tuple[CorridorWindow, ...] = (
    CorridorWindow(
        scope_name="initial_seed",
        corridor_source="manual_seed_bucket",
        corridor_key="norfolk_sr00337wb",
        corridor_name="Norfolk",
        route_name="R-VA   SR00337WB",
        window_from_measure=29.99,
        window_to_measure=31.72,
        selected_signals=(
            "HAMPTON & MAGNOLIA",
            "BOLLING & HAMPTON",
            "LARCHMONT ELEM (SB HAMPTON)",
            "CAMERA-47TH & HAMPTON",
        ),
    ),
    CorridorWindow(
        scope_name="initial_seed",
        corridor_source="manual_seed_bucket",
        corridor_key="hampton_big_bethel",
        corridor_name="Hampton",
        route_name="S-VA114PR BIG BETHEL RD",
        window_from_measure=3.12,
        window_to_measure=5.26,
        selected_signals=("24", "25", "167", "168", "185"),
    ),
    CorridorWindow(
        scope_name="initial_seed",
        corridor_source="manual_seed_bucket",
        corridor_key="hmms_braddock_eb",
        corridor_name="HMMS",
        route_name="R-VA029SC00620EB",
        window_from_measure=3.15,
        window_to_measure=9.16,
        selected_signals=(
            "Sully Park Drive",
            "Braddock Road / Walney Road",
            "Colchester Road",
            "Clifton Road",
            "Nb Ramp / Fairfax County Parkway",
        ),
    ),
)


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


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


def _slugify(raw_value: object) -> str:
    slug = re.sub(r"[^0-9A-Za-z]+", "_", str(raw_value).strip()).strip("_").lower()
    return slug or "corridor"


def _parse_direction_of_travel(raw_value: object) -> str | None:
    if raw_value is None or pd.isna(raw_value):
        return None

    tokens = [token.strip() for token in str(raw_value).replace("/", ";").split(";") if token.strip()]
    if not tokens:
        return None

    parsed: list[str] = []
    for token in tokens:
        normalized = token.upper()
        if normalized in {"N/A", "NA", "NONE", "UNKNOWN", "NULL"}:
            return None
        matches = CARDINAL_WORD_PATTERN.findall(normalized)
        if len(matches) != 1:
            return None
        parsed.append(CARDINAL_WORD_TO_LABEL[matches[0].upper()])

    unique = sorted(set(parsed))
    if len(unique) != 1:
        return None
    return unique[0]


def _parse_route_suffix_direction(route_name: object) -> str | None:
    if route_name is None or pd.isna(route_name):
        return None
    match = ROUTE_SUFFIX_PATTERN.search(str(route_name).strip())
    if not match:
        return None
    return ROUTE_SUFFIX_TO_LABEL[match.group(1).upper()]


def _parse_route_common_direction(route_common: object) -> str | None:
    if route_common is None or pd.isna(route_common):
        return None
    match = ROUTE_COMMON_TOKEN_PATTERN.search(str(route_common).strip())
    if not match:
        return None
    return CARDINAL_TOKEN_TO_LABEL[match.group(1).upper()]


def _route_name_fallback_result(
    route_name: object,
    route_common: object,
    strict_result: dict[str, object],
    empirical_result: dict[str, object],
) -> dict[str, object]:
    if empirical_result["Status"] == "assigned":
        return {
            "Method": ROUTE_NAME_FALLBACK_RULE_NAME,
            "Status": "unresolved",
            "AssignedDirection": None,
            "Activated": False,
            "Source": None,
            "Reason": f"{EMPIRICAL_90_RULE_NAME} already assigned from filtered empirical crash evidence",
        }

    route_suffix_direction = _parse_route_suffix_direction(route_name)
    if route_suffix_direction is None:
        return {
            "Method": ROUTE_NAME_FALLBACK_RULE_NAME,
            "Status": "unresolved",
            "AssignedDirection": None,
            "Activated": False,
            "Source": None,
            "Reason": "route-name fallback requires a parseable NB/SB/EB/WB suffix on RTE_NM",
        }

    route_common_direction = _parse_route_common_direction(route_common)
    if route_common_direction is not None and route_common_direction != route_suffix_direction:
        return {
            "Method": ROUTE_NAME_FALLBACK_RULE_NAME,
            "Status": "unresolved",
            "AssignedDirection": None,
            "Activated": False,
            "Source": "route_name_suffix,route_common_token",
            "Reason": "route-name fallback withheld because route-name fields disagree on direction",
        }

    qualifying_count = int(empirical_result["QualifyingCrashCount"])
    dominant_direction = empirical_result["DominantDirection"]
    sources = "route_name_suffix"
    if route_common_direction == route_suffix_direction:
        sources = "route_common_token,route_name_suffix"

    if qualifying_count == 0:
        return {
            "Method": ROUTE_NAME_FALLBACK_RULE_NAME,
            "Status": "assigned",
            "AssignedDirection": route_suffix_direction,
            "Activated": True,
            "Source": sources,
            "Reason": "fallback assigned from route-name token support because filtered empirical crashes are absent",
        }

    if (
        qualifying_count < PRIMARY_MIN_QUALIFYING_CRASHES
        and dominant_direction is not None
        and dominant_direction == route_suffix_direction
    ):
        return {
            "Method": ROUTE_NAME_FALLBACK_RULE_NAME,
            "Status": "assigned",
            "AssignedDirection": route_suffix_direction,
            "Activated": True,
            "Source": sources,
            "Reason": "fallback assigned from route-name token support because the only filtered empirical crash agrees but remains below the count threshold",
        }

    if strict_result["Reason"] == "qualifying crashes disagree on direction" or qualifying_count >= PRIMARY_MIN_QUALIFYING_CRASHES:
        reason = "route-name fallback withheld because filtered empirical evidence is mixed rather than sparse"
    else:
        reason = "route-name fallback withheld because the sparse filtered empirical signal disagrees with the route token"
    return {
        "Method": ROUTE_NAME_FALLBACK_RULE_NAME,
        "Status": "unresolved",
        "AssignedDirection": None,
        "Activated": False,
        "Source": sources,
        "Reason": reason,
    }


def _counts_to_json(counts: dict[str, int]) -> str:
    return json.dumps({key: int(value) for key, value in sorted(counts.items())}, sort_keys=True)


def _direction_count_fields(prefix: str, counts: dict[str, int]) -> dict[str, int]:
    return {f"{prefix}{label}Count": int(counts.get(label, 0)) for label in CARDINAL_LABELS}


def _evaluate_direction_counts(
    counts: dict[str, int],
    *,
    min_qualifying_crashes: int,
    method_name: str,
    dominant_share_threshold: float | None = None,
    require_unanimity: bool = False,
) -> dict[str, object]:
    ordered_counts = {key: int(value) for key, value in sorted(counts.items())}
    total = int(sum(ordered_counts.values()))
    distinct = int(len(ordered_counts))
    if total == 0:
        return {
            "Method": method_name,
            "Status": "unresolved",
            "AssignedDirection": None,
            "QualifyingCrashCount": 0,
            "DistinctDirectionCount": 0,
            "DominantDirection": None,
            "DominantCount": 0,
            "DominantShare": None,
            "MeetsDominantShareThreshold": False,
            "DirectionCounts": ordered_counts,
            "DirectionCountsJson": _counts_to_json(ordered_counts),
            "Reason": "no qualifying crashes",
        }

    dominant_direction, dominant_count = max(ordered_counts.items(), key=lambda item: (item[1], item[0]))
    dominant_count = int(dominant_count)
    dominant_share = round(dominant_count / total, 4)

    meets_dominant_share_threshold = bool(
        dominant_share_threshold is not None and dominant_share >= float(dominant_share_threshold)
    )

    if total < min_qualifying_crashes:
        status = "unresolved"
        assigned_direction = None
        reason = f"fewer than {min_qualifying_crashes} qualifying crashes"
    elif require_unanimity and distinct != 1:
        status = "unresolved"
        assigned_direction = None
        reason = "qualifying crashes disagree on direction"
    elif distinct == 1:
        status = "assigned"
        assigned_direction = dominant_direction
        reason = f"{total} qualifying crashes all agree on {dominant_direction}"
    elif dominant_share_threshold is not None and meets_dominant_share_threshold:
        status = "assigned"
        assigned_direction = dominant_direction
        reason = (
            f"{dominant_direction} holds {dominant_count} of {total} qualifying crashes "
            f"({dominant_share:.1%}) and meets the {dominant_share_threshold:.0%} threshold"
        )
    else:
        status = "unresolved"
        assigned_direction = None
        if dominant_share_threshold is not None:
            reason = (
                f"dominant share {dominant_share:.1%} stays below the {dominant_share_threshold:.0%} threshold"
            )
        else:
            reason = "qualifying crashes disagree on direction"

    return {
        "Method": method_name,
        "Status": status,
        "AssignedDirection": assigned_direction,
        "QualifyingCrashCount": total,
        "DistinctDirectionCount": distinct,
        "DominantDirection": dominant_direction,
        "DominantCount": dominant_count,
        "DominantShare": dominant_share,
        "MeetsDominantShareThreshold": meets_dominant_share_threshold,
        "DirectionCounts": ordered_counts,
        "DirectionCountsJson": _counts_to_json(ordered_counts),
        "Reason": reason,
    }


def _slice_overlap(
    frame: pd.DataFrame,
    *,
    route_field: str,
    from_field: str,
    to_field: str,
    route_name: str,
    window_from_measure: float,
    window_to_measure: float,
) -> pd.DataFrame:
    subset = frame.loc[frame[route_field].eq(route_name)].copy()
    subset["WindowFromMeasure"] = pd.to_numeric(subset[from_field], errors="coerce").clip(lower=window_from_measure)
    subset["WindowToMeasure"] = pd.to_numeric(subset[to_field], errors="coerce").clip(upper=window_to_measure)
    subset = subset.loc[subset["WindowFromMeasure"] < subset["WindowToMeasure"]].copy()
    return subset.sort_values(["WindowFromMeasure", "WindowToMeasure"]).reset_index(drop=True)


def _measure_mask(measures: pd.Series, start: float, end: float, *, inclusive_upper: bool) -> pd.Series:
    numeric = pd.to_numeric(measures, errors="coerce")
    if inclusive_upper:
        return numeric.ge(start) & numeric.le(end)
    return numeric.ge(start) & numeric.lt(end)


def _load_study_roads(config) -> gpd.GeoDataFrame:
    path = config.output_dir / "stage1b_study_slice" / "Study_Roads_Divided.parquet"
    roads = gpd.read_parquet(path)
    roads = roads[
        ["RTE_NM", "FROM_MEASURE", "TO_MEASURE", "RTE_ID", "RTE_COMMON", "RIM_FACILI", "RIM_MEDIAN", "geometry"]
    ].reset_index(names="StudyRoad_RowID")
    roads["StudyRoad_RowID"] = roads["StudyRoad_RowID"].astype(int)
    return roads


def _load_signals(config) -> gpd.GeoDataFrame:
    path = config.output_dir / "stage1b_study_slice" / "Study_Signals_NearestRoad.parquet"
    signals = gpd.read_parquet(path)
    signals = signals[
        [
            "Signal_RowID",
            "REG_SIGNAL_ID",
            "SIGNAL_NO",
            "INTNO",
            "MAJ_NAME",
            "MINOR_NAME",
            "NearestRoad_RowID",
            "NearestRoad_RTE_NM",
            "NearestRoad_FROM_MEASURE",
            "NearestRoad_TO_MEASURE",
            "NearestRoad_RTE_COMMON",
            "geometry",
        ]
    ].copy()
    signals["NearestRoad_RowID"] = pd.to_numeric(signals["NearestRoad_RowID"], errors="coerce").astype("Int64")
    return signals


def _classify_crash_filter_status(row: pd.Series) -> str:
    if pd.isna(row["ParsedDirectionOfTravel"]):
        return "excluded_no_clear_cardinal_dot"
    if not bool(row["IsSingleVehicle"]) and not bool(row["IsStraightAhead"]):
        return "excluded_not_single_vehicle_and_not_straight_ahead"
    if not bool(row["IsSingleVehicle"]):
        return "excluded_not_single_vehicle"
    if not bool(row["IsStraightAhead"]):
        return "excluded_not_straight_ahead"
    return "primary_filtered"


def _load_crashes(config) -> gpd.GeoDataFrame:
    basic_path = config.normalized_dir / "crashes.parquet"
    basic = gpd.read_parquet(
        basic_path,
        columns=["DOCUMENT_NBR", "CRASH_YEAR", "RTE_NM", "RNS_MP", "VEH_COUNT", "geometry"],
    )
    details = pyogrio.read_dataframe(
        config.raw_data_dir / "crashdata.gdb",
        layer="CrashData_Details",
        columns=["DOCUMENT_NBR", "DIRECTION_OF_TRAVEL_CD", "VEHICLE_MANEUVER_TYPE_CD"],
        read_geometry=False,
    )
    crashes = basic.merge(details, on="DOCUMENT_NBR", how="left", validate="one_to_one")
    crashes = gpd.GeoDataFrame(crashes, geometry="geometry", crs=basic.crs)
    crashes["ParsedDirectionOfTravel"] = crashes["DIRECTION_OF_TRAVEL_CD"].map(_parse_direction_of_travel)
    crashes["IsSingleVehicle"] = pd.to_numeric(crashes["VEH_COUNT"], errors="coerce").eq(1)
    crashes["IsStraightAhead"] = crashes["VEHICLE_MANEUVER_TYPE_CD"].eq(PRIMARY_MANEUVER)
    crashes["CrashDOTOnlyIncluded"] = crashes["ParsedDirectionOfTravel"].notna()
    crashes["PrimaryIncluded"] = (
        crashes["CrashDOTOnlyIncluded"] & crashes["IsSingleVehicle"] & crashes["IsStraightAhead"]
    )
    crashes["CrashFilterStatus"] = crashes.apply(_classify_crash_filter_status, axis=1)
    return crashes


def _clean_label_value(raw_value: object) -> str:
    if raw_value is None or pd.isna(raw_value):
        return ""
    if isinstance(raw_value, numbers.Real) and not isinstance(raw_value, bool):
        numeric_value = float(raw_value)
        if numeric_value.is_integer():
            return str(int(numeric_value))
    return str(raw_value).strip()


def _build_signal_labels(signal_rows: pd.DataFrame) -> str:
    labels: list[str] = []
    for row in signal_rows.itertuples(index=False):
        major = _clean_label_value(getattr(row, "MAJ_NAME", None))
        minor = _clean_label_value(getattr(row, "MINOR_NAME", None))
        if major and minor:
            labels.append(f"{major} / {minor}")
            continue
        for field_name in ("REG_SIGNAL_ID", "SIGNAL_NO", "INTNO", "Signal_RowID"):
            value = getattr(row, field_name, None)
            if value is not None and not pd.isna(value):
                labels.append(str(value).strip())
                break
    unique = []
    for label in labels:
        if label and label not in unique:
            unique.append(label)
    return " | ".join(unique)


def _build_expanded_corridors(roads: gpd.GeoDataFrame, signals: gpd.GeoDataFrame) -> tuple[CorridorWindow, ...]:
    signal_rows = signals.dropna(subset=["NearestRoad_RowID", "NearestRoad_RTE_NM"]).copy()
    signal_rows["NearestRoad_RowID"] = signal_rows["NearestRoad_RowID"].astype(int)

    row_signal_counts = (
        signal_rows.groupby(["NearestRoad_RowID", "NearestRoad_RTE_NM"], as_index=False)
        .agg(SignalCount=("Signal_RowID", "nunique"))
    )
    matched_rows = roads[["StudyRoad_RowID", "RTE_NM", "RTE_COMMON", "FROM_MEASURE", "TO_MEASURE"]].merge(
        row_signal_counts,
        left_on=["StudyRoad_RowID", "RTE_NM"],
        right_on=["NearestRoad_RowID", "NearestRoad_RTE_NM"],
        how="inner",
    )
    matched_rows = matched_rows.sort_values(["RTE_NM", "FROM_MEASURE", "TO_MEASURE"]).reset_index(drop=True)

    assignments: list[dict[str, object]] = []
    for route_name, route_rows in matched_rows.groupby("RTE_NM", sort=False):
        route_rows = route_rows.drop_duplicates("StudyRoad_RowID").sort_values(["FROM_MEASURE", "TO_MEASURE"])
        corridor_index = 0
        current_end: float | None = None
        for row in route_rows.itertuples(index=False):
            start = float(row.FROM_MEASURE)
            end = float(row.TO_MEASURE)
            if current_end is None or start > current_end + CONTIGUITY_GAP_TOLERANCE:
                corridor_index += 1
                current_end = end
            else:
                current_end = max(current_end, end)
            assignments.append(
                {
                    "RTE_NM": route_name,
                    "StudyRoad_RowID": int(row.StudyRoad_RowID),
                    "CorridorIndex": corridor_index,
                    "RTE_COMMON": row.RTE_COMMON,
                    "FROM_MEASURE": start,
                    "TO_MEASURE": end,
                }
            )

    assignment_frame = pd.DataFrame(assignments)
    if assignment_frame.empty:
        return ()

    signal_with_corridor = signal_rows.merge(
        assignment_frame[["RTE_NM", "StudyRoad_RowID", "CorridorIndex"]],
        left_on=["NearestRoad_RTE_NM", "NearestRoad_RowID"],
        right_on=["RTE_NM", "StudyRoad_RowID"],
        how="inner",
    )
    corridor_summary = (
        assignment_frame.groupby(["RTE_NM", "CorridorIndex"], as_index=False)
        .agg(
            window_from_measure=("FROM_MEASURE", "min"),
            window_to_measure=("TO_MEASURE", "max"),
            route_common=("RTE_COMMON", "first"),
        )
        .merge(
            signal_with_corridor.groupby(["RTE_NM", "CorridorIndex"], as_index=False).agg(
                signal_count=("Signal_RowID", "nunique")
            ),
            on=["RTE_NM", "CorridorIndex"],
            how="left",
        )
    )
    corridor_summary["signal_count"] = corridor_summary["signal_count"].fillna(0).astype(int)
    corridor_summary = corridor_summary.loc[corridor_summary["signal_count"].ge(EXPANDED_MIN_SIGNALS_PER_CORRIDOR)]

    expanded_corridors: list[CorridorWindow] = []
    for row in corridor_summary.itertuples(index=False):
        signal_subset = signal_with_corridor.loc[
            signal_with_corridor["RTE_NM"].eq(row.RTE_NM) & signal_with_corridor["CorridorIndex"].eq(row.CorridorIndex)
        ].copy()
        signal_labels = _build_signal_labels(signal_subset)
        preview_signals = tuple(part.strip() for part in signal_labels.split("|") if part.strip())[:5]
        route_common = _clean_label_value(row.route_common) or str(row.RTE_NM)
        corridor_name = f"{route_common} {float(row.window_from_measure):.2f}-{float(row.window_to_measure):.2f}"
        corridor_key = (
            f"expanded_{_slugify(row.RTE_NM)}_{int(row.CorridorIndex):02d}_"
            f"{int(round(float(row.window_from_measure) * 100)):05d}_"
            f"{int(round(float(row.window_to_measure) * 100)):05d}"
        )
        expanded_corridors.append(
            CorridorWindow(
                scope_name="expanded_signal_windows",
                corridor_source=f"auto_signal_window_min_{EXPANDED_MIN_SIGNALS_PER_CORRIDOR}_signals",
                corridor_key=corridor_key,
                corridor_name=corridor_name,
                route_name=str(row.RTE_NM),
                window_from_measure=round(float(row.window_from_measure), 4),
                window_to_measure=round(float(row.window_to_measure), 4),
                selected_signals=preview_signals,
            )
        )
    return tuple(sorted(expanded_corridors, key=lambda item: (item.route_name, item.window_from_measure)))


def _support_relation(primary_status: str, primary_direction: object, context_status: str, context_direction: object) -> str:
    if primary_status != "assigned":
        return "not_applicable"
    if context_status != "assigned" or not context_direction:
        return "no_support_context"
    if primary_direction == context_direction:
        return "agrees_with_primary"
    return "conflicts_with_primary"


def _corridor_continuity_summary(assignment_rows: pd.DataFrame) -> dict[str, object]:
    assigned_rows = assignment_rows.loc[assignment_rows["PrimaryStatus"].eq("assigned")].copy()
    unresolved_rows = assignment_rows.loc[assignment_rows["PrimaryStatus"].ne("assigned")].copy()
    assigned_directions = assigned_rows["PrimaryAssignedDirection"].dropna().astype(str).tolist()
    unique_directions = sorted(set(assigned_directions))
    adjacent_breaks = 0
    if len(assigned_rows) > 1:
        ordered = assigned_rows.sort_values("RowOrderWithinCorridor")
        previous: str | None = None
        for direction in ordered["PrimaryAssignedDirection"].astype(str):
            if previous is not None and previous != direction:
                adjacent_breaks += 1
            previous = direction
    internal_gap_count = 0
    if not assigned_rows.empty:
        first_assigned = int(assigned_rows["RowOrderWithinCorridor"].min())
        last_assigned = int(assigned_rows["RowOrderWithinCorridor"].max())
        internal_gap_count = int(
            assignment_rows.loc[
                assignment_rows["RowOrderWithinCorridor"].between(first_assigned, last_assigned)
                & assignment_rows["PrimaryStatus"].ne("assigned")
            ].shape[0]
        )
    if not unique_directions:
        continuity_status = "unresolved"
        corridor_direction = None
        continuity_reason = "no row-level assignments"
    elif len(unique_directions) > 1 or adjacent_breaks > 0:
        continuity_status = "fragmented"
        corridor_direction = None
        continuity_reason = "assigned rows fragment across multiple directions"
    elif not unresolved_rows.empty:
        continuity_status = "assigned_with_gaps"
        corridor_direction = unique_directions[0]
        continuity_reason = "assigned rows agree but one or more rows remain unresolved"
    else:
        continuity_status = "continuous_assigned"
        corridor_direction = unique_directions[0]
        continuity_reason = "all row-level assignments agree with no gaps"
    return {
        "PrimaryAssignedDirectionSetJson": json.dumps(unique_directions),
        "PrimaryUniqueAssignedDirectionCount": int(len(unique_directions)),
        "PrimaryAdjacentDirectionBreakCount": int(adjacent_breaks),
        "PrimaryInternalGapCount": int(internal_gap_count),
        "PrimaryContinuityStatus": continuity_status,
        "PrimaryCorridorDirection": corridor_direction,
        "PrimaryContinuityReason": continuity_reason,
    }


def _conflict_strength_class(has_conflict: bool, dominant_share: object) -> str:
    if not bool(has_conflict):
        return "no_conflict"
    if dominant_share is None or pd.isna(dominant_share):
        return "hard_conflict"
    share = float(dominant_share)
    if share >= 0.90:
        return "soft_conflict_90_plus"
    if share >= 0.80:
        return "soft_conflict_80_89"
    if share >= 0.70:
        return "soft_conflict_70_79"
    if share >= 0.60:
        return "soft_conflict_60_69"
    if share >= 0.50:
        return "soft_conflict_50_59"
    return "hard_conflict"


def _single_vehicle_support_relation(row: pd.Series) -> str:
    support_assigned = row["SingleVehicleSupportStatus"] == "assigned"
    if support_assigned and bool(row["CrashDOTOnlyHasConflict"]):
        return "clean_single_vehicle_signal_broader_conflict"
    if support_assigned and row["StrictUnanimousStatus"] == "assigned":
        return "supports_strict_assignment"
    if support_assigned and row["Empirical90PctStatus"] == "assigned":
        return "supports_empirical90_assignment"
    if support_assigned:
        return "single_vehicle_only_assignment"
    if bool(row.get("SingleVehicleSupportHasConflict", False)):
        return "single_vehicle_also_conflicted"
    if int(row["SingleVehicleSupportQualifyingCrashCount"]) < PRIMARY_MIN_QUALIFYING_CRASHES:
        return "insufficient_single_vehicle_signal"
    return "not_applicable"


def _route_name_fallback_relation(row: pd.Series) -> str:
    route_direction = row["RoadwayContextAssignedDirection"]
    empirical_dominant = row["Empirical90PctDominantDirection"]
    route_available = route_direction is not None and not pd.isna(route_direction)
    empirical_available = empirical_dominant is not None and not pd.isna(empirical_dominant)
    if route_available and empirical_available and route_direction != empirical_dominant:
        return "fallback_disagrees_with_empirical_dominant"
    if row["RouteNameFallbackStatus"] != "assigned":
        return "not_used"
    if bool(row["PrimaryHasConflict"]) or bool(row["Empirical90PctHasConflict"]):
        return "fallback_used_due_to_conflict"
    if row["StrictUnanimousReason"] in {
        "no qualifying crashes",
        f"fewer than {PRIMARY_MIN_QUALIFYING_CRASHES} qualifying crashes",
    }:
        return "fallback_used_due_to_weak_data"
    if route_available and empirical_available and route_direction == empirical_dominant:
        return "fallback_matches_empirical_dominant"
    return "fallback_only_assignment"


def _review_priority_details(row: pd.Series) -> tuple[str, int, str]:
    if bool(row["IsNewlyAssignedEmpirical90"]):
        return "highest", 100, "strict conflict softens to a >=90% dominant empirical direction"
    if bool(row["IsNewlyAssignedSingleVehicleSupport"]):
        return "highest", 99, "single-vehicle straight-ahead support is the only bounded rule that assigns"
    if row["ConflictStrengthClass"] == "soft_conflict_90_plus":
        return "highest", 98, "filtered empirical conflict remains but one direction still holds >=90% share"
    if row["SingleVehicleSupportRelation"] == "clean_single_vehicle_signal_broader_conflict":
        return "highest", 96, "single-vehicle straight-ahead signal is clean while broader crash DOT conflicts"
    if bool(row["EmpiricalFallbackDisagreement"]):
        return "highest", 95, "route-name support disagrees with the empirical dominant direction"
    if row["ConflictStrengthClass"] == "soft_conflict_80_89":
        return "high", 88, "filtered empirical conflict has an 80-89% dominant direction worth checking spatially"
    if bool(row["IsFallbackOnlyAssignment"]):
        return "high", 84, "row assigns only through route-name fallback after weak empirical evidence"
    if bool(row["IsStillUnresolvedAfterAllBoundedVariants"]) and bool(row["PrimaryHasConflict"]):
        return "high", 82, "row stays unresolved after every bounded variant and still has filtered empirical conflict"
    if bool(row["IsStillUnresolvedAfterAllBoundedVariants"]):
        return "medium", 68, "row stays unresolved after every bounded variant"
    if bool(row["RouteNameFallbackActivated"]):
        return "medium", 62, "route-name fallback activates under weak empirical evidence"
    if row["SingleVehicleSupportRelation"] in {"supports_empirical90_assignment", "supports_strict_assignment"}:
        return "low", 42, "single-vehicle support agrees with the current empirical read"
    return "low", 20, "no elevated review signal beyond the baseline outputs"


def _apply_review_support_fields(assignment_table: pd.DataFrame) -> pd.DataFrame:
    if assignment_table.empty:
        return assignment_table
    frame = assignment_table.copy()
    frame["SingleVehicleSupportHasConflict"] = frame["SingleVehicleSupportDirectionCountsJson"].map(
        lambda raw_value: len(json.loads(raw_value)) > 1 if raw_value else False
    )
    frame["ConflictStrengthClass"] = frame.apply(
        lambda row: _conflict_strength_class(row["PrimaryHasConflict"], row["PrimaryDominantShare"]),
        axis=1,
    )
    frame["SingleVehicleSupportRelation"] = frame.apply(_single_vehicle_support_relation, axis=1)
    frame["RouteNameFallbackRelation"] = frame.apply(_route_name_fallback_relation, axis=1)
    frame["IsSoftConflict90Plus"] = frame["ConflictStrengthClass"].eq("soft_conflict_90_plus")
    frame["IsSoftConflict80To89"] = frame["ConflictStrengthClass"].eq("soft_conflict_80_89")
    frame["IsSingleVehicleCleanBroaderConflict"] = (
        frame["CrashDOTOnlyHasConflict"] & frame["SingleVehicleSupportStatus"].eq("assigned")
    )
    frame["IsNewlyAssignedEmpirical90"] = (
        frame["StrictUnanimousStatus"].ne("assigned") & frame["Empirical90PctStatus"].eq("assigned")
    )
    frame["IsNewlyAssignedSingleVehicleSupport"] = (
        frame["StrictUnanimousStatus"].ne("assigned")
        & frame["Empirical90PctStatus"].ne("assigned")
        & frame["SingleVehicleSupportStatus"].eq("assigned")
    )
    frame["IsFallbackOnlyAssignment"] = (
        frame["StrictUnanimousStatus"].ne("assigned")
        & frame["Empirical90PctStatus"].ne("assigned")
        & frame["SingleVehicleSupportStatus"].ne("assigned")
        & frame["RouteNameFallbackStatus"].eq("assigned")
    )
    frame["IsStillUnresolvedAfterAllBoundedVariants"] = (
        frame["StrictUnanimousStatus"].ne("assigned")
        & frame["Empirical90PctStatus"].ne("assigned")
        & frame["SingleVehicleSupportStatus"].ne("assigned")
        & frame["RouteNameFallbackStatus"].ne("assigned")
    )
    frame["EmpiricalFallbackDisagreement"] = (
        frame["Empirical90PctDominantDirection"].notna()
        & frame["RoadwayContextAssignedDirection"].notna()
        & frame["Empirical90PctDominantDirection"].ne(frame["RoadwayContextAssignedDirection"])
    )
    priority_details = frame.apply(_review_priority_details, axis=1, result_type="expand")
    priority_details.columns = ["ReviewPriorityClass", "ReviewPriorityScore", "ReviewPriorityReason"]
    frame = pd.concat([frame, priority_details], axis=1)
    return frame


def _build_review_support_bucket_summary(assignment_table: pd.DataFrame) -> pd.DataFrame:
    if assignment_table.empty:
        return pd.DataFrame(columns=["SummaryType", "BucketName", "RowCount", "RowRate"])
    total_rows = max(int(len(assignment_table)), 1)
    parts: list[pd.DataFrame] = []
    for summary_type, field_name in (
        ("conflict_strength", "ConflictStrengthClass"),
        ("single_vehicle_support_relation", "SingleVehicleSupportRelation"),
        ("route_name_fallback_relation", "RouteNameFallbackRelation"),
        ("review_priority", "ReviewPriorityClass"),
    ):
        part = (
            assignment_table.groupby(field_name, dropna=False)
            .size()
            .reset_index(name="RowCount")
            .rename(columns={field_name: "BucketName"})
        )
        part["SummaryType"] = summary_type
        part["RowRate"] = (part["RowCount"] / total_rows).round(4)
        parts.append(part[["SummaryType", "BucketName", "RowCount", "RowRate"]])
    return pd.concat(parts, ignore_index=True).sort_values(["SummaryType", "RowCount", "BucketName"], ascending=[True, False, True])


def _review_ready_columns() -> list[str]:
    return [
        "ReviewPriorityClass",
        "ReviewPriorityScore",
        "ReviewPriorityReason",
        "ConflictStrengthClass",
        "SingleVehicleSupportRelation",
        "RouteNameFallbackRelation",
        "IsNewlyAssignedEmpirical90",
        "IsNewlyAssignedSingleVehicleSupport",
        "IsFallbackOnlyAssignment",
        "IsStillUnresolvedAfterAllBoundedVariants",
        "EmpiricalFallbackDisagreement",
        "ScopeName",
        "CorridorKey",
        "CorridorName",
        "RTE_NM",
        "StudyRoad_RowID",
        "WindowFromMeasure",
        "WindowToMeasure",
        "SignalCount",
        "SignalLabels",
        "StrictUnanimousStatus",
        "StrictUnanimousAssignedDirection",
        "StrictUnanimousReason",
        "Empirical90PctStatus",
        "Empirical90PctAssignedDirection",
        "Empirical90PctReason",
        "SingleVehicleSupportStatus",
        "SingleVehicleSupportAssignedDirection",
        "SingleVehicleSupportReason",
        "RouteNameFallbackStatus",
        "RouteNameFallbackAssignedDirection",
        "RouteNameFallbackReason",
        "RoadwayContextAssignedDirection",
        "PrimaryQualifyingCrashCount",
        "PrimaryDominantDirection",
        "PrimaryDominantShare",
        "PrimaryDirectionCountsJson",
        "CrashDOTOnlyQualifyingCrashCount",
        "CrashDOTOnlyDominantDirection",
        "CrashDOTOnlyDominantShare",
        "CrashDOTOnlyDirectionCountsJson",
        "SingleVehicleSupportQualifyingCrashCount",
        "SingleVehicleSupportDominantDirection",
        "SingleVehicleSupportDominantShare",
        "SingleVehicleSupportDirectionCountsJson",
    ]


def _build_targeted_review_outputs(assignment_table: pd.DataFrame) -> dict[str, pd.DataFrame]:
    columns = _review_ready_columns()
    empty_frame = pd.DataFrame(columns=columns)
    if assignment_table.empty:
        return {
            "soft_conflicts_90_plus": empty_frame.copy(),
            "soft_conflicts_80_89": empty_frame.copy(),
            "single_vehicle_clean_rows": empty_frame.copy(),
            "newly_assigned_empirical90": empty_frame.copy(),
            "newly_assigned_single_vehicle_support_only": empty_frame.copy(),
            "fallback_only_assignments": empty_frame.copy(),
            "still_unresolved_after_all_variants": empty_frame.copy(),
            "empirical_vs_fallback_disagreement": empty_frame.copy(),
        }

    def subset(mask: pd.Series) -> pd.DataFrame:
        return assignment_table.loc[mask, columns].sort_values(
            ["ReviewPriorityScore", "CorridorName", "WindowFromMeasure", "StudyRoad_RowID"],
            ascending=[False, True, True, True],
        )

    return {
        "soft_conflicts_90_plus": subset(assignment_table["IsSoftConflict90Plus"]),
        "soft_conflicts_80_89": subset(assignment_table["IsSoftConflict80To89"]),
        "single_vehicle_clean_rows": subset(
            assignment_table["IsSingleVehicleCleanBroaderConflict"]
            & assignment_table["StrictUnanimousStatus"].ne("assigned")
        ),
        "newly_assigned_empirical90": subset(assignment_table["IsNewlyAssignedEmpirical90"]),
        "newly_assigned_single_vehicle_support_only": subset(assignment_table["IsNewlyAssignedSingleVehicleSupport"]),
        "fallback_only_assignments": subset(assignment_table["IsFallbackOnlyAssignment"]),
        "still_unresolved_after_all_variants": subset(assignment_table["IsStillUnresolvedAfterAllBoundedVariants"]),
        "empirical_vs_fallback_disagreement": subset(assignment_table["EmpiricalFallbackDisagreement"]),
    }


def _build_review_support_summary_markdown(
    assignment_table: pd.DataFrame,
    targeted_outputs: dict[str, pd.DataFrame],
) -> str:
    total_rows = int(len(assignment_table))
    hard_conflicts = int(assignment_table["ConflictStrengthClass"].eq("hard_conflict").sum()) if total_rows else 0
    soft_conflicts = int(
        assignment_table["ConflictStrengthClass"].isin(
            {
                "soft_conflict_50_59",
                "soft_conflict_60_69",
                "soft_conflict_70_79",
                "soft_conflict_80_89",
                "soft_conflict_90_plus",
            }
        ).sum()
    ) if total_rows else 0
    single_vehicle_interpretable = int(
        (
            assignment_table["StrictUnanimousStatus"].ne("assigned")
            & assignment_table["SingleVehicleSupportStatus"].eq("assigned")
        ).sum()
    ) if total_rows else 0
    lines = [
        "# Review Support Summary",
        "",
        f"- Study-road rows in expanded sample: `{total_rows}`",
        f"- Hard conflicts: `{hard_conflicts}`",
        f"- Soft conflicts: `{soft_conflicts}`",
        f"- Soft conflicts with >=90% dominant share: `{len(targeted_outputs['soft_conflicts_90_plus'])}`",
        f"- Soft conflicts with 80-89% dominant share: `{len(targeted_outputs['soft_conflicts_80_89'])}`",
        f"- Single-vehicle-clean rows against broader crash conflict: `{len(targeted_outputs['single_vehicle_clean_rows'])}`",
        f"- Strict-unresolved rows that become interpretable under single-vehicle support: `{single_vehicle_interpretable}`",
        f"- Newly assigned under `{EMPIRICAL_90_RULE_NAME}`: `{len(targeted_outputs['newly_assigned_empirical90'])}`",
        f"- Newly assigned only under `{SINGLE_VEHICLE_SUPPORT_RULE_NAME}`: `{len(targeted_outputs['newly_assigned_single_vehicle_support_only'])}`",
        f"- Fallback-only assignments: `{len(targeted_outputs['fallback_only_assignments'])}`",
        f"- Still unresolved after all bounded variants: `{len(targeted_outputs['still_unresolved_after_all_variants'])}`",
        f"- Empirical-vs-fallback disagreements: `{len(targeted_outputs['empirical_vs_fallback_disagreement'])}`",
        "",
        "## GIS Review Order",
        "",
        f"1. `{EMPIRICAL_90_RULE_NAME}` newly assigned rows, because they are the closest bounded relaxation of the strict baseline.",
        f"2. `soft_conflicts_90_plus`, then `soft_conflicts_80_89`, to separate strong-dominant disagreement from truly ambiguous conflict.",
        "3. `single_vehicle_clean_rows`, especially where broader crash DOT is noisy but the clean single-vehicle straight-ahead subset stays directional.",
        "4. `empirical_vs_fallback_disagreement`, because these rows expose the sharpest support-versus-empirical tension.",
        "5. `fallback_only_assignments`, treated as secondary and review-sensitive rather than trusted truth.",
        "6. `still_unresolved_after_all_variants`, to identify the genuinely hard cases that should remain unresolved unless a new evidence source is justified.",
    ]
    return "\n".join(lines) + "\n"


def _single_vehicle_support_activation(
    crash_dot_only_result: dict[str, object],
    support_result: dict[str, object],
) -> str:
    if support_result["Status"] != "assigned":
        return "no_support_signal"
    if crash_dot_only_result["Status"] == "assigned":
        return "not_needed_broad_crash_dot_already_assigned"
    if int(crash_dot_only_result["DistinctDirectionCount"]) > 1:
        return "activated_against_broad_crash_conflict"
    return "activated_for_weak_broad_crash_data"


def _build_reason_summary(assignment_table: pd.DataFrame) -> pd.DataFrame:
    if assignment_table.empty:
        return pd.DataFrame(columns=["PrimaryStatus", "PrimaryReason", "RowCount", "RowRate"])
    reason_summary = (
        assignment_table.groupby(["PrimaryStatus", "PrimaryReason"], dropna=False)
        .size()
        .reset_index(name="RowCount")
        .sort_values(["PrimaryStatus", "RowCount", "PrimaryReason"], ascending=[True, False, True])
    )
    total_rows = max(int(len(assignment_table)), 1)
    reason_summary["RowRate"] = (reason_summary["RowCount"] / total_rows).round(4)
    return reason_summary


def _build_rule_comparison_summary(assignment_table: pd.DataFrame) -> pd.DataFrame:
    if assignment_table.empty:
        return pd.DataFrame(
            columns=[
                "RuleName",
                "AssignedRowCount",
                "UnresolvedRowCount",
                "AssignedRowRate",
                "UnresolvedRowRate",
                "NewlyAssignedVsStrictCount",
                "NewlyAssignedVsStrictRate",
                "ActivatedFallbackCount",
            ]
        )
    total_rows = max(int(len(assignment_table)), 1)
    rule_specs = (
        (STRICT_RULE_NAME, "StrictUnanimousStatus", None),
        (EMPIRICAL_90_RULE_NAME, "Empirical90PctStatus", None),
        (SINGLE_VEHICLE_SUPPORT_RULE_NAME, "SingleVehicleSupportStatus", "SingleVehicleSupportActivated"),
        (ROUTE_NAME_FALLBACK_RULE_NAME, "RouteNameFallbackStatus", "RouteNameFallbackActivated"),
    )
    rows: list[dict[str, object]] = []
    strict_assigned_mask = assignment_table["StrictUnanimousStatus"].eq("assigned")
    for rule_name, status_field, activation_field in rule_specs:
        assigned_mask = assignment_table[status_field].eq("assigned")
        unresolved_mask = ~assigned_mask
        row: dict[str, object] = {
            "RuleName": rule_name,
            "AssignedRowCount": int(assigned_mask.sum()),
            "UnresolvedRowCount": int(unresolved_mask.sum()),
            "AssignedRowRate": round(float(assigned_mask.sum()) / total_rows, 4),
            "UnresolvedRowRate": round(float(unresolved_mask.sum()) / total_rows, 4),
            "NewlyAssignedVsStrictCount": int((~strict_assigned_mask & assigned_mask).sum()),
            "NewlyAssignedVsStrictRate": round(float((~strict_assigned_mask & assigned_mask).sum()) / total_rows, 4),
            "ActivatedFallbackCount": 0,
        }
        if activation_field is not None:
            row["ActivatedFallbackCount"] = int(assignment_table[activation_field].astype(bool).sum())
        rows.append(row)
    return pd.DataFrame(rows)


def _build_rule_transition_summary(assignment_table: pd.DataFrame) -> pd.DataFrame:
    if assignment_table.empty:
        return pd.DataFrame(columns=["TransitionName", "RowCount", "RowRate"])
    total_rows = max(int(len(assignment_table)), 1)
    transitions = {
        "strict_unresolved_to_empirical90_assigned": (
            assignment_table["StrictUnanimousStatus"].ne("assigned")
            & assignment_table["Empirical90PctStatus"].eq("assigned")
        ),
        "strict_unresolved_to_single_vehicle_support_assigned": (
            assignment_table["StrictUnanimousStatus"].ne("assigned")
            & assignment_table["SingleVehicleSupportStatus"].eq("assigned")
        ),
        "strict_unresolved_to_route_name_fallback_assigned": (
            assignment_table["StrictUnanimousStatus"].ne("assigned")
            & assignment_table["RouteNameFallbackStatus"].eq("assigned")
        ),
        "strict_unresolved_after_all_variants": (
            assignment_table["StrictUnanimousStatus"].ne("assigned")
            & assignment_table["Empirical90PctStatus"].ne("assigned")
            & assignment_table["SingleVehicleSupportStatus"].ne("assigned")
            & assignment_table["RouteNameFallbackStatus"].ne("assigned")
        ),
        "strict_internal_conflict_resolved_by_empirical90": (
            assignment_table["PrimaryHasConflict"]
            & assignment_table["StrictUnanimousStatus"].ne("assigned")
            & assignment_table["Empirical90PctStatus"].eq("assigned")
        ),
        "strict_internal_conflict_still_unresolved": (
            assignment_table["PrimaryHasConflict"]
            & assignment_table["Empirical90PctStatus"].ne("assigned")
            & assignment_table["RouteNameFallbackStatus"].ne("assigned")
        ),
        "broad_crash_conflict_supported_by_single_vehicle_rule": (
            assignment_table["CrashDOTOnlyStatus"].ne("assigned")
            & assignment_table["SingleVehicleSupportActivation"].eq("activated_against_broad_crash_conflict")
        ),
        "route_name_fallback_used_after_weak_or_conflicting_empirical_evidence": (
            assignment_table["RouteNameFallbackActivated"].astype(bool)
        ),
    }
    rows = [
        {
            "TransitionName": name,
            "RowCount": int(mask.sum()),
            "RowRate": round(float(mask.sum()) / total_rows, 4),
        }
        for name, mask in transitions.items()
    ]
    return pd.DataFrame(rows).sort_values("TransitionName")


def _build_conflict_profile_summary(assignment_table: pd.DataFrame) -> pd.DataFrame:
    if assignment_table.empty:
        return pd.DataFrame(columns=["ConflictProfile", "RowCount", "RowRate"])
    total_rows = max(int(len(assignment_table)), 1)
    profiles = {
        "strict_internal_conflict_rows": assignment_table["PrimaryHasConflict"],
        "strict_internal_conflict_resolved_by_empirical90": (
            assignment_table["PrimaryHasConflict"] & assignment_table["Empirical90PctStatus"].eq("assigned")
        ),
        "strict_internal_conflict_route_fallback_only": (
            assignment_table["PrimaryHasConflict"]
            & assignment_table["Empirical90PctStatus"].ne("assigned")
            & assignment_table["RouteNameFallbackStatus"].eq("assigned")
        ),
        "strict_internal_conflict_still_unresolved": (
            assignment_table["PrimaryHasConflict"]
            & assignment_table["Empirical90PctStatus"].ne("assigned")
            & assignment_table["RouteNameFallbackStatus"].ne("assigned")
        ),
        "broad_crash_dot_conflict_rows": assignment_table["CrashDOTOnlyHasConflict"],
        "broad_crash_dot_conflict_supported_by_single_vehicle_rule": (
            assignment_table["CrashDOTOnlyHasConflict"] & assignment_table["SingleVehicleSupportStatus"].eq("assigned")
        ),
    }
    rows = [
        {
            "ConflictProfile": name,
            "RowCount": int(mask.sum()),
            "RowRate": round(float(mask.sum()) / total_rows, 4),
        }
        for name, mask in profiles.items()
    ]
    return pd.DataFrame(rows).sort_values("ConflictProfile")


def _build_variant_review_targets(assignment_table: pd.DataFrame) -> pd.DataFrame:
    if assignment_table.empty:
        return pd.DataFrame(
            columns=[
                "VariantName",
                "PriorityScore",
                "CorridorKey",
                "CorridorName",
                "RTE_NM",
                "WindowFromMeasure",
                "WindowToMeasure",
                "StudyRoad_RowID",
                "AssignedDirection",
                "Reason",
                "StrictReason",
                "Empirical90PctReason",
                "SingleVehicleSupportReason",
                "RouteNameFallbackReason",
            ]
        )
    targets: list[dict[str, object]] = []
    for row in assignment_table.itertuples(index=False):
        if row.StrictUnanimousStatus != "assigned" and row.Empirical90PctStatus == "assigned":
            priority = 93 if bool(row.PrimaryHasConflict) else 84
            targets.append(
                {
                    "VariantName": EMPIRICAL_90_RULE_NAME,
                    "PriorityScore": priority,
                    "CorridorKey": row.CorridorKey,
                    "CorridorName": row.CorridorName,
                    "RTE_NM": row.RTE_NM,
                    "WindowFromMeasure": row.WindowFromMeasure,
                    "WindowToMeasure": row.WindowToMeasure,
                    "StudyRoad_RowID": int(row.StudyRoad_RowID),
                    "AssignedDirection": row.Empirical90PctAssignedDirection,
                    "Reason": "strict baseline unresolved but 90% dominant-share empirical rule assigns",
                    "StrictReason": row.StrictUnanimousReason,
                    "Empirical90PctReason": row.Empirical90PctReason,
                    "SingleVehicleSupportReason": row.SingleVehicleSupportReason,
                    "RouteNameFallbackReason": row.RouteNameFallbackReason,
                }
            )
        if row.StrictUnanimousStatus != "assigned" and row.SingleVehicleSupportStatus == "assigned":
            priority = 91 if row.SingleVehicleSupportActivation == "activated_against_broad_crash_conflict" else 82
            targets.append(
                {
                    "VariantName": SINGLE_VEHICLE_SUPPORT_RULE_NAME,
                    "PriorityScore": priority,
                    "CorridorKey": row.CorridorKey,
                    "CorridorName": row.CorridorName,
                    "RTE_NM": row.RTE_NM,
                    "WindowFromMeasure": row.WindowFromMeasure,
                    "WindowToMeasure": row.WindowToMeasure,
                    "StudyRoad_RowID": int(row.StudyRoad_RowID),
                    "AssignedDirection": row.SingleVehicleSupportAssignedDirection,
                    "Reason": "strict baseline unresolved but clean single-vehicle straight-ahead support assigns",
                    "StrictReason": row.StrictUnanimousReason,
                    "Empirical90PctReason": row.Empirical90PctReason,
                    "SingleVehicleSupportReason": row.SingleVehicleSupportReason,
                    "RouteNameFallbackReason": row.RouteNameFallbackReason,
                }
            )
        if (
            row.StrictUnanimousStatus != "assigned"
            and row.Empirical90PctStatus != "assigned"
            and row.RouteNameFallbackStatus == "assigned"
        ):
            priority = 89 if bool(row.PrimaryHasConflict) else 78
            targets.append(
                {
                    "VariantName": ROUTE_NAME_FALLBACK_RULE_NAME,
                    "PriorityScore": priority,
                    "CorridorKey": row.CorridorKey,
                    "CorridorName": row.CorridorName,
                    "RTE_NM": row.RTE_NM,
                    "WindowFromMeasure": row.WindowFromMeasure,
                    "WindowToMeasure": row.WindowToMeasure,
                    "StudyRoad_RowID": int(row.StudyRoad_RowID),
                    "AssignedDirection": row.RouteNameFallbackAssignedDirection,
                    "Reason": "strict and relaxed empirical rules unresolved; route-name fallback assigns",
                    "StrictReason": row.StrictUnanimousReason,
                    "Empirical90PctReason": row.Empirical90PctReason,
                    "SingleVehicleSupportReason": row.SingleVehicleSupportReason,
                    "RouteNameFallbackReason": row.RouteNameFallbackReason,
                }
            )
    if not targets:
        return pd.DataFrame(
            columns=[
                "VariantName",
                "PriorityScore",
                "CorridorKey",
                "CorridorName",
                "RTE_NM",
                "WindowFromMeasure",
                "WindowToMeasure",
                "StudyRoad_RowID",
                "AssignedDirection",
                "Reason",
                "StrictReason",
                "Empirical90PctReason",
                "SingleVehicleSupportReason",
                "RouteNameFallbackReason",
            ]
        )
    return pd.DataFrame(targets).sort_values(
        ["PriorityScore", "VariantName", "CorridorName", "WindowFromMeasure", "StudyRoad_RowID"],
        ascending=[False, True, True, True, True],
    )


def _build_review_targets(assignment_table: pd.DataFrame, corridor_summary: pd.DataFrame) -> pd.DataFrame:
    targets: list[dict[str, object]] = []
    for row in corridor_summary.itertuples(index=False):
        if row.PrimaryContinuityStatus == "fragmented":
            priority = 100
            reason = "corridor-level fragmentation across assigned directions"
        elif row.PrimaryContinuityStatus == "assigned_with_gaps":
            priority = 85
            reason = "corridor-level assignment gaps remain unresolved"
        elif row.PrimaryContinuityStatus == "unresolved" and int(row.PrimaryFilteredQualifyingCount) > 0:
            priority = 82
            reason = "corridor stayed unresolved despite filtered qualifying crashes"
        elif int(row.SupportConflictAssignedRowCount) > 0:
            priority = 76
            reason = "roadway-context support conflicts with one or more assigned rows"
        else:
            continue
        targets.append(
            {
                "TargetLevel": "corridor",
                "PriorityScore": priority,
                "CorridorKey": row.CorridorKey,
                "CorridorName": row.CorridorName,
                "RTE_NM": row.RTE_NM,
                "WindowFromMeasure": row.WindowFromMeasure,
                "WindowToMeasure": row.WindowToMeasure,
                "StudyRoad_RowID": None,
                "Reason": reason,
                "PrimaryStatus": row.PrimaryContinuityStatus,
                "PrimaryAssignedDirection": row.PrimaryCorridorDirection,
            }
        )
    for row in assignment_table.itertuples(index=False):
        if bool(row.PrimaryHasConflict):
            priority = 95
            reason = "row-level filtered crash evidence conflicts internally"
        elif row.PrimaryStatus == "assigned" and row.RoadwayContextSupportRelation == "conflicts_with_primary":
            priority = 74
            reason = "assigned row conflicts with roadway-context support"
        elif row.PrimaryStatus == "unresolved" and int(row.PrimaryQualifyingCrashCount) > 0:
            priority = 72
            reason = "row stayed unresolved despite filtered qualifying crashes"
        elif row.PrimaryStatus == "assigned" and int(row.PrimaryQualifyingCrashCount) == PRIMARY_MIN_QUALIFYING_CRASHES:
            priority = 58
            reason = "assigned row rests on the minimum qualifying filtered crash count"
        else:
            continue
        targets.append(
            {
                "TargetLevel": "row",
                "PriorityScore": priority,
                "CorridorKey": row.CorridorKey,
                "CorridorName": row.CorridorName,
                "RTE_NM": row.RTE_NM,
                "WindowFromMeasure": row.WindowFromMeasure,
                "WindowToMeasure": row.WindowToMeasure,
                "StudyRoad_RowID": int(row.StudyRoad_RowID),
                "Reason": reason,
                "PrimaryStatus": row.PrimaryStatus,
                "PrimaryAssignedDirection": row.PrimaryAssignedDirection,
            }
        )
    if not targets:
        return pd.DataFrame(
            columns=[
                "TargetLevel",
                "PriorityScore",
                "CorridorKey",
                "CorridorName",
                "RTE_NM",
                "WindowFromMeasure",
                "WindowToMeasure",
                "StudyRoad_RowID",
                "Reason",
                "PrimaryStatus",
                "PrimaryAssignedDirection",
            ]
        )
    return pd.DataFrame(targets).sort_values(
        ["PriorityScore", "TargetLevel", "CorridorName", "WindowFromMeasure", "StudyRoad_RowID"],
        ascending=[False, True, True, True, True],
    )


def _scope_summary_payload(
    scope_name: str,
    corridor_source: str,
    assignment_table: pd.DataFrame,
    corridor_summary: pd.DataFrame,
    crash_review: gpd.GeoDataFrame,
    review_targets: pd.DataFrame,
    rule_comparison_summary: pd.DataFrame,
    variant_review_targets: pd.DataFrame,
) -> dict[str, object]:
    assigned_rows = int(assignment_table["PrimaryStatus"].eq("assigned").sum()) if not assignment_table.empty else 0
    unresolved_rows = int(assignment_table["PrimaryStatus"].eq("unresolved").sum()) if not assignment_table.empty else 0
    conflict_rows = int(assignment_table["PrimaryHasConflict"].sum()) if not assignment_table.empty else 0
    total_rows = max(int(len(assignment_table)), 1)
    support_agree = int(assignment_table["RoadwayContextSupportRelation"].eq("agrees_with_primary").sum()) if not assignment_table.empty else 0
    support_conflict = int(assignment_table["RoadwayContextSupportRelation"].eq("conflicts_with_primary").sum()) if not assignment_table.empty else 0
    return {
        "scope_name": scope_name,
        "corridor_source": corridor_source,
        "corridor_count": int(len(corridor_summary)),
        "study_road_row_count": int(len(assignment_table)),
        "signal_count": int(corridor_summary["SignalCount"].sum()) if not corridor_summary.empty else 0,
        "attached_crash_count": int(len(crash_review)),
        "crash_dot_only_parseable_count": int(crash_review["CrashDOTOnlyIncluded"].sum()) if not crash_review.empty else 0,
        "primary_filtered_qualifying_count": int(crash_review["PrimaryIncluded"].sum()) if not crash_review.empty else 0,
        "primary_assigned_row_count": assigned_rows,
        "primary_unresolved_row_count": unresolved_rows,
        "primary_conflict_row_count": conflict_rows,
        "primary_assigned_row_rate": round(assigned_rows / total_rows, 4),
        "primary_unresolved_row_rate": round(unresolved_rows / total_rows, 4),
        "primary_conflict_row_rate": round(conflict_rows / total_rows, 4),
        "continuity_status_counts": {
            key: int(value) for key, value in corridor_summary["PrimaryContinuityStatus"].value_counts().sort_index().items()
        } if not corridor_summary.empty else {},
        "support_agree_assigned_row_count": support_agree,
        "support_conflict_assigned_row_count": support_conflict,
        "review_target_count": int(len(review_targets)),
        "variant_review_target_count": int(len(variant_review_targets)),
        "rule_assigned_row_counts": {
            row.RuleName: int(row.AssignedRowCount) for row in rule_comparison_summary.itertuples(index=False)
        } if not rule_comparison_summary.empty else {},
        "rule_newly_assigned_vs_strict_counts": {
            row.RuleName: int(row.NewlyAssignedVsStrictCount) for row in rule_comparison_summary.itertuples(index=False)
        } if not rule_comparison_summary.empty else {},
    }


def _analyze_corridors(
    corridors: tuple[CorridorWindow, ...],
    roads: gpd.GeoDataFrame,
    signals: gpd.GeoDataFrame,
    crashes: gpd.GeoDataFrame,
) -> dict[str, object]:
    assignment_rows: list[dict[str, object]] = []
    baseline_crash_rows: list[dict[str, object]] = []
    baseline_context_rows: list[dict[str, object]] = []
    conflict_rows: list[dict[str, object]] = []
    corridor_rows: list[dict[str, object]] = []
    crash_review_rows: list[gpd.GeoDataFrame] = []

    for corridor in corridors:
        corridor_roads = _slice_overlap(
            roads,
            route_field="RTE_NM",
            from_field="FROM_MEASURE",
            to_field="TO_MEASURE",
            route_name=corridor.route_name,
            window_from_measure=corridor.window_from_measure,
            window_to_measure=corridor.window_to_measure,
        )
        corridor_road_ids = set(corridor_roads["StudyRoad_RowID"].astype(int).tolist())
        corridor_signals = signals.loc[
            signals["NearestRoad_RTE_NM"].eq(corridor.route_name)
            & signals["NearestRoad_RowID"].isin(corridor_road_ids)
            & pd.to_numeric(signals["NearestRoad_FROM_MEASURE"], errors="coerce").lt(corridor.window_to_measure)
            & pd.to_numeric(signals["NearestRoad_TO_MEASURE"], errors="coerce").gt(corridor.window_from_measure)
        ].copy()
        corridor_crashes = crashes.loc[
            crashes["RTE_NM"].eq(corridor.route_name)
            & _measure_mask(crashes["RNS_MP"], corridor.window_from_measure, corridor.window_to_measure, inclusive_upper=True)
        ].copy()
        route_suffix_direction = _parse_route_suffix_direction(corridor.route_name)

        for row_order, road_row in enumerate(corridor_roads.itertuples(index=False), start=1):
            start = float(road_row.WindowFromMeasure)
            end = float(road_row.WindowToMeasure)
            inclusive_upper = row_order == len(corridor_roads)
            road_crashes = corridor_crashes.loc[
                _measure_mask(corridor_crashes["RNS_MP"], start, end, inclusive_upper=inclusive_upper)
            ].copy()
            row_signals = corridor_signals.loc[corridor_signals["NearestRoad_RowID"].astype("Int64").eq(int(road_row.StudyRoad_RowID))].copy()
            crash_only_counts = (
                road_crashes.loc[road_crashes["CrashDOTOnlyIncluded"], "ParsedDirectionOfTravel"].value_counts().sort_index().to_dict()
            )
            primary_counts = (
                road_crashes.loc[road_crashes["PrimaryIncluded"], "ParsedDirectionOfTravel"].value_counts().sort_index().to_dict()
            )
            primary_result = _evaluate_direction_counts(
                primary_counts,
                min_qualifying_crashes=PRIMARY_MIN_QUALIFYING_CRASHES,
                method_name="primary_filtered_crash_dot",
                require_unanimity=True,
            )
            empirical_90_result = _evaluate_direction_counts(
                primary_counts,
                min_qualifying_crashes=PRIMARY_MIN_QUALIFYING_CRASHES,
                method_name=EMPIRICAL_90_RULE_NAME,
                dominant_share_threshold=EMPIRICAL_DOMINANT_SHARE_THRESHOLD,
            )
            crash_only_result = _evaluate_direction_counts(
                crash_only_counts,
                min_qualifying_crashes=PRIMARY_MIN_QUALIFYING_CRASHES,
                method_name="baseline_crash_dot_only",
                require_unanimity=True,
            )
            single_vehicle_support_result = _evaluate_direction_counts(
                primary_counts,
                min_qualifying_crashes=PRIMARY_MIN_QUALIFYING_CRASHES,
                method_name=SINGLE_VEHICLE_SUPPORT_RULE_NAME,
                dominant_share_threshold=SINGLE_VEHICLE_SUPPORT_DOMINANT_SHARE_THRESHOLD,
            )
            single_vehicle_support_activation = _single_vehicle_support_activation(
                crash_only_result,
                single_vehicle_support_result,
            )
            route_fallback_result = _route_name_fallback_result(
                corridor.route_name,
                road_row.RTE_COMMON,
                primary_result,
                empirical_90_result,
            )
            if route_suffix_direction is None:
                context_result = {
                    "Method": "baseline_roadway_context_only",
                    "Status": "unresolved",
                    "AssignedDirection": None,
                    "Reason": "route name carries no NB/SB/EB/WB suffix",
                }
            else:
                context_result = {
                    "Method": "baseline_roadway_context_only",
                    "Status": "assigned",
                    "AssignedDirection": route_suffix_direction,
                    "Reason": f"assigned from route-name suffix on {corridor.route_name}",
                }
            support_relation = _support_relation(
                primary_result["Status"],
                primary_result["AssignedDirection"],
                context_result["Status"],
                context_result["AssignedDirection"],
            )
            signal_labels = _build_signal_labels(row_signals) or " | ".join(corridor.selected_signals)
            assignment_rows.append(
                {
                    "ScopeName": corridor.scope_name,
                    "CorridorSource": corridor.corridor_source,
                    "CorridorKey": corridor.corridor_key,
                    "CorridorName": corridor.corridor_name,
                    "StudyRoad_RowID": int(road_row.StudyRoad_RowID),
                    "RowOrderWithinCorridor": int(row_order),
                    "RTE_NM": corridor.route_name,
                    "RTE_COMMON": road_row.RTE_COMMON,
                    "WindowFromMeasure": round(start, 4),
                    "WindowToMeasure": round(end, 4),
                    "WindowLengthMiles": round(end - start, 4),
                    "SignalCount": int(len(row_signals)),
                    "SignalLabels": signal_labels,
                    "PrimaryStatus": primary_result["Status"],
                    "PrimaryAssignedDirection": primary_result["AssignedDirection"],
                    "PrimaryQualifyingCrashCount": int(primary_result["QualifyingCrashCount"]),
                    "PrimaryDirectionCountsJson": primary_result["DirectionCountsJson"],
                    "PrimaryDominantDirection": primary_result["DominantDirection"],
                    "PrimaryDominantCount": int(primary_result["DominantCount"]),
                    "PrimaryDominantShare": primary_result["DominantShare"],
                    "PrimaryReason": primary_result["Reason"],
                    "PrimaryHasConflict": bool(int(primary_result["DistinctDirectionCount"]) > 1),
                    "StrictUnanimousStatus": primary_result["Status"],
                    "StrictUnanimousAssignedDirection": primary_result["AssignedDirection"],
                    "StrictUnanimousQualifyingCrashCount": int(primary_result["QualifyingCrashCount"]),
                    "StrictUnanimousDirectionCountsJson": primary_result["DirectionCountsJson"],
                    "StrictUnanimousDominantDirection": primary_result["DominantDirection"],
                    "StrictUnanimousDominantCount": int(primary_result["DominantCount"]),
                    "StrictUnanimousDominantShare": primary_result["DominantShare"],
                    "StrictUnanimousReason": primary_result["Reason"],
                    "Empirical90PctStatus": empirical_90_result["Status"],
                    "Empirical90PctAssignedDirection": empirical_90_result["AssignedDirection"],
                    "Empirical90PctQualifyingCrashCount": int(empirical_90_result["QualifyingCrashCount"]),
                    "Empirical90PctDirectionCountsJson": empirical_90_result["DirectionCountsJson"],
                    "Empirical90PctDominantDirection": empirical_90_result["DominantDirection"],
                    "Empirical90PctDominantCount": int(empirical_90_result["DominantCount"]),
                    "Empirical90PctDominantShare": empirical_90_result["DominantShare"],
                    "Empirical90PctReason": empirical_90_result["Reason"],
                    "Empirical90PctHasConflict": bool(int(empirical_90_result["DistinctDirectionCount"]) > 1),
                    "CrashDOTOnlyStatus": crash_only_result["Status"],
                    "CrashDOTOnlyAssignedDirection": crash_only_result["AssignedDirection"],
                    "CrashDOTOnlyQualifyingCrashCount": int(crash_only_result["QualifyingCrashCount"]),
                    "CrashDOTOnlyDirectionCountsJson": crash_only_result["DirectionCountsJson"],
                    "CrashDOTOnlyDominantDirection": crash_only_result["DominantDirection"],
                    "CrashDOTOnlyDominantCount": int(crash_only_result["DominantCount"]),
                    "CrashDOTOnlyDominantShare": crash_only_result["DominantShare"],
                    "CrashDOTOnlyReason": crash_only_result["Reason"],
                    "CrashDOTOnlyHasConflict": bool(int(crash_only_result["DistinctDirectionCount"]) > 1),
                    "SingleVehicleSupportStatus": single_vehicle_support_result["Status"],
                    "SingleVehicleSupportAssignedDirection": single_vehicle_support_result["AssignedDirection"],
                    "SingleVehicleSupportQualifyingCrashCount": int(single_vehicle_support_result["QualifyingCrashCount"]),
                    "SingleVehicleSupportDirectionCountsJson": single_vehicle_support_result["DirectionCountsJson"],
                    "SingleVehicleSupportDominantDirection": single_vehicle_support_result["DominantDirection"],
                    "SingleVehicleSupportDominantCount": int(single_vehicle_support_result["DominantCount"]),
                    "SingleVehicleSupportDominantShare": single_vehicle_support_result["DominantShare"],
                    "SingleVehicleSupportReason": single_vehicle_support_result["Reason"],
                    "SingleVehicleSupportActivated": single_vehicle_support_result["Status"] == "assigned"
                    and single_vehicle_support_activation.startswith("activated_"),
                    "SingleVehicleSupportActivation": single_vehicle_support_activation,
                    "RouteNameFallbackStatus": route_fallback_result["Status"],
                    "RouteNameFallbackAssignedDirection": route_fallback_result["AssignedDirection"],
                    "RouteNameFallbackReason": route_fallback_result["Reason"],
                    "RouteNameFallbackSource": route_fallback_result["Source"],
                    "RouteNameFallbackActivated": bool(route_fallback_result["Activated"]),
                    "RoadwayContextStatus": context_result["Status"],
                    "RoadwayContextAssignedDirection": context_result["AssignedDirection"],
                    "RoadwayContextReason": context_result["Reason"],
                    "RoadwayContextSupportRelation": support_relation,
                    **_direction_count_fields("Primary", primary_result["DirectionCounts"]),
                    **_direction_count_fields("StrictUnanimous", primary_result["DirectionCounts"]),
                    **_direction_count_fields("Empirical90Pct", empirical_90_result["DirectionCounts"]),
                    **_direction_count_fields("CrashDOTOnly", crash_only_result["DirectionCounts"]),
                    **_direction_count_fields("SingleVehicleSupport", single_vehicle_support_result["DirectionCounts"]),
                }
            )
            baseline_crash_rows.append(
                {
                    "ScopeName": corridor.scope_name,
                    "CorridorKey": corridor.corridor_key,
                    "CorridorName": corridor.corridor_name,
                    "StudyRoad_RowID": int(road_row.StudyRoad_RowID),
                    "RTE_NM": corridor.route_name,
                    "WindowFromMeasure": round(start, 4),
                    "WindowToMeasure": round(end, 4),
                    **{key: value for key, value in crash_only_result.items() if key not in {"Method", "DirectionCounts"}},
                    **_direction_count_fields("CrashDOTOnly", crash_only_result["DirectionCounts"]),
                }
            )
            baseline_context_rows.append(
                {
                    "ScopeName": corridor.scope_name,
                    "CorridorKey": corridor.corridor_key,
                    "CorridorName": corridor.corridor_name,
                    "StudyRoad_RowID": int(road_row.StudyRoad_RowID),
                    "RTE_NM": corridor.route_name,
                    "WindowFromMeasure": round(start, 4),
                    "WindowToMeasure": round(end, 4),
                    "Status": context_result["Status"],
                    "AssignedDirection": context_result["AssignedDirection"],
                    "Reason": context_result["Reason"],
                }
            )
            if int(primary_result["DistinctDirectionCount"]) > 1:
                conflict_rows.append(
                    {
                        "Method": STRICT_RULE_NAME,
                        "ScopeName": corridor.scope_name,
                        "CorridorKey": corridor.corridor_key,
                        "CorridorName": corridor.corridor_name,
                        "StudyRoad_RowID": int(road_row.StudyRoad_RowID),
                        "RTE_NM": corridor.route_name,
                        "WindowFromMeasure": round(start, 4),
                        "WindowToMeasure": round(end, 4),
                        "QualifyingCrashCount": int(primary_result["QualifyingCrashCount"]),
                        "DirectionCountsJson": primary_result["DirectionCountsJson"],
                        "DominantDirection": primary_result["DominantDirection"],
                        "DominantCount": int(primary_result["DominantCount"]),
                        "DominantShare": primary_result["DominantShare"],
                        "ResolutionStatus": primary_result["Status"],
                        "ResolutionReason": primary_result["Reason"],
                    }
                )
            if int(empirical_90_result["DistinctDirectionCount"]) > 1:
                conflict_rows.append(
                    {
                        "Method": EMPIRICAL_90_RULE_NAME,
                        "ScopeName": corridor.scope_name,
                        "CorridorKey": corridor.corridor_key,
                        "CorridorName": corridor.corridor_name,
                        "StudyRoad_RowID": int(road_row.StudyRoad_RowID),
                        "RTE_NM": corridor.route_name,
                        "WindowFromMeasure": round(start, 4),
                        "WindowToMeasure": round(end, 4),
                        "QualifyingCrashCount": int(empirical_90_result["QualifyingCrashCount"]),
                        "DirectionCountsJson": empirical_90_result["DirectionCountsJson"],
                        "DominantDirection": empirical_90_result["DominantDirection"],
                        "DominantCount": int(empirical_90_result["DominantCount"]),
                        "DominantShare": empirical_90_result["DominantShare"],
                        "ResolutionStatus": empirical_90_result["Status"],
                        "ResolutionReason": empirical_90_result["Reason"],
                    }
                )
            if int(crash_only_result["DistinctDirectionCount"]) > 1:
                conflict_rows.append(
                    {
                        "Method": "baseline_crash_dot_only",
                        "ScopeName": corridor.scope_name,
                        "CorridorKey": corridor.corridor_key,
                        "CorridorName": corridor.corridor_name,
                        "StudyRoad_RowID": int(road_row.StudyRoad_RowID),
                        "RTE_NM": corridor.route_name,
                        "WindowFromMeasure": round(start, 4),
                        "WindowToMeasure": round(end, 4),
                        "QualifyingCrashCount": int(crash_only_result["QualifyingCrashCount"]),
                        "DirectionCountsJson": crash_only_result["DirectionCountsJson"],
                        "DominantDirection": crash_only_result["DominantDirection"],
                        "DominantCount": int(crash_only_result["DominantCount"]),
                        "DominantShare": crash_only_result["DominantShare"],
                        "ResolutionStatus": crash_only_result["Status"],
                        "ResolutionReason": crash_only_result["Reason"],
                    }
                )
            if not road_crashes.empty:
                crash_rows = road_crashes.copy()
                crash_rows["ScopeName"] = corridor.scope_name
                crash_rows["CorridorSource"] = corridor.corridor_source
                crash_rows["CorridorKey"] = corridor.corridor_key
                crash_rows["CorridorName"] = corridor.corridor_name
                crash_rows["StudyRoad_RowID"] = int(road_row.StudyRoad_RowID)
                crash_rows["RowOrderWithinCorridor"] = int(row_order)
                crash_rows["PrimaryRowStatus"] = primary_result["Status"]
                crash_rows["PrimaryRowAssignedDirection"] = primary_result["AssignedDirection"]
                crash_rows["PrimaryRowHasConflict"] = bool(int(primary_result["DistinctDirectionCount"]) > 1)
                crash_rows["StrictUnanimousRowStatus"] = primary_result["Status"]
                crash_rows["StrictUnanimousRowAssignedDirection"] = primary_result["AssignedDirection"]
                crash_rows["Empirical90PctRowStatus"] = empirical_90_result["Status"]
                crash_rows["Empirical90PctRowAssignedDirection"] = empirical_90_result["AssignedDirection"]
                crash_rows["SingleVehicleSupportRowStatus"] = single_vehicle_support_result["Status"]
                crash_rows["SingleVehicleSupportRowAssignedDirection"] = single_vehicle_support_result["AssignedDirection"]
                crash_rows["RouteNameFallbackRowStatus"] = route_fallback_result["Status"]
                crash_rows["RouteNameFallbackRowAssignedDirection"] = route_fallback_result["AssignedDirection"]
                crash_rows["RoadwayContextAssignedDirection"] = context_result["AssignedDirection"]
                crash_rows["RoadwayContextSupportRelation"] = support_relation
                crash_rows["WindowFromMeasure"] = round(start, 4)
                crash_rows["WindowToMeasure"] = round(end, 4)
                crash_review_rows.append(crash_rows)
        corridor_assignment = pd.DataFrame([row for row in assignment_rows if row["CorridorKey"] == corridor.corridor_key]).sort_values(["RowOrderWithinCorridor"])
        continuity_summary = _corridor_continuity_summary(corridor_assignment)
        corridor_rows.append(
            {
                "ScopeName": corridor.scope_name,
                "CorridorSource": corridor.corridor_source,
                "CorridorKey": corridor.corridor_key,
                "CorridorName": corridor.corridor_name,
                "RTE_NM": corridor.route_name,
                "WindowFromMeasure": round(corridor.window_from_measure, 4),
                "WindowToMeasure": round(corridor.window_to_measure, 4),
                "StudyRoadRowCount": int(len(corridor_roads)),
                "SignalCount": int(len(corridor_signals)),
                "SelectedSignalBucket": " | ".join(corridor.selected_signals),
                "TotalCrashCount": int(len(corridor_crashes)),
                "CrashDOTOnlyParseableCount": int(corridor_crashes["CrashDOTOnlyIncluded"].sum()),
                "PrimaryFilteredQualifyingCount": int(corridor_crashes["PrimaryIncluded"].sum()),
                "PrimaryAssignedRowCount": int(corridor_assignment["PrimaryStatus"].eq("assigned").sum()),
                "PrimaryUnresolvedRowCount": int(corridor_assignment["PrimaryStatus"].ne("assigned").sum()),
                "PrimaryConflictRowCount": int(corridor_assignment["PrimaryHasConflict"].sum()),
                "RouteSuffixBaselineDirection": route_suffix_direction,
                "SupportAgreementAssignedRowCount": int(corridor_assignment["RoadwayContextSupportRelation"].eq("agrees_with_primary").sum()),
                "SupportConflictAssignedRowCount": int(corridor_assignment["RoadwayContextSupportRelation"].eq("conflicts_with_primary").sum()),
                "SupportNoContextAssignedRowCount": int(corridor_assignment["RoadwayContextSupportRelation"].eq("no_support_context").sum()),
                **continuity_summary,
            }
        )

    assignment_table = pd.DataFrame(assignment_rows).sort_values(["CorridorName", "WindowFromMeasure", "WindowToMeasure", "StudyRoad_RowID"])
    corridor_summary = pd.DataFrame(corridor_rows).sort_values(["CorridorName", "WindowFromMeasure"])
    conflict_summary = pd.DataFrame(conflict_rows).sort_values(["Method", "CorridorName", "WindowFromMeasure", "WindowToMeasure"])
    baseline_crash_summary = pd.DataFrame(baseline_crash_rows).sort_values(["CorridorName", "WindowFromMeasure", "WindowToMeasure"])
    baseline_context_summary = pd.DataFrame(baseline_context_rows).sort_values(["CorridorName", "WindowFromMeasure", "WindowToMeasure"])
    assignment_table = _apply_review_support_fields(assignment_table)
    reason_summary = _build_reason_summary(assignment_table)
    rule_comparison_summary = _build_rule_comparison_summary(assignment_table)
    rule_transition_summary = _build_rule_transition_summary(assignment_table)
    conflict_profile_summary = _build_conflict_profile_summary(assignment_table)
    review_support_bucket_summary = _build_review_support_bucket_summary(assignment_table)
    targeted_review_outputs = _build_targeted_review_outputs(assignment_table)
    review_targets = _build_review_targets(assignment_table, corridor_summary)
    variant_review_targets = _build_variant_review_targets(assignment_table)
    review_support_summary_markdown = _build_review_support_summary_markdown(assignment_table, targeted_review_outputs)

    road_review = roads.merge(
        assignment_table,
        on=["StudyRoad_RowID", "RTE_NM", "RTE_COMMON"],
        how="inner",
    )
    road_review = gpd.GeoDataFrame(road_review, geometry="geometry", crs=roads.crs)
    signal_review = signals.merge(
        assignment_table[
            [
                "ScopeName",
                "CorridorSource",
                "CorridorKey",
                "CorridorName",
                "StudyRoad_RowID",
                "RowOrderWithinCorridor",
                "PrimaryStatus",
                "PrimaryAssignedDirection",
                "PrimaryQualifyingCrashCount",
                "PrimaryReason",
                "PrimaryHasConflict",
                "StrictUnanimousStatus",
                "StrictUnanimousAssignedDirection",
                "Empirical90PctStatus",
                "Empirical90PctAssignedDirection",
                "SingleVehicleSupportStatus",
                "SingleVehicleSupportAssignedDirection",
                "ConflictStrengthClass",
                "SingleVehicleSupportRelation",
                "RouteNameFallbackRelation",
                "ReviewPriorityClass",
                "ReviewPriorityScore",
                "ReviewPriorityReason",
                "RouteNameFallbackStatus",
                "RouteNameFallbackAssignedDirection",
                "RoadwayContextAssignedDirection",
                "RoadwayContextSupportRelation",
            ]
        ].rename(columns={"StudyRoad_RowID": "NearestRoad_RowID"}),
        on="NearestRoad_RowID",
        how="inner",
    )
    signal_review = gpd.GeoDataFrame(signal_review, geometry="geometry", crs=signals.crs)
    crash_review = (
        gpd.GeoDataFrame(pd.concat(crash_review_rows, ignore_index=True), geometry="geometry", crs=crashes.crs)
        if crash_review_rows
        else gpd.GeoDataFrame(geometry=[], crs=crashes.crs)
    )
    return {
        "assignment_table": assignment_table,
        "corridor_summary": corridor_summary,
        "conflict_summary": conflict_summary,
        "baseline_crash_summary": baseline_crash_summary,
        "baseline_context_summary": baseline_context_summary,
        "reason_summary": reason_summary,
        "rule_comparison_summary": rule_comparison_summary,
        "rule_transition_summary": rule_transition_summary,
        "conflict_profile_summary": conflict_profile_summary,
        "review_support_bucket_summary": review_support_bucket_summary,
        "targeted_review_outputs": targeted_review_outputs,
        "review_targets": review_targets,
        "variant_review_targets": variant_review_targets,
        "review_support_summary_markdown": review_support_summary_markdown,
        "road_review": road_review,
        "signal_review": signal_review,
        "crash_review": crash_review,
        "scope_summary": _scope_summary_payload(
            corridors[0].scope_name if corridors else "empty_scope",
            corridors[0].corridor_source if corridors else "empty_scope",
            assignment_table,
            corridor_summary,
            crash_review,
            review_targets,
            rule_comparison_summary,
            variant_review_targets,
        ),
    }


def _build_corridor_review_layer(road_review: gpd.GeoDataFrame, corridor_summary: pd.DataFrame) -> gpd.GeoDataFrame:
    if road_review.empty or corridor_summary.empty:
        return gpd.GeoDataFrame(geometry=[], crs=road_review.crs)
    dissolved = road_review[["CorridorKey", "geometry"]].dissolve(by="CorridorKey").reset_index()
    corridor_layer = dissolved.merge(corridor_summary, on="CorridorKey", how="left")
    return gpd.GeoDataFrame(corridor_layer, geometry="geometry", crs=road_review.crs)


def _build_review_subset_layers(road_review: gpd.GeoDataFrame) -> dict[str, gpd.GeoDataFrame]:
    if road_review.empty:
        return {}
    layer_masks = {
        "review_highest_priority_rows": road_review["ReviewPriorityClass"].eq("highest"),
        "review_fallback_only_rows": road_review["IsFallbackOnlyAssignment"],
        "review_soft_conflict_90_plus_rows": road_review["ConflictStrengthClass"].eq("soft_conflict_90_plus"),
        "review_single_vehicle_clean_rows": road_review["IsSingleVehicleCleanBroaderConflict"],
    }
    layers: dict[str, gpd.GeoDataFrame] = {}
    for layer_name, mask in layer_masks.items():
        subset = road_review.loc[mask].copy()
        if subset.empty:
            continue
        layers[layer_name] = gpd.GeoDataFrame(subset, geometry="geometry", crs=road_review.crs)
    return layers


def _write_review_geopackage(
    output_dir: Path,
    road_review: gpd.GeoDataFrame,
    corridor_review: gpd.GeoDataFrame,
    signal_review: gpd.GeoDataFrame,
    crash_review: gpd.GeoDataFrame,
    extra_layers: dict[str, gpd.GeoDataFrame] | None = None,
) -> Path | None:
    if road_review.empty:
        return None
    review_dir = _output_subdir(output_dir, *REVIEW_GEOPACKAGE_CURRENT_SUBDIR)
    review_history_dir = _output_subdir(output_dir, *REVIEW_GEOPACKAGE_HISTORY_SUBDIR)
    gpkg_path = _prepare_output_path(review_dir / "expanded_review_layers.gpkg", history_dir=review_history_dir)
    if gpkg_path.exists():
        gpkg_path.unlink()
    first_layer = True
    try:
        layer_items = [
            ("road_rows", road_review),
            ("corridors", corridor_review),
            ("signals", signal_review),
            ("crashes", crash_review),
        ]
        if extra_layers:
            layer_items.extend(extra_layers.items())
        for layer_name, layer_frame in layer_items:
            if layer_frame is None or layer_frame.empty:
                continue
            layer_frame.to_file(
                gpkg_path,
                layer=layer_name,
                driver="GPKG",
                mode="w" if first_layer else "a",
            )
            first_layer = False
        return gpkg_path
    except Exception:  # pragma: no cover - environment-specific driver failure
        if gpkg_path.exists():
            try:
                gpkg_path.unlink()
            except PermissionError:
                pass
        return None


def _write_review_geojson_layers(
    output_dir: Path,
    road_review: gpd.GeoDataFrame,
    corridor_review: gpd.GeoDataFrame,
    signal_review: gpd.GeoDataFrame,
    crash_review: gpd.GeoDataFrame,
    extra_layers: dict[str, gpd.GeoDataFrame] | None = None,
) -> dict[str, str]:
    review_dir = _output_subdir(output_dir, *REVIEW_GEOJSON_CURRENT_SUBDIR)
    review_history_dir = _output_subdir(output_dir, *REVIEW_GEOJSON_HISTORY_SUBDIR)
    outputs: dict[str, str] = {}
    layer_items = [
        ("road_rows", road_review),
        ("corridors", corridor_review),
        ("signals", signal_review),
        ("crashes", crash_review),
    ]
    if extra_layers:
        layer_items.extend(extra_layers.items())
    for name, layer_frame in layer_items:
        if layer_frame is None or layer_frame.empty:
            continue
        path = _prepare_output_path(review_dir / f"{name}.geojson", history_dir=review_history_dir)
        layer_frame.to_file(path, driver="GeoJSON")
        outputs[f"expanded_review_{name}_geojson"] = str(path)
    return outputs


def _write_explore_html(
    output_dir: Path,
    road_review: gpd.GeoDataFrame,
    signal_review: gpd.GeoDataFrame,
    crash_review: gpd.GeoDataFrame,
) -> tuple[Path | None, dict[str, object]]:
    if road_review.empty:
        return None, {"status": "skipped", "reason": "no expanded road rows available"}
    if not _module_available("folium"):
        return None, {"status": "skipped", "reason": "folium is not installed"}
    review_dir = _output_subdir(output_dir, *REVIEW_CURRENT_SUBDIR)
    review_history_dir = _output_subdir(output_dir, *REVIEW_HISTORY_SUBDIR)
    html_path = _prepare_output_path(review_dir / "expanded_review_map.html", history_dir=review_history_dir)
    try:
        road_layer = road_review.to_crs(4326).copy()
        road_layer["ReviewStatus"] = road_layer["PrimaryStatus"]
        road_layer.loc[road_layer["PrimaryHasConflict"], "ReviewStatus"] = "conflict"
        road_layer.loc[
            road_layer["RoadwayContextSupportRelation"].eq("conflicts_with_primary")
            & road_layer["PrimaryStatus"].eq("assigned"),
            "ReviewStatus",
        ] = "assigned_support_conflict"
        review_map = road_layer.explore(
            column="ReviewStatus",
            categorical=True,
            categories=["assigned", "assigned_support_conflict", "conflict", "unresolved"],
            cmap=["#2b8cbe", "#d95f02", "#d7301f", "#9e9e9e"],
            legend=True,
            tooltip=["CorridorName", "StudyRoad_RowID", "PrimaryStatus", "PrimaryAssignedDirection", "PrimaryQualifyingCrashCount", "PrimaryReason"],
            style_kwds={"weight": 6},
            name="Expanded road rows",
        )
        if not signal_review.empty:
            signal_review.to_crs(4326).explore(
                m=review_map,
                color="#111111",
                marker_kwds={"radius": 4},
                tooltip=["CorridorName", "MAJ_NAME", "MINOR_NAME", "REG_SIGNAL_ID", "SIGNAL_NO"],
                name="Signals",
            )
        evidence_crashes = crash_review.loc[crash_review["PrimaryIncluded"] | crash_review["CrashDOTOnlyIncluded"]].copy()
        if not evidence_crashes.empty:
            evidence_crashes["ReviewCrashType"] = evidence_crashes["PrimaryIncluded"].map(lambda value: "primary_filtered" if bool(value) else "parseable_only")
            evidence_crashes.to_crs(4326).explore(
                m=review_map,
                column="ReviewCrashType",
                categorical=True,
                cmap=["#2166ac", "#fdae61"],
                marker_kwds={"radius": 3},
                tooltip=["CorridorName", "DOCUMENT_NBR", "ParsedDirectionOfTravel", "CrashFilterStatus", "PrimaryRowStatus"],
                name="Evidence crashes",
            )
        html_path.write_text(review_map.get_root().render(), encoding="utf-8")
        return html_path, {"status": "written", "path": str(html_path)}
    except Exception as exc:  # pragma: no cover - optional path only
        return None, {"status": "skipped", "reason": f"explore export failed: {exc}"}


def _build_output_layout_readme(output_files: dict[str, str], output_dir: Path) -> str:
    current_sections = [
        ("tables/current/initial_seed", (*TABLES_CURRENT_SUBDIR, "initial_seed")),
        ("tables/current/expanded_scope", (*TABLES_CURRENT_SUBDIR, "expanded_scope")),
        ("tables/current/expanded_scope/targeted_review", (*TABLES_CURRENT_SUBDIR, "expanded_scope", "targeted_review")),
        ("review/current", REVIEW_CURRENT_SUBDIR),
        ("review/geojson/current", REVIEW_GEOJSON_CURRENT_SUBDIR),
        ("review/geopackage/current", REVIEW_GEOPACKAGE_CURRENT_SUBDIR),
        ("runs/current", RUNS_CURRENT_SUBDIR),
    ]
    lines = [
        "# Directionality Experiment Outputs",
        "",
        "This output folder is organized so active deliverables stay separate from older timestamped files and lock-fallback writes.",
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
            "- `tables/history/`, `review/history/`, `review/geojson/history/`, `review/geopackage/history/`, and `runs/history/` preserve older timestamped outputs and lock-fallback writes.",
            "- Files in `current/` are the stable active paths future runs will try to replace.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_directionality_experiment() -> int:
    config = load_runtime_config()
    output_dir = config.output_dir / OUTPUT_FOLDER_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    initial_current_dir = _output_subdir(output_dir, *TABLES_CURRENT_SUBDIR, "initial_seed")
    initial_history_dir = _output_subdir(output_dir, *TABLES_HISTORY_SUBDIR, "initial_seed")
    expanded_current_dir = _output_subdir(output_dir, *TABLES_CURRENT_SUBDIR, "expanded_scope")
    expanded_history_dir = _output_subdir(output_dir, *TABLES_HISTORY_SUBDIR, "expanded_scope")
    targeted_current_dir = _output_subdir(output_dir, *TABLES_CURRENT_SUBDIR, "expanded_scope", "targeted_review")
    targeted_history_dir = _output_subdir(output_dir, *TABLES_HISTORY_SUBDIR, "expanded_scope", "targeted_review")
    review_current_dir = _output_subdir(output_dir, *REVIEW_CURRENT_SUBDIR)
    review_history_dir = _output_subdir(output_dir, *REVIEW_HISTORY_SUBDIR)
    runs_current_dir = _output_subdir(output_dir, *RUNS_CURRENT_SUBDIR)
    runs_history_dir = _output_subdir(output_dir, *RUNS_HISTORY_SUBDIR)

    roads = _load_study_roads(config)
    signals = _load_signals(config)
    crashes = _load_crashes(config)
    initial_result = _analyze_corridors(INITIAL_CORRIDORS, roads, signals, crashes)
    expanded_corridors = _build_expanded_corridors(roads, signals)
    expanded_result = _analyze_corridors(expanded_corridors, roads, signals, crashes)

    output_files = {
        "assignment_table": str(
            _write_csv_frame(
                initial_result["assignment_table"],
                initial_current_dir / "assignment_table.csv",
                history_dir=initial_history_dir,
            )
        ),
        "evidence_summary": str(
            _write_csv_frame(
                initial_result["corridor_summary"],
                initial_current_dir / "evidence_summary.csv",
                history_dir=initial_history_dir,
            )
        ),
        "conflict_summary": str(
            _write_csv_frame(
                initial_result["conflict_summary"],
                initial_current_dir / "conflict_summary.csv",
                history_dir=initial_history_dir,
            )
        ),
        "baseline_crash_dot_only": str(
            _write_csv_frame(
                initial_result["baseline_crash_summary"],
                initial_current_dir / "baseline_crash_dot_only.csv",
                history_dir=initial_history_dir,
            )
        ),
        "baseline_roadway_context_only": str(
            _write_csv_frame(
                initial_result["baseline_context_summary"],
                initial_current_dir / "baseline_roadway_context_only.csv",
                history_dir=initial_history_dir,
            )
        ),
        "expanded_assignment_table": str(
            _write_csv_frame(
                expanded_result["assignment_table"],
                expanded_current_dir / "expanded_assignment_table.csv",
                history_dir=expanded_history_dir,
            )
        ),
        "expanded_corridor_summary": str(
            _write_csv_frame(
                expanded_result["corridor_summary"],
                expanded_current_dir / "expanded_corridor_summary.csv",
                history_dir=expanded_history_dir,
            )
        ),
        "expanded_conflict_summary": str(
            _write_csv_frame(
                expanded_result["conflict_summary"],
                expanded_current_dir / "expanded_conflict_summary.csv",
                history_dir=expanded_history_dir,
            )
        ),
        "expanded_reason_summary": str(
            _write_csv_frame(
                expanded_result["reason_summary"],
                expanded_current_dir / "expanded_reason_summary.csv",
                history_dir=expanded_history_dir,
            )
        ),
        "expanded_rule_comparison_summary": str(
            _write_csv_frame(
                expanded_result["rule_comparison_summary"],
                expanded_current_dir / "expanded_rule_comparison_summary.csv",
                history_dir=expanded_history_dir,
            )
        ),
        "expanded_rule_transition_summary": str(
            _write_csv_frame(
                expanded_result["rule_transition_summary"],
                expanded_current_dir / "expanded_rule_transition_summary.csv",
                history_dir=expanded_history_dir,
            )
        ),
        "expanded_conflict_profile_summary": str(
            _write_csv_frame(
                expanded_result["conflict_profile_summary"],
                expanded_current_dir / "expanded_conflict_profile_summary.csv",
                history_dir=expanded_history_dir,
            )
        ),
        "expanded_review_support_bucket_summary": str(
            _write_csv_frame(
                expanded_result["review_support_bucket_summary"],
                expanded_current_dir / "expanded_review_support_bucket_summary.csv",
                history_dir=expanded_history_dir,
            )
        ),
        "expanded_review_targets": str(
            _write_csv_frame(
                expanded_result["review_targets"],
                expanded_current_dir / "expanded_review_targets.csv",
                history_dir=expanded_history_dir,
            )
        ),
        "expanded_variant_review_targets": str(
            _write_csv_frame(
                expanded_result["variant_review_targets"],
                expanded_current_dir / "expanded_variant_review_targets.csv",
                history_dir=expanded_history_dir,
            )
        ),
        "expanded_attached_crashes": str(
            _write_csv_frame(
                pd.DataFrame(expanded_result["crash_review"].drop(columns="geometry", errors="ignore")),
                expanded_current_dir / "expanded_attached_crashes.csv",
                history_dir=expanded_history_dir,
            )
        ),
        "expanded_review_support_summary": str(
            _write_text_file(
                expanded_result["review_support_summary_markdown"],
                review_current_dir / "review_support_summary.md",
                history_dir=review_history_dir,
            )
        ),
    }
    for output_name, frame in expanded_result["targeted_review_outputs"].items():
        output_files[f"expanded_{output_name}"] = str(
            _write_csv_frame(
                frame,
                targeted_current_dir / f"{output_name}.csv",
                history_dir=targeted_history_dir,
            )
        )

    expanded_corridor_review = _build_corridor_review_layer(expanded_result["road_review"], expanded_result["corridor_summary"])
    expanded_subset_layers = _build_review_subset_layers(expanded_result["road_review"])
    review_gpkg_path = _write_review_geopackage(
        output_dir,
        expanded_result["road_review"],
        expanded_corridor_review,
        expanded_result["signal_review"],
        expanded_result["crash_review"],
        expanded_subset_layers,
    )
    if review_gpkg_path is not None:
        output_files["expanded_review_gpkg"] = str(review_gpkg_path)
    else:
        output_files.update(
            _write_review_geojson_layers(
                output_dir,
                expanded_result["road_review"],
                expanded_corridor_review,
                expanded_result["signal_review"],
                expanded_result["crash_review"],
                expanded_subset_layers,
            )
        )
    review_html_path, html_status = _write_explore_html(
        output_dir,
        expanded_result["road_review"],
        expanded_result["signal_review"],
        expanded_result["crash_review"],
    )
    if review_html_path is not None:
        output_files["expanded_review_html"] = str(review_html_path)

    run_summary = {
        "interpreter": sys.executable,
        "output_dir": str(output_dir),
        "assignment_rule": {
            "status": "strict baseline assigns only when at least two qualifying crashes remain after filtering and all qualifying crashes agree on one parsed cardinal direction",
            "minimum_qualifying_crashes": PRIMARY_MIN_QUALIFYING_CRASHES,
            "required_vehicle_count": 1,
            "required_vehicle_maneuver_type_cd": PRIMARY_MANEUVER,
            "direction_parsing": "one clear parsed cardinal direction only; reject blank, n/a, or conflicting semicolon-coded values",
            "attachment_rule": "exact RTE_NM plus non-duplicating study-road measure interval attachment; row windows use [from,to) except the final row in a corridor uses [from,to]",
            "method_posture": "filtered empirical crash evidence is primary; roadway context is support-only; unresolved remains acceptable",
            "comparison_variants": {
                EMPIRICAL_90_RULE_NAME: {
                    "minimum_qualifying_crashes": PRIMARY_MIN_QUALIFYING_CRASHES,
                    "dominant_share_threshold": EMPIRICAL_DOMINANT_SHARE_THRESHOLD,
                    "evidence": "same filtered empirical crash subset as the strict baseline",
                },
                SINGLE_VEHICLE_SUPPORT_RULE_NAME: {
                    "minimum_qualifying_crashes": PRIMARY_MIN_QUALIFYING_CRASHES,
                    "dominant_share_threshold": SINGLE_VEHICLE_SUPPORT_DOMINANT_SHARE_THRESHOLD,
                    "evidence": "same single-vehicle straight-ahead filtered crash subset, exposed explicitly as a support readout",
                    "activation_note": "reported separately to show where the clean subset helps despite broader crash-dot noise",
                },
                ROUTE_NAME_FALLBACK_RULE_NAME: {
                    "activation_rule": f"only after {EMPIRICAL_90_RULE_NAME} stays unresolved",
                    "evidence": "route-name suffix or route-common token support only",
                },
            },
        },
        "expanded_scope": {
            "selection_rule": "all contiguous signal-adjacent divided-road route windows built from Study_Signals_NearestRoad and Study_Roads_Divided",
            "minimum_signals_per_corridor": EXPANDED_MIN_SIGNALS_PER_CORRIDOR,
            "contiguity_gap_tolerance_miles": CONTIGUITY_GAP_TOLERANCE,
        },
        "initial_seed_summary": initial_result["scope_summary"],
        "expanded_sample_summary": expanded_result["scope_summary"],
        "expanded_review_export": "geopackage" if review_gpkg_path is not None else "geojson_fallback",
        "expanded_review_html": html_status,
        "review_support": {
            "targeted_output_count": int(len(expanded_result["targeted_review_outputs"])),
            "highest_priority_row_count": int(expanded_result["assignment_table"]["ReviewPriorityClass"].eq("highest").sum()),
            "fallback_only_assignment_count": int(expanded_result["assignment_table"]["IsFallbackOnlyAssignment"].sum()),
        },
        "output_files": output_files,
    }
    run_summary_path = _write_json_object(
        run_summary,
        runs_current_dir / "run_summary.json",
        history_dir=runs_history_dir,
    )
    output_files["run_summary"] = str(run_summary_path)
    output_files["readme"] = str(
        _write_text_file(
            _build_output_layout_readme(output_files, output_dir),
            output_dir / "README.md",
        )
    )
    print(json.dumps(run_summary, indent=2))
    return 0


def main() -> int:
    return run_directionality_experiment()


if __name__ == "__main__":
    raise SystemExit(main())
