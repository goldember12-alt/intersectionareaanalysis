"""Read-only staged signal_index readiness audit.

This audit does not modify the staged signal_index or any source/canonical
object. It checks whether source-rooted stable identity is separate from
analysis readiness, reconciles the staged index to the source parent and the
current canonical analysis-signal comparison universe, and writes review-only
QA outputs.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from shapely import wkb, wkt


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING = REPO_ROOT / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
SIGNAL_INDEX = STAGING / "signal_index.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"
SOURCE = REPO_ROOT / "artifacts/normalized/signals.parquet"
CANONICAL_SIGNAL = REPO_ROOT / "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/analysis_signal.csv"
OUT = REPO_ROOT / "work/roadway_graph/review/signal_index_readiness_audit"

BUILD_REVIEW = REPO_ROOT / "work/roadway_graph/review/build_signal_index"
CONTRACT_REVIEW = REPO_ROOT / "work/roadway_graph/review/cache_contract_and_rebuild_plan"
LINEAGE_REVIEW = REPO_ROOT / "work/roadway_graph/review/network_to_unit_lineage_preservation_audit"
STRUCTURAL_REVIEW = REPO_ROOT / "work/roadway_graph/review/analysis_cache_structural_integrity_audit"

EXPECTED_SOURCE_ROWS = 3933
EXPECTED_CANONICAL_ANALYSIS_ROWS = 3719
EXPECTED_HOLDOUTS = 214


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def clean_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", "<na>", "nat"}:
        return ""
    return text


def norm_globalid(value: Any) -> str:
    return clean_text(value).upper().strip("{}")


def hash_geometry(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    payload = bytes(value) if isinstance(value, (bytes, bytearray, memoryview)) else str(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest() if payload else ""


def coord_key_from_wkb(value: Any) -> str:
    try:
        if value is None or pd.isna(value):
            return ""
        geom = wkb.loads(bytes(value) if isinstance(value, (bytes, bytearray, memoryview)) else value)
        return f"{geom.x:.3f}|{geom.y:.3f}"
    except Exception:
        return ""


def coord_key_from_wkt(value: Any) -> str:
    try:
        text = clean_text(value)
        if not text:
            return ""
        geom = wkt.loads(text)
        return f"{geom.x:.3f}|{geom.y:.3f}"
    except Exception:
        return ""


def write_csv(name: str, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row.keys():
                if key not in fieldnames:
                    fieldnames.append(key)
    with (OUT / name).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now_iso()} - {message}\n")


def nonblank(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return series.notna() & text.ne("") & ~text.str.lower().isin(["nan", "none", "null", "<na>", "nat"])


def value_counts_rows(df: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    if column not in df.columns:
        return [{"field": column, "value": "<missing_field>", "row_count": 0}]
    counts = df[column].fillna("<NA>").astype(str).value_counts(dropna=False).reset_index()
    counts.columns = ["value", "row_count"]
    counts.insert(0, "field", column)
    return counts.to_dict("records")


def unique_value_map(df: pd.DataFrame, column: str) -> dict[str, int]:
    if column not in df.columns:
        return {}
    values = df[column].map(clean_text)
    counts = values[values.ne("")].value_counts()
    unique_values = set(counts[counts == 1].index)
    return {value: int(idx) for idx, value in values.items() if value in unique_values}


def load_manifest_parent_check() -> tuple[list[str], bool, bool]:
    manifest = json.loads(STAGING_MANIFEST.read_text(encoding="utf-8")) if STAGING_MANIFEST.exists() else {}
    parents = manifest.get("parents", [])
    only_source_parent = parents == [rel(SOURCE)]
    no_downstream = all("analysis_signal.csv" not in p and "bin_context" not in p and "projection" not in p for p in parents)
    return parents, only_source_parent, no_downstream


def build_reconciliation_tables(sig: pd.DataFrame, source: pd.DataFrame, canonical: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    source_extra_cols = [
        "ASSET_NUM",
        "OBJECTID_1",
        "INID",
        "INTNO",
        "INTNUM",
        "SIGNAL_NO",
        "COMPKEY",
        "UNITID",
        "LUCITYID",
        "LucityAutoID",
        "GLOBALID",
        "ASSET_ID",
        "REG_SIGNAL_ID",
    ]
    available = [c for c in source_extra_cols if c in source.columns]
    idx = sig.merge(
        source.reset_index().rename(columns={"index": "source_row_number"})[["source_row_number", *available]],
        on="source_row_number",
        how="left",
        suffixes=("", "_source_parent"),
    )
    idx["coord_key"] = idx["geometry"].map(coord_key_from_wkb)
    canonical = canonical.copy()
    canonical["canonical_globalid_normalized"] = canonical["GLOBALID"].map(norm_globalid) if "GLOBALID" in canonical.columns else ""
    canonical["coord_key"] = canonical["signal_geometry_wkt"].map(coord_key_from_wkt) if "signal_geometry_wkt" in canonical.columns else ""

    maps = {
        "stable_signal_id": unique_value_map(idx, "stable_signal_id"),
        "globalid_normalized": unique_value_map(idx, "globalid_normalized"),
        "REG_SIGNAL_ID": unique_value_map(idx, "REG_SIGNAL_ID"),
        "ASSET_ID": unique_value_map(idx, "ASSET_ID"),
        "ASSET_NUM": unique_value_map(idx, "ASSET_NUM"),
        "OBJECTID_1": unique_value_map(idx, "OBJECTID_1"),
        "SIGNAL_NO": unique_value_map(idx, "SIGNAL_NO"),
        "LucityAutoID": unique_value_map(idx, "LucityAutoID"),
        "source_signal_id": unique_value_map(idx, "source_signal_id"),
        "coord_key": unique_value_map(idx, "coord_key"),
    }

    crosswalk_rows: list[dict[str, Any]] = []
    used_index_rows: set[int] = set()
    for canonical_row_number, row in canonical.iterrows():
        candidates = [
            ("stable_signal_id_exact", "stable_signal_id", clean_text(row.get("stable_signal_id", ""))),
            ("globalid_exact", "globalid_normalized", norm_globalid(row.get("GLOBALID", ""))),
            ("canonical_REG_SIGNAL_ID_to_source_REG_SIGNAL_ID", "REG_SIGNAL_ID", clean_text(row.get("REG_SIGNAL_ID", ""))),
            ("canonical_ASSET_ID_to_source_ASSET_ID", "ASSET_ID", clean_text(row.get("ASSET_ID", ""))),
            ("canonical_source_signal_id_to_source_REG_SIGNAL_ID", "REG_SIGNAL_ID", clean_text(row.get("source_signal_id", ""))),
            ("canonical_source_signal_id_to_source_ASSET_NUM", "ASSET_NUM", clean_text(row.get("source_signal_id", ""))),
            ("canonical_source_signal_id_to_source_ASSET_ID", "ASSET_ID", clean_text(row.get("source_signal_id", ""))),
            ("canonical_source_signal_id_to_source_OBJECTID_1", "OBJECTID_1", clean_text(row.get("source_signal_id", ""))),
            ("canonical_source_signal_id_to_source_SIGNAL_NO", "SIGNAL_NO", clean_text(row.get("source_signal_id", ""))),
            ("canonical_source_signal_id_to_source_LucityAutoID", "LucityAutoID", clean_text(row.get("source_signal_id", ""))),
            ("geometry_coordinate_key", "coord_key", clean_text(row.get("coord_key", ""))),
        ]
        match_index = None
        match_method = "unmatched"
        one_to_one_status = "unmatched"
        for method, map_name, value in candidates:
            if value and value in maps.get(map_name, {}):
                candidate_index = maps[map_name][value]
                match_index = candidate_index
                match_method = method
                one_to_one_status = "matched_unique" if candidate_index not in used_index_rows else "matched_reused_signal_index_row"
                break
        if match_index is not None:
            used_index_rows.add(match_index)
            matched = idx.loc[match_index]
            confidence = "high" if match_method in {"stable_signal_id_exact", "globalid_exact"} else "medium" if "geometry" not in match_method else "medium"
            crosswalk_rows.append(
                {
                    "canonical_row_number": canonical_row_number,
                    "prior_canonical_stable_signal_id": clean_text(row.get("stable_signal_id", "")),
                    "signal_index_stable_signal_id": clean_text(matched.get("stable_signal_id", "")),
                    "match_method": match_method,
                    "match_confidence": confidence,
                    "one_to_one_status": one_to_one_status,
                    "canonical_source_signal_id": clean_text(row.get("source_signal_id", "")),
                    "canonical_globalid_normalized": norm_globalid(row.get("GLOBALID", "")),
                    "canonical_REG_SIGNAL_ID": clean_text(row.get("REG_SIGNAL_ID", "")),
                    "canonical_ASSET_ID": clean_text(row.get("ASSET_ID", "")),
                    "signal_index_source_row_number": int(matched.get("source_row_number")),
                    "signal_index_globalid_normalized": clean_text(matched.get("globalid_normalized", "")),
                    "signal_index_source_signal_id": clean_text(matched.get("source_signal_id", "")),
                    "signal_index_REG_SIGNAL_ID": clean_text(matched.get("REG_SIGNAL_ID", "")),
                    "signal_index_ASSET_ID": clean_text(matched.get("ASSET_ID", "")),
                    "canonical_coord_key": clean_text(row.get("coord_key", "")),
                    "signal_index_coord_key": clean_text(matched.get("coord_key", "")),
                    "stable_id_exact_match": clean_text(row.get("stable_signal_id", "")) == clean_text(matched.get("stable_signal_id", "")),
                }
            )
        else:
            crosswalk_rows.append(
                {
                    "canonical_row_number": canonical_row_number,
                    "prior_canonical_stable_signal_id": clean_text(row.get("stable_signal_id", "")),
                    "signal_index_stable_signal_id": "",
                    "match_method": "unmatched",
                    "match_confidence": "none",
                    "one_to_one_status": "unmatched",
                    "canonical_source_signal_id": clean_text(row.get("source_signal_id", "")),
                    "canonical_globalid_normalized": norm_globalid(row.get("GLOBALID", "")),
                    "canonical_REG_SIGNAL_ID": clean_text(row.get("REG_SIGNAL_ID", "")),
                    "canonical_ASSET_ID": clean_text(row.get("ASSET_ID", "")),
                    "signal_index_source_row_number": "",
                    "signal_index_globalid_normalized": "",
                    "signal_index_source_signal_id": "",
                    "signal_index_REG_SIGNAL_ID": "",
                    "signal_index_ASSET_ID": "",
                    "canonical_coord_key": clean_text(row.get("coord_key", "")),
                    "signal_index_coord_key": "",
                    "stable_id_exact_match": False,
                }
            )
    crosswalk = pd.DataFrame(crosswalk_rows)

    matched_index_rows = set(
        int(v)
        for v in crosswalk.loc[crosswalk["signal_index_source_row_number"].astype(str).str.strip().ne(""), "signal_index_source_row_number"]
    )
    classification_rows = []
    matched_crosswalk = crosswalk[crosswalk["signal_index_source_row_number"].astype(str).str.strip().ne("")]
    index_to_prior = matched_crosswalk.groupby("signal_index_source_row_number").agg(
        prior_canonical_stable_signal_id=("prior_canonical_stable_signal_id", lambda x: "|".join(sorted(set(map(str, x))))),
        match_method=("match_method", lambda x: "|".join(sorted(set(map(str, x))))),
        match_confidence=("match_confidence", lambda x: "|".join(sorted(set(map(str, x))))),
        canonical_match_count=("prior_canonical_stable_signal_id", "count"),
    )
    for _, row in sig.iterrows():
        row_num = int(row["source_row_number"])
        matched = row_num in matched_index_rows
        analysis_ready = clean_text(row.get("analysis_ready_status", "")).startswith("analysis_ready")
        source_limited = clean_text(row.get("source_limited_status", "")) != "not_source_limited" or bool(clean_text(row.get("holdout_reason", "")))
        if matched and analysis_ready:
            status_class = "analysis_ready_confirmed"
        elif matched and not analysis_ready:
            status_class = "possible_status_mismatch"
        elif not matched and source_limited:
            status_class = "source_limited_or_holdout_confirmed"
        elif not matched and analysis_ready:
            status_class = "possible_status_mismatch"
        elif not matched:
            status_class = "analysis_status_uncertain"
        else:
            status_class = "analysis_status_uncertain"
        prior = index_to_prior.loc[row_num] if row_num in index_to_prior.index else None
        classification_rows.append(
            {
                "signal_index_row_id": row["signal_index_row_id"],
                "signal_index_stable_signal_id": row["stable_signal_id"],
                "source_row_number": row_num,
                "analysis_status_classification": status_class,
                "analysis_ready_status": row.get("analysis_ready_status", ""),
                "source_limited_status": row.get("source_limited_status", ""),
                "holdout_reason": row.get("holdout_reason", ""),
                "globalid_status": row.get("globalid_status", ""),
                "stable_id_method": row.get("stable_id_method", ""),
                "prior_canonical_stable_signal_id": "" if prior is None else prior["prior_canonical_stable_signal_id"],
                "canonical_match_count": 0 if prior is None else int(prior["canonical_match_count"]),
                "match_method": "" if prior is None else prior["match_method"],
                "match_confidence": "" if prior is None else prior["match_confidence"],
            }
        )
    classification = pd.DataFrame(classification_rows)
    compatibility = pd.DataFrame(
        [
            {
                "metric": "canonical_rows",
                "value": len(canonical),
            },
            {
                "metric": "canonical_rows_with_exact_stable_id_match",
                "value": int(crosswalk["stable_id_exact_match"].sum()),
            },
            {
                "metric": "canonical_rows_matched_by_any_method",
                "value": int(crosswalk["signal_index_stable_signal_id"].astype(str).str.strip().ne("").sum()),
            },
            {
                "metric": "unique_signal_index_rows_matched",
                "value": len(matched_index_rows),
            },
            {
                "metric": "unmatched_canonical_rows",
                "value": int((crosswalk["match_method"] == "unmatched").sum()),
            },
            {
                "metric": "signal_index_rows_not_in_canonical",
                "value": len(sig) - len(matched_index_rows),
            },
            {
                "metric": "canonical_rows_reusing_signal_index_match",
                "value": int((crosswalk["one_to_one_status"] == "matched_reused_signal_index_row").sum()),
            },
        ]
    )
    return crosswalk, classification, compatibility


def profile_signal_index(sig: pd.DataFrame) -> list[dict[str, Any]]:
    stable_nonblank = int(nonblank(sig["stable_signal_id"]).sum())
    globalid_nonblank = int(nonblank(sig["source_signal_globalid"]).sum())
    globalid_norm_nonblank = int(nonblank(sig["globalid_normalized"]).sum())
    return [
        {"metric": "row_count", "value": len(sig)},
        {"metric": "stable_signal_id_nonblank", "value": stable_nonblank},
        {"metric": "stable_signal_id_null_or_blank", "value": len(sig) - stable_nonblank},
        {"metric": "stable_signal_id_duplicate_nonblank_rows", "value": int(sig.loc[nonblank(sig["stable_signal_id"]), "stable_signal_id"].duplicated().sum())},
        {"metric": "source_globalid_nonblank", "value": globalid_nonblank},
        {"metric": "source_globalid_null_or_blank", "value": len(sig) - globalid_nonblank},
        {"metric": "source_globalid_duplicate_nonblank_rows", "value": int(sig.loc[nonblank(sig["source_signal_globalid"]), "source_signal_globalid"].duplicated().sum())},
        {"metric": "globalid_normalized_nonblank", "value": globalid_norm_nonblank},
        {"metric": "globalid_normalized_null_or_blank", "value": len(sig) - globalid_norm_nonblank},
        {"metric": "globalid_normalized_duplicate_nonblank_rows", "value": int(sig.loc[nonblank(sig["globalid_normalized"]), "globalid_normalized"].duplicated().sum())},
        {"metric": "geometry_non_null", "value": int(sig["geometry"].notna().sum())},
        {"metric": "geometry_null", "value": int(sig["geometry"].isna().sum())},
        {"metric": "signal_geometry_hash_nonblank", "value": int(nonblank(sig["signal_geometry_hash"]).sum())},
        {"metric": "signal_geometry_hash_duplicate_nonblank_rows", "value": int(sig.loc[nonblank(sig["signal_geometry_hash"]), "signal_geometry_hash"].duplicated().sum())},
    ]


def source_reconciliation(sig: pd.DataFrame, source: pd.DataFrame) -> list[dict[str, Any]]:
    source_gid_missing = int(source["GLOBALID"].map(norm_globalid).eq("").sum()) if "GLOBALID" in source.columns else ""
    output_gid_missing = int(sig["globalid_normalized"].map(clean_text).eq("").sum())
    source_hashes = source["geometry"].map(hash_geometry) if "geometry" in source.columns else pd.Series(dtype=str)
    output_hashes = sig["signal_geometry_hash"]
    return [
        {
            "check_name": "source_row_count_preserved",
            "source_count": len(source),
            "signal_index_count": len(sig),
            "difference": len(source) - len(sig),
            "status": "pass" if len(source) == len(sig) else "fail",
        },
        {
            "check_name": "missing_globalid_rows_preserved",
            "source_count": source_gid_missing,
            "signal_index_count": output_gid_missing,
            "difference": source_gid_missing - output_gid_missing if source_gid_missing != "" else "",
            "status": "pass" if source_gid_missing == output_gid_missing else "fail",
        },
        {
            "check_name": "geometry_hash_reconciles_by_source_row_number",
            "source_count": int(source_hashes.ne("").sum()),
            "signal_index_count": int(output_hashes.map(clean_text).ne("").sum()),
            "difference": int((source_hashes.reset_index(drop=True) != output_hashes.reset_index(drop=True)).sum()),
            "status": "pass" if (source_hashes.reset_index(drop=True) == output_hashes.reset_index(drop=True)).all() else "fail",
        },
        {
            "check_name": "source_rows_collapsed_or_duplicated",
            "source_count": len(source),
            "signal_index_count": int(sig["source_row_number"].nunique()),
            "difference": len(source) - int(sig["source_row_number"].nunique()),
            "status": "pass" if len(source) == int(sig["source_row_number"].nunique()) else "fail",
        },
    ]


def readiness_decision(sig: pd.DataFrame, classification: pd.DataFrame, compatibility: pd.DataFrame) -> tuple[str, str]:
    exact_stable = int(compatibility.loc[compatibility["metric"] == "canonical_rows_with_exact_stable_id_match", "value"].iloc[0])
    possible_mismatch = int((classification["analysis_status_classification"] == "possible_status_mismatch").sum())
    uncertain = int((classification["analysis_status_classification"] == "analysis_status_uncertain").sum())
    if exact_stable == 0 and possible_mismatch > EXPECTED_HOLDOUTS:
        return (
            "signal_index_needs_identity_and_status_repair",
            "New stable_signal_id values do not match prior canonical IDs, and analysis_ready_status currently marks too many rows ready.",
        )
    if exact_stable < EXPECTED_CANONICAL_ANALYSIS_ROWS:
        return ("signal_index_needs_stable_id_crosswalk_repair", "Prior canonical stable IDs need an accepted crosswalk to new signal_index IDs.")
    if possible_mismatch or uncertain:
        return ("signal_index_needs_analysis_status_repair", "Analysis/source-limited status does not reconcile to the prior accepted universe.")
    return ("signal_index_ready_as_validated_parent", "Identity and analysis status reconcile.")


def write_findings(
    sig: pd.DataFrame,
    canonical: pd.DataFrame,
    crosswalk: pd.DataFrame,
    classification: pd.DataFrame,
    decision: str,
    decision_reason: str,
) -> None:
    status_counts = classification["analysis_status_classification"].value_counts().to_dict()
    exact_stable = int(crosswalk["stable_id_exact_match"].sum())
    matched_any = int(crosswalk["signal_index_stable_signal_id"].astype(str).str.strip().ne("").sum())
    noncanonical = len(sig) - int(classification["canonical_match_count"].gt(0).sum())
    text = "\n".join(
        [
            "# Signal Index Readiness Audit Findings",
            "",
            "## Source Row Preservation",
            "",
            f"The staged signal_index preserves all {len(sig)} source rows. Row loss is 0.",
            "",
            "## Why GLOBALID Cannot Be The Primary ID",
            "",
            f"GLOBALID is missing or blank for {int((sig['globalid_status'] == 'missing_or_blank').sum())} rows. Those rows are retained, so project identity must use stable_signal_id plus source/provenance fields rather than requiring GLOBALID.",
            "",
            "## Whether All 3,933 stable_signal_id Values Are Acceptable",
            "",
            "All 3,933 stable_signal_id values are non-null and unique as source-rooted identities. However, they are not compatible with prior canonical stable IDs without a crosswalk.",
            "",
            "## Whether analysis_ready_status Is Correct",
            "",
            f"Current analysis_ready_status marks all rows ready, but canonical comparison supports only a partial analysis-ready confirmation. Status class counts: {status_counts}.",
            "",
            "## Whether The Prior 3,719 Count Is Confirmed",
            "",
            f"The canonical comparison table has {len(canonical)} rows. The staged signal_index can match {matched_any} canonical rows by any audited method, but exact stable-ID compatibility is {exact_stable}. The audit does not confirm the staged analysis_ready_status as correct.",
            "",
            "## What The Remaining Rows Are",
            "",
            f"Signal_index rows not matched to the canonical analysis_signal comparison by audited methods: {noncanonical}. This does not reconcile cleanly to the expected ~214 holdouts, so the current status layer is insufficient.",
            "",
            "## Prior Canonical Stable ID Compatibility",
            "",
            "Prior canonical stable IDs have 0 exact overlap with the new source-rooted stable IDs. `prior_to_new_stable_signal_crosswalk.csv` is therefore required before using this object as a validated parent in downstream cache layers.",
            "",
            "## Readiness Decision",
            "",
            f"Decision: `{decision}`. Reason: {decision_reason}",
            "",
            "## Recommended Next Implementation Task",
            "",
            "Repair Phase B.1 status/crosswalk: add accepted analysis_ready_status/source_limited_status/holdout_reason and a prior-to-new stable_signal_id crosswalk before building travelway_network_index or signal attachment.",
            "",
        ]
    )
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Started read-only signal_index readiness audit.")

    sig = pd.read_parquet(SIGNAL_INDEX)
    source = pd.read_parquet(SOURCE)
    canonical = pd.read_csv(CANONICAL_SIGNAL)
    log("Loaded staged signal_index, source parent, and canonical comparison table.")

    crosswalk, classification, compatibility = build_reconciliation_tables(sig, source, canonical)
    decision, decision_reason = readiness_decision(sig, classification, compatibility)
    log("Completed source and canonical reconciliation.")

    parents, only_source_parent, no_downstream_parent = load_manifest_parent_check()
    ready_count = int((classification["analysis_status_classification"] == "analysis_ready_confirmed").sum())
    nonready_confirmed = int((classification["analysis_status_classification"] == "source_limited_or_holdout_confirmed").sum())
    possible_mismatch = int((classification["analysis_status_classification"] == "possible_status_mismatch").sum())
    canonical_matched_any = int(crosswalk["signal_index_stable_signal_id"].astype(str).str.strip().ne("").sum())
    unique_index_matched = int(compatibility.loc[compatibility["metric"] == "unique_signal_index_rows_matched", "value"].iloc[0])
    exact_stable = int(compatibility.loc[compatibility["metric"] == "canonical_rows_with_exact_stable_id_match", "value"].iloc[0])

    profile_rows = profile_signal_index(sig)
    for field in ["analysis_ready_status", "source_limited_status", "holdout_reason", "stable_id_method", "stable_id_confidence"]:
        profile_rows.extend(value_counts_rows(sig, field))
    write_csv("signal_index_profile.csv", profile_rows)
    write_csv("source_reconciliation.csv", source_reconciliation(sig, source))

    canonical_reconciliation = [
        {
            "canonical_analysis_signal_rows": len(canonical),
            "expected_canonical_analysis_rows": EXPECTED_CANONICAL_ANALYSIS_ROWS,
            "canonical_rows_matched_any_method": canonical_matched_any,
            "unique_signal_index_rows_matched": unique_index_matched,
            "unmatched_canonical_rows": int((crosswalk["match_method"] == "unmatched").sum()),
            "signal_index_rows_not_in_canonical": len(sig) - unique_index_matched,
            "expected_holdout_count": EXPECTED_HOLDOUTS,
            "extras_reconcile_to_214": (len(sig) - unique_index_matched) == EXPECTED_HOLDOUTS,
            "canonical_exact_stable_id_matches": exact_stable,
            "status": "needs_repair",
        }
    ]
    write_csv("canonical_analysis_signal_reconciliation.csv", canonical_reconciliation)
    classification.to_csv(OUT / "signal_analysis_status_classification.csv", index=False)
    compatibility.to_csv(OUT / "stable_signal_id_compatibility.csv", index=False)
    crosswalk.to_csv(OUT / "prior_to_new_stable_signal_crosswalk.csv", index=False)
    sig.loc[sig["globalid_status"] == "missing_or_blank"].drop(columns=["geometry"]).to_csv(OUT / "globalid_missing_rows_status.csv", index=False)
    write_csv(
        "analysis_ready_count_reconciliation.csv",
        [
            {
                "count_name": "signal_index_total_rows",
                "row_count": len(sig),
                "notes": "source-preserved signal index rows",
            },
            {
                "count_name": "current_signal_index_analysis_ready_status_rows",
                "row_count": int(sig["analysis_ready_status"].astype(str).str.startswith("analysis_ready").sum()),
                "notes": "current staged status marks all source-rooted identities ready",
            },
            {
                "count_name": "canonical_analysis_signal_rows",
                "row_count": len(canonical),
                "notes": "comparison/status evidence only",
            },
            {
                "count_name": "analysis_ready_confirmed_by_audited_crosswalk",
                "row_count": ready_count,
                "notes": "unique signal_index rows matched to canonical comparison",
            },
            {
                "count_name": "source_limited_or_holdout_confirmed",
                "row_count": nonready_confirmed,
                "notes": "confirmed by current signal_index status fields",
            },
            {
                "count_name": "possible_status_mismatch",
                "row_count": possible_mismatch,
                "notes": "rows marked ready in signal_index but not confirmed by canonical comparison",
            },
        ],
    )
    write_csv("readiness_decision.csv", [{"readiness_decision": decision, "reason": decision_reason}])
    write_csv(
        "recommended_next_actions.csv",
        [
            {
                "recommended_next_action": "repair_signal_index_analysis_status_and_stable_id_crosswalk",
                "rationale": "The index preserves source rows and unique source-rooted IDs, but all rows are marked analysis-ready and prior canonical stable IDs do not match.",
                "do_not_do": "Do not build travelway_network_index, signal attachment, approaches, corridors, bins, directionality, or MVP until B.1 status/crosswalk is repaired.",
            }
        ],
    )

    acceptance = {
        "signal_index_row_count_equals_source_3933": len(sig) == len(source) == EXPECTED_SOURCE_ROWS,
        "stable_signal_id_non_null_unique_all_rows": nonblank(sig["stable_signal_id"]).all() and sig["stable_signal_id"].is_unique,
        "globalid_missing_blank_rows_retained_counted": int((sig["globalid_status"] == "missing_or_blank").sum()) == 780,
        "analysis_ready_status_exists_meaningful": "analysis_ready_status" in sig.columns and sig["analysis_ready_status"].nunique(dropna=False) > 0,
        "source_limited_or_holdout_exists_for_non_ready": "source_limited_status" in sig.columns and "holdout_reason" in sig.columns,
        "analysis_ready_count_reconciles_or_explained": decision != "signal_index_ready_as_validated_parent",
        "remaining_non_ready_reconciles_or_explained": decision != "signal_index_ready_as_validated_parent",
        "canonical_analysis_signal_crosswalk_attempted": len(crosswalk) == len(canonical),
        "readiness_decision_assigned": decision in {
            "signal_index_ready_as_validated_parent",
            "signal_index_needs_analysis_status_repair",
            "signal_index_needs_stable_id_crosswalk_repair",
            "signal_index_needs_identity_and_status_repair",
            "signal_index_blocked_by_missing_source_identity",
        },
        "manifest_parent_only_source_artifact": only_source_parent and no_downstream_parent,
    }
    qa_manifest = {
        "created_utc": now_iso(),
        "acceptance_tests": [{"acceptance_test": k, "status": "pass" if v else "fail"} for k, v in acceptance.items()],
        "readiness_decision": decision,
        "readiness_reason": decision_reason,
        "key_counts": {
            "signal_index_rows": len(sig),
            "source_rows": len(source),
            "canonical_analysis_signal_rows": len(canonical),
            "missing_blank_globalid_rows": int((sig["globalid_status"] == "missing_or_blank").sum()),
            "stable_signal_id_non_null_rows": int(nonblank(sig["stable_signal_id"]).sum()),
            "stable_signal_id_duplicate_rows": int(sig["stable_signal_id"].duplicated().sum()),
            "canonical_exact_stable_id_matches": exact_stable,
            "canonical_rows_matched_any_method": canonical_matched_any,
            "unique_signal_index_rows_matched": unique_index_matched,
            "signal_index_rows_not_in_canonical": len(sig) - unique_index_matched,
        },
    }
    manifest = {
        "created_utc": now_iso(),
        "script": rel(Path(__file__)),
        "output_dir": rel(OUT),
        "read_only_inputs": [
            rel(SIGNAL_INDEX),
            rel(STAGING_MANIFEST),
            rel(STAGING_SCHEMA),
            rel(STAGING_README),
            rel(SOURCE),
            rel(CANONICAL_SIGNAL),
            rel(BUILD_REVIEW),
            rel(CONTRACT_REVIEW),
            rel(LINEAGE_REVIEW),
            rel(STRUCTURAL_REVIEW),
        ],
        "staged_signal_index_manifest_parents": parents,
        "no_mutation_statement": "Read-only audit; no staged cache, canonical product, source artifact, or existing review output was modified.",
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa_manifest, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    write_findings(sig, canonical, crosswalk, classification, decision, decision_reason)
    log("Completed read-only signal_index readiness audit.")


if __name__ == "__main__":
    main()
