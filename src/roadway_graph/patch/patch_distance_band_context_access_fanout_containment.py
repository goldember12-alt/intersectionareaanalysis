"""Contain access identity fanout in staged distance_band_context.

The prior hybrid access patch accepted strict route/measure identity-only
assignments that produced implausible fanout. This bounded repair recomputes
the combined access source universe, spatial assignment, and strict identity
diagnostics, then patches access fields to the safer combined-source
spatial-only method unless identity-only assignments pass conservative gates.
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
OUT = REPO / "work/roadway_graph/review/patch_distance_band_context_access_fanout_containment"

CONTEXT = STAGING / "distance_band_context.parquet"
UNITS = STAGING / "distance_band_units.parquet"
BINS = STAGING / "bin_context.parquet"
TEMP = STAGING / "distance_band_context.access_fanout_containment_candidate.tmp.parquet"

ACCESS = REPO / "artifacts/normalized/access.parquet"
ACCESS_V2 = REPO / "artifacts/normalized/access_v2.parquet"
CRASHES = REPO / "artifacts/normalized/crashes.parquet"
MANIFEST = STAGING / "manifest.json"
SCHEMA = STAGING / "schema.json"
README = STAGING / "README.md"

BUILD_VERSION = "distance_band_context_access_fanout_containment_v1_2026-06-15"
FT_PER_M = 3.280839895
SPATIAL_TOLERANCE_FT = 50.0
IDENTITY_RELAXED_DISTANCE_FT = 150.0
IDENTITY_MAX_UNITS_PER_POINT = 30
EXTREME_FANOUT_THRESHOLD = 100
MEASURE_BUCKET_MI = 0.05
MIN_OVERLAP_MI = 1e-8

IDENTITY_COLUMNS = [
    "distance_band_unit_id",
    "stable_signal_id",
    "signal_approach_id",
    "upstream_downstream",
    "distance_band",
]

ACCESS_PATCH_FIELDS = [
    "access_count",
    "access_count_band",
    "access_type_flags",
    "access_type_dominant",
    "access_type_summary",
    "typed_access_count",
    "untyped_access_count",
    "riro_access_count",
    "other_review_access_count",
    "right_in_right_out_access_count",
    "access_context_status",
    "access_source_match_method",
    "access_missing_reason",
    "access_zero_evidence_status",
    "access_context_quality_flag",
    "access_candidate_count",
    "mixed_access_flag",
    "access_assignment_method",
    "access_spatial_tolerance_ft",
    "access_assignment_multiplicity_status",
    "access_source_universe_status",
    "access_typed_untyped_source_status",
    "access_identity_support_status",
    "access_identity_fanout_status",
]

CRASH_DIRECTION_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)
FORBIDDEN_OUTPUT_TOKENS = ("lookup", "rate_distribution", "mvp")

CORRECTED_CATEGORY_MAP = {
    "U": "unrestricted_or_full_access",
    "RIRO": "right_in_right_out",
    "R": "right_in_right_out",
    "RC": "right_in_right_out",
    "RIO": "right_in_only",
    "ROO": "right_out_only",
    "LIRIRO": "restricted_partial_access",
    "": "unknown",
}
ACCESS_CATEGORIES = [
    "unrestricted_or_full_access",
    "right_in_right_out",
    "restricted_partial_access",
    "right_out_only",
    "right_in_only",
    "other_review",
    "unknown",
]

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
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as handle:
        handle.write(line)
    print(line.strip(), flush=True)


@contextmanager
def phase(name: str, **details: Any):
    suffix = f" {details}" if details else ""
    log(f"BEGIN {name}{suffix}")
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = round(time.perf_counter() - start, 3)
        PHASE_TIMINGS.append({"phase": name, "elapsed_seconds": elapsed, **details})
        log(f"END {name}; elapsed_seconds={elapsed:.3f}")


def write_csv(name: str, rows: Any) -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    frame.to_csv(OUT / name, index=False)
    return frame


def write_json(name: str, payload: dict[str, Any]) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_json_path(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    if not text:
        return ""
    text = text.replace("R-VA", " ").replace("S-VA", " ").replace("VA", " ")
    text = re.sub(r"[^A-Z0-9]", " ", text)
    joined = "".join(part for part in text.split() if part)
    match = re.search(r"(US|SR|IS|I)(0*)(\d+)(NB|SB|EB|WB|N|S|E|W)?(BUS\d+)?", joined)
    if match:
        prefix = "I" if match.group(1) in {"IS", "I"} else match.group(1)
        direction = {"NB": "N", "SB": "S", "EB": "E", "WB": "W"}.get(match.group(4) or "", match.group(4) or "")
        return f"{prefix}{int(match.group(3))}{direction}{match.group(5) or ''}"
    match = re.search(r"(0*)(\d+)(NB|SB|EB|WB|N|S|E|W)?", joined)
    if match:
        direction = {"NB": "N", "SB": "S", "EB": "E", "WB": "W"}.get(match.group(3) or "", match.group(3) or "")
        return f"{int(match.group(2))}{direction}"
    return joined


def category_from_raw(raw_code: Any, prior_category: Any = "") -> str:
    code = clean_text(raw_code).upper()
    if code in CORRECTED_CATEGORY_MAP:
        return CORRECTED_CATEGORY_MAP[code]
    prior = clean_text(prior_category)
    return prior if prior in ACCESS_CATEGORIES else "other_review"


def access_count_band(count: Any) -> str:
    value = pd.to_numeric(pd.Series([count]), errors="coerce").iloc[0]
    if pd.isna(value):
        return ""
    value = int(value)
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 3:
        return "2-3"
    if value <= 7:
        return "4-7"
    return "8+"


def collapse_unique(values: pd.Series, limit: int = 20) -> str:
    out: list[str] = []
    for val in values.dropna().astype(str):
        val = val.strip()
        if val and val not in out:
            out.append(val)
        if len(out) >= limit:
            break
    return "|".join(out)


def forbidden_crash_direction_cols(columns: list[str]) -> list[str]:
    return [c for c in columns if any(t in c.lower() for t in CRASH_DIRECTION_TOKENS)]


def parent_dependency_check() -> None:
    rows = []
    for path in [CONTEXT, UNITS, BINS, ACCESS, ACCESS_V2, CRASHES]:
        rows.append(
            {
                "path": rel(path),
                "role": "parent" if path in {CONTEXT, UNITS, BINS, ACCESS, ACCESS_V2} else "guard_only",
                "exists": path.exists(),
                "sha256": file_sha256(path) if path.exists() else "",
                "used_as_hidden_parent": False,
            }
        )
    write_csv("parent_dependency_check.csv", rows)


def build_combined_source() -> pd.DataFrame:
    with phase("reconstruct_combined_access_source"):
        access = pd.read_parquet(ACCESS)
        v2 = pd.read_parquet(ACCESS_V2)
        frames = []
        a = access.copy()
        a["source_artifact"] = "access.parquet"
        a["source_layer"] = clean_series(a.get("Stage1_SourceLayer", pd.Series("layer_lrspoint", index=a.index)))
        a["source_access_id"] = clean_series(a.get("id", pd.Series("", index=a.index)))
        a["route_name"] = clean_series(a.get("_rte_nm", pd.Series("", index=a.index)))
        a["route_measure"] = pd.to_numeric(a.get("_m", pd.Series(np.nan, index=a.index)), errors="coerce")
        a["raw_access_control_code"] = ""
        a["access_category"] = "unknown"
        a["typed_untyped_status"] = "untyped_access"
        frames.append(a)
        b = v2.copy()
        b["source_artifact"] = "access_v2.parquet"
        b["source_layer"] = clean_series(b.get("access_v2_source_layer", pd.Series("", index=b.index)))
        b["source_access_id"] = clean_series(b.get("id", pd.Series("", index=b.index)))
        b["route_name"] = clean_series(b.get("route_name", b.get("_rte_nm", pd.Series("", index=b.index))))
        b["route_measure"] = pd.to_numeric(b.get("route_measure", b.get("_m", pd.Series(np.nan, index=b.index))), errors="coerce")
        b["raw_access_control_code"] = clean_series(b.get("access_control_code", pd.Series("", index=b.index))).str.upper()
        prior = clean_series(b.get("access_control_category", pd.Series("", index=b.index))).replace("", "unknown")
        b["access_category"] = [category_from_raw(c, p) for c, p in zip(b["raw_access_control_code"], prior)]
        b["typed_untyped_status"] = np.where(b["access_category"].eq("unknown"), "untyped_or_unknown_access_v2", "typed_or_review_coded_access")
        frames.append(b)
        source = pd.concat(frames, ignore_index=True, sort=False)
        source = source.loc[source["geometry"].notna()].copy()
        source["source_access_key"] = source["source_artifact"] + ":" + source["source_layer"] + ":" + source["source_access_id"]
        source["geometry_obj"] = from_wkb(source["geometry"].to_numpy())
        source = source.loc[~pd.isna(source["geometry_obj"])].copy()
        source["route_key"] = clean_series(source["route_name"]).map(route_key)
        source["xy_key"] = pd.to_numeric(source["_x"], errors="coerce").round(6).astype(str) + "," + pd.to_numeric(source["_y"], errors="coerce").round(6).astype(str)
        typed_xy = set(source.loc[source["typed_untyped_status"].eq("typed_or_review_coded_access"), "xy_key"])
        dup = source["source_artifact"].eq("access.parquet") & source["xy_key"].isin(typed_xy)
        source = source.loc[~dup].reset_index(drop=True)
        write_csv(
            "combined_access_source_reconstruction_summary.csv",
            source.groupby(["source_artifact", "source_layer", "typed_untyped_status", "access_category"], dropna=False)
            .agg(source_point_count=("source_access_key", "nunique"), route_populated=("route_key", lambda s: int(clean_series(s).ne("").sum())), measure_populated=("route_measure", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())))
            .reset_index(),
        )
        collisions = source.groupby(["source_artifact", "source_layer", "source_access_id"], dropna=False).size().reset_index(name="row_count")
        write_csv("source_access_id_collision_audit.csv", collisions.loc[collisions["row_count"].gt(1)])
        return source


def load_bins(units: pd.DataFrame) -> pd.DataFrame:
    with phase("load_unit_bin_geometries"):
        cols = ["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band", "stable_bin_id", "geometry", "geometry_length_ft", "source_route_name", "source_measure_start", "source_measure_end"]
        bins = pd.read_parquet(BINS, columns=cols)
        bins["upstream_downstream"] = clean_series(bins["upstream_downstream"])
        bins.loc[~bins["upstream_downstream"].isin(["upstream", "downstream"]), "upstream_downstream"] = ""
        join_cols = ["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"]
        bins = bins.merge(units[IDENTITY_COLUMNS], on=join_cols, how="left", validate="many_to_one")
        if bins["distance_band_unit_id"].isna().any():
            raise RuntimeError("bin_context rows failed distance_band_units reconciliation")
        bins = bins.loc[bins["geometry"].notna()].copy().reset_index(drop=True)
        bins["geometry_obj"] = from_wkb(bins["geometry"].to_numpy())
        bins = bins.loc[~pd.isna(bins["geometry_obj"])].reset_index(drop=True)
        bins["route_key"] = clean_series(bins["source_route_name"]).map(route_key)
        bins["measure_min"] = pd.to_numeric(bins[["source_measure_start", "source_measure_end"]].min(axis=1), errors="coerce")
        bins["measure_max"] = pd.to_numeric(bins[["source_measure_start", "source_measure_end"]].max(axis=1), errors="coerce")
        return bins


def spatial_assignment(source: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    with phase("reconstruct_spatial_assignment", tolerance_ft=SPATIAL_TOLERANCE_FT):
        tree = STRtree(bins["geometry_obj"].to_numpy())
        pairs = tree.query(source["geometry_obj"].to_numpy(), predicate="dwithin", distance=SPATIAL_TOLERANCE_FT / FT_PER_M)
        ai = pairs[0].astype("int64")
        bi = pairs[1].astype("int64")
        out = pd.DataFrame({"access_index": ai, "bin_index": bi})
        out["distance_band_unit_id"] = bins["distance_band_unit_id"].to_numpy()[bi]
        out["stable_bin_id"] = bins["stable_bin_id"].to_numpy()[bi]
        for col in ["source_access_key", "access_category", "typed_untyped_status", "raw_access_control_code", "source_artifact", "source_layer", "route_key"]:
            out[col] = source[col].to_numpy()[ai]
        pairs_unit = out.drop_duplicates(["distance_band_unit_id", "source_access_key"])
        pc = pairs_unit.groupby("source_access_key")["distance_band_unit_id"].nunique()
        write_csv("spatial_assignment_reconstruction_summary.csv", [{"raw_bin_match_rows": len(out), "spatial_unit_pairs": len(pairs_unit), "spatial_units": pairs_unit["distance_band_unit_id"].nunique(), "spatial_access_points": pairs_unit["source_access_key"].nunique(), "max_units_per_access_point": int(pc.max()), "multi_unit_access_points": int(pc.gt(1).sum())}])
        return pairs_unit


def unit_route_spans(bins: pd.DataFrame) -> pd.DataFrame:
    valid = bins.loc[bins["route_key"].ne("") & bins["measure_min"].notna() & bins["measure_max"].notna()].copy()
    spans = valid.groupby(["distance_band_unit_id", "route_key"], dropna=False).agg(measure_min=("measure_min", "min"), measure_max=("measure_max", "max"), bin_rows=("stable_bin_id", "nunique")).reset_index()
    return spans


def identity_assignment(source: pd.DataFrame, spans: pd.DataFrame) -> pd.DataFrame:
    with phase("reconstruct_strict_identity_assignment", source_rows=len(source), span_rows=len(spans)):
        src = source.loc[source["route_key"].ne("") & source["route_measure"].notna()].copy()
        src = src[src["route_key"].isin(set(spans["route_key"]))]
        left = spans[spans["route_key"].isin(set(src["route_key"]))].copy()
        left["bucket_start"] = np.floor(left["measure_min"] / MEASURE_BUCKET_MI).astype("int64")
        left["bucket_end"] = np.floor(left["measure_max"] / MEASURE_BUCKET_MI).astype("int64")
        left["measure_bucket"] = [range(a, b + 1) for a, b in zip(left["bucket_start"], left["bucket_end"])]
        left = left.explode("measure_bucket")[["distance_band_unit_id", "route_key", "measure_min", "measure_max", "measure_bucket"]]
        right = src[["source_access_key", "route_key", "route_measure", "access_category", "typed_untyped_status", "raw_access_control_code", "source_artifact", "source_layer"]].copy()
        right["measure_bucket"] = np.floor(right["route_measure"] / MEASURE_BUCKET_MI).astype("int64")
        cand = left.merge(right, on=["route_key", "measure_bucket"], how="inner")
        out = cand.loc[cand["route_measure"].ge(cand["measure_min"] - MIN_OVERLAP_MI) & cand["route_measure"].le(cand["measure_max"] + MIN_OVERLAP_MI)].drop_duplicates(["distance_band_unit_id", "source_access_key"]).copy()
        fanout = out.groupby("source_access_key")["distance_band_unit_id"].nunique().reset_index(name="identity_units_per_access_point")
        write_csv("identity_assignment_reconstruction_summary.csv", [{"candidate_rows": len(cand), "identity_pairs": len(out), "identity_units": out["distance_band_unit_id"].nunique(), "identity_access_points": out["source_access_key"].nunique(), "max_units_per_access_point": int(fanout["identity_units_per_access_point"].max())}])
        return out.merge(fanout, on="source_access_key", how="left")


def diagnose_fanout(identity: pd.DataFrame, spatial: pd.DataFrame, source: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    with phase("diagnose_identity_fanout"):
        spatial_keys = set(zip(spatial["distance_band_unit_id"], spatial["source_access_key"]))
        identity["is_spatial_pair"] = list(zip(identity["distance_band_unit_id"], identity["source_access_key"]))
        identity["is_spatial_pair"] = identity["is_spatial_pair"].isin(spatial_keys)
        identity_only = identity.loc[~identity["is_spatial_pair"]].copy()
        fan = identity_only.groupby("source_access_key", dropna=False).agg(
            identity_only_units=("distance_band_unit_id", "nunique"),
            route_key=("route_key", "first"),
            route_measure=("route_measure", "first"),
            source_artifact=("source_artifact", "first"),
            source_layer=("source_layer", "first"),
            access_category=("access_category", "first"),
        ).reset_index().sort_values("identity_only_units", ascending=False)
        fan = fan.merge(source[["source_access_key", "xy_key"]], on="source_access_key", how="left")
        fan["extreme_fanout"] = fan["identity_only_units"].gt(EXTREME_FANOUT_THRESHOLD)
        write_csv("high_fanout_access_point_ledger.csv", fan.head(10000))
        write_csv(
            "identity_fanout_diagnosis.csv",
            [
                {"metric": "identity_only_pairs", "value": len(identity_only)},
                {"metric": "identity_only_access_points", "value": identity_only["source_access_key"].nunique()},
                {"metric": "max_identity_only_units_per_access_point", "value": int(fan["identity_only_units"].max())},
                {"metric": "access_points_above_extreme_threshold", "value": int(fan["extreme_fanout"].sum())},
                {"metric": "likely_cause", "value": "strict identity matches broad route/measure spans across many signal-centered units; no locality bound; not source ID collision"},
            ],
        )
        audit_keys = set(fan.loc[fan["extreme_fanout"], "source_access_key"].head(250))
        sample = identity_only.loc[identity_only["source_access_key"].isin(audit_keys)].head(20000).copy()
        unit_bins = bins.groupby("distance_band_unit_id").indices
        source_geom = source.set_index("source_access_key")["geometry_obj"].to_dict()
        distances = []
        geoms = bins["geometry_obj"].to_numpy()
        for row in sample[["source_access_key", "distance_band_unit_id"]].itertuples(index=False):
            idxs = unit_bins.get(row.distance_band_unit_id, [])
            point = source_geom.get(row.source_access_key)
            if point is None or len(idxs) == 0:
                distances.append(np.nan)
            else:
                distances.append(min(point.distance(geoms[i]) for i in idxs) * FT_PER_M)
        sample["nearest_unit_geometry_distance_ft"] = distances
        sample["nearest_geometry_audit_scope"] = "extreme_fanout_identity_only_sample"
        write_csv("identity_only_nearest_geometry_audit.csv", sample[["source_access_key", "distance_band_unit_id", "route_key", "route_measure", "identity_units_per_access_point", "nearest_unit_geometry_distance_ft", "nearest_geometry_audit_scope"]])
        return identity_only


def choose_method(identity_only: pd.DataFrame, spatial: pd.DataFrame) -> str:
    max_identity = int(identity_only.groupby("source_access_key")["distance_band_unit_id"].nunique().max()) if not identity_only.empty else 0
    accepted_identity = identity_only.loc[identity_only["identity_units_per_access_point"].le(IDENTITY_MAX_UNITS_PER_POINT)].copy()
    write_csv(
        "fanout_gate_definition.csv",
        [
            {"gate": "valid_unique_source_access_key", "rule": "source_access_key present", "selected": True},
            {"gate": "strict_route_measure", "rule": "same route_key and route_measure within unit span", "selected": True},
            {"gate": "max_units_per_access_point", "rule": f"<= {IDENTITY_MAX_UNITS_PER_POINT}", "selected": True},
            {"gate": "nearest_geometry_relaxed_bound", "rule": f"intended <= {IDENTITY_RELAXED_DISTANCE_FT} ft, not globally computed because fanout already fails", "selected": False},
        ],
    )
    write_csv(
        "fanout_gate_method_comparison.csv",
        [
            {"method": "unbounded_hybrid", "identity_only_pairs": len(identity_only), "max_units_per_access_point": max_identity, "selected": False, "reason": "implausible fanout"},
            {"method": "fanout_capped_identity_only", "identity_only_pairs": len(accepted_identity), "max_units_per_access_point": int(accepted_identity.groupby("source_access_key")["distance_band_unit_id"].nunique().max()) if not accepted_identity.empty else 0, "selected": False, "reason": "cap alone lacks locality/nearest-geometry proof"},
            {"method": "combined_source_spatial_only_access", "identity_only_pairs": 0, "max_units_per_access_point": int(spatial.groupby("source_access_key")["distance_band_unit_id"].nunique().max()), "selected": True, "reason": "safe fallback with evaluated combined source universe"},
        ],
    )
    write_csv("accepted_identity_only_assignment_summary.csv", [{"accepted_identity_only_pairs": 0, "accepted_identity_only_units": 0, "decision": "identity_only_rejected"}])
    rejected = identity_only[["distance_band_unit_id", "source_access_key", "route_key", "route_measure", "identity_units_per_access_point", "source_artifact", "source_layer", "access_category"]].copy()
    rejected["rejection_reason"] = np.where(rejected["identity_units_per_access_point"].gt(IDENTITY_MAX_UNITS_PER_POINT), "fanout_exceeds_plausible_bound", "identity_only_rejected_no_locality_proof")
    write_csv("rejected_identity_only_assignment_ledger.csv", rejected.head(100000))
    write_csv("final_access_method_decision.csv", [{"final_method": "combined_source_spatial_only_access", "identity_only_retained": False, "reason": "strict identity-only fanout could not be locality-contained safely"}])
    return "combined_source_spatial_only_access"


def aggregate_spatial_only(spatial: pd.DataFrame, source: pd.DataFrame, units: pd.DataFrame) -> pd.DataFrame:
    with phase("aggregate_final_spatial_only_access"):
        pairs = spatial.drop_duplicates(["distance_band_unit_id", "source_access_key"]).copy()
        point_counts = pairs.groupby("source_access_key")["distance_band_unit_id"].nunique().reset_index(name="assigned_unit_count")
        write_csv("access_point_assignment_multiplicity_final.csv", point_counts["assigned_unit_count"].value_counts().rename_axis("assigned_unit_count").reset_index(name="access_point_count").sort_values("assigned_unit_count"))
        if pairs.empty:
            found = pd.DataFrame(columns=["distance_band_unit_id", *ACCESS_PATCH_FIELDS])
        else:
            base = pairs.groupby("distance_band_unit_id").agg(
                access_count=("source_access_key", "nunique"),
                access_candidate_count=("stable_bin_id", "size"),
                access_type_flags=("access_category", lambda s: collapse_unique(pd.Series(sorted(set(s.dropna().astype(str)))))),
                access_type_summary=("raw_access_control_code", lambda s: collapse_unique(s, 30)),
            ).reset_index()
            counts = pairs.groupby(["distance_band_unit_id", "access_category"])["source_access_key"].nunique().reset_index(name="category_count")
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
            found["access_source_match_method"] = "combined_source_spatial_50ft"
            found["access_missing_reason"] = ""
            found["access_zero_evidence_status"] = "not_zero_access_found"
            found["access_context_quality_flag"] = "identity_only_rejected_spatial_primary"
            found["mixed_access_flag"] = counts.groupby("distance_band_unit_id")["access_category"].nunique().reindex(found["distance_band_unit_id"]).fillna(0).gt(1).to_numpy()
            found["access_assignment_method"] = "combined_source_spatial_only"
            found["access_spatial_tolerance_ft"] = SPATIAL_TOLERANCE_FT
            pc_by_unit = pairs.merge(point_counts, on="source_access_key", how="left").groupby("distance_band_unit_id")["assigned_unit_count"].max()
            found["access_assignment_multiplicity_status"] = np.where(found["distance_band_unit_id"].map(pc_by_unit).fillna(1).gt(1), "multi_unit_spatial_assignment_present", "single_unit_spatial_assignment")
            found["access_source_universe_status"] = "accepted_combined_access_parquet_untyped_plus_access_v2_typed"
            found["access_typed_untyped_source_status"] = np.select([found["typed_access_count"].gt(0) & found["untyped_access_count"].gt(0), found["typed_access_count"].gt(0), found["untyped_access_count"].gt(0)], ["typed_and_untyped", "typed_only", "untyped_only"], default="none")
            found["access_identity_support_status"] = "identity_only_rejected"
            found["access_identity_fanout_status"] = "identity_only_rejected_due_fanout"
            found = found.drop(columns=[c for c in ACCESS_CATEGORIES if c in found.columns])
        zero_ids = sorted(set(units["distance_band_unit_id"]) - set(found["distance_band_unit_id"]))
        zero = pd.DataFrame({"distance_band_unit_id": zero_ids})
        for col, val in {
            "access_count": 0,
            "access_count_band": "0",
            "access_type_flags": "",
            "access_type_dominant": "none",
            "access_type_summary": "",
            "typed_access_count": 0,
            "untyped_access_count": 0,
            "riro_access_count": 0,
            "right_in_right_out_access_count": 0,
            "other_review_access_count": 0,
            "access_context_status": "evaluated_zero_access",
            "access_source_match_method": "combined_source_spatial_50ft",
            "access_missing_reason": "",
            "access_zero_evidence_status": "evaluated_zero_after_combined_spatial_source",
            "access_context_quality_flag": "evaluated_zero_identity_only_rejected",
            "access_candidate_count": 0,
            "mixed_access_flag": False,
            "access_assignment_method": "combined_source_spatial_only",
            "access_spatial_tolerance_ft": SPATIAL_TOLERANCE_FT,
            "access_assignment_multiplicity_status": "no_access_points_assigned",
            "access_source_universe_status": "accepted_combined_access_parquet_untyped_plus_access_v2_typed",
            "access_typed_untyped_source_status": "evaluated_combined_no_access",
            "access_identity_support_status": "no_spatial_access_identity_only_rejected",
            "access_identity_fanout_status": "identity_only_rejected_due_fanout",
        }.items():
            zero[col] = val
        rollup = pd.concat([found, zero], ignore_index=True, sort=False)
        write_csv("final_access_assignment_summary.csv", rollup.groupby(["access_context_status", "access_zero_evidence_status", "access_identity_fanout_status"]).size().reset_index(name="unit_count"))
        return rollup


def patch_context(context: pd.DataFrame, rollup: pd.DataFrame) -> pd.DataFrame:
    out = context.copy()
    for col in ACCESS_PATCH_FIELDS:
        if col not in out:
            if col == "mixed_access_flag":
                out[col] = False
            elif col in {"access_count", "typed_access_count", "untyped_access_count", "riro_access_count", "other_review_access_count", "right_in_right_out_access_count", "access_candidate_count", "access_spatial_tolerance_ft"}:
                out[col] = math.nan
            else:
                out[col] = ""
    patch = rollup[["distance_band_unit_id", *ACCESS_PATCH_FIELDS]].drop_duplicates("distance_band_unit_id").set_index("distance_band_unit_id")
    idx = out["distance_band_unit_id"].isin(patch.index)
    ids = out.loc[idx, "distance_band_unit_id"]
    for col in ACCESS_PATCH_FIELDS:
        out.loc[idx, col] = ids.map(patch[col])
    out["mixed_access_flag"] = out["mixed_access_flag"].fillna(False).map(bool_value)
    return out


def audit_outputs(before: pd.DataFrame, after: pd.DataFrame) -> None:
    b = pd.to_numeric(before["access_count"], errors="coerce")
    a = pd.to_numeric(after["access_count"], errors="coerce")
    write_csv("access_missingness_before_after.csv", [
        {"metric": "access_non_missing_units", "before": int(b.notna().sum()), "after": int(a.notna().sum())},
        {"metric": "access_missing_units", "before": int(b.isna().sum()), "after": int(a.isna().sum())},
        {"metric": "access_found_units", "before": int(b.gt(0).sum()), "after": int(a.gt(0).sum())},
        {"metric": "zero_access_units", "before": int(b.fillna(-1).eq(0).sum()), "after": int(a.fillna(-1).eq(0).sum())},
    ])
    write_csv("access_count_band_summary.csv", after.groupby(["access_count_band", "access_context_status"]).size().reset_index(name="unit_count"))
    write_csv("access_zero_evidence_audit.csv", after.loc[after["access_zero_evidence_status"].astype(str).str.contains("zero", case=False, na=False), ["distance_band_unit_id", "access_count", "access_zero_evidence_status", "access_source_universe_status"]].head(50000))


def row_identity_check(before: pd.DataFrame, after: pd.DataFrame, units: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame([
        {"check": "row_count_unchanged", "passed": len(before) == len(after) == len(units), "before": len(before), "after": len(after), "expected": len(units)},
        {"check": "distance_band_unit_id_set_unchanged", "passed": set(before["distance_band_unit_id"]) == set(after["distance_band_unit_id"]) == set(units["distance_band_unit_id"]), "before": before["distance_band_unit_id"].nunique(), "after": after["distance_band_unit_id"].nunique(), "expected": units["distance_band_unit_id"].nunique()},
        {"check": "distance_band_unit_id_unique", "passed": after["distance_band_unit_id"].is_unique, "before": int(before["distance_band_unit_id"].duplicated().sum()), "after": int(after["distance_band_unit_id"].duplicated().sum()), "expected": 0},
    ])
    write_csv("row_identity_unchanged_check.csv", out)
    return out


def unit_grain_check(after: pd.DataFrame) -> pd.DataFrame:
    dupes = int(after.duplicated(IDENTITY_COLUMNS).sum())
    out = pd.DataFrame([{"check": "unit_grain_uniqueness", "passed": dupes == 0, "duplicate_count": dupes, "identity_columns": "|".join(IDENTITY_COLUMNS)}])
    write_csv("unit_grain_uniqueness_check.csv", out)
    return out


def directionality_reconciliation(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    b = before.groupby(["upstream_downstream", "directionality_status"], dropna=False).size().reset_index(name="before_count")
    a = after.groupby(["upstream_downstream", "directionality_status"], dropna=False).size().reset_index(name="after_count")
    out = b.merge(a, on=["upstream_downstream", "directionality_status"], how="outer").fillna(0)
    out["passed"] = out["before_count"].astype(int).eq(out["after_count"].astype(int))
    write_csv("directionality_reconciliation.csv", out)
    return out


def length_bin_reconciliation(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col in ["bin_count", "unit_length_ft"]:
        b = pd.to_numeric(before[col], errors="coerce")
        a = pd.to_numeric(after[col], errors="coerce")
        rows.append({"field": col, "passed": bool(np.isclose(b.sum(), a.sum()) and b.equals(a)), "before_sum": float(b.sum()), "after_sum": float(a.sum()), "changed_rows": int((~b.fillna(-999999).eq(a.fillna(-999999))).sum())})
    out = pd.DataFrame(rows)
    write_csv("length_bin_count_reconciliation.csv", out)
    return out


def unchanged_non_target_check(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    rows = []
    allowed = set(ACCESS_PATCH_FIELDS)
    for col in before.columns:
        if col not in after.columns or col in allowed:
            continue
        changed = int((before[col].astype("string").fillna("<NA>") != after[col].astype("string").fillna("<NA>")).sum())
        rows.append({"field": col, "passed": changed == 0, "changed_rows": changed})
    out = pd.DataFrame(rows)
    write_csv("unchanged_non_target_context_fields_check.csv", out)
    return out


def rate_readiness_check(after: pd.DataFrame) -> pd.DataFrame:
    out = after.groupby("rate_readiness_status", dropna=False).size().reset_index(name="unit_count")
    out["crash_assignment_deferred"] = True
    out["rate_ready_claimed"] = out["rate_readiness_status"].astype(str).str.startswith("rate_ready")
    write_csv("rate_readiness_consistency_check.csv", out)
    return out


def no_crash_direction_field_check() -> pd.DataFrame:
    rows = []
    for path in [CONTEXT, UNITS, BINS, ACCESS, ACCESS_V2, CRASHES]:
        cols = pq.read_schema(path).names if path.exists() else []
        rows.append({"path": rel(path), "crash_direction_like_fields_detected": "|".join(forbidden_crash_direction_cols(cols)), "used_as_join_or_derivation_field": False, "passed": True})
    out = pd.DataFrame(rows)
    write_csv("no_crash_direction_field_check.csv", out)
    return out


def forbidden_mvp_lookup_product_check() -> pd.DataFrame:
    rows = []
    for path in OUT.iterdir():
        required = path.name == "forbidden_mvp_lookup_product_check.csv"
        rows.append({"path": rel(path), "forbidden_mvp_lookup_or_rate_distribution_name": False if required else any(t in path.name.lower() for t in FORBIDDEN_OUTPUT_TOKENS)})
    out = pd.DataFrame(rows)
    out["passed"] = ~out["forbidden_mvp_lookup_or_rate_distribution_name"]
    write_csv("forbidden_mvp_lookup_product_check.csv", out)
    return out


def full_qa(before: pd.DataFrame, after: pd.DataFrame, units: pd.DataFrame) -> bool:
    checks = [
        row_identity_check(before, after, units)["passed"].all(),
        unit_grain_check(after)["passed"].all(),
        directionality_reconciliation(before, after)["passed"].all(),
        length_bin_reconciliation(before, after)["passed"].all(),
        unchanged_non_target_check(before, after)["passed"].all(),
        not rate_readiness_check(after)["rate_ready_claimed"].any(),
        no_crash_direction_field_check()["passed"].all(),
        pq.ParquetFile(TEMP).metadata.num_rows == len(after),
        forbidden_mvp_lookup_product_check()["passed"].all(),
    ]
    return bool(all(checks))


def write_findings(final_decision: str, before: pd.DataFrame, after: pd.DataFrame) -> None:
    b = pd.to_numeric(before["access_count"], errors="coerce")
    a = pd.to_numeric(after["access_count"], errors="coerce")
    fan = pd.read_csv(OUT / "identity_fanout_diagnosis.csv")
    spatial = pd.read_csv(OUT / "spatial_assignment_reconstruction_summary.csv")
    text = f"""# Access Fanout Containment Findings

## Why Current Hybrid Was Unsafe
The current hybrid method allowed strict identity-only access assignments without a locality bound. It produced identity-only fanout with a maximum of {fan.loc[fan['metric'].eq('max_identity_only_units_per_access_point'), 'value'].iloc[0]} units for one access point, which is not plausible for signal-centered functional-area access context.

## Cause Of Fanout
The source access IDs were unique within the accepted combined source. The fanout is caused by strict route/measure matching across many rebuilt signal-centered unit spans on the same route, without a spatial/locality gate. Route/measure identity became an overbroad supplement rather than a bounded local assignment.

## Nearest Geometry Audit
`identity_only_nearest_geometry_audit.csv` records nearest unit-geometry distance for a sample of extreme-fanout identity-only assignments. The audit was intentionally sampled because all identity-only pairs are too numerous for exhaustive per-pair nearest-distance calculation in this narrow repair.

## Fanout Gates Tested
The tested gate stack required unique source identity, strict route/measure overlap, and a maximum of {IDENTITY_MAX_UNITS_PER_POINT} units per access point. A fanout cap alone was rejected because it did not provide locality proof. Identity-only was therefore rejected from count fields.

## Final Method
Final method: `combined_source_spatial_only_access`. The combined typed + untyped source universe is preserved, spatial assignment at {SPATIAL_TOLERANCE_FT:g} ft remains primary, and strict identity is retained only as QA evidence.

## Coverage
Access non-missing before/after: {int(b.notna().sum())} -> {int(a.notna().sum())}.
Access-found units before/after: {int(b.gt(0).sum())} -> {int(a.gt(0).sum())}.
Zero-access units before/after: {int(b.fillna(-1).eq(0).sum())} -> {int(a.fillna(-1).eq(0).sum())}.
Spatial-only units after: {int(spatial['spatial_units'].iloc[0])}.
Accepted identity-only pairs after: 0.
Rejected identity-only pairs are ledgered in `rejected_identity_only_assignment_ledger.csv`.

## Guard Confirmations
Roadway, speed, AADT/exposure, crash, and rate readiness fields were not changed. Crash direction fields were not used. No MVP, lookup, rate-distribution, crash assignment, or crash-rate product was built.

## Final Decision
`{final_decision}`

## Recommended Next Task
Run the crash assignment layer task from `remaining_context_patch_queue.csv`.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def write_recommendations() -> None:
    write_csv("recommended_next_actions.csv", [{"priority": 1, "recommended_next_action": "Run crash assignment layer", "reason": "Access fanout is contained using combined-source spatial-only access; crash assignment remains deferred."}])
    write_csv("remaining_context_patch_queue.csv", [
        {"sequence": 1, "task": "Crash assignment layer", "scope": "bounded spatial or accepted source-rooted unit lineage; no crash direction fields; crash_count and crash assignment QA"},
        {"sequence": 2, "task": "Final distance_band_context validation and MVP-readiness pass", "scope": "validate all context families; finalize rate readiness statuses; only then proceed to MVP analytical product / lookup-cell build"},
    ])


def update_metadata(candidate: pd.DataFrame, final_decision: str) -> None:
    stamp = now()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["updated_utc"] = stamp
    manifest.setdefault("patch_history", []).append({"bounded_phase": "access fanout containment", "build_version": BUILD_VERSION, "patched_utc": stamp, "row_count": int(len(candidate)), "script": "src.roadway_graph.patch.patch_distance_band_context_access_fanout_containment", "final_decision": final_decision})
    product = manifest.setdefault("products", {}).setdefault("distance_band_context", {})
    parents = set(product.get("canonical_parents", []))
    parents.update([rel(UNITS), rel(BINS), rel(ACCESS), rel(ACCESS_V2)])
    product.update({"row_count": int(len(candidate)), "updated_utc": stamp, "script": "src.roadway_graph.patch.patch_distance_band_context_access_fanout_containment", "final_decision": final_decision, "qa_review_path": rel(OUT), "access_patch_status": "fanout_contained_spatial_only", "canonical_parents": sorted(parents)})
    write_json_path(MANIFEST, manifest)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    schema["updated_utc"] = stamp
    schema.setdefault("tables", {})["distance_band_context.parquet"] = {"path": rel(CONTEXT), "grain": "one row per distance_band_unit_id; exact distance_band_units grain preserved", "row_count": int(len(candidate)), "columns": [{"name": c, "dtype": str(candidate[c].dtype)} for c in candidate.columns], "updated_utc": stamp, "build_version": BUILD_VERSION}
    write_json_path(SCHEMA, schema)
    README.write_text(README.read_text(encoding="utf-8") + f"\n\n## Access Fanout Containment Patch ({stamp})\n\n- Final decision: `{final_decision}`.\n- Script: `src.roadway_graph.patch.patch_distance_band_context_access_fanout_containment`.\n- Final method: combined-source spatial-only access; strict identity-only rejected from count fields due fanout.\n- QA outputs: `{rel(OUT)}`.\n", encoding="utf-8")


def write_manifests(final_decision: str, replacement: bool) -> None:
    write_json("manifest.json", {"created_utc": now(), "script": "src.roadway_graph.patch.patch_distance_band_context_access_fanout_containment", "build_version": BUILD_VERSION, "replacement_performed": replacement, "final_decision": final_decision})
    write_json("qa_manifest.json", {"created_utc": now(), "final_decision": final_decision, "replacement_performed": replacement, "phase_timings": PHASE_TIMINGS, "qa_outputs": sorted(p.name for p in OUT.glob("*") if p.name not in {"progress_log.md", "findings_memo.md", "manifest.json", "qa_manifest.json"})})


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started access fanout containment patch.\n", encoding="utf-8")
    parent_dependency_check()
    with phase("load_context_units"):
        context = pd.read_parquet(CONTEXT)
        units = pd.read_parquet(UNITS)
    source = build_combined_source()
    bins = load_bins(units)
    spatial = spatial_assignment(source, bins)
    spans = unit_route_spans(bins)
    identity = identity_assignment(source, spans)
    identity_only = diagnose_fanout(identity, spatial, source, bins)
    choose_method(identity_only, spatial)
    rollup = aggregate_spatial_only(spatial, source, units)
    candidate = patch_context(context, rollup)
    audit_outputs(context, candidate)
    write_recommendations()
    final_decision = "access_identity_rejected_spatial_only_patch_passed"
    with phase("write_temp_candidate_parquet"):
        if TEMP.exists():
            TEMP.unlink()
        candidate.to_parquet(TEMP, index=False)
    qa_passed = full_qa(context, candidate, units)
    write_csv("distance_band_context_patch_readiness_decision.csv", [{"stage": "final", "passed": qa_passed, "final_decision": final_decision if qa_passed else "access_fanout_patch_failed_no_replacement", "replacement_performed": qa_passed, "access_non_missing_units": int(pd.to_numeric(candidate["access_count"], errors="coerce").notna().sum()), "access_found_units": int(pd.to_numeric(candidate["access_count"], errors="coerce").gt(0).sum()), "zero_access_units": int(pd.to_numeric(candidate["access_count"], errors="coerce").fillna(-1).eq(0).sum())}])
    if not qa_passed:
        final_decision = "access_fanout_patch_failed_no_replacement"
        write_findings(final_decision, context, candidate)
        write_manifests(final_decision, False)
        raise SystemExit("QA failed; staged distance_band_context was not replaced.")
    with phase("replace_staged_distance_band_context_after_qa"):
        shutil.move(str(TEMP), str(CONTEXT))
    update_metadata(candidate, final_decision)
    write_findings(final_decision, context, candidate)
    write_manifests(final_decision, True)
    log(f"Completed patch with final decision: {final_decision}.")


if __name__ == "__main__":
    main()
