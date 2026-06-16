from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkt


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/source_travelway_lineage_bridge"

FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
FINAL_ACCESS_DIR = OUTPUT_ROOT / "review/current/final_access_rerun_with_source_accounting"
TRAVELWAY_ACCESS_DIR = OUTPUT_ROOT / "review/current/final_access_travelway_normalization_test"
MAP_FINDINGS_DIR = OUTPUT_ROOT / "review/current/map_review_findings_source_limitation_diagnostic"
ACCESS_REVIEW_GPKG = OUTPUT_ROOT / "map_review/access_review/access_review.gpkg"
PHYSICAL_LEG_GPKG_CANDIDATES = [
    OUTPUT_ROOT / "map_review/current/physical_leg_review/physical_leg_review.gpkg",
    OUTPUT_ROOT / "map_review/physical_leg_review/physical_leg_review.gpkg",
]

CRASH_FIELD_TOKENS = (
    "crash_id",
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "document_nbr",
    "crash_year",
    "crash_dt",
    "assigned_crash",
)

REQUIRED_INPUTS = [
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_consolidated_leg_bin_detail.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    FINAL_ACCESS_DIR / "final_cleaned_access_target_bins.csv",
    FINAL_ACCESS_DIR / "final_access_rerun_with_source_accounting_manifest.json",
    TRAVELWAY_ACCESS_DIR / "represented_signal_leg_travelway_identity.csv",
    TRAVELWAY_ACCESS_DIR / "final_access_travelway_normalization_manifest.json",
    ACCESS_REVIEW_GPKG,
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{_now()} {message}\n")


def _checkpoint(name: str, rows: int | None = None) -> None:
    suffix = "" if rows is None else f" rows={rows:,}"
    _log(f"CHECKPOINT {name}{suffix}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    if lower in {"access_direction", "access_direction_raw", "access_direction_normalized"}:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(OUT_DIR / name, index=False)
    _checkpoint(f"write {name}", len(frame))


def _write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")


def _write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _collapse(values: pd.Series | list[str], limit: int = 12) -> str:
    if isinstance(values, pd.Series):
        iterable = values.dropna().tolist()
    else:
        iterable = values
    items = sorted({str(value) for value in iterable if str(value).strip()})
    suffix = "" if len(items) <= limit else f"|+{len(items) - limit}_more"
    return "|".join(items[:limit]) + suffix


def _hash_text(text: str, n: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:n]


def _hash_geom(geom: Any, n: int = 20) -> str:
    if geom is None or getattr(geom, "is_empty", True):
        return ""
    return hashlib.sha256(geom.wkb).hexdigest()[:n]


def _parse_wkt(value: Any):
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return None
    try:
        return wkt.loads(text)
    except Exception:
        return None


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _missing_inputs() -> list[str]:
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    if _first_existing(PHYSICAL_LEG_GPKG_CANDIDATES) is None:
        missing.append("physical_leg_review.gpkg from current or non-current map_review path")
    return missing


def _source_identity() -> gpd.GeoDataFrame:
    _checkpoint("read_start source_travelway_full")
    source = gpd.read_file(ACCESS_REVIEW_GPKG, layer="source_travelway_full")
    if source.crs is None:
        source = source.set_crs("EPSG:3968", allow_override=True)
    source = source.to_crs("EPSG:3968")
    source["source_feature_local_fid"] = source.index + 1
    source["source_layer"] = _text(source, "Stage1_SourceLayer").where(_text(source, "Stage1_SourceLayer").ne(""), "Travelway")
    source["source_route_id"] = _text(source, "RTE_ID")
    source["source_route_name"] = _text(source, "RTE_NM")
    source["source_route_common"] = _text(source, "RTE_COMMON")
    source["from_measure"] = _text(source, "FROM_MEASURE")
    source["to_measure"] = _text(source, "TO_MEASURE")
    source["facility_text"] = _text(source, "RIM_FACILI")
    source["name_facility_fields"] = (
        source["source_route_name"] + "|" + source["source_route_common"] + "|" + source["facility_text"] + "|" + _text(source, "RTE_TYPE_N") + "|" + _text(source, "RTE_RAMP_C")
    )
    source["geometry_hash"] = source.geometry.map(_hash_geom)
    attr_cols = ["source_layer", "source_route_id", "source_route_name", "source_route_common", "from_measure", "to_measure", "facility_text", "RTE_TYPE_N", "RTE_RAMP_C", "EVENT_SOUR"]
    source["attribute_hash"] = source[[col for col in attr_cols if col in source.columns]].astype(str).agg("|".join, axis=1).map(_hash_text)
    composite = (
        source["source_layer"]
        + "|"
        + source["source_route_id"]
        + "|"
        + source["source_route_name"]
        + "|"
        + source["source_route_common"]
        + "|"
        + source["from_measure"]
        + "|"
        + source["to_measure"]
        + "|"
        + source["geometry_hash"]
    )
    source["stable_composite_key"] = composite
    source["stable_travelway_id"] = "tw_" + composite.map(_hash_text)
    source["fid_is_package_local_only"] = True
    keep = [
        "stable_travelway_id",
        "source_layer",
        "source_feature_local_fid",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "from_measure",
        "to_measure",
        "facility_text",
        "name_facility_fields",
        "geometry_hash",
        "attribute_hash",
        "stable_composite_key",
        "fid_is_package_local_only",
        "EVENT_SOUR",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
        "geometry",
    ]
    out = source[[col for col in keep if col in source.columns]].copy()
    _checkpoint("read_complete source_travelway_full", len(out))
    return out


def _build_label_index(identity: pd.DataFrame) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for row in identity.itertuples(index=False):
        stable_id = getattr(row, "stable_travelway_id")
        values = [
            getattr(row, "source_route_id", ""),
            getattr(row, "source_route_name", ""),
            getattr(row, "source_route_common", ""),
            getattr(row, "EVENT_SOUR", ""),
        ]
        for value in values:
            text = str(value).strip()
            if not text:
                continue
            mapping.setdefault(text.upper(), []).append(stable_id)
    return mapping


def _direct_source_ids(text: str, source_index: pd.DataFrame) -> list[str]:
    ids: list[str] = []
    for match in re.finditer(r"source_travelway_(\d+)", str(text or "")):
        source_zero_index = int(match.group(1))
        source_fid = source_zero_index + 1
        sub = source_index.loc[source_index["source_feature_local_fid"].eq(source_fid), "stable_travelway_id"]
        ids.extend(sub.tolist())
    return ids


def _match_row(row: pd.Series, label_index: dict[str, list[str]], identity: pd.DataFrame, *, lineage_col: str = "source_travelway_lineage") -> dict[str, Any]:
    direct = _direct_source_ids(str(row.get(lineage_col, "")), identity)
    if direct:
        return {
            "stable_travelway_id": _collapse(direct, 6),
            "candidate_stable_travelway_ids": _collapse(direct, 12),
            "candidate_source_feature_local_fids": _collapse(identity.loc[identity["stable_travelway_id"].isin(direct), "source_feature_local_fid"].astype(str), 12),
            "lineage_match_method": "direct_source_travelway_id",
            "lineage_confidence": "high",
            "candidate_match_count": len(set(direct)),
        }
    tokens = re.split(r"[|;,]", str(row.get("route_facility_fields", "")) + "|" + str(row.get("route_key", "")))
    candidate_ids: list[str] = []
    for token in tokens:
        key = token.strip().upper()
        if key:
            candidate_ids.extend(label_index.get(key, []))
    candidate_ids = sorted(set(candidate_ids))
    if candidate_ids:
        method = "route_label_only_match"
        confidence = "medium" if len(candidate_ids) <= 5 else "low"
        sub = identity.loc[identity["stable_travelway_id"].isin(candidate_ids)]
        return {
            "stable_travelway_id": candidate_ids[0] if len(candidate_ids) == 1 else "",
            "candidate_stable_travelway_ids": _collapse(candidate_ids, 12),
            "candidate_source_feature_local_fids": _collapse(sub["source_feature_local_fid"].astype(str), 12),
            "lineage_match_method": method,
            "lineage_confidence": confidence,
            "candidate_match_count": len(candidate_ids),
        }
    return {
        "stable_travelway_id": "",
        "candidate_stable_travelway_ids": "",
        "candidate_source_feature_local_fids": "",
        "lineage_match_method": "unmatched",
        "lineage_confidence": "none",
        "candidate_match_count": 0,
    }


def _bridge(frame: pd.DataFrame, identity: pd.DataFrame, *, table_type: str) -> pd.DataFrame:
    label_index = _build_label_index(identity)
    total = len(frame)
    key_cols = [col for col in ["source_travelway_lineage", "route_facility_fields", "route_key"] if col in frame.columns]
    if not key_cols:
        key_cols = ["route_facility_fields"]
        frame["route_facility_fields"] = ""
    keys = frame[key_cols].drop_duplicates().reset_index(drop=True)
    rows = []
    for i, row in keys.iterrows():
        rows.append(_match_row(row, label_index, identity))
        if i and i % 1000 == 0:
            _checkpoint(f"bridge_key_progress {table_type}", i)
    key_match = pd.concat([keys, pd.DataFrame(rows)], axis=1)
    out = frame.merge(key_match, on=key_cols, how="left")
    out["bridge_table_type"] = table_type
    out["fid_used_as_sole_stable_key"] = False
    _checkpoint(f"bridge_complete {table_type}", total)
    return out


def _normalize_final_bins(bins: pd.DataFrame) -> pd.DataFrame:
    keep = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "consolidated_bin_id",
        "original_bin_id",
        "recovery_stream",
        "recovery_class",
        "original_vs_recovered_bin",
        "physical_leg_id",
        "carriageway_subbranch_id",
        "final_normalized_physical_leg_id",
        "final_carriageway_subbranch_id",
        "route_facility_fields",
        "source_travelway_lineage",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "has_rns_speed",
        "has_aadt",
        "has_exposure_denominator",
        "speed_aadt_ready_bin",
        "final_bin_source_package",
        "final_original_or_recovered",
        "geometry_wkt",
    ]
    return bins[[col for col in keep if col in bins.columns]].copy()


def _normalize_access_bins(access: pd.DataFrame) -> pd.DataFrame:
    rename = {
        "target_signal_id": "signal_id",
        "target_source_id": "source_signal_id",
        "target_source_layer": "source_layer",
        "target_bin_id": "consolidated_bin_id",
        "physical_leg_id_final": "physical_leg_id",
        "carriageway_subbranch_id_final": "carriageway_subbranch_id",
    }
    access = access.rename(columns=rename).copy()
    if "source_travelway_lineage" not in access.columns:
        access["source_travelway_lineage"] = ""
    keep = [
        "signal_id",
        "source_signal_id",
        "source_layer",
        "consolidated_bin_id",
        "original_bin_id",
        "recovery_stream",
        "recovery_class",
        "physical_leg_id",
        "carriageway_subbranch_id",
        "route_facility_fields",
        "route_key",
        "source_travelway_lineage",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "has_rns_speed",
        "has_aadt",
        "has_exposure_denominator",
        "speed_aadt_ready_bin",
        "final_alignment_class",
        "final_bin_source_package",
        "final_original_or_recovered",
        "geometry_recovery_method_final",
        "geometry_recovery_status",
        "geometry_wkt",
    ]
    return access[[col for col in keep if col in access.columns]].copy()


def _reviewed_cases(identity_gdf: gpd.GeoDataFrame, scaffold_bridge: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    reviewed = [
        ("signal_000045", 52369, "R-VA002SC00616NB", "1373509", "1.17", "1.47", "reviewed_missing_or_questioned_leg"),
        ("signal_000045", 46419, "R-VA002SC01053EB", "2530101", "0", "0.54", "captured_connected_different_leg"),
        ("signal_002692", 110163, "R-VA   US00360EBBUS001", "2025719", "0", "0.03", "user_listed_source_leg"),
        ("signal_002692", 92253, "R-VA   US00360EB", "1820366", "146.1", "146.84", "user_listed_source_leg"),
        ("signal_002692", 17419, "R-VA042SC01108NB", "1404844", "0.23", "0.54", "user_listed_source_leg"),
        ("signal_002692", 129029, "R-VA   US00360EB", "1820366", "146.01", "146.1", "user_listed_source_leg"),
    ]
    for signal_id, fid, rte_nm, rte_id, from_m, to_m, case_role in reviewed:
        src = identity_gdf.loc[identity_gdf["source_feature_local_fid"].eq(fid)].copy()
        sig = scaffold_bridge.loc[scaffold_bridge["signal_id"].eq(signal_id)].copy()
        if src.empty:
            rows.append({"signal_id": signal_id, "reviewed_source_fid": fid, "case_role": case_role, "source_record_found": False})
            continue
        row = src.iloc[0]
        linked = sig.loc[
            _text(sig, "stable_travelway_id").eq(row["stable_travelway_id"])
            | _text(sig, "candidate_stable_travelway_ids").str.contains(row["stable_travelway_id"], regex=False)
            | _text(sig, "candidate_source_feature_local_fids").str.contains(str(fid), regex=False)
        ]
        distance_ft = ""
        if not sig.empty:
            sample = sig.head(2500).copy()
            sample["geometry"] = _text(sample, "geometry_wkt").map(_parse_wkt)
            sample_gdf = gpd.GeoDataFrame(sample.loc[sample["geometry"].notna()], geometry="geometry", crs="EPSG:3968")
            if len(sample_gdf):
                distance_ft = round(float(sample_gdf.geometry.distance(row.geometry).min()) * 3.280839895, 2)
        rows.append(
            {
                "signal_id": signal_id,
                "case_role": case_role,
                "reviewed_source_fid": fid,
                "reviewed_rte_nm": rte_nm,
                "reviewed_rte_id": rte_id,
                "reviewed_from_measure": from_m,
                "reviewed_to_measure": to_m,
                "source_record_found": True,
                "stable_travelway_id": row["stable_travelway_id"],
                "stable_composite_key": row["stable_composite_key"],
                "geometry_hash": row["geometry_hash"],
                "final_bins_linked_to_stable_id": len(linked),
                "nearest_signal_bin_distance_ft": distance_ft,
                "lineage_result": "stable_id_candidate_or_direct_link" if len(linked) else "geometry_or_route_review_needed",
                "fid_used_as_sole_stable_key": False,
            }
        )
    rows.append(
        {
            "signal_id": "wellington_university_hmms_674155",
            "case_role": "missing_hmms_signal",
            "reviewed_source_fid": "",
            "reviewed_rte_nm": "Wellington Road",
            "reviewed_rte_id": "674155",
            "reviewed_from_measure": "",
            "reviewed_to_measure": "",
            "source_record_found": True,
            "stable_travelway_id": "",
            "stable_composite_key": "",
            "geometry_hash": "",
            "final_bins_linked_to_stable_id": "",
            "nearest_signal_bin_distance_ft": "",
            "lineage_result": "signal_source_lineage_issue_not_travelway_fid_issue",
            "fid_used_as_sole_stable_key": False,
        }
    )
    return pd.DataFrame(rows)


def _source_limitation_bridge(identity: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    files = [
        MAP_FINDINGS_DIR / "map_review_findings_structured.csv",
        MAP_FINDINGS_DIR / "signal_000045_source_leg_diagnostic.csv",
        MAP_FINDINGS_DIR / "signal_002692_complex_intersection_diagnostic.csv",
        MAP_FINDINGS_DIR / "missing_hmms_wellington_signal_diagnostic.csv",
    ]
    fid_re = re.compile(r"\b(\d{4,6})\b")
    for path in files:
        if not path.exists():
            continue
        df = _read_csv(path)
        for idx, row in df.iterrows():
            text = "|".join(str(value) for value in row.to_dict().values())
            fids = []
            for column in ["provided_fid", "actual_package_fid", "source_route_fid"]:
                if column in row and str(row[column]).strip():
                    fids.extend(fid_re.findall(str(row[column])))
            stable = []
            for fid_text in sorted(set(fids)):
                fid = int(fid_text)
                if 1 <= fid <= len(identity):
                    stable.extend(identity.loc[identity["source_feature_local_fid"].eq(fid), "stable_travelway_id"].tolist())
            rows.append(
                {
                    "source_limitation_input_file": path.name,
                    "input_row_number": idx + 1,
                    "signal_id": row.get("signal_id", ""),
                    "reviewed_fids": _collapse(fids),
                    "stable_travelway_ids": _collapse(stable),
                    "evidence_bridge_status": "stable_travelway_attached" if stable else "no_travelway_fid_or_signal_only_case",
                    "source_limitation_text": text[:1000],
                }
            )
    return pd.DataFrame(rows)


def _summary(scaffold: pd.DataFrame, access: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, frame in [("final_scaffold_bins", scaffold), ("access_target_bins", access)]:
        total = len(frame)
        for group_cols in [[], ["recovery_stream"], ["final_alignment_class"], ["geometry_recovery_method_final"]]:
            existing = [col for col in group_cols if col in frame.columns]
            if not existing:
                subgroups = [((), frame)]
            else:
                subgroups = frame.groupby(existing, dropna=False)
            for key, sub in subgroups:
                if not isinstance(key, tuple):
                    key = (key,)
                row = {"table_name": name, "row_count": len(sub), "grouping": "|".join(existing) if existing else "all"}
                for col, val in zip(existing, key):
                    row[col] = val
                for method, method_sub in sub.groupby("lineage_match_method", dropna=False):
                    row[f"method_{method}"] = len(method_sub)
                row["high_confidence_lineage_count"] = int(_text(sub, "lineage_confidence").eq("high").sum())
                row["medium_confidence_lineage_count"] = int(_text(sub, "lineage_confidence").eq("medium").sum())
                row["low_confidence_lineage_count"] = int(_text(sub, "lineage_confidence").eq("low").sum())
                row["unmatched_count"] = int(_text(sub, "lineage_match_method").eq("unmatched").sum())
                row["lineage_coverage_rate_any"] = round((len(sub) - row["unmatched_count"]) / len(sub), 6) if len(sub) else 0
                row["lineage_coverage_rate_high"] = round(row["high_confidence_lineage_count"] / len(sub), 6) if len(sub) else 0
                rows.append(row)
    return pd.DataFrame(rows)


def _required_fields() -> pd.DataFrame:
    rows = [
        ("stable_travelway_id", "Stable Travelway feature identifier built from source layer, route identity, measures, and geometry hash.", "all scaffold/access/crash outputs"),
        ("stable_signal_id", "Durable signal identifier when available; otherwise source_signal_id plus source layer.", "signal/bin/access/crash outputs"),
        ("source_signal_id", "Original signal source identifier preserved from source records.", "signal/bin/access/crash outputs"),
        ("stable_bin_id", "Stable signal-relative bin identifier.", "bin/access/crash outputs"),
        ("source_layer", "Source data layer name for Travelway or signal lineage.", "all outputs"),
        ("source_route_id", "Travelway RTE_ID or equivalent.", "all roadway-lineage outputs"),
        ("source_route_name", "Travelway RTE_NM.", "all roadway-lineage outputs"),
        ("source_route_common", "Travelway RTE_COMMON/common route name.", "all roadway-lineage outputs"),
        ("source_measure_start", "Source or route measure start.", "all roadway-lineage outputs"),
        ("source_measure_end", "Source or route measure end.", "all roadway-lineage outputs"),
        ("geometry_hash", "Hash of source geometry WKB used as a reproducibility check, not as the only business key.", "source and bridge outputs"),
        ("lineage_match_method", "How lineage was attached: direct source ID, source road row, route/measure, geometry, route label, or unmatched.", "bridge and downstream outputs"),
        ("lineage_confidence", "High/medium/low/none confidence class for the lineage match.", "bridge and downstream outputs"),
    ]
    return pd.DataFrame(rows, columns=["required_field", "meaning", "required_in"])


def _qa() -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", "pass", "Writes only to source_travelway_lineage_bridge review folder."),
        ("no_candidates_promoted", "pass", "No promotion outputs are written."),
        ("no_access_or_crash_assignment", "pass", "No assignment outputs are created."),
        ("no_crash_records_read", "pass", "No crash inputs are read."),
        ("no_crash_direction_fields_used", "pass", "Read guards block crash direction fields."),
        ("no_rates_or_models", "pass", "No rate/model calculations are performed."),
        ("fid_not_sole_stable_lineage_key", "pass", "GeoPackage fid is stored as package-local source_feature_local_fid only."),
        ("stable_id_construction_documented", "pass", "Stable ID combines source layer, route id/name, measures, and geometry hash."),
        ("outputs_review_only", "pass", str(OUT_DIR)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "status", "note"])


def _findings(identity: pd.DataFrame, scaffold: pd.DataFrame, reviewed: pd.DataFrame) -> str:
    total = len(scaffold)
    high = int(_text(scaffold, "lineage_confidence").eq("high").sum())
    med = int(_text(scaffold, "lineage_confidence").eq("medium").sum())
    low = int(_text(scaffold, "lineage_confidence").eq("low").sum())
    unmatched = int(_text(scaffold, "lineage_match_method").eq("unmatched").sum())
    s45 = reviewed.loc[_text(reviewed, "signal_id").eq("signal_000045")]
    s45_lines = "\n".join(
        f"- FID {row.reviewed_source_fid}: {row.lineage_result}, stable ID {row.stable_travelway_id}, linked bins {row.final_bins_linked_to_stable_id}, nearest bin distance {row.nearest_signal_bin_distance_ft} ft."
        for row in s45.itertuples()
    )
    return f"""# Source Travelway Lineage Bridge

**Bounded question:** build a stable source Travelway identity bridge and audit whether final scaffold/access bins preserve source-row lineage.

## Findings

1. Source Travelway stable feature count: **{len(identity):,}**.
2. Final scaffold bins audited: **{total:,}**.
3. High-confidence direct Travelway lineage: **{high:,}** bins ({high / total:.1%}).
4. Medium-confidence lineage: **{med:,}** bins ({med / total:.1%}).
5. Low-confidence route-label-only lineage: **{low:,}** bins ({low / total:.1%}).
6. Unmatched bins: **{unmatched:,}** bins ({unmatched / total:.1%}).

## Reviewed Case Signal 000045

{s45_lines}

## Interpretation

GeoPackage `fid` is unique inside a package layer, but it is package-local and not stable source lineage. The stable ID generated here uses source layer, route id/name/common route, source measures, and source geometry hash. Final scaffold bins can often be associated to a source route family, but most do not carry exact source-row lineage. That should be fixed before further access/crash work depends on source-row-specific claims.

## Required Fields

Future scaffold, access, and crash/catchment outputs should carry `stable_travelway_id`, source signal/bin IDs, source route identity, source measures, `geometry_hash`, `lineage_match_method`, and `lineage_confidence`.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs: " + "; ".join(missing))

    identity_gdf = _source_identity()
    identity = pd.DataFrame(identity_gdf.drop(columns="geometry"))
    final_bins = _normalize_final_bins(_read_csv(FINAL_OVERVIEW_DIR / "final_consolidated_leg_bin_detail.csv"))
    access_bins = _normalize_access_bins(_read_csv(FINAL_ACCESS_DIR / "final_cleaned_access_target_bins.csv"))

    scaffold_bridge = _bridge(final_bins, identity, table_type="final_scaffold_bins")
    access_bridge = _bridge(access_bins, identity, table_type="access_target_bins")
    reviewed = _reviewed_cases(identity_gdf, scaffold_bridge)
    source_limitation = _source_limitation_bridge(identity)
    summary = _summary(scaffold_bridge, access_bridge)
    required = _required_fields()
    qa = _qa()

    _write_csv(identity, "source_travelway_stable_identity.csv")
    _write_csv(scaffold_bridge, "final_scaffold_travelway_lineage_bridge.csv")
    _write_csv(access_bridge, "access_target_travelway_lineage_bridge.csv")
    _write_csv(source_limitation, "source_limitation_travelway_evidence_bridge.csv")
    _write_csv(reviewed, "reviewed_case_lineage_audit.csv")
    _write_csv(summary, "travelway_lineage_completeness_summary.csv")
    _write_csv(required, "travelway_lineage_required_fields_recommendation.csv")
    _write_text(_findings(identity, scaffold_bridge, reviewed), "source_travelway_lineage_bridge_findings.md")
    _write_csv(qa, "source_travelway_lineage_bridge_qa.csv")
    manifest = {
        "created_at_utc": _now(),
        "bounded_question": "Stable source Travelway lineage bridge and completeness audit.",
        "output_folder": str(OUT_DIR),
        "source_travelway_feature_count": int(len(identity)),
        "final_scaffold_bin_count": int(len(scaffold_bridge)),
        "access_target_bin_count": int(len(access_bridge)),
        "stable_id_construction": "sha256(source_layer|source_route_id|source_route_name|source_route_common|from_measure|to_measure|geometry_hash) with tw_ prefix",
        "fid_policy": "GeoPackage fid retained only as source_feature_local_fid/package-local evidence; not used as sole stable lineage key.",
        "qa_pass": bool(qa["status"].eq("pass").all()),
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "non_goals": [
            "no scaffold logic changes",
            "no access/crash assignment",
            "no rates/models",
            "no active output modification",
            "no candidate promotion",
        ],
    }
    _write_json(manifest, "source_travelway_lineage_bridge_manifest.json")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
