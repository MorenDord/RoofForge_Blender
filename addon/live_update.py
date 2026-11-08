"""Debounced Blender main-thread rebuild for an attached RoofForge shell."""
from __future__ import annotations

import bpy
import json

from ..core.plan_preview import surface_plan_data
from .adapters.mesh_io import read_object_boundary
from .roof_build import (
    apply_shell_metadata,
    create_roof_mesh_data,
    pitch_values,
    build_roof_payload,
    centimeters_to_blender_units,
)
from .ui.plan_preview import schedule_roof_plan_refresh

_PENDING_SCENE_NAME: str | None = None
def live_update_delay_seconds(settings) -> float:
    """Return the user-selected debounce interval in seconds."""
    return max(0, int(settings.live_update_delay_ms)) / 1000.0


def _cancel_timer() -> None:
    try:
        if bpy.app.timers.is_registered(_run_pending_update):
            bpy.app.timers.unregister(_run_pending_update)
    except (AttributeError, RuntimeError, ValueError):
        pass


def schedule_live_update(scene=None) -> None:
    """Debounce a settings edit; geometry runs later on Blender's main thread."""
    global _PENDING_SCENE_NAME
    scene = scene or bpy.context.scene
    if scene is None or not hasattr(scene, "roof_forge"):
        return
    settings = scene.roof_forge
    if not settings.live_update or settings.generated_object is None:
        return
    _PENDING_SCENE_NAME = scene.name
    delay_seconds = live_update_delay_seconds(settings)
    _cancel_timer()
    try:
        bpy.app.timers.register(_run_pending_update, first_interval=delay_seconds)
    except (RuntimeError, ValueError):
        settings.last_status = "Не удалось запланировать Live Update."


def cancel_pending_live_update() -> None:
    global _PENDING_SCENE_NAME
    _cancel_timer()
    _PENDING_SCENE_NAME = None


def _stop_for_rename(settings, message: str) -> None:
    settings.live_update = False
    settings.last_status = message


def _run_pending_update():
    global _PENDING_SCENE_NAME
    scene_name = _PENDING_SCENE_NAME
    _PENDING_SCENE_NAME = None
    scene = bpy.data.scenes.get(scene_name) if scene_name else None
    if scene is None:
        return None
    settings = getattr(scene, "roof_forge", None)
    if settings is None or not settings.live_update:
        return None

    try:
        source = settings.source_object
        roof = settings.generated_object
        if source is not None:
            _ = source.name
        if roof is not None:
            _ = roof.name
    except ReferenceError:
        settings.generated_object = None
        settings.generated_name_snapshot = ""
        settings.last_status = "Live Update остановлен: объект крыши был удалён. Нажми «Create / Update Roof» для повторного создания."
        return None
    if source is None or roof is None:
        settings.last_status = "Live Update ожидает исходный объект и созданную крышу."
        return None
    if source.name != settings.source_name_snapshot:
        _stop_for_rename(
            settings,
            "Live Update остановлен: исходный объект переименован. Существующая крыша сохранена."
        )
        return None
    if roof.name != settings.generated_name_snapshot:
        _stop_for_rename(
            settings,
            "Live Update остановлен: объект крыши переименован. Существующая геометрия сохранена."
        )
        return None
    if source.type != "MESH" or roof.type != "MESH":
        settings.last_status = "Live Update остановлен: исходный объект или крыша больше не Mesh."
        return None

    new_mesh = None
    try:
        points = read_object_boundary(source)
        if len(points) != len(settings.slope_settings):
            settings.last_status = (
                f"Контур изменён: найдено {len(points)} рёбер, "
                f"а настроено {len(settings.slope_settings)} скатов. "
                "Нажми Create / Update Roof, чтобы пересчитать углы по изменённому контуру."
            )
            return None
        pitches = pitch_values(settings, len(points))
        thickness_units = centimeters_to_blender_units(
            settings.thickness_cm, scene
        )
        overhang_units = centimeters_to_blender_units(
            settings.eave_overhang_cm, scene
        )
        surface, shell, solver = build_roof_payload(
            points, pitches, thickness_units, overhang_units,
            corner_convergence=bool(settings.overhang_corner_convergence),
            cache_owner=source,
        )
        new_mesh = create_roof_mesh_data(
            f"{source.name}_RoofForge_LiveMesh", surface, shell
        )
        old_mesh = roof.data
        roof.data = new_mesh
        try:
            roof.matrix_world = source.matrix_world.copy()
            apply_shell_metadata(
                roof, source, surface, shell, pitches, solver,
                overhang_units,
                settings.thickness_cm, settings.eave_overhang_cm,
                bool(settings.overhang_corner_convergence),
            )
        except Exception:
            roof.data = old_mesh
            raise
        if old_mesh is not new_mesh and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
        settings.outline_preview_json = json.dumps(points, separators=(",", ":"))
        settings.roof_plan_json = json.dumps(
            surface_plan_data(surface), separators=(",", ":")
        )
        settings.last_status = "RoofForge live update completed"
        schedule_roof_plan_refresh(settings)
    except Exception as exc:
        if new_mesh is not None and new_mesh.users == 0:
            bpy.data.meshes.remove(new_mesh)
        settings.last_status = f"Live Update не выполнен; прежняя крыша сохранена: {exc}"
    return None
