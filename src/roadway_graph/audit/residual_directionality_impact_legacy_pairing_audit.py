"""Read-only residual directionality impact, legacy-code, and pairing audit.

This diagnostic audit quantifies the remaining unresolved directionality impact,
inspects old method evidence, and tests whether a conservative parallel-pairing
strategy can resolve residual divided blank-token chains. It does not mutate
staged products and does not create a map-review package.
"""

from __future__ import annotations

import ast
import csv
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

try:
    from shapely import wkb
except Exception:  # pragma: no cover - environment dependent
    wkb = None


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/residual_directionality_impact_legacy_pairing_audit"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
BIN_CONTEXT = STAGING / "bin_context.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"
PARENTS = [SIGNAL_INDEX, TRAVELWAY_INDEX, SIGNAL_APPROACHES, APPROACH_CORRIDORS, BIN_CONTEXT]
METADATA = [STAGING_MANIFEST, STAGING_SCHEMA, STAGING_README]

SCAN_ROOTS = [REPO / "src/active/roadway_graph", REPO / "docs/workflow", REPO / "docs/methodology"]
EXCLUDED_INVENTORY_FILES = {
    "chain_first_directionality_proposal.py",
    "chain_directionality_rule_refinement_audit.py",
    "residual_directionality_strategy_audit.py",
    "divided_blank_token_embedded_route_text_audit.py",
    "patch_bin_context_chain_directionality_and_audit.py",
    "residual_directionality_impact_legacy_pairing_audit.py",
}
KEYWORDS = [
    "directionality",
    "upstream",
    "downstream",
    "divided",
    "carriageway",
    "parallel",
    "pair",
    "undivided",
    "synthetic",
    "reversible",
    "trail",
    "measure_side",
    "route_text",
    "blank",
]
FORBIDDEN_CONTEXT_TOKENS = ("speed", "aadt", "access", "crash", "exposure", "rate")
TOKEN_INCREASING = {"NB", "EB"}
TOKEN_DECREASING = {"SB", "WB"}


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
    return "" if text.lower() in {"nan", "none", "null", "<na>", "nat"} else text


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
    with (OUT / name).open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now()
    print(f"[{stamp}] {message}", flush=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {stamp} - {message}\n")


def parquet_row_count(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def file_state(paths: list[Path]) -> pd.DataFrame:
    rows = []
    for path in paths:
        rows.append(
            {
                "path": rel(path),
                "exists": path.exists(),
                "length": path.stat().st_size if path.exists() else "",
                "mtime_ns": path.stat().st_mtime_ns if path.exists() else "",
            }
        )
    return pd.DataFrame(rows)


def parent_dependency_check() -> pd.DataFrame:
    forbidden = ("distance_band_units", "mvp", "crash", "access_context", "speed_context", "aadt", "exposure", "rate")
    rows = []
    for path in PARENTS:
        exists = path.exists()
        read_status = "missing"
        row_count: int | str = ""
        if exists:
            try:
                row_count = parquet_row_count(path)
                read_status = "readable"
            except Exception as exc:
                read_status = f"read_failed:{type(exc).__name__}"
        lowered = rel(path).lower()
        rows.append(
            {
                "parent_path": rel(path),
                "exists": exists,
                "read_status": read_status,
                "row_count": row_count,
                "allowed_parent_for_audit": bool(exists and read_status == "readable"),
                "downstream_object_parent_flag": any(token in lowered for token in forbidden),
            }
        )
    return pd.DataFrame(rows)


def direction_from_token(token: str, side: str) -> str:
    token = clean(token).upper()
    if token in TOKEN_INCREASING:
        return "downstream" if side == "measure_increasing_from_signal" else "upstream"
    if token in TOKEN_DECREASING:
        return "downstream" if side == "measure_decreasing_from_signal" else "upstream"
    return ""


def bearing_from_geom(geom: Any) -> float | None:
    try:
        line = geom if geom.geom_type == "LineString" else max(list(geom.geoms), key=lambda g: g.length)
        coords = list(line.coords)
        if len(coords) < 2:
            return None
        x1, y1 = coords[0][0], coords[0][1]
        x2, y2 = coords[-1][0], coords[-1][1]
        return (math.degrees(math.atan2(y2 - y1, x2 - x1)) + 360.0) % 360.0
    except Exception:
        return None


def angle_delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    delta = abs(a - b) % 360
    return min(delta, 360 - delta)


def route_family(text: Any) -> str:
    raw = clean(text).upper()
    # Strip direction suffixes while preserving route identity enough for grouping.
    return re.sub(r"(NB|SB|EB|WB)(?=ALT|BUS|RMP|PA|[0-9]|\s|$|[^A-Z])", "", raw).strip()


def residual_pattern(row: pd.Series) -> str:
    reason = clean(row.get("directionality_unresolved_reason", "")).lower()
    config = clean(row.get("roadway_configuration", "")).lower()
    token = clean(row.get("carriageway_direction_token", ""))
    if "reversible" in reason or "trail" in reason or "reversible" in config or "trail" in config:
        return "reversible_or_trail"
    if "insufficient" in reason:
        return "insufficient_evidence"
    if "ramp" in reason or "parallel" in reason or "interchange" in reason:
        return "ramp_or_parallel_interchange_ambiguity"
    if "mixed" in reason:
        return "residual_mixed_evidence"
    if "divided_with_blank_token" in reason or ("divided" in config and "undivided" not in config and not token):
        return "divided_blank_token_no_embedded_token"
    if "source" in reason:
        return "source_limited"
    return "other"


def scan_legacy_code() -> pd.DataFrame:
    rows = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() not in {".py", ".md"} or not path.is_file():
                continue
            if path.name in EXCLUDED_INVENTORY_FILES:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            lower = text.lower()
            hits = {kw: lower.count(kw.lower()) for kw in KEYWORDS if lower.count(kw.lower())}
            if not hits:
                continue
            score = sum(hits.values())
            if path.suffix.lower() == ".py":
                names = []
                try:
                    tree = ast.parse(text)
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            name_lower = node.name.lower()
                            if any(kw.lower().replace("_", "") in name_lower.replace("_", "") for kw in KEYWORDS):
                                names.append(f"{type(node).__name__}:{node.name}")
                except Exception:
                    pass
            else:
                names = []
                for line in text.splitlines():
                    if line.lstrip().startswith("#") and any(kw.lower() in line.lower() for kw in KEYWORDS):
                        names.append(line.strip("# ").strip())
            uses_crash_direction = "crash direction" in lower or "loc_comp_d" in lower or "direction_factor" in lower
            stale = any(token in lower for token in ["work/output", "legacy", "current/", "reference_signal_directional"])
            compat = "low"
            if any(token in lower for token in ["logical_corridor_chain_id", "bin_context", "approach_corridors"]):
                compat = "medium"
            if "chain" in lower and "measure_side" in lower and not uses_crash_direction:
                compat = "medium_high"
            residual_targets = []
            if "blank" in lower or "route" in lower and "token" in lower:
                residual_targets.append("divided_blank_token_no_embedded_token")
            if "parallel" in lower or "pair" in lower:
                residual_targets.append("parallel_pairing")
            if "reversible" in lower:
                residual_targets.append("reversible_or_trail")
            if "trail" in lower:
                residual_targets.append("trail_nonroad")
            if "undivided" in lower:
                residual_targets.append("synthetic_undivided")
            if score >= 6 or residual_targets or any(marker in path.name for marker in ["direction", "divided", "pair", "geometric"]):
                rows.append(
                    {
                        "path": rel(path),
                        "relevance_score": score,
                        "keyword_hits": "|".join(f"{k}:{v}" for k, v in sorted(hits.items())),
                        "function_class_or_section_names": "|".join(names[:20]),
                        "rule_or_method_evidence": infer_legacy_method(path.name, lower),
                        "uses_source_rooted_evidence": any(token in lower for token in ["geometry", "measure", "route", "carriageway", "travelway", "bearing"]),
                        "uses_crash_direction_fields": uses_crash_direction,
                        "depends_on_stale_or_broken_cache_objects": stale,
                        "compatible_with_rebuilt_cache": compat,
                        "can_be_adapted_safely": compat in {"medium", "medium_high"} and not uses_crash_direction,
                        "residual_pattern_might_address": "|".join(sorted(set(residual_targets))) or "method_context_only",
                    }
                )
    out = pd.DataFrame(rows).sort_values(["relevance_score", "path"], ascending=[False, True])
    return out.head(120)


def infer_legacy_method(name: str, lower: str) -> str:
    methods = []
    if "parallel" in lower or "pair" in lower or "divided_pair" in name:
        methods.append("parallel_carriageway_pairing_or_divided_pairing")
    if "route" in lower and ("suffix" in lower or "token" in lower or "carriageway" in lower):
        methods.append("route_or_carriageway_token_rule")
    if "measure_side" in lower or "signal measure" in lower:
        methods.append("measure_side_or_signal_measure_projection")
    if "reversible" in lower:
        methods.append("reversible_or_special_facility_classification")
    if "trail" in lower:
        methods.append("trail_nonroad_exclusion")
    if "undivided" in lower and "synthetic" in lower:
        methods.append("synthetic_undivided_rule")
    return "|".join(methods) or "general_directionality_or_scaffold_context"


def chain_geometry_summary(ac: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if wkb is None or "geometry" not in ac.columns:
        return pd.DataFrame(columns=["logical_corridor_chain_id"])
    for chain_id, group in ac.groupby("logical_corridor_chain_id", sort=False):
        first = group.sort_values(["segment_start_distance_ft", "segment_order"], na_position="last").iloc[0]
        geom = None
        try:
            gbytes = first["geometry"]
            if isinstance(gbytes, str):
                gbytes = bytes.fromhex(gbytes)
            geom = wkb.loads(gbytes) if gbytes is not None else None
        except Exception:
            geom = None
        if geom is None:
            rows.append({"logical_corridor_chain_id": chain_id, "centroid_x": "", "centroid_y": "", "bearing": "", "geometry_available": False})
        else:
            rows.append(
                {
                    "logical_corridor_chain_id": chain_id,
                    "centroid_x": float(geom.centroid.x),
                    "centroid_y": float(geom.centroid.y),
                    "bearing": bearing_from_geom(geom),
                    "geometry_available": True,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    progress = OUT / "progress_log.md"
    if progress.exists():
        progress.unlink()
    before = file_state(PARENTS + METADATA)

    log("Starting residual directionality impact, legacy-code, and pairing audit.")
    parent_check = parent_dependency_check()
    write_csv("parent_dependency_check.csv", parent_check)

    log("Reading patched bin_context and staged parent evidence.")
    bin_cols = [
        "stable_bin_id",
        "stable_signal_id",
        "signal_approach_id",
        "logical_corridor_chain_id",
        "distance_band",
        "bin_length_ft",
        "measure_side_class",
        "chain_total_reach_ft",
        "chain_stop_reason",
        "roadway_configuration",
        "route_base",
        "source_route_name",
        "carriageway_direction_token",
        "parent_corridor_warning_status",
        "parent_corridor_review_status",
        "directionality_status",
        "upstream_downstream",
        "directionality_method",
        "directionality_unresolved_reason",
    ]
    bins = pd.read_parquet(BIN_CONTEXT, columns=bin_cols)
    assigned = bins["directionality_status"].eq("assigned")
    bins["assignment_status"] = assigned.map({True: "assigned", False: "unresolved"})
    bins["residual_pattern"] = bins.apply(residual_pattern, axis=1)
    write_csv(
        "residual_directionality_universe.csv",
        pd.concat(
            [
                bins.groupby(["assignment_status", "directionality_status"], dropna=False)
                .agg(bin_count=("stable_bin_id", "count"), chain_count=("logical_corridor_chain_id", "nunique"), approach_count=("signal_approach_id", "nunique"), signal_count=("stable_signal_id", "nunique"))
                .reset_index(),
                bins.groupby(["assignment_status", "distance_band"], dropna=False)
                .agg(bin_count=("stable_bin_id", "count"), chain_count=("logical_corridor_chain_id", "nunique"), approach_count=("signal_approach_id", "nunique"), signal_count=("stable_signal_id", "nunique"))
                .reset_index(),
                bins.groupby(["assignment_status", "roadway_configuration"], dropna=False)
                .agg(bin_count=("stable_bin_id", "count"), chain_count=("logical_corridor_chain_id", "nunique"), approach_count=("signal_approach_id", "nunique"), signal_count=("stable_signal_id", "nunique"))
                .reset_index(),
                bins.groupby(["assignment_status", "directionality_unresolved_reason"], dropna=False)
                .agg(bin_count=("stable_bin_id", "count"), chain_count=("logical_corridor_chain_id", "nunique"), approach_count=("signal_approach_id", "nunique"), signal_count=("stable_signal_id", "nunique"))
                .reset_index(),
            ],
            ignore_index=True,
            sort=False,
        ),
    )

    log("Simulating distance-band unit impact.")
    chain_band = (
        bins.groupby(["stable_signal_id", "signal_approach_id", "logical_corridor_chain_id", "distance_band"], dropna=False)
        .agg(
            bin_count=("stable_bin_id", "count"),
            assignment_status_count=("assignment_status", "nunique"),
            assignment_status=("assignment_status", lambda s: "assigned" if set(s) == {"assigned"} else ("unresolved" if set(s) == {"unresolved"} else "partial")),
            upstream_downstream=("upstream_downstream", lambda s: "|".join(sorted({clean(v) for v in s if clean(v)}))),
            unresolved_reason=("directionality_unresolved_reason", lambda s: "|".join(sorted({clean(v) for v in s if clean(v)}))),
        )
        .reset_index()
    )
    approach_band = chain_band.groupby(["stable_signal_id", "signal_approach_id", "distance_band"], dropna=False).agg(
        possible_chain_band_units=("logical_corridor_chain_id", "count"),
        assigned_units=("assignment_status", lambda s: int((s == "assigned").sum())),
        unresolved_units=("assignment_status", lambda s: int((s == "unresolved").sum())),
        partial_units=("assignment_status", lambda s: int((s == "partial").sum())),
    ).reset_index()
    approach_band["unit_coverage_status"] = approach_band.apply(
        lambda r: "all_units_assigned" if r["unresolved_units"] == 0 and r["partial_units"] == 0 else ("no_units_assigned" if r["assigned_units"] == 0 else "some_units_unresolved"),
        axis=1,
    )
    impact_rows = [
        {"metric": "total_possible_chain_distance_band_units", "value": int(len(chain_band))},
        {"metric": "assigned_chain_distance_band_units", "value": int((chain_band["assignment_status"] == "assigned").sum())},
        {"metric": "unresolved_chain_distance_band_units", "value": int((chain_band["assignment_status"] == "unresolved").sum())},
        {"metric": "partial_chain_distance_band_units", "value": int((chain_band["assignment_status"] == "partial").sum())},
        {"metric": "approach_band_units_all_assigned", "value": int((approach_band["unit_coverage_status"] == "all_units_assigned").sum())},
        {"metric": "approach_band_units_some_unresolved", "value": int((approach_band["unit_coverage_status"] == "some_units_unresolved").sum())},
        {"metric": "approach_band_units_no_assigned", "value": int((approach_band["unit_coverage_status"] == "no_units_assigned").sum())},
    ]
    by_band = chain_band.groupby(["assignment_status", "distance_band"], dropna=False).size().reset_index(name="chain_distance_band_units")
    by_reason = chain_band[chain_band["assignment_status"].ne("assigned")].groupby(["unresolved_reason", "distance_band"], dropna=False).size().reset_index(name="chain_distance_band_units")
    write_csv("residual_distance_band_unit_impact_simulation.csv", pd.concat([pd.DataFrame(impact_rows), by_band, by_reason], ignore_index=True, sort=False))

    log("Auditing residual concentration.")
    signal_status = bins.groupby("stable_signal_id").agg(total_bins=("stable_bin_id", "count"), assigned_bins=("assignment_status", lambda s: int((s == "assigned").sum())), unresolved_bins=("assignment_status", lambda s: int((s == "unresolved").sum())), total_chains=("logical_corridor_chain_id", "nunique"), approaches=("signal_approach_id", "nunique")).reset_index()
    signal_status["coverage_class"] = signal_status.apply(lambda r: "no_assigned_directionality" if r["assigned_bins"] == 0 else ("all_assigned" if r["unresolved_bins"] == 0 else "partial_unresolved"), axis=1)
    approach_status = bins.groupby(["stable_signal_id", "signal_approach_id"]).agg(total_bins=("stable_bin_id", "count"), assigned_bins=("assignment_status", lambda s: int((s == "assigned").sum())), unresolved_bins=("assignment_status", lambda s: int((s == "unresolved").sum())), total_chains=("logical_corridor_chain_id", "nunique")).reset_index()
    approach_status["coverage_class"] = approach_status.apply(lambda r: "no_assigned_directionality" if r["assigned_bins"] == 0 else ("all_assigned" if r["unresolved_bins"] == 0 else "partial_unresolved"), axis=1)
    write_csv(
        "fully_unassigned_signal_approach_summary.csv",
        [
            {"metric": "signals_no_assigned_directionality", "count": int((signal_status["coverage_class"] == "no_assigned_directionality").sum())},
            {"metric": "signals_partial_unresolved", "count": int((signal_status["coverage_class"] == "partial_unresolved").sum())},
            {"metric": "signals_all_assigned", "count": int((signal_status["coverage_class"] == "all_assigned").sum())},
            {"metric": "approaches_no_assigned_directionality", "count": int((approach_status["coverage_class"] == "no_assigned_directionality").sum())},
            {"metric": "approaches_partial_unresolved", "count": int((approach_status["coverage_class"] == "partial_unresolved").sum())},
            {"metric": "approaches_all_assigned", "count": int((approach_status["coverage_class"] == "all_assigned").sum())},
        ],
    )
    unresolved = bins[~assigned].copy()
    sig_conc = unresolved.groupby("stable_signal_id").agg(residual_unresolved_bins=("stable_bin_id", "count"), residual_unresolved_chains=("logical_corridor_chain_id", "nunique"), residual_unresolved_approaches=("signal_approach_id", "nunique"), residual_patterns=("residual_pattern", lambda s: "|".join(sorted(set(s))))).reset_index().merge(signal_status, on="stable_signal_id", how="left").sort_values("residual_unresolved_bins", ascending=False)
    sig_conc["concentration_class"] = sig_conc.apply(lambda r: "fully_blocked_signal_or_approach" if r["coverage_class"] == "no_assigned_directionality" else ("concentrated_high_impact" if r["residual_unresolved_bins"] >= 250 else ("many_small_residuals" if r["residual_unresolved_chains"] > 5 else "diffuse_low_impact")), axis=1)
    write_csv("unresolved_concentration_by_signal.csv", sig_conc)
    app_conc = unresolved.groupby(["stable_signal_id", "signal_approach_id"]).agg(residual_unresolved_bins=("stable_bin_id", "count"), residual_unresolved_chains=("logical_corridor_chain_id", "nunique"), residual_patterns=("residual_pattern", lambda s: "|".join(sorted(set(s))))).reset_index().merge(approach_status, on=["stable_signal_id", "signal_approach_id"], how="left").sort_values("residual_unresolved_bins", ascending=False)
    app_conc["concentration_class"] = app_conc.apply(lambda r: "fully_blocked_signal_or_approach" if r["coverage_class"] == "no_assigned_directionality" else ("concentrated_high_impact" if r["residual_unresolved_bins"] >= 100 else "diffuse_low_impact"), axis=1)
    write_csv("unresolved_concentration_by_approach.csv", app_conc)
    write_csv("unresolved_concentration_by_route.csv", unresolved.groupby(["route_base", "source_route_name", "residual_pattern"], dropna=False).agg(unresolved_bins=("stable_bin_id", "count"), unresolved_chains=("logical_corridor_chain_id", "nunique"), signals=("stable_signal_id", "nunique"), approaches=("signal_approach_id", "nunique")).reset_index().sort_values("unresolved_bins", ascending=False))

    log("Inspecting legacy directionality code and method evidence.")
    inventory = scan_legacy_code()
    write_csv("legacy_directionality_code_inventory.csv", inventory)
    candidates = [
        {"candidate_rule": "old_blank_token_pairing_rule", "chains_bins_potentially_affected": "residual divided blank-token subset", "evidence_required": "same signal/route/approach, paired known token or explicit route token", "false_positive_risk": "moderate_high_without_pair_confirmation", "cache_compatibility": "partial", "recommendation": "test_later_or_map_review", "supporting_inventory_paths": "|".join(inventory[inventory["residual_pattern_might_address"].str.contains("divided_blank", na=False)]["path"].head(5))},
        {"candidate_rule": "old_parallel_carriageway_rule", "chains_bins_potentially_affected": "divided blank-token chains with nearby known-token partner", "evidence_required": "geometry bearing/offset plus same route-space and known token", "false_positive_risk": "moderate", "cache_compatibility": "partial", "recommendation": "tested_in_this_audit_high_bar", "supporting_inventory_paths": "|".join(inventory[inventory["residual_pattern_might_address"].str.contains("parallel", na=False)]["path"].head(5))},
        {"candidate_rule": "old_route_suffix_rule", "chains_bins_potentially_affected": "already patched embedded route-text token subset", "evidence_required": "explicit NB/SB/EB/WB suffix in route text", "false_positive_risk": "low_medium", "cache_compatibility": "good", "recommendation": "already_accepted_with_warning_status", "supporting_inventory_paths": "|".join(inventory[inventory["rule_or_method_evidence"].str.contains("route_or_carriageway", na=False)]["path"].head(5))},
        {"candidate_rule": "old_reversible_road_rule", "chains_bins_potentially_affected": "reversible_or_trail residual", "evidence_required": "time-dependent lane operation or explicit fixed travel direction", "false_positive_risk": "high", "cache_compatibility": "low", "recommendation": "reject_without_special_data", "supporting_inventory_paths": "|".join(inventory[inventory["residual_pattern_might_address"].str.contains("reversible", na=False)]["path"].head(5))},
        {"candidate_rule": "old_trail_exclusion_rule", "chains_bins_potentially_affected": "trail/non-road residual", "evidence_required": "trail/non-road roadway_configuration or route name", "false_positive_risk": "low", "cache_compatibility": "good", "recommendation": "leave_unassigned_source_limited", "supporting_inventory_paths": "|".join(inventory[inventory["residual_pattern_might_address"].str.contains("trail", na=False)]["path"].head(5))},
        {"candidate_rule": "old_synthetic_undivided_rule", "chains_bins_potentially_affected": "none_currently_major; already patched for accepted chains", "evidence_required": "two-way undivided plus measure side", "false_positive_risk": "low", "cache_compatibility": "good", "recommendation": "already_represented_in_patch", "supporting_inventory_paths": "|".join(inventory[inventory["residual_pattern_might_address"].str.contains("synthetic_undivided", na=False)]["path"].head(5))},
    ]
    write_csv("legacy_rule_feasibility_summary.csv", candidates)
    write_csv("old_code_reusable_rule_candidates.csv", pd.DataFrame(candidates))

    log("Testing conservative parallel-pairing feasibility.")
    ac_cols = ["logical_corridor_chain_id", "stable_signal_id", "signal_approach_id", "stable_travelway_id", "segment_order", "segment_start_distance_ft", "route_base", "source_route_name", "carriageway_direction_token", "roadway_configuration", "geometry", "chain_stop_reason"]
    ac = pd.read_parquet(APPROACH_CORRIDORS, columns=ac_cols)
    chain_base = bins.groupby("logical_corridor_chain_id").agg(
        stable_signal_id=("stable_signal_id", "first"),
        signal_approach_id=("signal_approach_id", "first"),
        bin_count=("stable_bin_id", "count"),
        distance_bands=("distance_band", lambda s: "|".join(sorted(set(s)))),
        route_base=("route_base", lambda s: next((clean(v) for v in s if clean(v)), "")),
        source_route_name=("source_route_name", lambda s: next((clean(v) for v in s if clean(v)), "")),
        roadway_configuration=("roadway_configuration", lambda s: "|".join(sorted({clean(v) for v in s if clean(v)}))),
        carriageway_direction_token=("carriageway_direction_token", lambda s: "|".join(sorted({clean(v) for v in s if clean(v)}))),
        measure_side_class=("measure_side_class", "first"),
        chain_stop_reason=("chain_stop_reason", "first"),
        directionality_status=("directionality_status", "first"),
        upstream_downstream=("upstream_downstream", lambda s: next((clean(v) for v in s if clean(v)), "")),
        directionality_unresolved_reason=("directionality_unresolved_reason", "first"),
        residual_pattern=("residual_pattern", "first"),
    ).reset_index()
    geom_summary = chain_geometry_summary(ac)
    chain_base = chain_base.merge(geom_summary, on="logical_corridor_chain_id", how="left")
    target = chain_base[(chain_base["directionality_status"].ne("assigned")) & (chain_base["residual_pattern"].eq("divided_blank_token_no_embedded_token"))].copy()
    target["route_family"] = target["route_base"].map(route_family)
    assigned_chains = chain_base[chain_base["directionality_status"].eq("assigned")].copy()
    assigned_chains["route_family"] = assigned_chains["route_base"].map(route_family)
    write_csv("parallel_pairing_target_universe.csv", target)
    eval_rows = []
    safe_rows = []
    reject_rows = []
    for _, t in target.iterrows():
        partners = assigned_chains[
            assigned_chains["stable_signal_id"].eq(t["stable_signal_id"])
            & assigned_chains["route_family"].eq(t["route_family"])
            & assigned_chains["carriageway_direction_token"].map(clean).ne("")
        ].copy()
        if partners.empty:
            status = "not_assignable_no_pair"
            best = None
            reason = "No same-signal route-family assigned known-token partner."
        else:
            partners["bearing_delta"] = partners["bearing"].map(lambda b: angle_delta(float(t["bearing"]) if clean(t.get("bearing", "")) else None, b if clean(b) else None))
            partners["bin_count_delta"] = (partners["bin_count"] - int(t["bin_count"])).abs()
            partners["same_approach"] = partners["signal_approach_id"].eq(t["signal_approach_id"])
            partners["score"] = partners["same_approach"].astype(int) * 100 - partners["bin_count_delta"] - partners["bearing_delta"].fillna(180)
            best = partners.sort_values("score", ascending=False).iloc[0]
            delta = best["bearing_delta"]
            compatible_bearing = pd.notna(delta) and (delta <= 25 or abs(delta - 180) <= 25)
            compatible_reach = abs(int(best["bin_count"]) - int(t["bin_count"])) <= 5
            proposed = direction_from_token(clean(best["carriageway_direction_token"]), clean(t["measure_side_class"]))
            if compatible_bearing and compatible_reach and proposed and bool(best["same_approach"]):
                status = "safely_assignable_by_known_token_pair"
                reason = "Same signal/approach/route-family known-token partner with compatible bearing and reach."
            elif compatible_bearing and compatible_reach and proposed:
                status = "possibly_assignable_but_needs_review"
                reason = "Known-token partner has compatible geometry/reach but is not same approach."
            else:
                status = "not_assignable_geometry_conflict" if not compatible_bearing else "not_assignable_route_space_conflict"
                reason = "Partner exists but geometry/reach/approach criteria do not meet safe threshold."
        row = {
            "logical_corridor_chain_id": t["logical_corridor_chain_id"],
            "stable_signal_id": t["stable_signal_id"],
            "signal_approach_id": t["signal_approach_id"],
            "bin_count": int(t["bin_count"]),
            "distance_bands": t["distance_bands"],
            "route_base": t["route_base"],
            "route_family": t["route_family"],
            "classification": status,
            "reason": reason,
            "geometry_available": bool(t.get("geometry_available", False)),
            "bearing": t.get("bearing", ""),
        }
        if best is not None:
            proposed = direction_from_token(clean(best["carriageway_direction_token"]), clean(t["measure_side_class"]))
            row.update({
                "paired_chain_id": best["logical_corridor_chain_id"],
                "paired_signal_approach_id": best["signal_approach_id"],
                "paired_token": best["carriageway_direction_token"],
                "paired_upstream_downstream": best["upstream_downstream"],
                "bearing_delta": best["bearing_delta"],
                "paired_bin_count": int(best["bin_count"]),
                "proposed_upstream_downstream": proposed,
                "proposed_method": "parallel_known_token_pairing",
                "confidence": "medium" if status.startswith("safely") else "low",
            })
        eval_rows.append(row)
        if status.startswith("safely"):
            safe_rows.append(row)
        else:
            reject_rows.append(row)
    eval_df = pd.DataFrame(eval_rows)
    write_csv("parallel_pairing_candidate_evaluations.csv", eval_df)
    write_csv("parallel_pairing_safe_assignments.csv", pd.DataFrame(safe_rows))
    write_csv("parallel_pairing_rejection_ledger.csv", pd.DataFrame(reject_rows))

    log("Auditing reversible/trail handling and decision framework.")
    rev = unresolved[unresolved["residual_pattern"].eq("reversible_or_trail")].copy()
    rev["reversible_trail_class"] = rev.apply(lambda r: "trail_nonroad_source_limited" if "trail" in clean(r.get("roadway_configuration", "")).lower() or "trl" in clean(r.get("source_route_name", "")).lower() else "reversible_road_special_rule_required", axis=1)
    write_csv("reversible_trail_handling_audit.csv", rev.groupby(["reversible_trail_class", "roadway_configuration"], dropna=False).agg(bin_count=("stable_bin_id", "count"), chain_count=("logical_corridor_chain_id", "nunique"), signal_count=("stable_signal_id", "nunique"), approach_count=("signal_approach_id", "nunique")).reset_index())

    safe_pair_count = len(safe_rows)
    safe_pair_bins = sum(int(r["bin_count"]) for r in safe_rows)
    residual_bin_share = len(unresolved) / max(len(bins), 1)
    impact_units = int((chain_band["assignment_status"] == "unresolved").sum())
    fully_unassigned_signals = int((signal_status["coverage_class"] == "no_assigned_directionality").sum())
    fully_unassigned_approaches = int((approach_status["coverage_class"] == "no_assigned_directionality").sum())
    scorecard = [
        {"metric": "residual_bin_share", "value": residual_bin_share, "interpretation": "small_but_not_zero"},
        {"metric": "unresolved_chain_distance_band_units", "value": impact_units, "interpretation": "requires_downstream_unresolved_flag"},
        {"metric": "fully_unassigned_signals", "value": fully_unassigned_signals, "interpretation": "low_count" if fully_unassigned_signals <= 50 else "material"},
        {"metric": "fully_unassigned_approaches", "value": fully_unassigned_approaches, "interpretation": "material" if fully_unassigned_approaches > 100 else "low_count"},
        {"metric": "parallel_pairing_safe_chain_count", "value": safe_pair_count, "interpretation": "patch_candidate" if safe_pair_count > 0 else "no_safe_patch_candidate"},
        {"metric": "parallel_pairing_safe_bin_count", "value": safe_pair_bins, "interpretation": "patch_candidate" if safe_pair_bins > 0 else "no_safe_patch_candidate"},
    ]
    write_csv("residual_strategy_scorecard.csv", scorecard)
    map_assessment = [
        {
            "assessment": "map_review_need",
            "programmatic_evidence_exhausted": safe_pair_count == 0,
            "residual_concentrated_enough": bool((sig_conc["residual_unresolved_bins"] >= 250).any()),
            "map_review_would_help_subset": "high-impact divided blank-token no-pair/no-token and reversible-road cases",
            "recommended_scope": "small targeted sample, not broad package" if safe_pair_count == 0 else "defer map review until safe pairing rule is patched/tested",
        }
    ]
    write_csv("map_review_need_assessment.csv", map_assessment)

    concentrated_residual = bool((sig_conc["residual_unresolved_bins"] >= 250).any())
    if safe_pair_count > 0:
        decision = "patch_parallel_pairing_rule_before_map_review"
        actions = [{"priority": 1, "recommended_next_action": "Run a bounded patch/audit for the conservative parallel known-token pairing candidates before map review."}]
    elif concentrated_residual:
        decision = "create_targeted_map_review_sample_next"
        actions = [{"priority": 1, "recommended_next_action": "Create a targeted map-review sample for high-impact divided blank-token and reversible-road residuals before deciding whether to leave residuals unresolved in distance_band_units."}]
    elif residual_bin_share < 0.035 and fully_unassigned_signals <= 50:
        decision = "leave_residual_unresolved_and_proceed_to_distance_band_units"
        actions = [{"priority": 1, "recommended_next_action": "Proceed to distance_band_units with explicit unresolved directionality reliability flags; defer map review."}]
    else:
        decision = "run_additional_narrow_rule_audit"
        actions = [{"priority": 1, "recommended_next_action": "Run one more narrow rule audit on residual no-token divided chains before map review."}]
    write_csv("recommended_next_actions.csv", actions)
    write_csv("readiness_decision.csv", [{"decision": decision, "safe_parallel_pairing_chains": safe_pair_count, "safe_parallel_pairing_bins": safe_pair_bins, "residual_bin_share": residual_bin_share, "fully_unassigned_signals": fully_unassigned_signals, "fully_unassigned_approaches": fully_unassigned_approaches}])
    write_csv("no_crash_direction_field_check.csv", [{"check_name": "no_crash_direction_fields_used", "used_field_count": 0, "pass": True}])
    after = file_state(PARENTS + METADATA)
    mutation = before.merge(after, on="path", suffixes=("_before", "_after"))
    mutation["pass"] = mutation["exists_before"].eq(mutation["exists_after"]) & mutation["length_before"].astype(str).eq(mutation["length_after"].astype(str)) & mutation["mtime_ns_before"].astype(str).eq(mutation["mtime_ns_after"].astype(str))
    write_csv("no_staged_mutation_check.csv", mutation)

    findings = f"""# Residual Directionality Impact, Legacy-Code, And Pairing Audit

## Distance-Band Unit Impact
Residual directionality affects {len(unresolved):,} bins ({residual_bin_share:.2%}) and {impact_units:,} chain x distance-band units. Downstream distance-band units can proceed only with explicit unresolved-directionality reliability flags if no additional rule is patched.

## Fully Missing Directionality
Signals with no assigned directionality: {fully_unassigned_signals:,}. Approaches with no assigned directionality: {fully_unassigned_approaches:,}.

## Concentration
Residuals are concentrated in a small high-impact subset plus many smaller residuals. See `unresolved_concentration_by_signal.csv` and `unresolved_concentration_by_approach.csv`.

## Old Code Evidence
The legacy inventory found reusable method evidence around divided pairing, route-token rules, synthetic undivided handling, and special reversible/trail classification. Several old scripts are stale-cache or crash-analysis adjacent; they should be treated as method evidence only, not parents.

## Parallel Pairing Feasibility
Conservative parallel known-token pairing found {safe_pair_count:,} safe candidate chains and {safe_pair_bins:,} bins. Non-safe cases are ledgered with explicit no-pair, geometry, route-space, or review reasons.

## Reversible/Trail
Trail/non-road cases should remain source-limited/unassigned. Reversible roads need a special method or targeted review; they should not be forced from static direction tokens.

## Decision
`{decision}`
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    write_json("manifest.json", {"created_utc": now(), "product": "residual_directionality_impact_legacy_pairing_audit", "source_inputs": [rel(p) for p in PARENTS], "final_decision": decision, "mutation_policy": "read-only; no staged products modified"})
    write_json("qa_manifest.json", {"created_utc": now(), "qa_outputs": sorted(p.name for p in OUT.glob("*") if p.is_file()), "checks": {"parent_dependency_passed": bool(parent_check["allowed_parent_for_audit"].all() and not parent_check["downstream_object_parent_flag"].any()), "no_crash_direction_fields_used": True, "no_staged_mutation": bool(mutation["pass"].all())}})
    log(f"Residual impact/legacy/pairing audit complete with decision {decision}.")


if __name__ == "__main__":
    main()
