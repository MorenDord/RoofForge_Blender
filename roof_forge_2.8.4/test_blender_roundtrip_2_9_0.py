"""Second-process Blender round-trip tests for RoofForge 2.9.

The CI workflow first creates and saves a .blend in
test_blender_runtime_2_9_0.py, then opens it in a fresh Blender process and
rebuilds only the ridge/valley helper meshes from their persisted source mesh.
"""
import os
import sys

import bpy


addon_parent = os.environ.get("ROOFFORGE_ADDON_PARENT")
if not addon_parent:
    raise RuntimeError("ROOFFORGE_ADDON_PARENT must point to the directory containing roof_forge.")
sys.path.insert(0, addon_parent)
import roof_forge


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def require_closed_profile(roof, property_key, label):
    object_name = str(roof.get(property_key, ""))
    profile = bpy.data.objects.get(object_name)
    require(profile is not None and profile.type == "MESH", label + " object is missing.")
    require(len(profile.data.polygons) > 0, label + " has no polygons.")
    uses = {}
    for polygon in profile.data.polygons:
        ids = list(polygon.vertices)
        for a, b in zip(ids, ids[1:] + ids[:1]):
            key = tuple(sorted((int(a), int(b))))
            uses[key] = uses.get(key, 0) + 1
    require(bool(uses), label + " has no edges.")
    require(all(count == 2 for count in uses.values()), label + " is not a closed manifold mesh.")
    return profile


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def main():
    require(tuple(bpy.app.version) >= (5, 0, 0), "RoofForge requires Blender 5.0+.")
    roof_forge.register()

    roofs = [
        obj for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.get("roofforge_generated", False)
        and obj.name in {
            "RF_Spatial_L_VariablePitch_Roof",
            "RF_Spatial_U_VariablePitch_Roof",
            "RF_Spatial_ObliqueMultiReflex_Roof",
        }
    ]
    require(len(roofs) == 3, "Expected saved spatial L/U and oblique multi-reflex roofs after reopening the .blend.")

    for roof in roofs:
        source_name = str(roof.get("roofforge_spatial_profile_source_mesh", ""))
        source_mesh = bpy.data.meshes.get(source_name)
        require(source_mesh is not None, roof.name + " source mesh datablock is missing.")
        source_faces = len(source_mesh.polygons)
        attribute = source_mesh.attributes.get("roofforge_face_source")
        require(attribute is not None, roof.name + " face-source metadata is missing.")
        require(len(attribute.data) == source_faces,
                roof.name + " face-source metadata length does not match the source mesh.")

        activate(roof)
        result = bpy.ops.roofforge.create_ridges()
        require("FINISHED" in result, roof.name + " Create Ridges failed.")
        require(not roof.get("roofforge_ridge_error", ""),
                roof.name + " ridge error: " + str(roof.get("roofforge_ridge_error")))
        require_closed_profile(roof, "roofforge_ridges_object", roof.name + " ridge")

        result = bpy.ops.roofforge.update_ridges()
        require("FINISHED" in result, roof.name + " Update Ridges failed.")
        require(not roof.get("roofforge_ridge_error", ""),
                roof.name + " ridge update error: " + str(roof.get("roofforge_ridge_error")))
        require_closed_profile(roof, "roofforge_ridges_object", roof.name + " ridge update")

        result = bpy.ops.roofforge.create_valleys()
        require("FINISHED" in result, roof.name + " Create Valleys failed.")
        require(not roof.get("roofforge_valley_error", ""),
                roof.name + " valley error: " + str(roof.get("roofforge_valley_error")))
        require_closed_profile(roof, "roofforge_valleys_object", roof.name + " valley")

        result = bpy.ops.roofforge.update_valleys()
        require("FINISHED" in result, roof.name + " Update Valleys failed.")
        require(not roof.get("roofforge_valley_error", ""),
                roof.name + " valley update error: " + str(roof.get("roofforge_valley_error")))
        require_closed_profile(roof, "roofforge_valleys_object", roof.name + " valley update")

        # The persisted FACE-domain source tags also drive standing-seam
        # analysis after reopening, including transition-cap suppression.
        roof_forge._rebuild_standing_seams_for_mesh(roof)
        require(not roof.get("roofforge_standing_error", ""),
                roof.name + " standing seam error: " + str(roof.get("roofforge_standing_error")))
        require(int(roof.get("roofforge_standing_segment_count", 0)) > 0,
                roof.name + " standing seam rebuild produced no segments.")
        standing_name = str(roof.get("roofforge_standing_seams_object", ""))
        standing = bpy.data.objects.get(standing_name)
        require(standing is not None and standing.type == "MESH",
                roof.name + " standing seam helper mesh is missing.")
        require(len(standing.data.polygons) > 0,
                roof.name + " standing seam helper has no faces.")
        require(any(edge.use_seam for edge in standing.data.edges),
                roof.name + " standing seam shoulder edges were not marked Seam.")

    roof_forge.unregister()
    print("ROOFFORGE_BLENDER_ROUNDTRIP_OK", bpy.app.version_string)


if __name__ == "__main__":
    main()
