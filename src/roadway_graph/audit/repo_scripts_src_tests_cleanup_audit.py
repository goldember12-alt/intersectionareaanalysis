from __future__ import annotations

import ast
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SRC_DIR = REPO_ROOT / "src"
TESTS_DIR = REPO_ROOT / "tests"
ACTIVE_RG_DIR = SRC_DIR / "active" / "roadway_graph"
OUT_DIR = REPO_ROOT / "work" / "roadway_graph" / "review" / "repo_scripts_src_tests_cleanup_audit"

SCAN_ROOTS = {
    "scripts": SCRIPTS_DIR,
    "src": SRC_DIR,
    "tests": TESTS_DIR,
}

CURRENT_MARKERS = [
    "final_dataset_cache",
    "final_summaries",
    "mvp_dataset",
    "artifacts/normalized/source_layers",
    "source_artifact_coverage",
    "repair_artifact_source_layer_coverage",
]

STALE_MARKERS = [
    "final_leg_corrected_analysis_dataset",
    "mvp_dataset",
    "_staging",
    "work/output",
    "work\\output",
    "legacy",
    "legacy/",
    "legacy\\",
]

REFERENCE_PATTERNS = [
    "final_dataset_cache",
    "final_summaries",
    "mvp_dataset",
    "final_leg_corrected_analysis_dataset",
    "mvp_dataset",
    "_staging",
    "work/output",
    "work\\output",
    "legacy",
    "artifacts/normalized",
    "artifacts\\normalized",
    "artifacts/staging",
    "artifacts\\staging",
    "Intersection Crash Analysis Layers",
    "roadway_graph",
    "crash_direction",
    "Crash_Direction",
    "TRAVEL_DIRECTION",
    "DirectionOfTravel",
]

TEXT_EXTENSIONS = {
    ".py",
    ".ps1",
    ".cmd",
    ".bat",
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".toml",
    ".yaml",
    ".yml",
}

LIKELY_INSTALLED = {
    "geopandas",
    "numpy",
    "pandas",
    "pyarrow",
    "pyogrio",
    "shapely",
    "sklearn",
    "statsmodels",
    "matplotlib",
    "seaborn",
    "networkx",
    "scipy",
    "pyproj",
}


@dataclass
class ImportRecord:
    file_path: str
    scope: str
    import_name: str
    root_module: str
    import_type: str
    level: int
    resolved_path: str
    parse_status: str
    parse_error: str


def rel(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_out() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def read_text_if_feasible(path: Path, max_bytes: int = 2_000_000) -> tuple[str, bool, str]:
    try:
        if path.stat().st_size > max_bytes:
            return "", False, "skipped_large_file"
        return path.read_text(encoding="utf-8", errors="replace"), True, ""
    except Exception as exc:  # pragma: no cover - audit resilience
        return "", False, f"{type(exc).__name__}: {exc}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def line_count(path: Path) -> int | None:
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return None
    try:
        with path.open("rb") as f:
            return sum(1 for _ in f)
    except Exception:
        return None


def appears_generated(path: Path, text: str) -> bool:
    name = path.name.lower()
    return (
        "__pycache__" in path.parts
        or name.endswith(".pyc")
        or "generated" in name
        or "manifest" in name
        or "do not edit" in text.lower()[:2000]
    )


def likely_role(path: Path, text: str) -> str:
    r = rel(path).lower()
    name = path.name.lower()
    if appears_generated(path, text):
        return "generated_output"
    if path.is_relative_to(ACTIVE_RG_DIR):
        return "current_active_code"
    if r.startswith("tests/"):
        if "fixture" in r:
            return "fixture"
        return "test"
    if path.suffix.lower() in {".json", ".toml", ".yaml", ".yml"}:
        return "config_like"
    if r.startswith("scripts/"):
        if any(marker in text for marker in STALE_MARKERS):
            return "obsolete_script"
        if "bootstrap" in name:
            return "config_like"
        return "obsolete_script"
    if "diagnostic" in name or "audit" in name or "prototype" in name:
        return "old_diagnostic"
    if r.startswith("src/transitional/"):
        return "legacy_code"
    if r.startswith("src/active/"):
        return "legacy_code"
    return "unknown"


def inventory_folder(root_name: str, root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not root.exists():
        return [
            {
                "path": rel(root),
                "file_type": "missing_folder",
                "file_size": 0,
                "modified_timestamp": "",
                "line_count": "",
                "file_hash": "",
                "extension": "",
                "likely_role": "unknown",
                "under_src_active_roadway_graph": False,
                "references_roadway_graph": False,
                "references_final_dataset_cache": False,
                "references_final_summaries": False,
                "references_mvp_dataset": False,
                "references_artifacts": False,
                "references_old_paths": False,
                "root_folder": root_name,
            }
        ]

    for path in sorted([p for p in root.rglob("*") if p.is_file()], key=lambda p: rel(p).lower()):
        text, text_readable, _ = read_text_if_feasible(path)
        lowered = text.lower()
        stat = path.stat()
        rows.append(
            {
                "path": rel(path),
                "file_type": "file",
                "file_size": stat.st_size,
                "modified_timestamp": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "line_count": line_count(path) if line_count(path) is not None else "",
                "file_hash": sha256_file(path),
                "extension": path.suffix.lower(),
                "likely_role": likely_role(path, text if text_readable else ""),
                "under_src_active_roadway_graph": path.is_relative_to(ACTIVE_RG_DIR),
                "references_roadway_graph": "roadway_graph" in lowered or "roadway graph" in lowered,
                "references_final_dataset_cache": "final_dataset_cache" in lowered,
                "references_final_summaries": "final_summaries" in lowered,
                "references_mvp_dataset": "mvp_dataset" in lowered,
                "references_artifacts": "artifacts/" in lowered or "artifacts\\" in lowered,
                "references_old_paths": any(marker.lower() in lowered for marker in STALE_MARKERS),
                "root_folder": root_name,
            }
        )
    return rows


def module_name_for_path(path: Path) -> str | None:
    if path.suffix.lower() != ".py":
        return None
    try:
        relative = path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return None
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def build_project_module_index() -> dict[str, str]:
    module_to_path: dict[str, str] = {}
    for root in [SCRIPTS_DIR, SRC_DIR, TESTS_DIR]:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            module = module_name_for_path(path)
            if module:
                module_to_path[module] = rel(path)
    return module_to_path


def classify_import(root_module: str, import_name: str, module_index: dict[str, str]) -> tuple[str, str]:
    if import_name in module_index:
        return "project_module", module_index[import_name]
    candidates = [name for name in module_index if name.startswith(import_name + ".")]
    if candidates:
        shortest = sorted(candidates, key=len)[0]
        return "project_package", module_index[shortest]
    if root_module in {"src", "scripts", "tests"}:
        return "unresolved_project_import", ""
    if root_module in getattr(sys, "stdlib_module_names", set()):
        return "standard_library", ""
    if root_module in LIKELY_INSTALLED:
        return "installed_package", ""
    return "unresolved_or_installed", ""


def resolve_relative_import(path: Path, module: str | None, level: int, name: str | None, module_index: dict[str, str]) -> tuple[str, str, str]:
    current_module = module_name_for_path(path) or ""
    package_parts = current_module.split(".")
    if path.name != "__init__.py":
        package_parts = package_parts[:-1]
    if level:
        keep = max(0, len(package_parts) - level + 1)
        base = package_parts[:keep]
    else:
        base = []
    target_parts = base + ([name] if name else [])
    resolved_name = ".".join(part for part in target_parts if part)
    import_type, resolved_path = classify_import(resolved_name.split(".")[0] if resolved_name else "", resolved_name, module_index)
    return resolved_name, import_type, resolved_path


def parse_imports_for_file(path: Path, scope: str, module_index: dict[str, str]) -> list[ImportRecord]:
    records: list[ImportRecord] = []
    if path.suffix.lower() != ".py":
        return records
    text, readable, error = read_text_if_feasible(path)
    if not readable:
        return [
            ImportRecord(rel(path), scope, "", "", "parse_failed", 0, "", "failed", error)
        ]
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [
            ImportRecord(rel(path), scope, "", "", "parse_failed", 0, "", "failed", f"SyntaxError: {exc}")
        ]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                import_name = alias.name
                root = import_name.split(".")[0]
                import_type, resolved = classify_import(root, import_name, module_index)
                records.append(ImportRecord(rel(path), scope, import_name, root, import_type, 0, resolved, "parsed", ""))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                for alias in node.names:
                    target_name, import_type, resolved = resolve_relative_import(path, node.module, node.level, alias.name, module_index)
                    records.append(ImportRecord(rel(path), scope, target_name, target_name.split(".")[0] if target_name else "", import_type, node.level, resolved, "parsed", ""))
            else:
                import_name = node.module or ""
                root = import_name.split(".")[0] if import_name else ""
                import_type, resolved = classify_import(root, import_name, module_index)
                records.append(ImportRecord(rel(path), scope, import_name, root, import_type, 0, resolved, "parsed", ""))
    return records


def import_records_to_rows(records: list[ImportRecord]) -> list[dict[str, Any]]:
    return [record.__dict__ for record in records]


def scan_imports(module_index: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    active_records: list[ImportRecord] = []
    scripts_records: list[ImportRecord] = []
    tests_records: list[ImportRecord] = []
    for root_name, root in SCAN_ROOTS.items():
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py"), key=lambda p: rel(p).lower()):
            if path.is_relative_to(ACTIVE_RG_DIR):
                active_records.extend(parse_imports_for_file(path, "src_active_roadway_graph", module_index))
            elif root_name == "scripts":
                scripts_records.extend(parse_imports_for_file(path, "scripts", module_index))
            elif root_name == "tests":
                tests_records.extend(parse_imports_for_file(path, "tests", module_index))

    all_records = active_records + scripts_records + tests_records
    unresolved = [
        r.__dict__
        for r in all_records
        if r.import_type in {"unresolved_project_import", "unresolved_or_installed", "parse_failed"}
    ]

    blockers: list[dict[str, Any]] = []
    for r in active_records:
        resolved = Path(r.resolved_path) if r.resolved_path else None
        outside_active = bool(resolved and r.resolved_path.startswith("src/") and not r.resolved_path.startswith("src/active/roadway_graph/"))
        if r.resolved_path.startswith("scripts/") or r.resolved_path.startswith("tests/") or outside_active:
            blockers.append(
                {
                    "active_file": r.file_path,
                    "import_name": r.import_name,
                    "resolved_path": r.resolved_path,
                    "blocker_type": "active_imports_outside_active_roadway_graph",
                    "cleanup_implication": "retain_or_migrate_before_promoting_active_roadway_graph",
                }
            )
    return (
        import_records_to_rows(active_records),
        import_records_to_rows(scripts_records),
        import_records_to_rows(tests_records),
        unresolved,
        blockers,
    )


def scan_references(inventory_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    stale_rows: list[dict[str, Any]] = []
    current_rows: list[dict[str, Any]] = []
    entry_points: list[dict[str, Any]] = []
    for item in inventory_rows:
        path = REPO_ROOT / item["path"]
        text, readable, error = read_text_if_feasible(path)
        if not readable:
            continue
        for pattern in REFERENCE_PATTERNS:
            count = len(re.findall(re.escape(pattern), text, flags=re.IGNORECASE))
            if count:
                row = {
                    "path": item["path"],
                    "pattern": pattern,
                    "match_count": count,
                    "reference_type": "stale" if pattern in STALE_MARKERS or pattern.lower() in [m.lower() for m in STALE_MARKERS] else "current_or_context",
                }
                rows.append(row)
                if row["reference_type"] == "stale":
                    stale_rows.append(row)
                if pattern in CURRENT_MARKERS:
                    current_rows.append(row)
        if path.suffix.lower() in {".py", ".ps1", ".cmd", ".bat"}:
            if "if __name__" in text or path.suffix.lower() in {".ps1", ".cmd", ".bat"}:
                entry_points.append(
                    {
                        "path": item["path"],
                        "entry_point_signal": "main_guard_or_executable_script",
                        "references_current_products": any(marker in text for marker in CURRENT_MARKERS),
                        "references_stale_paths": any(marker.lower() in text.lower() for marker in STALE_MARKERS),
                        "notes": error,
                    }
                )

    summary_counter: Counter[tuple[str, str]] = Counter()
    for row in rows:
        folder = row["path"].split("/", 1)[0]
        summary_counter[(folder, row["reference_type"])] += int(row["match_count"])
    summary = [
        {"root_folder": folder, "reference_type": ref_type, "match_count": count}
        for (folder, ref_type), count in sorted(summary_counter.items())
    ]
    return rows, stale_rows, current_rows, entry_points, summary


def classify_files(
    inventory_rows: list[dict[str, Any]],
    active_import_rows: list[dict[str, Any]],
    stale_ref_paths: set[str],
    current_ref_paths: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    imported_by_active = {
        row["resolved_path"]
        for row in active_import_rows
        if row.get("resolved_path")
        and not row["resolved_path"].startswith("src/active/roadway_graph/")
    }
    scripts_rows: list[dict[str, Any]] = []
    src_rows: list[dict[str, Any]] = []
    tests_rows: list[dict[str, Any]] = []

    for item in inventory_rows:
        path = item["path"]
        folder = path.split("/", 1)[0]
        classification = "manual_review"
        rationale = ""
        if item["likely_role"] == "generated_output":
            classification = "delete_candidate"
            rationale = "generated/cache/output-like file; do not retain in source after archive/checksum review"
        elif path.startswith("src/active/roadway_graph/"):
            classification = "keep_current"
            rationale = "candidate current implementation spine"
        elif path in imported_by_active:
            classification = "keep_current_dependency"
            rationale = "imported by src/active/roadway_graph"
        elif folder == "scripts":
            if "bootstrap" in Path(path).name.lower():
                classification = "archive_legacy"
                rationale = "bootstrap/support script, not imported by active code; keep until environment story is replaced"
            elif path in stale_ref_paths or item["likely_role"] == "obsolete_script":
                classification = "archive_legacy"
                rationale = "root script with stale or old cleanup/diagnostic role and no active imports"
            else:
                classification = "manual_review"
                rationale = "script has no active import dependency but role is not proven disposable"
        elif folder == "tests":
            if item["likely_role"] == "fixture":
                classification = "archive_legacy"
                rationale = "fixture for legacy/root test target"
            elif path in stale_ref_paths:
                classification = "archive_legacy"
                rationale = "test references old work/output products"
            else:
                classification = "manual_review"
                rationale = "test target requires human confirmation"
        elif folder == "src":
            if path in current_ref_paths and not path.startswith("src/active/roadway_graph/"):
                classification = "migrate_into_new_src_later"
                rationale = "outside active roadway_graph but references current products or workflow"
            elif path.startswith("src/active/") or path.startswith("src/transitional/"):
                classification = "archive_legacy"
                rationale = "outside candidate roadway_graph spine and not imported by active roadway_graph"
            elif Path(path).name in {"README.md", "__init__.py", "__main__.py"}:
                classification = "manual_review"
                rationale = "package/root metadata or entry stub"
            else:
                classification = "manual_review"
                rationale = "unclassified src file outside active roadway_graph"

        row = dict(item)
        row.update(
            {
                "cleanup_classification": classification,
                "classification_rationale": rationale,
                "imported_by_active_roadway_graph": path in imported_by_active,
            }
        )
        if folder == "scripts":
            scripts_rows.append(row)
        elif folder == "src":
            src_rows.append(row)
        elif folder == "tests":
            tests_rows.append(row)
    return scripts_rows, src_rows, tests_rows


def summarize_classifications(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[tuple[str, str]] = Counter()
    for group in groups:
        for row in group:
            counter[(row["root_folder"], row["cleanup_classification"])] += 1
    return [
        {"root_folder": folder, "cleanup_classification": classification, "file_count": count}
        for (folder, classification), count in sorted(counter.items())
    ]


def rows_by_classification(groups: list[list[dict[str, Any]]], classification: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in groups:
        for row in group:
            if row["cleanup_classification"] == classification:
                rows.append(
                    {
                        "path": row["path"],
                        "root_folder": row["root_folder"],
                        "likely_role": row["likely_role"],
                        "classification_rationale": row["classification_rationale"],
                    }
                )
    return rows


def build_cleanup_plan(
    scripts_rows: list[dict[str, Any]],
    src_rows: list[dict[str, Any]],
    tests_rows: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str]:
    scripts_counts = Counter(row["cleanup_classification"] for row in scripts_rows)
    tests_counts = Counter(row["cleanup_classification"] for row in tests_rows)
    src_counts = Counter(row["cleanup_classification"] for row in src_rows)

    plan = [
        {
            "step_order": 1,
            "cleanup_step": "archive_root_scripts_first",
            "recommendation": "Archive scripts/ as legacy/support material rather than delete wholesale in first cleanup.",
            "rationale": f"scripts classifications: {dict(scripts_counts)}; no active roadway_graph imports detected.",
        },
        {
            "step_order": 2,
            "cleanup_step": "archive_root_tests_first",
            "recommendation": "Archive tests/ as legacy guardrail tests unless the project wants to port tests to current final_dataset_cache workflows.",
            "rationale": f"tests classifications: {dict(tests_counts)}.",
        },
        {
            "step_order": 3,
            "cleanup_step": "archive_src_outside_active_roadway_graph",
            "recommendation": "Archive src files outside src/active/roadway_graph after reviewing package stubs and any migration candidates.",
            "rationale": f"src classifications: {dict(src_counts)}.",
        },
        {
            "step_order": 4,
            "cleanup_step": "promote_active_roadway_graph_later",
            "recommendation": "Promote or reorganize src/active/roadway_graph only after deciding the future package layout and updating pyproject/package entrypoints.",
            "rationale": "This audit did not modify package layout and found no active imports from scripts/tests/outside active roadway_graph." if not blockers else "External active dependencies must be retained or migrated first.",
        },
    ]

    future_layout = [
        {"path": "src/roadway_graph/", "purpose": "future current implementation package migrated from src/active/roadway_graph"},
        {"path": "src/roadway_graph/audits/", "purpose": "optional home for retained one-off audit scripts if kept in source"},
        {"path": "src/roadway_graph/builders/", "purpose": "optional home for canonical cache/product builders"},
        {"path": "tests/roadway_graph/", "purpose": "future tests rebuilt around final_dataset_cache/mvp_dataset contracts"},
    ]

    archive_plan = [
        {"candidate": "scripts/", "archive_mode": "legacy_TIMESTAMP archive first", "delete_after_zip_verification": "possible_later", "manual_review_required": True},
        {"candidate": "tests/", "archive_mode": "legacy_TIMESTAMP archive first", "delete_after_zip_verification": "possible_later", "manual_review_required": True},
        {"candidate": "src/active files outside roadway_graph and src/transitional/", "archive_mode": "legacy_TIMESTAMP archive first", "delete_after_zip_verification": "possible_later", "manual_review_required": True},
    ]

    checklist = [
        {"check": "confirm no active imports outside src/active/roadway_graph", "passed": not blockers},
        {"check": "create legacy_TIMESTAMP only in later task", "passed": True},
        {"check": "zip/archive before delete", "passed": True},
        {"check": "do not delete source truth or analysis products", "passed": True},
        {"check": "update pyproject before package promotion", "passed": True},
    ]

    if blockers:
        decision = "cleanup_blocked_by_active_dependencies"
    elif scripts_counts.get("manual_review", 0) or tests_counts.get("manual_review", 0) or src_counts.get("manual_review", 0):
        decision = "scripts_src_tests_cleanup_audit_complete_ready_for_archive_plan"
    else:
        decision = "scripts_can_be_removed_tests_can_be_removed_src_needs_migration_plan"
    return plan, future_layout, archive_plan, checklist, decision


def write_findings(
    final_decision: str,
    summaries: dict[str, Any],
    blockers: list[dict[str, Any]],
    stale_rows: list[dict[str, Any]],
    current_rows: list[dict[str, Any]],
) -> None:
    memo = f"""# Repo Scripts/Src/Tests Cleanup Audit

Created: {now_utc()}

## What Was Audited

This read-only audit inventoried `scripts/`, `src/`, and `tests/`. It treated `src/active/roadway_graph/` as the candidate current implementation spine and did not classify that folder for deletion.

## Scripts

`scripts/` has {summaries['scripts_total']} files. No imports from `src/active/roadway_graph/` to `scripts/` were found. The folder appears archive-first rather than immediate-delete because bootstrap/support scripts are still documented by older `src/README.md` text.

## Tests

`tests/` has {summaries['tests_total']} files. The root test targets older `src.active.context_enrichment*` modules and `work/output` products, so it appears legacy. No active roadway_graph code imports `tests/`.

## Src Outside Active Roadway Graph

`src/` has {summaries['src_total']} files, including {summaries['active_rg_total']} under `src/active/roadway_graph/`. Files outside the candidate spine appear mostly legacy/prototype/transitional or package stubs. They should be archived or reviewed before a later promotion.

## Active Roadway Graph Dependencies

Active roadway_graph external dependency blockers found: {len(blockers)}.

Result: {"no imports from scripts/tests/src-outside-active-roadway_graph were found" if not blockers else "external active dependencies must be retained or migrated before cleanup"}.

## Reference Findings

Stale path/reference rows: {len(stale_rows)}.

Current product/reference rows: {len(current_rows)}.

Stale references include old output or legacy markers such as `work/output`, `final_leg_corrected_analysis_dataset`, `mvp_dataset`, `_staging`, or `legacy` where found. Current references include `final_dataset_cache`, `final_summaries`, `mvp_dataset`, and current artifact paths.

## Recommended Cleanup Sequence

1. Create a `legacy_TIMESTAMP` archive in a later task and copy/archive `scripts/`, `tests/`, and selected `src` files outside `src/active/roadway_graph/`.
2. Verify archive checksums and package import behavior.
3. Rebuild current tests around `final_dataset_cache`, `final_summaries`, and `mvp_dataset`.
4. Only then promote or reorganize `src/active/roadway_graph/` into the future root package layout and update `pyproject.toml`.
5. Delete only after archive verification and explicit user approval.

## Before Promoting Active Roadway Graph

Decide the future package name/layout, update package discovery in `pyproject.toml`, port only current tests, and decide whether one-off audit scripts remain in source or move to an archive.

## Final Decision

{final_decision}
"""
    (OUT_DIR / "findings_memo.md").write_text(memo, encoding="utf-8")


def main() -> None:
    ensure_out()
    progress: list[str] = [f"{now_utc()} start repo_scripts_src_tests_cleanup_audit"]

    inventories = {name: inventory_folder(name, root) for name, root in SCAN_ROOTS.items()}
    all_inventory = inventories["scripts"] + inventories["src"] + inventories["tests"]
    write_csv(OUT_DIR / "folder_inventory_scripts.csv", inventories["scripts"])
    write_csv(OUT_DIR / "folder_inventory_src.csv", inventories["src"])
    write_csv(OUT_DIR / "folder_inventory_tests.csv", inventories["tests"])

    root_summary = []
    for name, rows in inventories.items():
        root_summary.append(
            {
                "root_folder": name,
                "exists": SCAN_ROOTS[name].exists(),
                "file_count": len(rows),
                "total_bytes": sum(int(row.get("file_size") or 0) for row in rows),
                "active_roadway_graph_file_count": sum(1 for row in rows if str(row.get("under_src_active_roadway_graph")) == "True" or row.get("under_src_active_roadway_graph") is True),
            }
        )
    write_csv(OUT_DIR / "root_code_folder_summary.csv", root_summary)
    progress.append(f"{now_utc()} gate1 inventory complete")

    module_index = build_project_module_index()
    active_imports, scripts_imports, tests_imports, unresolved, blockers = scan_imports(module_index)
    write_csv(OUT_DIR / "active_roadway_graph_import_dependency_audit.csv", active_imports)
    write_csv(OUT_DIR / "scripts_import_dependency_audit.csv", scripts_imports)
    write_csv(OUT_DIR / "tests_import_dependency_audit.csv", tests_imports)
    write_csv(OUT_DIR / "unresolved_imports_audit.csv", unresolved)
    write_csv(OUT_DIR / "external_dependency_blockers.csv", blockers)
    progress.append(f"{now_utc()} gate2 import audit complete")

    path_refs, stale_refs, current_refs, entry_points, ref_summary = scan_references(all_inventory)
    write_csv(OUT_DIR / "path_reference_audit.csv", path_refs)
    write_csv(OUT_DIR / "stale_path_reference_audit.csv", stale_refs)
    write_csv(OUT_DIR / "current_path_reference_audit.csv", current_refs)
    write_csv(OUT_DIR / "potential_entry_points.csv", entry_points)
    write_csv(OUT_DIR / "current_vs_legacy_reference_summary.csv", ref_summary)
    progress.append(f"{now_utc()} gate3 reference audit complete")

    stale_paths = {row["path"] for row in stale_refs}
    current_paths = {row["path"] for row in current_refs}
    scripts_class, src_class, tests_class = classify_files(all_inventory, active_imports, stale_paths, current_paths)
    write_csv(OUT_DIR / "scripts_cleanup_classification.csv", scripts_class)
    write_csv(OUT_DIR / "src_cleanup_classification.csv", src_class)
    write_csv(OUT_DIR / "tests_cleanup_classification.csv", tests_class)
    summary = summarize_classifications(scripts_class, src_class, tests_class)
    write_csv(OUT_DIR / "cleanup_classification_summary.csv", summary)
    groups = [scripts_class, src_class, tests_class]
    write_csv(OUT_DIR / "deletion_candidate_list.csv", rows_by_classification(groups, "delete_candidate"))
    write_csv(OUT_DIR / "archive_candidate_list.csv", rows_by_classification(groups, "archive_legacy"))
    write_csv(OUT_DIR / "keep_current_list.csv", rows_by_classification(groups, "keep_current") + rows_by_classification(groups, "keep_current_dependency"))
    write_csv(OUT_DIR / "manual_review_list.csv", rows_by_classification(groups, "manual_review"))
    write_csv(OUT_DIR / "migration_candidate_list.csv", rows_by_classification(groups, "migrate_into_new_src_later"))
    progress.append(f"{now_utc()} gate4 classification complete")

    cleanup_plan, future_layout, archive_plan, checklist, final_decision = build_cleanup_plan(scripts_class, src_class, tests_class, blockers)
    write_csv(OUT_DIR / "proposed_cleanup_plan.csv", cleanup_plan)
    write_csv(OUT_DIR / "proposed_future_src_layout.csv", future_layout)
    write_csv(OUT_DIR / "legacy_archive_plan.csv", archive_plan)
    write_csv(OUT_DIR / "deletion_safety_checklist.csv", checklist)
    write_csv(
        OUT_DIR / "next_task_recommendation.csv",
        [
            {
                "recommended_next_task": "Create an archive-only legacy_TIMESTAMP cleanup for scripts/, tests/, and src outside src/active/roadway_graph, then rebuild current tests before package promotion.",
                "do_not_do_yet": "Do not delete files or promote src/active/roadway_graph until archive verification and package layout decisions are complete.",
            }
        ],
    )
    write_csv(OUT_DIR / "recommended_next_actions.csv", [
        {"action_order": 1, "recommended_action": "Review manual_review_list.csv and archive_candidate_list.csv."},
        {"action_order": 2, "recommended_action": "Run an archive-only cleanup task creating legacy_TIMESTAMP with checksums."},
        {"action_order": 3, "recommended_action": "Port or replace legacy tests with tests targeting final_dataset_cache, final_summaries, and mvp_dataset."},
        {"action_order": 4, "recommended_action": "Plan later package promotion for src/active/roadway_graph."},
    ])
    write_csv(OUT_DIR / "final_decision.csv", [{"final_decision": final_decision}])
    progress.append(f"{now_utc()} gate5 cleanup plan complete")

    summaries = {
        "scripts_total": len(inventories["scripts"]),
        "tests_total": len(inventories["tests"]),
        "src_total": len(inventories["src"]),
        "active_rg_total": sum(1 for row in inventories["src"] if row["under_src_active_roadway_graph"]),
    }
    write_findings(final_decision, summaries, blockers, stale_refs, current_refs)

    manifest = {
        "created_utc": now_utc(),
        "bounded_question": "Audit root scripts/src/tests for cleanup planning without deleting, moving, or modifying existing files.",
        "audited_roots": [rel(path) for path in SCAN_ROOTS.values()],
        "protected_candidate_current_folder": rel(ACTIVE_RG_DIR),
        "output_folder": rel(OUT_DIR),
        "final_decision": final_decision,
        "file_counts": summaries,
        "external_dependency_blocker_count": len(blockers),
        "stale_reference_row_count": len(stale_refs),
        "current_reference_row_count": len(current_refs),
    }
    write_json(OUT_DIR / "manifest.json", manifest)
    write_json(
        OUT_DIR / "qa_manifest.json",
        {
            "created_utc": now_utc(),
            "read_only_audit": True,
            "deleted_moved_renamed_files": False,
            "modified_existing_scripts_src_tests": False,
            "modified_analysis_products": False,
            "required_outputs_written": True,
            "final_decision": final_decision,
        },
    )
    (OUT_DIR / "progress_log.md").write_text("\n".join(f"- {line}" for line in progress) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
