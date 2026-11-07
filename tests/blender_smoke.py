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
    settings.pitch_default = 35.0
    settings.thickness = 0.12

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

    validate_result = bpy.ops.roof_forge.validate_input()
    ensure(validate_result == {"FINISHED"}, f"validation operator failed in {'Edit' if edit_mode else 'Object'} Mode")
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
    settings.pitch_default = 35.0
    settings.thickness = 0.12
    settings.live_update = True
    ensure(
        bpy.ops.roof_forge.prepare_slopes() == {"FINISHED"},
        "could not prepare per-edge pitch settings",
    )
    ensure(len(settings.slope_settings) == 6, "expected one pitch setting per L contour edge")
    for index, item in enumerate(settings.slope_settings):
        item.pitch = 31.0 + index * 1.5
    ensure(
        bpy.ops.roof_forge.validate_input() == {"FINISHED"},
        "per-edge concave L validation failed",
    )
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
    old_thickness = settings.thickness
    try:
        roof_build.build_wavefront_roof_surface = lambda *args, **kwargs: (
            (_ for _ in ()).throw(AssertionError("surface solver ran during thickness-only update"))
        )
        settings.thickness = old_thickness + 0.025
        live_update._run_pending_update()
        ensure(
            abs(float(roof.get("roof_forge_thickness")) - settings.thickness) < 1e-7,
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
    u_settings.pitch_default = 35.0
    u_settings.thickness = 0.12
    u_settings.eave_overhang = 0.0
    ensure(
        bpy.ops.roof_forge.prepare_slopes() == {"FINISHED"},
        "could not prepare U contour pitch settings",
    )
    ensure(len(u_settings.slope_settings) == 8, "expected eight U contour slopes")
    for index, item in enumerate(u_settings.slope_settings):
        item.pitch = 30.0 + (index % 4) * 2.5
    ensure(
        bpy.ops.roof_forge.validate_input() == {"FINISHED"},
        "concave U contour did not validate at zero overhang",
    )
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

    # Convex roof with a horizontal eave overhang.
    clear_scene()
    convex_source = create_square_object("RoofForge_Smoke_Convex_Overhang")
    convex_settings = bpy.context.scene.roof_forge
    convex_settings.pitch_default = 35.0
    convex_settings.thickness = 0.12
    convex_settings.eave_overhang = 0.25
    ensure(
        bpy.ops.roof_forge.prepare_slopes() == {"FINISHED"},
        "could not prepare convex overhang pitch settings",
    )
    ensure(
        bpy.ops.roof_forge.validate_input() == {"FINISHED"},
        "convex contour with eave overhang did not validate",
    )
    ensure(
        bpy.ops.roof_forge.generate_surface() == {"FINISHED"},
        "convex contour with eave overhang did not generate",
    )
    convex_roof = convex_settings.generated_object
    ensure(convex_roof is not None, "convex overhang roof pointer missing")
    coords = [vertex.co for vertex in convex_roof.data.vertices]
    ensure(min(v.x for v in coords) < -0.20, "overhang did not extend the left eave")
    ensure(min(v.y for v in coords) < -0.20, "overhang did not extend the lower eave")
    ensure(max(v.x for v in coords) > 4.20, "overhang did not extend the right eave")
    ensure(max(v.y for v in coords) > 3.20, "overhang did not extend the upper eave")

    # The same nonzero overhang is intentionally rejected on an L contour.
    clear_scene()
    concave_source = create_l_contour("RoofForge_Smoke_Concave_Overhang_Reject")
    concave_settings = bpy.context.scene.roof_forge
    concave_settings.eave_overhang = 0.2
    ensure(
        bpy.ops.roof_forge.prepare_slopes() == {"FINISHED"},
        "could not prepare concave overhang pitch settings",
    )
    ensure(
        bpy.ops.roof_forge.validate_input() == {"CANCELLED"},
        "reflex contour unexpectedly accepted nonzero overhang",
    )
    ensure(
        "выпуклых" in concave_settings.last_status,
        "concave overhang error did not explain the current limitation",
    )

    extension.unregister()
    extension.unregister()  # Unregistration must be safe to call twice.
    ensure(not hasattr(bpy.types.Scene, "roof_forge"), "Scene settings remained registered")
    print(
        f"ROOFFORGE_SMOKE_OK Blender {bpy.app.version_string}: "
        "automatic boundary detection, per-edge pitch, L contour, live rebuild, Object/Edit Mode"
    )


if __name__ == "__main__":
    main()
