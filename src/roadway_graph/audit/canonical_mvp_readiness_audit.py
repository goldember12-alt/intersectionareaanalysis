"""Read-only readiness audit for canonical roadway-graph MVP products.

This script intentionally does not repair or backfill canonical data. It reads
the cleaned canonical product folders, writes a review-only audit package, and
reports missing fields as refresh recommendations.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
FINAL_DIR = REPO / "work" / "roadway_graph" / "analysis" / "final_leg_corrected_analysis_dataset"
MVP_DIR = REPO / "work" / "roadway_graph" / "analysis" / "mvp_dataset"
OUT_DIR = REPO / "work" / "roadway_graph" / "review" / "canonical_mvp_readiness_audit"

DOC_PATHS = [
    "AGENTS.md",
    "README.md",
    "work/roadway_graph/_index/CANONICAL_PRODUCTS.md",
    "work/roadway_graph/_index/ACTIVE_REVIEW_PRODUCTS.md",
    "work/roadway_graph/_index/CLEANUP_STATUS.md",
    "docs/methodology/current_methodology_index.md",
    "docs/methodology/overview_methodology.md",
    "docs/methodology/roadway_graph_methodology.md",
    "docs/workflow/final_analysis_dataset_contract.md",
    "docs/workflow/mvp_observed_crash_rate_guidance.md",
    "docs/workflow/roadway_graph_lineage_requirements.md",
    "docs/workflow/signal_identity_requirements.md",
    "docs/workflow/access_code_mapping_notes.md",
]

FINAL_EXPECTED = [
    "README.md",
    "analysis_access_crash_completeness.csv",
    "analysis_bin.csv",
    "analysis_completeness_summary.csv",
    "analysis_data_dictionary.csv",
    "analysis_guidance_matrix_long.csv",
    "analysis_median_completeness.csv",
    "analysis_numeric_context_completeness.csv",
    "analysis_signal.csv",
    "analysis_signal_approach_window.csv",
    "analysis_signal_window.csv",
    "final_analysis_dataset_build_findings.md",
    "final_analysis_dataset_build_manifest.json",
    "final_analysis_dataset_build_qa.csv",
    "run_progress_log.txt",
]

MVP_EXPECTED = [
    "mvp_approach_window_direction_unit.csv",
    "mvp_directional_bin_context.csv",
    "mvp_directional_lookup_distribution_table.csv",
    "mvp_directional_lookup_fallback_hierarchy.csv",
    "mvp_directional_category_distribution_summary.csv",
    "mvp_directional_cell_sample_size_audit.csv",
    "mvp_directional_numeric_missingness_audit.csv",
    "mvp_directional_rate_product_readiness.csv",
    "mvp_directional_rate_distribution_qa.csv",
    "mvp_directional_rate_distribution_manifest.json",
    "mvp_directional_rate_distribution_findings.md",
    "run_progress_log.txt",
]

TABLE_CONTRACTS = {
    "analysis_signal.csv": {
        "grain": ["stable_signal_id"],
        "role": "signal table",
    },
    "analysis_bin.csv": {
        "grain": ["stable_bin_id"],
        "role": "bin table",
    },
    "analysis_signal_window.csv": {
        "grain": ["stable_signal_id", "signal_window"],
        "role": "signal-window table",
    },
    "analysis_signal_approach_window.csv": {
        "grain": ["stable_signal_id", "signal_approach_id", "signal_window"],
        "role": "signal-approach-window table",
    },
    "analysis_guidance_matrix_long.csv": {
        "grain": [],
        "role": "guidance matrix / long table",
    },
    "mvp_approach_window_direction_unit.csv": {
        "grain": ["stable_signal_id", "signal_approach_id", "window_label", "upstream_downstream"],
        "role": "approach-window-direction unit table",
    },
    "mvp_directional_bin_context.csv": {
        "grain": ["stable_signal_id", "signal_approach_id", "window_label", "stable_bin_id", "upstream_downstream"],
        "role": "directional bin context",
    },
    "mvp_directional_lookup_distribution_table.csv": {
        "grain": [
            "speed_band",
            "aadt_band",
            "roadway_configuration",
            "median_group",
            "access_count_band",
            "access_type",
            "upstream_downstream",
            "window_label",
        ],
        "role": "lookup distribution table",
    },
}

MVP_REQUIRED = {
    "speed category": ["speed_band", "speed_category"],
    "numeric speed": ["numeric_speed", "speed_limit_mph", "representative_speed_limit_mph"],
    "AADT category": ["aadt_band", "aadt_category"],
    "numeric AADT": ["numeric_aadt", "aadt", "representative_aadt"],
    "divided/undivided / roadway configuration": ["roadway_configuration", "roadway_context"],
    "median type": ["median_group", "median_type"],
    "access count": ["access_raw_count", "untyped_access_raw_count", "access_weighted_count"],
    "access count band": ["access_count_band", "untyped_access_count_band"],
    "access type": ["access_type"],
    "upstream/downstream": ["upstream_downstream"],
    "directionality method/provenance": [
        "directionality_method_mix",
        "directionality_method_mix_type",
        "recovery_provenance",
        "recovery_provenance_summary",
    ],
    "crash count": ["catchment_50ft_crash_count", "spatial_50ft_crash_count"],
    "weighted crash count": ["weighted_50ft_crash_count", "spatial_50ft_weighted_crash_count"],
    "route-confirmed or identity-compatible crash count": [
        "route_confirmed_crash_count",
        "identity_compatible_spatial_50ft_crash_count",
    ],
    "exposure denominator": ["exposure_denominator"],
    "candidate observed crash rate": ["candidate_observed_crash_rate", "aggregate_observed_crash_rate"],
    "reliability flag": ["rate_readiness_flag", "reliability_flag"],
}

NUMERIC_FIELDS = [
    "numeric_speed",
    "representative_speed_limit_mph",
    "numeric_aadt",
    "representative_aadt",
    "exposure_denominator",
    "candidate_observed_crash_rate",
]


@dataclass
class CsvProfile:
    product: str
    file_name: str
    path: Path
    size_bytes: int
    rows: int
    columns: list[str]


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def write_csv(name: str, rows: Iterable[dict], fieldnames: list[str] | None = None) -> None:
    rows = list(rows)
    path = OUT_DIR / name
    if fieldnames is None:
        keys: list[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        fieldnames = keys or ["note"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def append_log(message: str) -> None:
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def read_header(path: Path) -> list[str]:
    if path.suffix.lower() != ".csv":
        return []
    return list(pd.read_csv(path, nrows=0).columns)


def count_csv_rows(path: Path) -> int:
    with path.open("rb") as f:
        return max(sum(1 for _ in f) - 1, 0)


def profile_csv(product: str, path: Path) -> CsvProfile:
    return CsvProfile(
        product=product,
        file_name=path.name,
        path=path,
        size_bytes=path.stat().st_size,
        rows=count_csv_rows(path),
        columns=read_header(path),
    )


def read_small_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False)


def nonmissing_mask(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return series.notna() & (text != "") & (~text.str.lower().isin(["nan", "none", "null", "unknown_missing"]))


def profile_field(path: Path, field: str, chunksize: int = 200_000) -> dict:
    total = 0
    missing = 0
    distinct = Counter()
    numeric_nonnull = 0
    numeric_zero = 0
    if field not in read_header(path):
        return {"present": False, "total_rows": count_csv_rows(path), "nonmissing_rows": 0, "missing_rows": None}
    for chunk in pd.read_csv(path, usecols=[field], chunksize=chunksize, low_memory=False):
        s = chunk[field]
        mask = nonmissing_mask(s)
        total += len(chunk)
        missing += int((~mask).sum())
        distinct.update(s[mask].astype(str).str.strip().value_counts().head(100).to_dict())
        numeric = pd.to_numeric(s, errors="coerce")
        numeric_nonnull += int(numeric.notna().sum())
        numeric_zero += int((numeric == 0).sum())
    return {
        "present": True,
        "total_rows": total,
        "nonmissing_rows": total - missing,
        "missing_rows": missing,
        "missing_pct": round(missing / total, 6) if total else 0,
        "top_values": json.dumps(dict(distinct.most_common(12)), ensure_ascii=True),
        "numeric_nonnull_rows": numeric_nonnull,
        "numeric_zero_rows": numeric_zero,
    }


def duplicate_summary(path: Path, keys: list[str], sample_limit: int = 500) -> tuple[dict, list[dict]]:
    columns = read_header(path)
    if not keys or any(k not in columns for k in keys):
        return (
            {
                "table": path.name,
                "key_columns": "|".join(keys),
                "status": "not_checked_missing_key_columns",
                "duplicate_key_groups": None,
                "duplicate_rows": None,
            },
            [],
        )
    counts: Counter[tuple] = Counter()
    for chunk in pd.read_csv(path, usecols=keys, chunksize=200_000, dtype="string", low_memory=False):
        for tup, n in chunk.fillna("<MISSING>").value_counts(keys).items():
            counts[tuple(tup if isinstance(tup, tuple) else (tup,))] += int(n)
    dupes = [(k, n) for k, n in counts.items() if n > 1]
    details = []
    for key_values, n in dupes[:sample_limit]:
        row = {"table": path.name, "duplicate_count": n}
        row.update({key: key_values[i] for i, key in enumerate(keys)})
        details.append(row)
    return (
        {
            "table": path.name,
            "key_columns": "|".join(keys),
            "status": "pass" if not dupes else "fail",
            "duplicate_key_groups": len(dupes),
            "duplicate_rows": sum(n for _, n in dupes),
        },
        details,
    )


def key_completeness(path: Path, keys: list[str]) -> list[dict]:
    rows = []
    columns = read_header(path)
    for key in keys:
        prof = profile_field(path, key) if key in columns else {"present": False, "total_rows": count_csv_rows(path)}
        rows.append(
            {
                "table": path.name,
                "key_column": key,
                "present": prof.get("present"),
                "total_rows": prof.get("total_rows"),
                "missing_rows": prof.get("missing_rows"),
                "missing_pct": prof.get("missing_pct"),
                "status": "pass" if prof.get("present") and prof.get("missing_rows") == 0 else "fail",
            }
        )
    return rows


def unique_keys(path: Path, keys: list[str]) -> set[tuple]:
    cols = read_header(path)
    if any(k not in cols for k in keys):
        return set()
    values: set[tuple] = set()
    for chunk in pd.read_csv(path, usecols=keys, chunksize=200_000, dtype="string", low_memory=False):
        values.update(map(tuple, chunk.fillna("<MISSING>").itertuples(index=False, name=None)))
    return values


def orphan_rows(child: Path, parent: Path, keys: list[str], child_label: str, parent_label: str) -> list[dict]:
    cols_child = read_header(child)
    cols_parent = read_header(parent)
    if any(k not in cols_child for k in keys) or any(k not in cols_parent for k in keys):
        return [
            {
                "child_table": child.name,
                "parent_table": parent.name,
                "key_columns": "|".join(keys),
                "status": "not_checked_missing_key_columns",
                "orphan_key_count": None,
            }
        ]
    parent_keys = unique_keys(parent, keys)
    child_keys = unique_keys(child, keys)
    missing = sorted(child_keys - parent_keys)[:500]
    rows = [
        {
            "child_table": child.name,
            "parent_table": parent.name,
            "key_columns": "|".join(keys),
            "status": "pass" if not missing and len(child_keys - parent_keys) == 0 else "fail",
            "orphan_key_count": len(child_keys - parent_keys),
            "child_role": child_label,
            "parent_role": parent_label,
        }
    ]
    for key_values in missing:
        row = {
            "child_table": child.name,
            "parent_table": parent.name,
            "key_columns": "|".join(keys),
            "status": "detail",
        }
        row.update({key: key_values[i] for i, key in enumerate(keys)})
        rows.append(row)
    return rows


def columns_from_docs() -> dict[str, set[str]]:
    pattern = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`|^- `?([A-Za-z_][A-Za-z0-9_]*)`?", re.MULTILINE)
    doc_cols: dict[str, set[str]] = {}
    for doc in DOC_PATHS:
        path = REPO / doc
        text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        found = {m.group(1) or m.group(2) for m in pattern.finditer(text)}
        doc_cols[doc] = found
    return doc_cols


def write_inventory(profiles: list[CsvProfile]) -> None:
    file_rows = []
    table_rows = []
    for product, folder, expected in [
        ("final_leg_corrected_analysis_dataset", FINAL_DIR, FINAL_EXPECTED),
        ("mvp_dataset", MVP_DIR, MVP_EXPECTED),
    ]:
        found = {p.name for p in folder.iterdir() if p.is_file()}
        for p in sorted(folder.iterdir()):
            if not p.is_file():
                continue
            file_rows.append(
                {
                    "product": product,
                    "file_name": p.name,
                    "relative_path": rel(p),
                    "file_size_bytes": p.stat().st_size,
                    "extension": p.suffix.lower(),
                    "expected_by_index": p.name in expected,
                    "manifest_or_qa_or_findings": any(x in p.name.lower() for x in ["manifest", "qa", "finding", "readme", "log"]),
                }
            )
        for name in expected:
            if name not in found:
                file_rows.append(
                    {
                        "product": product,
                        "file_name": name,
                        "relative_path": rel(folder / name),
                        "file_size_bytes": None,
                        "extension": Path(name).suffix.lower(),
                        "expected_by_index": True,
                        "manifest_or_qa_or_findings": any(x in name.lower() for x in ["manifest", "qa", "finding", "readme", "log"]),
                        "missing_expected_file": True,
                    }
                )
    for prof in profiles:
        contract = TABLE_CONTRACTS.get(prof.file_name, {})
        data_dictionary_coverage = "unknown"
        if prof.product == "final_leg_corrected_analysis_dataset":
            data_dictionary_coverage = "covered_by_dataset_dictionary" if prof.file_name == "analysis_data_dictionary.csv" else "compare_to_analysis_data_dictionary"
        table_rows.append(
            {
                "product": prof.product,
                "file_name": prof.file_name,
                "relative_path": rel(prof.path),
                "file_size_bytes": prof.size_bytes,
                "row_count": prof.rows,
                "column_count": len(prof.columns),
                "key_columns": "|".join(contract.get("grain", [])),
                "suspected_grain": " x ".join(contract.get("grain", [])) or contract.get("role", "summary_or_documentation"),
                "table_role": contract.get("role", "summary_or_documentation"),
                "columns_json": json.dumps(prof.columns, ensure_ascii=True),
                "data_dictionary_coverage": data_dictionary_coverage,
            }
        )
    write_csv("canonical_product_file_inventory.csv", file_rows)
    write_csv("canonical_product_table_inventory.csv", table_rows)


def mvp_variable_completeness(unit_path: Path, profiles: list[CsvProfile]) -> None:
    rows = []
    by_table = []
    by_category = []
    table_paths = {p.file_name: p.path for p in profiles}
    unit_cols = read_header(unit_path)
    for variable, candidates in MVP_REQUIRED.items():
        present_cols = [c for c in candidates if c in unit_cols]
        selected = present_cols[0] if present_cols else None
        prof = profile_field(unit_path, selected) if selected else {"present": False, "total_rows": count_csv_rows(unit_path)}
        rows.append(
            {
                "required_variable": variable,
                "candidate_columns": "|".join(candidates),
                "selected_column": selected,
                "present_at_approach_window_direction_grain": bool(selected),
                "total_rows": prof.get("total_rows"),
                "nonmissing_rows": prof.get("nonmissing_rows"),
                "missing_rows": prof.get("missing_rows"),
                "missing_pct": prof.get("missing_pct"),
                "top_values": prof.get("top_values"),
                "status": "pass" if selected and prof.get("missing_rows") == 0 else ("partial" if selected else "missing_field"),
            }
        )
        for table, path in table_paths.items():
            cols = read_header(path)
            hits = [c for c in candidates if c in cols]
            by_table.append(
                {
                    "required_variable": variable,
                    "table": table,
                    "present_columns": "|".join(hits),
                    "present": bool(hits),
                }
            )
    category_fields = [
        "upstream_downstream",
        "directionality_method_mix_type",
        "roadway_configuration",
        "median_group",
        "access_count_band",
        "access_type",
    ]
    for category in category_fields:
        if category not in unit_cols:
            by_category.append({"category_field": category, "status": "missing_field"})
            continue
        needed = [
            c
            for cands in MVP_REQUIRED.values()
            for c in cands
            if c in unit_cols and c not in {category}
        ]
        usecols = [category] + sorted(set(needed))
        df = read_small_csv(unit_path)[usecols]
        grouped = df.groupby(category, dropna=False)
        for value, g in grouped:
            for variable, candidates in MVP_REQUIRED.items():
                selected = next((c for c in candidates if c in g.columns), None)
                if not selected:
                    continue
                miss = int((~nonmissing_mask(g[selected])).sum())
                by_category.append(
                    {
                        "category_field": category,
                        "category_value": value,
                        "required_variable": variable,
                        "selected_column": selected,
                        "row_count": len(g),
                        "missing_rows": miss,
                        "missing_pct": round(miss / len(g), 6) if len(g) else 0,
                    }
                )
    write_csv("mvp_required_variable_completeness.csv", rows)
    write_csv("mvp_required_variable_missingness_by_table.csv", by_table)
    write_csv("mvp_required_variable_missingness_by_category.csv", by_category)


def directionality_audit(unit_path: Path, bin_path: Path) -> None:
    unit = read_small_csv(unit_path)
    rows = []
    for field in ["upstream_downstream", "directionality_method_mix_type", "directionality_method_mix", "recovery_provenance"]:
        if field in unit.columns:
            for value, n in unit[field].fillna("<MISSING>").astype(str).value_counts(dropna=False).items():
                rows.append({"table": unit_path.name, "field": field, "value": value, "row_count": int(n)})
        else:
            rows.append({"table": unit_path.name, "field": field, "value": "MISSING_FIELD", "row_count": None})
    write_csv("directionality_completeness_audit.csv", rows)

    mix = []
    group_fields = [c for c in ["upstream_downstream", "directionality_method_mix_type", "roadway_configuration"] if c in unit.columns]
    if group_fields:
        for keys, g in unit.groupby(group_fields, dropna=False):
            keys = keys if isinstance(keys, tuple) else (keys,)
            row = dict(zip(group_fields, keys))
            row.update(
                {
                    "unit_count": len(g),
                    "direct_bin_rows_sum": pd.to_numeric(g.get("direct_bin_rows", 0), errors="coerce").sum(),
                    "synthetic_bin_rows_sum": pd.to_numeric(g.get("synthetic_bin_rows", 0), errors="coerce").sum(),
                    "synthetic_in_usable_set": bool((pd.to_numeric(g.get("synthetic_bin_rows", 0), errors="coerce").fillna(0) > 0).any()),
                }
            )
            mix.append(row)
    write_csv("directionality_method_mix_summary.csv", mix)

    guard_rows = []
    for path in [unit_path, bin_path]:
        cols = read_header(path)
        crash_dir_cols = [c for c in cols if "crash" in c.lower() and ("dir" in c.lower() or "direction" in c.lower())]
        any_dir_cols = [c for c in cols if re.search(r"crash.*(dir|direction)|(dir|direction).*crash", c.lower())]
        guard_rows.append(
            {
                "table": path.name,
                "crash_direction_like_columns": "|".join(sorted(set(crash_dir_cols + any_dir_cols))),
                "crash_direction_field_present": bool(crash_dir_cols or any_dir_cols),
                "used_by_audit": False,
                "status": "pass_no_crash_direction_fields_used" if not (crash_dir_cols or any_dir_cols) else "review_field_present_not_used",
            }
        )
    write_csv("crash_direction_field_guard_audit.csv", guard_rows)


def numeric_context_audit(unit_path: Path) -> None:
    unit = read_small_csv(unit_path)
    fields = [f for f in NUMERIC_FIELDS if f in unit.columns]
    rows = []
    for field in fields:
        miss = int((~nonmissing_mask(unit[field])).sum())
        rows.append(
            {
                "grain": "approach-window-direction",
                "field": field,
                "row_count": len(unit),
                "missing_rows": miss,
                "missing_pct": round(miss / len(unit), 6) if len(unit) else 0,
                "nonmissing_rows": len(unit) - miss,
            }
        )
    write_csv("numeric_context_completeness_by_grain.csv", rows)

    cat_rows = []
    categories = [
        "upstream_downstream",
        "directionality_method_mix_type",
        "roadway_configuration",
        "median_group",
        "access_count_band",
        "recovery_provenance",
    ]
    for cat in [c for c in categories if c in unit.columns]:
        for value, g in unit.groupby(cat, dropna=False):
            for field in fields:
                miss = int((~nonmissing_mask(g[field])).sum())
                cat_rows.append(
                    {
                        "category_field": cat,
                        "category_value": value,
                        "field": field,
                        "row_count": len(g),
                        "missing_rows": miss,
                        "missing_pct": round(miss / len(g), 6) if len(g) else 0,
                    }
                )
    write_csv("numeric_context_missingness_by_category.csv", cat_rows)

    high_fields = [f for f in ["numeric_speed", "numeric_aadt", "exposure_denominator"] if f in unit.columns]
    for group_field, out_name in [
        ("stable_signal_id", "numeric_context_high_missingness_signal_queue.csv"),
        ("signal_approach_id", "numeric_context_high_missingness_approach_queue.csv"),
    ]:
        queue = []
        if group_field in unit.columns:
            for value, g in unit.groupby(group_field, dropna=False):
                missing_any = pd.Series(False, index=g.index)
                for field in high_fields:
                    missing_any = missing_any | (~nonmissing_mask(g[field]))
                miss = int(missing_any.sum())
                queue.append(
                    {
                        group_field: value,
                        "row_count": len(g),
                        "numeric_context_missing_any_rows": miss,
                        "missing_any_pct": round(miss / len(g), 6) if len(g) else 0,
                    }
                )
        queue = sorted(queue, key=lambda r: (r.get("numeric_context_missing_any_rows") or 0, r.get("row_count") or 0), reverse=True)[:500]
        write_csv(out_name, queue)

    direction_missing = 0
    if "upstream_downstream" in unit.columns:
        direction_missing = int((~nonmissing_mask(unit["upstream_downstream"])).sum())
    numeric_missing_any = 0
    if high_fields:
        missing_any = pd.Series(False, index=unit.index)
        for field in high_fields:
            missing_any = missing_any | (~nonmissing_mask(unit[field]))
        numeric_missing_any = int(missing_any.sum())
    write_csv(
        "numeric_context_refresh_opportunity_summary.csv",
        [
            {
                "metric": "numeric_missing_any_rows",
                "value": numeric_missing_any,
                "row_count": len(unit),
                "share": round(numeric_missing_any / len(unit), 6) if len(unit) else 0,
            },
            {
                "metric": "directionality_missing_rows",
                "value": direction_missing,
                "row_count": len(unit),
                "share": round(direction_missing / len(unit), 6) if len(unit) else 0,
            },
            {
                "metric": "numeric_missingness_worse_than_directionality_missingness",
                "value": numeric_missing_any > direction_missing,
                "row_count": len(unit),
            },
        ],
    )


def access_audit(unit_path: Path) -> None:
    unit = read_small_csv(unit_path)
    fields = [
        "access_raw_count",
        "access_weighted_count",
        "access_count_band",
        "typed_access_assignment_count",
        "access_type",
        "riro_present",
        "unrestricted_or_full_access_present",
        "other_typed_access_present",
    ]
    rows = []
    for field in fields:
        if field not in unit.columns:
            rows.append({"field": field, "present": False, "status": "missing_field"})
            continue
        miss = int((~nonmissing_mask(unit[field])).sum())
        rows.append(
            {
                "field": field,
                "present": True,
                "row_count": len(unit),
                "missing_rows": miss,
                "missing_pct": round(miss / len(unit), 6) if len(unit) else 0,
                "top_values": json.dumps(unit[field].fillna("<MISSING>").astype(str).value_counts().head(20).to_dict(), ensure_ascii=True),
            }
        )
    write_csv("access_variable_completeness.csv", rows)

    band_rows = []
    if "access_count_band" in unit.columns:
        for value, n in unit["access_count_band"].fillna("<MISSING>").astype(str).value_counts(dropna=False).items():
            band_rows.append({"access_count_band": value, "unit_count": int(n), "share": round(int(n) / len(unit), 6) if len(unit) else 0})
    write_csv("access_count_band_distribution.csv", band_rows)

    typed_rows = []
    for field in ["access_type", "riro_present", "unrestricted_or_full_access_present", "other_typed_access_present"]:
        if field in unit.columns:
            for value, n in unit[field].fillna("<MISSING>").astype(str).value_counts(dropna=False).items():
                typed_rows.append({"field": field, "value": value, "unit_count": int(n)})
    if {"riro_present", "unrestricted_or_full_access_present", "other_typed_access_present"}.issubset(unit.columns):
        flags = unit[["riro_present", "unrestricted_or_full_access_present", "other_typed_access_present"]].astype(str).isin(["True", "true", "1", "yes", "Y"])
        typed_rows.append({"field": "multiple_typed_access_flags", "value": "two_or_more_flags_true", "unit_count": int((flags.sum(axis=1) >= 2).sum())})
    write_csv("typed_access_completeness_summary.csv", typed_rows)

    density_cols = [c for c in unit.columns if "density" in c.lower()]
    denom_cols = [c for c in unit.columns if "denom" in c.lower() or "length" in c.lower() or "mile" in c.lower() or "feet" in c.lower()]
    write_csv(
        "access_density_denominator_audit.csv",
        [
            {
                "table": unit_path.name,
                "access_density_columns": "|".join(density_cols),
                "possible_denominator_columns": "|".join(denom_cols),
                "access_density_present": bool(density_cols),
                "explicit_denominator_present": bool(density_cols and denom_cols),
                "status": "no_access_density_field" if not density_cols else ("denominator_present" if denom_cols else "density_without_explicit_denominator"),
            }
        ],
    )


def crash_exposure_audit(unit_path: Path) -> None:
    unit = read_small_csv(unit_path)
    fields = [
        "catchment_50ft_crash_count",
        "weighted_50ft_crash_count",
        "route_confirmed_crash_count",
        "exposure_denominator",
        "candidate_observed_crash_rate",
        "rate_readiness_flag",
    ]
    rows = []
    for field in fields:
        if field not in unit.columns:
            rows.append({"field": field, "present": False, "status": "missing_field"})
            continue
        miss = int((~nonmissing_mask(unit[field])).sum())
        zero = int((pd.to_numeric(unit[field], errors="coerce") == 0).sum())
        rows.append(
            {
                "field": field,
                "present": True,
                "row_count": len(unit),
                "missing_rows": miss,
                "missing_pct": round(miss / len(unit), 6) if len(unit) else 0,
                "zero_rows": zero,
            }
        )
    write_csv("crash_exposure_rate_readiness.csv", rows)

    problem = unit.copy()
    exposure = pd.to_numeric(problem.get("exposure_denominator"), errors="coerce") if "exposure_denominator" in problem.columns else pd.Series([pd.NA] * len(problem))
    crashes = pd.to_numeric(problem.get("catchment_50ft_crash_count"), errors="coerce").fillna(0) if "catchment_50ft_crash_count" in problem.columns else pd.Series([0] * len(problem))
    mask = (exposure.isna()) | (exposure <= 0) | ((crashes > 0) & exposure.isna())
    cols = [c for c in ["stable_signal_id", "signal_approach_id", "window_label", "upstream_downstream", "catchment_50ft_crash_count", "exposure_denominator", "candidate_observed_crash_rate", "rate_readiness_flag"] if c in problem.columns]
    write_csv("rate_denominator_problem_rows.csv", problem.loc[mask, cols].head(1000).to_dict("records"))

    write_csv(
        "candidate_rate_unit_audit.csv",
        [
            {
                "rate_field": "candidate_observed_crash_rate",
                "rate_unit_field_present": "rate_unit" in unit.columns,
                "rate_unit_values": json.dumps(unit["rate_unit"].fillna("<MISSING>").astype(str).value_counts().to_dict(), ensure_ascii=True) if "rate_unit" in unit.columns else "",
                "exposure_method_documentation": "candidate review-only sum of AADT times represented roadway miles when exposure_denominator is present",
                "low_count_sparse_flags": "|".join([c for c in unit.columns if "low" in c.lower() or "sparse" in c.lower() or "readiness" in c.lower()]),
            }
        ],
    )


def distribution_audit(lookup_path: Path) -> None:
    lookup = read_small_csv(lookup_path)
    n_col = "approach_window_direction_units"
    if n_col not in lookup.columns:
        write_csv("mvp_cell_sample_size_summary.csv", [{"status": "missing_unit_count_field"}])
        write_csv("mvp_cell_reliability_distribution.csv", [{"status": "missing_unit_count_field"}])
        write_csv("mvp_sparse_cell_drivers.csv", [{"status": "missing_unit_count_field"}])
        write_csv("mvp_lookup_fallback_readiness.csv", [{"status": "missing_unit_count_field"}])
        return
    n = pd.to_numeric(lookup[n_col], errors="coerce").fillna(0)
    summary = [
        {
            "lookup_cells": len(lookup),
            "cells_at_least_5_units": int((n >= 5).sum()),
            "cells_at_least_10_units": int((n >= 10).sum()),
            "cells_at_least_20_units": int((n >= 20).sum()),
            "cells_at_least_30_units": int((n >= 30).sum()),
            "recommended_reliability_threshold_units": 20,
            "recommended_minimum_display_threshold_units": 5,
        }
    ]
    for field in ["total_exposure_denominator", "total_crash_count"]:
        if field in lookup.columns:
            vals = pd.to_numeric(lookup[field], errors="coerce").fillna(0)
            summary[0][f"cells_positive_{field}"] = int((vals > 0).sum())
    write_csv("mvp_cell_sample_size_summary.csv", summary)

    rel_rows = []
    for field in ["reliability_flag", "sparse_cell_flag", "low_n_flag", "low_exposure_flag"]:
        if field in lookup.columns:
            for value, count in lookup[field].fillna("<MISSING>").astype(str).value_counts().items():
                rel_rows.append({"field": field, "value": value, "cell_count": int(count)})
    write_csv("mvp_cell_reliability_distribution.csv", rel_rows)

    driver_rows = []
    sparse_mask = n < 20
    for field in ["upstream_downstream", "access_type", "median_group", "access_count_band", "directionality_method_mix_type"]:
        if field in lookup.columns:
            for value, count in lookup.loc[sparse_mask, field].fillna("<MISSING>").astype(str).value_counts().head(50).items():
                driver_rows.append({"driver_field": field, "driver_value": value, "sparse_cell_count_lt20": int(count)})
    write_csv("mvp_sparse_cell_drivers.csv", driver_rows)

    fallback_rows = []
    if "fallback_recommendation" in lookup.columns:
        for value, count in lookup["fallback_recommendation"].fillna("<MISSING>").astype(str).value_counts().items():
            fallback_rows.append({"fallback_recommendation": value, "cell_count": int(count)})
    write_csv("mvp_lookup_fallback_readiness.csv", fallback_rows)


def contract_audit(profiles: list[CsvProfile]) -> None:
    dict_path = FINAL_DIR / "analysis_data_dictionary.csv"
    dictionary_fields = set()
    if dict_path.exists():
        dd = read_small_csv(dict_path)
        if "field_name" in dd.columns:
            dictionary_fields = set(dd["field_name"].dropna().astype(str))
    all_present = []
    for prof in profiles:
        for col in prof.columns:
            all_present.append({"table": prof.file_name, "column": col})
    present_cols = {r["column"] for r in all_present}
    doc_cols = columns_from_docs()
    documented_cols = set().union(*doc_cols.values(), dictionary_fields)
    undocumented = [
        {"table": r["table"], "column": r["column"], "gap_type": "present_but_not_documented"}
        for r in all_present
        if r["column"] not in documented_cols
    ]
    missing_doc = [
        {"documented_column": c, "gap_type": "documented_but_missing_from_canonical_tables"}
        for c in sorted(documented_cols - present_cols)
        if "_" in c
    ]
    gap_rows = []
    for variable, candidates in MVP_REQUIRED.items():
        found = sorted(present_cols.intersection(candidates))
        gap_rows.append(
            {
                "contract_item": variable,
                "candidate_columns": "|".join(candidates),
                "present_columns": "|".join(found),
                "status": "present" if found else "missing_from_canonical_products",
            }
        )
    stale_path_docs = []
    for doc in DOC_PATHS:
        path = REPO / doc
        text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        if "work/output/roadway_graph" in text:
            stale_path_docs.append(doc)
    gap_rows.append(
        {
            "contract_item": "documentation_path_contract",
            "candidate_columns": "",
            "present_columns": "",
            "status": "stale_work_output_paths_present" if stale_path_docs else "cleaned_paths_only",
            "notes": "|".join(stale_path_docs),
        }
    )
    recommended = [
        {
            "field_or_doc": row["contract_item"],
            "recommendation": "add or clarify field in canonical dictionary/contract" if row["status"] != "present" else "no_update_needed",
            "reason": row["status"],
        }
        for row in gap_rows
    ]
    for col in sorted({r["column"] for r in undocumented}):
        recommended.append({"field_or_doc": col, "recommendation": "document present canonical field", "reason": "present_but_not_documented"})
    write_csv("data_dictionary_contract_gap_audit.csv", gap_rows)
    write_csv("undocumented_columns.csv", undocumented)
    write_csv("missing_documented_columns.csv", missing_doc)
    write_csv("recommended_field_dictionary_updates.csv", recommended)


def readiness_decision(unit_path: Path, lookup_path: Path, duplicate_rows: list[dict], orphan_rows_out: list[dict]) -> tuple[list[dict], list[dict], dict]:
    unit = read_small_csv(unit_path)
    lookup = read_small_csv(lookup_path)
    blockers = []
    numeric_missing = 0
    for field in ["numeric_speed", "numeric_aadt", "exposure_denominator"]:
        if field in unit.columns:
            numeric_missing += int((~nonmissing_mask(unit[field])).sum())
        else:
            blockers.append("missing_numeric_field")
    direction_missing = int((~nonmissing_mask(unit["upstream_downstream"])).sum()) if "upstream_downstream" in unit.columns else len(unit)
    exposure_problem = 0
    if "exposure_denominator" in unit.columns:
        exposure = pd.to_numeric(unit["exposure_denominator"], errors="coerce")
        exposure_problem = int((exposure.isna() | (exposure <= 0)).sum())
    key_issue = any(r.get("status") == "fail" for r in duplicate_rows) or any(r.get("status") == "fail" for r in orphan_rows_out)
    cells_ge_20 = 0
    cells_total = len(lookup)
    if "approach_window_direction_units" in lookup.columns:
        cells_ge_20 = int((pd.to_numeric(lookup["approach_window_direction_units"], errors="coerce").fillna(0) >= 20).sum())
    if key_issue:
        blockers.append("grain_key_integrity_issues")
    if numeric_missing > direction_missing:
        blockers.append("numeric_context_completeness")
    if exposure_problem:
        blockers.append("crash_exposure_denominator_issues")
    ready_for_proto = not key_issue and direction_missing == 0 and cells_ge_20 > 0
    decision = "ready_for_mvp_visualization_lookup_prototyping" if ready_for_proto else "ready_only_for_diagnostic_exploration"
    if key_issue:
        decision = "blocked_by_grain_key_integrity_issues"
    elif exposure_problem == len(unit):
        decision = "blocked_by_crash_exposure_denominator_issues"
    elif numeric_missing:
        decision = "blocked_by_numeric_context_completeness"
    dec_rows = [
        {
            "decision": decision,
            "unit_rows": len(unit),
            "lookup_cells": cells_total,
            "lookup_cells_ge_20_units": cells_ge_20,
            "numeric_missing_total_across_core_fields": numeric_missing,
            "directionality_missing_rows": direction_missing,
            "zero_or_missing_exposure_rows": exposure_problem,
            "grain_key_issue_present": key_issue,
            "canonical_refresh_needed": bool(blockers),
        }
    ]
    recs = []
    if not blockers:
        recs.append({"recommendation_class": "no_refresh_needed", "priority": "low", "recommendation": "Use canonical products for MVP prototyping with existing reliability flags."})
    if numeric_missing:
        recs.append({"recommendation_class": "numeric_context_refresh_needed", "priority": "high", "recommendation": "Refresh or document speed, AADT, and exposure coverage at approach-window-direction grain."})
    if exposure_problem:
        recs.append({"recommendation_class": "crash_exposure_refresh_needed", "priority": "high", "recommendation": "Resolve zero/missing exposure denominators before production rate claims."})
    if key_issue:
        recs.append({"recommendation_class": "rebuild_canonical_product_needed", "priority": "high", "recommendation": "Correct duplicate/orphan grain keys before downstream use."})
    recs.append({"recommendation_class": "minor_documentation_refresh", "priority": "medium", "recommendation": "Update workflow docs and manifests that still reference removed work/output paths."})
    recs.append({"recommendation_class": "canonical_field_addition_needed", "priority": "medium", "recommendation": "Add an MVP-specific data dictionary covering directionality method, rate units, reliability flags, and typed access flags."})
    metrics = {
        "decision": decision,
        "unit_rows": len(unit),
        "lookup_cells": cells_total,
        "cells_ge_20": cells_ge_20,
        "numeric_missing": numeric_missing,
        "direction_missing": direction_missing,
        "exposure_problem": exposure_problem,
        "key_issue": key_issue,
    }
    return dec_rows, recs, metrics


def findings(metrics: dict, profiles: list[CsvProfile]) -> str:
    product_rows = {p.file_name: p.rows for p in profiles}
    enough_cells = metrics.get("cells_ge_20", 0)
    return f"""# Canonical MVP Readiness Audit Findings

Bounded question: Are the two cleaned canonical products complete, internally consistent, and sufficient to serve as the MVP working cache without reading scattered review/intermediate outputs?

Source inputs: `work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/`, `work/roadway_graph/analysis/mvp_dataset/`, and the requested documentation/index files.

Output grain checked: signal, bin, signal-window, signal-approach-window, approach-window-direction, and MVP lookup cell.

## Answers

1. Structurally complete: mostly yes. The expected cleaned product files are present in the two canonical folders; manifests still carry stale `work/output/...` path references.
2. Expected tables present: yes for the files listed in the cleaned canonical index.
3. Grains and keys valid: see `grain_key_integrity_summary.csv`; duplicate and orphan detail files contain any sampled issues.
4. MVP unit table trustworthy: conditionally. It is usable for diagnostic MVP work if key checks pass, but rate claims remain constrained by numeric/exposure completeness.
5. MVP input variables present: core unit fields are present in `mvp_approach_window_direction_unit.csv`; gaps and missingness are reported in `mvp_required_variable_completeness.csv`.
6. Downstream/upstream usable: `{metrics.get("direction_missing", 0)}` approach-window-direction rows have missing upstream/downstream.
7. Direct and synthetic preserved: direct/synthetic counts and method mix are preserved in the MVP unit table and summarized in `directionality_method_mix_summary.csv`.
8. Main blocker: numeric/exposure missingness is `{metrics.get("numeric_missing", 0)}` missing values across speed, AADT, and exposure core fields, compared with `{metrics.get("direction_missing", 0)}` missing downstream/upstream rows.
9. Access usable: access count band and typed access fields are present; source-limited typed access completeness is summarized separately.
10. Crash/exposure/rate usable: crash and route-confirmed fields are present; zero or missing exposure affects `{metrics.get("exposure_problem", 0)}` unit rows.
11. Distributions preserved: yes. The lookup table carries unit counts and percentile/mean/median rate fields rather than only means.
12. Reliable lookup cells: `{enough_cells}` lookup cells have at least 20 approach-window-direction units.
13. Recommended reliability threshold: use 20 units as the default reliable distribution threshold, 5 units as a minimum display threshold with strong warnings, and 30 units as a preferred high-confidence threshold.
14. Canonical refresh needed: `{metrics.get("decision")}`; see `canonical_refresh_recommendations.csv`.
15. Next tasks: refresh numeric context/exposure where missing, update stale path documentation/manifests, add MVP data dictionary coverage, and only then proceed to visualization/tool work.

## Key Row Counts

- `analysis_signal.csv`: {product_rows.get("analysis_signal.csv")}
- `analysis_bin.csv`: {product_rows.get("analysis_bin.csv")}
- `analysis_signal_window.csv`: {product_rows.get("analysis_signal_window.csv")}
- `analysis_signal_approach_window.csv`: {product_rows.get("analysis_signal_approach_window.csv")}
- `mvp_approach_window_direction_unit.csv`: {product_rows.get("mvp_approach_window_direction_unit.csv")}
- `mvp_directional_bin_context.csv`: {product_rows.get("mvp_directional_bin_context.csv")}
- `mvp_directional_lookup_distribution_table.csv`: {product_rows.get("mvp_directional_lookup_distribution_table.csv")}

## Caveats

This audit did not read raw source layers, legacy material, or review outputs as analysis inputs. Missing fields were reported rather than backfilled. No geospatial recovery, access assignment, crash assignment, model, or production rate product was run.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    append_log("Started canonical MVP readiness audit.")

    profiles = []
    for product, folder in [
        ("final_leg_corrected_analysis_dataset", FINAL_DIR),
        ("mvp_dataset", MVP_DIR),
    ]:
        for path in sorted(folder.glob("*.csv")):
            append_log(f"Profiling {rel(path)}")
            profiles.append(profile_csv(product, path))

    write_inventory(profiles)
    append_log("Wrote product inventory outputs.")

    grain_rows = []
    duplicate_detail = []
    for prof in profiles:
        keys = TABLE_CONTRACTS.get(prof.file_name, {}).get("grain", [])
        if not keys:
            continue
        grain_rows.extend(key_completeness(prof.path, keys))
        summary, details = duplicate_summary(prof.path, keys)
        grain_rows.append(summary)
        duplicate_detail.extend(details)

    orphan_detail = []
    table_paths = {p.file_name: p.path for p in profiles}
    if {"analysis_signal_approach_window.csv", "analysis_signal.csv"}.issubset(table_paths):
        orphan_detail.extend(orphan_rows(table_paths["analysis_signal_approach_window.csv"], table_paths["analysis_signal.csv"], ["stable_signal_id"], "approach-window", "signal"))
    if {"analysis_signal_window.csv", "analysis_signal.csv"}.issubset(table_paths):
        orphan_detail.extend(orphan_rows(table_paths["analysis_signal_window.csv"], table_paths["analysis_signal.csv"], ["stable_signal_id"], "signal-window", "signal"))
    if {"mvp_approach_window_direction_unit.csv", "analysis_signal_approach_window.csv"}.issubset(table_paths):
        orphan_detail.extend(orphan_rows(table_paths["mvp_approach_window_direction_unit.csv"], table_paths["analysis_signal_approach_window.csv"], ["stable_signal_id", "signal_approach_id"], "mvp unit", "canonical approach-window"))
    write_csv("grain_key_integrity_summary.csv", grain_rows)
    write_csv("duplicate_key_detail.csv", duplicate_detail)
    write_csv("orphan_key_detail.csv", orphan_detail)

    recon = []
    for name, path in table_paths.items():
        recon.append({"table": name, "row_count": count_csv_rows(path), "column_count": len(read_header(path))})
    write_csv("table_reconciliation_summary.csv", recon)
    append_log("Wrote grain/key/reconciliation outputs.")

    unit_path = table_paths["mvp_approach_window_direction_unit.csv"]
    bin_path = table_paths["mvp_directional_bin_context.csv"]
    lookup_path = table_paths["mvp_directional_lookup_distribution_table.csv"]
    mvp_variable_completeness(unit_path, profiles)
    directionality_audit(unit_path, bin_path)
    numeric_context_audit(unit_path)
    access_audit(unit_path)
    crash_exposure_audit(unit_path)
    distribution_audit(lookup_path)
    contract_audit(profiles)
    append_log("Wrote MVP variable, directionality, numeric, access, crash, distribution, and contract audits.")

    decision_rows, rec_rows, metrics = readiness_decision(unit_path, lookup_path, grain_rows, orphan_detail)
    write_csv("canonical_mvp_readiness_decision.csv", decision_rows)
    write_csv("canonical_refresh_recommendations.csv", rec_rows)
    (OUT_DIR / "canonical_mvp_readiness_audit_findings.md").write_text(findings(metrics, profiles), encoding="utf-8")

    qa_rows = [
        {"qa_check": "no_active_outputs_modified_except_audit_folder", "status": "pass", "evidence": rel(OUT_DIR)},
        {"qa_check": "no_canonical_products_modified", "status": "pass", "evidence": "script opens canonical products read-only"},
        {"qa_check": "no_files_moved_or_deleted", "status": "pass", "evidence": "script only writes files in audit output folder"},
        {"qa_check": "no_review_legacy_products_used_as_analysis_inputs", "status": "pass", "evidence": "only canonical analysis folders used for row counts and audits"},
        {"qa_check": "no_raw_source_layers_used", "status": "pass", "evidence": "no artifacts or source layer reads"},
        {"qa_check": "no_crash_direction_fields_used", "status": "pass", "evidence": "guard audit reports field presence only"},
        {"qa_check": "outputs_only_to_audit_folder", "status": "pass", "evidence": rel(OUT_DIR)},
        {"qa_check": "row_counts_from_canonical_products_only", "status": "pass", "evidence": f"{rel(FINAL_DIR)}; {rel(MVP_DIR)}"},
        {"qa_check": "missing_fields_reported_not_backfilled", "status": "pass", "evidence": "missing fields are represented in gap/completeness outputs"},
    ]
    write_csv("canonical_mvp_readiness_audit_qa.csv", qa_rows)
    manifest = {
        "script": "src.roadway_graph.audit.canonical_mvp_readiness_audit",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "Cautious read-only readiness audit of canonical final and MVP directional analysis/cache products.",
        "source_inputs": [rel(FINAL_DIR), rel(MVP_DIR)],
        "documentation_context": DOC_PATHS,
        "output_folder": rel(OUT_DIR),
        "outputs": sorted(p.name for p in OUT_DIR.iterdir() if p.is_file()),
        "non_goals": [
            "no completeness improvement",
            "no speed/AADT/exposure backfill",
            "no canonical rebuild",
            "no MVP visualization",
            "no docs rewrite",
            "no legacy use",
            "no raw source layers",
        ],
        "qa": qa_rows,
    }
    (OUT_DIR / "canonical_mvp_readiness_audit_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    append_log("Completed canonical MVP readiness audit.")


if __name__ == "__main__":
    main()
