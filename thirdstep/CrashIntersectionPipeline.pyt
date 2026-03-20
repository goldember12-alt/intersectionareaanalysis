# -*- coding: utf-8 -*-
import os
import runpy
import arcpy
import traceback
import time

# Refactored thirdstep module directory
THIRDSTEP_MODULE_DIR = r"C:\Users\Jameson.Clements\IntersectionCrashAnalysis\thirdstep\thirdstep_module_refactor"

# Project-level helpers / optional scripts
PROJECT_ROOT = r"C:\Users\Jameson.Clements\IntersectionCrashAnalysis"
THIRDSTEP_PARENT_DIR = r"C:\Users\Jameson.Clements\IntersectionCrashAnalysis\thirdstep"

CLEAR_SCRIPT = os.path.join(PROJECT_ROOT, "clearinggdb.py")
THIRDSTEP_ENTRY = os.path.join(THIRDSTEP_MODULE_DIR, "thirdstep.py")
FIGURES_SCRIPT = os.path.join(THIRDSTEP_PARENT_DIR, "thirdstepfigures.py")

REQUIRED_MODULE_FILES = [
    "config.py",
    "logging_utils.py",
    "arcpy_utils.py",
    "field_normalization.py",
    "backfill.py",
    "geometry_pipeline.py",
    "assignments.py",
    "geopandas_oracle.py",
    "writeback_qc.py",
    "thirdstep.py",
]

ENV_PARAM_MAP = {
    "THIRDSTEP_PHASE_START": "phase_start",
    "THIRDSTEP_PHASE_STOP": "phase_stop",
    "THIRDSTEP_REUSE_STAGED_OUTPUTS": "reuse_staged_outputs",
    "THIRDSTEP_CACHE_ROADS_STUDY_AFTER_AADT": "cache_roads_after_aadt",
    "THIRDSTEP_FORCE_ROADS_AADT_SPATIAL_ONLY": "force_spatial_only_aadt",
}


class Toolbox(object):
    def __init__(self):
        self.label = "Crash Intersection Pipeline"
        self.alias = "crashpipeline"
        self.tools = [RunPipeline]


class RunPipeline(object):
    def __init__(self):
        self.label = "Run Crash Pipeline"
        self.description = (
            "Runs clearinggdb.py (optional), refactored thirdstep module entry point, "
            "and thirdstepfigures.py (optional)."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        params = []

        run_clear = arcpy.Parameter(
            displayName="Run clearinggdb.py (Factory Reset)",
            name="run_clear_step",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input"
        )
        run_clear.value = False
        params.append(run_clear)

        run_figures = arcpy.Parameter(
            displayName="Run thirdstepfigures.py (if present)",
            name="run_figures_step",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input"
        )
        run_figures.value = False
        params.append(run_figures)

        add_output_to_map = arcpy.Parameter(
            displayName="Add final output to active map",
            name="add_output_to_map",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input"
        )
        add_output_to_map.value = True
        params.append(add_output_to_map)

        phase_start = arcpy.Parameter(
            displayName="Phase start",
            name="phase_start",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input"
        )
        phase_start.value = 1
        params.append(phase_start)

        phase_stop = arcpy.Parameter(
            displayName="Phase stop",
            name="phase_stop",
            datatype="GPLong",
            parameterType="Optional",
            direction="Input"
        )
        phase_stop.value = 10
        params.append(phase_stop)

        reuse_staged_outputs = arcpy.Parameter(
            displayName="Reuse staged outputs",
            name="reuse_staged_outputs",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input"
        )
        reuse_staged_outputs.value = False
        params.append(reuse_staged_outputs)

        cache_roads_after_aadt = arcpy.Parameter(
            displayName="Cache roads after AADT enrichment",
            name="cache_roads_after_aadt",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input"
        )
        cache_roads_after_aadt.value = True
        params.append(cache_roads_after_aadt)

        force_spatial_only_aadt = arcpy.Parameter(
            displayName="Force spatial-only road AADT enrichment",
            name="force_spatial_only_aadt",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input"
        )
        force_spatial_only_aadt.value = False
        params.append(force_spatial_only_aadt)

        return params

    def _resolve_map(self, map_name=None):
        aprx = arcpy.mp.ArcGISProject("CURRENT")

        if map_name:
            maps = [m for m in aprx.listMaps() if m.name == map_name]
            if not maps:
                raise ValueError(
                    "Map '{}' not found. Available maps: {}".format(
                        map_name, [m.name for m in aprx.listMaps()]
                    )
                )
            return maps[0]

        try:
            m = aprx.activeMap
        except Exception:
            m = None

        if m is not None:
            return m

        maps = aprx.listMaps()
        if not maps:
            raise RuntimeError("No maps found in current ArcGIS Pro project.")
        return maps[0]

    def _add_output_to_map(self, output_path, map_name=None, remove_existing=True):
        if not arcpy.Exists(output_path):
            raise FileNotFoundError("Output does not exist: {}".format(output_path))

        m = self._resolve_map(map_name=map_name)
        layer_name = os.path.basename(output_path)

        if remove_existing:
            for lyr in m.listLayers():
                if lyr.name == layer_name:
                    arcpy.AddMessage("Removing existing layer: {}".format(lyr.name))
                    m.removeLayer(lyr)

        arcpy.AddMessage("Adding output to map '{}': {}".format(m.name, output_path))
        m.addDataFromPath(output_path)

    def _get_bool_param(self, parameters, index, default=False):
        try:
            if parameters and len(parameters) > index:
                val = parameters[index].value
                if val is None:
                    return default
                return bool(val)
        except Exception:
            pass
        return default

    def _get_int_param(self, parameters, index, default=None):
        try:
            if parameters and len(parameters) > index:
                val = parameters[index].value
                if val in (None, ""):
                    return default
                return int(val)
        except Exception:
            pass
        return default

    def _validate_module_layout(self):
        if not os.path.isdir(THIRDSTEP_MODULE_DIR):
            raise FileNotFoundError(
                "Refactored thirdstep module directory not found: {}".format(THIRDSTEP_MODULE_DIR)
            )

        missing = []
        for name in REQUIRED_MODULE_FILES:
            path = os.path.join(THIRDSTEP_MODULE_DIR, name)
            if not os.path.exists(path):
                missing.append(path)

        if missing:
            raise FileNotFoundError(
                "Refactored thirdstep module is incomplete. Missing files:\n{}".format(
                    "\n".join(missing)
                )
            )

    def _run_script(self, name, path):
        if not os.path.exists(path):
            raise FileNotFoundError("Missing script: {}".format(path))

        t_step = time.time()
        arcpy.AddMessage("------------------------------------------------------------")
        arcpy.AddMessage("Starting step: {}".format(name))
        arcpy.AddMessage("Script: {}".format(path))

        cwd_before = os.getcwd()
        try:
            script_dir = os.path.dirname(path)
            if script_dir:
                os.chdir(script_dir)
            runpy.run_path(path, run_name="__main__")
        except Exception:
            arcpy.AddError("FAILED in step: {}".format(name))
            arcpy.AddError(traceback.format_exc())
            raise
        finally:
            try:
                os.chdir(cwd_before)
            except Exception:
                pass

        arcpy.AddMessage("Finished step: {} in {:.2f}s".format(name, time.time() - t_step))

    def _set_debug_env(self, phase_start, phase_stop, reuse_staged_outputs, cache_roads_after_aadt, force_spatial_only_aadt):
        prev = {k: os.environ.get(k) for k in ENV_PARAM_MAP.keys()}
        os.environ["THIRDSTEP_PHASE_START"] = str(int(phase_start))
        os.environ["THIRDSTEP_PHASE_STOP"] = str(int(phase_stop))
        os.environ["THIRDSTEP_REUSE_STAGED_OUTPUTS"] = "1" if reuse_staged_outputs else "0"
        os.environ["THIRDSTEP_CACHE_ROADS_STUDY_AFTER_AADT"] = "1" if cache_roads_after_aadt else "0"
        os.environ["THIRDSTEP_FORCE_ROADS_AADT_SPATIAL_ONLY"] = "1" if force_spatial_only_aadt else "0"
        return prev

    def _restore_debug_env(self, prev):
        for key, old in prev.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old

    def execute(self, parameters, messages):
        t0 = time.time()
        arcpy.AddMessage("Execute started")

        run_clear = self._get_bool_param(parameters, 0, default=False)
        run_figures = self._get_bool_param(parameters, 1, default=False)
        add_output_to_map = self._get_bool_param(parameters, 2, default=True)
        phase_start = self._get_int_param(parameters, 3, default=1)
        phase_stop = self._get_int_param(parameters, 4, default=10)
        reuse_staged_outputs = self._get_bool_param(parameters, 5, default=False)
        cache_roads_after_aadt = self._get_bool_param(parameters, 6, default=True)
        force_spatial_only_aadt = self._get_bool_param(parameters, 7, default=False)

        if phase_start < 1:
            phase_start = 1
        if phase_stop > 10:
            phase_stop = 10
        if phase_stop < phase_start:
            raise ValueError("Phase stop must be greater than or equal to phase start.")

        arcpy.AddMessage("Run clear step: {}".format(run_clear))
        arcpy.AddMessage("Run figures step: {}".format(run_figures))
        arcpy.AddMessage("Add output to map: {}".format(add_output_to_map))
        arcpy.AddMessage("Phase start: {}".format(phase_start))
        arcpy.AddMessage("Phase stop: {}".format(phase_stop))
        arcpy.AddMessage("Reuse staged outputs: {}".format(reuse_staged_outputs))
        arcpy.AddMessage("Cache roads after AADT enrichment: {}".format(cache_roads_after_aadt))
        arcpy.AddMessage("Force spatial-only road AADT enrichment: {}".format(force_spatial_only_aadt))

        arcpy.env.overwriteOutput = True

        try:
            arcpy.env.addOutputsToMap = True
        except Exception:
            pass

        try:
            arcpy.env.scratchWorkspace = arcpy.env.scratchGDB
        except Exception:
            pass

        try:
            arcpy.env.parallelProcessingFactor = "100%"
        except Exception:
            pass

        arcpy.AddMessage("After env setup: {:.2f}s".format(time.time() - t0))

        self._validate_module_layout()

        arcpy.AddMessage("Project root: {}".format(PROJECT_ROOT))
        arcpy.AddMessage("thirdstep parent dir: {}".format(THIRDSTEP_PARENT_DIR))
        arcpy.AddMessage("Refactored module dir: {}".format(THIRDSTEP_MODULE_DIR))
        arcpy.AddMessage("thirdstep entry point: {}".format(THIRDSTEP_ENTRY))
        arcpy.AddMessage("Workspace: {}".format(arcpy.env.workspace))
        arcpy.AddMessage("ScratchGDB: {}".format(arcpy.env.scratchGDB))
        arcpy.AddMessage("ScratchWorkspace: {}".format(arcpy.env.scratchWorkspace))

        prev_env = self._set_debug_env(
            phase_start,
            phase_stop,
            reuse_staged_outputs,
            cache_roads_after_aadt,
            force_spatial_only_aadt,
        )

        try:
            if run_clear:
                self._run_script("clear", CLEAR_SCRIPT)

            self._run_script("thirdstep", THIRDSTEP_ENTRY)

            if run_figures:
                if os.path.exists(FIGURES_SCRIPT):
                    self._run_script("figures", FIGURES_SCRIPT)
                else:
                    arcpy.AddWarning("Skipping optional step; script not found: {}".format(FIGURES_SCRIPT))
        finally:
            self._restore_debug_env(prev_env)

        final_segments_name = "Final_Functional_Segments"
        final_signals_name = "Final_Study_Signals"
        final_zones_name = "Final_Functional_Zones_Stage3"

        final_segments = os.path.join(arcpy.env.workspace, final_segments_name)
        final_signals = os.path.join(arcpy.env.workspace, final_signals_name)
        final_zones = os.path.join(arcpy.env.workspace, final_zones_name)

        arcpy.AddMessage("------------------------------------------------------------")
        arcpy.AddMessage("Expected final segments: {}".format(final_segments))
        arcpy.AddMessage("Expected final signals:  {}".format(final_signals))
        arcpy.AddMessage("Expected final zones:    {}".format(final_zones))

        if add_output_to_map:
            try:
                self._add_output_to_map(final_segments, map_name=None, remove_existing=True)

                if arcpy.Exists(final_signals):
                    self._add_output_to_map(final_signals, map_name=None, remove_existing=True)

                if arcpy.Exists(final_zones):
                    self._add_output_to_map(final_zones, map_name=None, remove_existing=True)

            except Exception:
                arcpy.AddWarning(
                    "Pipeline finished, but failed to add one or more outputs to the map."
                )
                arcpy.AddWarning(traceback.format_exc())

        arcpy.AddMessage("------------------------------------------------------------")
        arcpy.AddMessage("Pipeline complete in {:.2f}s".format(time.time() - t0))
