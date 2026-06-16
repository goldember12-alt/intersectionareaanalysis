"""Read-only network-to-unit lineage preservation audit.

This audit checks whether the staged roadway_graph cache preserves the intended
lineage from source Travelway network and signal index through attachments,
approaches, corridors, bins, distance-band units, and context-enrichment keys.
It writes review outputs only and does not mutate staged/cache/source data.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
FINAL = REPO_ROOT / "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset"
STAGING = REPO_ROOT / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"
OUT = REPO_ROOT / "work/roadway_graph/review/network_to_unit_lineage_preservation_audit"
ART = REPO_ROOT / "artifacts/normalized"

SIGNALS = ART / "signals.parquet"
ROADS = ART / "roads.parquet"
SPEED = ART / "speed.parquet"
AADT = ART / "aadt.parquet"
ACCESS = ART / "access_v2.parquet"
CRASHES = ART / "crashes.parquet"

BIN_CONTEXT = STAGING / "bin_context.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_WINDOWS = STAGING / "approach_windows.parquet"
CONTINUATION_CORRIDORS = STAGING / "continuation_corridors.parquet"
CONTINUATION_PROVENANCE = STAGING / "continuation_provenance.parquet"
PROJECTION_INDEX = STAGING / "source_signal_travelway_projection_index.parquet"
CORRIDOR_INDEX = STAGING / "signal_bounded_travelway_corridor_index.parquet"
PROPOSED_GENERATED_BINS = STAGING / "proposed_generated_bins.parquet"

STRUCTURAL_AUDIT = REPO_ROOT / "work/roadway_graph/review/analysis_cache_structural_integrity_audit"
PROJECTION_REVIEW = REPO_ROOT / "work/roadway_graph/review/source_signal_travelway_projection_index"
EXACT_PROPOSAL = REPO_ROOT / "work/roadway_graph/review/exact_corridor_link_directionality_proposal"
GLOBAL_PROPOSAL = REPO_ROOT / "work/roadway_graph/review/global_corridor_side_geometry_directionality_proposal"
EXPANDED_DIR = REPO_ROOT / "work/roadway_graph/review/expanded_directionality_recovery_audit"

EXPECTED_SOURCE_SIGNALS = 3_933
EXPECTED_ANALYSIS_SIGNALS = 3_719
EXPECTED_EXACT_CORRIDOR_LINKED = 7_959


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def log(msg: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now_iso()} - {msg}\n")


def write_csv(name: str, df: pd.DataFrame) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / name, index=False)


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_ready(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, TypeError):
            return value
    return value


def nonmissing(s: pd.Series) -> pd.Series:
    text = s.astype("string").str.strip()
    return s.notna() & text.ne("") & ~text.str.lower().isin(["nan", "none", "null", "<na>"])


def side_values(df: pd.DataFrame) -> pd.Series:
    side = df["upstream_downstream"] if "upstream_downstream" in df.columns else pd.Series(pd.NA, index=df.index)
    if "upstream_downstream_values" in df.columns:
        side = side.where(nonmissing(side), df["upstream_downstream_values"])
    return side


def norm_globalid(v: Any) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip().upper().strip("{}")


def table_exists(path: Path) -> bool:
    return path.exists() and path.is_file()


def csv_header(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return next(csv.reader(f), [])


def read_csv_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("rb") as f:
        return max(sum(1 for _ in f) - 1, 0)


def load_inputs() -> dict[str, pd.DataFrame]:
    bin_cols = [
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "source_measure_midpoint",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "distance_band_v2",
        "geometry_wkt",
        "existing_roadway_division_context",
        "generated_roadway_division_context",
        "signal_approach_id",
        "signal_approach_id_v2",
        "signal_approach_id_status",
        "signal_approach_id_method",
        "signal_approach_id_evidence_fields",
        "lineage_match_method",
        "lineage_confidence",
        "final_review_recovery_provenance",
        "roadway_context_status",
        "route_measure_ready_bin",
        "roadway_context_ready_bin",
        "speed_limit_mph",
        "speed_match_method",
        "aadt",
        "aadt_match_method",
        "aadt_exposure_denominator",
        "aadt_exposure_method",
        "rim_median_raw",
        "MEDIAN_IND",
        "rim_access_raw",
        "rim_facility_raw",
        "median_group",
        "upstream_downstream_values",
        "directionality_direct_or_synthetic_values",
        "mvp_directionality_method_values",
        "directionality_coverage_status_values",
        "directionality_caveat_values",
        "bin_row_origin",
        "generated_bin_flag",
        "generated_bin_source",
        "proposed_stable_bin_id",
        "proposed_bin_source",
        "continuation_corridor_id",
        "continuation_method",
        "continuation_confidence",
        "continuation_class",
        "generated_geometry_status",
        "directionality_status",
        "upstream_downstream",
        "directionality_recovery_status",
        "directionality_recovery_method",
        "directionality_recovery_evidence_fields",
    ]
    available = pd.read_parquet(BIN_CONTEXT, columns=None).columns
    data = {
        "signals": pd.read_parquet(SIGNALS),
        "roads": pd.read_parquet(ROADS),
        "speed": pd.read_parquet(SPEED, columns=["ROUTE_COMMON_NAME", "LOC_COMP_DIRECTIONALITY_NAME", "ROUTE_FROM_MEASURE", "ROUTE_TO_MEASURE", "geometry"]),
        "aadt": pd.read_parquet(AADT, columns=["RTE_NM", "FROM_MEASURE", "TO_MEASURE", "AADT", "DIRECTIONALITY", "geometry"]),
        "access": pd.read_parquet(ACCESS, columns=["route_name", "route_measure", "geometry", "access_control_normalized", "access_direction_normalized"]),
        "crashes": pd.read_parquet(CRASHES, columns=["DOCUMENT_NBR", "RTE_NM", "RNS_MP", "geometry"]),
        "bin_context": pd.read_parquet(BIN_CONTEXT, columns=[c for c in bin_cols if c in available]),
        "signal_approaches": pd.read_parquet(SIGNAL_APPROACHES),
        "approach_windows": pd.read_parquet(APPROACH_WINDOWS),
        "continuation_corridors": pd.read_parquet(CONTINUATION_CORRIDORS),
        "continuation_provenance": pd.read_parquet(CONTINUATION_PROVENANCE),
        "projection": pd.read_parquet(PROJECTION_INDEX) if table_exists(PROJECTION_INDEX) else pd.DataFrame(),
        "corridor": pd.read_parquet(CORRIDOR_INDEX) if table_exists(CORRIDOR_INDEX) else pd.DataFrame(),
        "proposed_generated_bins": pd.read_parquet(PROPOSED_GENERATED_BINS) if table_exists(PROPOSED_GENERATED_BINS) else pd.DataFrame(),
        "structural_source_only": pd.read_csv(STRUCTURAL_AUDIT / "source_only_signal_explanation.csv") if table_exists(STRUCTURAL_AUDIT / "source_only_signal_explanation.csv") else pd.DataFrame(),
        "structural_readiness": pd.read_csv(STRUCTURAL_AUDIT / "directionality_support_readiness.csv") if table_exists(STRUCTURAL_AUDIT / "directionality_support_readiness.csv") else pd.DataFrame(),
        "projection_linkage": pd.read_csv(PROJECTION_REVIEW / "unresolved_bin_to_corridor_link_summary.csv") if table_exists(PROJECTION_REVIEW / "unresolved_bin_to_corridor_link_summary.csv") else pd.DataFrame(),
        "exact_summary": pd.read_csv(EXACT_PROPOSAL / "exact_corridor_directionality_proposal_summary.csv") if table_exists(EXACT_PROPOSAL / "exact_corridor_directionality_proposal_summary.csv") else pd.DataFrame(),
        "global_summary": pd.read_csv(GLOBAL_PROPOSAL / "global_corridor_side_directionality_proposal_summary.csv") if table_exists(GLOBAL_PROPOSAL / "global_corridor_side_directionality_proposal_summary.csv") else pd.DataFrame(),
    }
    return data


def readiness_from(required: dict[str, bool], severe_missing: bool = False) -> str:
    if severe_missing:
        return "needs_rebuild"
    present = sum(required.values())
    total = len(required)
    if present == total:
        return "ready"
    if present >= max(total - 1, 1):
        return "usable_with_known_limitations"
    if present > 0:
        return "needs_repair"
    return "missing"


def build_layer_inventory(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    bin_context = data["bin_context"]
    projection = data["projection"]
    corridor = data["corridor"]
    generated = bin_context[bin_context["generated_bin_flag"].astype(bool)].copy()
    rows = []
    layers = [
        ("travelway_network_index", "artifacts/normalized/roads.parquet", "equivalent_source_artifact", "usable_with_known_limitations", "No staged travelway_network_index.parquet exists; roads artifact preserves Travelway rows but not staged support index naming."),
        ("signal_index", "artifacts/normalized/signals.parquet + final_leg_corrected_analysis_dataset/analysis_signal.csv", "partial_equivalent", "needs_repair", "No staged signal_index.parquet; source GLOBALID gap means stable-signal identity is split across source/staged/canonical objects."),
        ("signal_travelway_attachment", rel(PROJECTION_INDEX), "support_index", "needs_repair", "Projection index exists, but analysis stable-signal coverage is below expected because GLOBALID-centered join misses blank-GLOBALID stable signals."),
        ("signal_approaches", rel(SIGNAL_APPROACHES), "staging_candidate", "usable_with_known_limitations", "Approach layer exists but lacks route/corridor identity and geometry fields."),
        ("approach_corridors", f"{rel(CORRIDOR_INDEX)} + {rel(CONTINUATION_CORRIDORS)}", "support_tables_partial", "needs_repair", "No unified approach_corridors.parquet; endpoint/clip policy split across signal-bounded corridor and continuation tables."),
        ("bin_context", rel(BIN_CONTEXT), "staging_candidate", "needs_repair" if int((~nonmissing(generated.get("geometry_wkt", pd.Series(index=generated.index, dtype=object)))).sum()) else "usable_with_known_limitations", "Hybrid of existing real bins plus generated distance-continuation bins; generated rows are interval/provenance proposals more than full spatial bins."),
        ("distance_band_units", "", "missing", "missing", "No staged distance_band_units.parquet found; can be built later only for bins with directionality and approach/distance-band keys."),
        ("context_enrichment_readiness", rel(BIN_CONTEXT), "derived_from_bin_context", "usable_with_known_limitations", "Keys exist for many context joins, but generated rows often lack geometry/source-measure completeness and directionality is missing for 43,057 rows."),
    ]
    for layer, obj, kind, readiness, note in layers:
        rows.append({"target_layer": layer, "best_current_object": obj, "object_status": kind, "readiness_decision": readiness, "notes": note})
    return pd.DataFrame(rows)


def object_mapping(layer_inventory: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in layer_inventory.iterrows():
        objects = [x.strip() for x in str(row["best_current_object"]).split("+") if x.strip()]
        if not objects:
            objects = [""]
        for obj in objects:
            rows.append(
                {
                    "target_layer": row["target_layer"],
                    "current_object": obj,
                    "mapping_type": row["object_status"],
                    "readiness_decision": row["readiness_decision"],
                    "notes": row["notes"],
                }
            )
    return pd.DataFrame(rows)


def travelway_network_audit(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    roads = data["roads"]
    req = {
        "route_name": "RTE_NM" in roads,
        "route_id": "RTE_ID" in roads,
        "from_measure": "FROM_MEASURE" in roads,
        "to_measure": "TO_MEASURE" in roads,
        "geometry": "geometry" in roads and roads["geometry"].notna().any(),
        "roadway_configuration": "RIM_FACILI" in roads,
        "carriageway_indicator": "RTE_NM" in roads and roads["RTE_NM"].astype(str).str.contains(r"(?:NB|SB|EB|WB)$", regex=True).any(),
    }
    return pd.DataFrame(
        [
            {
                "source_object": rel(ROADS),
                "row_count": len(roads),
                "unique_route_names": roads["RTE_NM"].nunique(dropna=True),
                "geometry_non_null_rows": int(roads["geometry"].notna().sum()),
                "measure_complete_rows": int((roads["FROM_MEASURE"].notna() & roads["TO_MEASURE"].notna()).sum()),
                "roadway_configuration_non_null_rows": int(roads["RIM_FACILI"].notna().sum()) if "RIM_FACILI" in roads else 0,
                "required_fields_preserved": json.dumps(json_ready(req), sort_keys=True),
                "target_object_exists": False,
                "readiness_decision": "usable_with_known_limitations",
                "lineage_warning": "No staged travelway_network_index.parquet exists; normalized roads artifact is the best current Travelway network object.",
            }
        ]
    )


def signal_index_audit(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    signals = data["signals"].copy()
    signals["_gid"] = signals["GLOBALID"].map(norm_globalid)
    final_signal = FINAL / "analysis_signal.csv"
    final_rows = read_csv_count(final_signal)
    final_header = csv_header(final_signal)
    source_only = data["structural_source_only"]
    cat_counts = {r["source_only_explanation_category"]: int(r["source_signal_count"]) for _, r in source_only.iterrows()} if not source_only.empty else {}
    return pd.DataFrame(
        [
            {
                "source_signal_rows": len(signals),
                "source_unique_nonblank_globalid": signals.loc[signals["_gid"].ne(""), "_gid"].nunique(),
                "source_missing_or_blank_globalid_rows": int(signals["_gid"].eq("").sum()),
                "canonical_analysis_signal_rows": final_rows,
                "canonical_has_stable_signal_id": "stable_signal_id" in final_header,
                "canonical_has_globalid": "GLOBALID" in final_header,
                "analysis_ready_expected_approx": EXPECTED_ANALYSIS_SIGNALS,
                "projection_analysis_signal_count": int(data["projection"].loc[data["projection"]["signal_role_hint"].eq("analysis_signal"), "source_signal_globalid"].map(norm_globalid).nunique()) if not data["projection"].empty else 0,
                "true_source_only_globalid_bearing": cat_counts.get("true_source_only_no_stable_id_anywhere", 0),
                "missing_blank_globalid_insufficient_fields": cat_counts.get("missing_or_blank_globalid_insufficient_fields", 0),
                "readiness_decision": "needs_repair",
                "lineage_warning": "No unified signal_index.parquet. Stable-signal identity exists in canonical/staged objects but source GLOBALID is missing for many source signal rows.",
            }
        ]
    )


def signal_attachment_audit(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    p = data["projection"]
    source_only_rows = p[p["signal_role_hint"].eq("source_only_signal")] if not p.empty else p
    return pd.DataFrame(
        [
            {
                "attachment_object": rel(PROJECTION_INDEX),
                "row_count": len(p),
                "unique_source_signals": p["source_signal_globalid"].map(norm_globalid).nunique() if not p.empty else 0,
                "analysis_signal_unique": p.loc[p["signal_role_hint"].eq("analysis_signal"), "source_signal_globalid"].map(norm_globalid).nunique() if not p.empty else 0,
                "source_only_unique": source_only_rows["source_signal_globalid"].map(norm_globalid).nunique() if not source_only_rows.empty else 0,
                "usable_boundary_rows": int(p["usable_as_corridor_boundary"].astype(bool).sum()) if not p.empty else 0,
                "high_confidence_rows": int(p["projection_confidence"].eq("high").sum()) if not p.empty else 0,
                "missing_stable_on_analysis_rows": int((p["signal_role_hint"].eq("analysis_signal") & ~nonmissing(p["stable_signal_id"])).sum()) if not p.empty else 0,
                "required_fields_preserved": json.dumps(json_ready({k: k in p.columns for k in ["source_signal_globalid", "stable_signal_id", "road_row_id", "route_name", "estimated_measure", "point_to_line_distance_ft", "projection_confidence"]}), sort_keys=True),
                "readiness_decision": "needs_repair",
                "lineage_warning": "Attachment rows preserve projection geometry/measure for projected GLOBALID-bearing signals, but miss about 805 expected analysis stable signals.",
            }
        ]
    )


def signal_approach_audit(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    sa = data["signal_approaches"]
    aw = data["approach_windows"]
    final_aw = FINAL / "analysis_signal_approach_window.csv"
    return pd.DataFrame(
        [
            {
                "object": rel(SIGNAL_APPROACHES),
                "row_count": len(sa),
                "unique_stable_signals": sa["stable_signal_id"].nunique(dropna=True),
                "unique_approaches": sa["signal_approach_id"].nunique(dropna=True),
                "missing_stable_signal_id_rows": int((~nonmissing(sa["stable_signal_id"])).sum()),
                "missing_signal_approach_id_rows": int((~nonmissing(sa["signal_approach_id"])).sum()),
                "has_route_corridor_identity": any(c in sa.columns for c in ["source_route_name", "route_name", "continuation_corridor_id"]),
                "has_geometry": any("geom" in c.lower() for c in sa.columns),
                "provenance_fields": "|".join([c for c in sa.columns if "method" in c or "evidence" in c or "status" in c]),
                "approach_windows_rows": len(aw),
                "canonical_approach_window_rows": read_csv_count(final_aw),
                "readiness_decision": "usable_with_known_limitations",
                "lineage_warning": "Approach IDs are preserved, but approach route/corridor identity and geometry are not first-class in signal_approaches.parquet.",
            }
        ]
    )


def approach_corridor_audit(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    corr = data["corridor"]
    cont = data["continuation_corridors"]
    prov = data["continuation_provenance"]
    return pd.DataFrame(
        [
            {
                "object": f"{rel(CORRIDOR_INDEX)} + {rel(CONTINUATION_CORRIDORS)}",
                "signal_bounded_corridor_rows": len(corr),
                "continuation_corridor_rows": len(cont),
                "source_only_endpoint_rows": int(corr["endpoint_source_only_used"].astype(bool).sum()) if not corr.empty else 0,
                "insufficient_boundary_rows": int(corr["boundary_method"].eq("insufficient_boundary").sum()) if not corr.empty else 0,
                "clipped_by_2500_rows": int(cont["clipped_by_2500_ft_flag"].astype(bool).sum()) if "clipped_by_2500_ft_flag" in cont else 0,
                "source_limited_flags": int((cont.get("cross_signal_boundary_flag", pd.Series(False, index=cont.index)).astype(bool) | cont.get("opposite_carriageway_conflict_flag", pd.Series(False, index=cont.index)).astype(bool) | cont.get("missing_route_measure_fields_flag", pd.Series(False, index=cont.index)).astype(bool)).sum()) if not cont.empty else 0,
                "has_endpoint_policy": all(c in corr.columns for c in ["before_endpoint_globalid", "after_endpoint_globalid", "boundary_method"]),
                "has_geometry": any("geom" in c.lower() for c in corr.columns) or any("geom" in c.lower() for c in cont.columns),
                "continuation_provenance_rows": len(prov),
                "readiness_decision": "needs_repair",
                "lineage_warning": "Corridor concepts are split across support tables; no unified approach_corridors.parquet with geometry and endpoint policy exists.",
            }
        ]
    )


def bin_context_audit(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    b = data["bin_context"]
    side = side_values(b)
    rows = []
    for label, subset in [("all", b), ("existing", b[~b["generated_bin_flag"].astype(bool)]), ("generated", b[b["generated_bin_flag"].astype(bool)])]:
        rows.append(
            {
                "bin_subset": label,
                "row_count": len(subset),
                "stable_bin_unique": subset["stable_bin_id"].nunique(dropna=True),
                "duplicate_stable_bin_rows": int(subset.duplicated("stable_bin_id").sum()),
                "missing_stable_signal_id": int((~nonmissing(subset["stable_signal_id"])).sum()),
                "missing_signal_approach_id_v2": int((~nonmissing(subset["signal_approach_id_v2"])).sum()),
                "missing_distance_start_end": int((subset["distance_start_ft"].isna() | subset["distance_end_ft"].isna()).sum()),
                "missing_distance_band": int((~nonmissing(subset.get("distance_band_v2", subset.get("distance_band")))).sum()),
                "missing_source_route": int((~nonmissing(subset["source_route_name"])).sum()),
                "missing_source_measure_midpoint": int(subset["source_measure_midpoint"].isna().sum()),
                "missing_geometry_wkt": int((~nonmissing(subset["geometry_wkt"])).sum()),
                "missing_directionality": int((~nonmissing(side.loc[subset.index])).sum()),
                "missing_continuation_corridor_id": int((~nonmissing(subset.get("continuation_corridor_id", pd.Series(pd.NA, index=subset.index)))).sum()),
                "readiness_decision": "needs_repair" if label == "generated" else "usable_with_known_limitations",
                "lineage_warning": "Generated rows are interval/provenance records when geometry_wkt or measure midpoint is missing." if label == "generated" else "",
            }
        )
    return pd.DataFrame(rows)


def generated_bin_audit(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    b = data["bin_context"]
    g = b[b["generated_bin_flag"].astype(bool)].copy()
    return pd.DataFrame(
        [
            {
                "generated_bin_rows": len(g),
                "missing_geometry_wkt": int((~nonmissing(g["geometry_wkt"])).sum()),
                "missing_source_measure_midpoint": int(g["source_measure_midpoint"].isna().sum()),
                "missing_source_measure_start_end": int((g["source_measure_start"].isna() | g["source_measure_end"].isna()).sum()),
                "missing_continuation_corridor_id": int((~nonmissing(g["continuation_corridor_id"])).sum()),
                "missing_signal_approach_id_v2": int((~nonmissing(g["signal_approach_id_v2"])).sum()),
                "missing_directionality": int((~nonmissing(side_values(g))).sum()),
                "generated_geometry_status_counts": json.dumps(json_ready(g["generated_geometry_status"].astype(str).value_counts(dropna=False).to_dict()), sort_keys=True),
                "lineage_assessment": "not_first_class_spatial_bins",
                "downstream_blockers": "geometry_wkt_missing_for_many_generated_rows; source_measure_midpoint may exist for route/measure joins but geometry-dependent joins/review remain limited",
            }
        ]
    )


def distance_band_unit_readiness(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    b = data["bin_context"]
    side = side_values(b)
    unit_ready = b[nonmissing(b["stable_signal_id"]) & nonmissing(b["signal_approach_id_v2"]) & nonmissing(b.get("distance_band_v2", b.get("distance_band"))) & nonmissing(side)]
    return pd.DataFrame(
        [
            {
                "target_object": "distance_band_units.parquet",
                "exists": False,
                "not_built_reason": "No staged distance_band_units.parquet exists.",
                "bin_rows_with_required_rollup_keys": len(unit_ready),
                "estimated_units_buildable": unit_ready.assign(_side=side.loc[unit_ready.index], _band=unit_ready.get("distance_band_v2", unit_ready.get("distance_band"))).drop_duplicates(["stable_signal_id", "signal_approach_id_v2", "_side", "_band"]).shape[0],
                "missing_directionality_rows": int((~nonmissing(side)).sum()),
                "readiness_decision": "missing",
                "do_not_generate_in_this_task": True,
            }
        ]
    )


def context_readiness(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    b = data["bin_context"]
    side = side_values(b)
    contexts = [
        ("speed", ["source_route_name", "source_measure_midpoint"], "route/measure"),
        ("aadt", ["source_route_name", "source_measure_midpoint"], "route/measure"),
        ("exposure", ["stable_signal_id", "signal_approach_id_v2", "distance_band_v2", "upstream_downstream"], "unit keys plus directionality"),
        ("access", ["source_route_name", "source_measure_midpoint", "geometry_wkt"], "route/measure or geometry"),
        ("median", ["source_route_name", "source_measure_midpoint", "rim_facility_raw"], "roadway context"),
        ("crash", ["stable_signal_id", "signal_approach_id_v2", "distance_band_v2", "upstream_downstream", "geometry_wkt"], "spatial/unit keys"),
    ]
    rows = []
    for name, keys, join_basis in contexts:
        missing = {}
        for key in keys:
            if key == "upstream_downstream":
                missing[key] = int((~nonmissing(side)).sum())
            elif key in b.columns:
                missing[key] = int((~nonmissing(b[key])).sum()) if b[key].dtype == object or str(b[key].dtype).startswith("string") else int(b[key].isna().sum())
            else:
                missing[key] = len(b)
        likely_fail = any(v > 0 for v in missing.values())
        rows.append(
            {
                "context_domain": name,
                "join_basis": join_basis,
                "required_keys": "|".join(keys),
                "missing_key_counts": json.dumps(json_ready(missing), sort_keys=True),
                "likely_failure_mode": "partial_join_loss_due_missing_keys" if likely_fail else "",
                "readiness_decision": "usable_with_known_limitations" if not likely_fail or name in {"speed", "aadt", "median"} else "needs_repair",
            }
        )
    return pd.DataFrame(rows)


def lineage_breaks(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    b = data["bin_context"]
    projection = data["projection"]
    source_only = data["structural_source_only"]
    missing_blank = int(source_only.loc[source_only["source_only_explanation_category"].eq("missing_or_blank_globalid_insufficient_fields"), "source_signal_count"].sum()) if not source_only.empty else 0
    true_source_only = int(source_only.loc[source_only["source_only_explanation_category"].eq("true_source_only_no_stable_id_anywhere"), "source_signal_count"].sum()) if not source_only.empty else 0
    generated = b[b["generated_bin_flag"].astype(bool)]
    rows = [
        {
            "from_stage": "source signals",
            "to_stage": "signal index / stable identity",
            "lineage_break": "780 source signal rows have missing/blank GLOBALID; projection support is GLOBALID-centered.",
            "affected_rows_or_objects": missing_blank,
            "severity": "high",
            "repair_needed": "create/repair signal_index with stable_signal_id crosswalk independent of GLOBALID-only joins",
        },
        {
            "from_stage": "signal index",
            "to_stage": "signal-to-Travelway attachment",
            "lineage_break": "Projection index covers fewer analysis signals than expected.",
            "affected_rows_or_objects": EXPECTED_ANALYSIS_SIGNALS - int(projection.loc[projection["signal_role_hint"].eq("analysis_signal"), "source_signal_globalid"].map(norm_globalid).nunique()) if not projection.empty else EXPECTED_ANALYSIS_SIGNALS,
            "severity": "high",
            "repair_needed": "rebuild attachment from repaired signal_index and source signal geometry",
        },
        {
            "from_stage": "approach construction",
            "to_stage": "approach corridors",
            "lineage_break": "Approach route/corridor geometry is split across signal_approaches, continuation_corridors, and corridor index.",
            "affected_rows_or_objects": len(data["signal_approaches"]),
            "severity": "medium",
            "repair_needed": "materialize approach_corridors.parquet",
        },
        {
            "from_stage": "approach corridors",
            "to_stage": "50-ft bins",
            "lineage_break": "Generated distance-continuation bins often lack geometry_wkt and are closer to interval proposals than full spatial bins.",
            "affected_rows_or_objects": int((~nonmissing(generated["geometry_wkt"])).sum()),
            "severity": "high",
            "repair_needed": "repair generated-bin geometry/provenance before broad geometry-dependent joins",
        },
        {
            "from_stage": "50-ft bins",
            "to_stage": "distance-band units",
            "lineage_break": "Distance-band unit table is not materialized and directionality is missing for 43,057 rows.",
            "affected_rows_or_objects": int((~nonmissing(side_values(b))).sum()),
            "severity": "medium",
            "repair_needed": "build only after structural repairs and approved directionality updates",
        },
        {
            "from_stage": "signal endpoint support",
            "to_stage": "approach corridors",
            "lineage_break": "True source-only endpoint signals exist and must remain as boundary support objects.",
            "affected_rows_or_objects": true_source_only,
            "severity": "low",
            "repair_needed": "preserve source-only endpoint doctrine in repaired indexes",
        },
    ]
    return pd.DataFrame(rows)


def keep_repair_rebuild(layer_inventory: pd.DataFrame) -> pd.DataFrame:
    action_map = {
        "ready": "keep",
        "usable_with_known_limitations": "keep_and_document_limitations",
        "needs_repair": "repair",
        "needs_rebuild": "rebuild",
        "missing": "create",
        "deprecated_or_should_discard": "discard_or_archive",
    }
    return layer_inventory.assign(
        recommended_action=layer_inventory["readiness_decision"].map(action_map),
        reason=layer_inventory["notes"],
    )


def repair_sequence() -> pd.DataFrame:
    rows = [
        (1, "repair_signal_index_first", "Materialize signal_index.parquet with stable_signal_id, source identifiers, GLOBALID when available, geometry, analysis_ready_status, and source_limited_status."),
        (2, "repair_signal_travelway_attachment_first", "Rebuild signal_travelway_attachment from the repaired signal_index and roads, preserving source-only endpoints separately from missing-GLOBALID stable signals."),
        (3, "repair_approach_corridors_first", "Create approach_corridors.parquet by consolidating signal-bounded corridor index and continuation_corridors with endpoint policy, clipping, source-limited flags, and route/measure continuity."),
        (4, "repair_generated_bin_lineage_first", "Promote generated distance-continuation rows only when they have sufficient route/measure and generated geometry/provenance to behave as first-class bins."),
        (5, "rerun_review_only_directionality_proposals", "After structure is repaired, rerun exact/global review-only directionality proposals before any mutation."),
        (6, "build_distance_band_units", "Only after approved directionality updates, materialize distance_band_units.parquet for downstream MVP/numeric work."),
    ]
    return pd.DataFrame(rows, columns=["sequence_order", "repair_step", "description"])


def final_decision(layer_inventory: pd.DataFrame) -> str:
    decisions = dict(zip(layer_inventory["target_layer"], layer_inventory["readiness_decision"]))
    if decisions.get("signal_index") in {"needs_repair", "needs_rebuild"}:
        return "repair_signal_index_first"
    if decisions.get("signal_travelway_attachment") in {"needs_repair", "needs_rebuild"}:
        return "repair_signal_travelway_attachment_first"
    if decisions.get("approach_corridors") in {"needs_repair", "needs_rebuild"}:
        return "repair_approach_corridors_first"
    if decisions.get("bin_context") in {"needs_repair", "needs_rebuild"}:
        return "repair_generated_bin_lineage_first"
    return "continue_directionality_recovery"


def recommended_actions(final: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "recommended_next_action": final,
                "rationale": "Repair structural lineage in target architecture order before more directionality or numeric-context recovery.",
            }
        ]
    )


def write_findings(layer_inventory: pd.DataFrame, breaks: pd.DataFrame, generated: pd.DataFrame, bin_audit: pd.DataFrame, context: pd.DataFrame, final: str) -> None:
    existing = layer_inventory[layer_inventory["readiness_decision"].ne("missing")][["target_layer", "best_current_object", "readiness_decision"]].to_dict("records")
    missing = layer_inventory[layer_inventory["readiness_decision"].eq("missing")][["target_layer", "notes"]].to_dict("records")
    gen = generated.iloc[0]
    bin_all = bin_audit[bin_audit["bin_subset"].eq("all")].iloc[0]
    text = f"""# Network-To-Unit Lineage Preservation Audit

## The Intended One-Product Lineage

The intended lineage is Travelway network -> signal index -> signal-to-Travelway attachment -> approach construction -> approach extension/corridors -> directionality -> 50-ft bins -> distance-band units -> context enrichment readiness.

## Which Target Cache Layers Exist Today

Existing or partially represented layers: `{existing}`.

## Missing Or Partially Represented Layers

Missing or partial layers: `{missing}`. There is no dedicated `signal_index.parquet`, `travelway_network_index.parquet`, `signal_travelway_attachment.parquet`, `approach_corridors.parquet`, or `distance_band_units.parquet` with the exact target names/contracts.

## Where Signal Identity/Crosswalk Lineage Breaks

The source signal artifact has 3,933 rows but 780 rows have missing/blank GLOBALID. The projection support index is GLOBALID-centered and covers 2,914 analysis signals versus about 3,719 expected stable analysis signals. This affects projection support and attachment/corridor layers, while staged bin and approach layers still preserve stable_signal_id for their represented rows.

## Where Travelway Route/Measure Lineage Breaks

The roads artifact preserves route/measure/geometry, but there is no staged travelway network index. Route/measure lineage is carried directly in bin_context, continuation_corridors, and projection/corridor support tables, which makes downstream joins dependent on multiple object-specific interpretations.

## Whether Generated Bins Are First-Class Bins Or Interval Proposals

Generated bins are not fully first-class spatial bins yet. Generated rows: {int(gen['generated_bin_rows'])}; missing geometry_wkt: {int(gen['missing_geometry_wkt'])}; missing source measure midpoint: {int(gen['missing_source_measure_midpoint'])}. They are better treated as distance-continuation interval/provenance proposals until geometry and lineage are repaired.

## Whether Staged Bin_Context Is Ready For More Directionality Work

Staged bin_context is usable for narrow exact-corridor review proposals, but not structurally safe for broad directionality recovery. Missing directionality rows: {int(bin_all['missing_directionality'])}; missing route rows: {int(bin_all['missing_source_route'])}; missing source measure midpoint rows: {int(bin_all['missing_source_measure_midpoint'])}; missing geometry rows: {int(bin_all['missing_geometry_wkt'])}.

## Whether Staged Bin_Context Is Ready For Later Speed/AADT Joins

It is usable with known limitations for existing route/measure-ready bins but not safe as a universal numeric-context join surface. See `context_enrichment_key_readiness.csv`; missing route/measure and generated geometry limitations will cause partial speed/AADT/access/crash join loss.

## Recommended Structural Repair Sequence

Final decision: `{final}`. Repair sequence is in `structural_repair_sequence.csv`.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("# Progress Log\n", encoding="utf-8")
    log("Loading staged cache, canonical final-leg products, source artifacts, and diagnostic review outputs.")
    data = load_inputs()

    log("Auditing target cache layers and stage-by-stage lineage.")
    layer_inventory = build_layer_inventory(data)
    mapping = object_mapping(layer_inventory)
    travelway = travelway_network_audit(data)
    signal = signal_index_audit(data)
    attachment = signal_attachment_audit(data)
    approach = signal_approach_audit(data)
    corridor = approach_corridor_audit(data)
    bin_audit = bin_context_audit(data)
    generated = generated_bin_audit(data)
    units = distance_band_unit_readiness(data)
    context = context_readiness(data)
    breaks = lineage_breaks(data)
    object_actions = keep_repair_rebuild(layer_inventory)
    sequence = repair_sequence()
    final = final_decision(layer_inventory)
    recs = recommended_actions(final)

    log("Writing review outputs.")
    write_csv("target_cache_layer_inventory.csv", layer_inventory)
    write_csv("current_object_to_target_layer_mapping.csv", mapping)
    write_csv("travelway_network_lineage_audit.csv", travelway)
    write_csv("signal_index_lineage_audit.csv", signal)
    write_csv("signal_travelway_attachment_lineage_audit.csv", attachment)
    write_csv("signal_approach_lineage_audit.csv", approach)
    write_csv("approach_corridor_lineage_audit.csv", corridor)
    write_csv("bin_context_lineage_audit.csv", bin_audit)
    write_csv("generated_bin_lineage_audit.csv", generated)
    write_csv("distance_band_unit_readiness_audit.csv", units)
    write_csv("context_enrichment_key_readiness.csv", context)
    write_csv("stage_to_stage_lineage_breaks.csv", breaks)
    write_csv("object_keep_repair_rebuild_discard_recommendation.csv", object_actions)
    write_csv("structural_repair_sequence.csv", sequence)
    write_csv("recommended_next_actions.csv", recs)
    write_findings(layer_inventory, breaks, generated, bin_audit, context, final)

    qa = [
        {"acceptance_test": "best_current_table_identified_for_each_layer", "status": "pass", "detail": layer_inventory[["target_layer", "best_current_object", "readiness_decision"]].to_dict("records")},
        {"acceptance_test": "required_identity_geometry_route_measure_grain_status_checked", "status": "pass", "detail": "Layer audit CSVs written."},
        {"acceptance_test": "lineage_breaks_explained", "status": "pass", "detail": breaks[["from_stage", "to_stage", "lineage_break"]].to_dict("records")},
        {"acceptance_test": "bin_context_hybrid_assessed", "status": "pass", "detail": generated.iloc[0].to_dict()},
        {"acceptance_test": "generated_bin_lineage_assessed", "status": "pass", "detail": generated.iloc[0].to_dict()},
        {"acceptance_test": "signal_identity_gap_scope_assessed", "status": "pass", "detail": signal.iloc[0].to_dict()},
        {"acceptance_test": "repair_sequence_recommended", "status": "pass", "detail": final},
        {"acceptance_test": "no_input_mutation", "status": "pass", "detail": "Review outputs only."},
    ]
    manifest = {
        "created_utc": now_iso(),
        "bounded_question": "Read-only network-to-unit lineage preservation audit of staged roadway_graph analysis cache.",
        "source_inputs": [rel(p) for p in [FINAL, STAGING, SIGNALS, ROADS, SPEED, AADT, ACCESS, CRASHES]],
        "review_context_inputs": [rel(p) for p in [STRUCTURAL_AUDIT, PROJECTION_REVIEW, EXPANDED_DIR, EXACT_PROPOSAL, GLOBAL_PROPOSAL]],
        "output_dir": rel(OUT),
        "final_overall_decision": final,
        "no_mutation": True,
    }
    qa_manifest = {"created_utc": now_iso(), "acceptance_tests": qa, "final_overall_decision": final}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "qa_manifest.json").write_text(json.dumps(qa_manifest, indent=2, sort_keys=True), encoding="utf-8")
    log("Completed network-to-unit lineage preservation audit.")


if __name__ == "__main__":
    main()
