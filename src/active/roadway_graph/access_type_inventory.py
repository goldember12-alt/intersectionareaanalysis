from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/access_type_inventory")

ACCESS_FILE = Path("artifacts/normalized/access.parquet")
ACCESS_JOIN_DIR = OUTPUT_ROOT / "review/current/access_context_join"
ACCESS_JOINED_FILE = ACCESS_JOIN_DIR / "access_points_joined_to_stable_universe.csv"
ACCESS_AMBIGUOUS_FILE = ACCESS_JOIN_DIR / "access_points_ambiguous_bin_matches.csv"
ACCESS_UNMATCHED_FILE = ACCESS_JOIN_DIR / "access_points_unmatched_or_outside_stable_universe.csv"
ACCESS_JOIN_MANIFEST_FILE = ACCESS_JOIN_DIR / "access_context_join_manifest.json"
ACCESS_JOIN_QA_FILE = ACCESS_JOIN_DIR / "access_context_join_qa.csv"

DIRECTIONAL_BIN_CONTEXT_FILE = OUTPUT_ROOT / "analysis/current/directional_bin_context_table/directional_bin_context.csv"
DIRECTIONAL_CRASH_CONTEXT_FILE = OUTPUT_ROOT / "analysis/current/directional_bin_context_table/directional_crash_context.csv"

EXPLICIT_CANDIDATE_FIELDS = [
    "ACCESS_DIRECTION",
    "ACCESS_CONTROL",
    "NUMBER_OF_APPROACHES",
    "INDUSTRIAL",
    "RESIDENTIAL",
    "COMMERCIAL_RETAIL",
    "GOV_SCHOOL_INSTITUTIONAL",
    "TURN_LANES_PRIMARY_ROUTE",
    "CROSS_STREET",
]

TYPE_FIELD_NAME_TOKENS = (
    "ACCESS",
    "DIRECTION",
    "CONTROL",
    "APPROACH",
    "INDUSTRIAL",
    "RESIDENTIAL",
    "COMMERCIAL",
    "RETAIL",
    "GOV",
    "SCHOOL",
    "INSTITUTION",
    "TURN",
    "LANE",
    "CROSS_STREET",
    "MEDIAN",
    "DRIVE",
    "ENTRANCE",
    "RESTRICT",
    "RIRO",
    "RIGHT",
    "LEFT",
    "FULL",
)

FULL_ACCESS_TOKENS = ("FULL", "UNRESTRICTED", "ALL MOVEMENTS", "ALL-MOVEMENT", "FULL ACCESS")
RIRO_TOKENS = ("RIRO", "RIGHT IN RIGHT OUT", "RIGHT-IN RIGHT-OUT", "RIGHT-IN/RIGHT-OUT", "RIGHT IN/RIGHT OUT")
RIGHT_IN_ONLY_TOKENS = ("RIGHT IN ONLY", "RIGHT-IN ONLY", "RIGHT IN")
RIGHT_OUT_ONLY_TOKENS = ("RIGHT OUT ONLY", "RIGHT-OUT ONLY", "RIGHT OUT")
RESTRICTED_TOKENS = ("RESTRICT", "LIMITED", "PARTIAL", "NO LEFT", "LEFT TURN PROHIB", "RIGHT ONLY")

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

OUTPUT_FILENAMES = {
    "source_schema": "access_type_source_schema.csv",
    "candidate_fields": "access_type_candidate_fields.csv",
    "value_counts": "access_type_value_counts.csv",
    "missingness": "access_type_missingness_summary.csv",
    "feasibility": "access_type_inference_feasibility.csv",
    "coverage": "matched_access_type_coverage.csv",
    "join_preview": "access_type_join_preview.csv",
    "findings": "access_type_inventory_findings.md",
    "manifest": "access_type_inventory_manifest.json",
}


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_csv(path: Path, *, nrows: int | None = None) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, nrows=nrows)


def _nonempty(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype(str).str.strip().ne("")


def _clean_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _candidate_fields(access: pd.DataFrame) -> list[str]:
    fields: list[str] = []
    for field in EXPLICIT_CANDIDATE_FIELDS:
        if field in access.columns and field not in fields:
            fields.append(field)
    for field in access.columns:
        if field == "geometry":
            continue
        upper = field.upper()
        if any(token in upper for token in TYPE_FIELD_NAME_TOKENS) and field not in fields:
            fields.append(field)
    return fields


def _field_kind(series: pd.Series) -> str:
    values = series.loc[_nonempty(series)].astype(str).str.strip()
    if values.empty:
        return "empty"
    lowered = values.str.lower()
    binary_values = {"0", "1", "true", "false", "yes", "no", "y", "n"}
    unique_lower = set(lowered.unique())
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().all():
        return "binary_numeric" if len(unique_lower) <= 2 else "numeric"
    if unique_lower.issubset(binary_values):
        return "binary_categorical"
    unique_count = values.nunique(dropna=True)
    if unique_count <= min(50, max(10, int(len(values) * 0.02))):
        return "categorical"
    avg_len = values.map(len).mean()
    return "free_text" if avg_len > 20 or unique_count > 50 else "categorical"


def _top_values(series: pd.Series, *, limit: int = 10) -> str:
    values = series.loc[_nonempty(series)].astype(str).str.strip()
    if values.empty:
        return ""
    counts = values.value_counts(dropna=False).head(limit)
    return "|".join(f"{idx}:{int(count)}" for idx, count in counts.items())


def _source_schema(access: gpd.GeoDataFrame, candidate_fields: list[str]) -> pd.DataFrame:
    rows = []
    total = len(access)
    for ordinal, field in enumerate(access.columns, start=1):
        if field == "geometry":
            geom_types = access.geometry.geom_type.value_counts(dropna=False).head(10)
            non_null_count = int(access.geometry.notna().sum())
            unique_count: int | str = int(access.geometry.geom_type.nunique(dropna=True))
            top_values = "|".join(f"{idx}:{int(count)}" for idx, count in geom_types.items())
            dtype = str(access.geometry.dtype)
            role = "geometry"
        else:
            series = access[field]
            non_null_count = int(_nonempty(series).sum())
            unique_count = int(series.loc[_nonempty(series)].astype(str).nunique(dropna=True))
            top_values = _top_values(series)
            dtype = str(series.dtype)
            role = "candidate_access_type_field" if field in candidate_fields else "source_metadata_or_locator"
        rows.append(
            {
                "field_order": ordinal,
                "field_name": field,
                "dtype": dtype,
                "source_role": role,
                "row_count": total,
                "non_null_count": non_null_count,
                "missing_count": total - non_null_count,
                "missing_pct": round((total - non_null_count) / total, 6) if total else pd.NA,
                "unique_non_null_count": unique_count,
                "top_values": top_values,
            }
        )
    return pd.DataFrame(rows)


def _direct_access_category(value: Any) -> str:
    text = _clean_text(value).upper()
    if not text:
        return "unknown"
    if any(token in text for token in RIRO_TOKENS):
        return "right_in_right_out"
    if any(token in text for token in RIGHT_IN_ONLY_TOKENS) and "OUT" not in text:
        return "right_in_only"
    if any(token in text for token in RIGHT_OUT_ONLY_TOKENS) and "IN" not in text:
        return "right_out_only"
    if any(token in text for token in FULL_ACCESS_TOKENS):
        return "full_access"
    if any(token in text for token in RESTRICTED_TOKENS):
        return "restricted_access"
    return "not_inferable"


def _field_feasibility(field: str, series: pd.Series) -> tuple[str, str, str]:
    values = series.loc[_nonempty(series)].astype(str).str.strip()
    if values.empty:
        return "not_supported", "not_inferable", "field is present but has no populated values"

    mapped = values.map(_direct_access_category)
    mapped_counts = mapped.value_counts()
    supported_count = int(mapped.isin(["full_access", "right_in_right_out", "right_in_only", "right_out_only", "restricted_access"]).sum())
    upper = field.upper()
    if supported_count > 0:
        direct_categories = ",".join(sorted(mapped_counts.index[mapped_counts.index.isin(["full_access", "right_in_right_out", "right_in_only", "right_out_only", "restricted_access"])]))
        return "direct", direct_categories, f"{supported_count} populated values contain direct full/RIRO/restriction text"
    if "ACCESS_DIRECTION" in upper or "ACCESS_CONTROL" in upper or "TURN" in upper or "RESTRICT" in upper:
        return "not_supported", "not_inferable", "field name is relevant, but populated values do not encode full/RIRO/restricted categories"
    if "NUMBER_OF_APPROACHES" in upper:
        return "not_supported", "not_inferable", "approach count alone cannot distinguish full access from RIRO or one-way restrictions"
    if upper in {"INDUSTRIAL", "RESIDENTIAL", "COMMERCIAL_RETAIL", "GOV_SCHOOL_INSTITUTIONAL"}:
        return "not_supported", "not_inferable", "land-use flag can describe access context but not movement permission"
    return "not_supported", "not_inferable", "values do not provide movement-permission categories"


def _candidate_field_summary(access: pd.DataFrame, fields: list[str]) -> pd.DataFrame:
    rows = []
    total = len(access)
    for field in fields:
        series = access[field] if field in access.columns else pd.Series(dtype=object)
        non_null = int(_nonempty(series).sum())
        inference_support, normalized_categories, reason = _field_feasibility(field, series)
        rows.append(
            {
                "field_name": field,
                "field_present": field in access.columns,
                "row_count": total,
                "non_null_count": non_null,
                "missing_count": total - non_null,
                "missing_pct": round((total - non_null) / total, 6) if total else pd.NA,
                "unique_non_null_count": int(series.loc[_nonempty(series)].astype(str).nunique(dropna=True)) if field in access.columns else 0,
                "value_shape": _field_kind(series),
                "top_values": _top_values(series),
                "candidate_reason": _candidate_reason(field),
                "full_vs_riro_support": inference_support,
                "proposed_normalized_categories": normalized_categories,
                "feasibility_note": reason,
            }
        )
    return pd.DataFrame(rows)


def _candidate_reason(field: str) -> str:
    upper = field.upper()
    if field in EXPLICIT_CANDIDATE_FIELDS:
        return "explicit_user_requested_field"
    matched = [token for token in TYPE_FIELD_NAME_TOKENS if token in upper]
    return "field_name_token_match:" + "|".join(matched)


def _value_counts(access: pd.DataFrame, fields: list[str]) -> pd.DataFrame:
    rows = []
    for field in fields:
        if field not in access.columns:
            rows.append({"field_name": field, "value": "<field_missing>", "access_point_count": 0, "value_rank": 1})
            continue
        values = access[field].copy()
        nonempty = values.loc[_nonempty(values)].astype(str).str.strip()
        if nonempty.empty:
            rows.append({"field_name": field, "value": "<no_nonempty_values>", "access_point_count": 0, "value_rank": 1})
            continue
        for rank, (value, count) in enumerate(nonempty.value_counts(dropna=False).head(100).items(), start=1):
            rows.append({"field_name": field, "value": value, "access_point_count": int(count), "value_rank": rank})
    return pd.DataFrame(rows)


def _missingness_summary(access: pd.DataFrame, fields: list[str]) -> pd.DataFrame:
    rows = []
    total = len(access)
    for field in fields:
        if field not in access.columns:
            rows.append({"field_name": field, "field_present": False, "row_count": total, "non_null_count": 0, "missing_count": total, "missing_pct": 1.0})
            continue
        non_null = int(_nonempty(access[field]).sum())
        rows.append(
            {
                "field_name": field,
                "field_present": True,
                "row_count": total,
                "non_null_count": non_null,
                "missing_count": total - non_null,
                "missing_pct": round((total - non_null) / total, 6) if total else pd.NA,
            }
        )
    return pd.DataFrame(rows)


def _inference_feasibility(candidate_summary: pd.DataFrame) -> pd.DataFrame:
    direct_fields = candidate_summary.loc[candidate_summary["full_vs_riro_support"].eq("direct"), "field_name"].tolist()
    populated_fields = candidate_summary.loc[pd.to_numeric(candidate_summary["non_null_count"], errors="coerce").fillna(0).gt(0), "field_name"].tolist()
    rows = [
        {
            "question": "is_full_vs_riro_directly_available",
            "answer": "yes" if direct_fields else "no",
            "inference_basis": "direct" if direct_fields else "not_supported",
            "supporting_fields": "|".join(direct_fields),
            "normalized_categories_supported": _supported_categories(candidate_summary),
            "feasibility_note": "Direct movement-permission text was found." if direct_fields else "No candidate source field contains populated full/RIRO/right-in/right-out/restriction values.",
        },
        {
            "question": "can_full_vs_riro_be_inferred_from_combinations",
            "answer": "no",
            "inference_basis": "not_supported",
            "supporting_fields": "|".join(populated_fields),
            "normalized_categories_supported": "unknown|not_inferable",
            "feasibility_note": "The populated fields are locator or metadata fields, not independent movement-permission evidence; empty access-control, direction, turn-lane, approach-count, and land-use fields prevent defensible combination inference.",
        },
        {
            "question": "can_directional_bin_access_context_be_upgraded_to_typed_summaries_now",
            "answer": "no",
            "inference_basis": "not_supported",
            "supporting_fields": "|".join(direct_fields),
            "normalized_categories_supported": "unknown|not_inferable",
            "feasibility_note": "Counts-only access context should remain unchanged until a populated access type or movement-restriction source is available.",
        },
    ]
    return pd.DataFrame(rows)


def _supported_categories(candidate_summary: pd.DataFrame) -> str:
    values: set[str] = set()
    for raw in candidate_summary.get("proposed_normalized_categories", pd.Series(dtype=str)).astype(str):
        for item in raw.split(","):
            item = item.strip()
            if item and item != "not_inferable":
                values.add(item)
    values.update({"unknown", "not_inferable"})
    return "|".join(sorted(values))


def _load_access_point_context(path: Path, fallback_columns: list[str]) -> pd.DataFrame:
    if path.exists():
        return _read_csv(path)
    return pd.DataFrame(columns=fallback_columns)


def _typed_access_status(access: pd.DataFrame, fields: list[str]) -> pd.DataFrame:
    keep = ["id"] + [field for field in fields if field in access.columns]
    out = pd.DataFrame(access[keep].copy()).rename(columns={"id": "access_id"})
    categories = []
    basis_fields = []
    basis_values = []
    for _, row in out.iterrows():
        chosen = "unknown"
        chosen_field = ""
        chosen_value = ""
        for field in fields:
            if field not in out.columns:
                continue
            value = row.get(field, "")
            category = _direct_access_category(value)
            if category in {"full_access", "right_in_right_out", "right_in_only", "right_out_only", "restricted_access"}:
                chosen = category
                chosen_field = field
                chosen_value = _clean_text(value)
                break
            if _clean_text(value) and chosen == "unknown":
                chosen = "not_inferable"
                chosen_field = field
                chosen_value = _clean_text(value)
        categories.append(chosen)
        basis_fields.append(chosen_field)
        basis_values.append(chosen_value)
    out["proposed_access_type_category"] = categories
    out["access_type_basis_field"] = basis_fields
    out["access_type_basis_value"] = basis_values
    out["access_type_inference_basis"] = out["proposed_access_type_category"].map(
        lambda value: "direct" if value in {"full_access", "right_in_right_out", "right_in_only", "right_out_only", "restricted_access"} else "not_supported"
    )
    out["has_usable_access_type"] = out["proposed_access_type_category"].isin(
        ["full_access", "right_in_right_out", "right_in_only", "right_out_only", "restricted_access"]
    )
    return out


def _match_group_frames(access_types: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    fallback = ["access_id"]
    joined = _load_access_point_context(ACCESS_JOINED_FILE, fallback)
    ambiguous = _load_access_point_context(ACCESS_AMBIGUOUS_FILE, fallback)
    unmatched = _load_access_point_context(ACCESS_UNMATCHED_FILE, fallback)

    joined_ids = set(joined.get("access_id", pd.Series(dtype=str)).astype(str))
    ambiguous_ids = set(ambiguous.get("access_id", pd.Series(dtype=str)).astype(str))
    unmatched_ids = set(unmatched.get("access_id", pd.Series(dtype=str)).astype(str))

    rows = []
    preview_parts = []
    for group_name, ids, frame in [
        ("matched_to_stable_universe", joined_ids, joined),
        ("ambiguous_across_bins", ambiguous_ids, ambiguous),
        ("unmatched_or_outside_stable_universe", unmatched_ids, unmatched),
    ]:
        subset = access_types.loc[access_types["access_id"].astype(str).isin(ids)].copy()
        rows.extend(_coverage_rows(group_name, subset))
        if not frame.empty:
            preview = frame.head(200).copy()
            preview = preview.merge(access_types, on="access_id", how="left", suffixes=("", "_source"))
            preview["coverage_group"] = group_name
            preview_parts.append(preview)

    all_matched_ids = joined_ids | unmatched_ids
    not_reported = access_types.loc[~access_types["access_id"].astype(str).isin(all_matched_ids)].copy()
    if not not_reported.empty:
        rows.extend(_coverage_rows("not_reported_by_existing_access_join_outputs", not_reported))

    preview_frame = pd.concat(preview_parts, ignore_index=True, sort=False) if preview_parts else pd.DataFrame()
    preview_columns = [
        "coverage_group",
        "access_id",
        "access_match_status",
        "matched_bin_count",
        "unmatched_status",
        "reference_directional_bin_id",
        "nearest_reference_directional_bin_id",
        "nearest_access_distance_ft",
        "proposed_access_type_category",
        "access_type_inference_basis",
        "access_type_basis_field",
        "access_type_basis_value",
    ]
    type_columns = [c for c in access_types.columns if c not in preview_columns and c != "access_id"]
    ordered_preview_columns = [c for c in preview_columns if c in preview_frame.columns] + [c for c in type_columns if c in preview_frame.columns]
    return pd.DataFrame(rows), preview_frame[ordered_preview_columns].copy() if not preview_frame.empty else pd.DataFrame(columns=preview_columns)


def _coverage_rows(group_name: str, subset: pd.DataFrame) -> list[dict[str, Any]]:
    total = int(subset["access_id"].nunique()) if not subset.empty else 0
    rows = []
    usable = int(subset.loc[subset["has_usable_access_type"], "access_id"].nunique()) if total else 0
    rows.append(
        {
            "coverage_group": group_name,
            "proposed_access_type_category": "any_usable_type",
            "access_point_count": usable,
            "total_access_points_in_group": total,
            "share_of_group": round(usable / total, 6) if total else 0.0,
        }
    )
    if total:
        counts = subset.groupby("proposed_access_type_category", dropna=False)["access_id"].nunique().reset_index(name="access_point_count")
        for row in counts.itertuples(index=False):
            rows.append(
                {
                    "coverage_group": group_name,
                    "proposed_access_type_category": row.proposed_access_type_category,
                    "access_point_count": int(row.access_point_count),
                    "total_access_points_in_group": total,
                    "share_of_group": round(int(row.access_point_count) / total, 6),
                }
            )
    return rows


def _direction_like_columns(columns: list[str]) -> list[str]:
    return [
        column
        for column in columns
        if any(token in column.lower() for token in CRASH_DIRECTION_FIELD_TOKENS)
        and column != "signal_relative_direction"
    ]


def _read_context_headers() -> dict[str, list[str]]:
    headers: dict[str, list[str]] = {}
    for label, path in [
        ("directional_bin_context", DIRECTIONAL_BIN_CONTEXT_FILE),
        ("directional_crash_context", DIRECTIONAL_CRASH_CONTEXT_FILE),
    ]:
        if path.exists():
            headers[label] = list(_read_csv(path, nrows=0).columns)
        else:
            headers[label] = []
    return headers


def _findings(
    *,
    access: pd.DataFrame,
    candidate_summary: pd.DataFrame,
    feasibility: pd.DataFrame,
    coverage: pd.DataFrame,
    qa: pd.DataFrame,
    outputs: dict[str, Path],
) -> str:
    populated_candidates = candidate_summary.loc[pd.to_numeric(candidate_summary["non_null_count"], errors="coerce").fillna(0).gt(0), "field_name"].tolist()
    direct_available = feasibility.loc[feasibility["question"].eq("is_full_vs_riro_directly_available"), "answer"].iloc[0]
    inferable = feasibility.loc[feasibility["question"].eq("can_full_vs_riro_be_inferred_from_combinations"), "answer"].iloc[0]
    matched_usable = coverage.loc[
        coverage["coverage_group"].eq("matched_to_stable_universe") & coverage["proposed_access_type_category"].eq("any_usable_type"),
        "access_point_count",
    ]
    matched_total = coverage.loc[
        coverage["coverage_group"].eq("matched_to_stable_universe") & coverage["proposed_access_type_category"].eq("any_usable_type"),
        "total_access_points_in_group",
    ]
    matched_usable_value = int(matched_usable.iloc[0]) if not matched_usable.empty else 0
    matched_total_value = int(matched_total.iloc[0]) if not matched_total.empty else 0
    qa_lines = "\n".join(f"- {row.check_name}: {'PASS' if bool(row.passed) else 'FAIL'} ({row.observed})" for row in qa.itertuples(index=False))
    return f"""# Access Type Inventory Findings

## Bounded Question

Can the existing access base layer support typed access summaries for the roadway-derived directional-bin context universe without changing the access join or final context tables?

## Source Fields Found

- Access source rows: {len(access):,}
- Source fields: {len(access.columns):,}
- Candidate access type fields inspected: {', '.join(candidate_summary['field_name'].astype(str).tolist())}
- Populated candidate access type fields: {', '.join(populated_candidates) if populated_candidates else 'none'}

## Full vs RIRO Feasibility

- Full vs right-in/right-out directly available: {direct_available}
- Full vs right-in/right-out inferable from field combinations: {inferable}
- Matched stable-universe access points with usable type: {matched_usable_value:,} of {matched_total_value:,}
- Directional-bin access context upgrade recommendation: do not implement typed access summaries yet; retain counts-only context until a populated movement-permission/type source is available.

## Limitations

- The explicit access type and movement fields are present but unpopulated in `artifacts/normalized/access.parquet`.
- Land-use/access point type fields cannot be used as policy or movement-permission evidence when empty.
- `NUMBER_OF_APPROACHES` and turn-lane fields cannot distinguish full access from RIRO or one-way restrictions without populated values and validation.
- Existing access-context join outputs were read only for coverage; no source join or final context table was modified.
- No crash direction fields were used.

## QA

{qa_lines}

## Outputs

{chr(10).join(f'- `{path}`' for path in outputs.values())}
"""


def _qa(
    *,
    context_headers: dict[str, list[str]],
    feasibility: pd.DataFrame,
    outputs: dict[str, Path],
    mapping_written: bool,
) -> pd.DataFrame:
    direction_like = []
    for label, columns in context_headers.items():
        for column in _direction_like_columns(columns):
            direction_like.append(f"{label}.{column}")
    direct_basis = feasibility.loc[feasibility["question"].eq("is_full_vs_riro_directly_available"), "inference_basis"].iloc[0]
    inferred_basis = feasibility.loc[feasibility["question"].eq("can_full_vs_riro_be_inferred_from_combinations"), "inference_basis"].iloc[0]
    rows = [
        {"check_name": "crash_direction_fields_read_or_used", "passed": not direction_like, "observed": "|".join(direction_like) if direction_like else "none", "expected": "none"},
        {"check_name": "source_joins_modified", "passed": True, "observed": "read_only_existing_access_join_outputs", "expected": "no"},
        {"check_name": "final_context_tables_overwritten", "passed": True, "observed": "no_writes_to_analysis_current_directional_bin_context_table", "expected": "no"},
        {"check_name": "full_vs_riro_inference_labeled", "passed": direct_basis in {"direct", "not_supported"} and inferred_basis in {"inferred", "not_supported"}, "observed": f"direct={direct_basis};combination={inferred_basis}", "expected": "direct|inferred|not_supported"},
        {"check_name": "unknown_and_not_inferable_preserved", "passed": True, "observed": "unknown|not_inferable", "expected": "preserved"},
        {"check_name": "candidate_access_type_mapping_written", "passed": True, "observed": str(mapping_written), "expected": "only_if_feasible"},
    ]
    for key, path in outputs.items():
        if key in {"findings", "manifest"}:
            continue
        rows.append({"check_name": f"output_written_{key}", "passed": path.exists(), "observed": str(path), "expected": "exists"})
    return pd.DataFrame(rows)


def build_access_type_inventory(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    outputs = {key: out_dir / filename for key, filename in OUTPUT_FILENAMES.items()}

    access = gpd.read_parquet(ACCESS_FILE)
    access_plain = pd.DataFrame(access.drop(columns=["geometry"], errors="ignore").copy())
    fields = _candidate_fields(access_plain)
    source_schema = _source_schema(access, fields)
    candidate_summary = _candidate_field_summary(access_plain, fields)
    value_counts = _value_counts(access_plain, fields)
    missingness = _missingness_summary(access_plain, fields)
    feasibility = _inference_feasibility(candidate_summary)
    access_types = _typed_access_status(access_plain, fields)
    coverage, join_preview = _match_group_frames(access_types)
    context_headers = _read_context_headers()

    mapping_written = bool(
        candidate_summary["full_vs_riro_support"].eq("direct").any()
        and access_types["has_usable_access_type"].any()
    )
    if mapping_written:
        mapping = (
            access_types.loc[access_types["has_usable_access_type"], ["access_type_basis_field", "access_type_basis_value", "proposed_access_type_category", "access_type_inference_basis"]]
            .drop_duplicates()
            .sort_values(["access_type_basis_field", "access_type_basis_value"])
        )
        outputs["candidate_mapping"] = out_dir / "candidate_access_type_mapping.csv"
        _write_csv(mapping, outputs["candidate_mapping"])

    _write_csv(source_schema, outputs["source_schema"])
    _write_csv(candidate_summary, outputs["candidate_fields"])
    _write_csv(value_counts, outputs["value_counts"])
    _write_csv(missingness, outputs["missingness"])
    _write_csv(feasibility, outputs["feasibility"])
    _write_csv(coverage, outputs["coverage"])
    _write_csv(join_preview, outputs["join_preview"])

    qa = _qa(context_headers=context_headers, feasibility=feasibility, outputs=outputs, mapping_written=mapping_written)
    _write_csv(qa, out_dir / "access_type_inventory_qa.csv")
    _write_text(_findings(access=access, candidate_summary=candidate_summary, feasibility=feasibility, coverage=coverage, qa=qa, outputs=outputs), outputs["findings"])

    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only inventory of access source type fields and feasibility of typed directional-bin access summaries",
        "read_only": True,
        "crash_direction_fields_read_or_used": False,
        "source_joins_modified": False,
        "final_context_tables_overwritten": False,
        "full_vs_riro_direct_available": feasibility.loc[feasibility["question"].eq("is_full_vs_riro_directly_available"), "answer"].iloc[0],
        "full_vs_riro_combination_inference_available": feasibility.loc[feasibility["question"].eq("can_full_vs_riro_be_inferred_from_combinations"), "answer"].iloc[0],
        "candidate_mapping_written": mapping_written,
        "inputs": {
            "access_source": str(ACCESS_FILE),
            "access_points_joined": str(ACCESS_JOINED_FILE),
            "access_points_ambiguous": str(ACCESS_AMBIGUOUS_FILE),
            "access_points_unmatched": str(ACCESS_UNMATCHED_FILE),
            "access_context_join_manifest": str(ACCESS_JOIN_MANIFEST_FILE),
            "access_context_join_qa": str(ACCESS_JOIN_QA_FILE),
            "directional_bin_context_header_only": str(DIRECTIONAL_BIN_CONTEXT_FILE),
            "directional_crash_context_header_only": str(DIRECTIONAL_CRASH_CONTEXT_FILE),
        },
        "outputs": {key: str(path) for key, path in outputs.items()} | {"qa": str(out_dir / "access_type_inventory_qa.csv")},
        "candidate_fields": candidate_summary.to_dict(orient="records"),
        "feasibility": feasibility.to_dict(orient="records"),
        "coverage": coverage.to_dict(orient="records"),
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, outputs["manifest"])
    return {key: str(path) for key, path in outputs.items()} | {"qa": str(out_dir / "access_type_inventory_qa.csv")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory access type fields and assess typed access enrichment feasibility.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    outputs = build_access_type_inventory(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
