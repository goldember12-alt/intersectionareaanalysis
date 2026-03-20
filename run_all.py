import os
import runpy
import traceback
from datetime import datetime

def _print(msg):
    try:
        import arcpy
        arcpy.AddMessage(msg)
    except Exception:
        pass
    print(msg)

def run_script(path):
    _print("\n" + "=" * 80)
    _print(f"RUNNING: {path}")
    _print("=" * 80)
    runpy.run_path(path, run_name="__main__")
    _print(f"DONE: {os.path.basename(path)}")

def add_output_to_map(output_path, map_name=None, remove_existing=True, zoom_to_layer=False):
    """
    Add the final output dataset to the current ArcGIS Pro map.

    Parameters
    ----------
    output_path : str
        Full path to a feature class, shapefile, layer file, etc.
    map_name : str or None
        If provided, add to this map name. Otherwise uses activeMap if available,
        else the first map in the project.
    remove_existing : bool
        If True, removes any existing layer with the same name before adding.
    zoom_to_layer : bool
        If True, attempts to zoom the active view to the new layer.
    """
    import arcpy

    if not arcpy.Exists(output_path):
        raise FileNotFoundError(f"Output does not exist or ArcGIS cannot read it: {output_path}")

    aprx = arcpy.mp.ArcGISProject("CURRENT")

    # Pick the target map
    m = None
    if map_name:
        matches = [mp for mp in aprx.listMaps() if mp.name == map_name]
        if not matches:
            raise ValueError(
                f"Map named '{map_name}' not found. Available maps: "
                f"{[mp.name for mp in aprx.listMaps()]}"
            )
        m = matches[0]
    else:
        try:
            m = aprx.activeMap
        except Exception:
            m = None

        if m is None:
            maps = aprx.listMaps()
            if not maps:
                raise RuntimeError("No maps found in the current ArcGIS Pro project.")
            m = maps[0]

    layer_name = os.path.basename(output_path)

    if remove_existing:
        for lyr in m.listLayers():
            if lyr.name == layer_name:
                _print(f"Removing existing layer from map: {lyr.name}")
                m.removeLayer(lyr)

    _print(f"Adding output to map '{m.name}': {output_path}")
    m.addDataFromPath(output_path)

    if zoom_to_layer:
        try:
            mv = aprx.activeView
            if hasattr(mv, "map") and mv.map.name == m.name:
                new_layer = None
                for lyr in m.listLayers():
                    if lyr.name == layer_name:
                        new_layer = lyr
                        break
                if new_layer:
                    mv.camera.setExtent(mv.getLayerExtent(new_layer, False, True))
        except Exception as e:
            _print(f"Could not zoom to layer: {e}")

def main(skip_clear=False, stop_after=None):
    """
    stop_after can be: None, 'clear', 'secondstep', 'figures'
    """
    here = os.path.dirname(os.path.abspath(__file__))

    clearing = os.path.join(here, "clearinggdb.py")
    secondstep = os.path.join(here, "secondstep", "secondstep.py")
    figures = os.path.join(here, "secondstep", "secondstepfigures.py")

    steps = [
        ("clear", clearing),
        ("secondstep", secondstep),
        ("figures", figures),
    ]

    _print(f"Started: {datetime.now().isoformat(timespec='seconds')}")

    for name, path in steps:
        path = os.path.abspath(path)

        if name == "clear" and skip_clear:
            _print(f"SKIPPING: {path}")
            continue

        if not os.path.exists(path):
            raise FileNotFoundError(f"Missing script: {path}")

        run_script(path)

        if stop_after == name:
            _print(f"\nStopping after step '{name}' by request.")
            break

    # ------------------------------------------------------------------
    # SET THIS to your actual final output feature class / layer path
    # Examples:
    # final_output = os.path.join(here, "IntersectionCrashAnalysis.gdb", "FinalLayer")
    # final_output = os.path.join(here, "secondstep", "outputs", "FinalLayer.shp")
    # ------------------------------------------------------------------
    final_output = os.path.join(here, "IntersectionCrashAnalysis.gdb", "FinalLayer")

    # Optional: set map name explicitly if you do not want to rely on activeMap
    target_map_name = None
    # Example:
    # target_map_name = "Map"

    if stop_after is None or stop_after == "figures":
        try:
            add_output_to_map(
                output_path=final_output,
                map_name=target_map_name,
                remove_existing=True,
                zoom_to_layer=False
            )
        except Exception as e:
            _print(f"WARNING: Pipeline completed, but failed to add final layer to map: {e}")

    _print(f"\nPipeline finished: {datetime.now().isoformat(timespec='seconds')}")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        _print("\n!!! PIPELINE FAILED !!!")
        traceback.print_exc()
        raise