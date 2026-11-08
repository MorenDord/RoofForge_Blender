"""Background smoke test for the RoofForge Blender 5.0 extension.

Run from the repository root:
    blender --background --factory-startup --python tests/blender_smoke.py
"""
from __future__ import annotations

import importlib
import json
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
    ensure(
        len(roof.data.attributes["roof_forge_component"].data) == len(roof.data.polygons)
        and len(roof.data.attributes["roof_forge_slope_index"].data) == len(roof.data.polygons),
        "roof face metadata does not match the dissolved mesh topology",
    )
    bm = bmesh.new()
    try:
        bm.from_mesh(roof.data)
        bm.normal_update()
        coords = [vertex.co for vertex in bm.verts]
        span = max(
            max(v.x for v in coords) - min(v.x for v in coords),
            max(v.y for v in coords) - min(v.y for v in coords),
            max(v.z for v in coords) - min(v.z for v in coords),
            1.0,
        )
        tolerance = span * 2.0e-6
        remaining_coplanar = []
        for edge in bm.edges:
            if len(edge.link_faces) != 2:
                continue
            first, second = edge.link_faces
            if first.normal.dot(second.normal) < 1.0 - 1.0e-8:
                continue
            origin = first.verts[0].co
            if all(
                abs(first.normal.dot(vertex.co - origin)) <= tolerance
                for vertex in second.verts
            ):
                remaining_coplanar.append(edge.index)
        ensure(
            not remaining_coplanar,
            f"coplanar internal roof edges were not dissolved: {remaining_coplanar[:8]}",
        )
    finally:
        bm.free()
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
        not hasattr(bpy.types, "ROOFFORGE_OT_select_slope_edge"),
        "Legacy Edit Mode source-edge selection operator is still registered",
    )
    panel_module = importlib.import_module(f"{extension.__name__}.addon.ui.panel")
    panel_code = panel_module.ROOFFORGE_PT_panel.draw.__code__
    ensure(
        "get_roof_plan_icon" in panel_code.co_names
        and "template_icon" in panel_code.co_names
        and "render_roof_plan_png" not in panel_code.co_names,
        "RoofForge panel must draw the cached facet plan without rendering it",
    )
    ensure(
        "prepare_slopes" not in panel_code.co_names,
        "Load / Refresh Slope Angles should not be part of the user panel",
    )
    ensure(
        "Show" not in panel_code.co_consts,
        "Pitch panel should not require Edit Mode edge-selection buttons",
    )
    ensure(
        hasattr(bpy.types, "ROOFFORGE_PT_main"),
        "RoofForge sidebar panel was not registered",
    )
    ensure(
        hasattr(bpy.context.scene.roof_forge, "plan_label_scale"),
        "number-size control was not registered",
    )
    ensure(
        hasattr(bpy.context.scene.roof_forge, "plan_line_width"),
        "plan line-thickness control was not registered",
    )
    ensure(
        hasattr(bpy.context.scene.roof_forge, "roof_plan_json"),
        "generated roof plan data property was not registered",
    )
    ensure(
        hasattr(bpy.context.scene.roof_forge, "overhang_corner_convergence"),
        "overhang corner-convergence option was not registered",
    )
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

    # The top-view plan is generated from the same stored ordered contour.
    clear_scene()
    plan_source = create_square_object("RoofForge_Smoke_Numbered_Plan")
    plan_settings = bpy.context.scene.roof_forge
    ensure(
        bpy.ops.roof_forge.generate_surface() == {"FINISHED"},
        "first-click roof generation without Load / Refresh Slope Angles failed",
    )
    ensure(
        len(plan_settings.slope_settings) == 4,
        "Generate did not initialise per-edge pitch settings automatically",
    )
    ensure(
        len(json.loads(plan_settings.outline_preview_json)) == 4,
        "Generate did not store the source contour for the roof plan",
    )
    plan_points = json.loads(plan_settings.outline_preview_json)
    plan_data = json.loads(plan_settings.roof_plan_json)
    ensure(
        len(plan_data.get("faces", ())) > 0 and len(plan_data.get("planes", ())) == 4,
        "generated facet plan did not preserve the actual roof topology",
    )
    plan_core = importlib.import_module(f"{extension.__name__}.core.plan_preview")
    plan_png = plan_core.render_roof_plan_png(plan_data, text_scale=1.0)
    ensure(
        plan_png.startswith(b"\x89PNG\r\n\x1a\n"),
        "transparent roof plan renderer did not return a valid PNG",
    )
    ensure(
        len(plan_core.visible_roof_edges(plan_data)) > 4,
        "facet plan is missing the roof's internal ridge lines",
    )
    plan_ui = importlib.import_module(f"{extension.__name__}.addon.ui.plan_preview")
    plan_icon = plan_ui.refresh_roof_plan_icon(
        plan_data,
        text_scale=plan_settings.plan_label_scale,
        line_width=plan_settings.plan_line_width,
    )
    ensure(plan_icon > 0, "Blender preview icon was not created for the roof plan")
    original_signature = plan_ui._PREVIEW_SIGNATURE
    plan_settings.plan_label_scale = 1.5
    plan_settings.plan_line_width = 3.0
    plan_ui.cancel_pending_roof_plan_refresh()
    ensure(
        plan_ui.schedule_roof_plan_refresh(plan_settings, delay=60.0),
        "plan refresh did not schedule a deferred preview update",
    )
    ensure(
        plan_ui.get_roof_plan_icon() == plan_icon
        and plan_ui._PREVIEW_SIGNATURE == original_signature,
        "plan image changed before the deferred refresh timer",
    )
    plan_ui.cancel_pending_roof_plan_refresh()
    resized_icon = plan_ui.refresh_roof_plan_icon(
        plan_data,
        text_scale=plan_settings.plan_label_scale,
        line_width=plan_settings.plan_line_width,
    )
    ensure(resized_icon > 0, "plan number/line setting did not refresh the cached preview")
    ensure(
        all(abs(float(plan_points[i][2])) < 1e-9 for i in range(4)),
        "plan preview changed source contour coordinates",
    )

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
        roof.get("roof_forge_solver") == "WEIGHTED_WAVEFRONT_FLAT_EAVE_OFFSET_CONTOUR",
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


    # Recreate after the result is deleted while the source is no longer active.
    plan_roof = plan_settings.generated_object
    plan_source.select_set(False)
    bpy.context.view_layer.objects.active = plan_roof
    plan_roof.select_set(True)
    bpy.data.objects.remove(plan_roof, do_unlink=True)
    bpy.context.view_layer.update()
    ensure(
        bpy.ops.roof_forge.generate_surface() == {"FINISHED"},
        "Generate did not recover the stored source after deleting the roof",
    )
    recreated_plan_roof = plan_settings.generated_object
    ensure(
        recreated_plan_roof is not None
        and recreated_plan_roof.get("roof_forge_generated", False),
        "deleted roof was not recreated from the stored contour object",
    )

    # Edit the source contour in Edit Mode, exit, then explicitly rebuild.
    recreated_plan_roof.select_set(False)
    plan_source.select_set(True)
    bpy.context.view_layer.objects.active = plan_source
    bpy.ops.object.mode_set(mode="EDIT")
    bm_source = bmesh.from_edit_mesh(plan_source.data)
    bm_source.verts.ensure_lookup_table()
    bm_source.verts[0].co.x -= 0.25
    bmesh.update_edit_mesh(plan_source.data, loop_triangles=False, destructive=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    old_rebuilt_vertices = tuple(
        tuple(float(value) for value in vertex.co)
        for vertex in recreated_plan_roof.data.vertices
    )
    ensure(
        bpy.ops.roof_forge.generate_surface() == {"FINISHED"},
        "Create / Update failed after editing the source contour in Edit Mode",
    )
    new_rebuilt_vertices = tuple(
        tuple(float(value) for value in vertex.co)
        for vertex in plan_settings.generated_object.data.vertices
    )
    ensure(
        old_rebuilt_vertices != new_rebuilt_vertices,
        "manual regeneration did not use the edited source contour",
    )

    # Concave U contour without overhang: preserve the established solver.
    clear_scene()
    u_source = create_u_contour("RoofForge_Smoke_Concave_U")
    u_settings = bpy.context.scene.roof_forge
    u_settings.thickness_cm = 1.0
    u_settings.eave_overhang_cm = 0.0
    ensure(
        bpy.ops.roof_forge.prepare_slopes() == {"FINISHED"},
        "could not prepare U contour pitch settings",
    )
    ensure(len(u_settings.slope_settings) == 8, "expected eight U contour slopes")
    for index, item in enumerate(u_settings.slope_settings):
        item.pitch = 30.0 + (index % 4) * 2.5
    ensure(
        bpy.ops.roof_forge.generate_surface() == {"FINISHED"},
        "concave U contour did not generate with overhang disabled",
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

    # Convex roof rebuilt from one expanded contour.
    clear_scene()
    convex_source = create_square_object("RoofForge_Smoke_Convex_Overhang")
    convex_settings = bpy.context.scene.roof_forge
    convex_settings.thickness_cm = 1.0
    convex_settings.eave_overhang_cm = 25.0
    convex_settings.overhang_corner_convergence = True
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
    ensure(
        convex_roof.get("roof_forge_overhang_support") == "SOURCE_CONTOUR_UNDERSIDE",
        "generated overhang metadata does not identify the original support contour",
    )
    ensure(
        convex_roof.get("roof_forge_overhang_corner_convergence") is True,
        "corner convergence mode was not persisted on the generated roof",
    )
    support_surface, support_shell, _support_solver = roof_build_for_units.build_roof_payload(
        [
            tuple(float(c) for c in vertex.co)
            for vertex in convex_source.data.vertices
        ],
        [30.0, 35.0, 40.0, 32.0],
        roof_build_for_units.centimeters_to_blender_units(
            convex_settings.thickness_cm, bpy.context.scene
        ),
        roof_build_for_units.centimeters_to_blender_units(
            convex_settings.eave_overhang_cm, bpy.context.scene
        ),
        cache_owner=convex_source,
    )
    ensure(support_shell.extrude_up, "eave shell did not extrude upward from its source-aligned underside")
    for edge_index, start in enumerate([
        tuple(float(c) for c in vertex.co)
        for vertex in convex_source.data.vertices
    ]):
        end = tuple(float(c) for c in convex_source.data.vertices[(edge_index + 1) % 4].co)
        support_plane = support_surface.planes[edge_index]
        ensure(
            abs(support_plane.height(start[0], start[1]) - start[2]) < 1e-7
            and abs(support_plane.height(end[0], end[1]) - end[2]) < 1e-7,
            f"support surface moved away from original eave edge {edge_index + 1}",
        )
    ensure(
        support_shell.vertices[len(support_surface.vertices):] == support_surface.vertices,
        "overhang underside vertices do not match the source-anchored support surface",
    )
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
        all(0 <= slope < 4 for slope in top_slope_values),
        "the rebuilt roof must contain only the original four edge pitches and no separate eave-cap faces",
    )
    ensure(
        len(top_slope_values) == len(convex_roof.data.attributes["roof_forge_slope_index"].data)
        - len([value for value in component_values if value == 1])
        - len([value for value in component_values if value == 2]),
        "roof top face metadata count is inconsistent",
    )

    # The same offset-contour rebuild must work on non-flat XYZ eaves.
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
        xyz_roof.get("roof_forge_solver") == "SOURCE_ANCHORED_PLANE_ENVELOPE_OFFSET_CONTOUR",
        "non-flat overhang did not preserve the original 3D support planes",
    )
    ensure(
        abs(float(xyz_roof.get("roof_forge_overhang_cm")) - 20.0) < 1e-7,
        "non-flat overhang centimeters were not preserved in metadata",
    )

    # Concave contours are explicitly rejected for the source-anchored overhang mode.
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
        "concave overhang unexpectedly bypassed the safe-mode restriction",
    )
    ensure(
        "не выполнено" in concave_settings.last_status,
        "unsupported concave overhang did not produce an actionable diagnostic",
    )

    extension.unregister()
    extension.unregister()  # Unregistration must be safe to call twice.
    ensure(not hasattr(bpy.types.Scene, "roof_forge"), "Scene settings remained registered")
    print(
        f"ROOFFORGE_SMOKE_OK Blender {bpy.app.version_string}: "
        "automatic boundary detection, transparent facet plan, convex source-aligned overhang, concave no-overhang and live rebuild"
    )


if __name__ == "__main__":
    main()
