from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("work/output/roadway_graph")
INDEX_DIR = ROOT / "_index"

RECENT_PREFIXES = (
    "expanded_",
    "review_only_347",
    "review_only_signal",
    "access_v",
    "access_context",
    "access_source",
    "signal_",
    "roadway_graph_data_loss",
    "strict_success",
    "unrepresented_signal",
)

DATE_STAMP = datetime.now().strftime("%Y%m%d")


def _rel(path: Path) -> str:
    return path.as_posix()


def _root_name(path: Path) -> str:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return ""
    parts = rel.parts
    return parts[0] if parts else "."


def _is_history(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return bool(parts & {"history", "archive", "legacy"})


def _is_current(path: Path) -> bool:
    return "current" in {part.lower() for part in path.parts}


def _contains_recent_name(path: Path) -> bool:
    name = path.name.lower()
    return name.startswith(RECENT_PREFIXES) or "expanded_universe" in name or "expanded_candidate" in name


def _classify(path: Path) -> str:
    root = _root_name(path)
    parts = [part.lower() for part in path.relative_to(ROOT).parts] if path != ROOT else []
    name = path.name.lower()
    if root == "_index":
        return "standalone_table_output"
    if root == "map_review":
        return "map_review_package"
    if root == "review":
        if "history" in parts or "archive" in parts:
            return "legacy_or_historical_output"
        if "current" in parts:
            if _contains_recent_name(path):
                return "current_review_diagnostic"
            return "current_review_diagnostic" if len(parts) >= 3 else "unclear_needs_manual_review"
        return "unclear_needs_manual_review"
    if root == "analysis":
        if "history" in parts or "archive" in parts:
            return "legacy_or_historical_output"
        if "current" in parts:
            return "current_analysis_product" if len(parts) >= 3 else "unclear_needs_manual_review"
        return "unclear_needs_manual_review"
    if root == "report":
        if "history" in parts or "archive" in parts:
            return "legacy_or_historical_output"
        if "current_active" in parts:
            return "unclear_needs_manual_review"
        if "current" in parts:
            return "report_generation_source"
        return "unclear_needs_manual_review"
    if root == "runs":
        return "runtime_or_run_log"
    if root == "tables":
        return "standalone_table_output"
    if "history" in parts or "archive" in parts:
        return "legacy_or_historical_output"
    return "unclear_needs_manual_review"


def _proposal(path: Path, classification: str) -> tuple[str, str, str, str, str]:
    root = _root_name(path)
    rel = path.relative_to(ROOT).as_posix() if path != ROOT else "."
    name = path.name
    risk = "low"
    safe = "yes"
    action = "keep"
    dest = rel
    reason = "Already fits the target contract."

    if root == "_index":
        return action, dest, "Inventory/index location.", risk, safe
    if root == "review" and "/history/" in f"/{rel}/":
        action = "move_to_review_archive"
        dest = rel.replace("review/history", f"review/archive/{DATE_STAMP}", 1)
        reason = "Historical review output; target contract uses review/archive/<YYYYMMDD>/."
        risk = "medium"
        safe = "no"
    elif root == "review" and classification == "current_review_diagnostic":
        action = "keep"
        reason = "Current review diagnostic lane."
    elif root == "analysis" and classification == "current_analysis_product":
        action = "keep"
        reason = "Current analysis product lane."
    elif root == "report" and "current_active" in rel:
        action = "manual_review"
        dest = rel.replace("report/current_active", f"report/archive/{DATE_STAMP}/current_active", 1)
        reason = "Confusing report/current_active transition folder; check dependencies before archive/rename."
        risk = "medium"
        safe = "no"
    elif root == "report" and classification == "report_generation_source":
        action = "keep"
        reason = "Report source/intermediate lane; final docs should live under docs/."
    elif root == "runs":
        action = "manual_review"
        dest = rel.replace("runs/history", f"runs/archive/{DATE_STAMP}", 1) if "runs/history" in rel else rel
        reason = "Run metadata is useful but not part of the proposed semantic target contract."
        risk = "medium"
        safe = "no"
    elif root == "tables":
        action = "manual_review"
        dest = rel
        reason = "Shared graph tables are important but need a documented table contract before any reclassification."
        risk = "high"
        safe = "no"
    elif classification == "legacy_or_historical_output":
        action = "archive"
        reason = "Historical output should be under an archive convention after dependency review."
        risk = "medium"
        safe = "no"
    elif classification == "unclear_needs_manual_review":
        action = "manual_review"
        reason = "Directory does not clearly fit a target lane."
        risk = "medium"
        safe = "no"
    elif classification == "map_review_package":
        action = "keep"
        reason = "Future/current map-review package lane."
    else:
        reason = "No migration proposed."
    return action, dest, reason, risk, safe


def _dir_record(path: Path) -> dict[str, str | int]:
    files = [p for p in path.iterdir() if p.is_file()]
    dirs = [p for p in path.iterdir() if p.is_dir()]
    recursive_files = [p for p in path.rglob("*") if p.is_file()]
    sizes = []
    mtimes = []
    ext_counter: Counter[str] = Counter()
    for file in recursive_files:
        try:
            stat = file.stat()
        except OSError:
            continue
        sizes.append(stat.st_size)
        mtimes.append(stat.st_mtime)
        ext_counter[file.suffix.lower() or "<none>"] += 1
    ext_common = "|".join(f"{ext}:{count}" for ext, count in ext_counter.most_common(8))
    names = {file.name.lower() for file in recursive_files}
    exts = set(ext_counter)
    classification = _classify(path)
    action, dest, reason, risk, safe = _proposal(path, classification)
    return {
        "path": _rel(path),
        "relative_path": path.relative_to(ROOT).as_posix() if path != ROOT else ".",
        "parent_root": _root_name(path),
        "file_count_immediate": len(files),
        "subdirectory_count_immediate": len(dirs),
        "file_count_recursive": len(recursive_files),
        "total_size_bytes_recursive": sum(sizes),
        "oldest_modified_time": datetime.fromtimestamp(min(mtimes)).isoformat() if mtimes else "",
        "newest_modified_time": datetime.fromtimestamp(max(mtimes)).isoformat() if mtimes else "",
        "common_file_extensions_recursive": ext_common,
        "contains_manifest": "true" if any("manifest" in name and name.endswith((".json", ".csv", ".md")) for name in names) else "false",
        "contains_json": "true" if ".json" in exts else "false",
        "contains_csv": "true" if ".csv" in exts else "false",
        "contains_geojson": "true" if ".geojson" in exts else "false",
        "contains_gpkg": "true" if ".gpkg" in exts else "false",
        "contains_png": "true" if ".png" in exts else "false",
        "contains_md": "true" if ".md" in exts else "false",
        "contains_qml": "true" if ".qml" in exts else "false",
        "contains_qgz": "true" if ".qgz" in exts else "false",
        "appears_current_or_historical": "historical" if _is_history(path) else ("current" if _is_current(path) else "unclear"),
        "appears_recent_expanded_universe": "true" if _contains_recent_name(path) else "false",
        "recommended_classification": classification,
        "recommended_action": action,
        "recommended_destination": dest,
        "recommendation_reason": reason,
        "risk_level": risk,
        "safe_to_move_automatically_later": safe,
    }


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_readme(root_rows: list[dict[str, object]], all_rows: list[dict[str, object]]) -> None:
    root_summary = "\n".join(
        f"- `{row['relative_path']}/`: {row['recommended_classification']}, {row['file_count_recursive']} files, {row['total_size_bytes_recursive']} bytes"
        for row in root_rows
    )
    current_review = sum(1 for row in all_rows if row["recommended_classification"] == "current_review_diagnostic")
    manual = sum(1 for row in all_rows if row["recommended_action"] == "manual_review")
    archive = sum(1 for row in all_rows if "archive" in str(row["recommended_action"]) or row["recommended_action"] == "archive")
    text = f"""# Roadway Graph Work Output Index

Generated by `src.roadway_graph.work_output_inventory`.

This folder is an index only. It does not contain authoritative analysis outputs and should not be edited as source data.

## Current Roots

{root_summary}

## Where To Look

- Recent expanded-universe work is mostly under `review/current/`.
- Accepted analysis products are under `analysis/current/`.
- Shared graph/scaffold tables are under `tables/current/`, but this lane still needs a formal table contract.
- Report generation intermediates are under `report/current/`; forward-facing docs and final narrative should live under `docs/`.
- Future QGIS packages should use `map_review/current/<review_name>/`.

## Historical Or Unclear Areas

- `review/history/` exists, while the target contract prefers `review/archive/<YYYYMMDD>/`.
- `runs/` contains run metadata but is not yet part of the semantic target contract.
- `report/current_active/` is confusing and needs dependency review before rename/archive.
- `tables/current/` is important shared evidence and should not be moved until producer/consumer dependencies are documented.

## Inventory Counts

- Directories inventoried: {len(all_rows)}
- Current review diagnostics: {current_review}
- Proposed archive/move-to-archive actions: {archive}
- Manual-review actions: {manual}

## Do Not Manually Edit

Do not manually edit generated CSV, Parquet, GeoJSON, GeoPackage, or manifest files under `work/output/roadway_graph/` unless a task explicitly asks for output repair. Prefer changing the producer script and rerunning the bounded command.
"""
    (INDEX_DIR / "README.md").write_text(text, encoding="utf-8")


def main() -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    dirs = [ROOT] + sorted([p for p in ROOT.rglob("*") if p.is_dir() and "_index" not in p.relative_to(ROOT).parts], key=lambda p: p.as_posix())
    rows = [_dir_record(path) for path in dirs]
    root_rows = [row for row in rows if row["relative_path"] in {".", "analysis", "report", "review", "runs", "tables", "map_review"}]
    classifications = [
        {
            "path": row["path"],
            "relative_path": row["relative_path"],
            "parent_root": row["parent_root"],
            "recommended_classification": row["recommended_classification"],
            "appears_current_or_historical": row["appears_current_or_historical"],
            "appears_recent_expanded_universe": row["appears_recent_expanded_universe"],
            "recommendation_reason": row["recommendation_reason"],
        }
        for row in rows
    ]
    migrations = [
        {
            "current_path": row["path"],
            "recommended_destination_path": (ROOT / str(row["recommended_destination"])).as_posix() if row["recommended_destination"] != "." else ROOT.as_posix(),
            "action": row["recommended_action"],
            "reason": row["recommendation_reason"],
            "risk_level": row["risk_level"],
            "safe_to_move_automatically_later": row["safe_to_move_automatically_later"],
            "recommended_classification": row["recommended_classification"],
        }
        for row in rows
    ]
    fields = list(rows[0].keys())
    _write_csv(INDEX_DIR / "output_directory_inventory.csv", rows, fields)
    _write_csv(INDEX_DIR / "output_root_inventory.csv", root_rows, fields)
    _write_csv(INDEX_DIR / "output_recommended_classification.csv", classifications, list(classifications[0].keys()))
    _write_csv(INDEX_DIR / "proposed_migration_manifest.csv", migrations, list(migrations[0].keys()))
    _write_readme(root_rows, rows)


if __name__ == "__main__":
    main()
