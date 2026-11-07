"""Background smoke test for the RoofForge Blender 5.0 extension.

Run from the repository root:
    blender --background --factory-startup --python tests/blender_smoke.py
"""
from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

import bpy
import bmesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
extension = importlib.import_module(ROOT.name)


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"RoofForge Blender smoke test failed: {message}")


def clear_scene() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def create_square_object(name: str, with_face: bool = False):
    mesh = bpy.data.meshes.new(f"{name}_SourceMesh")
    mesh.from_pydata(
        [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
         (4.0, 3.0, 0.0), (0.0, 3.0, 0.0)],
        [(0, 1), (1, 2), (2, 3), (3, 0)],
        [(0, 1, 2, 3)] if with_face else [],
    )
    mesh.update()
    mesh.edges.foreach_set("select", [False] * len(mesh.edges))
    mesh.vertices.foreach_set("select", [False] * len(mesh.vertices))
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for selected in list(bpy.context.selected_objects):
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def create_xyz_rectangle(name: str):
    points = [
        (0.0, 0.0, 0.0),
        (4.0, 0.0, 0.2),
        (4.0, 3.0, 0.4),
        (0.0, 3.0, 0.1),
    ]
    edges = [(index, (index + 1) % len(points)) for index in range(len(points))]
    mesh = bpy.data.meshes.new(f"{name}_SourceMesh")
    mesh.from_pydata(points, edges, [])
    mesh.update()
    mesh.edges.foreach_set("select", [False] * len(mesh.edges))
    mesh.vertices.foreach_set("select", [False] * len(mesh.vertices))
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for selected in list(bpy.context.selected_objects):
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def matrices_close(first, second, tolerance=1e-6) -> bool:
    return all(
        abs(first[row][column] - second[row][column]) <= tolerance
        for row in range(4) for column in range(4)
    )


def create_l_contour(name: str):
    points = [
        (0.0, 0.0, 0.0),
        (8.0, 0.0, 0.0),
        (8.0, 4.0, 0.0),
        (4.0, 4.0, 0.0),
        (4.0, 8.0, 0.0),
        (0.0, 8.0, 0.0),
    ]
    edges = [(index, (index + 1) % len(points)) for index in range(len(points))]
    mesh = bpy.data.meshes.new(f"{name}_SourceMesh")
    mesh.from_pydata(points, edges, [])
    mesh.update()
    mesh.edges.foreach_set("select", [False] * len(mesh.edges))
    mesh.vertices.foreach_set("select", [False] * len(mesh.vertices))
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for selected in list(bpy.context.selected_objects):
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def create_u_contour(name: str):
    points = [
        (0.0, 0.0, 0.0),
        (4.0, 0.0, 0.0),
        (4.0, 4.0, 0.0),
        (3.0, 4.0, 0.0),
        (3.0, 1.0, 0.0),
        (1.0, 1.0, 0.0),
        (1.0, 4.0, 0.0),
        (0.0, 4.0, 0.0),
    ]
    edges = [(index, (index + 1) % len(points)) for index in range(len(points))]
    mesh = bpy.data.meshes.new(f"{name}_SourceMesh")
    mesh.from_pydata(points, edges, [])
    mesh.update()
    mesh.edges.foreach_set("select", [False] * len(mesh.edges))
    mesh.vertices.foreach_set("select", [False] * len(mesh.vertices))
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for selected in list(bpy.context.selected_objects):
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


def create_regular_wire_loop(name: str, edge_count: int):
    points = [
        (math.cos(2.0 * math.pi * index / edge_count),
         math.sin(2.0 * math.pi * index / edge_count),
         0.0)
        for index in range(edge_count)
    ]
    edges = [(index, (index + 1) % edge_count) for index in range(edge_count)]
    mesh = bpy.data.meshes.new(f"{name}_SourceMesh")
    mesh.from_pydata(points, edges, [])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj



def check_generated_shell(source, source_coordinates) -> None:
    generated = [
        obj for obj in bpy.data.objects
        if obj.get("roof_forge_generated")
        and obj.get("roof_forge_source_name") == source.name
    ]
    ensure(len(generated) == 1, f"expected one generated object for {source.name}, got {len(generated)}")
    roof = generated[0]
    ensure(roof.type == "MESH", "generated result is not a mesh")
    ensure(roof.data.attributes.get("roof_forge_component") is not None, "component face attribute missing")
    ensure(roof.data.attributes.get("roof_forge_slope_index") is not None, "slope face attribute missing")
    ensure(len(roof.data.polygons) > 0, "generated mesh has no polygons")
    ensure(len(source.data.vertices) == 4, "source vertex count changed")
    after = tuple(tuple(float(c) for c in vertex.co) for vertex in source.data.vertices)
    ensure(after == source_coordinates, "source coordinates changed")
    ensure(matrices_close(roof.matrix_world, source.matrix_world), "generated transform differs from source")


def run_case(name: str, edit_mode: bool, with_face: bool = False) -> None:
    clear_scene()
    source = create_square_object(name, with_face=with_face)
    source_coordinates = tuple(tuple(float(c) for c in vertex.co) for vertex in source.data.vertices)
    settings = bpy.context.scene.roof_forge
    settings.thickness_cm = 1.0

    if edit_mode:
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(source.data)
        bm.select_mode = {"EDGE"}
        for face in bm.faces:
            face.select_set(False)
        for vertex in bm.verts:
            vertex.select_set(False)
        for edge in bm.edges:
            edge.select_set(False)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(source.data, loop_triangles=False, destructive=False)

    generate_result = bpy.ops.roof_forge.generate_surface()
    ensure(generate_result == {"FINISHED"}, f"generation operator failed in {'Edit' if edit_mode else 'Object'} Mode")

    if edit_mode:
        bpy.ops.object.mode_set(mode="OBJECT")
    check_generated_shell(source, source_coordinates)


def main() -> None:
    ensure(bpy.app.version >= (5, 0, 0), f"requires Blender 5.0+, got {bpy.app.version_string}")
    extension.register()
    extension.register()  # Registration must be safe to call twice.
    ensure(hasattr(bpy.types.Scene, "roof_forge"), "Scene settings were not registered")
    ensure(
        not hasattr(bpy.ops.roof_forge, "validate_input"),
        "Validate Roof operator should no longer be registered",
    )

    # No mesh elements are selected: the add-on must find the contour itself.
    run_case("RoofForge_Smoke_ObjectMode_Wire", edit_mode=False)
    run_case("RoofForge_Smoke_EditMode_Wire", edit_mode=True)
    # Also exercise boundary extraction from an actual surface mesh face.
    run_case("RoofForge_Smoke_ObjectMode_Surface", edit_mode=False, with_face=True)
    run_case("RoofForge_Smoke_EditMode_Surface", edit_mode=True, with_face=True)

    # 64 is the enforced alpha limit, not merely a benchmark target.
    clear_scene()
    oversized = create_regular_wire_loop("RoofForge_Smoke_OverLimit", 65)
    mesh_io = importlib.import_module(f"{extension.__name__}.addon.adapters.mesh_io")
    try:
        mesh_io.read_object_boundary(oversized)
    except ValueError as exc:
        ensure("64" in str(exc), "over-limit diagnostic does not state the 64-edge limit")
    else:
        raise RuntimeError("RoofForge Blender smoke test failed: 65-edge boundary was accepted")

    # Concave flat-eave L contour with independent pitch per boundary edge.
    clear_scene()
    source = create_l_contour("RoofForge_Smoke_Concave_L")
    source_coordinates = tuple(
        tuple(float(c) for c in vertex.co) for vertex in source.data.vertices
    )
    settings = bpy.context.scene.roof_forge
    settings.thickness_cm = 1.0
    settings.eave_overhang_cm = 15.0
    settings.live_update = True
    ensure(
        bpy.ops.roof_forge.prepare_slopes() == {"FINISHED"},
        "could not prepare per-edge pitch settings",
    )
    ensure(len(settings.slope_settings) == 6, "expected one pitch setting per L contour edge")
    ensure(
        all(abs(item.pitch - 30.0) < 1e-7 for item in settings.slope_settings),
        "new per-edge pitch fields must default to 30 degrees",
    )
    ensure(
        abs(settings.thickness_cm - 1.0) < 1e-7,
        "default roof thickness must be 1 cm",
    )
    ensure(not hasattr(settings, "pitch_default"), "Default Pitch field should be removed")
    for index, item in enumerate(settings.slope_settings):
        item.pitch = 31.0 + index * 1.5
    ensure(
        bpy.ops.roof_forge.generate_surface() == {"FINISHED"},
        "per-edge concave L generation failed",
    )
    roof = settings.generated_object
    ensure(roof is not None, "generated roof pointer was not stored")
    ensure(
        roof.get("roof_forge_solver") == "WEIGHTED_WAVEFRONT_FLAT_EAVE",
        "flat concave L did not use the weighted wavefront solver",
    )
    ensure(
        len(roof.data.attributes["roof_forge_slope_index"].data) > 0,
        "per-face slope metadata is missing",
    )
    before_update = tuple(tuple(float(c) for c in vertex.co) for vertex in roof.data.vertices)

    # Execute the scheduled timer callback directly in background mode; GUI
    # sessions run the same callback after the normal debounce interval.
    live_update = importlib.import_module(
        f"{extension.__name__}.addon.live_update"
    )
    # A thickness-only live update must reuse the cached upper surface.
    roof_build = importlib.import_module(f"{extension.__name__}.addon.roof_build")
    original_wavefront_builder = roof_build.build_wavefront_roof_surface
    old_thickness = settings.thickness_cm
    try:
        roof_build.build_wavefront_roof_surface = lambda *args, **kwargs: (
            (_ for _ in ()).throw(AssertionError("surface solver ran during thickness-only update"))
        )
        settings.thickness_cm = old_thickness + 0.5
        live_update._run_pending_update()
        ensure(
            abs(float(roof.get("roof_forge_thickness_cm")) - settings.thickness_cm) < 1e-7,
            "thickness-only cached rebuild did not update shell metadata",
        )
    finally:
        roof_build.build_wavefront_roof_surface = original_wavefront_builder
        live_update.cancel_pending_live_update()

    live_update = importlib.import_module(
        f"{extension.__name__}.addon.live_update"
    )
    settings.slope_settings[0].pitch += 2.0
    live_update._run_pending_update()
    live_update.cancel_pending_live_update()
    after_update = tuple(tuple(float(c) for c in vertex.co) for vertex in roof.data.vertices)
    ensure(before_update != after_update, "live pitch edit did not rebuild the generated mesh")
    ensure(
        tuple(tuple(float(c) for c in vertex.co) for vertex in source.data.vertices)
        == source_coordinates,
        "concave source contour changed during generation or live update",
    )

    bpy.data.objects.remove(roof, do_unlink=True)
    bpy.context.view_layer.update()
    ensure(
        bpy.ops.roof_forge.generate_surface() == {"FINISHED"},
        "Create / Update failed after the generated roof object was deleted",
    )
    recreated = settings.generated_object
    ensure(recreated is not None, "generated object pointer was not restored after deletion")
    ensure(
        bpy.data.objects.get(recreated.name) is recreated,
        "re-created roof is not registered in bpy.data.objects",
    )
    ensure(
        bpy.context.scene.objects.get(recreated.name) is recreated,
        "re-created roof is not linked to the active scene",
    )
    ensure(
        recreated.get("roof_forge_generated", False),
        "re-created object is missing RoofForge metadata",
    )
    generated_for_source = [
        obj for obj in bpy.context.scene.objects
        if obj.get("roof_forge_generated")
        and obj.get("roof_forge_source_name") == source.name
    ]
    ensure(
        len(generated_for_source) == 1,
        f"expected exactly one re-created roof, got {len(generated_for_source)}",
    )


    # Concave U contour with per-edge pitch and no overhang.
    clear_scene()
    u_source = create_u_contour("RoofForge_Smoke_Concave_U")
    u_settings = bpy.context.scene.roof_forge
    u_settings.thickness_cm = 1.0
    u_settings.eave_overhang_cm = 10.0
    ensure(
        bpy.ops.roof_forge.prepare_slopes() == {"FINISHED"},
        "could not prepare U contour pitch settings",
    )
    ensure(len(u_settings.slope_settings) == 8, "expected eight U contour slopes")
    for index, item in enumerate(u_settings.slope_settings):
        item.pitch = 30.0 + (index % 4) * 2.5
    ensure(
        bpy.ops.roof_forge.generate_surface() == {"FINISHED"},
        "concave U contour did not generate at zero overhang",
    )
    u_roof = u_settings.generated_object
    ensure(u_roof is not None, "concave U generated roof pointer missing")
    ensure(
        len(u_roof.data.polygons) > 0,
        "concave U generated an empty mesh",
    )

    roof_build_for_units = importlib.import_module(
        f"{extension.__name__}.addon.roof_build"
    )
    ensure(
        abs(roof_build_for_units.centimeters_to_blender_units(1.0, bpy.context.scene) - 0.01) < 1e-9,
        "1 cm must convert to 0.01 Blender units when scale_length is 1",
    )
    original_unit_scale = bpy.context.scene.unit_settings.scale_length
    try:
        bpy.context.scene.unit_settings.scale_length = 0.5
        ensure(
            abs(roof_build_for_units.centimeters_to_blender_units(1.0, bpy.context.scene) - 0.02) < 1e-9,
            "centimeter conversion did not honour scene unit scale_length",
        )
    finally:
        bpy.context.scene.unit_settings.scale_length = original_unit_scale

    delay_settings = u_settings
    delay_settings.live_update_delay_ms = 0
    ensure(
        live_update.live_update_delay_seconds(delay_settings) == 0.0,
        "zero-ms debounce did not disable the configured delay",
    )
    delay_settings.live_update_delay_ms = 230
    ensure(
        abs(live_update.live_update_delay_seconds(delay_settings) - 0.230) < 1e-9,
        "live update delay slider did not convert milliseconds to seconds",
    )
    delay_settings.live_update_delay_ms = 0

    # Convex roof with a horizontal eave overhang.
    clear_scene()
    convex_source = create_square_object("RoofForge_Smoke_Convex_Overhang")
    convex_settings = bpy.context.scene.roof_forge
    convex_settings.thickness_cm = 1.0
    convex_settings.eave_overhang_cm = 25.0
    ensure(
        bpy.ops.roof_forge.prepare_slopes() == {"FINISHED"},
        "could not prepare convex overhang pitch settings",
    )
    ensure(
        bpy.ops.roof_forge.prepare_slopes() == {"FINISHED"},
        "could not prepare individual convex pitches",
    )
    ensure(
        len(convex_settings.slope_settings) == 4,
        "expected four individual convex pitches",
    )
    for item, pitch in zip(convex_settings.slope_settings, (30.0, 35.0, 40.0, 32.0)):
        item.pitch = pitch
    ensure(
        bpy.ops.roof_forge.generate_surface() == {"FINISHED"},
        "convex contour with individual pitch and eave overhang did not generate",
    )
    convex_roof = convex_settings.generated_object
    ensure(convex_roof is not None, "convex overhang roof pointer missing")
    coords = [vertex.co for vertex in convex_roof.data.vertices]
    ensure(min(v.x for v in coords) < -0.20, "overhang did not extend the left eave")
    ensure(min(v.y for v in coords) < -0.20, "overhang did not extend the lower eave")
    ensure(max(v.x for v in coords) > 4.20, "overhang did not extend the right eave")
    ensure(max(v.y for v in coords) > 3.20, "overhang did not extend the upper eave")

    component_values = [
        item.value for item in convex_roof.data.attributes["roof_forge_component"].data
    ]
    slope_values = [
        item.value for item in convex_roof.data.attributes["roof_forge_slope_index"].data
    ]
    top_slope_values = [
        slope for component, slope in zip(component_values, slope_values)
        if component == 0
    ]
    ensure(
        all(slope >= 0 for slope in top_slope_values),
        "overhang must preserve original slope ids on all edge strips; no fan/cap faces expected",
    )
    ensure(
        len(top_slope_values) == len(convex_roof.data.attributes["roof_forge_slope_index"].data)
        - len([value for value in component_values if value == 1])
        - len([value for value in component_values if value == 2]),
        "roof top face metadata count is inconsistent",
    )

    # The same miter algorithm must work on non-flat XYZ eaves.
    clear_scene()
    xyz_source = create_xyz_rectangle("RoofForge_Smoke_XYZ_Overhang")
    xyz_settings = bpy.context.scene.roof_forge
    xyz_settings.thickness_cm = 1.0
    xyz_settings.eave_overhang_cm = 20.0
    ensure(
        bpy.ops.roof_forge.prepare_slopes() == {"FINISHED"},
        "could not prepare non-flat contour pitch settings",
    )
    for item, pitch in zip(xyz_settings.slope_settings, (38.0, 40.0, 42.0, 39.0)):
        item.pitch = pitch
    ensure(
        bpy.ops.roof_forge.generate_surface() == {"FINISHED"},
        "non-flat contour with individual pitch and overhang did not generate",
    )
    xyz_roof = xyz_settings.generated_object
    ensure(xyz_roof is not None, "non-flat overhang roof pointer missing")
    ensure(
        xyz_roof.get("roof_forge_solver") == "SUPPORT_PLANE_ENVELOPE_3D",
        "non-flat contour did not use the XYZ support-plane solver",
    )
    ensure(
        abs(float(xyz_roof.get("roof_forge_overhang_cm")) - 20.0) < 1e-7,
        "non-flat overhang centimeters were not preserved in metadata",
    )

    # A U-notch that is narrower than twice the requested eave must be rejected.
    clear_scene()
    concave_source = create_u_contour("RoofForge_Smoke_Concave_Overhang_Too_Large")
    concave_settings = bpy.context.scene.roof_forge
    concave_settings.eave_overhang_cm = 150.0
    ensure(
        bpy.ops.roof_forge.prepare_slopes() == {"FINISHED"},
        "could not prepare concave U overhang pitch settings",
    )
    stable_u_pitches = (
        51.3401917459, 53.1301023542, 45.0, 38.6598082541,
        39.8055710923, 35.5376777919, 45.0, 59.0362434679,
    )
    for item, pitch in zip(concave_settings.slope_settings, stable_u_pitches):
        item.pitch = pitch
    ensure(
        bpy.ops.roof_forge.generate_surface() == {"CANCELLED"},
        "oversized concave overhang unexpectedly accepted a collapsed offset",
    )
    ensure(
        "не выполнено" in concave_settings.last_status,
        "invalid concave offset did not produce an actionable diagnostic",
    )

    extension.unregister()
    extension.unregister()  # Unregistration must be safe to call twice.
    ensure(not hasattr(bpy.types.Scene, "roof_forge"), "Scene settings remained registered")
    print(
        f"ROOFFORGE_SMOKE_OK Blender {bpy.app.version_string}: "
        "automatic boundary detection, per-edge pitch, L/U concave overhang, live rebuild, Object/Edit Mode"
    )


if __name__ == "__main__":
    main()
