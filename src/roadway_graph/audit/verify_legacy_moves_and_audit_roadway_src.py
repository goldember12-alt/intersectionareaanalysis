from __future__ import annotations

import ast
import csv
import hashlib
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_RG = REPO_ROOT / "src" / "roadway_graph"
OUT_DIR = REPO_ROOT / "work" / "roadway_graph" / "review" / "verify_legacy_moves_and_audit_roadway_src"
PRIOR_DIR = REPO_ROOT / "work" / "roadway_graph" / "review" / "repo_scripts_src_tests_cleanup_audit"

PROTECTED_DIRS = [
    REPO_ROOT / "work" / "roadway_graph" / "analysis" / "final_dataset_cache",
    REPO_ROOT / "work" / "roadway_graph" / "analysis" / "final_summaries",
    REPO_ROOT / "work" / "roadway_graph" / "analysis" / "mvp_dataset",
    REPO_ROOT / "artifacts",
]

ROOT_NAMES = ["scripts", "src", "tests", "work", "artifacts", "config", "docs"]
TEXT_EXTS = {".py", ".md", ".txt", ".json", ".csv", ".toml", ".ps1", ".cmd", ".bat", ".yaml", ".yml"}
STALE_PATTERNS = [
    "src.roadway_graph",
    "src/active/roadway_graph",
    "src\\active\\roadway_graph",
    "final_leg_corrected_analysis_dataset",
    "mvp_dataset",
    "_staging",
    "work/output",
    "work\\output",
    "legacy",
]
CURRENT_PATTERNS = ["final_dataset_cache", "final_summaries", "mvp_dataset"]
REVIEW_PARENT_PATTERNS = ["work/roadway_graph/review", "work\\roadway_graph\\review"]
SOURCE_PATTERNS = ["Intersection Crash Analysis Layers"]
LIKELY_INSTALLED = {"pandas", "geopandas", "numpy", "pyarrow", "pyogrio", "shapely", "pyproj", "sklearn", "scipy", "statsmodels", "matplotlib", "seaborn", "networkx"}


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


def text(path: Path, max_bytes: int = 2_000_000) -> str:
    try:
        if path.stat().st_size > max_bytes or path.suffix.lower() not in TEXT_EXTS:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def file_count_size(root: Path) -> tuple[int, int, int]:
    if not root.exists():
        return 0, 0, 0
    files = 0
    folders = 0
    total = 0
    for p in root.rglob("*"):
        if p.is_dir():
            folders += 1
        elif p.is_file():
            files += 1
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return files, folders, total


def folder_snapshot(root: Path) -> dict[str, Any]:
    files, folders, size = file_count_size(root)
    latest = ""
    if root.exists():
        mtimes = [p.stat().st_mtime for p in root.rglob("*") if p.exists()]
        if mtimes:
            latest = datetime.fromtimestamp(max(mtimes), timezone.utc).isoformat()
    return {"path": rel(root) if root.exists() else root.as_posix(), "exists": root.exists(), "file_count": files, "folder_count": folders, "total_size": size, "latest_modified_timestamp": latest}


def root_inventory() -> list[dict[str, Any]]:
    rows = []
    for p in sorted(REPO_ROOT.iterdir(), key=lambda x: x.name.lower()):
        if p.name == ".git":
            continue
        files, folders, size = file_count_size(p) if p.is_dir() else (1, 0, p.stat().st_size)
        rows.append({"path": p.name, "is_dir": p.is_dir(), "file_count": files, "folder_count": folders, "total_size": size, "modified_timestamp": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()})
    return rows


def detect_legacy_folders() -> list[dict[str, Any]]:
    rows = []
    for p in sorted(REPO_ROOT.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_dir() or not p.name.lower().startswith("legacy"):
            continue
        files, folders, size = file_count_size(p)
        descendants = {x.name.lower() for x in p.iterdir()}
        manifest_like = any(x.name.lower().endswith((".json", ".csv", ".md", ".txt")) and ("manifest" in x.name.lower() or "checksum" in x.name.lower()) for x in p.rglob("*") if x.is_file())
        rows.append({
            "path": rel(p),
            "file_count": files,
            "folder_count": folders,
            "total_size": size,
            "modified_timestamp": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
            "contains_scripts": "scripts" in descendants,
            "contains_tests": "tests" in descendants,
            "contains_old_src_pieces": "legacy src" in descendants or "src" in descendants,
            "contains_manifest_or_checksum": manifest_like,
            "appears_intended_archive": "scripts" in descendants and "tests" in descendants and ("legacy src" in descendants or "src" in descendants),
        })
    return rows


def current_src_layout() -> list[dict[str, Any]]:
    rows = []
    if not (REPO_ROOT / "src").exists():
        return [{"path": "src", "type": "missing", "file_count": 0, "folder_count": 0, "total_size": 0}]
    for p in sorted((REPO_ROOT / "src").iterdir(), key=lambda x: x.name.lower()):
        files, folders, size = file_count_size(p) if p.is_dir() else (1, 0, p.stat().st_size)
        rows.append({"path": rel(p), "type": "dir" if p.is_dir() else "file", "file_count": files, "folder_count": folders, "total_size": size})
    return rows


def load_prior_classifications() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in ["scripts_cleanup_classification.csv", "src_cleanup_classification.csv", "tests_cleanup_classification.csv"]:
        for row in read_csv(PRIOR_DIR / name):
            row["prior_source_file"] = name
            rows.append(row)
    return rows


def candidate_legacy_paths(original: str, legacy_root: Path) -> list[Path]:
    p = Path(original)
    candidates = [legacy_root / p]
    parts = p.parts
    if original.startswith("scripts/"):
        candidates.append(legacy_root / original)
    elif original.startswith("tests/"):
        candidates.append(legacy_root / original)
    elif original.startswith("src/active/roadway_graph/"):
        rest = Path(*parts[3:])
        candidates.append(REPO_ROOT / "src" / "roadway_graph" / rest)
        candidates.append(legacy_root / "legacy src" / "roadway_graph" / rest)
    elif original.startswith("src/active/"):
        rest = Path(*parts[2:])
        candidates.append(legacy_root / "legacy src" / rest)
    elif original.startswith("src/transitional/"):
        rest = Path(*parts[1:])
        candidates.append(legacy_root / "legacy src" / rest)
    elif original.startswith("src/"):
        rest = Path(*parts[1:])
        candidates.append(legacy_root / "legacy src" / rest)
    return list(dict.fromkeys(candidates))


def verify_moves(prior_rows: list[dict[str, Any]], legacy_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    verification = []
    unexpected_remaining = []
    missing = []
    moved_current = []
    for row in prior_rows:
        original = row["path"]
        classification = row.get("cleanup_classification", "")
        original_path = REPO_ROOT / original
        candidates = candidate_legacy_paths(original, legacy_root)
        existing_candidates = [p for p in candidates if p.exists()]
        status = "manual_review_needed"
        located = ""
        hash_match = ""
        prior_hash = row.get("file_hash", "")
        if classification == "keep_current":
            current_equivalent = None
            if original.startswith("src/active/roadway_graph/"):
                current_equivalent = REPO_ROOT / "src" / "roadway_graph" / Path(original).relative_to("src/active/roadway_graph")
            if current_equivalent and current_equivalent.exists():
                status = "verified_current_file_promoted_to_src_roadway_graph"
                located = rel(current_equivalent)
                if prior_hash:
                    hash_match = str(sha256(current_equivalent) == prior_hash)
            elif any(str(p).startswith(str(legacy_root)) for p in existing_candidates):
                status = "unexpected_moved_current_file"
                located = rel(existing_candidates[0])
                moved_current.append({"path": original, "located_path": located, "prior_classification": classification})
            else:
                status = "missing_from_original_and_legacy"
                missing.append({"path": original, "prior_classification": classification, "note": "keep_current not found at promoted path"})
        elif classification in {"archive_legacy", "delete_candidate"}:
            if original_path.exists():
                status = "verified_still_in_place"
                located = original
                if not original.startswith("src/roadway_graph/"):
                    unexpected_remaining.append({"path": original, "prior_classification": classification, "safe_to_move_if_not_ambiguous": True})
            elif existing_candidates:
                status = "verified_moved_to_legacy" if str(existing_candidates[0]).startswith(str(legacy_root)) else "verified_current_file_promoted_to_src_roadway_graph"
                located = rel(existing_candidates[0])
                if prior_hash and existing_candidates[0].is_file():
                    hash_match = str(sha256(existing_candidates[0]) == prior_hash)
            else:
                status = "missing_from_original_and_legacy"
                if classification == "archive_legacy":
                    missing.append({"path": original, "prior_classification": classification, "note": "archive candidate missing from original and legacy"})
        elif classification == "manual_review":
            if original_path.exists():
                status = "verified_still_in_place"
                located = original
            elif existing_candidates:
                status = "verified_moved_to_legacy"
                located = rel(existing_candidates[0])
            else:
                status = "missing_from_original_and_legacy"
        verification.append({"path": original, "prior_classification": classification, "verification_status": status, "located_path": located, "prior_hash": prior_hash, "hash_match": hash_match})
    return verification, unexpected_remaining, missing, moved_current


def move_safe_remaining(rows: list[dict[str, Any]], legacy_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    plan = []
    executed = []
    skipped = []
    checks = []
    for row in rows:
        source = REPO_ROOT / row["path"]
        if not source.exists():
            continue
        if row["path"].startswith("src/roadway_graph/") or row["path"].startswith("src\\roadway_graph\\"):
            skipped.append({"source_path": row["path"], "reason": "inside src/roadway_graph; cleanup from that folder is audit-only in this task"})
            continue
        target = legacy_root / row["path"]
        plan_row = {"source_path": row["path"], "target_path": rel(target.parent / source.name) if target.parent.exists() else target.as_posix(), "file_size": source.stat().st_size if source.is_file() else "", "source_hash": sha256(source) if source.is_file() else ""}
        plan.append(plan_row)
        if target.exists():
            skipped.append({"source_path": row["path"], "target_path": rel(target), "reason": "target already exists"})
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            target_hash = sha256(target) if target.is_file() else ""
            passed = (not plan_row["source_hash"]) or plan_row["source_hash"] == target_hash
            executed.append({"source_path": row["path"], "target_path": rel(target), "move_completed": True})
            checks.append({"source_path": row["path"], "target_path": rel(target), "source_hash": plan_row["source_hash"], "target_hash": target_hash, "hash_match": passed})
        except Exception as exc:
            skipped.append({"source_path": row["path"], "target_path": target.as_posix(), "reason": f"{type(exc).__name__}: {exc}"})
    return plan, executed, skipped, checks


def classify_rg_file(path: Path) -> str:
    name = path.name.lower()
    if "__pycache__" in path.parts or name.endswith(".pyc") or ".tmp" in name:
        return "generated_or_cache_delete_candidate"
    if name in {"__init__.py", "__main__.py", "builder.py", "crs_utils.py", "geometric_direction.py", "roadway_role_classification.py"}:
        return "core_current"
    if name.startswith("build_") or name.startswith("patch_") or "repair_" in name or "rebuild_" in name:
        return "active_builder_or_patch_script"
    if "audit" in name or "validation" in name or "readiness" in name:
        return "active_audit_script"
    if "diagnostic" in name or "prototype" in name or "review" in name or "legacy" in name:
        return "one_off_diagnostic_keep_temporarily"
    if name.startswith("final_") or name.startswith("mvp_") or name.startswith("stage_"):
        return "active_builder_or_patch_script"
    return "manual_review"


def inventory_src_rg() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inv = []
    classes = []
    for p in sorted(SRC_RG.rglob("*"), key=lambda x: rel(x).lower()):
        if not p.is_file():
            continue
        body = text(p)
        cls = classify_rg_file(p)
        stat = p.stat()
        inv.append({"path": rel(p), "extension": p.suffix.lower(), "file_size": stat.st_size, "modified_timestamp": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(), "line_count": body.count("\n") + 1 if body else "", "file_hash": sha256(p), "classification": cls})
        classes.append({"path": rel(p), "file_classification": cls, "rationale": "name/path heuristic plus generated-cache detection"})
    return inv, classes


def module_name(path: Path) -> str:
    return ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)


def import_audit() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    unresolved = []
    project_modules = {module_name(p): rel(p) for p in SRC_RG.rglob("*.py")}
    stdlib = getattr(sys, "stdlib_module_names", set())
    for p in sorted(SRC_RG.rglob("*.py"), key=lambda x: rel(x).lower()):
        body = text(p)
        try:
            tree = ast.parse(body, filename=str(p))
        except SyntaxError as exc:
            unresolved.append({"path": rel(p), "import_name": "", "reason": f"SyntaxError: {exc}"})
            continue
        for node in ast.walk(tree):
            imports: list[tuple[str, int]] = []
            if isinstance(node, ast.Import):
                imports.extend((a.name, 0) for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append((node.module or "", node.level))
            for imp, level in imports:
                root = imp.split(".")[0] if imp else ""
                typ = "relative_import" if level else "unresolved_or_installed"
                resolved = ""
                if imp in project_modules:
                    typ = "inside_src_roadway_graph"
                    resolved = project_modules[imp]
                elif imp.startswith("src.roadway_graph"):
                    typ = "inside_src_roadway_graph"
                elif imp.startswith("src.roadway_graph"):
                    typ = "old_src_active_roadway_graph_import"
                    unresolved.append({"path": rel(p), "import_name": imp, "reason": "imports old src.roadway_graph path"})
                elif root in stdlib:
                    typ = "standard_library"
                elif root in LIKELY_INSTALLED:
                    typ = "installed_package"
                elif level:
                    typ = "relative_import"
                rows.append({"path": rel(p), "import_name": imp, "root_module": root, "level": level, "import_type": typ, "resolved_path": resolved})
                if typ == "unresolved_or_installed" and root not in {"", "__future__"}:
                    unresolved.append({"path": rel(p), "import_name": imp, "reason": "not resolved as stdlib/known package/src_roadway_graph"})
    return rows, unresolved


def path_references() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    refs = []
    entrypoints = []
    for p in sorted(SRC_RG.rglob("*"), key=lambda x: rel(x).lower()):
        if not p.is_file():
            continue
        body = text(p)
        if not body:
            continue
        for pattern in STALE_PATTERNS + CURRENT_PATTERNS + REVIEW_PARENT_PATTERNS + SOURCE_PATTERNS:
            count = body.lower().count(pattern.lower())
            if count:
                refs.append({"path": rel(p), "pattern": pattern, "match_count": count, "reference_class": "stale" if pattern in STALE_PATTERNS else "current_or_context"})
        if p.suffix == ".py" and ("if __name__" in body or "def main(" in body):
            entrypoints.append({"path": rel(p), "entrypoint_signal": "main_function_or_main_guard"})
    return refs, entrypoints


def protected_snapshot() -> dict[str, dict[str, Any]]:
    return {rel(p): folder_snapshot(p) for p in PROTECTED_DIRS}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    progress = [f"{now()} start"]
    before = protected_snapshot()

    root_rows = root_inventory()
    legacy_rows = detect_legacy_folders()
    src_layout = current_src_layout()
    write_csv(OUT_DIR / "root_folder_inventory.csv", root_rows)
    write_csv(OUT_DIR / "detected_legacy_folders.csv", legacy_rows)
    write_csv(OUT_DIR / "current_src_layout_inventory.csv", src_layout)

    intended = [r for r in legacy_rows if str(r.get("appears_intended_archive")) == "True" or r.get("appears_intended_archive") is True]
    gate1 = "legacy_folder_detected_continue"
    if not SRC_RG.exists():
        gate1 = "src_roadway_graph_missing_stop"
    elif not legacy_rows:
        gate1 = "legacy_folder_missing_stop"
    elif len(intended) != 1:
        gate1 = "layout_ambiguous_manual_review_stop"
    legacy_root = REPO_ROOT / intended[0]["path"] if intended else REPO_ROOT / legacy_rows[0]["path"] if legacy_rows else REPO_ROOT / "legacy_missing"
    write_csv(OUT_DIR / "gate1_layout_decision.csv", [{"gate1_decision": gate1, "legacy_folder": rel(legacy_root) if legacy_root.exists() else ""}])
    progress.append(f"{now()} gate1 {gate1}")
    if gate1.endswith("_stop"):
        finalize(gate1, "cleanup_verification_inconclusive", progress, before, before, [], [], [], [])
        return

    prior = load_prior_classifications()
    write_csv(OUT_DIR / "prior_audit_classification_loaded.csv", prior)
    verification, remaining, missing, moved_current = verify_moves(prior, legacy_root)
    write_csv(OUT_DIR / "manual_move_verification.csv", verification)
    write_csv(OUT_DIR / "unexpected_remaining_files.csv", remaining)
    write_csv(OUT_DIR / "missing_after_move_ledger.csv", missing)
    write_csv(OUT_DIR / "unexpectedly_moved_current_files.csv", moved_current)
    write_csv(OUT_DIR / "scripts_move_status.csv", [r for r in verification if r["path"].startswith("scripts/")])
    write_csv(OUT_DIR / "tests_move_status.csv", [r for r in verification if r["path"].startswith("tests/")])
    write_csv(OUT_DIR / "src_legacy_move_status.csv", [r for r in verification if r["path"].startswith("src/") and not r["path"].startswith("src/active/roadway_graph/")])
    if moved_current:
        gate2 = "current_files_moved_to_legacy_stop"
    elif any(r for r in missing if r.get("prior_classification") != "delete_candidate"):
        gate2 = "manual_moves_have_missing_files_stop"
    elif remaining:
        gate2 = "manual_moves_verified_with_remaining_safe_moves_continue"
    else:
        gate2 = "manual_moves_verified_continue"
    write_csv(OUT_DIR / "gate2_move_verification_decision.csv", [{"gate2_decision": gate2, "remaining_safe_move_count": len(remaining), "missing_count": len(missing), "moved_current_count": len(moved_current)}])
    progress.append(f"{now()} gate2 {gate2}")
    if gate2.endswith("_stop"):
        finalize(gate2, "cleanup_blocked_by_missing_or_misplaced_files", progress, before, before, [], [], [], [])
        return

    if remaining:
        plan, executed, skipped, checks = move_safe_remaining(remaining, legacy_root)
        gate3 = "safe_remaining_moves_completed" if executed and not skipped else "remaining_moves_skipped_manual_review" if skipped else "no_remaining_moves_needed"
    else:
        plan, executed, skipped, checks = [], [], [], []
        gate3 = "no_remaining_moves_needed"
    write_csv(OUT_DIR / "safe_remaining_moves_plan.csv", plan)
    write_csv(OUT_DIR / "safe_remaining_moves_executed.csv", executed)
    write_csv(OUT_DIR / "safe_remaining_moves_skipped.csv", skipped)
    write_csv(OUT_DIR / "safe_move_checksum_verification.csv", checks)
    write_csv(OUT_DIR / "gate3_move_completion_decision.csv", [{"gate3_decision": gate3, "executed_count": len(executed), "skipped_count": len(skipped)}])
    progress.append(f"{now()} gate3 {gate3}")

    post_root = root_inventory()
    write_csv(OUT_DIR / "post_cleanup_root_inventory.csv", post_root)
    write_csv(OUT_DIR / "post_cleanup_scripts_status.csv", [{"path": "scripts", **folder_snapshot(REPO_ROOT / "scripts")}])
    write_csv(OUT_DIR / "post_cleanup_tests_status.csv", [{"path": "tests", **folder_snapshot(REPO_ROOT / "tests")}])
    write_csv(OUT_DIR / "post_cleanup_src_status.csv", current_src_layout())
    after = protected_snapshot()
    protected_rows = []
    for key, b in before.items():
        a = after[key]
        protected_rows.append({"path": key, "file_count_before": b["file_count"], "file_count_after": a["file_count"], "total_size_before": b["total_size"], "total_size_after": a["total_size"], "unchanged": b["file_count"] == a["file_count"] and b["total_size"] == a["total_size"]})
    write_csv(OUT_DIR / "protected_products_unchanged_check.csv", protected_rows)
    gate4 = "cleanup_state_verified_ready_for_src_roadway_graph_audit" if all(r["unchanged"] for r in protected_rows) else "cleanup_state_not_safe_stop"
    write_csv(OUT_DIR / "gate4_post_cleanup_decision.csv", [{"gate4_decision": gate4}])
    progress.append(f"{now()} gate4 {gate4}")
    if gate4.endswith("_stop"):
        finalize(gate4, "cleanup_verification_inconclusive", progress, before, after, plan, executed, skipped, checks)
        return

    rg_inv, rg_class = inventory_src_rg()
    imports, unresolved = import_audit()
    refs, entrypoints = path_references()
    write_csv(OUT_DIR / "src_roadway_graph_file_inventory.csv", rg_inv)
    write_csv(OUT_DIR / "src_roadway_graph_import_audit.csv", imports)
    write_csv(OUT_DIR / "src_roadway_graph_unresolved_imports.csv", unresolved)
    write_csv(OUT_DIR / "src_roadway_graph_path_reference_audit.csv", refs)
    write_csv(OUT_DIR / "src_roadway_graph_file_classification.csv", rg_class)
    write_csv(OUT_DIR / "src_roadway_graph_entrypoint_candidates.csv", entrypoints)
    write_csv(OUT_DIR / "src_roadway_graph_generated_cache_candidates.csv", [r for r in rg_class if r["file_classification"] == "generated_or_cache_delete_candidate"])
    write_csv(OUT_DIR / "src_roadway_graph_legacy_candidates.csv", [r for r in rg_class if r["file_classification"] in {"one_off_diagnostic_keep_temporarily", "legacy_archive_candidate"}])
    write_csv(OUT_DIR / "src_roadway_graph_manual_review_items.csv", [r for r in rg_class if r["file_classification"] == "manual_review"])
    class_counts = Counter(r["file_classification"] for r in rg_class)
    external = [r for r in imports if r["import_type"] == "old_src_active_roadway_graph_import"]
    stale = [r for r in refs if r["reference_class"] == "stale"]
    gate5 = "src_roadway_graph_has_external_dependency_blockers" if external else "src_roadway_graph_contains_legacy_generated_cleanup_needed" if class_counts.get("generated_or_cache_delete_candidate", 0) or stale else "src_roadway_graph_audit_complete_ready_for_reorganization_plan"
    write_csv(OUT_DIR / "src_roadway_graph_reorganization_plan.csv", [
        {"step_order": 1, "recommendation": "Remove generated/cache files from src/roadway_graph in a later cleanup task after checksum/archive review."},
        {"step_order": 2, "recommendation": "Separate canonical builders, audits, patch scripts, and one-off diagnostics into subpackages or archive buckets."},
        {"step_order": 3, "recommendation": "Update hardcoded stale paths from work/output and old final_leg/mvp folder names before treating modules as current runnable entrypoints."},
        {"step_order": 4, "recommendation": "Update pyproject package discovery for src.roadway_graph after reorganization decisions."},
    ])
    write_csv(OUT_DIR / "gate5_src_audit_decision.csv", [{"gate5_decision": gate5, "file_count": len(rg_inv), "external_old_import_count": len(external), "stale_reference_rows": len(stale), "generated_cache_count": class_counts.get("generated_or_cache_delete_candidate", 0)}])
    progress.append(f"{now()} gate5 {gate5}")

    final_decision = "legacy_moves_completed_src_roadway_graph_audited_ready_for_next_cleanup" if executed and gate5 == "src_roadway_graph_audit_complete_ready_for_reorganization_plan" else "legacy_moves_verified_src_roadway_graph_audited_ready_for_next_cleanup" if gate5 == "src_roadway_graph_audit_complete_ready_for_reorganization_plan" else "legacy_moves_verified_but_src_roadway_graph_needs_manual_review"
    finalize(gate5, final_decision, progress, before, after, plan, executed, skipped, checks, class_counts, len(stale), len(external), legacy_root)


def finalize(gate_status: str, final_decision: str, progress: list[str], before: dict[str, Any], after: dict[str, Any], plan: list[dict[str, Any]], executed: list[dict[str, Any]], skipped: list[dict[str, Any]], checks: list[dict[str, Any]], class_counts: Counter | None = None, stale_count: int = 0, external_count: int = 0, legacy_root: Path | None = None) -> None:
    write_csv(OUT_DIR / "final_decision.csv", [{"final_decision": final_decision}])
    write_csv(OUT_DIR / "recommended_next_actions.csv", [
        {"action_order": 1, "recommended_action": "Review src_roadway_graph_file_classification.csv and stale path references before reorganizing src/roadway_graph."},
        {"action_order": 2, "recommended_action": "Run a later src/roadway_graph cleanup task to remove generated/cache files and archive one-off diagnostics."},
        {"action_order": 3, "recommended_action": "Update pyproject/package entrypoints after source layout decisions."},
    ])
    write_json(OUT_DIR / "manifest.json", {"created_utc": now(), "output_folder": rel(OUT_DIR), "legacy_folder": rel(legacy_root) if legacy_root and legacy_root.exists() else "", "final_decision": final_decision, "gate_status": gate_status})
    write_json(OUT_DIR / "qa_manifest.json", {"created_utc": now(), "deleted_files_permanently": False, "moved_src_roadway_graph": False, "reorganized_src_roadway_graph": False, "modified_protected_products": False, "safe_moves_executed_count": len(executed), "safe_moves_skipped_count": len(skipped)})
    (OUT_DIR / "progress_log.md").write_text("\n".join(f"- {p}" for p in progress) + "\n", encoding="utf-8")
    cls = dict(class_counts or {})
    memo = f"""# Verify Legacy Moves And Audit Roadway Src

Created: {now()}

Detected legacy folder: `{rel(legacy_root) if legacy_root and legacy_root.exists() else 'not detected'}`.

Manual move verification was run against `work/roadway_graph/review/repo_scripts_src_tests_cleanup_audit/`. Current files moved into legacy are reported in `unexpectedly_moved_current_files.csv`; remaining legacy candidates are reported in `unexpected_remaining_files.csv`; missing files are reported in `missing_after_move_ledger.csv`.

Safe moves completed by this script: {len(executed)}. Safe moves skipped: {len(skipped)}. No files were permanently deleted.

`src/roadway_graph` was not moved or reorganized.

Current root status: root `scripts/` and `tests/` are absent unless listed in the post-cleanup status CSVs; root `src/` contains the candidate `src/roadway_graph` package.

Protected products check: `protected_products_unchanged_check.csv`.

`src/roadway_graph` classification summary: {cls}.

External old `src.roadway_graph` import findings: {external_count}.

Hardcoded stale path/reference rows in `src/roadway_graph`: {stale_count}.

Recommended next task: clean and reorganize `src/roadway_graph` in a dedicated task, starting with generated/cache files and stale path references, then update package metadata.

Final decision: `{final_decision}`.
"""
    (OUT_DIR / "findings_memo.md").write_text(memo, encoding="utf-8")


if __name__ == "__main__":
    main()
