"""Headless Blender 5.x smoke tests for RoofForge 2.9 development.

Run with Blender:
  ROOFFORGE_ADDON_PARENT=/tmp/addons blender --background --factory-startup --python test_blender_runtime_2_9_0.py
"""
import math
import os
import sys
from pathlib import Path

import bpy


addon_parent = os.environ.get("ROOFFORGE_ADDON_PARENT")
if not addon_parent:
    raise RuntimeError("ROOFFORGE_ADDON_PARENT must point to the directory containing the roof_forge package.")

sys.path.insert(0, addon_parent)
import roof_forge


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def make_boundary_object(name, points):
    mesh = bpy.data.meshes.new(name + "_InputMesh")
    edges = [(i, (i + 1) % len(points)) for i in range(len(points))]
    mesh.from_pydata(points, edges, [])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def create_roof_from_outline(name, points, pitches, overhang=0.0):
    source = make_boundary_object(name, points)
    settings = bpy.context.scene.roofforge_settings
    settings.overhang = overhang
    settings.make_solid = True
    settings.thickness = 0.01
    settings.show_ridges = True
    settings.show_valleys = True
    for i, angle in enumerate(pitches, 1):
        setattr(settings, "spatial_pitch_{:02d}".format(i), math.radians(angle))

    result = bpy.ops.roofforge.create_roof()
    require("FINISHED" in result, "Create roof operator cancelled for " + name)

    roofs = [
        obj for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.get("roofforge_generated", False)
        and obj.get("roofforge_source", "") == source.name
    ]
    require(len(roofs) == 1, "Expected exactly one generated roof for " + name)
    roof = roofs[0]
    require(not roof.get("roofforge_error", ""), "Roof rebuild failed: " + str(roof.get("roofforge_error")))
    require(len(roof.data.vertices) >= 4, "Generated roof has too few vertices.")
    require(len(roof.data.polygons) >= 4, "Generated roof has too few faces.")
    require(roof.get("roofforge_top_faces", 0) >= 1, "Top surface face count was not stored.")
    require(bool(roof.get("roofforge_ridges_object", "")), "Ridge helper object was not created.")
    return source, roof


def main():
    require(tuple(bpy.app.version) >= (5, 0, 0), "RoofForge requires Blender 5.0 or newer.")
    roof_forge.register()
    require(hasattr(bpy.types.Scene, "roofforge_settings"), "Scene settings were not registered.")
    require(hasattr(bpy.types.Object, "roofforge_settings"), "Object settings were not registered.")

    # Flat rectangle with different per-edge pitches exercises the weighted
    # flat-eave event path, the real overhang mesh and the profile helpers.
    flat_source, flat_roof = create_roof_from_outline(
        "RF_Flat_Rectangle",
        [(0, 0, 0), (8, 0, 0), (8, 5, 0), (0, 5, 0)],
        [32, 35, 38, 34],
        overhang=0.20,
    )
    require(flat_roof.get("roofforge_edge_pitch_count") == 4, "Flat per-edge pitch controls were not persisted.")
    require(bool(flat_roof.get("roofforge_spatial_profile_source_mesh", "")),
            "Flat per-edge roof did not persist its profile source mesh.")
    source_mesh_name = flat_roof["roofforge_spatial_profile_source_mesh"]
    source_mesh = bpy.data.meshes.get(source_mesh_name)
    require(source_mesh is not None, "Flat roof profile source mesh is missing.")
    require(source_mesh.attributes.get("roofforge_face_source") is not None,
            "Face-source metadata was not persisted on the flat roof.")

    # Verify the live callback rebuilds only after a pitch slider changes.
    previous_vertices = len(flat_roof.data.vertices)
    flat_roof.roofforge_settings.spatial_pitch_01 = math.radians(40)
    require(not flat_roof.get("roofforge_error", ""),
            "Live flat-pitch rebuild failed: " + str(flat_roof.get("roofforge_error")))
    updated_pitches = __import__("json").loads(flat_roof["roofforge_edge_pitches"])
    require(abs(updated_pitches[0] - math.radians(40)) < 1.0e-7,
            "Live pitch callback did not persist the new angle.")
    require(len(flat_roof.data.vertices) >= 4 and previous_vertices >= 4,
            "Live rebuild produced an invalid mesh.")

    # A non-planar convex eave loop exercises XYZ boundary extraction,
    # 3D support planes, spatial miter overhang, thickness and saved profile data.
    spatial_source, spatial_roof = create_roof_from_outline(
        "RF_Spatial_Rectangle",
        [(0, 0, 0.000), (8, 0, 0.020), (8, 5, 0.040), (0, 5, 0.010)],
        [35, 36, 37, 34],
        overhang=0.15,
    )
    require(bool(spatial_roof.get("roofforge_spatial", False)),
            "Non-planar eave loop was not detected as spatial.")
    require(bool(spatial_roof.get("roofforge_spatial_profile_source_mesh", "")),
            "Spatial roof profile source mesh was not persisted.")
    require(spatial_roof.get("roofforge_top_faces", 0) >= 4,
            "Spatial roof did not create its slope faces.")

    # Check that the profile-analysis tools can read the saved source mesh
    # without invoking roof regeneration.
    surface = roof_forge._spatial_profile_surface_from_source_mesh(spatial_roof)
    require(surface is not None and len(surface[1]) >= 3,
            "Existing spatial profile source mesh could not be analysed.")

    roof_forge.unregister()
    print("ROOFFORGE_BLENDER_RUNTIME_OK", bpy.app.version_string)


if __name__ == "__main__":
    main()
