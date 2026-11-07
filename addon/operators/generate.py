"""Generate or rebuild a validated RoofForge alpha shell."""
import bpy

from ..adapters.mesh_io import read_object_boundary
from ..roof_build import (
    apply_shell_metadata,
    build_roof_payload,
    create_roof_mesh_data,
    pitch_values,
    sync_slope_settings,
)


class ROOFFORGE_OT_generate_surface(bpy.types.Operator):
    bl_idname = "roof_forge.generate_surface"
    bl_label = "Create / Update Roof"
    bl_description = "Build or safely update a closed roof shell from the active mesh boundary"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == "MESH"

    def execute(self, context):
        source = context.object
        settings = context.scene.roof_forge
        new_mesh = None
        roof_object = None
        created_object = False

        try:
            points = read_object_boundary(source)
            sync_slope_settings(settings, source, len(points))
            pitches = pitch_values(settings, len(points))
            surface, shell, solver = build_roof_payload(
                points, pitches, settings.thickness
            )
            new_mesh = create_roof_mesh_data(
                f"{source.name}_RoofForge_Mesh", surface, shell
            )

            current_roof = settings.generated_object
            can_update = (
                current_roof is not None
                and bpy.data.objects.get(current_roof.name) is current_roof
                and current_roof.name == settings.generated_name_snapshot
                and current_roof.get("roof_forge_generated", False)
            )
            if can_update:
                roof_object = current_roof
                old_mesh = roof_object.data
                roof_object.data = new_mesh
                try:
                    apply_shell_metadata(
                        roof_object, source, surface, shell, pitches, solver
                    )
                except Exception:
                    roof_object.data = old_mesh
                    raise
                if old_mesh is not new_mesh and old_mesh.users == 0:
                    bpy.data.meshes.remove(old_mesh)
            else:
                roof_object = bpy.data.objects.new(
                    f"{source.name}_RoofForge", new_mesh
                )
                context.collection.objects.link(roof_object)
                created_object = True
                apply_shell_metadata(
                    roof_object, source, surface, shell, pitches, solver
                )

            settings.source_object = source
            settings.generated_object = roof_object
            settings.source_name_snapshot = source.name
            settings.generated_name_snapshot = roof_object.name
            settings.last_status = (
                f"Готово: {len(points)} скатов, {len(shell.faces)} граней; {solver}."
            )
            settings.live_update = bool(settings.live_update)
            new_mesh = None  # Ownership transferred to the generated object.

        except Exception as exc:
            if created_object and roof_object is not None:
                if bpy.data.objects.get(roof_object.name) is roof_object:
                    bpy.data.objects.remove(roof_object, do_unlink=True)
            if new_mesh is not None and new_mesh.users == 0:
                bpy.data.meshes.remove(new_mesh)
            message = getattr(exc, "message", str(exc))
            settings.last_status = f"Построение не выполнено: {message}"
            self.report({"ERROR"}, message)
            return {"CANCELLED"}

        action = "Обновлена" if not created_object and roof_object else "Создана"
        self.report(
            {"INFO"},
            f"{action} крыша: {len(surface.faces)} верхних граней, "
            f"{shell.side_face_count} боковых стенок; solver {solver}."
        )
        return {"FINISHED"}
