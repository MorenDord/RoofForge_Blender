"""Generate the first RoofForge upper-surface mesh."""
import bpy

from ..adapters.mesh_io import read_selected_boundary
from ...core.geometry import GeometryInputError
from ...core.mesh import build_roof_surface


class ROOFFORGE_OT_generate_surface(bpy.types.Operator):
    bl_idname = "roof_forge.generate_surface"
    bl_label = "Create Roof Surface"
    bl_description = "Build a planar upper roof surface from the selected closed boundary loop"
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
        except ValueError as exc:
            message = getattr(exc, "message", str(exc))
            self.report({"ERROR"}, message)
            return {"CANCELLED"}

        mesh_data = None
        roof_object = None
        try:
            mesh_data = bpy.data.meshes.new(f"{source.name}_RoofForge_SurfaceMesh")
            mesh_data.from_pydata(surface.vertices, [], surface.faces)
            mesh_data.update(calc_edges=True)
            if len(mesh_data.polygons) != len(surface.face_slope_indices):
                raise RuntimeError("Blender изменил число полигонов при создании сетки; результат не сохранён.")

            slope_attribute = mesh_data.attributes.new(
                name="roof_forge_slope_index", type="INT", domain="FACE"
            )
            for index, slope_index in enumerate(surface.face_slope_indices):
                slope_attribute.data[index].value = int(slope_index)

            roof_object = bpy.data.objects.new(f"{source.name}_RoofForge_Surface", mesh_data)
            context.collection.objects.link(roof_object)
            roof_object.matrix_world = source.matrix_world.copy()
            roof_object["roof_forge_generated"] = True
            roof_object["roof_forge_source_name"] = source.name
            roof_object["roof_forge_stage"] = "SURFACE_ONLY"
            roof_object["roof_forge_pitch_default"] = float(settings.pitch_default)
        except Exception as exc:
            if roof_object is not None and roof_object.name in bpy.data.objects:
                bpy.data.objects.remove(roof_object, do_unlink=True)
            if mesh_data is not None and mesh_data.name in bpy.data.meshes:
                bpy.data.meshes.remove(mesh_data)
            self.report({"ERROR"}, f"Не удалось создать сетку крыши: {exc}")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Создана верхняя поверхность: {len(surface.vertices)} вершин, {len(surface.faces)} граней. Толщина и свесы пока не создаются."
        )
        return {"FINISHED"}
