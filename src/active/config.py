from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SupplementalTrafficVolumeConfig:
    geojson_path: Path
    shapefile_dir: Path


@dataclass(frozen=True)
class InputLayer:
    key: str
    layer_name: str
    source_gdb: Path
    source_layer_name: str
    merge_sources: tuple[tuple[Path, str], ...] = ()
    active_stage: bool = True
    derived: bool = False
    notes: str | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    repo_root: Path
    config_path: Path
    raw_data_dir: Path
    staging_dir: Path
    normalized_dir: Path
    output_dir: Path
    parity_dir: Path
    working_crs: str
    stage1_entrypoint: str
    inputs: dict[str, InputLayer]
    supplemental_traffic_volume: SupplementalTrafficVolumeConfig


def get_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _require_table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Expected [{key}] table in configuration.")
    return value


def _optional_table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected [{key}] table in configuration.")
    return value


def load_runtime_config(config_path: Path | None = None) -> RuntimeConfig:
    repo_root = get_repo_root()
    resolved_config = config_path or repo_root / "config" / "stage1_portable.toml"
    data = tomllib.loads(resolved_config.read_text(encoding="utf-8"))

    project = _require_table(data, "project")
    entrypoints = _optional_table(data, "entrypoints")
    inputs_table = _require_table(data, "inputs")
    supplemental_table = _require_table(_require_table(data, "supplemental"), "traffic_volume")

    inputs: dict[str, InputLayer] = {}
    for key, layer_data in inputs_table.items():
        if not isinstance(layer_data, dict):
            raise ValueError(f"Expected [inputs.{key}] table in configuration.")
        layer_name = str(layer_data["layer_name"])
        source_gdb = repo_root / str(project["raw_data_dir"]) / str(layer_data["source_gdb"])
        merge_sources = tuple(
            (repo_root / str(project["raw_data_dir"]) / item.split("|", 1)[0], item.split("|", 1)[1])
            for item in layer_data.get("merge_sources", [])
        )
        inputs[key] = InputLayer(
            key=key,
            layer_name=layer_name,
            source_gdb=source_gdb,
            source_layer_name=str(layer_data.get("source_layer_name", layer_name)),
            merge_sources=merge_sources,
            active_stage=bool(layer_data.get("active_stage", True)),
            derived=bool(layer_data.get("derived", False)),
            notes=str(layer_data["notes"]) if "notes" in layer_data else None,
        )

    return RuntimeConfig(
        repo_root=repo_root,
        config_path=resolved_config,
        raw_data_dir=repo_root / str(project["raw_data_dir"]),
        staging_dir=repo_root / str(project["staging_dir"]),
        normalized_dir=repo_root / str(project["normalized_dir"]),
        output_dir=repo_root / str(project["output_dir"]),
        parity_dir=repo_root / str(project["parity_dir"]),
        working_crs=str(project["working_crs"]),
        stage1_entrypoint=str(entrypoints.get("stage1", "python -m src")),
        inputs=inputs,
        supplemental_traffic_volume=SupplementalTrafficVolumeConfig(
            geojson_path=repo_root / str(project["raw_data_dir"]) / str(supplemental_table["geojson_path"]),
            shapefile_dir=repo_root / str(project["raw_data_dir"]) / str(supplemental_table["shapefile_dir"]),
        ),
    )
