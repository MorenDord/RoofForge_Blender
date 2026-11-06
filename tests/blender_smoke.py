"""Background smoke test for the RoofForge Blender 5.0 extension.

Run from the repository root:
    blender --background --factory-startup --python tests/blender_smoke.py
"""
from __future__ import annotations

import importlib
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

    extension.unregister()
    extension.unregister()  # Unregistration must be safe to call twice.
    ensure(not hasattr(bpy.types.Scene, "roof_forge"), "Scene settings remained registered")
    print(
        f"ROOFFORGE_SMOKE_OK Blender {bpy.app.version_string}: "
        "automatic boundary detection, Object/Edit Mode, wire/surface meshes"
    )


if __name__ == "__main__":
    main()
