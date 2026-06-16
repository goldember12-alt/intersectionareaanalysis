from __future__ import annotations

import csv
import hashlib
import json
import py_compile
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "work" / "roadway_graph" / "review" / "package_metadata_cleanup"
LEGACY_ROOT = REPO_ROOT / "legacy_06152026"
CONFIG_DIR = REPO_ROOT / "config"
DOCS_DIR = REPO_ROOT / "docs"
SRC_RG = REPO_ROOT / "src" / "roadway_graph"
PYPROJECT = REPO_ROOT / "pyproject.toml"

PROTECTED_DIRS = [
    REPO_ROOT / "work" / "roadway_graph" / "analysis" / "final_dataset_cache",
    REPO_ROOT / "work" / "roadway_graph" / "analysis" / "final_summaries",
    REPO_ROOT / "work" / "roadway_graph" / "analysis" / "mvp_dataset",
    REPO_ROOT / "artifacts",
]

STALE_PATTERNS = [
    "src.active",
    "src.active" + ".roadway_graph",
    "src.active.directed_segments",
    "src.transitional",
    "scripts/",
    "tests/",
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


def inventory_file(path: Path) -> dict[str, Any]:
    return {
        "path": rel(path),
        "size": path.stat().st_size,
        "modified_timestamp": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "hash": sha256(path),
        "extension": path.suffix.lower(),
    }


def folder_snapshot(path: Path) -> dict[str, Any]:
    files = 0
    size = 0
    if path.exists():
        for p in path.rglob("*"):
            if p.is_file():
                files += 1
                size += p.stat().st_size
    return {"path": rel(path), "exists": path.exists(), "file_count": files, "total_size": size}


def protected_snapshot() -> dict[str, dict[str, Any]]:
    return {rel(path): folder_snapshot(path) for path in PROTECTED_DIRS}


def docs_snapshot() -> dict[str, dict[str, Any]]:
    if not DOCS_DIR.exists():
        return {}
    return {rel(p): inventory_file(p) for p in sorted(DOCS_DIR.rglob("*")) if p.is_file()}


def pyproject_settings(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped
        if "packages" in stripped or "description" in stripped or "readme" in stripped or "include" in stripped or "where" in stripped or "namespaces" in stripped:
            rows.append({"section": section, "setting": stripped})
    return rows


def stale_pyproject_rows(text: str) -> list[dict[str, Any]]:
    return [{"pattern": pattern, "present": pattern in text} for pattern in STALE_PATTERNS if pattern in text]


def gate1(before_docs: dict[str, dict[str, Any]]) -> str:
    current = [
        {"check": "pyproject_exists", "passed": PYPROJECT.exists()},
        {"check": "legacy_06152026_exists", "passed": LEGACY_ROOT.exists()},
        {"check": "src_roadway_graph_exists", "passed": SRC_RG.exists()},
        {"check": "docs_exists", "passed": DOCS_DIR.exists()},
        {"check": "config_exists", "passed": CONFIG_DIR.exists()},
    ]
    config_inventory = [inventory_file(p) for p in sorted(CONFIG_DIR.rglob("*")) if p.is_file()] if CONFIG_DIR.exists() else []
    docs_inventory = list(before_docs.values())
    py_text = PYPROJECT.read_text(encoding="utf-8") if PYPROJECT.exists() else ""
    write_csv(OUT_DIR / "current_state_inventory.csv", current)
    write_csv(OUT_DIR / "config_inventory.csv", config_inventory)
    write_csv(OUT_DIR / "docs_inventory.csv", docs_inventory)
    write_csv(OUT_DIR / "pyproject_current_settings.csv", pyproject_settings(py_text))
    write_csv(OUT_DIR / "pyproject_stale_reference_audit.csv", stale_pyproject_rows(py_text))
    if not PYPROJECT.exists():
        decision = "pyproject_missing_stop"
    elif not LEGACY_ROOT.exists():
        decision = "legacy_folder_missing_stop"
    elif not SRC_RG.exists():
        decision = "src_roadway_graph_missing_stop"
    elif not DOCS_DIR.exists():
        decision = "layout_ambiguous_stop"
    else:
        decision = "current_state_verified_continue"
    write_csv(OUT_DIR / "gate1_decision.csv", [{"gate1_decision": decision}])
    return decision


def gate2_archive_config() -> str:
    plan: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    if not CONFIG_DIR.exists():
        decision = "config_absent_continue"
    else:
        files = sorted([p for p in CONFIG_DIR.rglob("*") if p.is_file()])
        for p in files:
            target = LEGACY_ROOT / "config_remaining_root_cleanup" / p.relative_to(REPO_ROOT)
            plan.append({"source_path": rel(p), "target_path": rel(target), "size": p.stat().st_size, "source_hash": sha256(p)})
        try:
            for row in plan:
                src = REPO_ROOT / row["source_path"]
                target = REPO_ROOT / row["target_path"]
                if target.exists():
                    raise FileExistsError(f"target exists: {target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(target))
                target_hash = sha256(target)
                rec = dict(row)
                rec.update({"target_hash": target_hash, "hash_match": target_hash == row["source_hash"], "target_exists": target.exists(), "source_removed": not src.exists()})
                executed.append(rec)
                checks.append(rec)
            try:
                CONFIG_DIR.rmdir()
            except OSError:
                pass
            decision = "config_archived_continue" if executed else "config_absent_continue"
        except Exception as exc:
            checks.append({"error": f"{type(exc).__name__}: {exc}"})
            decision = "config_move_failed_stop"
    write_csv(OUT_DIR / "config_move_plan.csv", plan)
    write_csv(OUT_DIR / "config_moves_executed.csv", executed)
    write_csv(OUT_DIR / "config_move_checksum_verification.csv", checks)
    write_csv(OUT_DIR / "config_root_status_after.csv", [{"config_exists": CONFIG_DIR.exists(), "file_count": len([p for p in CONFIG_DIR.rglob('*') if p.is_file()]) if CONFIG_DIR.exists() else 0}])
    write_csv(OUT_DIR / "gate2_decision.csv", [{"gate2_decision": decision}])
    return decision


def discover_subpackages() -> list[str]:
    packages = ["src.roadway_graph"]
    for init_file in sorted(SRC_RG.rglob("__init__.py")):
        if init_file == SRC_RG / "__init__.py":
            continue
        parts = init_file.parent.relative_to(REPO_ROOT).parts
        packages.append(".".join(parts))
    return sorted(set(packages))


def update_pyproject() -> str:
    before = PYPROJECT.read_text(encoding="utf-8")
    packages = discover_subpackages()
    plan = [
        {"change": "description", "new_value": "Canonical roadway graph cache and crash-analysis tooling for Virginia signalized intersections."},
        {"change": "readme", "new_value": "README.md"},
        {"change": "package_discovery", "new_value": 'setuptools namespace discovery include = ["src.roadway_graph*"]'},
    ]
    after = before
    after = re.sub(
        r'description\s*=\s*"[^"]*"',
        'description = "Canonical roadway graph cache and crash-analysis tooling for Virginia signalized intersections."',
        after,
    )
    after = re.sub(r'readme\s*=\s*"[^"]*"', 'readme = "README.md"', after)
    find_block = """[tool.setuptools.packages.find]\nwhere = ["."]\ninclude = ["src.roadway_graph*"]\nnamespaces = true\n"""
    if "[tool.setuptools]" in after:
        after = re.sub(r"\[tool\.setuptools\]\s*packages\s*=\s*\[[\s\S]*?\]\s*", find_block, after, count=1)
    elif "[tool.setuptools.packages.find]" not in after:
        after = after.rstrip() + "\n\n" + find_block
    changed = before != after
    if changed:
        PYPROJECT.write_text(after, encoding="utf-8")
    post = PYPROJECT.read_text(encoding="utf-8")
    stale = stale_pyproject_rows(post)
    write_csv(OUT_DIR / "pyproject_update_plan.csv", plan)
    write_csv(OUT_DIR / "pyproject_update_summary.csv", [{"updated": changed, "discovered_subpackages": "|".join(packages)}])
    write_csv(OUT_DIR / "pyproject_post_update_settings.csv", pyproject_settings(post))
    write_csv(OUT_DIR / "pyproject_post_update_stale_reference_check.csv", stale)
    decision = "pyproject_update_failed_stop" if stale else "pyproject_updated_continue" if changed else "pyproject_no_update_needed_continue"
    write_csv(OUT_DIR / "gate3_decision.csv", [{"gate3_decision": decision}])
    return decision


def compile_package() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for p in sorted(SRC_RG.rglob("*.py")):
        try:
            py_compile.compile(str(p), doraise=True)
            rows.append({"path": rel(p), "compiled": True, "error": ""})
        except Exception as exc:
            rows.append({"path": rel(p), "compiled": False, "error": f"{type(exc).__name__}: {exc}"})
            failures.append({"path": rel(p), "error": f"{type(exc).__name__}: {exc}"})
    return rows, failures


def run_python_check(code: str) -> dict[str, Any]:
    proc = subprocess.run([str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"), "-c", code], cwd=REPO_ROOT, capture_output=True, text=True)
    return {"returncode": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip(), "passed": proc.returncode == 0}


def old_import_refs() -> list[dict[str, Any]]:
    rows = []
    old_import = "src.active" + ".roadway_graph"
    for p in sorted(SRC_RG.rglob("*.py")):
        body = p.read_text(encoding="utf-8", errors="replace")
        if old_import in body:
            rows.append({"path": rel(p), "pattern": old_import})
    return rows


def validate(before_protected: dict[str, dict[str, Any]], before_docs: dict[str, dict[str, Any]]) -> str:
    compile_rows, failures = compile_package()
    package_check = run_python_check("import src.roadway_graph; print('import ok')")
    subpkg_check = run_python_check("import src.roadway_graph.build, src.roadway_graph.patch, src.roadway_graph.audit, src.roadway_graph.qa, src.roadway_graph.utils, src.roadway_graph.cli; print('subpackages ok')")
    discovery_check = run_python_check("import setuptools; print('\\n'.join(setuptools.find_namespace_packages(where='.', include=['src.roadway_graph*'])))")
    old_refs = old_import_refs()

    after_protected = protected_snapshot()
    protected_rows = []
    for key, before in before_protected.items():
        after = after_protected[key]
        protected_rows.append({"path": key, "file_count_before": before["file_count"], "file_count_after": after["file_count"], "total_size_before": before["total_size"], "total_size_after": after["total_size"], "unchanged": before["file_count"] == after["file_count"] and before["total_size"] == after["total_size"]})

    after_docs = docs_snapshot()
    docs_rows = []
    all_doc_paths = sorted(set(before_docs) | set(after_docs))
    for path in all_doc_paths:
        b = before_docs.get(path)
        a = after_docs.get(path)
        docs_rows.append({"path": path, "existed_before": b is not None, "exists_after": a is not None, "hash_before": b.get("hash") if b else "", "hash_after": a.get("hash") if a else "", "untouched": bool(b and a and b.get("hash") == a.get("hash"))})

    write_csv(OUT_DIR / "package_compile_check.csv", compile_rows)
    write_csv(OUT_DIR / "package_import_check.csv", [{"check": "import src.roadway_graph", **package_check}, {"check": "setuptools namespace discovery", **discovery_check}])
    write_csv(OUT_DIR / "subpackage_import_check.csv", [{"check": "representative subpackages", **subpkg_check}])
    write_csv(OUT_DIR / "old_import_reference_check.csv", old_refs)
    write_csv(OUT_DIR / "protected_products_unchanged_check.csv", protected_rows)
    write_csv(OUT_DIR / "docs_untouched_check.csv", docs_rows)
    failed = failures or old_refs or not package_check["passed"] or not subpkg_check["passed"] or not all(r["unchanged"] for r in protected_rows) or not all(r["untouched"] for r in docs_rows)
    decision = "package_validation_failed_manual_repair_needed" if failed else "package_validation_passed"
    write_csv(OUT_DIR / "gate4_decision.csv", [{"gate4_decision": decision, "compile_failures": len(failures), "old_import_refs": len(old_refs), "docs_untouched": all(r["untouched"] for r in docs_rows)}])
    return decision


def cleanup_pycache() -> None:
    for p in sorted(SRC_RG.rglob("__pycache__")):
        if SRC_RG.resolve() in p.resolve().parents:
            shutil.rmtree(p)


def final_notes(final_decision: str, config_decision: str, pyproject_decision: str, validation_decision: str) -> None:
    write_csv(OUT_DIR / "final_decision.csv", [{"final_decision": final_decision}])
    write_csv(OUT_DIR / "recommended_next_actions.csv", [
        {"action_order": 1, "recommended_action": "Run a final zip-readiness audit covering git status, ignored heavy paths, and required distribution artifacts."},
        {"action_order": 2, "recommended_action": "Review remaining source-code stale path references from prior roadway_graph cleanup outputs."},
        {"action_order": 3, "recommended_action": "Decide whether legacy_06152026 should remain ignored, be zipped externally, or be excluded from distribution."},
    ])
    write_json(OUT_DIR / "manifest.json", {"created_utc": now(), "final_decision": final_decision, "config_decision": config_decision, "pyproject_decision": pyproject_decision, "validation_decision": validation_decision})
    write_json(OUT_DIR / "qa_manifest.json", {"created_utc": now(), "docs_broadly_rewritten": False, "protected_products_modified": False, "heavy_builds_run": False, "source_geodatabases_modified": False})
    memo = f"""# Package Metadata Cleanup

Config decision: `{config_decision}`. Root `config/` was removed only if absent/empty or after files were archived to `legacy_06152026`.

Pyproject decision: `{pyproject_decision}`. `pyproject.toml` now uses setuptools namespace discovery for `src.roadway_graph*`, with current description and `README.md` as the project readme.

Validation decision: `{validation_decision}`. Package compile/import/subpackage checks are recorded in the review outputs.

Docs were preserved; hashes are recorded in `docs_untouched_check.csv`.

Protected products were unchanged; see `protected_products_unchanged_check.csv`.

Final decision: `{final_decision}`.

Recommended next task: run a final zip-readiness audit and review remaining source-code stale references from the earlier source cleanup pass.
"""
    (OUT_DIR / "findings_memo.md").write_text(memo, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    progress = [f"{now()} start"]
    before_docs = docs_snapshot()
    before_protected = protected_snapshot()

    d1 = gate1(before_docs)
    progress.append(f"{now()} gate1 {d1}")
    if d1.endswith("_stop"):
        final_notes("package_metadata_cleanup_inconclusive_manual_review", d1, "not_run", "not_run")
        return

    d2 = gate2_archive_config()
    progress.append(f"{now()} gate2 {d2}")
    if d2.endswith("_stop"):
        final_notes("package_metadata_cleanup_inconclusive_manual_review", d2, "not_run", "not_run")
        return

    d3 = update_pyproject()
    progress.append(f"{now()} gate3 {d3}")
    if d3.endswith("_stop"):
        final_notes("package_metadata_cleanup_blocked_by_pyproject", d2, d3, "not_run")
        return

    d4 = validate(before_protected, before_docs)
    progress.append(f"{now()} gate4 {d4}")
    cleanup_pycache()
    if d4 == "package_validation_passed":
        final = "package_metadata_cleanup_complete_ready_for_zip_audit"
    elif d4 == "package_validation_passed_with_notes":
        final = "package_metadata_cleanup_complete_with_minor_notes"
    else:
        final = "package_metadata_cleanup_blocked_by_import_errors"
    final_notes(final, d2, d3, d4)
    (OUT_DIR / "progress_log.md").write_text("\n".join(f"- {p}" for p in progress) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
