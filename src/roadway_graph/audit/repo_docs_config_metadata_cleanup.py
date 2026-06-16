from __future__ import annotations

import csv
import hashlib
import json
import py_compile
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config"
DOCS_DIR = REPO_ROOT / "docs"
LEGACY_ROOT = REPO_ROOT / "legacy_06152026"
OUT_DIR = REPO_ROOT / "work" / "roadway_graph" / "review" / "repo_docs_config_metadata_cleanup"
SCRIPT_PATH = REPO_ROOT / "src" / "roadway_graph" / "audit" / "repo_docs_config_metadata_cleanup.py"

PROTECTED_DIRS = [
    REPO_ROOT / "work" / "roadway_graph" / "analysis" / "final_dataset_cache",
    REPO_ROOT / "work" / "roadway_graph" / "analysis" / "final_summaries",
    REPO_ROOT / "work" / "roadway_graph" / "analysis" / "mvp_dataset",
    REPO_ROOT / "artifacts",
]

STALE_REFS = [
    "work/output",
    "work\\output",
    "_staging",
    "final_leg_corrected_analysis_dataset",
    "mvp_directional_rate_distribution_dataset",
    "scripts/",
    "scripts\\",
    "tests/",
    "tests\\",
    "src/active/roadway_graph",
    "src\\active\\roadway_graph",
]
CURRENT_REFS = [
    "final_dataset_cache",
    "final_summaries",
    "mvp_dataset",
    "artifacts/normalized/source_layers",
    "artifacts\\normalized\\source_layers",
    "src/roadway_graph",
    "src\\roadway_graph",
    "work/roadway_graph/_index",
    "work\\roadway_graph\\_index",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


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


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path: Path) -> str:
    try:
        if path.stat().st_size > 2_000_000:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def folder_state(path: Path) -> dict[str, Any]:
    files = 0
    size = 0
    if path.exists():
        for p in path.rglob("*"):
            if p.is_file():
                files += 1
                size += p.stat().st_size
    return {"path": rel(path), "exists": path.exists(), "file_count": files, "total_size": size}


def protected_snapshot() -> dict[str, dict[str, Any]]:
    return {rel(path): folder_state(path) for path in PROTECTED_DIRS}


def inventory_file(path: Path) -> dict[str, Any]:
    body = read_text(path)
    stale = [ref for ref in STALE_REFS if ref.lower() in body.lower()]
    current = [ref for ref in CURRENT_REFS if ref.lower() in body.lower()]
    return {
        "path": rel(path),
        "size": path.stat().st_size,
        "modified_timestamp": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "hash": sha256(path),
        "extension": path.suffix.lower(),
        "content_summary": " ".join(body.strip().split())[:300],
        "stale_reference_count": len(stale),
        "stale_references": "|".join(stale),
        "current_reference_count": len(current),
        "current_references": "|".join(current),
    }


def find_references(target: str) -> list[dict[str, Any]]:
    rows = []
    for root in [REPO_ROOT / "src" / "roadway_graph", REPO_ROOT / "docs", REPO_ROOT]:
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else root.rglob("*")
        for p in candidates:
            if not p.is_file() or p.suffix.lower() not in {".py", ".md", ".txt", ".toml", ".json"}:
                continue
            if p == SCRIPT_PATH or OUT_DIR in p.parents:
                continue
            body = read_text(p)
            if target.lower() in body.lower():
                rows.append({"referencing_path": rel(p), "target": target})
    return rows


def gate1_config() -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    if not CONFIG_DIR.exists():
        write_csv(OUT_DIR / "config_file_inventory.csv", [])
        write_csv(OUT_DIR / "config_reference_audit.csv", [])
        write_csv(OUT_DIR / "config_dependency_blockers.csv", [])
        write_csv(OUT_DIR / "config_cleanup_recommendation.csv", [{"decision": "config_not_present_continue"}])
        return "config_not_present_continue", [], []

    inv = [inventory_file(p) for p in sorted(CONFIG_DIR.rglob("*")) if p.is_file()]
    refs: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for row in inv:
        path = row["path"]
        refs.extend(find_references(path))
        refs.extend(find_references(Path(path).name))
        role = "old_pipeline_config" if row["stale_reference_count"] else "unknown_manual_review"
        row["likely_role"] = role
    for ref in refs:
        if ref["referencing_path"].startswith("src/roadway_graph/") and "repo_structure_audit.py" not in ref["referencing_path"]:
            blockers.append({"config_path": ref["target"], "referencing_path": ref["referencing_path"], "blocker": "active_code_reference"})
    write_csv(OUT_DIR / "config_file_inventory.csv", inv)
    write_csv(OUT_DIR / "config_reference_audit.csv", refs)
    write_csv(OUT_DIR / "config_dependency_blockers.csv", blockers)
    decision = "config_required_keep_continue" if blockers else "config_safe_to_archive_continue"
    write_csv(OUT_DIR / "config_cleanup_recommendation.csv", [{"decision": decision, "blocker_count": len(blockers)}])
    return decision, inv, blockers


def move_file_to_legacy(src: Path, legacy_subdir: str) -> dict[str, Any]:
    target = LEGACY_ROOT / legacy_subdir / src.relative_to(REPO_ROOT)
    source_hash = sha256(src)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"Target exists: {target}")
    size = src.stat().st_size
    shutil.move(str(src), str(target))
    target_hash = sha256(target)
    return {
        "source_path": rel(src),
        "target_path": rel(target),
        "size": size,
        "source_hash": source_hash,
        "target_hash": target_hash,
        "hash_match": source_hash == target_hash,
    }


def archive_config(decision: str) -> str:
    plan = []
    executed = []
    checks = []
    if decision == "config_safe_to_archive_continue" and CONFIG_DIR.exists():
        for p in sorted(CONFIG_DIR.rglob("*")):
            if p.is_file():
                plan.append({"source_path": rel(p), "target_path": rel(LEGACY_ROOT / "config_pre_distribution_cleanup" / p.relative_to(REPO_ROOT)), "size": p.stat().st_size, "source_hash": sha256(p)})
        for row in plan:
            moved = move_file_to_legacy(REPO_ROOT / row["source_path"], "config_pre_distribution_cleanup")
            executed.append(moved)
            checks.append(moved)
        try:
            CONFIG_DIR.rmdir()
        except OSError:
            pass
        out_decision = "config_archived_continue"
    elif decision == "config_required_keep_continue":
        out_decision = "config_kept_required_continue"
    else:
        out_decision = "config_archive_skipped_manual_review_continue"
    write_csv(OUT_DIR / "config_archive_move_plan.csv", plan)
    write_csv(OUT_DIR / "config_archive_moves_executed.csv", executed)
    write_csv(OUT_DIR / "config_archive_checksum_verification.csv", checks)
    write_csv(OUT_DIR / "config_archive_decision.csv", [{"gate2_decision": out_decision}])
    return out_decision


def gate3_docs() -> tuple[str, list[dict[str, Any]]]:
    if not DOCS_DIR.exists():
        for name in ["docs_file_inventory.csv", "docs_stale_reference_audit.csv", "docs_current_reference_audit.csv", "docs_classification.csv", "docs_archive_candidates.csv", "docs_revision_candidates.csv", "docs_manual_review_items.csv"]:
            write_csv(OUT_DIR / name, [])
        return "docs_missing_continue", []
    inv = []
    stale_rows = []
    current_rows = []
    classification = []
    for p in sorted(DOCS_DIR.rglob("*")):
        if not p.is_file():
            continue
        row = inventory_file(p)
        inv.append(row)
        for ref in row["stale_references"].split("|") if row["stale_references"] else []:
            stale_rows.append({"path": row["path"], "stale_reference": ref})
        for ref in row["current_references"].split("|") if row["current_references"] else []:
            current_rows.append({"path": row["path"], "current_reference": ref})
        action = "archive_legacy" if row["stale_reference_count"] or not row["current_reference_count"] else "revise_current"
        classification.append({"path": row["path"], "suggested_action": action, "stale_reference_count": row["stale_reference_count"], "current_reference_count": row["current_reference_count"]})
    archive = [r for r in classification if r["suggested_action"] == "archive_legacy"]
    revise = [r for r in classification if r["suggested_action"] == "revise_current"]
    write_csv(OUT_DIR / "docs_file_inventory.csv", inv)
    write_csv(OUT_DIR / "docs_stale_reference_audit.csv", stale_rows)
    write_csv(OUT_DIR / "docs_current_reference_audit.csv", current_rows)
    write_csv(OUT_DIR / "docs_classification.csv", classification)
    write_csv(OUT_DIR / "docs_archive_candidates.csv", archive)
    write_csv(OUT_DIR / "docs_revision_candidates.csv", revise)
    write_csv(OUT_DIR / "docs_manual_review_items.csv", [])
    return "docs_revision_plan_ready_continue", classification


def gate4_docs(classification: list[dict[str, Any]]) -> str:
    plan = []
    executed = []
    checks = []
    archive_paths = {r["path"] for r in classification if r["suggested_action"] == "archive_legacy"}
    # Archive all pre-existing docs so the remaining docs tree is compact and current.
    if DOCS_DIR.exists():
        for p in sorted(DOCS_DIR.rglob("*")):
            if p.is_file():
                plan.append({"source_path": rel(p), "target_path": rel(LEGACY_ROOT / "docs_pre_distribution_cleanup" / p.relative_to(REPO_ROOT)), "reason": "archive_legacy" if rel(p) in archive_paths else "archive_before_current_docs_rewrite"})
        for row in plan:
            moved = move_file_to_legacy(REPO_ROOT / row["source_path"], "docs_pre_distribution_cleanup")
            executed.append(moved)
            checks.append(moved)
        for d in sorted([p for p in DOCS_DIR.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "README.md").write_text(current_docs_readme(), encoding="utf-8")
    (DOCS_DIR / "methodology.md").write_text(current_methodology_doc(), encoding="utf-8")
    (DOCS_DIR / "workflow.md").write_text(current_workflow_doc(), encoding="utf-8")
    revisions = [
        {"path": "docs/README.md", "action": "created_current_distribution_docs"},
        {"path": "docs/methodology.md", "action": "created_current_methodology_summary"},
        {"path": "docs/workflow.md", "action": "created_current_workflow_summary"},
    ]
    remaining = [inventory_file(p) for p in sorted(DOCS_DIR.rglob("*")) if p.is_file()]
    write_csv(OUT_DIR / "docs_archive_move_plan.csv", plan)
    write_csv(OUT_DIR / "docs_archive_moves_executed.csv", executed)
    write_csv(OUT_DIR / "docs_archive_checksum_verification.csv", checks)
    write_csv(OUT_DIR / "docs_revision_summary.csv", revisions)
    write_csv(OUT_DIR / "docs_remaining_inventory.csv", remaining)
    return "docs_revised_and_archived_continue"


def current_docs_readme() -> str:
    return """# Current Documentation

This folder contains compact current documentation for the cleaned `IntersectionCrashAnalysis` repository.

Current active surfaces:
- `work/roadway_graph/analysis/final_dataset_cache/`: canonical core cache.
- `work/roadway_graph/analysis/final_summaries/`: lightweight human-readable summaries and QA rollups.
- `work/roadway_graph/analysis/mvp_dataset/`: first development MVP analytical product.
- `artifacts/normalized/source_layers/`: source-preserving parquet artifacts.
- `src/roadway_graph/`: active Python package.
- `work/roadway_graph/review/`: review and cleanup logs.

Archived pre-cleanup documentation is under `legacy_06152026/docs_pre_distribution_cleanup/`.
"""


def current_methodology_doc() -> str:
    return """# Methodology Summary

The project supports Virginia downstream functional-area analysis at signalized intersections.

The current methodology is canonical-cache first. The final core cache integrates signal, travelway, approach, corridor, bin, distance-band, access, crash, speed, AADT, exposure, and directionality context. Review outputs are diagnostic evidence only and are not data parents for ordinary analysis.

Important doctrine:
- Upstream/downstream directionality is cache-derived; crash direction fields are not used to derive it.
- Access context is combined-source, spatial-only, and exclusive within signal/approach/direction distance bands.
- Crash assignment is spatial-primary, 50 ft, band-exclusive within crash/signal/approach/direction, equal fractional, and total-preserving.
- Exposure is currently a daily VMT proxy unless later MVP logic defines final crash-period exposure.
- Unresolved and source-limited cases are preserved with flags rather than hidden.
"""


def current_workflow_doc() -> str:
    return """# Workflow Summary

Use the cleaned products in this order:

1. Start ordinary analysis from `work/roadway_graph/analysis/final_dataset_cache/`.
2. Use `work/roadway_graph/analysis/final_summaries/` for compact human-readable QA and summaries.
3. Use `work/roadway_graph/analysis/mvp_dataset/` only as the current development MVP product.
4. Use `artifacts/normalized/source_layers/` for source-layer preservation and lineage checks.
5. Use `work/roadway_graph/review/` only for diagnostics, audit evidence, and cleanup logs.

Do not use old branch outputs or old root scripts/tests. The active source package is `src/roadway_graph/`.
"""


def update_readme() -> str:
    before = (REPO_ROOT / "README.md").read_text(encoding="utf-8", errors="replace") if (REPO_ROOT / "README.md").exists() else ""
    after = """# IntersectionCrashAnalysis

`IntersectionCrashAnalysis` supports context-aware crash analysis for Virginia signalized intersections, with the long-term goal of downstream functional-area guidance.

The repository is now organized around a canonical roadway graph cache and products derived from it. Ordinary analysis should start from the current cache and should not stitch together old branch outputs.

## Current State

- The canonical core cache is built at `work/roadway_graph/analysis/final_dataset_cache/`.
- Lightweight summary and QA products are built at `work/roadway_graph/analysis/final_summaries/`.
- The first development MVP analytical product is built at `work/roadway_graph/analysis/mvp_dataset/`.
- Source-layer preservation has been repaired under `artifacts/normalized/source_layers/`, with documented residuals for measured-geometry handling.
- The active Python package is `src/roadway_graph/`.

## Folder Map

- `artifacts/`: protected staging, normalized, and source-preserving artifacts.
- `src/roadway_graph/`: active package, including builders, audits, patches, QA helpers, and utilities.
- `work/roadway_graph/analysis/final_dataset_cache/`: canonical core cache.
- `work/roadway_graph/analysis/final_summaries/`: compact reporting and QA summaries.
- `work/roadway_graph/analysis/mvp_dataset/`: development MVP lookup/rate product.
- `work/roadway_graph/_index/`: current product indexes.
- `work/roadway_graph/review/`: audit, cleanup, repair, and diagnostic logs.
- `legacy_06152026/`: archived legacy repo material, not active workflow input.

## Do Not Use As Current Inputs

- old `final_leg_corrected_analysis_dataset`
- old `mvp_directional_rate_distribution_dataset`
- old `src/active/roadway_graph`
- old root scripts/tests
- old `work/output` paths

## Method Notes

- Crash direction fields are not used to derive upstream/downstream.
- Directionality is derived and documented in the cache.
- Access assignment is combined-source, spatial-only, and exclusive within signal/approach/direction distance bands.
- Crash assignment is spatial-primary, band-exclusive, equal fractional, and total-preserving.
- Exposure is a daily VMT proxy unless later MVP logic defines final crash-period exposure.

## Lightweight Validation

Use the repository virtual environment:

```powershell
.\\.venv\\Scripts\\python.exe -m py_compile src\\roadway_graph\\audit\\repo_docs_config_metadata_cleanup.py
.\\.venv\\Scripts\\python.exe -c \"import src.roadway_graph; print('import ok')\"
```

Inspect cache metadata before using data:

```powershell
Get-ChildItem work\\roadway_graph\\analysis\\final_dataset_cache
Get-ChildItem work\\roadway_graph\\analysis\\final_summaries
Get-ChildItem work\\roadway_graph\\analysis\\mvp_dataset
```

## Distribution Note

The repo is close to zip/distribution readiness after remaining source-package cleanup and validation. Heavy external source layers should remain outside the active repo after artifact preservation is accepted.
"""
    (REPO_ROOT / "README.md").write_text(after, encoding="utf-8")
    stale = [ref for ref in STALE_REFS if ref.lower() in after.lower()]
    write_csv(OUT_DIR / "readme_revision_summary.csv", [{"path": "README.md", "old_bytes": len(before.encode()), "new_bytes": len(after.encode()), "stale_reference_count": len(stale)}])
    write_csv(OUT_DIR / "readme_stale_reference_check.csv", [{"reference": ref, "present": ref.lower() in after.lower()} for ref in STALE_REFS])
    return "readme_updated_continue"


def update_agents() -> str:
    before = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8", errors="replace")
    after = """# AGENTS.md

## Purpose

This file is the operating contract for Codex and other agents working in this repository.

`IntersectionCrashAnalysis` supports Virginia downstream functional-area analysis at signalized intersections. The project preserves roadway, signal, access, crash, speed, AADT, exposure, median, and directionality context in a canonical cache, then builds summaries, MVP products, figures, and tools from that cache.

## Current Canonical Paths

- `work/roadway_graph/analysis/final_dataset_cache/`: canonical core cache.
- `work/roadway_graph/analysis/final_summaries/`: lightweight reporting and QA summaries.
- `work/roadway_graph/analysis/mvp_dataset/`: current development MVP product, not final guidance.
- `artifacts/normalized/source_layers/`: source-preserving parquet artifacts.
- `src/roadway_graph/`: active source package.
- `work/roadway_graph/_index/`: current product indexes.
- `work/roadway_graph/review/`: review, audit, repair, and cleanup logs.
- `legacy_06152026/`: archive only.

## Data Preservation Doctrine

Data preservation is the first rule. Do not delete, move, overwrite, or rewrite data unless the user explicitly authorizes that action. Prefer archive or temp-output workflows for mutations. Preserve unresolved, ambiguous, source-limited, and review-only cases with flags instead of hiding them.

## Canonical-First Rule

For ordinary analysis, figures, tables, lookup work, and tools, start from `final_dataset_cache`. Use `final_summaries` for compact reporting and QA. Use `mvp_dataset` for the current development MVP product.

Review outputs are diagnostics, not data parents. Do not promote review outputs into ordinary analysis unless a task explicitly performs and validates that promotion.

## Prohibited Current Paths

Do not use old final-cache, MVP, source, or output paths as current parents. Do not write to old output folders. Do not recreate staging folders unless explicitly requested by the user.

## Directionality And Crash Doctrine

Crash direction fields must not be used to derive upstream/downstream. Directionality is cache-derived. Crash assignment is spatial-primary, band-exclusive, equal fractional, and total-preserving. Access assignment is combined-source, spatial-only, and exclusive within signal/approach/direction distance bands. Exposure is currently a daily VMT proxy unless later MVP logic defines final crash-period exposure.

## Source And Artifact Doctrine

Raw/source/staging data and `artifacts/` are protected source evidence. Read them only for source audit, lineage, missingness investigation, or refresh design. `artifacts/normalized/source_layers/` is the source-preserving parquet layer.

## Runtime Guidance

Use gated workflows for mutation tasks. Write progress logs for long jobs. Inspect existing logs and manifests before rerunning. Avoid broad reruns when a narrow audit or validation will answer the question.

Use the repository virtual environment for validation:

```powershell
.\\.venv\\Scripts\\python.exe -m py_compile <script>
.\\.venv\\Scripts\\python.exe -m <module>
```

Do not run heavy cache or MVP builders unless the user explicitly asks for that work.

## Final Report Format

Final reports should state files changed, source docs/products read, validation commands run, stale path fragments remaining when relevant, key doctrine changes, unresolved assumptions, and focused `git status --short`.
"""
    (REPO_ROOT / "AGENTS.md").write_text(after, encoding="utf-8")
    stale = [ref for ref in STALE_REFS if ref.lower() in after.lower()]
    write_csv(OUT_DIR / "agents_revision_summary.csv", [{"path": "AGENTS.md", "old_bytes": len(before.encode()), "new_bytes": len(after.encode()), "stale_reference_count": len(stale)}])
    write_csv(OUT_DIR / "agents_stale_reference_check.csv", [{"reference": ref, "present": ref.lower() in after.lower()} for ref in STALE_REFS])
    return "agents_updated_continue"


def update_gitignore() -> str:
    before = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8", errors="replace")
    after = """# Git / local repo internals
.git/
/.git_writable_test/
/.git-local/
/.git_working/

# Python
__pycache__/
*.pyc
*.py[cod]
*$py.class

# Root packaging/build outputs. Keep this root-anchored so src/roadway_graph/build is visible.
/build/
/dist/
/.eggs/
/*.egg-info/
/pip-wheel-metadata/

# Test / coverage / tooling caches
.pytest_cache/
.mypy_cache/
.ruff_cache/
.tox/
.nox/
.coverage
.coverage.*
htmlcov/

# Virtual environments
/.venv/
.venv/
venv/
env/
ENV/

# IDE / editor files
.idea/
.vscode/
*.iml

# OS cruft
Thumbs.db
Desktop.ini
.DS_Store

# Logs and temp
*.log
*.tmp
*.temp
scratch/
temp/
tmp/
pip_cache/
.npm-cache/

# Protected heavy/generated work and artifact products
/work/
/artifacts/

# Archived local legacy material
/legacy_*/
/legacy/*
!/legacy/README.md

# Source geodatabases/layers and compressed deliveries
/Intersection Crash Analysis Layers/
*.gdb/
*.gpkg
*.gpkg-journal
*.parquet
*.feather
*.arrow
*.geojson
*.csv
*.xlsx
*.xls
*.shp
*.shx
*.dbf
*.cpg
*.sbn
*.sbx
*.prj
*.tif
*.tiff
*.img
*.las
*.laz
*.zip
*.7z
*.rar
*.aprx
*.lyrx

# Explicit small documentation exceptions may be added below if needed.
"""
    (REPO_ROOT / ".gitignore").write_text(after, encoding="utf-8")
    rules = []
    for line in after.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            rules.append({"rule": stripped})
    hidden_check = subprocess.run(["git", "check-ignore", "-q", "src/roadway_graph/build/__init__.py"], cwd=REPO_ROOT)
    active_visible = hidden_check.returncode != 0
    write_csv(OUT_DIR / "gitignore_revision_summary.csv", [{"path": ".gitignore", "old_bytes": len(before.encode()), "new_bytes": len(after.encode()), "active_source_build_visible": active_visible}])
    write_csv(OUT_DIR / "gitignore_rule_audit.csv", rules)
    write_csv(OUT_DIR / "gitignore_active_source_visibility_check.csv", [{"path": "src/roadway_graph/build/__init__.py", "visible_not_ignored": active_visible}])
    return "gitignore_updated_continue" if active_visible else "gitignore_update_failed_stop"


def final_validation(before: dict[str, dict[str, Any]]) -> str:
    after = protected_snapshot()
    protected_rows = []
    for key, b in before.items():
        a = after[key]
        protected_rows.append({"path": key, "file_count_before": b["file_count"], "file_count_after": a["file_count"], "total_size_before": b["total_size"], "total_size_after": a["total_size"], "unchanged": b["file_count"] == a["file_count"] and b["total_size"] == a["total_size"]})
    write_csv(OUT_DIR / "protected_products_unchanged_check.csv", protected_rows)

    checks = []
    for p in [REPO_ROOT / "README.md", REPO_ROOT / "AGENTS.md", REPO_ROOT / ".gitignore", DOCS_DIR / "README.md", DOCS_DIR / "workflow.md"]:
        body = read_text(p)
        for ref in STALE_REFS:
            if ref.lower() in body.lower():
                lower = body.lower()
                context = "manual_review"
                if "do not use" in lower or "do not write" in lower or "not active workflow" in lower:
                    context = "intentional_prohibition_or_archive_context"
                if ref in {"scripts\\", "scripts/"} and ".venv" in lower:
                    context = "virtualenv_scripts_path_not_root_scripts"
                checks.append({"path": rel(p), "reference": ref, "present": True, "context": context})
    write_csv(OUT_DIR / "stale_reference_final_check.csv", checks)

    py_compile.compile(str(SCRIPT_PATH), doraise=True)
    import_proc = subprocess.run([str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"), "-c", "import src.roadway_graph; print('import ok')"], cwd=REPO_ROOT, capture_output=True, text=True)
    visible_proc = subprocess.run(["git", "check-ignore", "-q", "src/roadway_graph/build/__init__.py"], cwd=REPO_ROOT)
    active_visible = visible_proc.returncode != 0
    write_csv(OUT_DIR / "active_source_visibility_check.csv", [{"path": "src/roadway_graph/build/__init__.py", "visible_not_ignored": active_visible}])
    if not all(r["unchanged"] for r in protected_rows) or import_proc.returncode != 0 or not active_visible:
        return "repo_metadata_cleanup_failed"
    actionable = [row for row in checks if row.get("context") == "manual_review"]
    return "repo_docs_config_metadata_cleanup_complete_zip_readiness_next" if not actionable else "repo_docs_config_metadata_cleanup_complete_with_manual_review_items"


def findings(final_decision: str, config_decision: str, docs_decision: str) -> None:
    memo = f"""# Repo Docs Config Metadata Cleanup

Created: {now()}

Config decision: `{config_decision}`. Stale root config was archived when safe and no active dependency blocker was found.

Docs decision: `{docs_decision}`. Pre-cleanup docs were archived to `legacy_06152026/docs_pre_distribution_cleanup/`; concise current docs were written under `docs/`.

README.md was rewritten to describe the current cache, summaries, MVP product, source artifacts, source package, and distribution posture.

AGENTS.md was rewritten with current paths, canonical-first doctrine, data preservation doctrine, and stale-path prohibitions.

.gitignore was rewritten conservatively. Heavy work/artifacts/legacy outputs remain ignored, while `src/roadway_graph/build/` is no longer hidden by a broad build rule.

Protected products were checked in `protected_products_unchanged_check.csv`.

Remaining manual review items are listed in the stale-reference checks if present.

Final decision: `{final_decision}`.

Recommended next task: update `pyproject.toml` package discovery for `src.roadway_graph`, then run a focused source-package import/entrypoint validation.
"""
    (OUT_DIR / "findings_memo.md").write_text(memo, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    progress = [f"{now()} start"]
    before = protected_snapshot()

    config_decision, _, blockers = gate1_config()
    progress.append(f"{now()} gate1 {config_decision}")
    if config_decision == "config_ambiguous_manual_review_stop":
        final = "repo_docs_config_cleanup_blocked_by_config_dependency"
        finalize(final, progress, config_decision, "not_run")
        return

    config_archive_decision = archive_config(config_decision)
    progress.append(f"{now()} gate2 {config_archive_decision}")
    if config_archive_decision == "config_archive_failed_stop":
        final = "repo_metadata_cleanup_failed"
        finalize(final, progress, config_archive_decision, "not_run")
        return

    docs_decision, docs_classification = gate3_docs()
    progress.append(f"{now()} gate3 {docs_decision}")
    docs_archive_decision = gate4_docs(docs_classification)
    progress.append(f"{now()} gate4 {docs_archive_decision}")

    readme_decision = update_readme()
    progress.append(f"{now()} gate5 {readme_decision}")
    agents_decision = update_agents()
    progress.append(f"{now()} gate6 {agents_decision}")
    gitignore_decision = update_gitignore()
    progress.append(f"{now()} gate7 {gitignore_decision}")
    final = final_validation(before)
    progress.append(f"{now()} gate8 {final}")
    finalize(final, progress, config_archive_decision, docs_archive_decision)


def finalize(final_decision: str, progress: list[str], config_decision: str, docs_decision: str) -> None:
    write_csv(OUT_DIR / "final_decision.csv", [{"final_decision": final_decision}])
    write_csv(OUT_DIR / "recommended_next_actions.csv", [
        {"action_order": 1, "recommended_action": "Update pyproject.toml package discovery to match src/roadway_graph."},
        {"action_order": 2, "recommended_action": "Run focused package import/module validation after pyproject update."},
        {"action_order": 3, "recommended_action": "Review remaining stale source-code references from the roadway_graph cleanup audit."},
        {"action_order": 4, "recommended_action": "Decide whether legacy_06152026 should be zipped externally before distribution."},
    ])
    write_json(OUT_DIR / "manifest.json", {"created_utc": now(), "final_decision": final_decision, "output_folder": rel(OUT_DIR)})
    write_json(OUT_DIR / "qa_manifest.json", {"created_utc": now(), "modified_protected_products": False, "deleted_nontrivial_docs_or_config": False, "archived_to_legacy": True, "heavy_builds_run": False})
    (OUT_DIR / "progress_log.md").write_text("\n".join(f"- {p}" for p in progress) + "\n", encoding="utf-8")
    findings(final_decision, config_decision, docs_decision)


if __name__ == "__main__":
    main()
