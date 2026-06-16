"""Read-only roadway_graph cache contract and rebuild plan.

This script writes a review-only planning package. It defines the target cache
contract, rebuild dependency order, object roles, QA gates, zero-data-loss
checks, and promotion criteria. It does not build cache Parquets or mutate
canonical, staged, source, or artifact data.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover - validation environment has pyarrow
    pq = None


REPO_ROOT = Path(__file__).resolve().parents[3]
OUT = REPO_ROOT / "work/roadway_graph/review/cache_contract_and_rebuild_plan"
ANALYSIS = REPO_ROOT / "work/roadway_graph/analysis"
FINAL = ANALYSIS / "final_leg_corrected_analysis_dataset"
STAGING = ANALYSIS / "_staging/final_leg_corrected_analysis_dataset_refresh_candidate"
ART = REPO_ROOT / "artifacts/normalized"


READ_CONTEXT = [
    "AGENTS.md",
    "README.md",
    "work/roadway_graph/_index/CANONICAL_PRODUCTS.md",
    "work/roadway_graph/_index/ACTIVE_REVIEW_PRODUCTS.md",
    "work/roadway_graph/_index/CLEANUP_STATUS.md",
    "docs/methodology/current_methodology_index.md",
    "docs/methodology/overview_methodology.md",
    "docs/methodology/roadway_graph_methodology.md",
    "docs/methodology/proposal_alignment_growth_plan.md",
    "docs/workflow/final_analysis_dataset_contract.md",
    "docs/workflow/roadway_graph_lineage_requirements.md",
    "docs/workflow/signal_identity_requirements.md",
    "docs/workflow/mvp_observed_crash_rate_guidance.md",
    "docs/workflow/access_code_mapping_notes.md",
    "docs/workflow/map_review_workflow.md",
]


SOURCE_ARTIFACTS = [
    "artifacts/normalized/signals.parquet",
    "artifacts/normalized/roads.parquet",
    "artifacts/normalized/speed.parquet",
    "artifacts/normalized/aadt.parquet",
    "artifacts/normalized/access_v2.parquet",
    "artifacts/normalized/crashes.parquet",
]


CURRENT_CACHE_OBJECTS = [
    "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/analysis_signal.csv",
    "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/analysis_bin.csv",
    "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/analysis_signal_window.csv",
    "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/analysis_signal_approach_window.csv",
    "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/analysis_guidance_matrix_long.csv",
    "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate/signal_approaches.parquet",
    "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate/approach_windows.parquet",
    "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate/continuation_corridors.parquet",
    "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate/continuation_provenance.parquet",
    "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate/proposed_generated_bins.parquet",
    "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate/bin_context.parquet",
    "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate/source_signal_travelway_projection_index.parquet",
    "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate/signal_bounded_travelway_corridor_index.parquet",
]


RECENT_REVIEWS = [
    "work/roadway_graph/review/analysis_cache_structural_integrity_audit/",
    "work/roadway_graph/review/network_to_unit_lineage_preservation_audit/",
    "work/roadway_graph/review/source_signal_travelway_projection_index/",
    "work/roadway_graph/review/expanded_directionality_recovery_audit/",
    "work/roadway_graph/review/expanded_bin_universe_impact_audit/",
]


TARGET_OBJECTS = [
    {
        "object_name": "signal_index.parquet",
        "canonical_path": "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/signal_index.parquet",
        "grain": "one row per project signal identity, including analysis-ready and source-limited/holdout source signals",
        "purpose": "Canonical signal identity bridge preserving stable_signal_id, source identifiers, geometry, and analysis/source-limited status.",
        "build_phase": "Phase B",
        "depends_on": "artifacts/normalized/signals.parquet",
        "downstream_consumers": "signal_travelway_attachment; signal_approaches; approach_corridors; bin_context; QA and map-review queues",
    },
    {
        "object_name": "travelway_network_index.parquet",
        "canonical_path": "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/travelway_network_index.parquet",
        "grain": "one row per stable source Travelway geometry/measure interval",
        "purpose": "Canonical Travelway row index with stable row identity, route/measure fields, geometry, and roadway configuration.",
        "build_phase": "Phase B",
        "depends_on": "artifacts/normalized/roads.parquet",
        "downstream_consumers": "signal_travelway_attachment; approach_corridors; bin_context; future context joins",
    },
    {
        "object_name": "signal_travelway_attachment.parquet",
        "canonical_path": "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/signal_travelway_attachment.parquet",
        "grain": "one signal-to-Travelway projection candidate per signal and Travelway row",
        "purpose": "Project source and stable signal geometries to plausible Travelway rows with measure and confidence evidence.",
        "build_phase": "Phase B",
        "depends_on": "signal_index.parquet; travelway_network_index.parquet",
        "downstream_consumers": "signal_approaches; approach_corridors; directionality QA; source-only endpoint boundaries",
    },
    {
        "object_name": "signal_approaches.parquet",
        "canonical_path": "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/signal_approaches.parquet",
        "grain": "one physical signal approach per stable signal and approach identity",
        "purpose": "Represent physical approaches independent of carriageway/source-row over-splitting, preserving route/corridor evidence.",
        "build_phase": "Phase C",
        "depends_on": "signal_index.parquet; signal_travelway_attachment.parquet; travelway_network_index.parquet",
        "downstream_consumers": "approach_corridors; bin_context; distance_band_units; MVP units",
    },
    {
        "object_name": "approach_corridors.parquet",
        "canonical_path": "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/approach_corridors.parquet",
        "grain": "one extended source-rooted corridor segment per signal approach, route/carriageway, and endpoint policy interval",
        "purpose": "Materialize bounded approach corridors with endpoint/source-only boundary support, 2,500-ft clipping, route/measure continuity, and source-limited flags.",
        "build_phase": "Phase C",
        "depends_on": "signal_approaches.parquet; signal_travelway_attachment.parquet; travelway_network_index.parquet",
        "downstream_consumers": "bin_context; directionality; speed/AADT/access/catchment readiness",
    },
    {
        "object_name": "bin_context.parquet",
        "canonical_path": "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/bin_context.parquet",
        "grain": "one 50-ft bin per signal approach/corridor side interval, including real and generated bins with explicit geometry status",
        "purpose": "Canonical bin-level spatial and lineage surface carrying geometry/source-measure interval, approach identity, distance bands, and directionality/status fields.",
        "build_phase": "Phase C and Phase D",
        "depends_on": "approach_corridors.parquet; signal_approaches.parquet; travelway_network_index.parquet",
        "downstream_consumers": "distance_band_units; context enrichment; crash/access assignment; MVP after QA",
    },
    {
        "object_name": "distance_band_units.parquet",
        "canonical_path": "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/distance_band_units.parquet",
        "grain": "stable_signal_id x signal_approach_id x upstream_downstream x distance_band",
        "purpose": "Unit rollup for downstream analysis and MVP readiness after directionality and bin context validation.",
        "build_phase": "Phase D",
        "depends_on": "bin_context.parquet",
        "downstream_consumers": "context enrichment summaries; MVP directional observed crash-rate product; report tables",
    },
]


FIELD_CONTRACTS: dict[str, dict[str, list[str]]] = {
    "signal_index.parquet": {
        "required": ["stable_signal_id", "signal_index_row_id", "geometry", "signal_geometry_hash", "analysis_ready_status"],
        "recommended": ["source_signal_globalid", "source_signal_id", "source_layer", "source_system", "OBJECTID", "ASSET_ID", "REG_SIGNAL_ID", "locality_or_district"],
        "nullable": ["source_signal_globalid", "OBJECTID", "ASSET_ID", "REG_SIGNAL_ID", "source_limited_reason", "holdout_reason"],
        "provenance_status": ["stable_id_method", "stable_id_confidence", "source_limited_status", "source_identity_hash", "source_record_status"],
    },
    "travelway_network_index.parquet": {
        "required": ["stable_travelway_id", "travelway_index_row_id", "source_layer", "source_route_name", "source_measure_start", "source_measure_end", "geometry", "geometry_hash"],
        "recommended": ["source_route_id", "source_route_common", "source_feature_local_fid", "roadway_configuration", "carriageway_direction_token", "route_base", "RIM_MEDIAN", "RIM_ACCESS", "RIM_FACILITY"],
        "nullable": ["source_route_id", "source_route_common", "carriageway_direction_token", "source_feature_local_fid"],
        "provenance_status": ["stable_travelway_id_method", "lineage_confidence", "route_measure_status", "geometry_validity_status"],
    },
    "signal_travelway_attachment.parquet": {
        "required": ["attachment_id", "stable_signal_id", "stable_travelway_id", "projected_distance_along_geometry", "projected_fraction", "estimated_measure", "point_to_line_distance_ft", "attachment_confidence"],
        "recommended": ["source_signal_globalid", "candidate_rank_for_signal", "candidate_rank_for_route", "route_name", "carriageway_direction_token", "usable_as_corridor_boundary"],
        "nullable": ["source_signal_globalid", "stable_signal_id_for_source_only_endpoint", "no_attachment_reason"],
        "provenance_status": ["attachment_method", "projection_confidence", "signal_role_hint", "source_only_boundary_flag", "no_attachment_reason"],
    },
    "signal_approaches.parquet": {
        "required": ["signal_approach_id", "stable_signal_id", "approach_identity_status", "approach_identity_method"],
        "recommended": ["approach_bearing", "approach_label", "primary_stable_travelway_id", "route_base", "source_route_name_values", "carriageway_subbranch_count", "geometry"],
        "nullable": ["approach_bearing", "approach_label", "geometry", "source_limited_reason"],
        "provenance_status": ["approach_identity_evidence_fields", "approach_confidence", "physical_leg_status", "source_limited_status"],
    },
    "approach_corridors.parquet": {
        "required": ["approach_corridor_id", "stable_signal_id", "signal_approach_id", "stable_travelway_id", "corridor_from_measure", "corridor_to_measure", "reviewed_signal_measure", "corridor_confidence"],
        "recommended": ["before_endpoint_signal_id", "after_endpoint_signal_id", "before_endpoint_source_globalid", "after_endpoint_source_globalid", "endpoint_source_only_used", "clipped_by_2500_ft_flag", "geometry"],
        "nullable": ["before_endpoint_signal_id", "after_endpoint_signal_id", "before_endpoint_source_globalid", "after_endpoint_source_globalid", "geometry", "source_limited_reason"],
        "provenance_status": ["endpoint_policy", "boundary_method", "source_only_endpoint_flag", "cross_signal_boundary_flag", "route_measure_continuity_status", "no_corridor_reason"],
    },
    "bin_context.parquet": {
        "required": ["stable_bin_id", "stable_signal_id", "signal_approach_id", "approach_corridor_id", "stable_travelway_id", "distance_start_ft", "distance_end_ft", "distance_band", "source_measure_start", "source_measure_end", "generated_bin_flag", "geometry_status"],
        "recommended": ["geometry", "geometry_wkt", "source_measure_midpoint", "route_key_name", "route_key_common", "upstream_downstream", "directionality_method", "speed_limit_mph", "aadt", "rim_access_raw", "rim_median_raw"],
        "nullable": ["geometry", "geometry_wkt", "source_measure_midpoint", "upstream_downstream", "directionality_method", "speed_limit_mph", "aadt", "no_directionality_reason"],
        "provenance_status": ["bin_origin", "generated_geometry_status", "lineage_match_method", "lineage_confidence", "directionality_status", "source_limited_status", "context_enrichment_status"],
    },
    "distance_band_units.parquet": {
        "required": ["distance_band_unit_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band", "bin_count", "unit_length_ft"],
        "recommended": ["speed_category", "aadt_category", "divided_undivided", "median_group", "access_count_band", "access_type_flags", "crash_count", "exposure_denominator"],
        "nullable": ["speed_category", "aadt_category", "median_group", "access_count_band", "access_type_flags", "crash_count", "exposure_denominator"],
        "provenance_status": ["unit_build_status", "unit_completeness_status", "context_readiness_status", "rate_readiness_status", "missingness_reason"],
    },
}


ALLOWED_INPUTS = {
    "signal_index.parquet": [
        "artifacts/normalized/signals.parquet",
        "validated prior signal_index.parquet from the same rebuild lineage, for no-loss comparison only",
    ],
    "travelway_network_index.parquet": [
        "artifacts/normalized/roads.parquet",
        "validated prior travelway_network_index.parquet from the same rebuild lineage, for no-loss comparison only",
    ],
    "signal_travelway_attachment.parquet": [
        "signal_index.parquet",
        "travelway_network_index.parquet",
    ],
    "signal_approaches.parquet": [
        "signal_index.parquet",
        "signal_travelway_attachment.parquet",
        "travelway_network_index.parquet",
        "explicitly accepted map-review decisions, if any, with provenance",
    ],
    "approach_corridors.parquet": [
        "signal_approaches.parquet",
        "signal_travelway_attachment.parquet",
        "travelway_network_index.parquet",
    ],
    "bin_context.parquet": [
        "approach_corridors.parquet",
        "signal_approaches.parquet",
        "travelway_network_index.parquet",
        "validated directionality proposal only after explicit promotion approval",
    ],
    "distance_band_units.parquet": [
        "bin_context.parquet",
        "validated context enrichment tables produced from source artifacts and bin_context",
    ],
}


FORBIDDEN_DEPENDENCIES = {
    "signal_index.parquet": [
        "any downstream approach, bin, crash, access, or MVP table",
        "review-only projection outputs as identity parents",
        "display-name-only signal matching",
    ],
    "travelway_network_index.parquet": [
        "bin_context, approach corridors, crash assignments, access assignments, or MVP outputs",
        "package-local GeoPackage fid as the only stable key",
    ],
    "signal_travelway_attachment.parquet": [
        "directionality proposals",
        "crash direction fields",
        "bin_context-derived route matches as primary parent",
    ],
    "signal_approaches.parquet": [
        "distance-band units",
        "crash/access/speed/AADT context as approach-definition drivers",
        "legacy branch summaries without source-rooted evidence",
    ],
    "approach_corridors.parquet": [
        "bin_context as the parent corridor source",
        "directionality proposal objects as corridor parents",
        "review-only global/case proposal outputs as canonical parents",
    ],
    "bin_context.parquet": [
        "distance_band_units.parquet",
        "MVP products",
        "crash direction fields",
        "speed/AADT/access/crash recovery outputs as bin geometry parents",
    ],
    "distance_band_units.parquet": [
        "MVP lookup tables",
        "report figures",
        "review-only proposal summaries",
        "any object that was derived from distance_band_units itself",
    ],
}


QA_GATES = {
    "signal_index.parquet": [
        "source row count reconciles to artifacts/normalized/signals.parquet",
        "stable_signal_id is unique where non-null and all analysis-ready signals have one",
        "GLOBALID is normalized but not required for stable identity",
        "missing GLOBALID rows are retained with source-limited/status fields",
        "geometry availability and geometry_hash are reported",
    ],
    "travelway_network_index.parquet": [
        "row count reconciles to artifacts/normalized/roads.parquet or documented source filters",
        "stable_travelway_id is unique",
        "route/measure start/end and geometry completeness are profiled",
        "roadway configuration and carriageway indicators are preserved where present",
        "invalid or zero-length geometries are retained with status rather than dropped silently",
    ],
    "signal_travelway_attachment.parquet": [
        "all analysis-ready signals are attempted",
        "source-only endpoint signals are preserved as boundary-capable rows",
        "projection distance, fraction, estimated measure, and confidence are populated or no-attachment reason is explicit",
        "candidate ranking is deterministic",
        "no downstream directionality or crash fields are used",
    ],
    "signal_approaches.parquet": [
        "approach counts by signal are plausible and compared with prior canonical/review counts",
        "physical approach identity is separated from carriageway/source-row subbranches",
        "every row links to signal_index",
        "route/corridor evidence is preserved or source-limited reason is explicit",
        "ambiguous approaches remain flagged, not forced",
    ],
    "approach_corridors.parquet": [
        "every corridor links to a signal approach and Travelway row",
        "source-only endpoint boundaries are allowed and flagged",
        "2,500-ft clipping and neighbor-signal boundary policy are explicit",
        "corridors do not cross unsupported signal boundaries",
        "route/measure continuity and geometry status are reported",
    ],
    "bin_context.parquet": [
        "stable_bin_id is unique",
        "real and generated bins are separated by bin_origin/generated_bin_flag",
        "generated bins have geometry or explicit generated_geometry_status plus source measure interval",
        "distance bands and approach links are complete or no-bin reason is explicit",
        "directionality fields remain nullable with method/status/no-proposal reason",
    ],
    "distance_band_units.parquet": [
        "unit grain is unique",
        "only bins with validated directionality enter directional units",
        "bin-to-unit aggregation reconciles bin counts and lengths",
        "context missingness is preserved in flags",
        "MVP/rate readiness is descriptive and does not imply modeling readiness",
    ],
}


ZERO_DATA_LOSS = {
    "signal_index.parquet": [
        "No source signal row may be dropped without a retained exclusion row and source_limited_reason.",
        "Rows missing GLOBALID must remain representable via stable ID method based on local identifiers and geometry hash.",
        "Duplicate source identities must be preserved with conflict flags rather than collapsed silently.",
    ],
    "travelway_network_index.parquet": [
        "Every roads artifact row must be represented or listed in a rejection ledger with reason.",
        "Route/measure/geometry fields must be copied before normalization; normalized keys cannot replace raw fields.",
        "Package-local fid can be retained only as provenance, never as sole stable identity.",
    ],
    "signal_travelway_attachment.parquet": [
        "Every signal_index row must receive candidates or an explicit no_attachment_reason.",
        "Source-only endpoint candidates must not be discarded because stable_signal_id is null.",
        "Low-confidence candidates remain in the table with rank/confidence flags.",
    ],
    "signal_approaches.parquet": [
        "Every analysis-ready signal must appear in an approach coverage ledger.",
        "Subbranches and route/facility changes must remain as evidence fields even when merged into a physical approach.",
        "Unclear approach cases must keep status and evidence, not vanish from the rebuild.",
    ],
    "approach_corridors.parquet": [
        "Every signal approach must receive corridors or a no_corridor_reason.",
        "Endpoint method and source-only endpoint usage must be retained.",
        "Corridors clipped by 2,500 ft or neighbor signals must preserve unclipped source interval evidence.",
    ],
    "bin_context.parquet": [
        "Real and generated bin counts must reconcile separately.",
        "Generated bins without geometry must not masquerade as spatial bins; geometry_status must explain them.",
        "Every omitted bin candidate must appear in a no-bin/no-proposal ledger.",
    ],
    "distance_band_units.parquet": [
        "Unit rollups must reconcile to eligible bin counts and lengths.",
        "Unresolved directionality and missing context must remain visible in missingness summaries.",
        "No rate/MVP table may be the only place where unit membership is preserved.",
    ],
}


REBUILD_SEQUENCE = [
    ("A", 1, "contract_finalization", "Approve this contract, target object names, path policy, QA gates, and promotion criteria."),
    ("B", 2, "build_signal_index", "Build source-rooted signal_index from normalized signals; validate stable ID and GLOBALID gaps."),
    ("B", 3, "build_travelway_network_index", "Build source-rooted travelway_network_index from normalized roads with stable travelway IDs."),
    ("B", 4, "build_signal_travelway_attachment", "Project all signal_index records to travelway_network_index; preserve source-only endpoints."),
    ("C", 5, "build_signal_approaches", "Construct physical approaches from signal attachment and Travelway evidence."),
    ("C", 6, "build_approach_corridors", "Materialize endpoint-bounded and clipped corridors with route/measure continuity."),
    ("C", 7, "build_bin_context_without_final_directionality", "Generate/retain 50-ft bins with full lineage and geometry status."),
    ("D", 8, "review_and_promote_directionality_layer", "Only after bin lineage QA, apply approved directionality methods with provenance."),
    ("D", 9, "build_distance_band_units", "Aggregate validated directional bins to approach-side-distance units."),
    ("E", 10, "context_enrichment_readiness", "Attach or audit speed, AADT, access, crash, median, and exposure readiness from source-rooted joins."),
    ("F", 11, "mvp_regeneration_after_structural_qa", "Regenerate MVP only after structural and context QA passes."),
]


CURRENT_OBJECT_ROLES = [
    ("artifacts/normalized/signals.parquet", "source_parent", "Use as source truth for signal_index; missing GLOBALID is a retained source limitation, not a drop reason."),
    ("artifacts/normalized/roads.parquet", "source_parent", "Use as source truth for travelway_network_index."),
    ("artifacts/normalized/speed.parquet", "source_parent_later_context", "Allowed only for Phase E context enrichment, not for scaffold or directionality parentage."),
    ("artifacts/normalized/aadt.parquet", "source_parent_later_context", "Allowed only for Phase E context enrichment/exposure readiness."),
    ("artifacts/normalized/access_v2.parquet", "source_parent_later_context", "Allowed only for access enrichment after bins/corridors are structurally validated."),
    ("artifacts/normalized/crashes.parquet", "source_parent_later_context", "Allowed only for crash/catchment context after structural QA; crash direction fields forbidden for directionality."),
    ("work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/analysis_signal.csv", "comparison_target_only", "Useful to reconcile represented/canonical signal counts but not a parent for signal_index rebuild."),
    ("work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/analysis_bin.csv", "comparison_target_only", "Useful for no-data-loss and count reconciliation; not a parent for new bin geometry."),
    ("work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/analysis_signal_window.csv", "comparison_target_only", "Useful for window count comparison only."),
    ("work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/analysis_signal_approach_window.csv", "comparison_target_only", "Useful for approach/window comparison only."),
    ("work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate/signal_approaches.parquet", "method_reference_only", "May inform approach rules and QA comparisons; must be rebuilt from validated parents."),
    ("work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate/continuation_corridors.parquet", "method_reference_only", "May inform corridor extension logic; not a canonical parent because endpoint/corridor policy is split."),
    ("work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate/bin_context.parquet", "comparison_target_only", "Hybrid real/generated bin surface; use for count reconciliation and field gap evidence, not as parent."),
    ("work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate/source_signal_travelway_projection_index.parquet", "method_reference_only", "Use projection method evidence only; rebuild from repaired signal_index/travelway_network_index."),
    ("work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate/signal_bounded_travelway_corridor_index.parquet", "method_reference_only", "Use endpoint/source-only logic evidence only; rebuild as approach_corridors."),
    ("work/roadway_graph/review/analysis_cache_structural_integrity_audit/", "method_reference_only", "Audit evidence for current limitations and acceptance checks."),
    ("work/roadway_graph/review/network_to_unit_lineage_preservation_audit/", "method_reference_only", "Audit evidence for target architecture and repair sequence."),
    ("work/roadway_graph/review/source_signal_travelway_projection_index/", "method_reference_only", "Projection-index method and case acceptance evidence only."),
    ("work/roadway_graph/review/expanded_directionality_recovery_audit/", "comparison_target_only", "Directionality residual context only; not a cache parent."),
    ("work/roadway_graph/review/expanded_bin_universe_impact_audit/", "comparison_target_only", "Universe/count impact evidence only; not a cache parent."),
]


PROMOTION_CRITERIA = [
    "All required target objects for the promoted phase exist in staging as Parquet plus schema/manifest/QA files.",
    "Each object passes its QA gates and zero-data-loss checks.",
    "Parent paths in manifests point only to allowed source artifacts or previously validated cache objects.",
    "No dependency loop exists in the manifest graph.",
    "Review-only method/proposal objects are not listed as canonical parents.",
    "Row counts reconcile to source or documented exclusion ledgers.",
    "Unresolved/source-limited cases are retained with status/provenance flags.",
    "A promotion memo states changed fields, affected grains, caveats, and downstream impacts.",
    "Canonical replacement is explicit and bounded; prior canonical products are preserved according to data-preservation policy.",
]


IMPLEMENTATION_PHASES = [
    ("Phase A", "contract_finalization", "Freeze the target object names, field contract, dependency rules, QA gates, and promotion policy."),
    ("Phase B", "build_source_rooted_base_indexes", "Build signal_index, travelway_network_index, and signal_travelway_attachment from source artifacts and validated parents only."),
    ("Phase C", "build_approach_corridor_bin_layers", "Build signal_approaches, approach_corridors, and bin_context with full source lineage and geometry status."),
    ("Phase D", "build_directionality_and_distance_units", "Apply approved directionality methods only after structural QA, then build distance_band_units."),
    ("Phase E", "context_enrichment_readiness", "Assess or attach speed, AADT, access, crash, median, and exposure readiness from source-rooted joins."),
    ("Phase F", "mvp_regeneration_after_structural_qa", "Regenerate MVP/distribution products only after cache structure and context QA pass."),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def write_csv(name: str, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with (OUT / name).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_text(name: str, text: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(text, encoding="utf-8")


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now_iso()} - {message}\n")


def object_metadata(path_text: str) -> dict[str, Any]:
    path = REPO_ROOT / path_text
    meta: dict[str, Any] = {
        "path": path_text,
        "exists": path.exists(),
        "row_count": "",
        "column_count": "",
        "columns_sample": "",
    }
    if path.suffix.lower() == ".parquet" and path.exists() and pq is not None:
        parquet = pq.ParquetFile(path)
        cols = parquet.schema_arrow.names
        meta.update(
            {
                "row_count": parquet.metadata.num_rows,
                "column_count": len(cols),
                "columns_sample": "|".join(cols[:20]),
            }
        )
    elif path.suffix.lower() == ".csv" and path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f), [])
        meta.update({"column_count": len(header), "columns_sample": "|".join(header[:20])})
    return meta


def rows_target_objects() -> list[dict[str, Any]]:
    return [
        {
            "object_name": o["object_name"],
            "canonical_path": o["canonical_path"],
            "grain": o["grain"],
            "purpose": o["purpose"],
            "build_phase": o["build_phase"],
            "allowed_parent_summary": o["depends_on"],
            "downstream_consumers": o["downstream_consumers"],
        }
        for o in TARGET_OBJECTS
    ]


def rows_field_contract() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for object_name, groups in FIELD_CONTRACTS.items():
        for category, fields in groups.items():
            for field in fields:
                rows.append(
                    {
                        "object_name": object_name,
                        "field_name": field,
                        "field_category": category,
                        "required_before_validation": category == "required",
                    }
                )
    return rows


def rows_allowed_inputs() -> list[dict[str, Any]]:
    rows = []
    for object_name, inputs in ALLOWED_INPUTS.items():
        for input_name in inputs:
            rows.append(
                {
                    "object_name": object_name,
                    "allowed_input": input_name,
                    "input_role": "source_parent" if input_name.startswith("artifacts/") else "validated_parent_or_explicit_acceptance",
                    "condition": "Must appear in manifest as parent and pass upstream QA before use.",
                }
            )
    return rows


def rows_forbidden_dependencies() -> list[dict[str, Any]]:
    rows = []
    for object_name, deps in FORBIDDEN_DEPENDENCIES.items():
        for dep in deps:
            rows.append(
                {
                    "object_name": object_name,
                    "forbidden_dependency": dep,
                    "risk": "dependency_loop_or_untrusted_parent",
                    "enforcement": "Block validation if manifest parent path or code reads this as a build parent.",
                }
            )
    return rows


def rows_roles() -> list[dict[str, Any]]:
    rows = []
    for path_text, role, notes in CURRENT_OBJECT_ROLES:
        meta = object_metadata(path_text.rstrip("/"))
        rows.append(
            {
                "current_object": path_text,
                "role_classification": role,
                "exists": meta["exists"] if not path_text.endswith("/") else (REPO_ROOT / path_text).exists(),
                "row_count": meta["row_count"],
                "column_count": meta["column_count"],
                "notes": notes,
            }
        )
    return rows


def rows_rebuild_sequence() -> list[dict[str, Any]]:
    return [
        {
            "phase": phase,
            "sequence_order": order,
            "step": step,
            "description": description,
            "may_promote_after_step": step
            in {
                "build_signal_travelway_attachment",
                "build_bin_context_without_final_directionality",
                "build_distance_band_units",
                "mvp_regeneration_after_structural_qa",
            },
        }
        for phase, order, step, description in REBUILD_SEQUENCE
    ]


def rows_qa_gates() -> list[dict[str, Any]]:
    return [
        {"object_name": object_name, "qa_gate": gate, "gate_type": "blocking"}
        for object_name, gates in QA_GATES.items()
        for gate in gates
    ]


def rows_zero_data_loss() -> list[dict[str, Any]]:
    return [
        {"object_name": object_name, "zero_data_loss_check": check, "failure_policy": "block_validation_or_write_explicit_loss_ledger"}
        for object_name, checks in ZERO_DATA_LOSS.items()
        for check in checks
    ]


def rows_phase_plan() -> list[dict[str, Any]]:
    return [
        {"phase": phase, "phase_name": name, "objective": objective, "allowed_output": "review/staging plan or bounded staged cache object in later implementation task"}
        for phase, name, objective in IMPLEMENTATION_PHASES
    ]


def rows_recommended_actions() -> list[dict[str, Any]]:
    return [
        {
            "recommended_next_action": "implement_phase_b_signal_index_only",
            "rationale": "Signal identity is the first parent in the dependency graph and prior audits show it is the first structural break.",
            "must_not_do": "Do not rebuild projection, approaches, bins, directionality, or MVP in the first implementation task.",
        }
    ]


def contract_md() -> str:
    parts = [
        "# Roadway Graph Target Cache Contract",
        "",
        "This is a planning contract, not a cache rebuild. Canonical cache Parquets must be built only by later bounded implementation tasks after this contract is accepted.",
        "",
    ]
    for obj in TARGET_OBJECTS:
        name = obj["object_name"]
        groups = FIELD_CONTRACTS[name]
        parts.extend(
            [
                f"## {name}",
                "",
                f"Purpose: {obj['purpose']}",
                "",
                f"Grain: {obj['grain']}",
                "",
                f"Canonical path: `{obj['canonical_path']}`",
                "",
                "Required fields:",
                *[f"- `{f}`" for f in groups["required"]],
                "",
                "Recommended fields:",
                *[f"- `{f}`" for f in groups["recommended"]],
                "",
                "Nullable fields:",
                *[f"- `{f}`" for f in groups["nullable"]],
                "",
                "Provenance/status fields:",
                *[f"- `{f}`" for f in groups["provenance_status"]],
                "",
                geometry_requirement(name),
                "",
                source_identity_requirement(name),
                "",
                f"Downstream consumers: {obj['downstream_consumers']}",
                "",
                "QA gates:",
                *[f"- {gate}" for gate in QA_GATES[name]],
                "",
                "Allowed parents:",
                *[f"- {parent}" for parent in ALLOWED_INPUTS[name]],
                "",
                "Forbidden parents:",
                *[f"- {parent}" for parent in FORBIDDEN_DEPENDENCIES[name]],
                "",
            ]
        )
    return "\n".join(parts)


def geometry_requirement(object_name: str) -> str:
    if object_name in {"signal_index.parquet", "travelway_network_index.parquet"}:
        return "Geometry requirements: geometry is required and must have a reproducible geometry hash and validity status."
    if object_name == "signal_travelway_attachment.parquet":
        return "Geometry requirements: source geometries remain in parent objects; attachment must preserve projection distance, fraction, estimated measure, and point-to-line distance."
    if object_name == "bin_context.parquet":
        return "Geometry requirements: real bins require geometry; generated bins require either generated geometry or explicit generated_geometry_status plus source measure interval."
    if object_name == "distance_band_units.parquet":
        return "Geometry requirements: unit geometry is optional; unit membership must reconcile to bin_context geometry/status."
    return "Geometry requirements: geometry is recommended where it represents the object directly; otherwise preserve parent geometry references and status."


def source_identity_requirement(object_name: str) -> str:
    if object_name == "signal_index.parquet":
        return "Source identity requirements: stable_signal_id is canonical; GLOBALID is preserved when present but must not be required."
    if object_name == "travelway_network_index.parquet":
        return "Source identity requirements: stable_travelway_id must be built from route, measure, source layer, local row identity, and geometry hash evidence."
    return "Source identity requirements: preserve parent stable_signal_id, stable_travelway_id, source route/measure, and status/provenance fields needed to trace back to validated parents."


def dependency_plan_md() -> str:
    lines = [
        "# Rebuild Dependency Plan",
        "",
        "## Dependency Graph",
        "",
        "artifacts/normalized/signals.parquet -> signal_index.parquet",
        "artifacts/normalized/roads.parquet -> travelway_network_index.parquet",
        "signal_index.parquet + travelway_network_index.parquet -> signal_travelway_attachment.parquet",
        "signal_index.parquet + signal_travelway_attachment.parquet + travelway_network_index.parquet -> signal_approaches.parquet",
        "signal_approaches.parquet + signal_travelway_attachment.parquet + travelway_network_index.parquet -> approach_corridors.parquet",
        "approach_corridors.parquet + signal_approaches.parquet + travelway_network_index.parquet -> bin_context.parquet",
        "bin_context.parquet -> distance_band_units.parquet",
        "bin_context.parquet + distance_band_units.parquet + source context artifacts -> later context/MVP products",
        "",
        "## One-Way Parent/Child Relationships",
        "",
        "Parents may feed children only in the order shown above. A child may be used for QA comparison against an older object, but a child must never become a parent of an upstream object.",
        "",
        "## No-Loop Rule",
        "",
        "A validation manifest must list parent objects. Validation fails if any parent is downstream of the object being built, if an object appears in its own ancestry, or if a review/proposal product appears as a canonical parent.",
        "",
        "## Staging Policy",
        "",
        "Each implementation task writes to a bounded staging folder first, with manifest, schema, QA, row-count reconciliation, and no-data-loss ledgers. Staging products remain noncanonical until explicit promotion.",
        "",
        "## Promotion Policy",
        "",
        "Promotion requires passing object QA gates, zero-data-loss checks, dependency graph validation, and a promotion memo describing changed fields, caveats, and downstream impacts.",
        "",
        "## Old Staged/Review Product Policy",
        "",
        "Existing staged and review products may be used as method evidence, comparison targets, and QA regression baselines. They must not be listed as canonical parents unless a later task explicitly validates and promotes them into this dependency graph.",
        "",
    ]
    return "\n".join(lines)


def findings_md() -> str:
    return "\n".join(
        [
            "# Cache Contract And Rebuild Plan Findings",
            "",
            "## Why Patchwork Fixes Should Stop",
            "",
            "Recent audits show that signal identity, projection support, corridor policy, generated-bin lineage, and distance-unit materialization are split across hybrid staged and review objects. Continuing symptom-level fixes risks making downstream directionality and numeric-context work depend on untrusted children or proposal products.",
            "",
            "## Target Cache System",
            "",
            "The target system is a one-way lineage: Travelway network -> signal index -> signal-to-Travelway attachment -> approach construction -> approach corridors -> bin context -> distance-band units -> context/MVP readiness. Every cache object must be built only from source artifacts or previously validated parents.",
            "",
            "## Useful Current Objects That Are Not Canonical Parents",
            "",
            "The normalized source artifacts are allowed source parents. Existing canonical CSVs, staged support tables, projection/corridor indexes, generated-bin proposals, and recent review outputs are useful as comparison targets or method references only. They are not automatically valid parents for the rebuild.",
            "",
            "## Objects To Rebuild First",
            "",
            "Rebuild `signal_index.parquet` first, then `travelway_network_index.parquet`, then `signal_travelway_attachment.parquet`. This fixes the source/stable identity and projection parentage before approaches, corridors, bins, directionality, or context joins are revisited.",
            "",
            "## Zero Data Loss",
            "",
            "Every step must reconcile source rows, retain unresolved/source-limited rows with status fields, and write explicit exclusion/loss ledgers. Missing GLOBALID, low-confidence projection, ambiguous approach identity, and generated-bin geometry gaps are status conditions, not silent-drop reasons.",
            "",
            "## Avoiding Dependency Loops",
            "",
            "Each manifest must validate the parent graph. Downstream objects such as bin_context, distance_band_units, MVP tables, directionality proposals, crash/access assignments, and report figures cannot feed upstream identity, Travelway, attachment, approach, or corridor objects.",
            "",
            "## Recommended First Implementation Task",
            "",
            "Implement Phase B step 1 only: build a staged `signal_index.parquet` from `artifacts/normalized/signals.parquet`, preserving rows missing GLOBALID with stable identity/status logic and writing QA/reconciliation outputs. Do not rebuild projections or bins in that task.",
            "",
        ]
    )


def promotion_md() -> str:
    return "\n".join(
        [
            "# Promotion Criteria",
            "",
            "A staged cache object may be promoted only when all criteria below pass:",
            "",
            *[f"- {criterion}" for criterion in PROMOTION_CRITERIA],
            "",
            "Promotion is an explicit bounded task. This planning package does not promote or create canonical cache Parquets.",
            "",
        ]
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Started read-only cache contract and rebuild planning package.")

    source_metadata = [object_metadata(p) for p in SOURCE_ARTIFACTS]
    current_metadata = [object_metadata(p) for p in CURRENT_CACHE_OBJECTS]
    log("Read context metadata for source artifacts and current/staged cache objects.")

    write_csv("target_cache_objects.csv", rows_target_objects())
    write_csv("target_object_field_contract.csv", rows_field_contract())
    write_csv("allowed_inputs_by_object.csv", rows_allowed_inputs())
    write_csv("forbidden_dependencies_by_object.csv", rows_forbidden_dependencies())
    write_csv("current_object_role_classification.csv", rows_roles())
    write_csv("rebuild_sequence.csv", rows_rebuild_sequence())
    write_csv("qa_gates_by_object.csv", rows_qa_gates())
    write_csv("zero_data_loss_checks.csv", rows_zero_data_loss())
    write_csv("implementation_phase_plan.csv", rows_phase_plan())
    write_csv("recommended_next_actions.csv", rows_recommended_actions())

    write_text("target_cache_contract.md", contract_md())
    write_text("rebuild_dependency_plan.md", dependency_plan_md())
    write_text("findings_memo.md", findings_md())
    write_text("promotion_criteria.md", promotion_md())
    log("Wrote contract, dependency, QA, promotion, and phase-plan outputs.")

    acceptance_tests = [
        ("grain_and_purpose_defined", len(TARGET_OBJECTS) == 7),
        ("field_categories_defined", all(name in FIELD_CONTRACTS for name in [o["object_name"] for o in TARGET_OBJECTS])),
        ("allowed_inputs_defined", all(name in ALLOWED_INPUTS for name in [o["object_name"] for o in TARGET_OBJECTS])),
        ("forbidden_dependencies_defined", all(name in FORBIDDEN_DEPENDENCIES for name in [o["object_name"] for o in TARGET_OBJECTS])),
        ("current_object_roles_defined", len(CURRENT_OBJECT_ROLES) >= 15),
        ("zero_data_loss_checks_defined", all(name in ZERO_DATA_LOSS for name in [o["object_name"] for o in TARGET_OBJECTS])),
        ("qa_gates_defined", all(name in QA_GATES for name in [o["object_name"] for o in TARGET_OBJECTS])),
        ("rebuild_sequence_defined", len(REBUILD_SEQUENCE) == 11),
        ("promotion_criteria_defined", len(PROMOTION_CRITERIA) >= 8),
        ("dependency_loop_prevention_defined", "No-Loop Rule" in dependency_plan_md()),
        ("no_cache_parquets_created", not any(p.suffix.lower() == ".parquet" for p in OUT.glob("*"))),
    ]
    qa_manifest = {
        "created_utc": now_iso(),
        "bounded_question": "Define a source-rooted roadway_graph cache contract and rebuild sequence without implementing the rebuild.",
        "acceptance_tests": [
            {
                "acceptance_test": name,
                "status": "pass" if ok else "fail",
            }
            for name, ok in acceptance_tests
        ],
        "source_artifact_metadata": source_metadata,
        "current_cache_metadata": current_metadata,
        "review_context_read": RECENT_REVIEWS,
        "final_recommended_first_task": "implement_phase_b_signal_index_only",
    }
    manifest = {
        "created_utc": now_iso(),
        "script": rel(Path(__file__)),
        "output_dir": rel(OUT),
        "read_context": READ_CONTEXT,
        "source_artifacts": SOURCE_ARTIFACTS,
        "current_cache_objects": CURRENT_CACHE_OBJECTS,
        "recent_review_context": RECENT_REVIEWS,
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
        "no_mutation_statement": "Planning outputs only; no canonical, staged, source, artifact, MVP, recovery, or target cache Parquet products were modified or created.",
    }
    write_text("qa_manifest.json", json.dumps(qa_manifest, indent=2, sort_keys=True))
    write_text("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    log("Completed planning package.")


if __name__ == "__main__":
    main()
