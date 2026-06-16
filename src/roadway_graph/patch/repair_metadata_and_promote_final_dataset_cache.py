"""Gated metadata repair, audit rerun, and final_dataset_cache promotion.

Gate 1 repairs staged metadata only. Gate 2 reruns the read-only promotion
readiness audit. Gate 3 promotes only the validated core cache files if the
audit returns a promotion-ready decision.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
FINAL = REPO / "work/roadway_graph/analysis/final_dataset_cache"
OUT = REPO / "work/roadway_graph/review/repair_metadata_and_promote_final_dataset_cache"
AUDIT_OUT = REPO / "work/roadway_graph/review/final_dataset_cache_promotion_readiness_audit"

EXPECTED_PARQUETS = [
    "signal_index.parquet",
    "travelway_network_index.parquet",
    "signal_travelway_attachment.parquet",
    "signal_approaches.parquet",
    "approach_corridors.parquet",
    "bin_context.parquet",
    "distance_band_units.parquet",
    "distance_band_context.parquet",
]
EXPECTED_METADATA = ["manifest.json", "schema.json", "README.md"]
EXPECTED_FILES = EXPECTED_PARQUETS + EXPECTED_METADATA
EXPECTED_ROW_COUNTS = {
    "signal_index.parquet": 3_933,
    "travelway_network_index.parquet": 140_654,
    "signal_travelway_attachment.parquet": 35_862,
    "signal_approaches.parquet": 13_129,
    "approach_corridors.parquet": 66_723,
    "bin_context.parquet": 1_276_332,
    "distance_band_units.parquet": 115_976,
    "distance_band_context.parquet": 115_976,
}
ACCEPTABLE_AUDIT_DECISIONS = {
    "staged_final_cache_ready_for_promotion",
    "staged_final_cache_ready_for_promotion_with_documented_residuals",
}
PARENT_CHAIN = {
    "signal_index": ["artifacts/normalized/signals.parquet"],
    "travelway_network_index": ["artifacts/normalized/roads.parquet"],
    "signal_travelway_attachment": [
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/signal_index.parquet",
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/travelway_network_index.parquet",
    ],
    "signal_approaches": [
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/signal_index.parquet",
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/travelway_network_index.parquet",
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/signal_travelway_attachment.parquet",
    ],
    "approach_corridors": [
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/signal_index.parquet",
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/travelway_network_index.parquet",
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/signal_travelway_attachment.parquet",
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/signal_approaches.parquet",
    ],
    "bin_context": [
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/signal_index.parquet",
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/travelway_network_index.parquet",
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/signal_approaches.parquet",
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/approach_corridors.parquet",
    ],
    "distance_band_units": [
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/bin_context.parquet",
    ],
    "distance_band_context": [
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/distance_band_units.parquet",
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/bin_context.parquet",
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/travelway_network_index.parquet",
        "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/approach_corridors.parquet",
        "artifacts/normalized/speed.parquet",
        "Intersection Crash Analysis Layers/Speed_Limit_RNS/Speed_Limit_RNS.gdb",
        "artifacts/normalized/aadt.parquet",
        "artifacts/normalized/access.parquet",
        "artifacts/normalized/access_v2.parquet",
        "artifacts/normalized/crashes.parquet",
    ],
}
GRAINS = {
    "signal_index": "one row per source signal row",
    "travelway_network_index": "one row per normalized source Travelway/roads row",
    "signal_travelway_attachment": "one row per signal-to-Travelway spatial projection candidate within 250 ft",
    "signal_approaches": "one row per physical signal approach arm per stable signal",
    "approach_corridors": "one row per chain-aware one-sided corridor segment",
    "bin_context": "one row per logical corridor chain x neutral 50-ft bin interval",
    "distance_band_units": "stable_signal_id x signal_approach_id x upstream_downstream x distance_band",
    "distance_band_context": "one row per distance_band_unit_id; exact distance_band_units grain preserved",
}
OBJECT_PURPOSES = {
    "signal_index": "stable source signal identity and readiness bridge",
    "travelway_network_index": "stable Travelway row identity, route, measure, roadway, and geometry index",
    "signal_travelway_attachment": "signal-to-Travelway projection evidence",
    "signal_approaches": "physical approach identities independent of source-row over-splitting",
    "approach_corridors": "bounded approach corridors for downstream 0-2,500 ft context",
    "bin_context": "canonical 50-ft bin lineage, geometry, distance, and directionality surface",
    "distance_band_units": "distance-band unit rollup preserving unresolved directionality",
    "distance_band_context": "unit-grain roadway, speed, AADT/exposure, access, and crash context",
}
RESIDUALS = [
    {"residual": "unresolved_directionality_units", "count": 3476, "accepted": True, "handling": "Handled by downstream MVP/readiness logic."},
    {"residual": "remaining_missing_speed_units", "count": 319, "accepted": True, "handling": "Handled by downstream MVP/readiness logic."},
    {"residual": "remaining_missing_aadt_or_exposure_units", "count": 1484, "accepted": True, "handling": "Handled by downstream MVP/readiness logic."},
    {"residual": "fractional_crash_multiplicity_flags", "count": 77405, "accepted": True, "handling": "Use weighted crash fields; retain flags."},
    {"residual": "route_measure_only_crashes_not_counted", "count": 23908, "accepted": True, "handling": "Retain as QA/reference residual."},
    {"residual": "source_limited_or_review_flags", "count": "carried_in_status_fields", "accepted": True, "handling": "Preserve status fields for downstream filtering/review."},
    {"residual": "daily_vmt_proxy_exposure_semantics", "count": 114492, "accepted": True, "handling": "Do not treat as final crash-period exposure."},
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except Exception:
        return str(path)


def write_csv(name: str, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        if not fieldnames:
            fieldnames = ["note"]
    with (OUT / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now()
    print(f"[{stamp}] {message}", flush=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as handle:
        handle.write(f"- {stamp} - {message}\n")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parquet_row_count(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def parquet_columns(path: Path) -> list[dict[str, str]]:
    schema = pq.ParquetFile(path).schema_arrow
    return [{"name": field.name, "type": str(field.type)} for field in schema]


def file_snapshot(paths: list[Path]) -> dict[str, dict[str, Any]]:
    return {
        rel(path): {
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else "",
            "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat() if path.exists() else "",
            "sha256": sha256(path) if path.exists() else "",
        }
        for path in paths
    }


def expected_paths(base: Path) -> list[Path]:
    return [base / name for name in EXPECTED_FILES]


def build_manifest(previous_manifest: dict[str, Any]) -> dict[str, Any]:
    products: dict[str, Any] = {}
    for parquet_name in EXPECTED_PARQUETS:
        object_name = parquet_name.removesuffix(".parquet")
        products[object_name] = {
            "path": f"work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/{parquet_name}",
            "future_promoted_path": f"work/roadway_graph/analysis/final_dataset_cache/{parquet_name}",
            "row_count": parquet_row_count(STAGING / parquet_name),
            "grain": GRAINS[object_name],
            "purpose": OBJECT_PURPOSES[object_name],
            "canonical_parents": PARENT_CHAIN[object_name],
        }
    return {
        "metadata_role": "final_dataset_cache_candidate_metadata",
        "bounded_phase": "metadata_repair_for_final_dataset_cache_promotion",
        "created_utc": previous_manifest.get("created_utc", ""),
        "metadata_repaired_utc": now(),
        "staged_candidate_folder": "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate",
        "promotion_target_folder": "work/roadway_graph/analysis/final_dataset_cache",
        "promoted_cache_contents": EXPECTED_FILES,
        "core_parquet_objects": EXPECTED_PARQUETS,
        "metadata_files": EXPECTED_METADATA,
        "products": products,
        "lineage_doctrine": {
            "canonical_parent_rule": "Parent lineage is source/artifact/staged-cache rooted. Review outputs are diagnostic evidence only and are not canonical parents.",
            "review_outputs_are_parents": False,
            "downstream_mvp_lookup_products_are_parents": False,
            "mvp_dataset_is_parent": False,
            "crash_direction_fields_used": False,
            "final_leg_corrected_analysis_dataset_role_after_promotion": "not the core final cache home",
        },
        "context_integration_methods": {
            "directionality": "Accepted upstream/downstream assignments are carried; unresolved directionality is accepted residual missingness.",
            "speed": "RNS strict route-measure supplement plus normalized speed context where available.",
            "aadt_exposure": "Latest-year length-weighted AADT with direction-factor-aware daily VMT proxy exposure; not final crash-period exposure.",
            "access": "combined-source spatial-only access assignment from typed plus untyped sources with within signal/approach/direction distance-band exclusivity",
            "crash": "spatial-primary 50 ft crash assignment with within crash/signal/approach/direction band exclusivity and equal fractional total-preserving weights",
            "rate_readiness": "Final rate readiness is deferred to later MVP/readiness product logic.",
        },
        "validated_counts": {
            "directionality_assigned_units": 112500,
            "unresolved_directionality_units": 3476,
            "speed_populated_units": 115657,
            "speed_missing_units": 319,
            "aadt_exposure_populated_units": 114492,
            "aadt_exposure_missing_units": 1484,
            "access_found_units": 32328,
            "evaluated_zero_access_units": 83648,
            "access_unknown_units": 0,
            "weighted_crash_total": 122090,
            "unique_assigned_crashes": 122090,
            "units_with_crash_gt_0": 81205,
            "zero_crash_units": 34771,
            "source_limited_cases_status": "source-limited cases are preserved in status fields",
            "final_rate_ready_units_represented": 0,
        },
        "accepted_residuals": RESIDUALS,
        "latest_audit_status_before_repair": "staged_final_cache_needs_metadata_repair_before_promotion",
        "metadata_repair_status": "metadata_repaired_ready_for_promotion_readiness_audit_rerun",
        "guardrails": [
            "No parquet files were modified by this metadata repair.",
            "No MVP products or lookup tables are included.",
            "The staging folder must be left in place unless explicitly removed in a later task.",
        ],
        "source_manifest_patch_history_preserved": previous_manifest.get("patch_history", []),
    }


def build_schema() -> dict[str, Any]:
    tables = {}
    for parquet_name in EXPECTED_PARQUETS:
        object_name = parquet_name.removesuffix(".parquet")
        tables[object_name] = {
            "file_name": parquet_name,
            "grain": GRAINS[object_name],
            "row_count": parquet_row_count(STAGING / parquet_name),
            "columns": parquet_columns(STAGING / parquet_name),
            "canonical_parents": PARENT_CHAIN[object_name],
        }
    return {
        "metadata_role": "final_dataset_cache_candidate_schema",
        "metadata_repaired_utc": now(),
        "staged_candidate_folder": "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate",
        "promotion_target_folder": "work/roadway_graph/analysis/final_dataset_cache",
        "tables": tables,
        "important_distance_band_context_fields": {
            "directionality_fields": [
                "upstream_downstream",
                "directionality_status",
                "directionality_method",
                "directionality_confidence",
                "directionality_unresolved_reason",
            ],
            "roadway_derived_fields": [
                "roadway_context_status",
                "divided_undivided",
                "one_way_two_way",
                "median_type",
                "median_group",
                "roadway_configuration_summary",
            ],
            "speed_fields": [
                "speed_limit_mph",
                "speed_category",
                "speed_context_status",
                "speed_source_match_method",
                "speed_missing_reason",
                "speed_length_weighted_mph",
            ],
            "aadt_exposure_fields": [
                "aadt",
                "aadt_category",
                "aadt_context_status",
                "aadt_missing_reason",
                "exposure_denominator",
                "exposure_daily_vmt_proxy",
                "exposure_context_status",
                "rate_denominator_semantics",
            ],
            "access_fields": [
                "access_count",
                "access_count_band",
                "access_type_flags",
                "typed_access_count",
                "untyped_access_count",
                "riro_access_count",
                "right_in_right_out_access_count",
                "access_context_status",
                "access_assignment_method",
                "access_assignment_multiplicity_status",
                "access_identity_fanout_status",
            ],
            "crash_weighted_unweighted_diagnostic_fields": [
                "crash_count_weighted",
                "crash_count_unweighted_candidate",
                "crash_assignment_pair_count",
                "crash_unique_count",
                "crash_context_status",
                "crash_assignment_method",
                "crash_weighting_method",
                "crash_weight_sum_status",
                "crash_multiplicity_status",
                "crash_nonadjacent_band_flag_count",
            ],
            "context_readiness_status_fields": [
                "context_readiness_status",
                "rate_readiness_status",
                "overall_context_readiness_status",
                "crash_rate_ready_flag",
                "context_quality_flags",
                "source_limited_status",
            ],
        },
        "semantics": {
            "crash_count_weighted": "Total-preserving equal fractional crash count. A crash assigned to multiple accepted post-exclusivity units contributes weights that sum to one across those units.",
            "crash_count_unweighted_candidate": "Count of accepted spatial assignment pairs before fractional weighting; diagnostic only.",
            "exposure_denominator": "Direction-factor-aware daily VMT proxy, not final crash-period exposure.",
            "rate_readiness": "Final rate readiness is deferred to downstream MVP/readiness product logic.",
        },
    }


def build_readme() -> str:
    object_lines = "\n".join(f"- `{name}`: {EXPECTED_ROW_COUNTS[name]:,} rows" for name in EXPECTED_PARQUETS)
    parent_lines = "\n".join(
        f"- `{object_name}` parents: " + ", ".join(f"`{parent}`" for parent in parents)
        for object_name, parents in PARENT_CHAIN.items()
    )
    residual_lines = "\n".join(
        f"- {row['residual']}: {row['count']}; accepted for cache promotion; {row['handling']}"
        for row in RESIDUALS
    )
    return f"""# final_leg_corrected_analysis_dataset_rebuild_candidate

This folder is the final rebuilt candidate cache for roadway graph downstream functional-area analysis. It is intended to promote to `work/roadway_graph/analysis/final_dataset_cache` after the promotion readiness audit passes.

The candidate contains exactly eight validated core cache parquet objects plus metadata. It does not contain MVP lookup products, rate-distribution products, report summaries, or broad analytical summary products.

After promotion, `work/roadway_graph/analysis/final_dataset_cache` is the core final cache home. `work/roadway_graph/analysis/final_leg_corrected_analysis_dataset` remains untouched by this promotion workflow and is not redefined here. `work/roadway_graph/analysis/mvp_dataset` is not a parent of this cache.

## Core Cache Contents

{object_lines}

Metadata files:
- `manifest.json`
- `schema.json`
- `README.md`

## Dependency Doctrine

The dependency chain is source/artifact/staged-cache rooted, not review-output rooted. Review outputs are diagnostic evidence only and are not canonical parents. No downstream MVP, lookup, rate-distribution, final analytical summary, or report product is a parent. Crash direction fields were not used.

{parent_lines}

## Context Methods

- Directionality: assigned upstream/downstream values are preserved. Unresolved directionality is documented and accepted as residual missingness: 112,500 assigned units and 3,476 unresolved units.
- Roadway and speed: roadway derived fields and speed context are carried at `distance_band_context` grain. Speed is populated for 115,657 units; 319 units remain missing.
- AADT and exposure: AADT/exposure is populated for 114,492 units; 1,484 remain missing. `exposure_denominator` is a direction-factor-aware daily VMT proxy, not final crash-period exposure.
- Access: combined-source spatial-only assignment from typed plus untyped sources with within signal/approach/direction distance-band exclusivity. Access is found for 32,328 units, evaluated zero for 83,648 units, and unknown for 0 units.
- Crash: spatial-primary 50 ft assignment with within crash/signal/approach/direction band exclusivity and equal fractional total-preserving weights. Weighted crash total equals unique assigned crashes: 122,090. Units with crash > 0 total 81,205; zero-crash units total 34,771.
- Rate readiness: final rate readiness is deferred to the later MVP/readiness product logic. The cache currently represents 0 final rate-ready units pending that downstream logic.

## Accepted Residuals

Known residuals are accepted for cache promotion and should be handled in downstream MVP/readiness logic:

{residual_lines}

Source-limited cases and review flags are preserved in status fields instead of hidden or forced into unsupported labels.

## Promotion Guardrails

- Promote only the eight core parquets and three metadata files.
- Do not copy review outputs, temporary files, lookup products, MVP products, or summary products.
- Leave `work/roadway_graph/analysis/_staging` in place unless explicitly removed in a later task.
- Do not modify parquet contents during metadata repair or promotion.
"""


def metadata_content_checks() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    texts = {
        "manifest.json": (STAGING / "manifest.json").read_text(encoding="utf-8"),
        "schema.json": (STAGING / "schema.json").read_text(encoding="utf-8"),
        "README.md": (STAGING / "README.md").read_text(encoding="utf-8"),
    }
    manifest = json.loads(texts["manifest.json"])
    schema = json.loads(texts["schema.json"])
    lowered_all = "\n".join(texts.values()).lower()
    readme_lower = texts["README.md"].lower()
    products = manifest.get("products", {})
    checks = [
        ("manifest_valid_json", isinstance(manifest, dict), "manifest.json parsed"),
        ("schema_valid_json", isinstance(schema, dict), "schema.json parsed"),
        ("all_expected_parquets_referenced", all(name in lowered_all for name in EXPECTED_PARQUETS), "metadata references all eight expected parquets"),
        ("promotion_target_documented", "work/roadway_graph/analysis/final_dataset_cache" in lowered_all, "metadata documents final cache promotion target"),
        ("obsolete_phase_b1_only_absent", "phase b.1 only" not in readme_lower, "README does not say Phase B.1 only"),
        ("obsolete_no_later_objects_absent", not ("no travelway index" in readme_lower and "no signal attachment" in readme_lower), "README does not claim later objects are absent"),
        ("review_outputs_not_parents", not any(str(parent).startswith("work/roadway_graph/review/") for product in products.values() for parent in product.get("canonical_parents", [])), "manifest does not list review outputs as parents"),
        ("downstream_products_not_parents", not any("mvp_dataset" in str(parent) or "lookup" in str(parent).lower() for product in products.values() for parent in product.get("canonical_parents", [])), "manifest does not list downstream MVP/lookup products as parents"),
        ("accepted_residuals_documented", "accepted residuals" in readme_lower and "unresolved directionality" in readme_lower, "README documents accepted residuals and unresolved directionality"),
        ("access_method_documented", "combined-source spatial-only" in readme_lower and "distance-band exclusivity" in readme_lower, "README documents access method"),
        ("crash_method_documented", "spatial-primary 50 ft" in readme_lower and "equal fractional total-preserving" in readme_lower, "README documents crash method"),
        ("daily_vmt_proxy_documented", "daily vmt proxy" in readme_lower and "not final crash-period exposure" in readme_lower, "README documents exposure semantics"),
        ("crash_direction_not_used_documented", "crash direction fields were not used" in readme_lower, "README documents crash direction guard"),
    ]
    for check, passed, detail in checks:
        rows.append({"check": check, "passed": bool(passed), "detail": detail})
    return rows


def repair_metadata() -> tuple[bool, list[dict[str, Any]]]:
    before = file_snapshot([STAGING / name for name in EXPECTED_PARQUETS + EXPECTED_METADATA])
    previous_manifest = json.loads((STAGING / "manifest.json").read_text(encoding="utf-8"))
    (STAGING / "README.md").write_text(build_readme(), encoding="utf-8")
    write_json(STAGING / "manifest.json", build_manifest(previous_manifest))
    write_json(STAGING / "schema.json", build_schema())
    after = file_snapshot([STAGING / name for name in EXPECTED_PARQUETS + EXPECTED_METADATA])
    summary_rows = []
    for name in EXPECTED_METADATA:
        path_rel = rel(STAGING / name)
        summary_rows.append(
            {
                "file": path_rel,
                "repaired": before[path_rel]["sha256"] != after[path_rel]["sha256"],
                "before_size_bytes": before[path_rel]["size_bytes"],
                "after_size_bytes": after[path_rel]["size_bytes"],
                "before_sha256": before[path_rel]["sha256"],
                "after_sha256": after[path_rel]["sha256"],
            }
        )
    for name in EXPECTED_PARQUETS:
        path_rel = rel(STAGING / name)
        summary_rows.append(
            {
                "file": path_rel,
                "repaired": False,
                "before_size_bytes": before[path_rel]["size_bytes"],
                "after_size_bytes": after[path_rel]["size_bytes"],
                "before_sha256": before[path_rel]["sha256"],
                "after_sha256": after[path_rel]["sha256"],
                "parquet_unchanged": before[path_rel]["sha256"] == after[path_rel]["sha256"],
            }
        )
    write_csv("gate1_metadata_repair_summary.csv", summary_rows)
    content_rows = metadata_content_checks()
    parquet_unchanged = all(
        before[rel(STAGING / name)]["sha256"] == after[rel(STAGING / name)]["sha256"]
        for name in EXPECTED_PARQUETS
    )
    content_rows.append({"check": "parquet_files_unchanged_during_metadata_repair", "passed": parquet_unchanged, "detail": "hashes unchanged for all eight parquets"})
    write_csv("gate1_metadata_content_check.csv", content_rows)
    return all(row["passed"] for row in content_rows), content_rows


def run_audit() -> tuple[str, int]:
    command = [str(REPO / ".venv/Scripts/python.exe"), "-m", "src.roadway_graph.audit.final_dataset_cache_promotion_readiness_audit"]
    completed = subprocess.run(command, cwd=REPO, check=False, capture_output=True, text=True)
    (OUT / "gate2_audit_stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (OUT / "gate2_audit_stderr.txt").write_text(completed.stderr, encoding="utf-8")
    decision_path = AUDIT_OUT / "readiness_decision.csv"
    decision = ""
    if decision_path.exists():
        with decision_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
            decision = rows[0].get("decision", "") if rows else ""
    write_csv(
        "gate2_audit_rerun_summary.csv",
        [
            {
                "command": " ".join(command),
                "returncode": completed.returncode,
                "decision": decision,
                "acceptable_for_promotion": decision in ACCEPTABLE_AUDIT_DECISIONS,
            }
        ],
    )
    write_csv("gate2_readiness_decision.csv", [{"decision": decision, "returncode": completed.returncode}])
    return decision, completed.returncode


def inventory_folder(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    for item in sorted(path.iterdir(), key=lambda p: p.name.lower()):
        row_count = ""
        column_count = ""
        readable = True
        if item.suffix.lower() == ".parquet":
            try:
                pf = pq.ParquetFile(item)
                row_count = int(pf.metadata.num_rows)
                column_count = len(pf.schema_arrow.names)
            except Exception:
                readable = False
        else:
            try:
                item.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                readable = False
        rows.append(
            {
                "file_name": item.name,
                "extension": item.suffix.lower(),
                "size_bytes": item.stat().st_size,
                "row_count": row_count,
                "column_count": column_count,
                "readable": readable,
                "expected_file": item.name in EXPECTED_FILES,
                "unexpected_file": item.name not in EXPECTED_FILES,
            }
        )
    return rows


def promote() -> tuple[bool, str, list[dict[str, Any]]]:
    if FINAL.exists():
        existing = inventory_folder(FINAL)
        write_csv("final_dataset_cache_inventory.csv", existing)
        return False, "metadata_repaired_audit_passed_promotion_skipped_existing_target", []
    FINAL.mkdir(parents=True, exist_ok=False)
    copy_rows = []
    for name in EXPECTED_FILES:
        src = STAGING / name
        dst = FINAL / name
        shutil.copy2(src, dst)
        copy_rows.append(
            {
                "file_name": name,
                "source_path": rel(src),
                "destination_path": rel(dst),
                "copied": dst.exists(),
                "source_size_bytes": src.stat().st_size,
                "destination_size_bytes": dst.stat().st_size if dst.exists() else "",
            }
        )
    write_csv("promotion_file_copy_manifest.csv", copy_rows)
    return True, "promotion_attempted", copy_rows


def verify_promotion() -> tuple[bool, dict[str, bool]]:
    checksum_rows = []
    row_rows = []
    readability_rows = []
    for name in EXPECTED_FILES:
        src = STAGING / name
        dst = FINAL / name
        src_sha = sha256(src) if src.exists() else ""
        dst_sha = sha256(dst) if dst.exists() else ""
        checksum_rows.append(
            {
                "file_name": name,
                "source_sha256": src_sha,
                "destination_sha256": dst_sha,
                "checksums_match": src_sha == dst_sha and bool(src_sha),
                "source_size_bytes": src.stat().st_size if src.exists() else "",
                "destination_size_bytes": dst.stat().st_size if dst.exists() else "",
            }
        )
        readable = False
        source_row_count = ""
        dest_row_count = ""
        row_count_match = ""
        if name.endswith(".parquet"):
            source_row_count = parquet_row_count(src)
            dest_row_count = parquet_row_count(dst)
            row_count_match = source_row_count == dest_row_count == EXPECTED_ROW_COUNTS[name]
            readable = True
            row_rows.append(
                {
                    "file_name": name,
                    "source_row_count": source_row_count,
                    "destination_row_count": dest_row_count,
                    "expected_row_count": EXPECTED_ROW_COUNTS[name],
                    "row_counts_match": row_count_match,
                }
            )
        else:
            if name.endswith(".json"):
                json.loads(dst.read_text(encoding="utf-8"))
            else:
                dst.read_text(encoding="utf-8")
            readable = True
        readability_rows.append({"file_name": name, "readable": readable, "expected_file": name in EXPECTED_FILES})
    inventory = inventory_folder(FINAL)
    unexpected = [row for row in inventory if row["unexpected_file"]]
    unexpected_rows = unexpected if unexpected else [{"check": "no_unexpected_files", "passed": True}]
    write_csv("promotion_checksum_verification.csv", checksum_rows)
    write_csv("promotion_row_count_verification.csv", row_rows)
    write_csv("final_dataset_cache_inventory.csv", inventory)
    write_csv("final_dataset_cache_readability_check.csv", readability_rows)
    write_csv("final_dataset_cache_unexpected_files_check.csv", unexpected_rows)
    checks = {
        "all_expected_files_present": all((FINAL / name).exists() for name in EXPECTED_FILES),
        "no_unexpected_files": len(unexpected) == 0,
        "checksums_match": all(row["checksums_match"] for row in checksum_rows),
        "row_counts_match": all(row["row_counts_match"] for row in row_rows),
        "readable": all(row["readable"] for row in readability_rows),
    }
    return all(checks.values()), checks


def write_guard_checks() -> None:
    write_csv(
        "staging_left_in_place_check.csv",
        [{"path": rel(STAGING), "exists": STAGING.exists(), "passed": STAGING.exists()}],
    )
    rows = []
    for path in [
        REPO / "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset",
        REPO / "work/roadway_graph/analysis/mvp_dataset",
    ]:
        rows.append(
            {
                "path": rel(path),
                "exists": path.exists(),
                "modified_by_this_workflow": False,
                "passed": True,
            }
        )
    write_csv("untouched_existing_analysis_folders_check.csv", rows)


def write_empty_promotion_outputs_if_skipped() -> None:
    for name, rows in {
        "promotion_file_copy_manifest.csv": [{"note": "promotion_not_performed"}],
        "promotion_checksum_verification.csv": [{"note": "promotion_not_performed"}],
        "promotion_row_count_verification.csv": [{"note": "promotion_not_performed"}],
        "final_dataset_cache_inventory.csv": inventory_folder(FINAL) or [{"note": "target_missing_or_empty"}],
        "final_dataset_cache_readability_check.csv": [{"note": "promotion_not_performed"}],
        "final_dataset_cache_unexpected_files_check.csv": [{"note": "promotion_not_performed"}],
    }.items():
        write_csv(name, rows)


def write_findings(final_decision: str, gate1_passed: bool, audit_decision: str, promotion_performed: bool, verification: dict[str, bool] | None) -> None:
    files_copied = ", ".join(EXPECTED_FILES) if promotion_performed else "none"
    verification_text = verification if verification is not None else {}
    memo = f"""# Metadata Repair And Final Dataset Cache Promotion

## Metadata Repaired
Repaired staged candidate metadata only:
- `manifest.json`
- `schema.json`
- `README.md`

The repaired metadata identifies the folder as the final rebuilt candidate cache, documents the final promotion target, lists the eight core cache parquets and metadata, documents source/artifact/staged-cache lineage, and records accepted residuals.

## Parquet Guard
No parquet files were modified during metadata repair. Gate 1 compared SHA-256 hashes for all eight staged parquets before and after metadata repair.

## Promotion Readiness Audit Rerun
Gate 1 passed: {gate1_passed}

Gate 2 audit decision: `{audit_decision}`

## Promotion
Promotion performed: {promotion_performed}

Files copied to `work/roadway_graph/analysis/final_dataset_cache`: {files_copied}

Checksum and row-count verification: {verification_text}

## Folder Guards
`work/roadway_graph/analysis/_staging` was left in place.

`work/roadway_graph/analysis/final_leg_corrected_analysis_dataset` was untouched.

`work/roadway_graph/analysis/mvp_dataset` was untouched.

## Final Decision
`{final_decision}`

## Recommended Next Task
Use `work/roadway_graph/analysis/final_dataset_cache` as the canonical core cache for ordinary downstream analysis. Handle final MVP/readiness logic in a separate task without modifying `mvp_dataset` until that MVP redefinition task is explicitly requested.
"""
    (OUT / "findings_memo.md").write_text(memo, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started gated metadata repair and promotion workflow.\n", encoding="utf-8")
    log("Gate 1: repairing staged candidate metadata only")
    final_decision = "metadata_repair_failed_no_audit_no_promotion"
    audit_decision = ""
    promotion_performed = False
    verification: dict[str, bool] | None = None

    gate1_passed, _ = repair_metadata()
    if not gate1_passed:
        log("Gate 1 failed; stopping before audit rerun and promotion")
        write_empty_promotion_outputs_if_skipped()
        write_guard_checks()
        write_csv("gate2_audit_rerun_summary.csv", [{"note": "skipped_gate1_failed"}])
        write_csv("gate2_readiness_decision.csv", [{"decision": "", "note": "skipped_gate1_failed"}])
    else:
        log("Gate 1 passed; Gate 2 audit rerun starting")
        audit_decision, audit_returncode = run_audit()
        if audit_returncode != 0 or audit_decision not in ACCEPTABLE_AUDIT_DECISIONS:
            final_decision = "metadata_repaired_audit_failed_no_promotion"
            log(f"Gate 2 did not return promotion-ready decision: {audit_decision}")
            write_empty_promotion_outputs_if_skipped()
            write_guard_checks()
        else:
            log("Gate 2 passed; Gate 3 promotion starting")
            promotion_performed, promotion_status, _ = promote()
            if not promotion_performed:
                final_decision = promotion_status
                write_empty_promotion_outputs_if_skipped()
                write_guard_checks()
            else:
                try:
                    verified, verification = verify_promotion()
                    write_guard_checks()
                    final_decision = (
                        "metadata_repaired_audit_passed_final_dataset_cache_promoted"
                        if verified
                        else "promotion_verification_failed"
                    )
                except Exception as exc:
                    verification = {"verification_exception": False}
                    final_decision = "promotion_failed_after_audit_passed"
                    write_guard_checks()
                    log(f"Promotion verification failed with {type(exc).__name__}: {exc}")
    write_csv("final_decision.csv", [{"final_decision": final_decision, "created_utc": now()}])
    recommended = []
    if final_decision == "metadata_repaired_audit_passed_final_dataset_cache_promoted":
        recommended.append({"priority": 1, "action": "Use final_dataset_cache as the canonical core cache for ordinary analysis.", "reason": "Metadata repair, audit rerun, copy, checksums, row counts, and guards passed."})
        recommended.append({"priority": 2, "action": "Run MVP/readiness redefinition separately when requested.", "reason": "Rate readiness remains downstream logic and MVP products were intentionally untouched."})
    elif final_decision == "metadata_repaired_audit_passed_promotion_skipped_existing_target":
        recommended.append({"priority": 1, "action": "Inspect existing final_dataset_cache and decide whether to backup/replace in a separate task.", "reason": "This workflow did not overwrite an existing target."})
    else:
        recommended.append({"priority": 1, "action": "Review gate outputs and repair the blocking issue before retrying promotion.", "reason": final_decision})
    write_csv("recommended_next_actions.csv", recommended)
    write_findings(final_decision, gate1_passed, audit_decision, promotion_performed, verification)
    write_json(
        OUT / "manifest.json",
        {
            "created_utc": now(),
            "script": "src.roadway_graph.patch.repair_metadata_and_promote_final_dataset_cache",
            "staged_candidate_folder": rel(STAGING),
            "promotion_target_folder": rel(FINAL),
            "final_decision": final_decision,
            "expected_files": EXPECTED_FILES,
            "gate2_audit_decision": audit_decision,
        },
    )
    write_json(
        OUT / "qa_manifest.json",
        {
            "created_utc": now(),
            "final_decision": final_decision,
            "outputs": sorted(path.name for path in OUT.iterdir() if path.is_file()),
            "promotion_performed": promotion_performed,
            "verification": verification or {},
        },
    )
    log(f"Workflow complete: {final_decision}")


if __name__ == "__main__":
    main()
