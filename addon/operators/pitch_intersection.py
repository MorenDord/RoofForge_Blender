"""Silent pitch snapping to the adjacent slope-intersection event."""
from __future__ import annotations

import bpy

from ...core.pitch_snap import find_adjacent_pitch_angle
from ..adapters.mesh_io import read_object_boundary
from ..roof_build import _build_roof_surface, pitch_values


def _build_surface_without_overhang(points, pitches):
    # Eave overhang adds an outer strip but does not change the upper ridge /
    # valley graph. Solve the authored footprint alone so only those upper
    # intersection vertices participate in the snap count.
    surface, _solver = _build_roof_surface(
        points,
        pitches,
        0.0,
        True,
    )
    return surface


class ROOFFORGE_OT_pitch_intersection_step(bpy.types.Operator):
    bl_idname = "roof_forge.pitch_intersection_step"
    bl_label = "Snap to adjacent intersection"
    bl_description = "Set this slope's angle to its next adjacent intersection event"
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
            ("PREVIOUS", "Previous", "Search toward a lower pitch"),
            ("NEXT", "Next", "Search toward a higher pitch"),
        ),
        default="NEXT",
        options={"HIDDEN"},
    )

    def execute(self, context):
        settings = getattr(context.scene, "roof_forge", None)
        if settings is None:
            return {"FINISHED"}

        try:
            source = settings.source_object
            if source is None or source.type != "MESH":
                return {"FINISHED"}
            points = read_object_boundary(source)
            if len(points) != len(settings.slope_settings):
                return {"FINISHED"}
            pitches = pitch_values(settings, len(points))
            if self.edge_index < 0 or self.edge_index >= len(pitches):
                return {"FINISHED"}

            direction = -1 if self.direction == "PREVIOUS" else 1
            candidate = find_adjacent_pitch_angle(
                points,
                pitches,
                self.edge_index,
                direction,
                _build_surface_without_overhang,
            )
            if candidate is not None:
                settings.slope_settings[self.edge_index].pitch = candidate
        except Exception:
            # An unavailable neighbour or an unsupported trial roof is a no-op
            # by design. Do not surface an error in Blender's status bar.
            return {"FINISHED"}

        return {"FINISHED"}


__all__ = ["ROOFFORGE_OT_pitch_intersection_step"]
