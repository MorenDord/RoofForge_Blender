"""Input validation operator (first vertical slice)."""
import bpy
from ..adapters.mesh_io import read_selected_boundary
from ...core.geometry import validate_simple_polygon


class ROOFFORGE_OT_validate_input(bpy.types.Operator):
    bl_idname = "roof_forge.validate_input"
    bl_label = "Validate Roof Boundary"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    def execute(self, context):
        try:
            points = read_selected_boundary(context.object)
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        diagnostics = validate_simple_polygon(points)
        errors = [d for d in diagnostics if d.severity == "ERROR"]
        if errors:
            self.report({"ERROR"}, errors[0].message)
            return {"CANCELLED"}
        self.report({"INFO"}, "Контур прошёл базовую проверку.")
        return {"FINISHED"}
