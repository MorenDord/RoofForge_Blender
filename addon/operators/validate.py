"""Validate the complete roof build before creating Blender datablocks."""
import bpy

from ..adapters.mesh_io import read_selected_boundary
from ...core.geometry import GeometryInputError
from ...core.mesh import build_roof_surface
from ...core.shell import build_roof_shell


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

        settings = context.scene.roof_forge
        try:
            pitches = [settings.pitch_default] * len(points)
            surface = build_roof_surface(points, pitches)
            shell = build_roof_shell(surface, settings.thickness)
        except GeometryInputError as exc:
            self.report({"ERROR"}, exc.message)
            return {"CANCELLED"}
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Проверка пройдена: верх {len(surface.faces)} граней, "
            f"оболочка {len(shell.faces)} граней; manifold и границы корректны."
        )
        return {"FINISHED"}
