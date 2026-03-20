import arcpy
import os

# ==============================================================================
# CONFIGURATION
# ==============================================================================
source_folder = r"C:\Users\Jameson.Clements\Downloads\Intersection Crash Analysis Layers"

p = arcpy.mp.ArcGISProject("CURRENT")
m = p.activeMap
project_gdb = p.defaultGeodatabase

arcpy.env.overwriteOutput = True

# ------------------------------------------------------------------------------
# Manifest of authoritative source geodatabases
# ------------------------------------------------------------------------------
SOURCE_GDBS = [
    "accesspoints.gdb",
    "crashdata.gdb",
    "HMMS_Traffic_Signals.gdb",
    "New_AADT.gdb",
    "postedspeedlimits.gdb",
    "Travelway.gdb",
    "Hampton_Analysis.gdb",
    "Traffic_Signals_-_City_of_Norfolk.gdb"
]

# ------------------------------------------------------------------------------
# Optional explicit manifest:
# If None, the script will auto-discover all FCs/tables in the listed source GDBs
# and treat them as canonical base datasets.
#
# If you want tighter control, replace None with a dict like:
# {
#     "feature_classes": {"RoadCenterlines", "CrashPoints", ...},
#     "tables": {"AADT_Table", ...}
# }
# ------------------------------------------------------------------------------
EXPLICIT_BASE_MANIFEST = None

# ------------------------------------------------------------------------------
# Derived outputs allowed to exist in the project GDB
# These should NOT be deleted as extras.
# ------------------------------------------------------------------------------
ALLOWED_DERIVED_DATASETS = {
    "Master_Signal_Layer"
}

# ------------------------------------------------------------------------------
# Datasets used to create the master signal layer
# ------------------------------------------------------------------------------
POTENTIAL_SIGNAL_INPUTS = [
    "HMMS_TrafficSignals_Flat",
    "Norfolk_Signals",
    "Hampton_Signals",
    "Traffic_Signals"
]

MASTER_SIGNAL_OUTPUT = "Master_Signal_Layer"

# ------------------------------------------------------------------------------
# Map maintenance options
# ------------------------------------------------------------------------------
REMOVE_BROKEN_LAYERS_FROM_MAP = False
ADD_MISSING_BASE_LAYERS_TO_MAP = False
ADD_MASTER_SIGNAL_TO_MAP = False


# ==============================================================================
# HELPERS
# ==============================================================================
def norm(name):
    """Case-insensitive normalization for ArcGIS dataset names."""
    return name.lower().strip() if name else name


def list_gdb_contents(gdb_path):
    """Return feature classes and tables from a geodatabase."""
    prev_ws = arcpy.env.workspace
    arcpy.env.workspace = gdb_path

    fcs = arcpy.ListFeatureClasses() or []
    tables = arcpy.ListTables() or []

    arcpy.env.workspace = prev_ws
    return {
        "feature_classes": fcs,
        "tables": tables
    }


def build_base_manifest(source_folder, source_gdbs, explicit_manifest=None):
    """
    Build canonical base manifest of datasets that should exist in project_gdb.
    If explicit_manifest is given, use it.
    Otherwise auto-discover from source GDBs.
    """
    if explicit_manifest is not None:
        return {
            "feature_classes": set(explicit_manifest.get("feature_classes", set())),
            "tables": set(explicit_manifest.get("tables", set()))
        }

    base_fcs = set()
    base_tables = set()

    print("--- BUILDING BASE MANIFEST FROM SOURCE GDBS ---")
    for gdb_name in source_gdbs:
        source_gdb_path = os.path.join(source_folder, gdb_name)

        if not arcpy.Exists(source_gdb_path):
            print(f"   ! Missing source GDB, skipped: {gdb_name}")
            continue

        contents = list_gdb_contents(source_gdb_path)

        for fc in contents["feature_classes"]:
            base_fcs.add(fc)

        for tb in contents["tables"]:
            base_tables.add(tb)

        print(
            f"   {gdb_name}: "
            f"{len(contents['feature_classes'])} FC(s), "
            f"{len(contents['tables'])} table(s)"
        )

    print(
        f"   -> Canonical base manifest built: "
        f"{len(base_fcs)} FC(s), {len(base_tables)} table(s)\n"
    )

    return {
        "feature_classes": base_fcs,
        "tables": base_tables
    }


def get_project_contents(project_gdb):
    """List current project GDB contents."""
    print(f"--- SCANNING PROJECT GDB: {os.path.basename(project_gdb)} ---")
    contents = list_gdb_contents(project_gdb)
    print(
        f"   Found {len(contents['feature_classes'])} FC(s), "
        f"{len(contents['tables'])} table(s)\n"
    )
    return contents


def delete_extras(project_gdb, project_contents, base_manifest, allowed_derived):
    """
    Delete only datasets that are not in the canonical base manifest and not in allowed derived outputs.
    """
    print("--- DELETING NON-CANONICAL DATASETS ---")
    arcpy.env.workspace = project_gdb

    allowed_fc_norm = {norm(x) for x in base_manifest["feature_classes"]} | {norm(x) for x in allowed_derived}
    allowed_tb_norm = {norm(x) for x in base_manifest["tables"]}

    deleted_any = False

    for fc in project_contents["feature_classes"]:
        if norm(fc) not in allowed_fc_norm:
            try:
                arcpy.management.Delete(fc)
                print(f"   Deleted extra FC: {fc}")
                deleted_any = True
            except Exception as e:
                print(f"   ! Failed to delete FC {fc}: {e}")

    for tb in project_contents["tables"]:
        if norm(tb) not in allowed_tb_norm:
            try:
                arcpy.management.Delete(tb)
                print(f"   Deleted extra table: {tb}")
                deleted_any = True
            except Exception as e:
                print(f"   ! Failed to delete table {tb}: {e}")

    if not deleted_any:
        print("   No extra datasets found.")

    print("")


def add_missing_base_data(source_folder, source_gdbs, project_gdb, project_contents, base_manifest):
    """
    Add only datasets from the source GDBs that are missing from the project GDB.
    """
    print("--- ADDING MISSING BASE DATASETS ---")

    existing_fc_norm = {norm(x) for x in project_contents["feature_classes"]}
    existing_tb_norm = {norm(x) for x in project_contents["tables"]}

    manifest_fc_norm = {norm(x): x for x in base_manifest["feature_classes"]}
    manifest_tb_norm = {norm(x): x for x in base_manifest["tables"]}

    added_any = False

    for gdb_name in source_gdbs:
        source_gdb_path = os.path.join(source_folder, gdb_name)

        if not arcpy.Exists(source_gdb_path):
            print(f"   ! Missing source GDB, skipped: {gdb_name}")
            continue

        contents = list_gdb_contents(source_gdb_path)

        # Add missing feature classes
        for fc in contents["feature_classes"]:
            fc_norm = norm(fc)

            # Only import if it belongs to canonical manifest and is missing
            if fc_norm in manifest_fc_norm and fc_norm not in existing_fc_norm:
                input_path = os.path.join(source_gdb_path, fc)
                output_path = os.path.join(project_gdb, fc)

                try:
                    arcpy.management.CopyFeatures(input_path, output_path)
                    print(f"   Added missing FC: {fc}")
                    existing_fc_norm.add(fc_norm)
                    added_any = True
                except Exception as e:
                    print(f"   ! Failed to add FC {fc}: {e}")

        # Add missing tables
        for tb in contents["tables"]:
            tb_norm = norm(tb)

            if tb_norm in manifest_tb_norm and tb_norm not in existing_tb_norm:
                input_path = os.path.join(source_gdb_path, tb)
                output_path = os.path.join(project_gdb, tb)

                try:
                    arcpy.management.CopyRows(input_path, output_path)
                    print(f"   Added missing table: {tb}")
                    existing_tb_norm.add(tb_norm)
                    added_any = True
                except Exception as e:
                    print(f"   ! Failed to add table {tb}: {e}")

    if not added_any:
        print("   No missing base datasets needed to be added.")

    print("")


def rebuild_master_signal_layer(project_gdb, potential_inputs, output_name):
    """
    Rebuild master signal layer from available inputs.
    Deletes and recreates only the derived output.
    """
    print("--- REBUILDING MASTER SIGNAL LAYER ---")
    arcpy.env.workspace = project_gdb

    all_fcs = arcpy.ListFeatureClasses() or []
    all_fc_lookup = {norm(fc): fc for fc in all_fcs}

    signals_to_merge = []
    for sig in potential_inputs:
        matched = all_fc_lookup.get(norm(sig))
        if matched:
            signals_to_merge.append(matched)

    if len(signals_to_merge) > 1:
        try:
            if arcpy.Exists(os.path.join(project_gdb, output_name)):
                arcpy.management.Delete(output_name)
                print(f"   Deleted old derived output: {output_name}")

            arcpy.management.Merge(signals_to_merge, os.path.join(project_gdb, output_name))
            print(f"   Rebuilt {output_name} from: {', '.join(signals_to_merge)}")
        except Exception as e:
            print(f"   ! Failed to rebuild {output_name}: {e}")
    else:
        print(f"   ! Not enough signal layers found to merge. Found: {signals_to_merge}")

    print("")


def get_map_layer_dataset_names(map_obj):
    """
    Return normalized dataset names currently represented in the map.
    Best effort only; some layers may not expose connection properties in a consistent way.
    """
    names = set()

    for lyr in map_obj.listLayers():
        try:
            if lyr.supports("DATASOURCE"):
                ds = os.path.basename(lyr.dataSource)
                names.add(norm(ds))
        except Exception:
            pass

    return names


def clean_broken_layers(map_obj):
    """Optionally remove broken layers from the map."""
    print("--- REMOVING BROKEN LAYERS FROM MAP ---")
    removed_any = False

    for lyr in map_obj.listLayers():
        try:
            if lyr.isBroken:
                print(f"   Removing broken layer: {lyr.name}")
                map_obj.removeLayer(lyr)
                removed_any = True
        except Exception:
            pass

    if not removed_any:
        print("   No broken layers found.")

    print("")


def add_missing_layers_to_map(map_obj, project_gdb, dataset_names, label):
    """
    Add missing datasets to the map if they are not already represented.
    """
    print(f"--- ADDING MISSING {label} TO MAP ---")
    map_dataset_names = get_map_layer_dataset_names(map_obj)
    added_any = False

    for ds_name in sorted(dataset_names):
        if norm(ds_name) not in map_dataset_names:
            ds_path = os.path.join(project_gdb, ds_name)
            if arcpy.Exists(ds_path):
                try:
                    map_obj.addDataFromPath(ds_path)
                    print(f"   Added to map: {ds_name}")
                    added_any = True
                except Exception as e:
                    print(f"   ! Failed to add {ds_name} to map: {e}")

    if not added_any:
        print(f"   No missing {label.lower()} needed to be added to the map.")

    print("")


# ==============================================================================
# MAIN
# ==============================================================================
def main():
    print("=== TARGETED FACTORY RESET START ===\n")
    print(f"Project GDB: {project_gdb}")
    print(f"Source folder: {source_folder}\n")

    base_manifest = build_base_manifest(
        source_folder=source_folder,
        source_gdbs=SOURCE_GDBS,
        explicit_manifest=EXPLICIT_BASE_MANIFEST
    )

    project_contents = get_project_contents(project_gdb)

    delete_extras(
        project_gdb=project_gdb,
        project_contents=project_contents,
        base_manifest=base_manifest,
        allowed_derived=ALLOWED_DERIVED_DATASETS
    )

    # Re-scan after deletion
    project_contents = get_project_contents(project_gdb)

    add_missing_base_data(
        source_folder=source_folder,
        source_gdbs=SOURCE_GDBS,
        project_gdb=project_gdb,
        project_contents=project_contents,
        base_manifest=base_manifest
    )

    rebuild_master_signal_layer(
        project_gdb=project_gdb,
        potential_inputs=POTENTIAL_SIGNAL_INPUTS,
        output_name=MASTER_SIGNAL_OUTPUT
    )

    if REMOVE_BROKEN_LAYERS_FROM_MAP:
        clean_broken_layers(m)

    if ADD_MISSING_BASE_LAYERS_TO_MAP:
        add_missing_layers_to_map(
            map_obj=m,
            project_gdb=project_gdb,
            dataset_names=base_manifest["feature_classes"],
            label="BASE FEATURE CLASSES"
        )

    if ADD_MASTER_SIGNAL_TO_MAP:
        add_missing_layers_to_map(
            map_obj=m,
            project_gdb=project_gdb,
            dataset_names={MASTER_SIGNAL_OUTPUT},
            label="DERIVED LAYERS"
        )

    print("=== TARGETED FACTORY RESET COMPLETE ===")


if __name__ == "__main__":
    main()