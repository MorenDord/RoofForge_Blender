"""Select the source boundary edge associated with one numbered pitch field."""
from __future__ import annotations

import bpy
import bmesh

from ..adapters.mesh_io import ordered_boundary_edge_vertex_indices


class ROOFFORGE_OT_select_slope_edge(bpy.types.Operator):
    bl_idname = "roof_forge.select_slope_edge"
    bl_label = "Show Source Edge"
    bl_description = "Select the source boundary edge associated with this numbered Pitch field"
    bl_options = {"REGISTER"}

    edge_index: bpy.props.IntProperty(name="Contour Edge Index", default=0, min=0)

    @classmethod
    def poll(cls, context):
        obj = context.object
        settings = getattr(context.scene, "roof_forge", None) if context.scene else None
        return (
            obj is not None
            and obj.type == "MESH"
            and settings is not None
            and settings.source_object == obj
            and len(settings.slope_settings) > 0
        )

    def execute(self, context):
        obj = context.object
        settings = context.scene.roof_forge

        if settings.source_object != obj:
            self.report({"ERROR"}, "Активный объект не совпадает с исходным контуром RoofForge.")
            return {"CANCELLED"}
        if self.edge_index >= len(settings.slope_settings):
            self.report({"ERROR"}, "Индекс ската устарел. Обнови список углов.")
            return {"CANCELLED"}

        was_edit_mode = obj.mode == "EDIT"
        try:
            if not was_edit_mode:
                bpy.ops.object.mode_set(mode="EDIT")

            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.verts.index_update()
            bm.edges.index_update()

            ordered_pairs = ordered_boundary_edge_vertex_indices(bm)
            if len(ordered_pairs) != len(settings.slope_settings):
                raise ValueError(
                    "Число граничных рёбер изменилось. Нажми Load / Refresh Slope Angles."
                )

            vertex_pair = ordered_pairs[self.edge_index]
            vertices = {vertex.index: vertex for vertex in bm.verts}
            first = vertices.get(vertex_pair[0])
            second = vertices.get(vertex_pair[1])
            if first is None or second is None:
                raise ValueError("Не удалось найти вершины выбранного граничного ребра.")

            target = next(
                (
                    edge for edge in bm.edges
                    if (
                        (edge.verts[0] is first and edge.verts[1] is second)
                        or (edge.verts[0] is second and edge.verts[1] is first)
                    )
                ),
                None,
            )
            if target is None:
                raise ValueError("Исходное граничное ребро не найдено в mesh topology.")

            context.tool_settings.mesh_select_mode = (False, True, False)
            bm.select_mode = {"EDGE"}
            for face in bm.faces:
                face.select_set(False)
            for edge in bm.edges:
                edge.select_set(False)
            for vertex in bm.verts:
                vertex.select_set(False)
            target.select_set(True)
            bm.select_flush_mode()
            bm.select_history.clear()
            bm.select_history.add(target)
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)

            self.report(
                {"INFO"},
                f"Выбрано исходное ребро {self.edge_index + 1:02d} "
                f"(V{vertex_pair[0] + 1} → V{vertex_pair[1] + 1}).",
            )
            return {"FINISHED"}

        except Exception as exc:
            if not was_edit_mode and obj.mode == "EDIT":
                bpy.ops.object.mode_set(mode="OBJECT")
            self.report({"ERROR"}, str(getattr(exc, "message", exc)))
            return {"CANCELLED"}
