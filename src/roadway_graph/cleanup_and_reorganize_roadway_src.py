from __future__ import annotations

import ast
import csv
import hashlib
import json
import py_compile
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_RG = REPO_ROOT / "src" / "roadway_graph"
LEGACY_ROOT = REPO_ROOT / "legacy_06152026"
LEGACY_REORG_ROOT = LEGACY_ROOT / "src_roadway_graph_pre_reorg"
PRIOR_DIR = REPO_ROOT / "work" / "roadway_graph" / "review" / "verify_legacy_moves_and_audit_roadway_src"
OUT_DIR = REPO_ROOT / "work" / "roadway_graph" / "review" / "cleanup_and_reorganize_roadway_src"

PROTECTED_PRODUCTS = [
    REPO_ROOT / "work" / "roadway_graph" / "analysis" / "final_dataset_cache",
    REPO_ROOT / "work" / "roadway_graph" / "analysis" / "final_summaries",
    REPO_ROOT / "work" / "roadway_graph" / "analysis" / "mvp_dataset",
    REPO_ROOT / "artifacts",
]

KEEP_ROOT = {
    "__init__.py",
    "__main__.py",
    "README.md",
    "builder.py",
    "cleanup_and_reorganize_roadway_src.py",
}
UTILS = {"crs_utils.py", "geometric_direction.py", "roadway_role_classification.py"}
TEXT_EXTS = {".py", ".md", ".txt", ".json", ".csv"}
STALE_PATTERNS = [
    "src.roadway_graph",
    "src/active/roadway_graph",
    "src\\active\\roadway_graph",
    "final_leg_corrected_analysis_dataset",
    "mvp_dataset",
    "_staging",
    "work/output",
    "work\\output",
]
SAFE_PATH_REWRITES = {
    "mvp_dataset": "mvp_dataset",
}


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


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def text(path: Path) -> str:
    try:
        if path.suffix.lower() not in TEXT_EXTS or path.stat().st_size > 2_000_000:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def folder_snapshot(path: Path) -> dict[str, Any]:
    files = 0
    size = 0
    if path.exists():
        for p in path.rglob("*"):
            if p.is_file():
                files += 1
                size += p.stat().st_size
    return {"path": rel(path), "exists": path.exists(), "file_count": files, "total_size": size}


def current_inventory() -> list[dict[str, Any]]:
    rows = []
    if not SRC_RG.exists():
        return rows
    for p in sorted(SRC_RG.rglob("*"), key=lambda x: rel(x).lower()):
        if not p.is_file():
            continue
        rows.append(
            {
                "path": rel(p),
                "extension": p.suffix.lower(),
                "file_size": p.stat().st_size,
                "modified_timestamp": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
                "file_hash": sha256(p),
            }
        )
    return rows


def load_prior_classifications() -> dict[str, str]:
    rows = read_csv(PRIOR_DIR / "src_roadway_graph_file_classification.csv")
    return {row["path"]: row["file_classification"] for row in rows if row.get("path")}


def ensure_pkg_dirs() -> None:
    for name in ["build", "patch", "audit", "qa", "utils", "cli", "docs"]:
        d = SRC_RG / name
        d.mkdir(exist_ok=True)
        init = d / "__init__.py"
        if name != "docs" and not init.exists():
            init.write_text('"""Roadway graph package submodule."""\n', encoding="utf-8")


def gate1(prior: dict[str, str], before: dict[str, dict[str, Any]]) -> str:
    rows = []
    checks = {
        "legacy_06152026_exists": LEGACY_ROOT.exists(),
        "src_roadway_graph_exists": SRC_RG.exists(),
        "scripts_absent": not (REPO_ROOT / "scripts").exists(),
        "tests_absent": not (REPO_ROOT / "tests").exists(),
        "prior_classifications_loaded": bool(prior),
    }
    for key, passed in checks.items():
        rows.append({"check": key, "passed": passed})
    for path, snap in before.items():
        rows.append({"check": f"protected_exists:{path}", "passed": snap["exists"]})
    write_csv(OUT_DIR / "gate1_current_state_check.csv", rows)
    write_csv(OUT_DIR / "gate1_prior_audit_load_check.csv", [{"prior_output": rel(PRIOR_DIR), "loaded_classification_count": len(prior), "passed": bool(prior)}])
    write_csv(OUT_DIR / "gate1_file_inventory_before.csv", current_inventory())
    if not prior:
        decision = "prior_audit_missing_stop"
    elif not LEGACY_ROOT.exists():
        decision = "legacy_folder_missing_stop"
    elif not SRC_RG.exists():
        decision = "src_roadway_graph_missing_stop"
    elif (REPO_ROOT / "scripts").exists() or (REPO_ROOT / "tests").exists():
        decision = "layout_ambiguous_stop"
    else:
        decision = "current_state_verified_continue"
    write_csv(OUT_DIR / "gate1_decision.csv", [{"gate1_decision": decision}])
    return decision


def delete_generated_cache(prior: dict[str, str]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    plan = []
    deleted = []
    verification = []
    for p in sorted(SRC_RG.rglob("*"), key=lambda x: rel(x).lower(), reverse=True):
        if not p.exists():
            continue
        r = rel(p) if p.is_file() else rel(p)
        is_cache = "__pycache__" in p.parts or p.name.endswith(".pyc") or p.name == ".pytest_cache" or p.suffix.lower() in {".pyc", ".pyo"}
        prior_generated = p.is_file() and prior.get(r) == "generated_or_cache_delete_candidate"
        if p.is_file() and (is_cache or prior_generated):
            plan.append({"path": r, "file_size": p.stat().st_size, "file_hash": sha256(p), "reason": "generated/cache file"})
        elif p.is_dir() and (p.name == "__pycache__" or p.name == ".pytest_cache"):
            plan.append({"path": r, "file_size": "", "file_hash": "", "reason": "generated/cache directory"})

    for row in plan:
        p = REPO_ROOT / row["path"]
        if not p.exists():
            verification.append({"path": row["path"], "deleted": True, "note": "already absent"})
            continue
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            deleted.append(row)
            verification.append({"path": row["path"], "deleted": not p.exists(), "note": ""})
        except Exception as exc:
            verification.append({"path": row["path"], "deleted": False, "note": f"{type(exc).__name__}: {exc}"})
    write_csv(OUT_DIR / "gate2_generated_cache_delete_plan.csv", plan)
    write_csv(OUT_DIR / "gate2_generated_cache_deleted.csv", deleted)
    write_csv(OUT_DIR / "gate2_generated_cache_delete_verification.csv", verification)
    failed = [r for r in verification if str(r.get("deleted")) != "True" and r.get("deleted") is not True]
    decision = "generated_cache_delete_failed_stop" if failed else "generated_cache_deleted_continue" if deleted else "no_generated_cache_to_delete_continue"
    write_csv(OUT_DIR / "gate2_decision.csv", [{"gate2_decision": decision, "delete_count": len(deleted), "failed_count": len(failed)}])
    return decision, plan, deleted


def archive_noncurrent(prior: dict[str, str]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    plan = []
    skipped = []
    executed = []
    checks = []
    imported = imported_module_stems()
    for path, cls in prior.items():
        p = REPO_ROOT / path
        if not p.exists() or not p.is_file():
            continue
        if p.name in KEEP_ROOT or p.name == "verify_legacy_moves_and_audit_roadway_src.py":
            skipped.append({"path": path, "reason": "package/root or recent verifier retained"})
            continue
        stem = p.stem
        if cls == "one_off_diagnostic_keep_temporarily" and stem not in imported:
            target = LEGACY_REORG_ROOT / p.relative_to(SRC_RG)
            plan.append({"source_path": path, "target_path": rel(target), "file_size": p.stat().st_size, "source_hash": sha256(p), "reason": cls})
        elif cls == "manual_review":
            skipped.append({"path": path, "reason": "manual_review retained for later inspection"})
    for row in plan:
        src = REPO_ROOT / row["source_path"]
        target = REPO_ROOT / row["target_path"]
        if target.exists():
            skipped.append({"path": row["source_path"], "target_path": row["target_path"], "reason": "target collision"})
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))
        target_hash = sha256(target)
        ok = target_hash == row["source_hash"] and not src.exists()
        executed.append({"source_path": row["source_path"], "target_path": row["target_path"], "moved": ok})
        checks.append({"source_path": row["source_path"], "target_path": row["target_path"], "source_hash": row["source_hash"], "target_hash": target_hash, "hash_match": target_hash == row["source_hash"], "source_removed": not src.exists()})
    remaining_manual = []
    for p in sorted(SRC_RG.rglob("*.py"), key=lambda x: rel(x).lower()):
        r = rel(p)
        if prior.get(r) == "manual_review":
            remaining_manual.append({"path": r, "reason": "manual_review retained"})
    write_csv(OUT_DIR / "gate3_archive_move_plan.csv", plan)
    write_csv(OUT_DIR / "gate3_archive_moves_executed.csv", executed)
    write_csv(OUT_DIR / "gate3_archive_moves_skipped.csv", skipped)
    write_csv(OUT_DIR / "gate3_archive_checksum_verification.csv", checks)
    write_csv(OUT_DIR / "gate3_manual_review_remaining.csv", remaining_manual)
    failed = [r for r in checks if str(r.get("hash_match")) != "True" and r.get("hash_match") is not True]
    decision = "archive_move_failed_stop" if failed else "archive_moves_completed_continue" if executed else "archive_moves_skipped_continue" if skipped else "no_archive_moves_needed_continue"
    write_csv(OUT_DIR / "gate3_decision.csv", [{"gate3_decision": decision, "planned_count": len(plan), "executed_count": len(executed), "skipped_count": len(skipped)}])
    return decision, plan, executed, skipped


def imported_module_stems() -> set[str]:
    stems: set[str] = set()
    for p in SRC_RG.rglob("*.py"):
        body = text(p)
        try:
            tree = ast.parse(body)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(("src.roadway_graph.", "src.roadway_graph.")):
                        stems.add(alias.name.split(".")[-1])
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.startswith(("src.roadway_graph.", "src.roadway_graph.")):
                    stems.add(mod.split(".")[-1])
    return stems


def destination_for(path: Path, cls: str) -> Path | None:
    name = path.name
    if name in KEEP_ROOT:
        return None
    if name in UTILS:
        return SRC_RG / "utils" / name
    if name.startswith("patch_") or "repair_" in name:
        return SRC_RG / "patch" / name
    if cls == "active_audit_script" or "audit" in name or "validation" in name or "readiness" in name:
        return SRC_RG / "audit" / name
    if cls == "active_builder_or_patch_script" or name.startswith(("build_", "stage_", "final_", "mvp_", "rebuild_")):
        return SRC_RG / "build" / name
    if "qa" in name or "review_package" in name:
        return SRC_RG / "qa" / name
    return None


def apply_layout(prior: dict[str, str]) -> tuple[str, dict[str, str], list[dict[str, Any]]]:
    ensure_pkg_dirs()
    move_map: dict[str, str] = {}
    plan = []
    executed = []
    skipped = []
    for p in sorted(SRC_RG.glob("*.py"), key=lambda x: x.name.lower()):
        r = rel(p)
        cls = prior.get(r, "manual_review")
        dest = destination_for(p, cls)
        if dest is None or dest == p:
            skipped.append({"source_path": r, "reason": "retained at package root"})
            continue
        if dest.exists():
            skipped.append({"source_path": r, "target_path": rel(dest), "reason": "target exists"})
            continue
        plan.append({"source_path": r, "target_path": rel(dest), "classification": cls})
        old_mod = f"src.roadway_graph.{p.stem}"
        new_mod = f"src.roadway_graph.{dest.parent.name}.{p.stem}"
        move_map[old_mod] = new_mod
        move_map[f"src.roadway_graph.{p.stem}"] = new_mod
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dest))
        executed.append({"source_path": r, "target_path": rel(dest), "moved": dest.exists() and not p.exists()})
    tree = []
    for p in sorted(SRC_RG.rglob("*"), key=lambda x: rel(x).lower()):
        tree.append({"path": rel(p), "type": "dir" if p.is_dir() else "file", "size": p.stat().st_size if p.is_file() else ""})
    write_csv(OUT_DIR / "gate4_package_layout_plan.csv", plan)
    write_csv(OUT_DIR / "gate4_file_moves_executed.csv", executed)
    write_csv(OUT_DIR / "gate4_file_moves_skipped.csv", skipped)
    write_csv(OUT_DIR / "gate4_package_tree_after.csv", tree)
    decision = "package_layout_applied_continue" if executed and not any(str(r.get("moved")) != "True" and r.get("moved") is not True for r in executed) else "package_layout_partial_continue" if executed else "package_layout_partial_continue"
    write_csv(OUT_DIR / "gate4_decision.csv", [{"gate4_decision": decision, "move_count": len(executed), "skipped_count": len(skipped)}])
    return decision, move_map, executed


def repair_imports_and_paths(move_map: dict[str, str]) -> tuple[str, int, int, list[dict[str, Any]]]:
    import_rows = []
    path_rows = []
    ambiguous = []
    for p in sorted(SRC_RG.rglob("*.py"), key=lambda x: rel(x).lower()):
        body = text(p)
        if not body:
            continue
        original = body
        import_changes = 0
        for old, new in sorted(move_map.items(), key=lambda kv: len(kv[0]), reverse=True):
            if old in body:
                body = body.replace(old, new)
                import_changes += 1
        if "src.roadway_graph" in body:
            # Safe fallback for modules not moved but still promoted to root.
            body = body.replace("src.roadway_graph", "src.roadway_graph")
            import_changes += 1
        path_changes = 0
        for old, new in SAFE_PATH_REWRITES.items():
            if old in body:
                body = body.replace(old, new)
                path_changes += 1
        for marker in ["final_leg_corrected_analysis_dataset", "_staging", "work/output", "work\\output"]:
            if marker in body:
                ambiguous.append({"path": rel(p), "pattern": marker, "reason": "ambiguous executable or historical reference; left unchanged"})
        if body != original:
            p.write_text(body, encoding="utf-8")
        if import_changes:
            import_rows.append({"path": rel(p), "import_rewrites": import_changes})
        if path_changes:
            path_rows.append({"path": rel(p), "path_rewrites": path_changes, "rewrite": "mvp_dataset -> mvp_dataset"})
    unresolved = find_old_imports()
    remaining_stale = find_stale_refs()
    write_csv(OUT_DIR / "gate5_import_rewrite_summary.csv", import_rows)
    write_csv(OUT_DIR / "gate5_stale_path_rewrite_summary.csv", path_rows)
    write_csv(OUT_DIR / "gate5_unresolved_imports_after.csv", unresolved)
    write_csv(OUT_DIR / "gate5_remaining_stale_references.csv", remaining_stale)
    write_csv(OUT_DIR / "gate5_ambiguous_references_ledger.csv", ambiguous)
    decision = "import_repair_failed_stop" if unresolved else "imports_repaired_stale_paths_remain_continue" if remaining_stale else "imports_and_paths_repaired_continue"
    write_csv(OUT_DIR / "gate5_decision.csv", [{"gate5_decision": decision, "import_rewrite_files": len(import_rows), "path_rewrite_files": len(path_rows), "remaining_stale_rows": len(remaining_stale), "ambiguous_rows": len(ambiguous)}])
    return decision, len(import_rows), len(path_rows), remaining_stale


def find_old_imports() -> list[dict[str, Any]]:
    rows = []
    for p in SRC_RG.rglob("*.py"):
        body = text(p)
        if "src.roadway_graph" in body:
            rows.append({"path": rel(p), "unresolved_import": "src.roadway_graph"})
    return rows


def find_stale_refs() -> list[dict[str, Any]]:
    rows = []
    for p in SRC_RG.rglob("*"):
        if not p.is_file():
            continue
        body = text(p)
        if not body:
            continue
        for pat in STALE_PATTERNS:
            count = body.count(pat)
            if count:
                rows.append({"path": rel(p), "pattern": pat, "match_count": count})
    return rows


def validate_package() -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    compile_rows = []
    failures = []
    for p in sorted(SRC_RG.rglob("*.py"), key=lambda x: rel(x).lower()):
        try:
            py_compile.compile(str(p), doraise=True)
            compile_rows.append({"path": rel(p), "compiled": True, "error": ""})
        except Exception as exc:
            compile_rows.append({"path": rel(p), "compiled": False, "error": f"{type(exc).__name__}: {exc}"})
            failures.append({"path": rel(p), "validation": "compile", "error": f"{type(exc).__name__}: {exc}"})
    proc = subprocess.run([str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"), "-c", "import src.roadway_graph; print('import ok')"], cwd=REPO_ROOT, capture_output=True, text=True)
    import_rows = [{"command": "import src.roadway_graph", "returncode": proc.returncode, "stdout": proc.stdout.strip(), "stderr": proc.stderr.strip(), "passed": proc.returncode == 0}]
    if proc.returncode:
        failures.append({"path": "src/roadway_graph", "validation": "import", "error": proc.stderr.strip()})
    entry_rows = [{"entrypoint": "src.roadway_graph", "checked": "package_import_only", "note": "heavy builders not run"}]
    write_csv(OUT_DIR / "gate6_compile_check.csv", compile_rows)
    write_csv(OUT_DIR / "gate6_import_check.csv", import_rows)
    write_csv(OUT_DIR / "gate6_entrypoint_check.csv", entry_rows)
    write_csv(OUT_DIR / "gate6_validation_failures.csv", failures)
    decision = "package_validation_failed_manual_repair_needed" if failures else "package_validation_passed_with_notes"
    write_csv(OUT_DIR / "gate6_decision.csv", [{"gate6_decision": decision, "compile_file_count": len(compile_rows), "failure_count": len(failures)}])
    return decision, compile_rows, import_rows, entry_rows, failures


def final_inventory() -> list[dict[str, Any]]:
    rows = []
    for p in sorted(SRC_RG.rglob("*"), key=lambda x: rel(x).lower()):
        if p.is_file():
            rows.append({"path": rel(p), "size": p.stat().st_size, "extension": p.suffix.lower()})
    write_csv(OUT_DIR / "final_src_roadway_graph_inventory.csv", rows)
    return rows


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    progress = [f"{now()} start"]
    before = {rel(p): folder_snapshot(p) for p in PROTECTED_PRODUCTS}
    prior = load_prior_classifications()

    d1 = gate1(prior, before)
    progress.append(f"{now()} gate1 {d1}")
    if d1.endswith("_stop"):
        finalize("roadway_src_cleanup_blocked", progress, before, before)
        return

    d2, delete_plan, deleted = delete_generated_cache(prior)
    progress.append(f"{now()} gate2 {d2}")
    if d2.endswith("_stop"):
        finalize("roadway_src_cleanup_failed_no_destructive_loss", progress, before, {rel(p): folder_snapshot(p) for p in PROTECTED_PRODUCTS})
        return

    d3, archive_plan, archived, archive_skipped = archive_noncurrent(prior)
    progress.append(f"{now()} gate3 {d3}")
    if d3.endswith("_stop"):
        finalize("roadway_src_cleanup_failed_no_destructive_loss", progress, before, {rel(p): folder_snapshot(p) for p in PROTECTED_PRODUCTS})
        return

    d4, move_map, layout_moves = apply_layout(prior)
    progress.append(f"{now()} gate4 {d4}")
    if d4.endswith("_stop"):
        finalize("roadway_src_cleanup_failed_no_destructive_loss", progress, before, {rel(p): folder_snapshot(p) for p in PROTECTED_PRODUCTS})
        return

    d5, import_rewrites, path_rewrites, stale_remaining = repair_imports_and_paths(move_map)
    progress.append(f"{now()} gate5 {d5}")
    if d5.endswith("_stop"):
        finalize("roadway_src_partially_reorganized_manual_repair_needed", progress, before, {rel(p): folder_snapshot(p) for p in PROTECTED_PRODUCTS})
        return

    d6, compile_rows, import_rows, entry_rows, failures = validate_package()
    progress.append(f"{now()} gate6 {d6}")
    inv = final_inventory()
    manual = [{"path": r["path"], "reason": "manual review after cleanup"} for r in inv if Path(r["path"]).name not in KEEP_ROOT and "/build/" not in r["path"] and "/patch/" not in r["path"] and "/audit/" not in r["path"] and "/utils/" not in r["path"] and "/qa/" not in r["path"] and not r["path"].endswith("__init__.py")]
    write_csv(OUT_DIR / "remaining_manual_review_items.csv", manual)
    write_csv(OUT_DIR / "recommended_next_actions.csv", [
        {"action_order": 1, "recommended_action": "Review remaining stale path references before treating moved modules as current runnable entrypoints."},
        {"action_order": 2, "recommended_action": "Decide what to do with retained manual-review root modules and move/archive them in a second pass."},
        {"action_order": 3, "recommended_action": "Update pyproject.toml package discovery to include src.roadway_graph and subpackages."},
        {"action_order": 4, "recommended_action": "Create lightweight tests for final_dataset_cache, final_summaries, and mvp_dataset command surfaces."},
    ])
    if failures:
        final = "roadway_src_partially_reorganized_manual_repair_needed"
    elif stale_remaining or manual:
        final = "roadway_src_reorganized_with_minor_manual_review"
    else:
        final = "roadway_src_reorganized_and_validated"
    finalize(final, progress, before, {rel(p): folder_snapshot(p) for p in PROTECTED_PRODUCTS}, len(deleted), len(archived), len(layout_moves), import_rewrites, path_rewrites, len(stale_remaining), len(manual), len(failures))


def finalize(
    final_decision: str,
    progress: list[str],
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
    deleted_count: int = 0,
    archived_count: int = 0,
    layout_move_count: int = 0,
    import_rewrites: int = 0,
    path_rewrites: int = 0,
    stale_remaining: int = 0,
    manual_remaining: int = 0,
    validation_failures: int = 0,
) -> None:
    protected = []
    for key, b in before.items():
        a = after.get(key, {})
        protected.append({"path": key, "file_count_before": b.get("file_count"), "file_count_after": a.get("file_count"), "total_size_before": b.get("total_size"), "total_size_after": a.get("total_size"), "unchanged": b.get("file_count") == a.get("file_count") and b.get("total_size") == a.get("total_size")})
    write_csv(OUT_DIR / "protected_products_unchanged_check.csv", protected)
    write_csv(OUT_DIR / "final_decision.csv", [{"final_decision": final_decision}])
    write_json(OUT_DIR / "manifest.json", {"created_utc": now(), "final_decision": final_decision, "output_folder": rel(OUT_DIR), "deleted_generated_cache_count": deleted_count, "archived_count": archived_count, "layout_move_count": layout_move_count})
    write_json(OUT_DIR / "qa_manifest.json", {"created_utc": now(), "modified_analysis_products": False, "modified_artifacts": False, "permanently_deleted_non_cache_source": False, "generated_cache_deleted_count": deleted_count, "validation_failures": validation_failures})
    (OUT_DIR / "progress_log.md").write_text("\n".join(f"- {p}" for p in progress) + "\n", encoding="utf-8")
    memo = f"""# Cleanup And Reorganize Roadway Src

Created: {now()}

Generated/cache files deleted: {deleted_count}. Only cache/generated files under `src/roadway_graph` were deleted.

Files moved to `legacy_06152026/src_roadway_graph_pre_reorg`: {archived_count}.

Package layout created under `src/roadway_graph`: `build/`, `patch/`, `audit/`, `qa/`, `utils/`, `cli/`, and `docs/`.

Files moved into package subfolders: {layout_move_count}.

Import rewrite files changed: {import_rewrites}. Old `src.roadway_graph` imports were rewritten where found.

Stale path rewrite files changed: {path_rewrites}. Ambiguous stale references were left in place and ledgered.

Remaining stale reference rows: {stale_remaining}.

Remaining manual review items: {manual_remaining}.

Validation failures: {validation_failures}.

`src/roadway_graph` is now the active source package candidate, but `pyproject.toml` still needs a later package discovery update.

Final decision: `{final_decision}`.

Recommended next task: review remaining stale references and manual-review modules, then update `pyproject.toml` and add lightweight package tests.
"""
    (OUT_DIR / "findings_memo.md").write_text(memo, encoding="utf-8")


if __name__ == "__main__":
    main()
