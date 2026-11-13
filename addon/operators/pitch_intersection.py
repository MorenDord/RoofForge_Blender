"""Geometric pitch snapping to a vertex formed by neighbouring slopes."""
from __future__ import annotations

import bpy

from ...core.geometry import PlaneZ, build_boundary_planes
from ...core.mesh import build_roof_surface_from_planes
from ...core.pitch_snap import find_adjacent_pitch_vertex_angle
from ..adapters.mesh_io import read_object_boundary
from ..roof_build import _build_roof_surface, pitch_values


def _build_surface_without_overhang(points, pitches):
    # Eave overhang changes the outer shell but not the upper slope junctions.
    surface, _solver = _build_roof_surface(
        points,
        pitches,
        0.0,
        True,
    )
    return surface


def _build_surface_without_slope(points, pitches, excluded_slope):
    """Build the roof made by all slopes except the one being adjusted.

    Keep one plane slot per source edge so every face retains its original
    slope index. The selected plane is raised above the maximum of all other
    planes over the contour domain, making it inactive without changing the
    support-edge indexing used by the finite-segment envelope.
    """
    planes = build_boundary_planes(points, pitches)
    if excluded_slope < 0 or excluded_slope >= len(planes):
        raise IndexError("Индекс выбранного ската находится вне контура.")

    xy_domain = [(float(point[0]), float(point[1])) for point in points]
    other_heights = [
        plane.height(point[0], point[1])
        for index, plane in enumerate(planes)
        if index != excluded_slope
        for point in xy_domain
    ]
    coordinate_span = max(
        1.0,
        max(point[0] for point in xy_domain) - min(point[0] for point in xy_domain),
        max(point[1] for point in xy_domain) - min(point[1] for point in xy_domain),
        max(float(point[2]) for point in points) - min(float(point[2]) for point in points),
    )
    suppression_height = max(other_heights) + coordinate_span * 1000.0
    planes[excluded_slope] = PlaneZ(0.0, 0.0, suppression_height)

    # The original contour remains the finite support for each plane. This is
    # important for concave footprints: an infinite extension of a remote edge
    # must not manufacture a false neighbour vertex.
    return build_roof_surface_from_planes(
        xy_domain,
        planes,
        active_contour=points,
    )


class ROOFFORGE_OT_pitch_intersection_step(bpy.types.Operator):
    bl_idname = "roof_forge.pitch_intersection_step"
    bl_label = "Snap pitch to neighbouring vertex"
    bl_description = (
        "Find the nearest real roof vertex in the requested pitch direction "
        "and make this slope meet it"
    )
    bl_options = {"INTERNAL", "UNDO"}

    edge_index: bpy.props.IntProperty(
        name="Slope Index",
        default=0,
        min=0,
        max=255,
        options={"HIDDEN"},
    )
    direction: bpy.props.EnumProperty(
        name="Direction",
        items=(
            (
                "PREVIOUS",
                "Previous vertex",
                "Lower this pitch until the slope meets a vertex of the other slopes",
            ),
            (
                "NEXT",
                "Next vertex",
                "Raise this pitch until the slope meets a vertex of the other slopes",
            ),
        ),
        default="NEXT",
        options={"HIDDEN"},
    )

    def execute(self, context):
        settings = getattr(getattr(context, "scene", None), "roof_forge", None)
        if settings is None:
            self.report({"WARNING"}, "Настройки RoofForge не найдены.")
            return {"CANCELLED"}

        settings.pitch_snap_status = ""
        try:
            source = settings.source_object
            if source is None or source.type != "MESH":
                raise RuntimeError(
                    "Сначала создай крышу для выбранного Mesh-контура."
                )

            points = read_object_boundary(source)
            if len(points) != len(settings.slope_settings):
                raise RuntimeError(
                    "Контур изменился. Нажми Create / Update Roof, чтобы обновить список скатов."
                )
            pitches = pitch_values(settings, len(points))
            if self.edge_index < 0 or self.edge_index >= len(pitches):
                raise IndexError("Индекс выбранного ската находится вне списка Pitch.")

            direction = -1 if self.direction == "PREVIOUS" else 1
            candidate = find_adjacent_pitch_vertex_angle(
                points,
                pitches,
                self.edge_index,
                direction,
                _build_surface_without_overhang,
                _build_surface_without_slope,
            )
            if candidate is None:
                direction_label = "меньший" if direction < 0 else "больший"
                settings.pitch_snap_status = (
                    f"Скат {self.edge_index + 1:02d}: вершина соседних скатов "
                    f"не найдена в сторону {direction_label} угла."
                )
                self.report({"INFO"}, settings.pitch_snap_status)
                return {"FINISHED"}

            old_angle = float(pitches[self.edge_index])
            settings.slope_settings[self.edge_index].pitch = candidate.angle_degrees
            x, y, z = candidate.target_vertex
            settings.pitch_snap_status = (
                f"Скат {self.edge_index + 1:02d}: {old_angle:.2f}° → "
                f"{candidate.angle_degrees:.2f}°; общая вершина "
                f"({x:.3f}, {y:.3f}, {z:.3f})."
            )
            self.report({"INFO"}, settings.pitch_snap_status)
            return {"FINISHED"}

        except Exception as exc:
            message = str(getattr(exc, "message", exc))
            settings.pitch_snap_status = f"Подбор угла не выполнен: {message}"
            self.report({"WARNING"}, settings.pitch_snap_status)
            return {"CANCELLED"}


__all__ = ["ROOFFORGE_OT_pitch_intersection_step"]
