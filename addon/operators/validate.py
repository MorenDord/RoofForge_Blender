"""Input validation operator (geometry-aware vertical slice)."""
import bpy

from ..adapters.mesh_io import read_selected_boundary
from ...core.geometry import (
    GeometryInputError,
    boundary_envelope_conflicts,
    build_boundary_planes,
    validate_simple_polygon,
)


class ROOFFORGE_OT_validate_input(bpy.types.Operator):
    bl_idname = "roof_forge.validate_input"
    bl_label = "Validate Roof Boundary"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    def execute(self, context):
        try:
            points_3d = read_selected_boundary(context.object)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        points_2d = [(point[0], point[1]) for point in points_3d]
        diagnostics = validate_simple_polygon(points_2d)
        errors = [item for item in diagnostics if item.severity == "ERROR"]
        if errors:
            self.report({"ERROR"}, errors[0].message)
            return {"CANCELLED"}

        try:
            pitch = context.scene.roof_forge.pitch_default
            planes = build_boundary_planes(points_3d, [pitch] * len(points_3d))
            conflicts = boundary_envelope_conflicts(points_3d, planes)
        except GeometryInputError as exc:
            self.report({"ERROR"}, exc.message)
            return {"CANCELLED"}

        if conflicts:
            self.report({"ERROR"}, conflicts[0].message)
            return {"CANCELLED"}

        self.report({"INFO"}, f"Контур корректен. Построено проверочных плоскостей: {len(planes)}.")
        return {"FINISHED"}
