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
_PANEL_CATEGORY = "RoofForge"
_DRAW_REGION_TYPE = "UI"
_PANEL_BASE_TOP_RESERVED = 220
_PANEL_BOTTOM_RESERVED = 12
_PANEL_MAX_SIZE = 220


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


def _is_panel_scrolled(region):
    """Return True when the UI region's vertical view is not at its top."""
    try:
        view2d = region.view2d
        current_top = float(view2d.cur.ymax)
        content_top = float(view2d.tot.ymax)
        return (content_top - current_top) > 2.0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        # Some Blender contexts do not expose a View2D for the UI region.
        return False


def _draw_vector_preview():
    try:
        context = bpy.context
        region = context.region
        scene = context.scene
        if region is None or region.type != _DRAW_REGION_TYPE or scene is None:
            return
        if getattr(region, "active_panel_category", "") != _PANEL_CATEGORY:
            return
        settings = getattr(scene, "roof_forge", None)
        if settings is None or not settings.plan_show_vector or not settings.roof_plan_json:
            return
        # The preview occupies a reserved blank row in the main RoofForge
        # panel. Do not pin it over controls while the N-panel is scrolled.
        if _is_panel_scrolled(region):
            return

        geometry = _cached_geometry(settings.roof_plan_json)
        min_x, min_y, max_x, max_y = geometry["bounds"]
        span_x, span_y = max_x - min_x, max_y - min_y
        ui_scale = 1.0
        try:
            ui_scale = max(0.5, float(context.preferences.system.ui_scale))
        except (AttributeError, TypeError, ValueError):
            pass

        top_reserved = _PANEL_BASE_TOP_RESERVED * ui_scale
        if settings.plan_show_raster:
            try:
                from .plan_preview import get_roof_plan_icon
                if get_roof_plan_icon():
                    top_reserved += max(156.0, region.width - 24.0) + 12.0 * ui_scale
            except (AttributeError, ReferenceError, RuntimeError):
                pass

        available = min(
            _PANEL_MAX_SIZE * ui_scale,
            max(96.0 * ui_scale, region.width - 28.0 * ui_scale),
            max(96.0 * ui_scale, region.height - top_reserved - _PANEL_BOTTOM_RESERVED * ui_scale),
        )
        if region.height < top_reserved + 96.0 * ui_scale:
            return
        padding = 10.0 * ui_scale
        inner = max(1.0, available - 2.0 * padding)
        scale = inner / max(span_x, span_y, 1.0e-9)
        origin_x = (region.width - available) * 0.5 + padding + (inner - span_x * scale) * 0.5
        canvas_top = region.height - top_reserved
        origin_y = canvas_top - available + padding + (inner - span_y * scale) * 0.5

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
        _draw_rect(shader, (region.width - available) * 0.5, origin_y - padding, available, available, (0.025, 0.03, 0.04, 0.78))
        if line_positions:
            batch = batch_for_shader(shader, "LINES", {"pos": line_positions})
            shader.bind()
            shader.uniform_float("color", (0.96, 0.97, 1.0, 0.98))
            gpu.state.line_width_set(max(1.0, min(6.0, float(settings.plan_line_width) * ui_scale)))
            batch.draw(shader)

        font_id = 0
        blf.size(font_id, max(10, int(13 * float(settings.plan_label_scale) * ui_scale)))
        for number, center, _clearance in geometry["labels"]:
            px = screen(center)
            text = str(number)
            width, height = blf.dimensions(font_id, text)
            blf.position(font_id, px[0] - width * 0.5, px[1] - height * 0.5, 0)
            blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
            blf.draw(font_id, text)

        blf.size(font_id, max(9, int(10 * ui_scale)))
        blf.position(font_id, (region.width - available) * 0.5 + 8 * ui_scale, origin_y - padding + 6 * ui_scale, 0)
        blf.color(font_id, 0.72, 0.78, 0.86, 0.95)
        blf.draw(font_id, "RoofForge / GPU")
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
                    for region in area.regions:
                        if region.type == "UI":
                            region.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError):
        pass


def register_vector_preview():
    global _DRAW_HANDLE
    if _DRAW_HANDLE is None:
        try:
            _DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
                _draw_vector_preview, (), _DRAW_REGION_TYPE, "POST_PIXEL"
            )
        except (AttributeError, RuntimeError, TypeError):
            _DRAW_HANDLE = None
    tag_vector_preview_redraw()


def unregister_vector_preview():
    global _DRAW_HANDLE, _CACHE_SIGNATURE, _CACHE_GEOMETRY
    if _DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_DRAW_HANDLE, _DRAW_REGION_TYPE)
        except (ReferenceError, RuntimeError, ValueError):
            pass
    _DRAW_HANDLE = None
    _CACHE_SIGNATURE = None
    _CACHE_GEOMETRY = None


__all__ = ["register_vector_preview", "unregister_vector_preview", "tag_vector_preview_redraw"]
