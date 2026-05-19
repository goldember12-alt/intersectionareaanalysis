from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/urban_rural_context_inventory")
IDENTITY_DIR = OUTPUT_ROOT / "review/current/roadway_identity_metadata_propagation"

INPUTS = {
    "normalized_roads": Path("artifacts/normalized/roads.parquet"),
    "staged_roads": Path("artifacts/staging/roads.parquet"),
    "normalized_aadt": Path("artifacts/normalized/aadt.parquet"),
    "normalized_speed": Path("artifacts/normalized/speed.parquet"),
    "normalized_access": Path("artifacts/normalized/access.parquet"),
    "normalized_crashes": Path("artifacts/normalized/crashes.parquet"),
    "directional_bins_identity_enriched": IDENTITY_DIR / "directional_bins_identity_enriched.csv",
    "base_bins_identity_enriched": IDENTITY_DIR / "base_bins_identity_enriched.csv",
    "directional_segments_identity_enriched": IDENTITY_DIR / "directional_segments_identity_enriched.csv",
    "aadt_source_schema": OUTPUT_ROOT / "review/current/aadt_source_staging/aadt_source_schema.csv",
    "speed_source_schema": OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_schema.csv",
}

FIELD_PATTERNS = (
    "URBAN",
    "RURAL",
    "URBAN_CODE",
    "AREA_TYPE",
    "JURISDICTION",
    "JURIS",
    "DISTRICT",
    "COUNTY",
    "MUNICIPALITY",
    "MUNIC",
    "MPO",
    "FED_FUNC_CLASS",
    "FUNC",
    "CLASS",
)

KEY_PATTERNS = ("source_road_row_id", "source_bin_key", "base_segment_id", "reference_directional_bin_id", "RTE_NM", "RTE_COMMON", "ROUTE_COMMON_NAME", "EVENT_SOURCE_ID")


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _columns(path: Path) -> list[str]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".parquet":
        return pq.ParquetFile(path).schema_arrow.names
    return pd.read_csv(path, nrows=0).columns.tolist()


def _read_sample(path: Path, columns: list[str], nrows: int = 5000) -> pd.DataFrame:
    if not path.exists() or not columns:
        return pd.DataFrame(columns=columns)
    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path, columns=[column for column in columns if column != "geometry"])
        return pd.DataFrame(frame.drop(columns=["geometry"], errors="ignore")).head(nrows)
    return pd.read_csv(path, usecols=columns, dtype=str, keep_default_na=False, nrows=nrows)


def _candidate_role(column: str) -> str:
    upper = column.upper()
    if "URBAN" in upper or "RURAL" in upper:
        return "direct_urban_rural_candidate"
    if upper == "AREA_TYPE":
        return "crash_area_type_not_roadway_truth"
    if "FUNC" in upper or "CLASS" in upper:
        return "functional_class_candidate"
    if "MPO" in upper:
        return "planning_area_context_candidate"
    if "JURIS" in upper or "DISTRICT" in upper or "COUNTY" in upper or "MUNIC" in upper:
        return "geographic_context_not_urban_rural"
    return "context_candidate"


def _field_candidates() -> pd.DataFrame:
    rows = []
    for table, path in INPUTS.items():
        cols = _columns(path)
        candidate_cols = [column for column in cols if any(pattern in column.upper() for pattern in FIELD_PATTERNS)]
        sample = _read_sample(path, candidate_cols)
        for column in candidate_cols:
            values = sample[column].map(lambda value: str(value).strip()) if column in sample.columns else pd.Series(dtype=str)
            nonmissing = values.loc[values.ne("") & ~values.str.upper().isin(["NAN", "NONE", "<NA>", "NULL"])].map(str)
            rows.append(
                {
                    "table_name": table,
                    "path": str(path),
                    "field_name": column,
                    "field_role": _candidate_role(column),
                    "field_present": True,
                    "sample_nonmissing_count": int(len(nonmissing)),
                    "sample_unique_count": int(nonmissing.nunique()),
                    "sample_values": " | ".join([str(value) for value in nonmissing.drop_duplicates().head(10).tolist()]),
                    "already_present_in_enriched_bins": table == "directional_bins_identity_enriched",
                    "recommended_for_urban_rural": False,
                    "recommendation_notes": "",
                }
            )
        if not candidate_cols:
            rows.append(
                {
                    "table_name": table,
                    "path": str(path),
                    "field_name": "",
                    "field_role": "no_candidate_fields_found",
                    "field_present": False,
                    "sample_nonmissing_count": 0,
                    "sample_unique_count": 0,
                    "sample_values": "",
                    "already_present_in_enriched_bins": False,
                    "recommended_for_urban_rural": False,
                    "recommendation_notes": "",
                }
            )
    return pd.DataFrame(rows)


def _source_inventory(fields: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for table, path in INPUTS.items():
        rows.append(
            {
                "table_name": table,
                "path": str(path),
                "exists": path.exists(),
                "column_count": len(_columns(path)),
                "candidate_field_count": int(fields.loc[fields["table_name"].eq(table) & fields["field_present"].astype(bool), "field_name"].nunique()),
                "has_direct_urban_rural_field": bool(fields.loc[fields["table_name"].eq(table), "field_role"].eq("direct_urban_rural_candidate").any()),
                "has_crash_area_type": bool(fields.loc[fields["table_name"].eq(table), "field_name"].str.upper().eq("AREA_TYPE").any()),
                "notes": "crash AREA_TYPE is crash-context evidence only, not roadway-level urban/rural truth" if table == "normalized_crashes" else "",
            }
        )
    return pd.DataFrame(rows)


def _join_key_candidates() -> pd.DataFrame:
    rows = []
    enriched_cols = set(_columns(INPUTS["directional_bins_identity_enriched"]))
    for table, path in INPUTS.items():
        cols = _columns(path)
        for column in cols:
            if column in enriched_cols or any(pattern.upper() in column.upper() for pattern in KEY_PATTERNS):
                rows.append(
                    {
                        "table_name": table,
                        "path": str(path),
                        "field_name": column,
                        "present_in_enriched_bins": column in enriched_cols,
                        "join_key_candidate": column in enriched_cols or column in KEY_PATTERNS,
                        "notes": "candidate only; no urban/rural source recommended unless a roadway-level class field exists",
                    }
                )
    return pd.DataFrame(rows)


def _recommendation(fields: pd.DataFrame) -> pd.DataFrame:
    direct = fields.loc[fields["field_role"].eq("direct_urban_rural_candidate") & fields["field_present"].astype(bool)].copy()
    roadway_direct = direct.loc[direct["table_name"].isin(["normalized_roads", "staged_roads", "directional_bins_identity_enriched", "base_bins_identity_enriched", "directional_segments_identity_enriched"])]
    if not roadway_direct.empty:
        row = roadway_direct.iloc[0]
        return pd.DataFrame(
            [
                {
                    "recommendation": "use_existing_roadway_level_field",
                    "best_source_table": row["table_name"],
                    "best_source_field": row["field_name"],
                    "field_already_present_in_enriched_bins": bool(row["already_present_in_enriched_bins"]),
                    "separate_join_needed": not bool(row["already_present_in_enriched_bins"]),
                    "recommended_method": "join by source_road_row_id/base_segment_id/source_bin_key as appropriate",
                    "use_in_combined_table_now": True,
                    "notes": "Roadway-level direct urban/rural field found.",
                }
            ]
        )
    return pd.DataFrame(
        [
            {
                "recommendation": "source_not_found",
                "best_source_table": "",
                "best_source_field": "",
                "field_already_present_in_enriched_bins": False,
                "separate_join_needed": False,
                "recommended_method": "include null urban/rural fields and urban_rural_context_status=source_not_found in combined table; add Census urban area, VDOT classification, or another documented roadway/area source later",
                "use_in_combined_table_now": False,
                "notes": "No roadway-level urban/rural class found. Crash AREA_TYPE and AADT/speed jurisdiction/MPO fields are contextual but not roadway-level urban/rural truth.",
            }
        ]
    )


def _findings(fields: pd.DataFrame, recommendation: pd.DataFrame, outputs: dict[str, Path]) -> str:
    rec = recommendation.iloc[0].to_dict()
    found = fields.loc[fields["field_present"].astype(bool) & fields["field_name"].astype(str).ne("")]
    direct = found.loc[found["field_role"].eq("direct_urban_rural_candidate")]
    lines = [
        "# Urban/Rural Context Inventory Findings",
        "",
        "## Bounded Question",
        "",
        "Inventory available roadway and context sources for a defensible urban/rural field before assembling the combined directional-bin context table. Do not modify context tables.",
        "",
        "## Candidate Fields Found",
        "",
        f"- direct urban/rural fields: {len(direct)}",
        f"- total context candidate fields: {len(found)}",
        f"- candidate field names: {', '.join(sorted(found['field_name'].drop_duplicates().tolist())) if not found.empty else 'none'}",
        "",
        "## Source Decision",
        "",
        f"- recommendation: {rec.get('recommendation')}",
        f"- best source table: {rec.get('best_source_table') or 'none'}",
        f"- best source field: {rec.get('best_source_field') or 'none'}",
        f"- already present in enriched bins: {rec.get('field_already_present_in_enriched_bins')}",
        f"- separate join needed: {rec.get('separate_join_needed')}",
        f"- recommended method: {rec.get('recommended_method')}",
        "",
        "## Important Limitation",
        "",
        "Crash `AREA_TYPE` is available in normalized crashes, but it is crash-context evidence only and is not used as roadway-level urban/rural truth.",
        "",
        "## Files Created",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
    ]
    return "\n".join(lines)


def build_urban_rural_context_inventory(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    fields = _field_candidates()
    inventory = _source_inventory(fields)
    keys = _join_key_candidates()
    recommendation = _recommendation(fields)
    outputs = {
        "source_inventory_csv": out_dir / "urban_rural_source_inventory.csv",
        "field_candidates_csv": out_dir / "urban_rural_field_candidates.csv",
        "join_key_candidates_csv": out_dir / "urban_rural_join_key_candidates.csv",
        "recommendation_csv": out_dir / "urban_rural_context_recommendation.csv",
        "findings_md": out_dir / "urban_rural_context_inventory_findings.md",
        "manifest_json": out_dir / "urban_rural_context_inventory_manifest.json",
    }
    _write_csv(inventory, outputs["source_inventory_csv"])
    _write_csv(fields, outputs["field_candidates_csv"])
    _write_csv(keys, outputs["join_key_candidates_csv"])
    _write_csv(recommendation, outputs["recommendation_csv"])
    _write_text(_findings(fields, recommendation, outputs), outputs["findings_md"])
    _write_json(
        {
            "created_at_utc": started.isoformat(),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "bounded_question": "read-only inventory of possible roadway-level urban/rural context sources",
            "inputs": {name: str(path) for name, path in INPUTS.items()},
            "recommendation": recommendation.to_dict(orient="records"),
            "outputs": {key: str(path) for key, path in outputs.items()},
            "context_tables_modified": False,
            "crash_area_type_used_as_roadway_truth": False,
        },
        outputs["manifest_json"],
    )
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only urban/rural context source inventory.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_urban_rural_context_inventory(output_root=args.output_root)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
