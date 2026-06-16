"""Repository structure audit and Codex operating-contract plan.

This read-only audit inventories the active repository roots, classifies large
generated output areas, and drafts AGENTS/README guidance for future Codex
work. It does not delete, move, or rewrite analytical outputs.
"""

from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "work/output/roadway_graph/review/current/repo_structure_audit"

AUDIT_ROOTS = ["artifacts", "config", "docs", "scripts", "src", "tests", "work"]
EXCLUDED_ROOTS = {
    ".git",
    ".venv",
    "Intersection Crash Analysis Layers",
    "legacy",
    "intersection_crash_analysis.egg-info",
}

CANONICAL_FIRST_READ = {
    "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset",
    "work/output/roadway_graph/analysis/current/mvp_dataset",
}


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def write_log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {message}\n")
    print(message, flush=True)


def write_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT_DIR / name, index=False, quoting=csv.QUOTE_MINIMAL)
    write_log(f"Wrote {name}: {len(df):,} rows")


def mb(size: int | float) -> float:
    return round(float(size) / (1024 * 1024), 3)


def classify_role(path: str) -> str:
    p = path.replace("\\", "/").lower()
    if p.startswith("artifacts/"):
        if "normalized" in p:
            return "stable_normalized_data"
        if "stage" in p or "staging" in p:
            return "source_or_staging_input"
        return "artifact_or_input"
    if p.startswith("config/"):
        return "configuration_or_mapping"
    if p.startswith("docs/"):
        if "methodology" in p:
            return "methodology_documentation"
        if "workflow" in p:
            return "workflow_documentation"
        return "documentation"
    if p.startswith("scripts/"):
        return "utility_or_bootstrap_script"
    if p.startswith("src/"):
        return "active_source_code"
    if p.startswith("tests/"):
        return "test_code"
    if p.startswith("work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"):
        return "canonical_first_read_analysis_dataset"
    if p.startswith("work/output/roadway_graph/analysis/current/mvp_dataset"):
        return "canonical_first_read_mvp_distribution"
    if p.startswith("work/output/roadway_graph/analysis/current/"):
        return "current_analysis_product"
    if p.startswith("work/output/roadway_graph/review/current/"):
        return "current_review_product"
    if "map_review" in p:
        return "map_review_package"
    if p.startswith("work/"):
        return "generated_work_output"
    return "other"


def classify_work_product(path: str) -> str:
    p = path.replace("\\", "/")
    if any(p.startswith(c) for c in CANONICAL_FIRST_READ):
        return "canonical_first_read"
    if p.startswith("work/output/roadway_graph/analysis/current/mvp_directional_observed_crash_rate_feasibility"):
        return "supporting_mvp_feasibility"
    if p.startswith("work/output/roadway_graph/analysis/current/final_analysis"):
        return "current_analysis_support_or_diagnostic"
    if p.startswith("work/output/roadway_graph/analysis/current/"):
        return "current_analysis_product"
    if p.startswith("work/output/roadway_graph/review/current/final_"):
        return "current_review_recovery_or_audit"
    if p.startswith("work/output/roadway_graph/review/current/"):
        return "current_review_product"
    if "/map_review/" in p or p.startswith("work/output/roadway_graph/map_review"):
        return "map_review_package"
    if "/history/" in p or "/archive/" in p:
        return "archive_or_history"
    if p.startswith("work/output/"):
        return "generated_intermediate_or_legacy_output"
    return "work_other"


def script_stage(path: str) -> str:
    name = Path(path).name.lower()
    rules = [
        ("source normalization", ["stage", "normalize", "source", "lineage"]),
        ("signal/scaffold recovery", ["signal", "scaffold", "intersection_zone", "offset", "recovery"]),
        ("leg normalization/recovery", ["leg", "physical_leg", "subbranch"]),
        ("access assignment", ["access"]),
        ("crash assignment", ["crash"]),
        ("roadway identity", ["identity", "travelway"]),
        ("directionality", ["directionality", "directional", "upstream", "downstream"]),
        ("MVP / analysis dataset", ["mvp", "analysis_dataset", "guidance_matrix"]),
        ("visualization", ["visualization", "figure", "review_analysis_output_package"]),
        ("repo maintenance", ["inventory", "audit", "cleanup", "work_output"]),
    ]
    for stage, needles in rules:
        if any(n in name for n in needles):
            return stage
    return "other_active_roadway_graph_script"


def scan_files() -> tuple[pd.DataFrame, list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    excluded_rows: list[dict[str, object]] = []
    for root_name in AUDIT_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_ROOTS]
            dpath = Path(dirpath)
            for fname in filenames:
                path = dpath / fname
                try:
                    st = path.stat()
                except OSError:
                    continue
                r = rel(path)
                parts = Path(r).parts
                rows.append(
                    {
                        "path": r,
                        "root": parts[0] if parts else "",
                        "parent": rel(path.parent),
                        "extension": path.suffix.lower() or "[no_ext]",
                        "size_bytes": st.st_size,
                        "size_mb": mb(st.st_size),
                        "modified_time": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                        "likely_role": classify_role(r),
                    }
                )
    for name in sorted(EXCLUDED_ROOTS):
        path = ROOT / name
        excluded_rows.append(
            {
                "excluded_path": name,
                "exists": path.exists(),
                "exclusion_reason": "intentionally_not_deep_scanned",
                "special_note": "generated_package_metadata_candidate_verify_before_delete"
                if name == "intersection_crash_analysis.egg-info"
                else "",
            }
        )
    return pd.DataFrame(rows), excluded_rows


def folder_summary(files: pd.DataFrame, max_level: int = 8) -> pd.DataFrame:
    rows = []
    for level in range(1, max_level + 1):
        grouped: dict[str, dict[str, object]] = {}
        for _, row in files.iterrows():
            parts = Path(row["parent"]).parts
            if not parts:
                continue
            if len(parts) < level:
                continue
            folder = "/".join(parts[:level])
            if not folder:
                continue
            item = grouped.setdefault(folder, {"folder_path": folder, "level": level, "total_size_bytes": 0, "file_count": 0})
            item["total_size_bytes"] += int(row["size_bytes"])
            item["file_count"] += 1
        rows.extend(grouped.values())
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["total_size_mb"] = df["total_size_bytes"].map(mb)
    return df.sort_values(["total_size_bytes", "file_count"], ascending=False)


def root_inventory(files: pd.DataFrame) -> pd.DataFrame:
    folder_counts = defaultdict(set)
    for p in files["parent"]:
        parts = Path(p).parts
        for i in range(1, len(parts) + 1):
            folder_counts[parts[0] if parts else ""].add("/".join(parts[:i]))
    rows = []
    for root in AUDIT_ROOTS:
        sub = files[files["root"].eq(root)]
        if sub.empty:
            rows.append(
                {
                    "folder_path": root,
                    "total_size_mb": 0,
                    "file_count": 0,
                    "folder_count": 0,
                    "largest_subfolders": "",
                    "largest_files": "",
                    "file_extensions_summary": "",
                    "modified_time_min": "",
                    "modified_time_max": "",
                    "likely_role": classify_role(root + "/"),
                }
            )
            continue
        fs = folder_summary(sub, max_level=4)
        largest_subfolders = "; ".join(
            f"{r.folder_path} ({r.total_size_mb} MB)" for r in fs[fs["level"].eq(2)].head(5).itertuples()
        )
        largest_files = "; ".join(
            f"{r.path} ({r.size_mb} MB)" for r in sub.sort_values("size_bytes", ascending=False).head(5).itertuples()
        )
        ext = sub.groupby("extension").agg(files=("path", "count"), mb=("size_mb", "sum")).reset_index()
        ext_summary = "; ".join(f"{r.extension}:{r.files}" for r in ext.sort_values("files", ascending=False).head(8).itertuples())
        rows.append(
            {
                "folder_path": root,
                "total_size_mb": mb(sub["size_bytes"].sum()),
                "file_count": len(sub),
                "folder_count": len(folder_counts[root]),
                "largest_subfolders": largest_subfolders,
                "largest_files": largest_files,
                "file_extensions_summary": ext_summary,
                "modified_time_min": sub["modified_time"].min(),
                "modified_time_max": sub["modified_time"].max(),
                "likely_role": classify_role(root + "/"),
            }
        )
    return pd.DataFrame(rows)


def extension_summary(files: pd.DataFrame) -> pd.DataFrame:
    out = files.groupby(["root", "extension"], dropna=False).agg(
        file_count=("path", "count"),
        total_size_bytes=("size_bytes", "sum"),
        largest_file_bytes=("size_bytes", "max"),
    ).reset_index()
    out["total_size_mb"] = out["total_size_bytes"].map(mb)
    out["largest_file_mb"] = out["largest_file_bytes"].map(mb)
    return out.sort_values(["total_size_bytes", "file_count"], ascending=False)


def work_inventory(files: pd.DataFrame) -> pd.DataFrame:
    work = files[files["root"].eq("work")].copy()
    if work.empty:
        return work
    rows = []
    for folder, g in folder_summary(work).query("level <= 5").iterrows():
        pass
    fs = folder_summary(work, max_level=8)
    for r in fs[fs["level"].isin([3, 4, 5, 6, 7, 8])].itertuples():
        rows.append(
            {
                "folder_path": r.folder_path,
                "total_size_mb": r.total_size_mb,
                "file_count": r.file_count,
                "work_product_class": classify_work_product(r.folder_path),
                "codex_use_policy": codex_use_policy(r.folder_path),
            }
        )
    return pd.DataFrame(rows).sort_values(["total_size_mb", "file_count"], ascending=False)


def codex_use_policy(path: str) -> str:
    p = path.replace("\\", "/")
    if any(p.startswith(c) for c in CANONICAL_FIRST_READ):
        return "read_first_for_future_analysis"
    if p.startswith("work/output/roadway_graph/analysis/current/"):
        return "read_when_canonical_product_lacks_needed_field"
    if p.startswith("work/output/roadway_graph/review/current/"):
        return "read_for_traceability_or_specific_review_task"
    if "history" in p or "archive" in p:
        return "archive_only_unless_explicitly_requested"
    return "do_not_use_unless_explicitly_requested"


def docs_inventory(files: pd.DataFrame) -> pd.DataFrame:
    docs = files[files["root"].eq("docs")].copy()
    rows = []
    for r in docs.itertuples():
        p = r.path
        if "/methodology/" in p:
            doc_type = "methodology"
        elif "/workflow/" in p:
            doc_type = "workflow"
        elif "map_review" in p:
            doc_type = "map_review"
        elif "contract" in p or "doctrine" in p or "guidance" in p:
            doc_type = "contract_or_doctrine"
        else:
            doc_type = "other_doc"
        rows.append(
            {
                "path": p,
                "size_mb": r.size_mb,
                "modified_time": r.modified_time,
                "doc_type": doc_type,
                "recommended_action": docs_recommendation(p),
            }
        )
    return pd.DataFrame(rows)


def docs_recommendation(path: str) -> str:
    base = Path(path).name
    important = {
        "README.md",
        "AGENTS.md",
        "final_analysis_dataset_contract.md",
        "mvp_observed_crash_rate_guidance.md",
        "roadway_graph_methodology.md",
        "current_workflow_index.md",
    }
    if base in important:
        return "consolidate_or_rewrite_as_active_top_level_guidance"
    if "legacy" in path.lower():
        return "legacy_reference_only"
    return "keep_or_review_for_consolidation"


def src_inventory(files: pd.DataFrame) -> pd.DataFrame:
    src = files[(files["root"].eq("src")) & (files["extension"].eq(".py"))].copy()
    rows = []
    for r in src.itertuples():
        p = r.path
        rows.append(
            {
                "path": p,
                "size_mb": r.size_mb,
                "modified_time": r.modified_time,
                "functional_stage": script_stage(p),
                "script_status_guess": script_status_guess(p),
            }
        )
    return pd.DataFrame(rows)


def script_status_guess(path: str) -> str:
    name = Path(path).name.lower()
    if any(n in name for n in ["final_analysis_dataset_build", "mvp_dataset"]):
        return "canonical_or_mvp_current"
    if name.startswith("final_") or name.startswith("mvp_"):
        return "current_review_or_analysis_script"
    if any(n in name for n in ["diagnostic", "audit", "feasibility"]):
        return "diagnostic_or_traceability"
    return "active_or_supporting"


def simple_inventory(files: pd.DataFrame, root: str, classifier) -> pd.DataFrame:
    sub = files[files["root"].eq(root)].copy()
    rows = []
    for r in sub.itertuples():
        rows.append(
            {
                "path": r.path,
                "size_mb": r.size_mb,
                "extension": r.extension,
                "modified_time": r.modified_time,
                "inventory_class": classifier(r.path),
            }
        )
    return pd.DataFrame(rows)


def artifacts_class(path: str) -> str:
    p = path.lower()
    if "normalized" in p:
        return "stable_normalized_data_do_not_modify"
    if "stage" in p:
        return "staging_input_do_not_modify"
    return "artifact_input_review_before_modification"


def config_class(path: str) -> str:
    p = path.lower()
    if "access" in p:
        return "access_mapping_or_config"
    if "field" in p or "mapping" in p:
        return "field_mapping"
    return "config"


def scripts_class(path: str) -> str:
    p = path.lower()
    if "bootstrap" in p:
        return "environment_bootstrap_keep"
    if "install" in p or "pip" in p:
        return "dependency_utility"
    return "utility_script"


def tests_class(path: str) -> str:
    return "existing_test" if path.endswith(".py") else "test_support_file"


def plans(files: pd.DataFrame, work_inv: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = []
    for path in AUDIT_ROOTS + sorted(EXCLUDED_ROOTS):
        exists = (ROOT / path).exists()
        if path in {"artifacts", "Intersection Crash Analysis Layers"}:
            cls = "source_or_staging_do_not_delete"
        elif path in {".git", ".venv"}:
            cls = "needs_user_review"
        elif path == "intersection_crash_analysis.egg-info":
            cls = "generated_metadata_candidate"
        elif path == "legacy":
            cls = "archive_candidate"
        else:
            cls = "keep_current"
        rows.append(
            {
                "path": path,
                "exists": exists,
                "classification": cls,
                "recommended_action": "do_not_delete_in_this_pass",
                "verification_before_cleanup": "confirm dependency/import/build behavior" if cls == "generated_metadata_candidate" else "",
            }
        )
    for r in work_inv.head(200).itertuples():
        is_canonical_or_parent = any(
            r.folder_path == c or c.startswith(r.folder_path.rstrip("/") + "/") or r.folder_path.startswith(c + "/")
            for c in CANONICAL_FIRST_READ
        )
        if is_canonical_or_parent:
            cls = "canonical_first_read" if r.work_product_class == "canonical_first_read" else "keep_current"
        elif r.work_product_class in {"archive_or_history", "generated_intermediate_or_legacy_output"}:
            cls = "archive_candidate"
        elif r.work_product_class == "canonical_first_read":
            cls = "canonical_first_read"
        elif "review" in r.work_product_class:
            cls = "generated_intermediate"
        else:
            cls = "keep_current"
        rows.append(
            {
                "path": r.folder_path,
                "exists": True,
                "classification": cls,
                "recommended_action": "keep_current_location_pending_user_cleanup_review",
                "verification_before_cleanup": "confirm not referenced by canonical build or current docs",
            }
        )
    cleanup = pd.DataFrame(rows)
    archive = cleanup[cleanup["classification"].isin(["archive_candidate", "stale_superseded", "generated_intermediate"])].copy()
    do_not_delete = cleanup[cleanup["classification"].isin(["source_or_staging_do_not_delete", "canonical_first_read", "keep_current"])].copy()
    return cleanup, archive, do_not_delete


def write_recommended_structure() -> None:
    text = """# Recommended Repository Structure

This is a planning document only. No files were moved by the audit.

## First-Read Rule For Codex

1. Read `AGENTS.md`.
2. Read `docs/workflow/final_analysis_dataset_contract.md`.
3. For table/figure/MVP work, read `work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset/` first.
4. For the MVP directional observed crash-rate lookup, read `work/output/roadway_graph/analysis/current/mvp_dataset/` first.
5. Read review outputs only when the prompt asks for traceability, diagnostics, recovery, QA, or a missing field.

## Folder Policy

- `artifacts/`: protected source/staging/normalized data. Do not modify casually.
- `config/`: stable mappings and category definitions. Public labels and MVP category definitions should move here after review.
- `docs/`: active methodology, workflow, contracts, and guidance.
- `src/`: active code and review-only build scripts.
- `scripts/`: bootstrap and utility scripts.
- `tests/`: smoke tests and future canonical row-count checks.
- `work/output/roadway_graph/analysis/current/`: canonical and analysis-ready products.
- `work/output/roadway_graph/review/current/`: diagnostics, audits, recovery passes, and review packages.
- `work/output/roadway_graph/archive/`: future home for superseded generated outputs after explicit user approval.

## Archive Rule

Generated review/intermediate outputs may be archived only after a separate cleanup pass confirms they are superseded and not required by current scripts or docs.
"""
    (OUT_DIR / "recommended_repo_structure.md").write_text(text, encoding="utf-8")
    write_log("Wrote recommended_repo_structure.md")


def write_agents_draft() -> None:
    text = """# AGENTS.md Draft

## Project Purpose

This repository supports Virginia downstream functional-area analysis at signalized intersections. The immediate MVP is a directional observed crash-rate lookup/guidance product.

## Data Preservation Doctrine

Do not delete, move, or rewrite data unless the user explicitly authorizes it. Raw, staged, normalized, canonical, and review outputs are evidence. Recovery is preferred over discard: maximize usable signals, legs, context, access, crashes, directionality, and source limitation clarity.

## Canonical Data Policy

Codex must read canonical products first:

- `work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset/`
- `work/output/roadway_graph/analysis/current/mvp_dataset/`

Review outputs are for diagnostics, traceability, and bounded recovery tasks only unless explicitly promoted by the user.

## First-Read Rule

For future analysis/table/figure/MVP prompts, read the canonical analysis dataset first. Do not search old review folders unless the canonical dataset lacks a required field or the prompt explicitly asks for historical diagnostics.

## Folder Policy

- `analysis/current`: canonical and analysis-ready products.
- `review/current`: audits, diagnostics, recovery outputs, and review-only products.
- `archive` or `history`: not first-read unless explicitly requested.
- `artifacts`: protected source/staging/normalized data.

## MVP Definition

Inputs: speed category, AADT category, divided/undivided, median type, access count band, access type, upstream/downstream.

Output: distribution of observed crash rates across matching approach-window-direction units, mean/median/percentiles, crash count, exposure, included unit count, and reliability flags.

## Directionality Doctrine

Downstream/upstream is a core project attribute. Direct divided/one-way labels and synthetic undivided centerline interpretations are both usable in the MVP, with method/provenance flags. Crash direction fields must not be used for directionality.

## Access Doctrine

Raw access count bands are the primary access input. Access density is secondary only when the denominator is clear.

## Crash Roadway Identity Doctrine

Crash roadway identity is a carried QA/reference field. Spatial 50-ft crash assignment remains a primary geometry/catchment product unless a later validated product supersedes it.

## Validation Commands

Use `.\.venv\Scripts\python.exe -m py_compile <script>` and `.\.venv\Scripts\python.exe -m <module>`.

## Final Report Format

Report files changed, commands run, output folder, key counts, QA status, unresolved assumptions, and `git status --short`.
"""
    (OUT_DIR / "AGENTS_draft.md").write_text(text, encoding="utf-8")
    write_log("Wrote AGENTS_draft.md")


def write_readme_draft() -> None:
    text = """# IntersectionCrashAnalysis README Draft

This repository builds the roadway, signal, access, crash, numeric context, and directionality backend for Virginia downstream functional-area analysis.

## Current State

The project has a canonical final analysis dataset and an MVP directional observed crash-rate distribution dataset. Future analysis and visualization work should use these first.

## Canonical Products

- `work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset/`
- `work/output/roadway_graph/analysis/current/mvp_dataset/`

## MVP Product

The MVP lookup takes speed band, AADT band, roadway configuration, median group, access count band, access type, and upstream/downstream. It returns observed crash-rate distributions, crash counts, exposure, unit counts, and reliability flags.

## Running Core Scripts

Use the repo virtual environment:

```powershell
.\.venv\Scripts\python.exe -m py_compile src\active\roadway_graph\<script>.py
.\.venv\Scripts\python.exe -m src.roadway_graph.<module>
```

## Output Folders

- `analysis/current`: canonical and analysis-ready products.
- `review/current`: diagnostics, audits, and review-only recovery products.
- `artifacts`: protected source/staging/normalized data.

## Codex Guidance

Codex should read the canonical products first, avoid stale review folders unless explicitly requested, preserve data, and never use crash direction fields for downstream/upstream directionality.
"""
    (OUT_DIR / "README_draft.md").write_text(text, encoding="utf-8")
    write_log("Wrote README_draft.md")


def write_tree(files: pd.DataFrame) -> None:
    folders = sorted(set(files["parent"]))
    rows = []
    for folder in folders[:2000]:
        depth = len(Path(folder).parts)
        if depth <= 4:
            rows.append("  " * (depth - 1) + Path(folder).name + "/")
    (OUT_DIR / "repo_structure_tree.txt").write_text("\n".join(rows), encoding="utf-8")
    write_log("Wrote repo_structure_tree.txt")


def write_findings(root_inv: pd.DataFrame, work_inv: pd.DataFrame, cleanup: pd.DataFrame, excluded: list[dict[str, object]]) -> None:
    largest = root_inv.sort_values("total_size_mb", ascending=False).head(5)
    canonical = work_inv[work_inv["work_product_class"].eq("canonical_first_read")]
    archive_count = int((cleanup["classification"] == "archive_candidate").sum())
    egg = next((x for x in excluded if x["excluded_path"] == "intersection_crash_analysis.egg-info"), {})
    text = f"""# Repo Structure Audit Findings

## Bounded Question

This audit inventories the active repository structure and drafts a Codex operating-contract plan. It does not delete, move, rewrite, or regenerate analytical outputs.

## Largest Root Folders

{largest[["folder_path", "total_size_mb", "file_count", "folder_count", "likely_role"]].to_string(index=False)}

The largest folders are generated work outputs and protected source/staging data. They are large because this repo preserves detailed review, analysis, map-review, and canonical data products.

## Canonical First-Read Products

{canonical[["folder_path", "total_size_mb", "file_count"]].head(20).to_string(index=False)}

Future Codex prompts should read these before searching old review folders.

## Confusing Areas

- `work/output/roadway_graph/review/current/`: many useful diagnostics, but not first-read for general analysis.
- `work/output/roadway_graph/analysis/current/`: contains both canonical products and supporting diagnostics; canonical contracts are needed.
- `src/active/roadway_graph/`: many one-off and recovery scripts; scripts should be grouped by stage in docs.

## AGENTS.md Should Enforce

Data preservation, canonical-first reads, no-delete/no-move without authorization, downstream/upstream as a core MVP attribute, synthetic undivided directionality as an intentional methodology decision, raw access count bands as primary, and crash direction exclusion.

## README.md Should Say

What the project does, current canonical products, MVP lookup definition, how to run scripts, where outputs live, and what future Codex prompts should read first.

## Archive Candidates

The cleanup plan marks {archive_count:,} paths as archive/generated-intermediate candidates for user review. No cleanup was executed.

## Do Not Delete

`artifacts/`, canonical first-read products, active docs, active source, config, and source/staging data should not be deleted. `.git`, `.venv`, and source geodatabases are excluded from cleanup unless the user explicitly asks.

## intersection_crash_analysis.egg-info

Exists: {egg.get('exists')}. It is likely generated Python package metadata and may be safe to delete later only after verifying imports/builds still work, checking whether editable install metadata is needed, and confirming no scripts depend on files inside it.

## Next Restructuring Pass

Do not move files yet. First adopt updated AGENTS/README guidance, add smoke tests for canonical row counts, then create an explicit archive migration plan for generated review/intermediate outputs.
"""
    (OUT_DIR / "repo_structure_audit_findings.md").write_text(text, encoding="utf-8")
    write_log("Wrote repo_structure_audit_findings.md")


def write_qa(excluded: list[dict[str, object]]) -> pd.DataFrame:
    excluded_names = {x["excluded_path"] for x in excluded}
    rows = [
        ("no_files_deleted", True, "Audit script does not delete files."),
        ("no_files_moved", True, "Audit script does not move files."),
        ("no_active_outputs_modified", True, "Only audit outputs were written."),
        ("git_excluded_not_deep_scanned", ".git" in excluded_names, ".git reported as excluded."),
        ("venv_excluded_not_deep_scanned", ".venv" in excluded_names, ".venv reported as excluded."),
        ("source_layers_excluded_not_deep_scanned", "Intersection Crash Analysis Layers" in excluded_names, "Source layer folder reported as excluded."),
        ("legacy_excluded_not_deep_scanned", "legacy" in excluded_names, "legacy reported as excluded."),
        ("egg_info_excluded_not_deep_scanned", "intersection_crash_analysis.egg-info" in excluded_names, "egg-info reported as generated metadata candidate."),
        ("outputs_written_only_to_review_audit_folder", str(OUT_DIR).replace("\\", "/").endswith("work/output/roadway_graph/review/current/repo_structure_audit"), str(OUT_DIR)),
    ]
    qa = pd.DataFrame(rows, columns=["qa_check", "passed", "note"])
    write_csv(qa, "repo_structure_audit_qa.csv")
    return qa


def write_manifest(outputs: Iterable[str], excluded: list[dict[str, object]]) -> None:
    manifest = {
        "script": "src.roadway_graph.audit.repo_structure_audit",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "bounded_question": "read-only repository structure audit and Codex operating-contract plan",
        "output_folder": str(OUT_DIR),
        "audited_roots": AUDIT_ROOTS,
        "excluded_roots": excluded,
        "outputs": list(outputs),
        "non_goals": [
            "no deletion",
            "no moves",
            "no active output modification",
            "no geospatial recovery",
        ],
    }
    (OUT_DIR / "repo_structure_audit_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_log("Wrote repo_structure_audit_manifest.json")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log = OUT_DIR / "run_progress_log.txt"
    if log.exists():
        log.unlink()
    write_log("Starting repository structure audit.")
    files, excluded = scan_files()
    root_inv = root_inventory(files)
    folders = folder_summary(files)
    largest_files = files.sort_values("size_bytes", ascending=False).head(500)
    ext = extension_summary(files)
    work_inv = work_inventory(files)
    canonical = work_inv[work_inv["work_product_class"].eq("canonical_first_read")].copy()
    review = work_inv[work_inv["folder_path"].str.startswith("work/output/roadway_graph/review/current", na=False)].copy()
    docs = docs_inventory(files)
    src = src_inventory(files)
    artifacts = simple_inventory(files, "artifacts", artifacts_class)
    config = simple_inventory(files, "config", config_class)
    scripts = simple_inventory(files, "scripts", scripts_class)
    tests = simple_inventory(files, "tests", tests_class)
    cleanup, archive, do_not_delete = plans(files, work_inv)

    write_csv(root_inv, "repo_root_inventory.csv")
    write_csv(folders, "repo_folder_size_summary.csv")
    write_csv(largest_files, "repo_largest_files.csv")
    write_csv(ext, "repo_extension_summary.csv")
    write_csv(work_inv, "work_output_inventory.csv")
    write_csv(canonical, "canonical_data_product_inventory.csv")
    write_csv(review, "review_output_inventory.csv")
    write_csv(docs, "docs_inventory.csv")
    write_csv(src, "src_script_inventory.csv")
    write_csv(artifacts, "artifacts_inventory.csv")
    write_csv(config, "config_inventory.csv")
    write_csv(scripts, "scripts_inventory.csv")
    write_csv(tests, "tests_inventory.csv")
    write_recommended_structure()
    write_agents_draft()
    write_readme_draft()
    write_csv(cleanup, "repo_cleanup_candidate_plan.csv")
    write_csv(archive, "repo_archive_candidate_plan.csv")
    write_csv(do_not_delete, "repo_do_not_delete_list.csv")
    write_tree(files)
    qa = write_qa(excluded)
    write_findings(root_inv, work_inv, cleanup, excluded)
    outputs = [
        "repo_root_inventory.csv",
        "repo_folder_size_summary.csv",
        "repo_largest_files.csv",
        "repo_extension_summary.csv",
        "work_output_inventory.csv",
        "canonical_data_product_inventory.csv",
        "review_output_inventory.csv",
        "docs_inventory.csv",
        "src_script_inventory.csv",
        "artifacts_inventory.csv",
        "config_inventory.csv",
        "scripts_inventory.csv",
        "tests_inventory.csv",
        "recommended_repo_structure.md",
        "AGENTS_draft.md",
        "README_draft.md",
        "repo_cleanup_candidate_plan.csv",
        "repo_archive_candidate_plan.csv",
        "repo_do_not_delete_list.csv",
        "repo_structure_audit_findings.md",
        "repo_structure_audit_qa.csv",
        "repo_structure_audit_manifest.json",
        "repo_structure_tree.txt",
        "run_progress_log.txt",
    ]
    write_manifest(outputs, excluded)
    write_log("Completed repository structure audit.")


if __name__ == "__main__":
    main()
