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
    settings.show_standing_seams = True
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
    require_sibling_helper(roof, "roofforge_ridges_object", "Ridge")
    require_sibling_helper(roof, "roofforge_valleys_object", "Valley")
    require(int(roof.get("roofforge_standing_segment_count", 0)) > 0,
            "Standing seam generator did not create any segments for " + name)
    standing_name = str(roof.get("roofforge_standing_seams_object", ""))
    standing_obj = bpy.data.objects.get(standing_name)
    require(standing_obj is not None and standing_obj.type == "MESH",
            "Standing seam helper object is missing for " + name)
    require_sibling_helper(roof, "roofforge_standing_seams_object", "Standing seam")
    require(len(standing_obj.data.polygons) > 0,
            "Standing seam mesh has no faces for " + name)
    require(not roof.get("roofforge_standing_error", ""),
            "Standing seam build failed for " + name + ": " + str(roof.get("roofforge_standing_error")))
    return source, roof



def flush_pending_roof_update(roof):
    key = roof.name
    require(key in roof_forge._PENDING_ROOF_UPDATES,
            "Expected a pending RoofForge update for " + key)
    owner, _due_time, update_kind = roof_forge._PENDING_ROOF_UPDATES[key]
    roof_forge._PENDING_ROOF_UPDATES[key] = (owner, 0.0, update_kind)
    roof_forge._flush_pending_roof_updates()


def flush_pending_roof_finalization(roof):
    key = roof.name
    require(key in roof_forge._PENDING_ROOF_FINALIZATIONS,
            "Expected a pending detail finalization for " + key)
    owner, _due_time = roof_forge._PENDING_ROOF_FINALIZATIONS[key]
    roof_forge._PENDING_ROOF_FINALIZATIONS[key] = (owner, 0.0)
    roof_forge._flush_pending_roof_updates()


def require_sibling_helper(roof, property_key, label):
    helper_name = str(roof.get(property_key, ""))
    helper = bpy.data.objects.get(helper_name)
    require(helper is not None, label + " helper is missing.")
    require(helper.parent is None, label + " must be a sibling of the roof, not its child.")
    follow = next(
        (constraint for constraint in helper.constraints
         if constraint.type == "COPY_TRANSFORMS"
         and constraint.name == "RoofForge Follow Roof"),
        None,
    )
    require(follow is not None and follow.target is roof,
            label + " must follow the roof transform with a sibling constraint.")
    return helper


def require_closed_profile_object(roof, property_key, label):
    object_name = str(roof.get(property_key, ""))
    require(bool(object_name), label + " helper object name is missing.")
    profile = bpy.data.objects.get(object_name)
    require(profile is not None and profile.type == "MESH", label + " helper mesh is missing.")
    require(len(profile.data.polygons) > 0, label + " profile mesh has no faces.")
    edge_uses = {}
    for polygon in profile.data.polygons:
        vertices = list(polygon.vertices)
        for a, b in zip(vertices, vertices[1:] + vertices[:1]):
            key = tuple(sorted((int(a), int(b))))
            edge_uses[key] = edge_uses.get(key, 0) + 1
    require(bool(edge_uses), label + " profile mesh has no edges.")
    require(all(count == 2 for count in edge_uses.values()),
            label + " profile mesh is not a closed manifold shell.")
    return profile


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

    # Non-planar concave L and U outlines with per-edge pitches exercise the
    # complete 2.9 path: pitch-aware planar event topology, 3D lifting, mitered
    # eaves, transition caps, saved face-source tags and ridge/valley profiles.
    l_source, l_roof = create_roof_from_outline(
        "RF_Spatial_L_VariablePitch",
        [(0, 0, 0.00), (8, 0, 0.08), (8, 4, 0.12),
         (4, 4, 0.16), (4, 8, 0.20), (0, 8, 0.10)],
        [33, 35, 37, 36, 38, 34],
        overhang=0.20,
    )
    # Emulate a helper saved by an older add-on build as a child; startup
    # migration must turn it into a sibling with a roof-follow constraint.
    legacy_ridge = bpy.data.objects.get(str(l_roof.get("roofforge_ridges_object", "")))
    require(legacy_ridge is not None, "Legacy helper migration fixture is missing.")
    old_follow = next(
        (constraint for constraint in legacy_ridge.constraints
         if constraint.name == "RoofForge Follow Roof"),
        None,
    )
    if old_follow is not None:
        legacy_ridge.constraints.remove(old_follow)
    legacy_ridge.parent = l_roof
    roof_forge._migrate_legacy_thickness()
    require_sibling_helper(l_roof, "roofforge_ridges_object", "Migrated ridge")
    require(bool(l_roof.get("roofforge_spatial_profile_source_mesh", "")),
            "Spatial L roof profile source mesh was not persisted.")
    l_source_mesh = bpy.data.meshes.get(l_roof["roofforge_spatial_profile_source_mesh"])
    require(l_source_mesh is not None and
            l_source_mesh.attributes.get("roofforge_face_source") is not None,
            "Spatial L roof did not persist per-face source IDs.")
    require_closed_profile_object(l_roof, "roofforge_ridges_object", "L ridge")
    require_closed_profile_object(l_roof, "roofforge_valleys_object", "L valley")

    # Individual pitch edits rebuild only the roof surface at the configured
    # frame rate. Detail meshes stay hidden and untouched until the user pauses.
    l_roof_before_pitch = l_roof.data
    ridge_name = str(l_roof.get("roofforge_ridges_object", ""))
    valley_name = str(l_roof.get("roofforge_valleys_object", ""))
    standing_name = str(l_roof.get("roofforge_standing_seams_object", ""))
    ridge_object = bpy.data.objects.get(ridge_name)
    valley_object = bpy.data.objects.get(valley_name)
    standing_object = bpy.data.objects.get(standing_name)
    require(ridge_object is not None and valley_object is not None and standing_object is not None,
            "Detail helper meshes must exist before interactive pitch editing.")
    ridge_before = ridge_object.data
    valley_before = valley_object.data
    standing_before = standing_object.data
    l_roof.roofforge_settings.spatial_pitch_01 = math.radians(34.2)
    l_roof.roofforge_settings.spatial_pitch_01 = math.radians(34.5)
    require(roof_forge._PENDING_ROOF_UPDATES[l_roof.name][2] == "interactive",
            "Spatial pitch change did not queue a roof-only interactive update.")
    require(ridge_object.hide_get() and valley_object.hide_get() and standing_object.hide_get(),
            "Detail meshes were not hidden while adjusting pitch angles.")
    require(l_roof.data is l_roof_before_pitch,
            "The scheduled roof-only update ran before the test explicitly flushed it.")
    flush_pending_roof_update(l_roof)
    require(l_roof.data is not l_roof_before_pitch,
            "Interactive pitch update did not rebuild the generated roof mesh.")
    require(ridge_object.data is ridge_before and valley_object.data is valley_before
            and standing_object.data is standing_before,
            "Interactive pitch update recalculated profile or standing-seam meshes.")
    require(ridge_object.hide_get() and valley_object.hide_get() and standing_object.hide_get(),
            "Detail meshes became visible before interactive editing finished.")
    require(not l_roof.get("roofforge_error", ""),
            "Live spatial pitch rebuild failed: " + str(l_roof.get("roofforge_error")))
    flush_pending_roof_finalization(l_roof)
    require(ridge_object.data is not ridge_before and valley_object.data is not valley_before,
            "Pitch finalization did not rebuild ridge and valley details.")
    require(standing_object.data is not standing_before,
            "Pitch finalization did not rebuild standing seams.")
    require(not ridge_object.hide_get() and not valley_object.hide_get()
            and not standing_object.hide_get(),
            "Detail meshes were not restored after pitch editing.")
    require(int(l_roof.get("roofforge_standing_segment_count", 0)) > 0,
            "Pitch finalization did not regenerate standing seams.")

    # Ridge width changes rebuild only ridge/valley detail meshes, not the roof.
    l_roof_mesh_before_profile = l_roof.data
    ridge_name = str(l_roof.get("roofforge_ridges_object", ""))
    ridge_object = bpy.data.objects.get(ridge_name)
    require(ridge_object is not None, "Ridge helper is missing before profile-only edit.")
    ridge_mesh_before = ridge_object.data
    l_roof.roofforge_settings.ridge_width = 0.205
    require(l_roof.data is l_roof_mesh_before_profile,
            "Ridge width slider rebuilt the roof instead of only profile details.")
    require(roof_forge._PENDING_ROOF_UPDATES[l_roof.name][2] == "profiles",
            "Ridge width change did not queue a profile-only update.")
    flush_pending_roof_update(l_roof)
    require(l_roof.data is l_roof_mesh_before_profile,
            "Profile-only update replaced the roof mesh datablock.")
    require(ridge_object.data is not ridge_mesh_before,
            "Profile-only update did not rebuild the ridge mesh.")
    require(not l_roof.get("roofforge_profile_error", ""),
            "Profile-only update failed: " + str(l_roof.get("roofforge_profile_error")))

    # Standing-seam width changes rebuild only the seam detail object. The roof
    # datablock and its vertex coordinates must remain unchanged.
    l_roof_mesh = l_roof.data
    roof_vertex_snapshot = [tuple(vertex.co) for vertex in l_roof.data.vertices]
    standing_name = str(l_roof.get("roofforge_standing_seams_object", ""))
    standing_object = bpy.data.objects.get(standing_name)
    require(standing_object is not None, "Standing seam helper object is missing before live edit.")
    standing_mesh_before = standing_object.data
    l_roof.roofforge_settings.standing_panel_width = 0.85
    require(l_roof.data is l_roof_mesh,
            "Standing seam width change rebuilt the roof mesh instead of only the seam detail.")
    require([tuple(vertex.co) for vertex in l_roof.data.vertices] == roof_vertex_snapshot,
            "Standing seam width change modified roof vertices.")
    require(standing_object.data is not standing_mesh_before,
            "Standing seam width change did not rebuild the seam mesh datablock.")
    require(int(l_roof.get("roofforge_standing_segment_count", 0)) > 0,
            "Live spatial standing-seam rebuild produced no segments.")
    require(not l_roof.get("roofforge_standing_error", ""),
            "Live spatial standing-seam rebuild failed: " + str(l_roof.get("roofforge_standing_error")))

    u_source, u_roof = create_roof_from_outline(
        "RF_Spatial_U_VariablePitch",
        [(0, 0, 0.00), (10, 0, 0.08), (10, 8, 0.14),
         (7, 8, 0.20), (7, 3, 0.12), (3, 3, 0.18),
         (3, 8, 0.24), (0, 8, 0.10)],
        [33, 35, 37, 38, 34, 36, 32, 37],
        overhang=0.20,
    )
    require(bool(u_roof.get("roofforge_spatial_profile_source_mesh", "")),
            "Spatial U roof profile source mesh was not persisted.")
    u_source_mesh = bpy.data.meshes.get(u_roof["roofforge_spatial_profile_source_mesh"])
    require(u_source_mesh is not None and
            u_source_mesh.attributes.get("roofforge_face_source") is not None,
            "Spatial U roof did not persist per-face source IDs.")
    require_closed_profile_object(u_roof, "roofforge_ridges_object", "U ridge")
    require_closed_profile_object(u_roof, "roofforge_valleys_object", "U valley")

    oblique_source, oblique_roof = create_roof_from_outline(
        "RF_Spatial_ObliqueMultiReflex",
        [(0.0, 0.0, 0.00), (10.0, 0.0, 0.04),
         (10.0, 8.0, 0.10), (7.0, 8.0, 0.14),
         (6.6, 3.2, 0.09), (3.4, 3.2, 0.16),
         (3.0, 8.0, 0.22), (0.0, 8.0, 0.12)],
        [33, 35, 37, 36, 38, 34, 32, 37],
        overhang=0.20,
    )
    require(bool(oblique_roof.get("roofforge_spatial_profile_source_mesh", "")),
            "Oblique multi-reflex roof profile source mesh was not persisted.")
    require_closed_profile_object(oblique_roof, "roofforge_ridges_object", "Oblique ridge")
    require_closed_profile_object(oblique_roof, "roofforge_valleys_object", "Oblique valley")

    # A four-way plus plan stresses the multi-branch ridge junction patch
    # in the actual Blender mesh datablocks, not only the pure-Python builder.
    plus_source, plus_roof = create_roof_from_outline(
        "RF_Spatial_Plus_MultiBranch",
        [(3, 0, 0.000), (7, 0, 0.020), (7, 3, 0.055), (10, 3, 0.070),
         (10, 7, 0.045), (7, 7, 0.090), (7, 10, 0.120), (3, 10, 0.080),
         (3, 7, 0.050), (0, 7, 0.040), (0, 3, 0.010), (3, 3, 0.015)],
        [35] * 12,
        overhang=0.20,
    )
    require(bool(plus_roof.get("roofforge_spatial_profile_source_mesh", "")),
            "Multi-branch plus roof profile source mesh was not persisted.")
    require_closed_profile_object(plus_roof, "roofforge_ridges_object", "Plus multi-branch ridge")
    require_closed_profile_object(plus_roof, "roofforge_valleys_object", "Plus multi-branch valley")

    # Save a real .blend for a second Blender process to reopen and exercise
    # Create/Update profile tools against the persisted source mesh metadata.
    roundtrip_path = os.environ.get("ROOFFORGE_ROUNDTRIP_BLEND", "")
    require(bool(roundtrip_path), "ROOFFORGE_ROUNDTRIP_BLEND must be set for save/reopen validation.")
    bpy.ops.wm.save_as_mainfile(filepath=roundtrip_path)

    roof_forge.unregister()
    print("ROOFFORGE_BLENDER_RUNTIME_OK", bpy.app.version_string)


if __name__ == "__main__":
    main()
