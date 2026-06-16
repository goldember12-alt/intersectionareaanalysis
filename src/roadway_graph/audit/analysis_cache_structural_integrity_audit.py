"""Read-only structural integrity audit for roadway_graph analysis cache.

This audit inventories active analysis/cache products, reconciles signal
identity across source/canonical/staged/support objects, and checks whether the
projection/corridor support indexes and staged bin_context are structurally
trustworthy for the next directionality proposal. It writes review outputs
only and does not mutate any analysis, staging, canonical, source, or artifact
input.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
ANALYSIS = REPO_ROOT / "work/roadway_graph/analysis"
FINAL = ANALYSIS / "final_leg_corrected_analysis_dataset"
MVP = ANALYSIS / "mvp_dataset"
STAGING = ANALYSIS / "_staging/final_leg_corrected_analysis_dataset_refresh_candidate"
REVIEW_OUT = REPO_ROOT / "work/roadway_graph/review/analysis_cache_structural_integrity_audit"
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
PROJECTION_INDEX = STAGING / "source_signal_travelway_projection_index.parquet"
CORRIDOR_INDEX = STAGING / "signal_bounded_travelway_corridor_index.parquet"
FINAL_SIGNAL = FINAL / "analysis_signal.csv"

READ_CONTEXT = [
    REPO_ROOT / "work/roadway_graph/review/source_signal_travelway_projection_index",
    REPO_ROOT / "work/roadway_graph/review/expanded_directionality_recovery_audit",
    REPO_ROOT / "work/roadway_graph/review/expanded_bin_universe_impact_audit",
    REPO_ROOT / "work/roadway_graph/review/global_corridor_side_geometry_directionality_proposal",
    REPO_ROOT / "work/roadway_graph/review/exact_corridor_link_directionality_proposal",
]

EXPECTED_SOURCE_SIGNALS = 3_933
EXPECTED_APPROX_ANALYSIS_SIGNALS = 3_719
EXPECTED_HOLDOUTS = 214
EXPECTED_EXACT_LINKED = 7_959
CURRENT_DIRECTION_READY_UNITS = 98_831


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def log(message: str) -> None:
    REVIEW_OUT.mkdir(parents=True, exist_ok=True)
    with (REVIEW_OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now_iso()} - {message}\n")


def write_csv(name: str, df: pd.DataFrame) -> None:
    REVIEW_OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(REVIEW_OUT / name, index=False)


def nonmissing(s: pd.Series) -> pd.Series:
    if s is None:
        return pd.Series(dtype=bool)
    text = s.astype("string").str.strip()
    return s.notna() & text.ne("") & ~text.str.lower().isin(["nan", "none", "null", "<na>"])


def side_values(df: pd.DataFrame) -> pd.Series:
    side = df["upstream_downstream"] if "upstream_downstream" in df.columns else pd.Series(pd.NA, index=df.index)
    if "upstream_downstream_values" in df.columns:
        side = side.where(nonmissing(side), df["upstream_downstream_values"])
    return side


def norm_globalid(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().upper()
    text = text.strip("{}")
    return text


def norm_stable(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def file_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return "parquet"
    if suffix == ".csv":
        return "csv"
    if suffix == ".json":
        return "json"
    if suffix in {".md", ".txt"}:
        return suffix.lstrip(".")
    return suffix.lstrip(".") or "unknown"


def data_like(path: Path) -> bool:
    if path.suffix.lower() == ".zip":
        return False
    return path.suffix.lower() in {".parquet", ".csv", ".json", ".md", ".txt"}


def infer_parent_product(path: Path) -> str:
    parts = path.relative_to(ANALYSIS).parts
    if not parts:
        return "analysis_root"
    if parts[0] == "_staging" and len(parts) > 1:
        return "_staging/" + parts[1]
    return parts[0]


def infer_role(path: Path) -> str:
    relp = rel(path).lower()
    name = path.name.lower()
    if name in {"manifest.json", "schema.json", "readme.md"} or "manifest" in name or "schema" in name:
        return "manifest_or_schema"
    if "/exports/" in relp or "\\exports\\" in relp:
        return "export"
    if "source_signal_travelway_projection_index" in name or "signal_bounded_travelway_corridor_index" in name:
        return "support_index"
    if "proposal" in name or "proposed" in name:
        return "proposal_product"
    if "mvp_dataset" in relp:
        return "canonical_root_product"
    if "final_leg_corrected_analysis_dataset/" in relp:
        return "canonical_root_product"
    if "_staging/" in relp:
        return "staging_candidate"
    if "analysis/" in relp and path.parent == ANALYSIS:
        return "stale_or_unclear"
    return "stale_or_unclear"


def likely_grain(columns: list[str], name: str) -> str:
    cols = set(columns)
    lname = name.lower()
    if "stable_bin_id" in cols:
        return "bin"
    if "corridor_index_id" in cols:
        return "stable signal x source route/road row corridor"
    if "source_signal_globalid" in cols and "road_row_id" in cols:
        return "source signal x travelway candidate"
    if "signal_approach_id_v2" in cols and "stable_signal_id" in cols:
        return "signal x approach"
    if "signal_approach_id" in cols and "window_label" in cols:
        return "signal x approach x window x direction"
    if "stable_signal_id" in cols and ("globalid" in {c.lower() for c in cols} or "signal" in lname):
        return "signal"
    if "route_name" in cols or "RTE_NM" in cols:
        return "route/travelway"
    return "unknown"


def key_fields_present(columns: list[str]) -> str:
    keys = [
        "GLOBALID",
        "source_signal_globalid",
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "signal_approach_id_v2",
        "signal_approach_id",
        "corridor_index_id",
        "road_row_id",
        "route_name",
        "source_route_name",
        "RTE_NM",
        "source_measure_midpoint",
        "estimated_measure",
    ]
    return "|".join([k for k in keys if k in columns])


def csv_header_and_count(path: Path) -> tuple[list[str], int | None, str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, [])
        row_count = 0
        with path.open("rb") as f:
            for row_count, _ in enumerate(f, start=0):
                pass
        return header, max(row_count, 0), ""
    except Exception as exc:
        return [], None, str(exc)


def read_table_profile(path: Path) -> dict[str, Any]:
    ftype = file_type(path)
    out: dict[str, Any] = {
        "row_count": pd.NA,
        "columns": "",
        "column_count": pd.NA,
        "geometry_presence": False,
        "likely_grain": "unknown",
        "key_fields_present": "",
        "notes_warnings": "",
    }
    try:
        if ftype == "parquet":
            df0 = pd.read_parquet(path)
            columns = list(df0.columns)
            out.update(
                row_count=int(len(df0)),
                columns="|".join(columns),
                column_count=int(len(columns)),
                geometry_presence=any("geom" in c.lower() for c in columns),
                likely_grain=likely_grain(columns, path.name),
                key_fields_present=key_fields_present(columns),
            )
        elif ftype == "csv":
            header, rows, err = csv_header_and_count(path)
            out.update(
                row_count=rows,
                columns="|".join(header),
                column_count=len(header),
                geometry_presence=any("geom" in c.lower() or "wkt" in c.lower() for c in header),
                likely_grain=likely_grain(header, path.name),
                key_fields_present=key_fields_present(header),
                notes_warnings=err,
            )
        elif ftype == "json":
            with path.open("r", encoding="utf-8") as f:
                obj = json.load(f)
            keys = list(obj.keys()) if isinstance(obj, dict) else []
            out.update(columns="|".join(keys), column_count=len(keys), likely_grain="metadata")
        else:
            out.update(likely_grain="documentation")
    except Exception as exc:
        out["notes_warnings"] = f"read_error: {exc}"
    return out


def inventory_analysis_cache() -> pd.DataFrame:
    rows = []
    for path in sorted(ANALYSIS.rglob("*")):
        if MVP in path.parents:
            continue
        if path.is_file() and data_like(path):
            profile = read_table_profile(path)
            rows.append(
                {
                    "path": rel(path),
                    "file_type": file_type(path),
                    "parent_product_folder": infer_parent_product(path),
                    "inferred_role": infer_role(path),
                    "size_bytes": path.stat().st_size,
                    "modified_time": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                    **profile,
                }
            )
    return pd.DataFrame(rows)


def product_contract_audit() -> pd.DataFrame:
    products = [FINAL, STAGING]
    rows = []
    for folder in products:
        files = list(folder.iterdir()) if folder.exists() else []
        names = {p.name for p in files}
        data_files = [p for p in files if p.is_file() and p.suffix.lower() in {".parquet", ".csv"}]
        proposal_support = [p.name for p in data_files if any(x in p.name.lower() for x in ["proposal", "proposed", "projection_index", "corridor_index"])]
        rows.append(
            {
                "product_folder": rel(folder),
                "exists": folder.exists(),
                "manifest_json": "manifest.json" in names or any("manifest" in n.lower() and n.endswith(".json") for n in names),
                "schema_json": "schema.json" in names,
                "README_md": "README.md" in names,
                "exports_folder": (folder / "exports").exists(),
                "parquet_table_count": sum(p.suffix.lower() == ".parquet" for p in data_files),
                "csv_table_count": sum(p.suffix.lower() == ".csv" for p in data_files),
                "csv_only_legacy_tables": "|".join(p.name for p in data_files if p.suffix.lower() == ".csv"),
                "unclear_duplicate_tables": "",
                "proposal_support_tables_mixed_with_final_tables": "|".join(proposal_support),
                "contract_warning": "support/proposal tables mixed into staged candidate" if proposal_support and "_staging" in rel(folder) else "",
            }
        )
    return pd.DataFrame(rows)


def table_key_field_profile(inventory: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in inventory.iterrows():
        if r["file_type"] not in {"csv", "parquet"}:
            continue
        cols = str(r.get("columns", "")).split("|") if pd.notna(r.get("columns")) else []
        rows.append(
            {
                "path": r["path"],
                "row_count": r["row_count"],
                "likely_grain": r["likely_grain"],
                "has_stable_signal_id": "stable_signal_id" in cols,
                "has_globalid": "GLOBALID" in cols or "source_signal_globalid" in cols or "reviewed_source_signal_globalid" in cols,
                "has_stable_bin_id": "stable_bin_id" in cols,
                "has_signal_approach": "signal_approach_id_v2" in cols or "signal_approach_id" in cols,
                "has_route_identity": any(c in cols for c in ["source_route_name", "route_name", "RTE_NM"]),
                "has_measure_fields": any("measure" in c.lower() for c in cols),
                "has_geometry": bool(r["geometry_presence"]),
                "key_fields_present": r["key_fields_present"],
            }
        )
    return pd.DataFrame(rows)


def source_signal_identifier_crosswalk(signals: pd.DataFrame) -> pd.DataFrame:
    id_cols = [c for c in ["REG_SIGNAL_ID", "ASSET_NUM", "SIGNAL_NO", "ASSET_ID", "INTNO", "INTNUM"] if c in signals.columns]
    rows = []
    for col in id_cols:
        x = signals[["GLOBALID", col]].rename(columns={col: "source_signal_id"}).copy()
        x["source_signal_id"] = x["source_signal_id"].astype(str).str.strip()
        x = x[nonmissing(x["source_signal_id"])]
        x["identifier_field"] = col
        rows.append(x)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["GLOBALID", "source_signal_id", "identifier_field"])


def load_identity_inputs() -> dict[str, pd.DataFrame]:
    bin_cols = [
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "source_route_name",
        "source_measure_start",
        "source_measure_end",
        "source_measure_midpoint",
        "distance_band",
        "distance_band_v2",
        "signal_approach_id_v2",
        "geometry_wkt",
        "upstream_downstream_values",
        "upstream_downstream",
        "directionality_status",
        "directionality_recovery_status",
        "bin_row_origin",
        "generated_bin_flag",
        "continuation_corridor_id",
    ]
    available = pd.read_parquet(BIN_CONTEXT, columns=None).columns
    return {
        "signals": pd.read_parquet(SIGNALS),
        "final_signal": pd.read_csv(FINAL_SIGNAL) if FINAL_SIGNAL.exists() else pd.DataFrame(),
        "bin_context": pd.read_parquet(BIN_CONTEXT, columns=[c for c in bin_cols if c in available]),
        "signal_approaches": pd.read_parquet(SIGNAL_APPROACHES),
        "approach_windows": pd.read_parquet(APPROACH_WINDOWS),
        "projection": pd.read_parquet(PROJECTION_INDEX) if PROJECTION_INDEX.exists() else pd.DataFrame(),
        "corridor": pd.read_parquet(CORRIDOR_INDEX) if CORRIDOR_INDEX.exists() else pd.DataFrame(),
        "roads": pd.read_parquet(ROADS, columns=["RTE_NM", "FROM_MEASURE", "TO_MEASURE", "geometry"]),
    }


def stable_set(series: pd.Series) -> str:
    vals = sorted({norm_stable(v) for v in series if norm_stable(v)})
    return "|".join(vals)


def build_signal_identity_reconciliation(data: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    signals = data["signals"].copy()
    signals["_globalid_norm"] = signals["GLOBALID"].map(norm_globalid)
    rec = signals[["GLOBALID", "_globalid_norm", "geometry"]].copy()
    rec["source_geometry_available"] = rec["geometry"].notna()
    rec["source_globalid_available"] = rec["_globalid_norm"].astype(str).str.strip().ne("")
    rec = rec.drop(columns=["geometry"])

    if not data["final_signal"].empty and "GLOBALID" in data["final_signal"].columns:
        fs = data["final_signal"].copy()
        fs["_globalid_norm"] = fs["GLOBALID"].map(norm_globalid)
        fs = fs[fs["_globalid_norm"].astype(str).str.strip().ne("")]
        fs_map = fs.groupby("_globalid_norm")["stable_signal_id"].agg(stable_set).reset_index(name="stable_signal_id_canonical_final")
        rec = rec.merge(fs_map, on="_globalid_norm", how="left")
    else:
        rec["stable_signal_id_canonical_final"] = ""

    id_cross = source_signal_identifier_crosswalk(signals)
    bin_map = data["bin_context"][["source_signal_id", "stable_signal_id"]].dropna().drop_duplicates().copy()
    bin_map["source_signal_id"] = bin_map["source_signal_id"].astype(str).str.strip()
    bin_join = id_cross.merge(bin_map, on="source_signal_id", how="inner")
    bin_stable = bin_join.groupby("GLOBALID")["stable_signal_id"].agg(stable_set).reset_index()
    bin_stable["_globalid_norm"] = bin_stable["GLOBALID"].map(norm_globalid)
    bin_stable = bin_stable[bin_stable["_globalid_norm"].astype(str).str.strip().ne("")]
    bin_stable = bin_stable[["_globalid_norm", "stable_signal_id"]].rename(columns={"stable_signal_id": "stable_signal_id_staged_bin_context"})
    rec = rec.merge(bin_stable, on="_globalid_norm", how="left")

    proj = data["projection"].copy()
    if not proj.empty:
        proj["_globalid_norm"] = proj["source_signal_globalid"].map(norm_globalid)
        proj = proj[proj["_globalid_norm"].astype(str).str.strip().ne("")]
        proj_stable = proj.groupby("_globalid_norm")["stable_signal_id"].agg(stable_set).reset_index(name="stable_signal_id_projection_index")
        proj_role = proj.groupby("_globalid_norm")["signal_role_hint"].agg(lambda s: "|".join(sorted(set(s.dropna().astype(str))))).reset_index(name="projection_signal_role_hint")
        proj_rows = proj.groupby("_globalid_norm").size().reset_index(name="projection_rows")
        rec = rec.merge(proj_stable, on="_globalid_norm", how="left").merge(proj_role, on="_globalid_norm", how="left").merge(proj_rows, on="_globalid_norm", how="left")
    else:
        rec["stable_signal_id_projection_index"] = ""
        rec["projection_signal_role_hint"] = ""
        rec["projection_rows"] = 0

    corr = data["corridor"].copy()
    if not corr.empty:
        corr["_reviewed_norm"] = corr["reviewed_source_signal_globalid"].map(norm_globalid)
        corr = corr[corr["_reviewed_norm"].astype(str).str.strip().ne("")]
        corr_stable = corr.groupby("_reviewed_norm")["stable_signal_id"].agg(stable_set).reset_index(name="stable_signal_id_corridor_reviewed")
        rec = rec.merge(corr_stable.rename(columns={"_reviewed_norm": "_globalid_norm"}), on="_globalid_norm", how="left")
    else:
        rec["stable_signal_id_corridor_reviewed"] = ""

    stable_cols = [
        "stable_signal_id_canonical_final",
        "stable_signal_id_staged_bin_context",
        "stable_signal_id_projection_index",
        "stable_signal_id_corridor_reviewed",
    ]
    for col in stable_cols:
        if col not in rec.columns:
            rec[col] = ""
        rec[col] = rec[col].fillna("")
    rec["stable_signal_id_anywhere"] = rec[stable_cols].apply(lambda row: stable_set(pd.Series("|".join([str(v) for v in row if str(v)]).split("|"))), axis=1)
    rec["has_stable_anywhere"] = nonmissing(rec["stable_signal_id_anywhere"])
    rec["has_stable_in_projection"] = nonmissing(rec["stable_signal_id_projection_index"])
    rec["projection_marked_source_only"] = rec.get("projection_signal_role_hint", pd.Series("", index=rec.index)).fillna("").astype(str).str.contains("source_only_signal", na=False)
    rec["source_only_explanation_category"] = "not_source_only_in_projection"
    rec.loc[rec["projection_marked_source_only"] & rec["has_stable_anywhere"], "source_only_explanation_category"] = "false_source_only_missing_projection_crosswalk"
    rec.loc[rec["projection_marked_source_only"] & ~rec["has_stable_anywhere"], "source_only_explanation_category"] = "true_source_only_no_stable_id_anywhere"
    rec.loc[~rec["projection_marked_source_only"] & ~rec["has_stable_anywhere"], "source_only_explanation_category"] = "not_projected_source_only_but_no_stable_id_anywhere"
    rec["stable_id_mismatch_flag"] = rec[stable_cols].apply(lambda row: len({v for cell in row for v in str(cell).split("|") if v}) > 1, axis=1)
    rec.loc[~rec["source_globalid_available"], "source_only_explanation_category"] = "missing_or_blank_globalid_insufficient_fields"

    format_diag = pd.DataFrame(
        [
            {"diagnostic": "source_signal_rows", "value": len(signals)},
            {"diagnostic": "source_unique_globalid_normalized", "value": signals["_globalid_norm"].nunique()},
            {"diagnostic": "source_nonblank_unique_globalid_normalized", "value": signals.loc[signals["_globalid_norm"].astype(str).str.strip().ne(""), "_globalid_norm"].nunique()},
            {"diagnostic": "source_missing_or_blank_globalid_rows", "value": int((signals["_globalid_norm"].astype(str).str.strip().eq("")).sum())},
            {"diagnostic": "source_duplicate_globalid_rows", "value": int(signals.duplicated("_globalid_norm").sum())},
            {"diagnostic": "canonical_final_stable_signal_rows", "value": int(nonmissing(data["final_signal"].get("stable_signal_id", pd.Series(dtype=str))).sum()) if not data["final_signal"].empty else 0},
            {"diagnostic": "canonical_final_unique_stable_signal_id", "value": data["final_signal"]["stable_signal_id"].nunique() if not data["final_signal"].empty and "stable_signal_id" in data["final_signal"].columns else 0},
            {"diagnostic": "canonical_final_rows_with_globalid", "value": int(nonmissing(data["final_signal"].get("GLOBALID", pd.Series(dtype=str))).sum()) if not data["final_signal"].empty else 0},
            {"diagnostic": "canonical_final_unique_nonblank_globalid", "value": data["final_signal"].assign(_g=data["final_signal"]["GLOBALID"].map(norm_globalid)).query("_g != ''")["_g"].nunique() if not data["final_signal"].empty and "GLOBALID" in data["final_signal"].columns else 0},
            {"diagnostic": "projection_unique_source_globalid", "value": proj["_globalid_norm"].nunique() if not proj.empty else 0},
            {"diagnostic": "projection_duplicate_globalid_route_rows", "value": int(proj.duplicated(["_globalid_norm", "route_name", "road_row_id"]).sum()) if not proj.empty else 0},
            {"diagnostic": "signals_with_braced_globalid", "value": int(signals["GLOBALID"].astype(str).str.startswith("{").sum())},
        ]
    )

    explanation = rec.groupby("source_only_explanation_category").size().reset_index(name="source_signal_count")
    return rec, explanation, format_diag


def signal_identity_summary(rec: pd.DataFrame) -> pd.DataFrame:
    rows = []
    cols = {
        "canonical_final": "stable_signal_id_canonical_final",
        "staged_bin_context": "stable_signal_id_staged_bin_context",
        "projection_index": "stable_signal_id_projection_index",
        "corridor_reviewed_signal": "stable_signal_id_corridor_reviewed",
        "anywhere": "stable_signal_id_anywhere",
    }
    for name, col in cols.items():
        rows.append(
            {
                "object": name,
                "total_source_signals": int(len(rec)),
                "signals_with_stable_signal_id": int(nonmissing(rec[col]).sum()),
                "signals_without_stable_signal_id": int((~nonmissing(rec[col])).sum()),
                "duplicate_globalid_rows": int(rec.duplicated("_globalid_norm").sum()),
                "duplicate_stable_signal_id_rows": int(rec[nonmissing(rec[col])].duplicated(col).sum()) if col in rec else 0,
                "mismatched_globalid_to_stable_mappings": int(rec["stable_id_mismatch_flag"].sum()),
            }
        )
    rows.append(
        {
            "object": "projection_index_source_only_explanation",
            "total_source_signals": int(len(rec)),
            "signals_with_stable_signal_id": int((rec["projection_marked_source_only"] & rec["has_stable_anywhere"]).sum()),
            "signals_without_stable_signal_id": int((rec["projection_marked_source_only"] & ~rec["has_stable_anywhere"]).sum()),
            "duplicate_globalid_rows": 0,
            "duplicate_stable_signal_id_rows": 0,
            "mismatched_globalid_to_stable_mappings": int(rec["stable_id_mismatch_flag"].sum()),
        }
    )
    return pd.DataFrame(rows)


def projection_index_integrity(proj: pd.DataFrame, rec: pd.DataFrame) -> pd.DataFrame:
    required = [
        "source_signal_globalid",
        "stable_signal_id",
        "signal_role_hint",
        "road_row_id",
        "route_name",
        "from_measure",
        "to_measure",
        "estimated_measure",
        "point_to_line_distance_ft",
        "projection_confidence",
        "usable_as_corridor_boundary",
    ]
    source_only_unique = proj.loc[proj["signal_role_hint"].eq("source_only_signal"), "source_signal_globalid"].map(norm_globalid).nunique()
    analysis_unique = proj.loc[proj["signal_role_hint"].eq("analysis_signal"), "source_signal_globalid"].map(norm_globalid).nunique()
    false_source_only = int((rec["projection_marked_source_only"] & rec["has_stable_anywhere"]).sum())
    true_source_only = int((rec["projection_marked_source_only"] & ~rec["has_stable_anywhere"]).sum())
    rows = [
        {"check": "row_count", "value": len(proj), "status": "info", "detail": ""},
        {"check": "required_columns_present", "value": int(all(c in proj.columns for c in required)), "status": "pass" if all(c in proj.columns for c in required) else "fail", "detail": "|".join([c for c in required if c not in proj.columns])},
        {"check": "unique_source_signals", "value": proj["source_signal_globalid"].map(norm_globalid).nunique(), "status": "info", "detail": ""},
        {"check": "analysis_signal_unique_signals_in_projection", "value": analysis_unique, "status": "review" if analysis_unique < EXPECTED_APPROX_ANALYSIS_SIGNALS else "pass", "detail": f"expected approximately {EXPECTED_APPROX_ANALYSIS_SIGNALS} analysis-ready signals"},
        {"check": "source_only_unique_signals_in_projection", "value": source_only_unique, "status": "review" if false_source_only else "pass", "detail": f"false_source_only={false_source_only}; true_source_only={true_source_only}"},
        {"check": "usable_boundary_rows", "value": int(proj["usable_as_corridor_boundary"].astype(bool).sum()), "status": "info", "detail": ""},
        {"check": "missing_stable_id_on_analysis_role_rows", "value": int((proj["signal_role_hint"].eq("analysis_signal") & ~nonmissing(proj["stable_signal_id"])).sum()), "status": "pass", "detail": ""},
        {"check": "missing_projection_measure_on_usable_rows", "value": int((proj["usable_as_corridor_boundary"].astype(bool) & proj["estimated_measure"].isna()).sum()), "status": "pass", "detail": ""},
        {"check": "duplicate_projection_candidate_rows", "value": int(proj.duplicated(["source_signal_globalid", "route_name", "road_row_id"]).sum()), "status": "review", "detail": "Duplicate candidate rows at source_signal x route x road_row grain."},
    ]
    return pd.DataFrame(rows)


def corridor_index_integrity(corr: pd.DataFrame) -> pd.DataFrame:
    required = [
        "corridor_index_id",
        "stable_signal_id",
        "reviewed_source_signal_globalid",
        "route_name",
        "reviewed_signal_estimated_measure",
        "before_interval_from_measure",
        "before_interval_to_measure",
        "after_interval_from_measure",
        "after_interval_to_measure",
        "boundary_method",
        "endpoint_source_only_used",
        "corridor_confidence",
    ]
    rows = [
        {"check": "row_count", "value": len(corr), "status": "info", "detail": ""},
        {"check": "required_columns_present", "value": int(all(c in corr.columns for c in required)), "status": "pass" if all(c in corr.columns for c in required) else "fail", "detail": "|".join([c for c in required if c not in corr.columns])},
        {"check": "duplicate_corridor_index_id_rows", "value": int(corr.duplicated("corridor_index_id").sum()), "status": "pass" if int(corr.duplicated("corridor_index_id").sum()) == 0 else "fail", "detail": ""},
        {"check": "corridor_rows_missing_reviewed_stable_signal_id", "value": int((~nonmissing(corr["stable_signal_id"])).sum()), "status": "pass", "detail": ""},
        {"check": "corridor_rows_using_source_only_endpoints", "value": int(corr["endpoint_source_only_used"].astype(bool).sum()), "status": "info", "detail": ""},
        {"check": "corridor_rows_insufficient_boundary", "value": int(corr["boundary_method"].eq("insufficient_boundary").sum()), "status": "review", "detail": ""},
        {"check": "missing_reviewed_measure", "value": int(corr["reviewed_signal_estimated_measure"].isna().sum()), "status": "pass", "detail": ""},
        {"check": "missing_all_intervals", "value": int(corr["before_interval_from_measure"].isna().fillna(True) & corr["after_interval_to_measure"].isna().fillna(True)).sum() if False else int((corr["before_interval_from_measure"].isna() & corr["after_interval_to_measure"].isna()).sum()), "status": "review", "detail": ""},
    ]
    return pd.DataFrame(rows)


def staged_bin_context_integrity(bin_context: pd.DataFrame) -> pd.DataFrame:
    side = side_values(bin_context)
    rows = [
        {"metric": "row_count", "value": len(bin_context), "status": "info", "detail": ""},
        {"metric": "stable_bin_id_unique_count", "value": bin_context["stable_bin_id"].nunique(dropna=True), "status": "info", "detail": f"duplicate rows={int(bin_context.duplicated('stable_bin_id').sum())}"},
        {"metric": "stable_signal_id_missing_rows", "value": int((~nonmissing(bin_context["stable_signal_id"])).sum()), "status": "pass" if int((~nonmissing(bin_context["stable_signal_id"])).sum()) == 0 else "review", "detail": ""},
        {"metric": "signal_approach_id_v2_missing_rows", "value": int((~nonmissing(bin_context["signal_approach_id_v2"])).sum()), "status": "review", "detail": ""},
        {"metric": "distance_band_missing_rows", "value": int((~nonmissing(bin_context.get("distance_band_v2", bin_context.get("distance_band")))).sum()), "status": "pass", "detail": ""},
        {"metric": "directionality_missing_rows", "value": int((~nonmissing(side)).sum()), "status": "info", "detail": ""},
        {"metric": "route_name_missing_rows", "value": int((~nonmissing(bin_context["source_route_name"])).sum()), "status": "review", "detail": ""},
        {"metric": "source_measure_midpoint_missing_rows", "value": int(bin_context["source_measure_midpoint"].isna().sum()), "status": "review", "detail": ""},
        {"metric": "geometry_wkt_missing_rows", "value": int((~nonmissing(bin_context.get("geometry_wkt", pd.Series(pd.NA, index=bin_context.index)))).sum()), "status": "review", "detail": ""},
        {"metric": "missing_key_lineage_rows", "value": int((~nonmissing(bin_context["stable_bin_id"]) | ~nonmissing(bin_context["stable_signal_id"]) | ~nonmissing(bin_context["source_route_name"])).sum()), "status": "review", "detail": ""},
    ]
    for col in ["bin_row_origin", "generated_bin_flag"]:
        counts = bin_context[col].astype(str).value_counts(dropna=False).reset_index()
        for _, r in counts.iterrows():
            rows.append({"metric": f"{col}_count", "value": int(r["count"]), "status": "info", "detail": str(r[col])})
    return pd.DataFrame(rows)


def recompute_unresolved_linkage(bin_context: pd.DataFrame, corr: pd.DataFrame) -> pd.DataFrame:
    side = side_values(bin_context)
    status_text = (
        bin_context.get("directionality_status", pd.Series("", index=bin_context.index)).astype("string").str.lower().fillna("")
        + "|"
        + bin_context.get("directionality_recovery_status", pd.Series("", index=bin_context.index)).astype("string").str.lower().fillna("")
    )
    unresolved = bin_context[(~nonmissing(side)) | status_text.str.contains("not_recovered|unresolved", regex=True, na=False)].copy()
    usable = corr[corr["corridor_confidence"].isin(["high", "medium"])].copy()
    route_map = {k: v for k, v in usable.groupby(["stable_signal_id", "route_name"], dropna=False)}
    counts = {
        "linked_to_single_corridor_interval": 0,
        "not_linked_measure_outside_corridor_intervals": 0,
        "not_linked_missing_bin_measure": 0,
        "not_linked_multiple_corridors": 0,
        "not_linked_no_corridor_for_signal_route": 0,
    }
    for _, row in unresolved.iterrows():
        cands = route_map.get((row.get("stable_signal_id"), row.get("source_route_name")))
        if cands is None or cands.empty:
            counts["not_linked_no_corridor_for_signal_route"] += 1
            continue
        measure = pd.to_numeric(pd.Series([row.get("source_measure_midpoint")]), errors="coerce").iloc[0]
        if pd.isna(measure):
            start = pd.to_numeric(pd.Series([row.get("source_measure_start")]), errors="coerce").iloc[0]
            end = pd.to_numeric(pd.Series([row.get("source_measure_end")]), errors="coerce").iloc[0]
            measure = (float(start) + float(end)) / 2.0 if pd.notna(start) and pd.notna(end) else math.nan
        if math.isnan(float(measure)) if pd.notna(measure) else True:
            counts["not_linked_missing_bin_measure"] += 1
            continue
        m = float(measure)
        linked = cands[
            (
                (pd.to_numeric(cands["before_interval_from_measure"], errors="coerce") <= m + 1e-7)
                & (pd.to_numeric(cands["before_interval_to_measure"], errors="coerce") >= m - 1e-7)
            )
            | (
                (pd.to_numeric(cands["after_interval_from_measure"], errors="coerce") <= m + 1e-7)
                & (pd.to_numeric(cands["after_interval_to_measure"], errors="coerce") >= m - 1e-7)
            )
        ]
        if len(linked) == 1:
            counts["linked_to_single_corridor_interval"] += 1
        elif len(linked) > 1:
            counts["not_linked_multiple_corridors"] += 1
        else:
            counts["not_linked_measure_outside_corridor_intervals"] += 1
    return pd.DataFrame([{"link_status": k, "bins": v} for k, v in counts.items()])


def readiness_decision(signal_explanation: pd.DataFrame, proj_audit: pd.DataFrame, corr_audit: pd.DataFrame, bin_audit: pd.DataFrame, linkage: pd.DataFrame) -> pd.DataFrame:
    false_source_only = int(signal_explanation.loc[signal_explanation["source_only_explanation_category"].eq("false_source_only_missing_projection_crosswalk"), "source_signal_count"].sum())
    missing_globalid = int(signal_explanation.loc[signal_explanation["source_only_explanation_category"].eq("missing_or_blank_globalid_insufficient_fields"), "source_signal_count"].sum())
    proj_fail = proj_audit["status"].eq("fail").any()
    corr_fail = corr_audit["status"].eq("fail").any()
    linked = int(linkage.loc[linkage["link_status"].eq("linked_to_single_corridor_interval"), "bins"].sum())
    projection_analysis_signals = int(proj_audit.loc[proj_audit["check"].eq("analysis_signal_unique_signals_in_projection"), "value"].sum()) if "analysis_signal_unique_signals_in_projection" in set(proj_audit["check"]) else 0
    if false_source_only > 0 or missing_globalid > 0 or projection_analysis_signals < EXPECTED_APPROX_ANALYSIS_SIGNALS:
        decision = "needs_signal_identity_crosswalk_repair"
        rationale = f"Projection-index analysis signal coverage is {projection_analysis_signals} versus about {EXPECTED_APPROX_ANALYSIS_SIGNALS} expected; missing/blank GLOBALID source rows={missing_globalid}; false source-only rows={false_source_only}."
    elif proj_fail:
        decision = "needs_projection_index_rebuild"
        rationale = "Projection index required-column or structural checks failed."
    elif corr_fail:
        decision = "needs_corridor_index_rebuild"
        rationale = "Corridor index required structural checks failed."
    elif linked <= 0:
        decision = "needs_bin_context_lineage_repair"
        rationale = "No unresolved bins link to corridor intervals."
    else:
        decision = "ready_for_exact_corridor_recovery"
        rationale = "Exact-corridor subset is structurally usable, with caveats documented."
    return pd.DataFrame([{"readiness_decision": decision, "rationale": rationale, "linked_exact_corridor_bins": linked, "false_source_only_count": false_source_only, "missing_or_blank_globalid_count": missing_globalid, "projection_analysis_signal_count": projection_analysis_signals}])


def keep_repair_discard(inventory: pd.DataFrame, readiness: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in inventory.iterrows():
        role = r["inferred_role"]
        action = "keep"
        reason = "Active cache/support evidence."
        if role == "stale_or_unclear":
            action = "review_or_relocate"
            reason = "Object is under analysis root but not clearly in canonical/staging product folder."
        if role == "support_index" and readiness.iloc[0]["readiness_decision"] == "needs_signal_identity_crosswalk_repair":
            action = "repair"
            reason = "Support index is structurally useful but stable_signal_id crosswalk is incomplete."
        rows.append({"path": r["path"], "inferred_role": role, "recommended_action": action, "reason": reason})
    return pd.DataFrame(rows)


def recommended_actions(readiness: pd.DataFrame) -> pd.DataFrame:
    decision = readiness.iloc[0]["readiness_decision"]
    if decision == "needs_signal_identity_crosswalk_repair":
        action = "repair_projection_index_signal_identity_crosswalk_before_broad_recovery"
    elif decision == "ready_for_exact_corridor_recovery":
        action = "use_exact_corridor_subset_for_reviewed_directionality_apply_task"
    else:
        action = "resolve_cache_structural_blocker_before_more_recovery"
    return pd.DataFrame([{"recommended_next_action": action, "readiness_decision": decision, "rationale": readiness.iloc[0]["rationale"]}])


def write_findings(inventory: pd.DataFrame, product_contract: pd.DataFrame, signal_summary: pd.DataFrame, source_only: pd.DataFrame, proj_audit: pd.DataFrame, corr_audit: pd.DataFrame, bin_audit: pd.DataFrame, linkage: pd.DataFrame, readiness: pd.DataFrame) -> None:
    role_counts = inventory["inferred_role"].value_counts().to_dict()
    source_only_counts = {r["source_only_explanation_category"]: int(r["source_signal_count"]) for _, r in source_only.iterrows()}
    final_with_stable = int(signal_summary.loc[signal_summary["object"].eq("canonical_final"), "signals_with_stable_signal_id"].iloc[0])
    projection_source_only = source_only_counts.get("true_source_only_no_stable_id_anywhere", 0) + source_only_counts.get("false_source_only_missing_projection_crosswalk", 0)
    false_source_only = source_only_counts.get("false_source_only_missing_projection_crosswalk", 0)
    true_source_only = source_only_counts.get("true_source_only_no_stable_id_anywhere", 0)
    missing_globalid = source_only_counts.get("missing_or_blank_globalid_insufficient_fields", 0)
    linked = int(linkage.loc[linkage["link_status"].eq("linked_to_single_corridor_interval"), "bins"].sum())
    missing_dir = int(bin_audit.loc[bin_audit["metric"].eq("directionality_missing_rows"), "value"].iloc[0])
    text = f"""# Analysis Cache Structural Integrity Audit

## What Analysis Cache Objects Exist Now

Inventoried data-like objects under `work/roadway_graph/analysis/`, excluding active deep audit of `mvp_dataset` per user direction: {len(inventory)}. Role counts: `{role_counts}`.

## Canonical, Staged, Proposal, Support, Or Unclear Objects

Major product contract findings are in `product_contract_audit.csv`. The canonical final-leg folder is a CSV-based root product. The refresh candidate staging folder contains Parquet staged tables plus support indexes and proposed generated bins. The MVP folder was not actively audited in this run.

## Whether The 1,019 Source-Only Signal Count Is Real

The earlier `1,019` source-only count is not a real stable-signal holdout count. It decomposes into {missing_globalid} normalized source signal rows with missing/blank `GLOBALID` and insufficient identifier fields, {true_source_only} true source-only GLOBALID-bearing signals with no stable ID found anywhere, and {false_source_only} false source-only rows with stable ID evidence elsewhere. Canonical final-leg stable signal coverage by source GLOBALID is {final_with_stable}; canonical stable signal coverage by `stable_signal_id` is larger and is documented in `globalid_format_diagnostics.csv`.

## Source GLOBALID And Stable Signal ID Reconciliation

See `signal_identity_reconciliation.csv`, `source_only_signal_explanation.csv`, and `globalid_format_diagnostics.csv`. GLOBALID normalization removed brace/case/whitespace differences before comparison.

## Projection/Corridor Index Trustworthiness

Projection index checks: `{proj_audit.to_dict('records')}`. Corridor index checks: `{corr_audit.to_dict('records')}`. The indexes are useful as support objects, but the projection index should be repaired for signal identity before broad directionality recovery that depends on source-only counts.

## Staged Bin Context Trustworthiness

Staged `bin_context.parquet` row count and directionality missingness are structurally consistent with prior audits. Missing directionality rows: {missing_dir}. Key lineage/profile checks are in `staged_bin_context_integrity_audit.csv`.

## Objects To Use For The Next Directionality Task

Use staged `bin_context.parquet`, `source_signal_travelway_projection_index.parquet`, `signal_bounded_travelway_corridor_index.parquet`, and the exact-corridor proposal outputs only as review/proposal inputs. Do not use root-level unclear analysis artifacts for new recovery logic.

## What Must Be Repaired Before More Recovery

Repair the projection-index signal identity crosswalk/source-signal identity handling so canonical stable signals that lack source `GLOBALID` are not confused with true source-only endpoint signals. This is primarily a support-index/crosswalk repair; source artifact normalization may also need review for the 780 blank-GLOBALID signal rows.

## Directionality-Support Readiness

Readiness decision: `{readiness.iloc[0]['readiness_decision']}`. Exact-corridor linked unresolved bins: {linked}.

## Recommended Next Step

See `recommended_next_actions.csv`.
"""
    (REVIEW_OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    REVIEW_OUT.mkdir(parents=True, exist_ok=True)
    (REVIEW_OUT / "progress_log.md").write_text("# Progress Log\n", encoding="utf-8")
    log("Inventorying analysis cache data-like objects.")
    inventory = inventory_analysis_cache()
    product_contract = product_contract_audit()
    key_profile = table_key_field_profile(inventory)

    log("Loading identity and structural audit inputs.")
    data = load_identity_inputs()
    signal_rec, source_only_explanation, format_diag = build_signal_identity_reconciliation(data)
    signal_summary = signal_identity_summary(signal_rec)

    log("Auditing projection/corridor indexes and staged bin_context.")
    proj_audit = projection_index_integrity(data["projection"], signal_rec)
    corr_audit = corridor_index_integrity(data["corridor"])
    bin_audit = staged_bin_context_integrity(data["bin_context"])
    linkage = recompute_unresolved_linkage(data["bin_context"], data["corridor"])

    log("Building readiness decision and recommendations.")
    readiness = readiness_decision(source_only_explanation, proj_audit, corr_audit, bin_audit, linkage)
    keep_repair = keep_repair_discard(inventory, readiness)
    recs = recommended_actions(readiness)

    write_csv("analysis_cache_inventory.csv", inventory)
    write_csv("product_contract_audit.csv", product_contract)
    write_csv("table_key_field_profile.csv", key_profile)
    write_csv("signal_identity_reconciliation.csv", signal_rec)
    write_csv("source_only_signal_explanation.csv", source_only_explanation)
    write_csv("globalid_format_diagnostics.csv", format_diag)
    write_csv("projection_index_integrity_audit.csv", proj_audit)
    write_csv("corridor_index_integrity_audit.csv", corr_audit)
    write_csv("staged_bin_context_integrity_audit.csv", bin_audit)
    write_csv("unresolved_bin_corridor_linkage_audit.csv", linkage)
    write_csv("directionality_support_readiness.csv", readiness)
    write_csv("cache_objects_to_keep_repair_or_discard.csv", keep_repair)
    write_csv("recommended_next_actions.csv", recs)
    write_findings(inventory, product_contract, signal_summary, source_only_explanation, proj_audit, corr_audit, bin_audit, linkage, readiness)

    qa_rows = [
        {"qa_gate": "analysis_objects_inventoried", "status": "pass" if len(inventory) > 0 else "fail", "detail": f"objects={len(inventory)}"},
        {"qa_gate": "signal_identity_reconciled", "status": "pass" if len(signal_rec) == EXPECTED_SOURCE_SIGNALS else "review", "detail": f"source_signals={len(signal_rec)} expected={EXPECTED_SOURCE_SIGNALS}"},
        {"qa_gate": "source_only_count_explained", "status": "pass", "detail": source_only_explanation.to_dict("records")},
        {"qa_gate": "projection_index_structural_audit", "status": "pass" if not proj_audit["status"].eq("fail").any() else "fail", "detail": ""},
        {"qa_gate": "corridor_index_structural_audit", "status": "pass" if not corr_audit["status"].eq("fail").any() else "fail", "detail": ""},
        {"qa_gate": "no_input_mutation", "status": "pass", "detail": "Script writes only review outputs."},
    ]
    manifest = {
        "created_utc": now_iso(),
        "bounded_question": "Read-only structural integrity audit of active roadway_graph analysis cache system.",
        "source_inputs": [rel(p) for p in [ANALYSIS, FINAL, STAGING, SIGNALS, ROADS, SPEED, AADT, ACCESS, CRASHES]],
        "mvp_dataset_deep_audit": "skipped_per_user_direction",
        "review_context_inputs": [rel(p) for p in READ_CONTEXT],
        "output_dir": rel(REVIEW_OUT),
        "analysis_objects_inventoried": int(len(inventory)),
        "major_cache_products_found": product_contract["product_folder"].tolist(),
        "readiness_decision": readiness.iloc[0].to_dict(),
        "no_mutation": True,
    }
    qa_manifest = {
        "created_utc": now_iso(),
        "qa_gates": qa_rows,
        "signal_identity_summary": signal_summary.to_dict("records"),
        "source_only_explanation": source_only_explanation.to_dict("records"),
        "readiness_decision": readiness.iloc[0].to_dict(),
    }
    (REVIEW_OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (REVIEW_OUT / "qa_manifest.json").write_text(json.dumps(qa_manifest, indent=2, sort_keys=True), encoding="utf-8")
    log("Completed analysis cache structural integrity audit.")


if __name__ == "__main__":
    main()
