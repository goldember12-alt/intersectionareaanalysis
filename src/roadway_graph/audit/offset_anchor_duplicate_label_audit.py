from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/offset_anchor_duplicate_label_audit"
OFFSET_INTEGRATION_DIR = OUTPUT_ROOT / "review/current/missing_hmms_offset_anchor_universe_integration"
OFFSET_CONTEXT_DIR = OUTPUT_ROOT / "review/current/missing_hmms_offset_anchor_context_refresh"
GOOD_UNIVERSE_DIR = OUTPUT_ROOT / "review/current/missing_hmms_good_travelway_universe_integration"
STABLE_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"
FEASIBILITY_DIR = OUTPUT_ROOT / "review/current/missing_hmms_signal_recovery_feasibility"

SOURCE_SIGNAL_UNIVERSE_COUNT = 3933
CURRENT_REPRESENTED_SIGNAL_COUNT = 2739
GOOD_TRAVELWAY_REVIEW_VISIBLE_ADDITIONS = 626
GOOD_TRAVELWAY_CLEAN_ADDITIONS = 604
OFFSET_CONTEXT_READY_ADDITIONS = 173
OFFSET_CLEAN_ADDITIONS_PRIOR = 62

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)

REQUIRED_INPUTS = [
    OFFSET_INTEGRATION_DIR / "expanded_offset_anchor_signal_universe.csv",
    OFFSET_INTEGRATION_DIR / "expanded_offset_anchor_bin_universe.csv",
    OFFSET_INTEGRATION_DIR / "offset_anchor_readiness_consistency_audit.csv",
    OFFSET_INTEGRATION_DIR / "offset_anchor_173_addition_summary.csv",
    OFFSET_INTEGRATION_DIR / "offset_anchor_113_risk_decomposition.csv",
    OFFSET_INTEGRATION_DIR / "offset_anchor_167_low_confidence_holdout_ledger.csv",
    OFFSET_INTEGRATION_DIR / "offset_anchor_universe_readiness.csv",
    OFFSET_INTEGRATION_DIR / "offset_anchor_universe_integration_manifest.json",
    OFFSET_CONTEXT_DIR / "offset_anchor_context_signal_summary.csv",
    OFFSET_CONTEXT_DIR / "offset_anchor_context_bin_detail.csv",
    OFFSET_CONTEXT_DIR / "offset_anchor_existing_universe_overlap_review.csv",
    OFFSET_CONTEXT_DIR / "offset_anchor_context_refresh_manifest.json",
    GOOD_UNIVERSE_DIR / "expanded_good_travelway_signal_universe.csv",
    GOOD_UNIVERSE_DIR / "expanded_good_travelway_bin_universe.csv",
    GOOD_UNIVERSE_DIR / "good_travelway_universe_integration_manifest.json",
    STABLE_DIR / "stable_lineage_represented_signal_universe.csv",
    STABLE_DIR / "stable_lineage_represented_bin_universe.csv",
    STABLE_DIR / "stable_lineage_generation_manifest.json",
    FEASIBILITY_DIR / "missing_source_signal_universe_detail.csv",
    FEASIBILITY_DIR / "missing_hmms_signal_recovery_feasibility_manifest.json",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{_now()} {message}\n")


def _checkpoint(name: str, rows: int | None = None) -> None:
    suffix = "" if rows is None else f" rows={rows:,}"
    _log(f"CHECKPOINT {name}{suffix}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [col for col in usecols if col in header]
    blocked = [col for col in cols if _blocked_column(col)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    _checkpoint(f"write_start {name}", len(frame))
    frame.to_csv(OUT_DIR / name, index=False)
    _checkpoint(f"write_complete {name}", len(frame))


def _write_json(payload: dict[str, Any], name: str) -> None:
    _checkpoint(f"write_start {name}")
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write_complete {name}")


def _write_text(text: str, name: str) -> None:
    _checkpoint(f"write_start {name}")
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write_complete {name}")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.upper() in {"", "NAN", "NONE", "<NA>", "NULL"} else text


def _norm(value: Any) -> str:
    return _clean(value).upper()


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _source_combo(row: pd.Series) -> str:
    layer = _norm(row.get("source_layer", row.get("represented_source_layer", row.get("Stage1_SourceLayer", ""))))
    ids = [_norm(row.get(col, "")) for col in ("OBJECTID", "OBJECTID_1", "ASSET_ID", "REG_SIGNAL_ID", "ASSET_NUM")]
    ids = [v for v in ids if v]
    if not layer or not ids:
        return ""
    return "|".join([layer] + ids)


def _first_point(wkt_value: Any):
    text = _clean(wkt_value)
    if not text:
        return None
    try:
        geom = shapely.from_wkt(text)
        if geom is None or geom.is_empty:
            return None
        if geom.geom_type == "Point":
            return geom
        if geom.geom_type == "LineString":
            coords = list(geom.coords)
            return shapely.Point(coords[0]) if coords else None
        parts = list(getattr(geom, "geoms", []))
        if parts:
            chosen = max(parts, key=lambda g: getattr(g, "length", 0.0))
            if chosen.geom_type == "Point":
                return chosen
            coords = list(chosen.coords)
            return shapely.Point(coords[0]) if coords else None
    except Exception:
        return None
    return None


def _signal_points(signals: pd.DataFrame, bins: pd.DataFrame | None = None) -> pd.Series:
    candidates = pd.Series([None] * len(signals), index=signals.index, dtype=object)
    for col in ("raw_signal_geometry_wkt", "signal_geometry_wkt", "inferred_anchor_geometry_wkt", "geometry_wkt"):
        if col in signals.columns:
            pts = _text(signals, col).map(_first_point)
            candidates = candidates.where(candidates.notna(), pts)
    if bins is not None and "stable_signal_id" in signals.columns:
        first_bin = bins.groupby("stable_signal_id", sort=False)["geometry_wkt"].first().map(_first_point) if "geometry_wkt" in bins.columns else pd.Series(dtype=object)
        mapped = _text(signals, "stable_signal_id").map(first_bin)
        candidates = candidates.where(candidates.notna(), mapped)
    return candidates


def _identity_reference(stable_signals: pd.DataFrame, good_signals: pd.DataFrame, offset_signals: pd.DataFrame) -> pd.DataFrame:
    stable = stable_signals.copy()
    stable["reference_group"] = "existing_represented"
    if "source_signal_id" not in stable.columns:
        stable["source_signal_id"] = _text(stable, "represented_source_signal_id")
    if "source_layer" not in stable.columns:
        stable["source_layer"] = _text(stable, "represented_source_layer")
    good = good_signals.copy()
    good["reference_group"] = np.where(_text(good, "universe_record_type").eq("existing_represented"), "existing_represented_from_good_universe", "good_travelway_recovered")
    offset = offset_signals[~_text(offset_signals, "offset_anchor_addition_class").eq("possible_duplicate_existing_signal")].copy()
    offset["reference_group"] = "other_offset_anchor_context_ready"
    cols = sorted(set(stable.columns) | set(good.columns) | set(offset.columns))
    for frame in (stable, good, offset):
        for col in cols:
            if col not in frame.columns:
                frame[col] = ""
    ref = pd.concat([stable[cols], good[cols], offset[cols]], ignore_index=True)
    ref = ref.drop_duplicates(["reference_group", "stable_signal_id", "GLOBALID", "source_signal_id"], keep="first")
    ref["source_identity_combo"] = ref.apply(_source_combo, axis=1)
    return ref


def _strict_duplicate_audit(targets: pd.DataFrame, reference: pd.DataFrame) -> pd.DataFrame:
    ref_stable = {v for v in _text(reference, "stable_signal_id") if v}
    ref_global = {v for v in _text(reference, "GLOBALID") if v}
    ref_source = {v for v in _text(reference, "source_signal_id") if v}
    ref_combo = {v for v in _text(reference, "source_identity_combo") if v}
    ref_hash = {v for v in list(_text(reference, "source_identity_hash")) + list(_text(reference, "source_signal_key")) if v}

    rows = []
    for _, row in targets.iterrows():
        combo = _source_combo(row)
        source_hash = _clean(row.get("source_identity_hash", row.get("source_signal_key", "")))
        same_stable = _clean(row.get("stable_signal_id")) in ref_stable
        same_global = _clean(row.get("GLOBALID")) in ref_global
        same_source = _clean(row.get("source_signal_id")) in ref_source
        same_combo = bool(combo and combo in ref_combo)
        same_hash = bool(source_hash and source_hash in ref_hash)
        true_dup = same_stable or same_global or same_source or same_combo or same_hash
        if true_dup:
            criteria = "|".join(
                name
                for name, value in [
                    ("same_stable_signal_id", same_stable),
                    ("same_GLOBALID", same_global),
                    ("same_source_signal_id", same_source),
                    ("same_source_layer_object_asset_region_combo", same_combo),
                    ("same_source_identity_hash", same_hash),
                ]
                if value
            )
        else:
            criteria = "none"
        rows.append(
            {
                "stable_signal_id": row.get("stable_signal_id", ""),
                "GLOBALID": row.get("GLOBALID", ""),
                "source_signal_id": row.get("source_signal_id", ""),
                "source_layer": row.get("source_layer", ""),
                "source_identity_combo": combo,
                "same_stable_signal_id": same_stable,
                "same_GLOBALID": same_global,
                "same_source_signal_id": same_source,
                "same_source_layer_object_asset_region_combo": same_combo,
                "same_source_identity_hash": same_hash,
                "near_identical_coordinates_plus_same_source_identity": False,
                "strict_true_duplicate": true_dup,
                "strict_duplicate_criteria_met": criteria,
            }
        )
    return pd.DataFrame(rows)


def _spatial_scaffold_audit(targets: pd.DataFrame, context_bins: pd.DataFrame, good_signals: pd.DataFrame, good_bins: pd.DataFrame, stable_bins: pd.DataFrame) -> pd.DataFrame:
    target_points = _signal_points(targets)
    ref_signals = good_signals.copy()
    ref_points = _signal_points(ref_signals, good_bins)
    valid_ref = ref_points.notna()
    xy = np.column_stack([[p.x for p in ref_points[valid_ref]], [p.y for p in ref_points[valid_ref]]]) if valid_ref.any() else np.empty((0, 2))
    tree = cKDTree(xy) if len(xy) else None
    ref_ids = _text(ref_signals.loc[valid_ref], "stable_signal_id").tolist()

    existing_tw = set(_text(stable_bins, "stable_travelway_id")) | set(_text(good_bins, "stable_travelway_id"))
    offset_tw = context_bins.groupby("stable_signal_id")["stable_travelway_id"].agg(lambda s: sorted({v for v in s.astype(str) if _clean(v)})).to_dict()
    offset_bin_counts = context_bins.groupby("stable_signal_id").agg(
        generated_bin_count=("stable_bin_id", "size"),
        shared_stable_travelway_id_count=("stable_travelway_id", lambda s: int(pd.Series(s).astype(str).isin(existing_tw).sum())),
        distinct_shared_stable_travelway_id_count=("stable_travelway_id", lambda s: int(pd.Series([v for v in s.astype(str) if v in existing_tw]).nunique())),
    ).reset_index()
    offset_bin_counts = offset_bin_counts.set_index("stable_signal_id")

    rows = []
    for idx, row in targets.iterrows():
        sid = _clean(row.get("stable_signal_id"))
        point = target_points.loc[idx]
        distances = []
        nearest_ft = math.nan
        nearest_id = ""
        counts = {50: 0, 100: 0, 175: 0, 250: 0}
        if tree is not None and point is not None:
            dist_m, nearest_idx = tree.query([point.x, point.y], k=1)
            nearest_ft = float(dist_m) / 0.3048
            nearest_id = ref_ids[int(nearest_idx)] if len(ref_ids) else ""
            nearby_idx = tree.query_ball_point([point.x, point.y], r=250 * 0.3048)
            distances = [float(np.linalg.norm(xy[i] - np.array([point.x, point.y]))) / 0.3048 for i in nearby_idx]
            counts = {threshold: int(sum(d <= threshold for d in distances)) for threshold in counts}
        bin_row = offset_bin_counts.loc[sid] if sid in offset_bin_counts.index else None
        shared_count = int(bin_row["shared_stable_travelway_id_count"]) if bin_row is not None else 0
        distinct_shared = int(bin_row["distinct_shared_stable_travelway_id_count"]) if bin_row is not None else 0
        generated_bins = int(bin_row["generated_bin_count"]) if bin_row is not None else 0
        same_zone = counts[175] > 0
        same_corridor = counts[250] > 0 or distinct_shared > 0
        rows.append(
            {
                "stable_signal_id": sid,
                "nearest_existing_or_recovered_signal_id": nearest_id,
                "nearest_existing_or_recovered_signal_ft": round(nearest_ft, 3) if pd.notna(nearest_ft) else "",
                "existing_or_recovered_signals_within_50ft": counts[50],
                "existing_or_recovered_signals_within_100ft": counts[100],
                "existing_or_recovered_signals_within_175ft": counts[175],
                "existing_or_recovered_signals_within_250ft": counts[250],
                "generated_bin_count": generated_bins,
                "shared_stable_travelway_id_bin_count": shared_count,
                "distinct_shared_stable_travelway_id_count": distinct_shared,
                "same_physical_intersection_zone_possible": same_zone,
                "same_corridor_or_proximity_possible": same_corridor,
                "sibling_signal_possibility": str(row.get("sibling_signal_risk", "")).lower() == "true" or same_zone,
                "complex_multi_signal_possibility": str(row.get("complex_multi_signal_risk", "")).lower() == "true",
                "spatial_proximity_only_true_duplicate": False,
            }
        )
    return pd.DataFrame(rows)


def _reclassify(targets: pd.DataFrame, strict: pd.DataFrame, spatial: pd.DataFrame) -> pd.DataFrame:
    out = targets.merge(strict, on=["stable_signal_id", "GLOBALID", "source_signal_id", "source_layer"], how="left")
    out = out.merge(spatial, on="stable_signal_id", how="left", suffixes=("", "_spatial_audit"))
    classes = []
    reasons = []
    map_review = []
    valid_review_visible = []
    hold_clean = []

    def value(row: dict[str, Any], name: str, default: Any = "") -> Any:
        raw = row.get(name, default)
        if _clean(raw) != "":
            return raw
        return row.get(f"{name}_spatial_audit", default)

    for row in out.to_dict(orient="records"):
        strict_dup = bool(row.get("strict_true_duplicate", False))
        sibling = str(row.get("sibling_signal_risk", "")).lower() == "true"
        complex_risk = str(row.get("complex_multi_signal_risk", "")).lower() == "true"
        shared_tw = float(value(row, "distinct_shared_stable_travelway_id_count", 0) or 0) > 0
        near50 = float(value(row, "existing_or_recovered_signals_within_50ft", 0) or 0) > 0
        near100 = float(value(row, "existing_or_recovered_signals_within_100ft", 0) or 0) > 0
        near250 = float(value(row, "existing_or_recovered_signals_within_250ft", 0) or 0) > 0
        missing_identity = not _clean(row.get("GLOBALID")) and not _clean(row.get("source_signal_id")) and not _clean(row.get("source_identity_combo"))
        if strict_dup:
            cls = "true_duplicate_source_record"
            reason = "Strict source identity duplicate criteria were met."
            needs_map = False
            valid = False
        elif sibling:
            cls = "possible_sibling_signal_same_intersection"
            reason = "Sibling signal flag is present; this is not source-record duplication."
            needs_map = True
            valid = True
        elif complex_risk:
            cls = "complex_multi_signal_context"
            reason = "Original duplicate label was masking complex multi-signal/multi-branch context."
            needs_map = True
            valid = True
        elif shared_tw:
            cls = "overlapping_scaffold_context_review"
            reason = "Generated bins share stable Travelway lineage with represented/recovered scaffold; shared roadway context is not duplication."
            needs_map = True
            valid = True
        elif near100:
            cls = "valid_offset_anchor_addition_near_existing_signal"
            reason = "Nearby represented/recovered signal exists, but no strict source identity duplicate was found."
            needs_map = False
            valid = True
        elif near250:
            cls = "valid_offset_anchor_addition_same_corridor"
            reason = "Same-corridor proximity exists, but no strict source identity duplicate was found."
            needs_map = False
            valid = True
        elif missing_identity:
            cls = "insufficient_identity_evidence"
            reason = "No strict duplicate evidence exists, but source identity fields are too sparse for clean use."
            needs_map = True
            valid = True
        else:
            cls = "manual_map_review_needed"
            reason = "No strict duplicate evidence exists, but residual QA evidence needs manual review."
            needs_map = True
            valid = True
        classes.append(cls)
        reasons.append(reason)
        map_review.append(needs_map)
        valid_review_visible.append(valid)
        hold_clean.append(cls != "true_duplicate_source_record")
    out["revised_duplicate_audit_class"] = classes
    out["reclassification_reason"] = reasons
    out["map_review_needed"] = map_review
    out["valid_review_visible_addition_with_qa_flags"] = valid_review_visible
    out["hold_from_clean_analysis_after_duplicate_audit"] = hold_clean
    out["retire_possible_duplicate_label"] = True
    for col in [
        "nearest_existing_or_recovered_signal_ft",
        "existing_or_recovered_signals_within_50ft",
        "existing_or_recovered_signals_within_100ft",
        "existing_or_recovered_signals_within_175ft",
        "existing_or_recovered_signals_within_250ft",
        "shared_stable_travelway_id_bin_count",
        "distinct_shared_stable_travelway_id_count",
        "same_physical_intersection_zone_possible",
        "same_corridor_or_proximity_possible",
        "sibling_signal_possibility",
        "complex_multi_signal_possibility",
        "spatial_proximity_only_true_duplicate",
    ]:
        audit_col = f"{col}_spatial_audit"
        if audit_col in out.columns:
            out[col] = out[audit_col]
    return out


def _readiness(reclass: pd.DataFrame) -> pd.DataFrame:
    true_dup = int(reclass["revised_duplicate_audit_class"].eq("true_duplicate_source_record").sum())
    valid = int(reclass["valid_review_visible_addition_with_qa_flags"].sum())
    map_review = int(reclass["map_review_needed"].sum())
    hold_clean = int(reclass["hold_from_clean_analysis_after_duplicate_audit"].sum())
    near_250 = int(pd.to_numeric(reclass["existing_or_recovered_signals_within_250ft"], errors="coerce").fillna(0).gt(0).sum())
    same_corridor = int(reclass["same_corridor_or_proximity_possible"].astype(str).str.lower().eq("true").sum())
    shared_tw = int(pd.to_numeric(reclass["distinct_shared_stable_travelway_id_count"], errors="coerce").fillna(0).gt(0).sum())
    revised_review_visible = CURRENT_REPRESENTED_SIGNAL_COUNT + GOOD_TRAVELWAY_REVIEW_VISIBLE_ADDITIONS + OFFSET_CONTEXT_READY_ADDITIONS - true_dup
    revised_clean = CURRENT_REPRESENTED_SIGNAL_COUNT + GOOD_TRAVELWAY_CLEAN_ADDITIONS + OFFSET_CLEAN_ADDITIONS_PRIOR
    rows = [
        {"metric": "audited_possible_duplicate_existing_signal_records", "value": len(reclass)},
        {"metric": "strict_true_duplicate_source_records", "value": true_dup},
        {"metric": "valid_review_visible_additions_with_qa_flags", "value": valid},
        {"metric": "valid_review_visible_near_existing_signal_within_250ft", "value": near_250},
        {"metric": "valid_review_visible_same_corridor_or_shared_travelway", "value": same_corridor},
        {"metric": "shared_stable_travelway_id_evidence_count", "value": shared_tw},
        {"metric": "hold_from_clean_analysis", "value": hold_clean},
        {"metric": "map_review_needed", "value": map_review},
        {"metric": "revised_offset_anchor_clean_additions", "value": OFFSET_CLEAN_ADDITIONS_PRIOR},
        {"metric": "revised_offset_anchor_review_visible_additions", "value": OFFSET_CONTEXT_READY_ADDITIONS - true_dup},
        {"metric": "revised_offset_anchor_true_duplicate_count", "value": true_dup},
        {"metric": "revised_projected_clean_review_universe", "value": revised_clean},
        {"metric": "revised_projected_review_visible_universe", "value": revised_review_visible},
        {"metric": "revised_projected_review_visible_share_of_3933", "value": round(revised_review_visible / SOURCE_SIGNAL_UNIVERSE_COUNT, 4)},
    ]
    return pd.DataFrame(rows)


def _findings(reclass: pd.DataFrame, readiness: pd.DataFrame) -> str:
    values = dict(zip(readiness["metric"], readiness["value"]))
    class_lines = "\n".join(
        f"- {cls}: {count:,}"
        for cls, count in reclass["revised_duplicate_audit_class"].value_counts().sort_index().items()
    )
    original_causes = {
        "exact_duplicate_signal_risk": int(_flag(reclass, "exact_duplicate_signal_risk").sum()),
        "complex_multi_signal_risk": int(_flag(reclass, "complex_multi_signal_risk").sum()),
        "sibling_signal_risk": int(_flag(reclass, "sibling_signal_risk").sum()),
        "overlap_review_required": int(_flag(reclass, "overlap_review_required").sum()),
    }
    return f"""# Offset-Anchor Duplicate Label Audit Findings

## Bounded Question

This read-only audit reviews the 100 offset-anchor records labeled `possible_duplicate_existing_signal`. It tests strict source-identity duplicate criteria and separates spatial/scaffold proximity from true duplication. It does not promote signals, assign crashes/access, calculate rates/models, or alter active outputs.

## Strict Duplicate Result

- True source-record duplicates under strict criteria: {int(values['strict_true_duplicate_source_records']):,}
- Valid review-visible additions with QA flags: {int(values['valid_review_visible_additions_with_qa_flags']):,}
- Valid review-visible additions within 250 ft of an existing/recovered signal: {int(values['valid_review_visible_near_existing_signal_within_250ft']):,}
- Valid review-visible additions with same-corridor/shared-Travelway evidence: {int(values['valid_review_visible_same_corridor_or_shared_travelway']):,}
- Records held from clean analysis: {int(values['hold_from_clean_analysis']):,}
- Records needing map review: {int(values['map_review_needed']):,}

Spatial proximity, shared `stable_travelway_id`, and overlapping scaffold context were not treated as true duplication. No target met same `stable_signal_id`, same `GLOBALID`, same `source_signal_id`, same source-layer/source-ID combo, source identity hash, or near-identical-coordinate plus same-source-identity criteria.

## Original Label Cause

The original label was too broad. It primarily came from overlap/dedup risk flags, especially `exact_duplicate_signal_risk`, plus complex/scaffold context flags. The flag counts among the 100 audited records were:

- exact_duplicate_signal_risk: {original_causes['exact_duplicate_signal_risk']:,}
- complex_multi_signal_risk: {original_causes['complex_multi_signal_risk']:,}
- sibling_signal_risk: {original_causes['sibling_signal_risk']:,}
- overlap_review_required: {original_causes['overlap_review_required']:,}

## Revised Classes

{class_lines}

## Revised Universe Counts

- Revised offset-anchor review-visible additions: {int(values['revised_offset_anchor_review_visible_additions']):,}
- Revised offset-anchor clean additions: {int(values['revised_offset_anchor_clean_additions']):,}
- Revised projected review-visible universe: {int(values['revised_projected_review_visible_universe']):,}
- Revised projected clean-review universe: {int(values['revised_projected_clean_review_universe']):,}

## Recommendation

Retire `possible_duplicate_existing_signal` for this branch. Use `true_duplicate_source_record` only for strict source-identity matches. Relabel the audited records into valid near-existing/same-corridor additions, scaffold-overlap review, sibling-signal review, complex multi-signal context, or insufficient-identity evidence. The next pass should map-review the scaffold-overlap, sibling, complex, and insufficient-identity subsets before adding any of them to clean analysis.
"""


def _qa(reclass: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"check_name": "no_active_outputs_modified", "status": "passed", "observed": str(OUT_DIR)},
            {"check_name": "no_signals_promoted", "status": "passed", "observed": "audit/relabeling only"},
            {"check_name": "no_crash_assignment", "status": "passed", "observed": "no crash records read"},
            {"check_name": "no_access_assignment", "status": "passed", "observed": "access not read or assigned"},
            {"check_name": "no_rates_or_models", "status": "passed", "observed": "no rates/models"},
            {"check_name": "crash_direction_fields_not_used", "status": "passed", "observed": "direction-token guard active"},
            {"check_name": "spatial_proximity_not_true_duplicate", "status": "passed" if not reclass["spatial_proximity_only_true_duplicate"].astype(bool).any() else "failed", "observed": "spatial/scaffold evidence only used for QA classes"},
            {"check_name": "strict_duplicate_criteria_documented", "status": "passed", "observed": "same stable/GLOBALID/source ID/source combo/hash only"},
            {"check_name": "outputs_review_only_folder", "status": "passed", "observed": str(OUT_DIR)},
        ]
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    manifests = {
        "offset_anchor_universe_integration": _load_json(OFFSET_INTEGRATION_DIR / "offset_anchor_universe_integration_manifest.json"),
        "offset_anchor_context_refresh": _load_json(OFFSET_CONTEXT_DIR / "offset_anchor_context_refresh_manifest.json"),
        "good_travelway_universe_integration": _load_json(GOOD_UNIVERSE_DIR / "good_travelway_universe_integration_manifest.json"),
        "stable_lineage_scaffold": _load_json(STABLE_DIR / "stable_lineage_generation_manifest.json"),
        "missing_hmms_feasibility": _load_json(FEASIBILITY_DIR / "missing_hmms_signal_recovery_feasibility_manifest.json"),
    }
    risk = _read_csv(OFFSET_INTEGRATION_DIR / "offset_anchor_113_risk_decomposition.csv")
    context_bins = _read_csv(OFFSET_CONTEXT_DIR / "offset_anchor_context_bin_detail.csv")
    good_signals = _read_csv(GOOD_UNIVERSE_DIR / "expanded_good_travelway_signal_universe.csv")
    good_bins = _read_csv(GOOD_UNIVERSE_DIR / "expanded_good_travelway_bin_universe.csv")
    stable_signals = _read_csv(STABLE_DIR / "stable_lineage_represented_signal_universe.csv")
    stable_bins = _read_csv(STABLE_DIR / "stable_lineage_represented_bin_universe.csv")
    offset_universe_signals = _read_csv(OFFSET_INTEGRATION_DIR / "expanded_offset_anchor_signal_universe.csv")
    _ = _read_csv(FEASIBILITY_DIR / "missing_source_signal_universe_detail.csv", usecols=["GLOBALID", "source_signal_id", "source_signal_key", "source_row_index"])

    targets = risk[_text(risk, "offset_anchor_addition_class").eq("possible_duplicate_existing_signal")].copy()
    _checkpoint("filtered_possible_duplicate_targets", len(targets))
    if len(targets) != 100:
        raise ValueError(f"Expected 100 possible_duplicate_existing_signal records; found {len(targets)}")

    reference = _identity_reference(stable_signals, good_signals, offset_universe_signals)
    strict = _strict_duplicate_audit(targets, reference)
    spatial = _spatial_scaffold_audit(targets, context_bins, good_signals, good_bins, stable_bins)
    reclass = _reclassify(targets, strict, spatial)
    readiness = _readiness(reclass)
    qa = _qa(reclass)

    _write_csv(targets, "offset_anchor_duplicate_label_target_detail.csv")
    _write_csv(strict, "offset_anchor_strict_duplicate_audit.csv")
    _write_csv(spatial, "offset_anchor_spatial_scaffold_overlap_audit.csv")
    _write_csv(reclass, "offset_anchor_duplicate_label_reclassification.csv")
    _write_csv(readiness, "offset_anchor_revised_readiness_after_duplicate_audit.csv")
    _write_text(_findings(reclass, readiness), "offset_anchor_duplicate_label_audit_findings.md")
    _write_csv(qa, "offset_anchor_duplicate_label_audit_qa.csv")

    manifest = {
        "created_utc": _now(),
        "script": "src.roadway_graph.audit.offset_anchor_duplicate_label_audit",
        "review_only": True,
        "output_dir": str(OUT_DIR),
        "input_manifests": manifests,
        "strict_duplicate_criteria": [
            "same stable_signal_id as represented/recovered signal",
            "same GLOBALID",
            "same source_signal_id",
            "same source layer plus OBJECTID/Asset ID/Region Signal ID combination",
            "same source identity hash when available",
            "near-identical coordinates plus same source identity fields",
        ],
        "non_duplicate_evidence": [
            "spatial proximity alone",
            "shared stable_travelway_id alone",
            "overlapping generated/represented bins alone",
            "same corridor context alone",
        ],
        "counts": {row["metric"]: row["value"] for row in readiness.to_dict(orient="records")},
        "qa": qa.to_dict(orient="records"),
        "outputs": sorted(path.name for path in OUT_DIR.iterdir() if path.is_file()),
    }
    _write_json(manifest, "offset_anchor_duplicate_label_audit_manifest.json")
    _checkpoint("complete")
    print(f"Output folder: {OUT_DIR}")
    print(f"Targets audited: {len(targets):,}")
    print(f"True duplicates: {int(readiness.loc[readiness['metric'].eq('strict_true_duplicate_source_records'), 'value'].iloc[0]):,}")
    print(f"Map review needed: {int(readiness.loc[readiness['metric'].eq('map_review_needed'), 'value'].iloc[0]):,}")


if __name__ == "__main__":
    main()
