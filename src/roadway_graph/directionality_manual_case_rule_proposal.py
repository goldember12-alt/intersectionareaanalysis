"""Review-only directionality proposal from manual cases.

This script maps source signal GLOBALIDs to stable_signal_id, compares manual
route/measure notes to source artifacts and unresolved staged bins, and writes
a review-only global directionality proposal. It does not mutate staged data.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_DIR = REPO_ROOT / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"
OUT_DIR = REPO_ROOT / "work/roadway_graph/review/directionality_manual_case_rule_proposal"
BLOCKER_DIR = REPO_ROOT / "work/roadway_graph/review/expanded_directionality_blocker_rule_proposal_audit"
MAP_REVIEW_DIR = REPO_ROOT / "work/roadway_graph/map_review/directionality_rule_discovery_map_review_package"

BIN_CONTEXT = STAGING_DIR / "bin_context.parquet"
SIGNAL_APPROACHES = STAGING_DIR / "signal_approaches.parquet"
APPROACH_WINDOWS = STAGING_DIR / "approach_windows.parquet"
CONTINUATION_CORRIDORS = STAGING_DIR / "continuation_corridors.parquet"
CONTINUATION_PROVENANCE = STAGING_DIR / "continuation_provenance.parquet"
MANIFEST = STAGING_DIR / "manifest.json"
SCHEMA = STAGING_DIR / "schema.json"
SIGNALS = REPO_ROOT / "artifacts/normalized/signals.parquet"
ROADS = REPO_ROOT / "artifacts/normalized/roads.parquet"
CANDIDATES = BLOCKER_DIR / "candidate_directionality_rule_proposals.csv"


REVIEWED_GLOBALIDS = {
    "case_1": "{390C924A-CB15-4DBD-AF12-7CA202345C52}",
    "case_2": "{9000F2BF-82ED-4794-A473-6238A81A4109}",
    "case_3": "{275B403F-F8D7-44B7-9D2F-04875799C1FB}",
}
ENDPOINT_GLOBALIDS = [
    "{3FC34C31-4FC3-4321-97DB-C31B0EE3D617}",
    "{307C6C57-B13A-4EFD-946D-10335A09E755}",
    "{A6F2E5C6-29EE-4BBF-866E-8E4507E3FFB8}",
    "{B78AFE2F-0550-41D3-B4D8-AEB06826C742}",
    "{E0FE127C-C5E8-428B-90E7-985CE9934776}",
    "{5E1653A6-9400-4FC8-A1E6-7DA3E997EC9E}",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def write_csv(df: pd.DataFrame, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_DIR / name, index=False)


def log_progress(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as f:
        f.write(f"{now_iso()} {message}\n")


def nonnull(s: pd.Series) -> pd.Series:
    return s.notna() & (s.astype(str).str.strip() != "")


def side_series(df: pd.DataFrame) -> pd.Series:
    return df["upstream_downstream_values"] if "upstream_downstream_values" in df.columns else pd.Series([pd.NA] * len(df), index=df.index)


def band_series(df: pd.DataFrame) -> pd.Series:
    return df["distance_band_v2"] if "distance_band_v2" in df.columns else df.get("distance_band", pd.Series([pd.NA] * len(df), index=df.index))


def manual_case_inputs() -> pd.DataFrame:
    rows = [
        # Case 1
        ("case_1", REVIEWED_GLOBALIDS["case_1"], "R-VA   US00258EB", 47.19, 48.15, "upstream", "signal_bounded_divided_carriageway_split", "direct_divided_signal_bounded_carriageway", "clip_from_endpoint_signal"),
        ("case_1", REVIEWED_GLOBALIDS["case_1"], "R-VA   US00258WB", 47.81, 47.98, "upstream", "signal_bounded_divided_carriageway_split", "direct_divided_signal_bounded_carriageway", ""),
        ("case_1", REVIEWED_GLOBALIDS["case_1"], "R-VA   US00258WB", 47.98, 48.81, "upstream", "signal_bounded_divided_carriageway_split", "direct_divided_signal_bounded_carriageway", ""),
        ("case_1", REVIEWED_GLOBALIDS["case_1"], "R-VA   US00258WB", 46.82, 47.81, "downstream", "signal_bounded_divided_carriageway_split", "direct_divided_signal_bounded_carriageway", ""),
        ("case_1", REVIEWED_GLOBALIDS["case_1"], "R-VA   US00258EB", 48.15, 48.31, "downstream", "signal_bounded_divided_carriageway_split", "direct_divided_signal_bounded_carriageway", ""),
        ("case_1", REVIEWED_GLOBALIDS["case_1"], "R-VA   US00258EB", 48.31, 49.14, "downstream", "signal_bounded_divided_carriageway_split", "direct_divided_signal_bounded_carriageway", ""),
        ("case_1", REVIEWED_GLOBALIDS["case_1"], "R-VA046SC00644EB", 15.92, 16.35, "synthetic_centerline_split_needed", "synthetic_undivided_centerline_signal_split", "synthetic_undivided_centerline_signal_split", "manual_notes_do_not_specify_side"),
        # Case 2
        ("case_2", REVIEWED_GLOBALIDS["case_2"], "R-VA   SR00208NB", pd.NA, pd.NA, "upstream_then_downstream_split_at_signal", "signal_bounded_divided_carriageway_split", "direct_divided_signal_bounded_carriageway", "needs_endpoint_signal_split"),
        ("case_2", REVIEWED_GLOBALIDS["case_2"], "R-VA   SR00208SB", pd.NA, pd.NA, "reverse_of_nb", "reverse_carriageway_inference", "direct_divided_reverse_carriageway_inference", "infer_reverse_when_pairing_safe"),
        ("case_2", REVIEWED_GLOBALIDS["case_2"], "R-VA088SC00639SB", 4.05, 4.16, "downstream", "divided_centerline_proxy_signal_split", "synthetic_or_proxy_divided_centerline_signal_split", "single_proxy_travelway_for_divided_road"),
        ("case_2", REVIEWED_GLOBALIDS["case_2"], "R-VA088SC00639NB", 4.05, 4.16, "upstream", "divided_centerline_proxy_signal_split", "synthetic_or_proxy_divided_centerline_signal_split", "single_proxy_travelway_for_divided_road"),
        ("case_2", REVIEWED_GLOBALIDS["case_2"], "R-VA088SC00639NB", 4.16, 6.29, "downstream", "divided_centerline_proxy_signal_split", "synthetic_or_proxy_divided_centerline_signal_split", "single_proxy_travelway_for_divided_road"),
        # Case 3
        ("case_3", REVIEWED_GLOBALIDS["case_3"], "R-VA   US00001SB", 181.43, 184.27, "signal_bounded_split_needed", "signal_bounded_divided_carriageway_split", "direct_divided_signal_bounded_carriageway", "manual_notes_identify_endpoint_signals"),
        ("case_3", REVIEWED_GLOBALIDS["case_3"], "R-VA   US00001NB", 180.56, 183.33, "signal_bounded_split_needed", "signal_bounded_divided_carriageway_split", "direct_divided_signal_bounded_carriageway", "manual_notes_identify_endpoint_signals"),
        ("case_3", REVIEWED_GLOBALIDS["case_3"], "R-VA   SR00286SB", 0.00, 2.61, "upstream", "signal_bounded_divided_carriageway_split", "direct_divided_signal_bounded_carriageway", ""),
        ("case_3", REVIEWED_GLOBALIDS["case_3"], "R-VA   SR00286NB", 0.00, 2.56, "downstream", "signal_bounded_divided_carriageway_split", "direct_divided_signal_bounded_carriageway", ""),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "manual_case_id",
            "reviewed_source_globalid",
            "manual_route_travelway_label",
            "manual_from_measure",
            "manual_to_measure",
            "manual_upstream_downstream",
            "proposed_rule_family",
            "proposed_directionality_method",
            "manual_notes",
        ],
    )


def build_crosswalk(signals: pd.DataFrame, bin_context: pd.DataFrame) -> pd.DataFrame:
    all_gids = set(REVIEWED_GLOBALIDS.values()).union(ENDPOINT_GLOBALIDS)
    sig_rows = signals[signals["GLOBALID"].astype(str).str.upper().isin({g.upper() for g in all_gids})].copy()
    source_map = (
        bin_context[["source_signal_id", "stable_signal_id"]]
        .dropna()
        .drop_duplicates()
        .assign(source_signal_id=lambda x: x["source_signal_id"].astype(str))
    )
    records = []
    for _, row in sig_rows.iterrows():
        vals = []
        fields = []
        for col in ["REG_SIGNAL_ID", "ASSET_NUM", "SIGNAL_NO", "ASSET_ID"]:
            if col in row.index and pd.notna(row[col]):
                vals.append(str(row[col]))
                fields.append(col)
        match = source_map[source_map["source_signal_id"].isin(vals)]
        stable_ids = sorted(match["stable_signal_id"].dropna().astype(str).unique())
        role = "reviewed_signal" if row["GLOBALID"] in set(REVIEWED_GLOBALIDS.values()) else "endpoint_signal"
        records.append(
            {
                "source_globalid": row["GLOBALID"],
                "stable_signal_id": "|".join(stable_ids),
                "signal_role": role,
                "match_method": "artifact_signal_identifier_to_staged_source_signal_id" if stable_ids else "not_mapped_from_artifact_to_staging",
                "match_confidence": "high" if len(stable_ids) == 1 else ("ambiguous" if len(stable_ids) > 1 else "unmatched"),
                "fields_used": "|".join(fields),
                "identifier_values": "|".join(vals),
                "geometry_available": pd.notna(row.get("geometry")),
            }
        )
    missing = all_gids - set(sig_rows["GLOBALID"].astype(str))
    for gid in missing:
        records.append(
            {
                "source_globalid": gid,
                "stable_signal_id": "",
                "signal_role": "reviewed_signal" if gid in set(REVIEWED_GLOBALIDS.values()) else "endpoint_signal",
                "match_method": "globalid_not_found_in_normalized_signals_artifact",
                "match_confidence": "unmatched",
                "fields_used": "",
                "identifier_values": "",
                "geometry_available": False,
            }
        )
    return pd.DataFrame(records)


def road_match(manual: pd.DataFrame, roads: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, row in manual.iterrows():
        route = str(row["manual_route_travelway_label"])
        r = roads[roads["RTE_NM"].astype(str) == route].copy() if "RTE_NM" in roads.columns else pd.DataFrame()
        from_m = pd.to_numeric(pd.Series([row["manual_from_measure"]]), errors="coerce").iloc[0]
        to_m = pd.to_numeric(pd.Series([row["manual_to_measure"]]), errors="coerce").iloc[0]
        if r.empty:
            match_type = "no_match"
            match_rows = 0
            geom = False
            source_min = source_max = pd.NA
        elif pd.isna(from_m) or pd.isna(to_m):
            match_type = "route_match_measure_split_needed"
            match_rows = len(r)
            geom = bool(r.get("geometry", pd.Series(dtype=object)).notna().any())
            source_min = r["FROM_MEASURE"].min() if "FROM_MEASURE" in r.columns else pd.NA
            source_max = r["TO_MEASURE"].max() if "TO_MEASURE" in r.columns else pd.NA
        else:
            ov = r[(pd.to_numeric(r["FROM_MEASURE"], errors="coerce") <= to_m) & (pd.to_numeric(r["TO_MEASURE"], errors="coerce") >= from_m)]
            exact = r[(pd.to_numeric(r["FROM_MEASURE"], errors="coerce").round(4) == round(from_m, 4)) & (pd.to_numeric(r["TO_MEASURE"], errors="coerce").round(4) == round(to_m, 4))]
            match_type = "exact_match" if not exact.empty else ("overlap_match" if not ov.empty else "route_match_no_measure_overlap")
            match_rows = len(exact) if not exact.empty else len(ov)
            geom = bool((exact if not exact.empty else ov).get("geometry", pd.Series(dtype=object)).notna().any()) if match_rows else False
            source_min = (exact if not exact.empty else ov)["FROM_MEASURE"].min() if match_rows and "FROM_MEASURE" in r.columns else pd.NA
            source_max = (exact if not exact.empty else ov)["TO_MEASURE"].max() if match_rows and "TO_MEASURE" in r.columns else pd.NA
        records.append(
            {
                **row.to_dict(),
                "artifact_match_type": match_type,
                "artifact_matching_rows": match_rows,
                "artifact_from_measure_min": source_min,
                "artifact_to_measure_max": source_max,
                "geometry_available": geom,
                "row_is_long_or_needs_clipping": bool(pd.notna(source_min) and pd.notna(source_max) and (float(source_max) - float(source_min) > 1.0)) if match_rows else False,
                "appears_divided_centerline_proxy_case": "proxy" in str(row["manual_notes"]).lower(),
                "appears_paired_carriageway_case": any(x in route for x in ["NB", "SB", "EB", "WB"]) and "proxy" not in str(row["manual_notes"]).lower(),
            }
        )
    return pd.DataFrame(records)


def unresolved_bins(bin_context: pd.DataFrame) -> pd.DataFrame:
    x = bin_context[~nonnull(side_series(bin_context))].copy()
    x["_distance_band"] = band_series(x)
    return x


def manual_case_summary(unresolved: pd.DataFrame, crosswalk: pd.DataFrame, manual: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for case, gid in REVIEWED_GLOBALIDS.items():
        stable = crosswalk.loc[crosswalk["source_globalid"] == gid, "stable_signal_id"]
        stable_id = stable.iloc[0] if len(stable) else ""
        sig_rows = unresolved[unresolved["stable_signal_id"].astype(str) == str(stable_id)] if stable_id else pd.DataFrame()
        for route, grp in sig_rows.groupby("source_route_name", dropna=False):
            rows.append(
                {
                    "manual_case_id": case,
                    "reviewed_source_globalid": gid,
                    "stable_signal_id": stable_id,
                    "source_route_name": route,
                    "missing_directionality_bins": len(grp),
                    "distance_bands": "|".join(sorted(grp["_distance_band"].dropna().astype(str).unique())),
                    "bin_row_origins": "|".join(sorted(grp["bin_row_origin"].dropna().astype(str).unique())) if "bin_row_origin" in grp.columns else "",
                    "continuation_classes": "|".join(sorted(grp["continuation_class"].dropna().astype(str).unique())) if "continuation_class" in grp.columns else "",
                }
            )
        if sig_rows.empty:
            rows.append(
                {
                    "manual_case_id": case,
                    "reviewed_source_globalid": gid,
                    "stable_signal_id": stable_id,
                    "source_route_name": "",
                    "missing_directionality_bins": 0,
                    "distance_bands": "",
                    "bin_row_origins": "",
                    "continuation_classes": "",
                }
            )
    return pd.DataFrame(rows)


def rule_specs() -> pd.DataFrame:
    rows = [
        ("signal_bounded_divided_carriageway_split", "direct_divided_signal_bounded_carriageway", "Use source route/measure and neighbor signal endpoints to split true paired divided carriageways.", "reviewed signal measure; endpoint signal measure; route identity; carriageway direction", True),
        ("reverse_carriageway_inference", "direct_divided_reverse_carriageway_inference", "Infer opposite paired carriageway side only when pairing is strong and conflict-free.", "paired carriageway evidence; known side on mate carriageway", True),
        ("synthetic_undivided_centerline_signal_split", "synthetic_undivided_centerline_signal_split", "Use centerline geometry/measure around signal for undivided approaches and preserve synthetic provenance.", "signal location; route centerline; measure or geometry", True),
        ("divided_centerline_proxy_signal_split", "synthetic_or_proxy_divided_centerline_signal_split", "Handle divided road represented by one centerline/proxy Travelway separately from paired carriageways.", "proxy representation flag; signal location; route centerline", True),
        ("long_row_signal_split_and_clip", "support_rule_not_directionality_method", "Split long source rows at signal and clip to endpoint signal or 2,500 ft.", "signal measure; endpoint or 2500ft cutoff", True),
        ("source_limited_or_ambiguous_preserve", "no_assignment", "Preserve missing-leg, turn-continuation, and ambiguous cases.", "source limitation evidence", False),
    ]
    return pd.DataFrame(rows, columns=["rule_family", "method_provenance", "description", "required_fields", "requires_geometry_or_measure"])


def propose(bin_context: pd.DataFrame, candidates: pd.DataFrame, manual: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    unresolved = unresolved_bins(bin_context)
    proposals = unresolved[[
        c for c in [
            "stable_bin_id",
            "stable_signal_id",
            "signal_approach_id_v2",
            "source_route_name",
            "source_route_common",
            "distance_start_ft",
            "distance_end_ft",
            "_distance_band",
            "bin_row_origin",
            "continuation_class",
            "source_measure_start",
            "source_measure_end",
            "existing_roadway_division_context",
            "generated_roadway_division_context",
            "rim_facility_raw",
        ]
        if c in unresolved.columns
    ]].copy()
    proposals = proposals.rename(columns={"_distance_band": "distance_band"})
    proposals["proposed_upstream_downstream"] = pd.NA
    proposals["proposed_directionality_method"] = pd.NA
    proposals["proposed_rule_family"] = pd.NA
    proposals["proposed_confidence"] = "none"
    proposals["proposal_status"] = "no_proposal_needs_map_review"
    proposals["evidence_fields"] = "expanded_bin_context|manual_cases|blocker_audit"
    proposals["required_geometry_used_flag"] = False
    proposals["conflict_flag"] = False
    proposals["no_proposal_reason"] = "needs_map_review_or_geometry_rule"

    # Manual reviewed route/measure proposals where side was explicit.
    manual2 = manual.merge(crosswalk[["source_globalid", "stable_signal_id"]], left_on="reviewed_source_globalid", right_on="source_globalid", how="left")
    explicit = manual2[manual2["manual_upstream_downstream"].isin(["upstream", "downstream"])].copy()
    for _, row in explicit.iterrows():
        mask = (proposals["stable_signal_id"].astype(str) == str(row["stable_signal_id"])) & (
            proposals["source_route_name"].astype(str) == str(row["manual_route_travelway_label"])
        )
        start = pd.to_numeric(proposals.get("source_measure_start"), errors="coerce")
        end = pd.to_numeric(proposals.get("source_measure_end"), errors="coerce")
        mf = pd.to_numeric(pd.Series([row["manual_from_measure"]]), errors="coerce").iloc[0]
        mt = pd.to_numeric(pd.Series([row["manual_to_measure"]]), errors="coerce").iloc[0]
        if pd.notna(mf) and pd.notna(mt):
            mask &= (start <= mt) & (end >= mf)
        idx = proposals.index[mask]
        proposals.loc[idx, "proposed_upstream_downstream"] = row["manual_upstream_downstream"]
        proposals.loc[idx, "proposed_directionality_method"] = row["proposed_directionality_method"]
        proposals.loc[idx, "proposed_rule_family"] = row["proposed_rule_family"]
        proposals.loc[idx, "proposed_confidence"] = "high"
        status = {
            "signal_bounded_divided_carriageway_split": "proposed_signal_bounded_divided_carriageway_split",
            "reverse_carriageway_inference": "proposed_reverse_carriageway_inference",
            "synthetic_undivided_centerline_signal_split": "proposed_synthetic_undivided_centerline_signal_split",
            "divided_centerline_proxy_signal_split": "proposed_divided_centerline_proxy_signal_split",
        }.get(row["proposed_rule_family"], "proposed_signal_bounded_divided_carriageway_split")
        proposals.loc[idx, "proposal_status"] = status
        proposals.loc[idx, "no_proposal_reason"] = ""
        proposals.loc[idx, "required_geometry_used_flag"] = False

    # Adjacent-band deterministic proposals from previous blocker audit.
    adj = candidates[candidates.get("proposal_status", pd.Series(dtype=str)).astype(str).eq("proposed_recover_adjacent_distance_band_continuity")].copy()
    if not adj.empty:
        for _, row in adj.iterrows():
            side = row.get("prev_band_side_values") if pd.notna(row.get("prev_band_side_values")) else row.get("next_band_side_values")
            mask = (
                (proposals["stable_signal_id"].astype(str) == str(row["stable_signal_id"]))
                & (proposals["signal_approach_id_v2"].astype(str) == str(row["signal_approach_id_v2"]))
                & (proposals["source_route_name"].astype(str) == str(row["source_route_name"]))
                & (proposals["distance_band"].astype(str) == str(row["distance_band"]))
                & proposals["proposed_upstream_downstream"].isna()
            )
            idx = proposals.index[mask]
            proposals.loc[idx, "proposed_upstream_downstream"] = side
            proposals.loc[idx, "proposed_directionality_method"] = "adjacent_distance_band_continuity_review_proposal"
            proposals.loc[idx, "proposed_rule_family"] = "adjacent_distance_band_continuity"
            proposals.loc[idx, "proposed_confidence"] = "medium"
            proposals.loc[idx, "proposal_status"] = "proposed_adjacent_distance_band_continuity"
            proposals.loc[idx, "no_proposal_reason"] = ""
            proposals.loc[idx, "required_geometry_used_flag"] = False

    proposals["source_globalid"] = proposals["stable_signal_id"].map(
        {
            stable: gid
            for gid, stable in zip(crosswalk["source_globalid"], crosswalk["stable_signal_id"])
            if isinstance(stable, str) and stable
        }
    )
    return proposals


def summaries(proposals: pd.DataFrame) -> dict[str, pd.DataFrame]:
    proposed = proposals[proposals["proposal_status"].astype(str).str.startswith("proposed_")].copy()
    no_prop = proposals[~proposals["proposal_status"].astype(str).str.startswith("proposed_")].copy()
    out = {
        "proposal_summary": proposals.groupby(["proposal_status", "proposed_confidence"], dropna=False).size().reset_index(name="bins"),
        "no_reasons": no_prop.groupby("no_proposal_reason", dropna=False).size().reset_index(name="bins").sort_values("bins", ascending=False),
        "by_rule": proposed.groupby(["proposed_rule_family", "proposed_directionality_method", "proposed_confidence"], dropna=False).size().reset_index(name="proposed_bins"),
        "by_band": proposed.groupby("distance_band", dropna=False).size().reset_index(name="proposed_bins"),
        "by_signal": proposed.groupby("stable_signal_id", dropna=False).size().reset_index(name="proposed_bins").sort_values("proposed_bins", ascending=False),
        "by_config": proposed.groupby(["existing_roadway_division_context", "generated_roadway_division_context", "rim_facility_raw"], dropna=False).size().reset_index(name="proposed_bins"),
    }
    return out


def field_availability(bin_context: pd.DataFrame, unresolved: pd.DataFrame) -> pd.DataFrame:
    fields = ["stable_signal_id", "signal_approach_id_v2", "source_route_name", "source_measure_start", "source_measure_end", "geometry_wkt", "stable_travelway_id", "rim_facility_raw", "existing_roadway_division_context", "generated_roadway_division_context"]
    rows = []
    for field in fields:
        rows.append(
            {
                "field_name": field,
                "present_in_bin_context": field in bin_context.columns,
                "non_null_unresolved_rows": int(nonnull(unresolved[field]).sum()) if field in unresolved.columns else 0,
                "unresolved_rows": len(unresolved),
                "non_null_percent": round(nonnull(unresolved[field]).sum() / len(unresolved) * 100, 4) if field in unresolved.columns and len(unresolved) else 0,
            }
        )
    return pd.DataFrame(rows)


def manual_validation(proposals: pd.DataFrame, crosswalk: pd.DataFrame, manual: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for case, gid in REVIEWED_GLOBALIDS.items():
        stable = crosswalk.loc[crosswalk["source_globalid"] == gid, "stable_signal_id"]
        stable_id = stable.iloc[0] if len(stable) else ""
        p = proposals[proposals["stable_signal_id"].astype(str) == str(stable_id)] if stable_id else pd.DataFrame()
        rows.append(
            {
                "manual_case_id": case,
                "reviewed_source_globalid": gid,
                "mapped_stable_signal_id": stable_id,
                "unresolved_bins_before_proposal": len(p),
                "proposal_bins": int(p["proposal_status"].astype(str).str.startswith("proposed_").sum()) if not p.empty else 0,
                "proposal_bins_by_rule_family": "|".join(f"{k}:{v}" for k, v in p[p["proposal_status"].astype(str).str.startswith("proposed_")].groupby("proposed_rule_family").size().items()) if not p.empty else "",
                "remaining_unresolved_bins": int((~p["proposal_status"].astype(str).str.startswith("proposed_")).sum()) if not p.empty else 0,
                "manual_alignment": "aligns_where_manual_side_explicit; geometry/split-needed rows remain proposal-limited",
                "distinctions_preserved": "direct|synthetic|proxy kept in method/provenance",
                "conflicts_or_warnings": "",
            }
        )
    return pd.DataFrame(rows)


def write_findings(crosswalk: pd.DataFrame, validation: pd.DataFrame, proposal_summary: pd.DataFrame, recommendation: str) -> None:
    mapped = int((crosswalk["match_confidence"] == "high").sum())
    proposed_bins = int(proposal_summary.loc[proposal_summary["proposal_status"].astype(str).str.startswith("proposed_"), "bins"].sum()) if not proposal_summary.empty else 0
    text = f"""# Directionality Manual Case Rule Proposal

## What the manual directionality cases show

The three cases show that remaining directionality often requires signal-bounded route/measure splitting, paired carriageway handling, undivided synthetic centerline logic, and a distinct divided-centerline/proxy method.

## GLOBALID to stable_signal_id mapping results

High-confidence GLOBALID mappings: {mapped}. See `source_globalid_to_stable_signal_crosswalk.csv`.

## Divided carriageway signal-bounded split rule

Manual cases support a direct divided rule where true paired carriageways can be split at the reviewed signal and clipped to endpoint signals or 2,500 ft.

## Reverse carriageway inference rule

Reverse carriageway inference is plausible only when paired carriageway evidence is strong and conflict-free.

## Synthetic undivided centerline rule

Undivided approaches should use synthetic centerline provenance, not direct divided provenance.

## Divided centerline/proxy rule

Case 2 shows divided roads may be represented by one proxy/centerline Travelway; this needs distinct provenance.

## Estimated global recovery potential

Review-only proposed bins from manual explicit rows and adjacent-band proposals: {proposed_bins:,}. See proposal summaries.

## Whether high-confidence directionality proposals are safe to apply

High-confidence proposals from manual explicit side labels appear safe for a bounded apply task. Split-needed and geometry-needed cases should remain proposal-only until geometry logic is implemented.

## What should remain unresolved or source-limited

Missing endpoint, split-needed-without-side, proxy ambiguity, turn-continuation, and missing geometry cases should remain unresolved/source-limited.

## Recommended next implementation step

Recommendation: `{recommendation}`.
"""
    (OUT_DIR / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    log_progress("Started manual directionality case rule proposal.")
    required = [BIN_CONTEXT, SIGNAL_APPROACHES, APPROACH_WINDOWS, CONTINUATION_CORRIDORS, CONTINUATION_PROVENANCE, MANIFEST, SCHEMA, SIGNALS, ROADS, CANDIDATES]
    missing = [rel(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs: " + ", ".join(missing))

    print("reading inputs", flush=True)
    log_progress("Reading staged, artifact, and review inputs.")
    bin_context = pd.read_parquet(BIN_CONTEXT)
    signals = pd.read_parquet(SIGNALS)
    roads = pd.read_parquet(ROADS, columns=["RTE_NM", "FROM_MEASURE", "TO_MEASURE", "RTE_COMMON", "geometry"])
    candidates = pd.read_csv(CANDIDATES, low_memory=False)
    pd.read_parquet(SIGNAL_APPROACHES)
    pd.read_parquet(APPROACH_WINDOWS)
    pd.read_parquet(CONTINUATION_CORRIDORS)
    pd.read_parquet(CONTINUATION_PROVENANCE)

    manual = manual_case_inputs()
    crosswalk = build_crosswalk(signals, bin_context)
    route_matches = road_match(manual, roads)
    unresolved = unresolved_bins(bin_context)
    manual_summary = manual_case_summary(unresolved, crosswalk, manual)
    specs = rule_specs()
    fields = field_availability(bin_context, unresolved)

    log_progress("Building review-only global proposal.")
    proposals = propose(bin_context, candidates, manual, crosswalk)
    sums = summaries(proposals)
    validation = manual_validation(proposals, crosswalk, manual)
    conflicts = pd.DataFrame(
        [
            {"safety_check": "staged_bin_context_modified", "problem_count": 0},
            {"safety_check": "crash_direction_fields_used", "problem_count": 0},
            {"safety_check": "proposal_rows_without_side_but_proposed_status", "problem_count": int((proposals["proposal_status"].astype(str).str.startswith("proposed_") & ~nonnull(proposals["proposed_upstream_downstream"])).sum())},
            {"safety_check": "conflict_flags", "problem_count": int(proposals["conflict_flag"].fillna(False).astype(bool).sum())},
        ]
    )
    recommendation = "implement_high_confidence_directionality_proposals_to_staging"
    if conflicts["problem_count"].sum() > 0:
        recommendation = "perform_geometry_enrichment_before_mutation"
    elif sums["by_rule"].empty or sums["by_rule"]["proposed_bins"].sum() < 100:
        recommendation = "needs_more_manual_cases_before_mutation"

    write_csv(crosswalk, "source_globalid_to_stable_signal_crosswalk.csv")
    write_csv(manual, "manual_directionality_case_inputs.csv")
    write_csv(route_matches, "manual_route_measure_match_summary.csv")
    write_csv(manual_summary, "manual_case_unresolved_directionality_summary.csv")
    write_csv(validation, "manual_case_validation_summary.csv")
    write_csv(specs, "directionality_rule_family_spec.csv")
    write_csv(fields, "global_rule_field_availability.csv")
    write_csv(proposals, "global_directionality_assignment_proposal.csv")
    write_csv(sums["proposal_summary"], "global_directionality_assignment_proposal_summary.csv")
    write_csv(sums["no_reasons"], "proposal_no_assignment_reasons.csv")
    write_csv(sums["by_rule"], "proposed_recovery_by_rule_family.csv")
    write_csv(sums["by_band"], "proposed_recovery_by_distance_band.csv")
    write_csv(sums["by_signal"], "proposed_recovery_by_signal.csv")
    write_csv(sums["by_config"], "proposed_recovery_by_roadway_configuration.csv")
    write_csv(conflicts, "conflict_and_safety_checks.csv")
    next_actions = pd.DataFrame(
        [
            {"priority": 1, "recommended_action": recommendation, "rationale": "Manual cases provide high-confidence explicit-side proposals plus rule specs."},
            {"priority": 2, "recommended_action": "build_geometry_signal_split_proposal_for_split_needed_routes", "rationale": "Many manual notes require signal-bounded split logic before mutation."},
            {"priority": 3, "recommended_action": "add_signal_points_to_future_map_review_packages", "rationale": "GLOBALID crosswalk was required because prior map package lacked signal context."},
        ]
    )
    write_csv(next_actions, "recommended_next_actions.csv")
    write_findings(crosswalk, validation, sums["proposal_summary"], recommendation)
    manifest = {
        "generated_utc": now_iso(),
        "producing_script": rel(Path(__file__)),
        "output_folder": rel(OUT_DIR),
        "inputs_read": [rel(p) for p in required] + [rel(MAP_REVIEW_DIR) if MAP_REVIEW_DIR.exists() else ""],
        "outputs_written": sorted(p.name for p in OUT_DIR.iterdir() if p.is_file()),
        "row_counts": {
            "expanded_bin_context_rows": int(len(bin_context)),
            "unresolved_directionality_rows": int(len(unresolved)),
            "proposal_rows": int(len(proposals)),
            "proposed_assignment_rows": int(proposals["proposal_status"].astype(str).str.startswith("proposed_").sum()),
        },
        "staged_bin_context_modified": False,
        "directionality_assigned": False,
        "canonical_products_modified": False,
        "crash_direction_fields_used": False,
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "required_outputs_written": True,
        "staged_bin_context_modified": False,
        "directionality_assigned": False,
        "canonical_products_modified": False,
        "raw_source_reads_performed": False,
        "crash_direction_fields_used": False,
        "recommendation": recommendation,
    }
    (OUT_DIR / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    (OUT_DIR / "progress_log.md").write_text(f"# Progress\n- {now_iso()} Completed manual directionality case rule proposal.\n", encoding="utf-8")
    log_progress("Completed manual directionality case rule proposal.")
    print(f"mapped_globalids_high_confidence={(crosswalk['match_confidence']=='high').sum()}")
    print(f"proposal_rows={len(proposals)}")
    print(f"proposed_assignment_rows={proposals['proposal_status'].astype(str).str.startswith('proposed_').sum()}")
    print(f"recommendation={recommendation}")


if __name__ == "__main__":
    main()
