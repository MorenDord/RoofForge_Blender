"""Generate a closed RoofForge shell from the selected boundary loop."""
import bpy

from ..adapters.mesh_io import read_selected_boundary
from ...core.geometry import GeometryInputError
from ...core.mesh import build_roof_surface
from ...core.shell import build_roof_shell


class ROOFFORGE_OT_generate_surface(bpy.types.Operator):
    bl_idname = "roof_forge.generate_surface"
    bl_label = "Create Roof Shell"
    bl_description = "Build a roof with a solid shell extruded along the roof-local global Z axis"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    def execute(self, context):
        source = context.object
        settings = context.scene.roof_forge
        try:
            points = read_selected_boundary(source)
            if len(points) < 3:
                raise GeometryInputError("POLY_TOO_SMALL", "Контур должен содержать минимум три вершины.")
            surface = build_roof_surface(points, [settings.pitch_default] * len(points))
            shell = build_roof_shell(surface, settings.thickness)
        except ValueError as exc:
            message = getattr(exc, "message", str(exc))
            self.report({"ERROR"}, message)
            return {"CANCELLED"}

        mesh_data = None
        roof_object = None
        try:
            mesh_data = bpy.data.meshes.new(f"{source.name}_RoofForge_Mesh")
            mesh_data.from_pydata(shell.vertices, [], shell.faces)
            mesh_data.update(calc_edges=True)
            if len(mesh_data.polygons) != len(shell.faces):
                raise RuntimeError("Blender изменил число полигонов при создании сетки; результат не сохранён.")

            component_attribute = mesh_data.attributes.new(
                name="roof_forge_component", type="INT", domain="FACE"
            )
            component_values = (
                [0] * shell.top_face_count
                + [1] * shell.bottom_face_count
                + [2] * shell.side_face_count
            )
            slope_attribute = mesh_data.attributes.new(
                name="roof_forge_slope_index", type="INT", domain="FACE"
            )
            slope_values = (
                list(surface.face_slope_indices)
                + list(surface.face_slope_indices)
                + [-1] * shell.side_face_count
            )
            for index, component in enumerate(component_values):
                component_attribute.data[index].value = component
            for index, slope_index in enumerate(slope_values):
                slope_attribute.data[index].value = int(slope_index)

            roof_object = bpy.data.objects.new(f"{source.name}_RoofForge", mesh_data)
            context.collection.objects.link(roof_object)
            roof_object.matrix_world = source.matrix_world.copy()
            roof_object["roof_forge_generated"] = True
            roof_object["roof_forge_source_name"] = source.name
            roof_object["roof_forge_stage"] = "CLOSED_SHELL"
            roof_object["roof_forge_pitch_default"] = float(settings.pitch_default)
            roof_object["roof_forge_thickness"] = float(settings.thickness)
        except Exception as exc:
            if roof_object is not None and roof_object.name in bpy.data.objects:
                bpy.data.objects.remove(roof_object, do_unlink=True)
            if mesh_data is not None and mesh_data.name in bpy.data.meshes:
                bpy.data.meshes.remove(mesh_data)
            self.report({"ERROR"}, f"Не удалось создать оболочку крыши: {exc}")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Создана замкнутая оболочка: {len(shell.vertices)} вершин, "
            f"{len(shell.faces)} граней; верх {shell.top_face_count}, "
            f"низ {shell.bottom_face_count}, карнизы {shell.side_face_count}."
        )
        return {"FINISHED"}
