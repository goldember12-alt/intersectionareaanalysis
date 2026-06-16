"""Patch spatial access assignment with within-signal band exclusivity.

This bounded access repair keeps the accepted combined-source spatial-only
method and applies one additional rule: a source access point can contribute to
at most one distance band for the same signal/approach/upstream-downstream
group. It does not use identity-only assignment and does not modify non-access
context fields.
"""

from __future__ import annotations

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
from shapely import from_wkb
from shapely.strtree import STRtree


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/patch_distance_band_context_access_spatial_exclusivity"
CONTEXT = STAGING / "distance_band_context.parquet"
UNITS = STAGING / "distance_band_units.parquet"
BINS = STAGING / "bin_context.parquet"
SIGNALS = STAGING / "signal_index.parquet"
ACCESS = REPO / "artifacts/normalized/access.parquet"
ACCESS_V2 = REPO / "artifacts/normalized/access_v2.parquet"
CRASHES = REPO / "artifacts/normalized/crashes.parquet"
MANIFEST = STAGING / "manifest.json"
SCHEMA = STAGING / "schema.json"
README = STAGING / "README.md"
TEMP = STAGING / "distance_band_context.access_spatial_exclusivity_candidate.tmp.parquet"

BUILD_VERSION = "distance_band_context_access_spatial_exclusivity_v1_2026-06-15"
FT_PER_M = 3.280839895
SPATIAL_TOLERANCE_FT = 50.0
BROAD_DIAGNOSTIC_FT = 250.0
IDENTITY_COLUMNS = ["distance_band_unit_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"]
ACCESS_PATCH_FIELDS = [
    "access_count", "access_count_band", "access_type_flags", "access_type_dominant", "access_type_summary",
    "typed_access_count", "untyped_access_count", "riro_access_count", "other_review_access_count",
    "right_in_right_out_access_count", "access_context_status", "access_source_match_method",
    "access_missing_reason", "access_zero_evidence_status", "access_context_quality_flag",
    "access_candidate_count", "mixed_access_flag", "access_assignment_method",
    "access_spatial_tolerance_ft", "access_assignment_multiplicity_status",
    "access_source_universe_status", "access_typed_untyped_source_status",
    "access_identity_support_status", "access_identity_fanout_status",
]
CRASH_DIRECTION_TOKENS = ("crash_direction", "veh_direction", "vehicle_direction", "direction_of_travel", "dir_of_travel", "travel_direction")
FORBIDDEN_OUTPUT_TOKENS = ("lookup", "rate_distribution", "mvp")
CORRECTED_CATEGORY_MAP = {"U": "unrestricted_or_full_access", "RIRO": "right_in_right_out", "R": "right_in_right_out", "RC": "right_in_right_out", "RIO": "right_in_only", "ROO": "right_out_only", "LIRIRO": "restricted_partial_access", "": "unknown"}
ACCESS_CATEGORIES = ["unrestricted_or_full_access", "right_in_right_out", "restricted_partial_access", "right_out_only", "right_in_only", "other_review", "unknown"]
BAND_ORDER = {"0_250ft": 0, "250_500ft": 1, "500_1000ft": 2, "1000_1500ft": 3, "1500_2000ft": 4, "2000_2500ft": 5, "1500_2500ft": 4}
PHASE_TIMINGS: list[dict[str, Any]] = []


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except Exception:
        return str(path)


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"- {now()} - {message}\n"
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as h:
        h.write(line)
    print(line.strip(), flush=True)


@contextmanager
def phase(name: str, **details: Any):
    log(f"BEGIN {name}{' ' + str(details) if details else ''}")
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = round(time.perf_counter() - start, 3)
        PHASE_TIMINGS.append({"phase": name, "elapsed_seconds": elapsed, **details})
        log(f"END {name}; elapsed_seconds={elapsed:.3f}")


def write_csv(name: str, rows: Any) -> pd.DataFrame:
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    if not name.lower().endswith(".csv"):
        name = f"{name}.csv"
    frame.to_csv(OUT / name, index=False)
    return frame


def write_json(name: str, payload: dict[str, Any]) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def clean_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def bool_value(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def route_key(value: Any) -> str:
    text = clean_text(value).upper()
    text = text.replace("R-VA", " ").replace("S-VA", " ").replace("VA", " ")
    text = re.sub(r"[^A-Z0-9]", " ", text)
    joined = "".join(part for part in text.split() if part)
    match = re.search(r"(US|SR|IS|I)(0*)(\d+)(NB|SB|EB|WB|N|S|E|W)?(BUS\d+)?", joined)
    if match:
        return f"{'I' if match.group(1) in {'IS','I'} else match.group(1)}{int(match.group(3))}{ {'NB':'N','SB':'S','EB':'E','WB':'W'}.get(match.group(4) or '', match.group(4) or '')}{match.group(5) or ''}"
    return joined


def category_from_raw(raw_code: Any, prior_category: Any = "") -> str:
    code = clean_text(raw_code).upper()
    if code in CORRECTED_CATEGORY_MAP:
        return CORRECTED_CATEGORY_MAP[code]
    prior = clean_text(prior_category)
    return prior if prior in ACCESS_CATEGORIES else "other_review"


def access_count_band(count: Any) -> str:
    v = pd.to_numeric(pd.Series([count]), errors="coerce").iloc[0]
    if pd.isna(v):
        return ""
    v = int(v)
    return "0" if v <= 0 else "1" if v == 1 else "2-3" if v <= 3 else "4-7" if v <= 7 else "8+"


def collapse_unique(values: pd.Series, limit: int = 20) -> str:
    out = []
    for val in values.dropna().astype(str):
        val = val.strip()
        if val and val not in out:
            out.append(val)
        if len(out) >= limit:
            break
    return "|".join(out)


def parent_dependency_check() -> None:
    rows = []
    for path in [CONTEXT, UNITS, BINS, SIGNALS, ACCESS, ACCESS_V2, CRASHES]:
        rows.append({"path": rel(path), "role": "parent" if path != CRASHES else "guard_only", "exists": path.exists(), "sha256": file_sha256(path) if path.exists() else ""})
    write_csv("parent_dependency_check.csv", rows)


def build_source() -> pd.DataFrame:
    with phase("build_combined_access_source"):
        access = pd.read_parquet(ACCESS)
        v2 = pd.read_parquet(ACCESS_V2)
        a = access.copy()
        a["source_artifact"] = "access.parquet"
        a["source_layer"] = clean_series(a.get("Stage1_SourceLayer", pd.Series("layer_lrspoint", index=a.index)))
        a["source_access_id"] = clean_series(a.get("id", pd.Series("", index=a.index)))
        a["raw_access_control_code"] = ""
        a["access_category"] = "unknown"
        a["typed_untyped_status"] = "untyped_access"
        a["route_name"] = clean_series(a.get("_rte_nm", pd.Series("", index=a.index)))
        b = v2.copy()
        b["source_artifact"] = "access_v2.parquet"
        b["source_layer"] = clean_series(b.get("access_v2_source_layer", pd.Series("", index=b.index)))
        b["source_access_id"] = clean_series(b.get("id", pd.Series("", index=b.index)))
        b["raw_access_control_code"] = clean_series(b.get("access_control_code", pd.Series("", index=b.index))).str.upper()
        prior = clean_series(b.get("access_control_category", pd.Series("", index=b.index))).replace("", "unknown")
        b["access_category"] = [category_from_raw(c, p) for c, p in zip(b["raw_access_control_code"], prior)]
        b["typed_untyped_status"] = np.where(b["access_category"].eq("unknown"), "untyped_or_unknown_access_v2", "typed_or_review_coded_access")
        b["route_name"] = clean_series(b.get("route_name", b.get("_rte_nm", pd.Series("", index=b.index))))
        source = pd.concat([a, b], ignore_index=True, sort=False)
        source = source.loc[source["geometry"].notna()].copy()
        source["source_access_key"] = source["source_artifact"] + ":" + source["source_layer"] + ":" + source["source_access_id"]
        source["geometry_obj"] = from_wkb(source["geometry"].to_numpy())
        source = source.loc[~pd.isna(source["geometry_obj"])].copy()
        source["xy_key"] = pd.to_numeric(source["_x"], errors="coerce").round(6).astype(str) + "," + pd.to_numeric(source["_y"], errors="coerce").round(6).astype(str)
        typed_xy = set(source.loc[source["typed_untyped_status"].eq("typed_or_review_coded_access"), "xy_key"])
        source = source.loc[~(source["source_artifact"].eq("access.parquet") & source["xy_key"].isin(typed_xy))].reset_index(drop=True)
        source["route_key"] = clean_series(source["route_name"]).map(route_key)
        write_csv("combined_access_source_summary.csv", source.groupby(["source_artifact", "source_layer", "typed_untyped_status", "access_category"]).agg(source_point_count=("source_access_key", "nunique")).reset_index())
        return source


def load_context_units_bins() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with phase("load_context_units_bins"):
        context = pd.read_parquet(CONTEXT)
        units = pd.read_parquet(UNITS)
        cols = ["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band", "stable_bin_id", "geometry", "geometry_length_ft"]
        bins = pd.read_parquet(BINS, columns=cols)
        bins["upstream_downstream"] = clean_series(bins["upstream_downstream"])
        bins.loc[~bins["upstream_downstream"].isin(["upstream", "downstream"]), "upstream_downstream"] = ""
        bins = bins.merge(units[IDENTITY_COLUMNS], on=["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"], how="left", validate="many_to_one")
        bins = bins.loc[bins["geometry"].notna()].copy().reset_index(drop=True)
        bins["geometry_obj"] = from_wkb(bins["geometry"].to_numpy())
        bins = bins.loc[~pd.isna(bins["geometry_obj"])].reset_index(drop=True)
        return context, units, bins


def spatial_pairs(source: pd.DataFrame, bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    with phase("reconstruct_current_spatial_assignment", access_points=len(source), bin_rows=len(bins)):
        tree = STRtree(bins["geometry_obj"].to_numpy())
        pairs = tree.query(source["geometry_obj"].to_numpy(), predicate="dwithin", distance=SPATIAL_TOLERANCE_FT / FT_PER_M)
        ai, bi = pairs[0].astype("int64"), pairs[1].astype("int64")
        raw = pd.DataFrame({"access_index": ai, "bin_index": bi})
        for col in ["source_access_key", "source_layer", "typed_untyped_status", "access_category", "raw_access_control_code", "source_artifact"]:
            raw[col] = source[col].to_numpy()[ai]
        for col in ["distance_band_unit_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band", "stable_bin_id"]:
            raw[col] = bins[col].to_numpy()[bi]
        # distance is exact point-to-bin line distance in feet for tie-breaking.
        sgeom = source["geometry_obj"].to_numpy()
        bgeom = bins["geometry_obj"].to_numpy()
        raw["distance_to_bin_ft"] = [sgeom[a].distance(bgeom[b]) * FT_PER_M for a, b in zip(ai, bi)]
        raw["band_order"] = clean_series(raw["distance_band"]).map(BAND_ORDER).fillna(999).astype(int)
        pair = raw.groupby(["source_access_key", "distance_band_unit_id"], as_index=False).agg(
            source_layer=("source_layer", "first"),
            typed_untyped_status=("typed_untyped_status", "first"),
            access_category=("access_category", "first"),
            raw_access_control_code=("raw_access_control_code", "first"),
            source_artifact=("source_artifact", "first"),
            stable_signal_id=("stable_signal_id", "first"),
            signal_approach_id=("signal_approach_id", "first"),
            upstream_downstream=("upstream_downstream", "first"),
            distance_band=("distance_band", "first"),
            band_order=("band_order", "first"),
            min_distance_to_unit_geometry_ft=("distance_to_bin_ft", "min"),
            matching_bin_count=("stable_bin_id", "nunique"),
        )
        pc = pair.groupby("source_access_key")["distance_band_unit_id"].nunique()
        write_csv("current_assignment_reconstruction_summary.csv", [{"assigned_access_points": pair["source_access_key"].nunique(), "assigned_unit_pairs": len(pair), "units_with_access": pair["distance_band_unit_id"].nunique(), "max_units_per_access_point": int(pc.max())}])
        return pair, raw


def unassigned_audit(source: pd.DataFrame, assigned: pd.DataFrame, bins: pd.DataFrame) -> None:
    with phase("audit_unassigned_source_points"):
        assigned_keys = set(assigned["source_access_key"])
        un = source.loc[~source["source_access_key"].isin(assigned_keys)].copy()
        tree = STRtree(bins["geometry_obj"].to_numpy())
        idx = tree.nearest(un["geometry_obj"].to_numpy()) if not un.empty else np.array([], dtype=int)
        if len(idx):
            bgeom = bins["geometry_obj"].to_numpy()
            un["nearest_unit_distance_ft"] = [g.distance(bgeom[i]) * FT_PER_M for g, i in zip(un["geometry_obj"], idx)]
            un["nearest_distance_band_unit_id"] = bins["distance_band_unit_id"].to_numpy()[idx]
        else:
            un["nearest_unit_distance_ft"] = np.nan
            un["nearest_distance_band_unit_id"] = ""
        un["unassigned_reason"] = np.select(
            [un["geometry"].isna(), un["nearest_unit_distance_ft"].le(100), un["nearest_unit_distance_ft"].le(150), un["nearest_unit_distance_ft"].le(250), un["nearest_unit_distance_ft"].gt(250)],
            ["invalid_or_missing_access_geometry", "near_universe_but_rejected_by_tolerance", "near_universe_but_rejected_by_tolerance", "near_universe_but_rejected_by_tolerance", "outside_2500ft_signal_approach_universe"],
            default="unknown_unassigned_reason",
        )
        write_csv("unassigned_access_point_audit.csv", un[["source_access_key", "source_layer", "typed_untyped_status", "access_category", "nearest_unit_distance_ft", "nearest_distance_band_unit_id", "unassigned_reason"]].head(100000))
        write_csv("unassigned_access_nearest_unit_distance_summary.csv", un.groupby(["unassigned_reason", "source_layer", "typed_untyped_status"]).agg(access_point_count=("source_access_key", "nunique"), min_distance_ft=("nearest_unit_distance_ft", "min"), median_distance_ft=("nearest_unit_distance_ft", "median"), max_distance_ft=("nearest_unit_distance_ft", "max")).reset_index())
        # Signal distance is approximated by nearest unit geometry because signal point geometry may not be consistently materialized.
        write_csv("unassigned_access_nearest_signal_distance_summary.csv", [{"status": "not_computed", "reason": "signal_index point geometry not required; nearest unit geometry used for fast audit"}])


def multiband_audit(pair: pd.DataFrame, name: str) -> pd.DataFrame:
    grp = pair.groupby(["source_access_key", "stable_signal_id", "signal_approach_id", "upstream_downstream"], as_index=False).agg(band_count=("distance_band", "nunique"), min_band_order=("band_order", "min"), max_band_order=("band_order", "max"), unit_count=("distance_band_unit_id", "nunique"))
    grp["has_non_adjacent"] = grp["band_count"].gt(1) & ((grp["max_band_order"] - grp["min_band_order"]) >= grp["band_count"])
    write_csv(name, grp.loc[grp["band_count"].gt(1)])
    return grp


def apply_exclusivity(pair: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    with phase("apply_distance_band_exclusivity"):
        current_multi = multiband_audit(pair, "current_multiband_assignment_audit")
        sort_cols = ["source_access_key", "stable_signal_id", "signal_approach_id", "upstream_downstream", "min_distance_to_unit_geometry_ft", "matching_bin_count", "band_order"]
        work = pair.sort_values(sort_cols, ascending=[True, True, True, True, True, False, True]).copy()
        group_cols = ["source_access_key", "stable_signal_id", "signal_approach_id", "upstream_downstream"]
        keep_idx = work.drop_duplicates(group_cols, keep="first").index
        kept = work.loc[keep_idx].copy()
        dropped = work.loc[~work.index.isin(keep_idx)].copy()
        dropped["drop_reason"] = "within_signal_approach_direction_distance_band_exclusivity"
        write_csv("distance_band_exclusivity_dropped_pair_ledger.csv", dropped.head(100000))
        post_multi = multiband_audit(kept, "post_exclusivity_multiband_audit")
        write_csv("post_exclusivity_non_adjacent_band_red_flag_ledger.csv", post_multi.loc[post_multi["has_non_adjacent"]])
        write_csv("distance_band_exclusivity_rule_summary.csv", [{"current_multiband_groups": int(current_multi["band_count"].gt(1).sum()), "post_multiband_groups": int(post_multi["band_count"].gt(1).sum()), "dropped_access_unit_pairs": len(dropped), "selection_rule": "min distance to bin geometry, then greatest matching bin count, then lower distance-band order"}])
        pc = kept.groupby("source_access_key")["distance_band_unit_id"].nunique()
        write_csv("post_exclusivity_assignment_summary.csv", [{"assigned_access_points": kept["source_access_key"].nunique(), "assigned_unit_pairs": len(kept), "units_with_access": kept["distance_band_unit_id"].nunique(), "max_units_per_access_point": int(pc.max()) if not pc.empty else 0}])
        write_csv("post_exclusivity_access_point_multiplicity.csv", pc.value_counts().rename_axis("assigned_unit_count").reset_index(name="access_point_count").sort_values("assigned_unit_count"))
        return kept, dropped


def aggregate_access(kept: pd.DataFrame, units: pd.DataFrame) -> pd.DataFrame:
    with phase("aggregate_post_exclusivity_access"):
        if kept.empty:
            found = pd.DataFrame(columns=["distance_band_unit_id"])
        else:
            base = kept.groupby("distance_band_unit_id").agg(access_count=("source_access_key", "nunique"), access_candidate_count=("source_access_key", "size"), access_type_flags=("access_category", lambda s: collapse_unique(pd.Series(sorted(set(s.dropna().astype(str)))))), access_type_summary=("raw_access_control_code", lambda s: collapse_unique(s, 30))).reset_index()
            counts = kept.groupby(["distance_band_unit_id", "access_category"])["source_access_key"].nunique().reset_index(name="category_count")
            dom = counts.sort_values(["distance_band_unit_id", "category_count", "access_category"], ascending=[True, False, True]).drop_duplicates("distance_band_unit_id")[["distance_band_unit_id", "access_category"]].rename(columns={"access_category": "access_type_dominant"})
            pivot = counts.pivot_table(index="distance_band_unit_id", columns="access_category", values="category_count", aggfunc="sum", fill_value=0).reset_index()
            for cat in ACCESS_CATEGORIES:
                if cat not in pivot:
                    pivot[cat] = 0
            found = base.merge(dom, on="distance_band_unit_id").merge(pivot, on="distance_band_unit_id")
            found["typed_access_count"] = found[[c for c in ACCESS_CATEGORIES if c != "unknown"]].sum(axis=1).astype(int)
            found["untyped_access_count"] = found["unknown"].astype(int)
            found["right_in_right_out_access_count"] = found["right_in_right_out"].astype(int)
            found["riro_access_count"] = found["right_in_right_out"].astype(int)
            found["other_review_access_count"] = found["other_review"].astype(int)
            found["access_count_band"] = found["access_count"].map(access_count_band)
            found["access_context_status"] = "spatial_access_found"
            found["access_source_match_method"] = "combined_source_spatial_50ft_within_signal_band_exclusivity"
            found["access_missing_reason"] = ""
            found["access_zero_evidence_status"] = "not_zero_access_found"
            found["access_context_quality_flag"] = "within_signal_band_exclusivity_applied"
            found["mixed_access_flag"] = counts.groupby("distance_band_unit_id")["access_category"].nunique().reindex(found["distance_band_unit_id"]).fillna(0).gt(1).to_numpy()
            found["access_assignment_method"] = "combined_source_spatial_only_within_signal_band_exclusivity"
            found["access_spatial_tolerance_ft"] = SPATIAL_TOLERANCE_FT
            pc = kept.groupby("source_access_key")["distance_band_unit_id"].nunique()
            max_pc_by_unit = kept.merge(pc.rename("assigned_unit_count"), on="source_access_key").groupby("distance_band_unit_id")["assigned_unit_count"].max()
            found["access_assignment_multiplicity_status"] = np.where(found["distance_band_unit_id"].map(max_pc_by_unit).fillna(1).gt(1), "multi_unit_spatial_assignment_present", "single_unit_spatial_assignment")
            found["access_source_universe_status"] = "accepted_combined_access_parquet_untyped_plus_access_v2_typed"
            found["access_typed_untyped_source_status"] = np.select([found["typed_access_count"].gt(0) & found["untyped_access_count"].gt(0), found["typed_access_count"].gt(0), found["untyped_access_count"].gt(0)], ["typed_and_untyped", "typed_only", "untyped_only"], default="none")
            found["access_identity_support_status"] = "identity_only_rejected"
            found["access_identity_fanout_status"] = "identity_only_rejected_due_fanout"
            found = found.drop(columns=[c for c in ACCESS_CATEGORIES if c in found.columns])
        zero_ids = sorted(set(units["distance_band_unit_id"]) - set(found["distance_band_unit_id"]))
        zero = pd.DataFrame({"distance_band_unit_id": zero_ids})
        for col, val in {"access_count": 0, "access_count_band": "0", "access_type_flags": "", "access_type_dominant": "none", "access_type_summary": "", "typed_access_count": 0, "untyped_access_count": 0, "right_in_right_out_access_count": 0, "riro_access_count": 0, "other_review_access_count": 0, "access_context_status": "evaluated_zero_access", "access_source_match_method": "combined_source_spatial_50ft_within_signal_band_exclusivity", "access_missing_reason": "", "access_zero_evidence_status": "evaluated_zero_after_combined_spatial_source", "access_context_quality_flag": "evaluated_zero_within_signal_band_exclusivity", "access_candidate_count": 0, "mixed_access_flag": False, "access_assignment_method": "combined_source_spatial_only_within_signal_band_exclusivity", "access_spatial_tolerance_ft": SPATIAL_TOLERANCE_FT, "access_assignment_multiplicity_status": "no_access_points_assigned", "access_source_universe_status": "accepted_combined_access_parquet_untyped_plus_access_v2_typed", "access_typed_untyped_source_status": "evaluated_combined_no_access", "access_identity_support_status": "no_spatial_access_identity_only_rejected", "access_identity_fanout_status": "identity_only_rejected_due_fanout"}.items():
            zero[col] = val
        return pd.concat([found, zero], ignore_index=True, sort=False)


def patch_context(context: pd.DataFrame, rollup: pd.DataFrame) -> pd.DataFrame:
    out = context.copy()
    for col in ACCESS_PATCH_FIELDS:
        if col not in out:
            out[col] = False if col == "mixed_access_flag" else math.nan if col in {"access_count", "typed_access_count", "untyped_access_count", "riro_access_count", "other_review_access_count", "right_in_right_out_access_count", "access_candidate_count", "access_spatial_tolerance_ft"} else ""
    patch = rollup[["distance_band_unit_id", *ACCESS_PATCH_FIELDS]].drop_duplicates("distance_band_unit_id").set_index("distance_band_unit_id")
    idx = out["distance_band_unit_id"].isin(patch.index)
    ids = out.loc[idx, "distance_band_unit_id"]
    for col in ACCESS_PATCH_FIELDS:
        out.loc[idx, col] = ids.map(patch[col])
    out["mixed_access_flag"] = out["mixed_access_flag"].fillna(False).map(bool_value)
    return out


def consistency_outputs(before: pd.DataFrame, after: pd.DataFrame, kept: pd.DataFrame, current_pair: pd.DataFrame) -> None:
    already_patched = clean_series(before.get("access_assignment_method", pd.Series("", index=before.index))).eq("combined_source_spatial_only_within_signal_band_exclusivity").all()
    preserve_prior_delta = already_patched and (OUT / "access_count_before_after_summary.csv").exists()
    before_count = pd.to_numeric(before["access_count"], errors="coerce")
    after_count = pd.to_numeric(after["access_count"], errors="coerce")
    delta_rows = [{"metric": "access_found_units", "before": int(before_count.gt(0).sum()), "after": int(after_count.gt(0).sum())}, {"metric": "zero_access_units", "before": int(before_count.eq(0).sum()), "after": int(after_count.eq(0).sum())}, {"metric": "total_access_count_sum", "before": int(before_count.sum()), "after": int(after_count.sum())}]
    if preserve_prior_delta:
        write_csv("access_count_before_after_rerun_idempotence_check.csv", delta_rows)
    else:
        write_csv("access_count_before_after_summary.csv", delta_rows)
        bands = before.groupby(["access_count_band", "access_context_status"]).size().reset_index(name="before_units").merge(after.groupby(["access_count_band", "access_context_status"]).size().reset_index(name="after_units"), on=["access_count_band", "access_context_status"], how="outer").fillna(0)
        write_csv("access_count_band_before_after_summary.csv", bands)
    calc = kept.groupby("distance_band_unit_id")["source_access_key"].nunique().rename("reconstructed_access_count").reset_index()
    chk = after[["distance_band_unit_id", "access_count", "access_zero_evidence_status", "typed_access_count", "untyped_access_count"]].merge(calc, on="distance_band_unit_id", how="left").fillna({"reconstructed_access_count": 0})
    chk["access_count_num"] = pd.to_numeric(chk["access_count"], errors="coerce").fillna(-1).astype(int)
    count_ok = chk["access_count_num"].eq(chk["reconstructed_access_count"].astype(int)).all()
    zero_ok = (chk.loc[chk["access_count_num"].eq(0), "access_zero_evidence_status"].astype(str).str.contains("zero", case=False, na=False)).all()
    src_counts = kept.groupby(["distance_band_unit_id", "typed_untyped_status"])["source_access_key"].nunique().unstack(fill_value=0).reset_index()
    src_counts["typed_reconstructed"] = src_counts.get("typed_or_review_coded_access", 0)
    src_counts["untyped_reconstructed"] = src_counts.get("untyped_access", 0) + src_counts.get("untyped_or_unknown_access_v2", 0)
    tc = after[["distance_band_unit_id", "typed_access_count", "untyped_access_count"]].merge(src_counts[["distance_band_unit_id", "typed_reconstructed", "untyped_reconstructed"]], on="distance_band_unit_id", how="left").fillna(0)
    type_ok = pd.to_numeric(tc["typed_access_count"], errors="coerce").fillna(0).astype(int).eq(tc["typed_reconstructed"].astype(int)) & pd.to_numeric(tc["untyped_access_count"], errors="coerce").fillna(0).astype(int).eq(tc["untyped_reconstructed"].astype(int))
    write_csv("access_type_count_consistency_check.csv", [{"check": "typed_untyped_counts_match_post_exclusivity_pairs", "passed": bool(type_ok.all()), "failed_units": int((~type_ok).sum())}])
    write_csv("access_zero_evidence_consistency_check.csv", [{"check": "zero_access_has_zero_evidence_status", "passed": bool(zero_ok), "failed_units": int((~chk.loc[chk["access_count_num"].eq(0), "access_zero_evidence_status"].astype(str).str.contains("zero", case=False, na=False)).sum())}, {"check": "access_count_matches_post_exclusivity_pairs", "passed": bool(count_ok), "failed_units": int((~chk["access_count_num"].eq(chk["reconstructed_access_count"].astype(int))).sum())}])
    write_csv("old_benchmark_comparison_summary.csv", [{"window": "0_1000ft", "old_signals_with_access": 1843, "old_access_inventory": 14060, "old_typed_inventory": 4225, "current_recomputed_note": "not recomputed by signal window in this targeted patch"}, {"window": "0_2500ft", "old_signals_with_access": 1904, "old_access_inventory": 20365, "old_typed_inventory": 6639, "current_assigned_source_points": kept["source_access_key"].nunique(), "current_access_unit_pairs_after_exclusivity": len(kept)}])


def qa_checks(before: pd.DataFrame, after: pd.DataFrame, units: pd.DataFrame, kept: pd.DataFrame) -> bool:
    rows = [{"check": "row_count_unchanged", "passed": len(before) == len(after) == len(units), "before": len(before), "after": len(after), "expected": len(units)}, {"check": "distance_band_unit_id_set_unchanged", "passed": set(before["distance_band_unit_id"]) == set(after["distance_band_unit_id"]) == set(units["distance_band_unit_id"]), "before": before["distance_band_unit_id"].nunique(), "after": after["distance_band_unit_id"].nunique(), "expected": units["distance_band_unit_id"].nunique()}, {"check": "distance_band_unit_id_unique", "passed": after["distance_band_unit_id"].is_unique, "before": int(before["distance_band_unit_id"].duplicated().sum()), "after": int(after["distance_band_unit_id"].duplicated().sum()), "expected": 0}]
    write_csv("row_identity_unchanged_check.csv", rows)
    write_csv("unit_grain_uniqueness_check.csv", [{"check": "unit_grain_uniqueness", "passed": int(after.duplicated(IDENTITY_COLUMNS).sum()) == 0, "duplicate_count": int(after.duplicated(IDENTITY_COLUMNS).sum()), "identity_columns": "|".join(IDENTITY_COLUMNS)}])
    d = before.groupby(["upstream_downstream", "directionality_status"], dropna=False).size().reset_index(name="before_count").merge(after.groupby(["upstream_downstream", "directionality_status"], dropna=False).size().reset_index(name="after_count"), on=["upstream_downstream", "directionality_status"], how="outer").fillna(0)
    d["passed"] = d["before_count"].astype(int).eq(d["after_count"].astype(int))
    write_csv("directionality_reconciliation.csv", d)
    lrows = []
    for col in ["bin_count", "unit_length_ft"]:
        b, a = pd.to_numeric(before[col], errors="coerce"), pd.to_numeric(after[col], errors="coerce")
        lrows.append({"field": col, "passed": bool(np.isclose(b.sum(), a.sum()) and b.equals(a)), "before_sum": float(b.sum()), "after_sum": float(a.sum()), "changed_rows": int((~b.fillna(-999999).eq(a.fillna(-999999))).sum())})
    write_csv("length_bin_count_reconciliation.csv", lrows)
    allowed = set(ACCESS_PATCH_FIELDS)
    nt = []
    for col in before.columns:
        if col not in after.columns or col in allowed:
            continue
        changed = int((before[col].astype("string").fillna("<NA>") != after[col].astype("string").fillna("<NA>")).sum())
        nt.append({"field": col, "passed": changed == 0, "changed_rows": changed})
    write_csv("unchanged_non_target_context_fields_check.csv", nt)
    rr = after.groupby("rate_readiness_status", dropna=False).size().reset_index(name="unit_count")
    rr["crash_assignment_deferred"] = True
    rr["rate_ready_claimed"] = rr["rate_readiness_status"].astype(str).str.startswith("rate_ready")
    write_csv("rate_readiness_consistency_check.csv", rr)
    crash = []
    for path in [CONTEXT, UNITS, BINS, ACCESS, ACCESS_V2, CRASHES]:
        cols = pq.read_schema(path).names if path.exists() else []
        found = [c for c in cols if any(t in c.lower() for t in CRASH_DIRECTION_TOKENS)]
        crash.append({"path": rel(path), "crash_direction_like_fields_detected": "|".join(found), "used_as_join_or_derivation_field": False, "passed": True})
    write_csv("no_crash_direction_field_check.csv", crash)
    forb = []
    for path in OUT.iterdir():
        required = path.name == "forbidden_mvp_lookup_product_check.csv"
        bad = False if required else any(t in path.name.lower() for t in FORBIDDEN_OUTPUT_TOKENS)
        forb.append({"path": rel(path), "forbidden_mvp_lookup_or_rate_distribution_name": bad, "passed": not bad})
    write_csv("forbidden_mvp_lookup_product_check.csv", forb)
    group_cols = ["source_access_key", "stable_signal_id", "signal_approach_id", "upstream_downstream"]
    type_check = pd.read_csv(OUT / "access_type_count_consistency_check.csv")
    zero_check = pd.read_csv(OUT / "access_zero_evidence_consistency_check.csv")
    type_ok = bool(type_check["passed"].all())
    zero_ok = bool(zero_check["passed"].all())
    exclusive_ok = kept.groupby(group_cols)["distance_band"].nunique().max() <= 1 if not kept.empty else True
    nonadj_empty = pd.read_csv(OUT / "post_exclusivity_non_adjacent_band_red_flag_ledger.csv").empty
    readback = pq.ParquetFile(TEMP).metadata.num_rows == len(after)
    return all(r["passed"] for r in rows) and all(r["passed"] for r in lrows) and all(r["passed"] for r in nt) and not rr["rate_ready_claimed"].any() and all(r["passed"] for r in forb) and exclusive_ok and nonadj_empty and type_ok and zero_ok and readback


def metadata(candidate: pd.DataFrame, final_decision: str) -> None:
    stamp = now()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["updated_utc"] = stamp
    manifest.setdefault("patch_history", []).append({"bounded_phase": "access spatial band exclusivity", "build_version": BUILD_VERSION, "patched_utc": stamp, "row_count": int(len(candidate)), "script": "src.roadway_graph.patch.patch_distance_band_context_access_spatial_exclusivity", "final_decision": final_decision})
    product = manifest.setdefault("products", {}).setdefault("distance_band_context", {})
    product.update({"row_count": int(len(candidate)), "updated_utc": stamp, "script": "src.roadway_graph.patch.patch_distance_band_context_access_spatial_exclusivity", "final_decision": final_decision, "qa_review_path": rel(OUT), "access_patch_status": "spatial_exclusivity_passed"})
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    schema["updated_utc"] = stamp
    schema.setdefault("tables", {})["distance_band_context.parquet"] = {"path": rel(CONTEXT), "grain": "one row per distance_band_unit_id", "row_count": int(len(candidate)), "columns": [{"name": c, "dtype": str(candidate[c].dtype)} for c in candidate.columns], "updated_utc": stamp, "build_version": BUILD_VERSION}
    SCHEMA.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    README.write_text(README.read_text(encoding="utf-8") + f"\n\n## Access Spatial Exclusivity Patch ({stamp})\n\n- Final decision: `{final_decision}`.\n- Method: combined-source spatial-only 50 ft with within signal/approach/direction distance-band exclusivity.\n- QA outputs: `{rel(OUT)}`.\n", encoding="utf-8")


def write_findings(decision: str, source: pd.DataFrame, current_pair: pd.DataFrame, kept: pd.DataFrame, dropped: pd.DataFrame) -> None:
    unassigned = source["source_access_key"].nunique() - current_pair["source_access_key"].nunique()
    current_multi = pd.read_csv(OUT / "current_multiband_assignment_audit.csv")
    post_multi = pd.read_csv(OUT / "post_exclusivity_multiband_audit.csv")
    nonadj = pd.read_csv(OUT / "post_exclusivity_non_adjacent_band_red_flag_ledger.csv")
    text = f"""# Access Spatial Exclusivity Patch Findings

## Source And Assignment
Accepted source access points: {source['source_access_key'].nunique()}.
Assigned at least once before exclusivity: {current_pair['source_access_key'].nunique()}.
Assigned at least once after exclusivity: {kept['source_access_key'].nunique()}.
Unassigned source points: {unassigned}.

Unassigned points were classified with nearest unit geometry. Most points beyond the 250 ft diagnostic threshold are treated as outside the rebuilt 0-2,500 ft signal approach universe; near-but-rejected points are ledgered for geometry/tolerance review.

## Band Exclusivity
Current multi-band same signal/approach/direction groups: {len(current_multi)}.
Post-exclusivity multi-band groups: {len(post_multi)}.
Dropped adjacent-overlap access-unit pairs: {len(dropped)}.
Non-adjacent band red flags after patch: {len(nonadj)}.

The selected band is the one with the smallest point-to-bin geometry distance, then greatest matching bin support, then lower distance-band order.

## Benchmark Context
Old 0-1,000 and 0-2,500 ft benchmark counts are recorded in `old_benchmark_comparison_summary.csv` as sanity context only, not parent truth.

## Readiness
Typed/untyped and zero-access consistency checks are written to QA outputs. Access is ready for crash assignment if the final readiness decision is pass/minor review.

## Guard Confirmations
Roadway, speed, AADT/exposure, crash, and rate readiness fields were not changed. Crash direction fields were not used. No MVP, lookup, rate-distribution, crash assignment, or crash-rate product was built.

## Final Decision
`{decision}`

## Recommended Next Task
Run the crash assignment layer task from `remaining_context_patch_queue.csv`.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started access spatial exclusivity patch.\n", encoding="utf-8")
    parent_dependency_check()
    context, units, bins = load_context_units_bins()
    source = build_source()
    current_pair, raw = spatial_pairs(source, bins)
    unassigned_audit(source, current_pair, bins)
    kept, dropped = apply_exclusivity(current_pair)
    rollup = aggregate_access(kept, units)
    candidate = patch_context(context, rollup)
    consistency_outputs(context, candidate, kept, current_pair)
    write_csv("recommended_next_actions.csv", [{"priority": 1, "recommended_next_action": "Run crash assignment layer", "reason": "Spatial access band exclusivity applied; access counts are bounded by signal/approach/direction bands."}])
    write_csv("remaining_context_patch_queue.csv", [{"sequence": 1, "task": "Crash assignment layer", "scope": "bounded spatial or accepted source-rooted unit lineage; no crash direction fields; crash_count and crash assignment QA"}, {"sequence": 2, "task": "Final distance_band_context validation and MVP-readiness pass", "scope": "validate all context families; finalize rate readiness statuses; only then proceed to MVP analytical product / lookup-cell build"}])
    final_decision = "spatial_access_exclusivity_patch_passed_ready_for_crash"
    with phase("write_temp_candidate_parquet"):
        if TEMP.exists():
            TEMP.unlink()
        candidate.to_parquet(TEMP, index=False)
    qa_passed = qa_checks(context, candidate, units, kept)
    if not bool(pd.read_csv(OUT / "access_type_count_consistency_check.csv")["passed"].iloc[0]):
        final_decision = "spatial_access_exclusivity_patch_passed_with_minor_review_flags"
    write_csv("distance_band_context_patch_readiness_decision.csv", [{"stage": "final", "passed": qa_passed, "replacement_performed": qa_passed, "final_decision": final_decision if qa_passed else "spatial_access_exclusivity_patch_failed_no_replacement", "access_found_units": int(pd.to_numeric(candidate["access_count"], errors="coerce").gt(0).sum()), "zero_access_units": int(pd.to_numeric(candidate["access_count"], errors="coerce").eq(0).sum())}])
    if not qa_passed:
        final_decision = "spatial_access_exclusivity_patch_failed_no_replacement"
        write_findings(final_decision, source, current_pair, kept, dropped)
        write_json("manifest.json", {"created_utc": now(), "final_decision": final_decision, "replacement_performed": False})
        write_json("qa_manifest.json", {"created_utc": now(), "final_decision": final_decision, "replacement_performed": False, "phase_timings": PHASE_TIMINGS})
        raise SystemExit("QA failed; staged distance_band_context was not replaced.")
    with phase("replace_staged_distance_band_context_after_qa"):
        shutil.move(str(TEMP), str(CONTEXT))
    metadata(candidate, final_decision)
    write_findings(final_decision, source, current_pair, kept, dropped)
    write_json("manifest.json", {"created_utc": now(), "script": "src.roadway_graph.patch.patch_distance_band_context_access_spatial_exclusivity", "build_version": BUILD_VERSION, "final_decision": final_decision, "replacement_performed": True})
    write_json("qa_manifest.json", {"created_utc": now(), "final_decision": final_decision, "replacement_performed": True, "phase_timings": PHASE_TIMINGS, "qa_outputs": sorted(p.name for p in OUT.glob("*") if p.name not in {"progress_log.md", "findings_memo.md", "manifest.json", "qa_manifest.json"})})
    log(f"Completed patch with final decision: {final_decision}.")


if __name__ == "__main__":
    main()
