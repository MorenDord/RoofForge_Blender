"""Direct GPU vector overlay for the RoofForge top-view facet plan."""
from __future__ import annotations

import json

import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader

from ...core.plan_preview import _label_center, _normalise_plan, _visible_edges

_DRAW_HANDLE = None
_CACHE_SIGNATURE = None
_CACHE_GEOMETRY = None
_PANEL_PADDING = 14
_PANEL_SIZE = 236


def _prepare_geometry(plan_data):
    vertices, faces, slopes, planes = _normalise_plan(plan_data)
    edges = _visible_edges(faces, slopes, planes)
    min_x = min(point[0] for point in vertices)
    max_x = max(point[0] for point in vertices)
    min_y = min(point[1] for point in vertices)
    max_y = max(point[1] for point in vertices)
    span_x, span_y = max_x - min_x, max_y - min_y
    if max(span_x, span_y) <= 1.0e-12:
        raise ValueError("Roof plan has zero area")
    largest = {}
    for face_index, face in enumerate(faces):
        slope_index = slopes[face_index]
        polygon = [(vertices[index][0], vertices[index][1]) for index in face]
        area = abs(sum(
            polygon[i][0] * polygon[(i + 1) % len(polygon)][1]
            - polygon[(i + 1) % len(polygon)][0] * polygon[i][1]
            for i in range(len(polygon))
        )) * 0.5
        if area > largest.get(slope_index, (0.0, ()))[0]:
            largest[slope_index] = (area, polygon)
    labels = []
    for slope_index in sorted(largest):
        polygon = largest[slope_index][1]
        center, clearance = _label_center(polygon)
        if clearance > 1.0e-9:
            labels.append((slope_index + 1, center, clearance))
    return {
        "vertices": [(point[0], point[1]) for point in vertices],
        "edges": edges,
        "labels": labels,
        "bounds": (min_x, min_y, max_x, max_y),
    }


def _cached_geometry(plan_json):
    global _CACHE_SIGNATURE, _CACHE_GEOMETRY
    if plan_json != _CACHE_SIGNATURE:
        _CACHE_GEOMETRY = _prepare_geometry(json.loads(plan_json))
        _CACHE_SIGNATURE = plan_json
    return _CACHE_GEOMETRY


def _draw_rect(shader, x, y, width, height, color):
    vertices = (
        (x, y), (x + width, y), (x + width, y + height),
        (x, y), (x + width, y + height), (x, y + height),
    )
    batch = batch_for_shader(shader, "TRIS", {"pos": vertices})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_vector_preview():
    try:
        context = bpy.context
        region = context.region
        scene = context.scene
        if region is None or region.type != "WINDOW" or scene is None:
            return
        settings = getattr(scene, "roof_forge", None)
        if settings is None or not settings.plan_show_vector or not settings.roof_plan_json:
            return
        geometry = _cached_geometry(settings.roof_plan_json)
        min_x, min_y, max_x, max_y = geometry["bounds"]
        span_x, span_y = max_x - min_x, max_y - min_y
        available = min(_PANEL_SIZE, max(120, region.width - 36), max(120, region.height - 36))
        inner = available - 2 * _PANEL_PADDING
        scale = inner / max(span_x, span_y, 1.0e-9)
        origin_x = 18 + (inner - span_x * scale) * 0.5
        origin_y = 32 + (inner - span_y * scale) * 0.5

        def screen(point):
            return (
                origin_x + (point[0] - min_x) * scale,
                origin_y + (point[1] - min_y) * scale,
            )

        line_positions = []
        for first, second in geometry["edges"]:
            line_positions.extend((
                screen(geometry["vertices"][first]),
                screen(geometry["vertices"][second]),
            ))

        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        _draw_rect(shader, 12, 12, available + 12, available + 34, (0.025, 0.03, 0.04, 0.78))
        if line_positions:
            batch = batch_for_shader(shader, "LINES", {"pos": line_positions})
            shader.bind()
            shader.uniform_float("color", (0.96, 0.97, 1.0, 0.98))
            gpu.state.line_width_set(max(1.0, min(6.0, float(settings.plan_line_width))))
            batch.draw(shader)

        font_id = 0
        blf.size(font_id, max(10, int(13 * float(settings.plan_label_scale))))
        for number, center, _clearance in geometry["labels"]:
            px = screen(center)
            text = str(number)
            width, height = blf.dimensions(font_id, text)
            blf.position(font_id, px[0] - width * 0.5, px[1] - height * 0.5, 0)
            blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
            blf.draw(font_id, text)

        blf.size(font_id, 10)
        blf.position(font_id, 22, available + 22, 0)
        blf.color(font_id, 0.72, 0.78, 0.86, 0.95)
        blf.draw(font_id, "RoofForge / Vector")
        gpu.state.line_width_set(1.0)
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.blend_set("NONE")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError):
        try:
            gpu.state.line_width_set(1.0)
            gpu.state.depth_test_set("LESS_EQUAL")
            gpu.state.blend_set("NONE")
        except (AttributeError, RuntimeError):
            pass


def tag_vector_preview_redraw():
    try:
        for window in bpy.context.window_manager.windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError):
        pass


def register_vector_preview():
    global _DRAW_HANDLE
    if _DRAW_HANDLE is None:
        try:
            _DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
                _draw_vector_preview, (), "WINDOW", "POST_PIXEL"
            )
        except (AttributeError, RuntimeError, TypeError):
            _DRAW_HANDLE = None
    tag_vector_preview_redraw()


def unregister_vector_preview():
    global _DRAW_HANDLE, _CACHE_SIGNATURE, _CACHE_GEOMETRY
    if _DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_DRAW_HANDLE, "WINDOW")
        except (ReferenceError, RuntimeError, ValueError):
            pass
    _DRAW_HANDLE = None
    _CACHE_SIGNATURE = None
    _CACHE_GEOMETRY = None


__all__ = ["register_vector_preview", "unregister_vector_preview", "tag_vector_preview_redraw"]
