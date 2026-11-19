"""Debounced Blender main-thread rebuild for object- and Edit-Mode contour edits."""
from __future__ import annotations

import json
import time

import bpy

from ..core.roof_plan import surface_plan_data
from .adapters.mesh_io import read_object_boundary
from .roof_build import (
    apply_shell_metadata,
    build_roof_payload,
    centimeters_to_blender_units,
    create_roof_mesh_data,
    pitch_values,
    sync_slope_settings,
)
from .roof_details import rebuild_roof_details


_PENDING_SCENE_NAME: str | None = None
_EDIT_MODE_WATCH_STATES: dict[str, dict] = {}
_EDIT_MODE_POLL_INTERVAL = 0.15
_EDIT_MODE_MIN_DEBOUNCE = 0.25


def live_update_delay_seconds(settings) -> float:
    """Return the user-selected debounce interval in seconds."""
    return max(0, int(settings.live_update_delay_ms)) / 1000.0


def _timer_is_registered(callback) -> bool:
    try:
        return bool(bpy.app.timers.is_registered(callback))
    except (AttributeError, RuntimeError, ValueError):
        return False


def _cancel_timer(callback) -> None:
    try:
        if _timer_is_registered(callback):
            bpy.app.timers.unregister(callback)
    except (AttributeError, RuntimeError, ValueError):
        pass


def _schedule_edit_mode_monitor() -> None:
    if _timer_is_registered(_edit_mode_monitor):
        return
    try:
        bpy.app.timers.register(
            _edit_mode_monitor,
            first_interval=_EDIT_MODE_POLL_INTERVAL,
        )
    except (RuntimeError, ValueError):
        pass


def _start_edit_mode_monitoring_after_load():
    """Defer scene access until Blender has left the restricted register context."""
    start_edit_mode_monitoring()
    return None


def schedule_edit_mode_monitoring_startup() -> None:
    """Schedule startup monitoring after extension registration or file load."""
    if _timer_is_registered(_start_edit_mode_monitoring_after_load):
        return
    try:
        bpy.app.timers.register(
            _start_edit_mode_monitoring_after_load,
            first_interval=0.5,
        )
    except (AttributeError, RuntimeError, ValueError):
        pass


@bpy.app.handlers.persistent
def _roof_forge_file_loaded(_dummy):
    schedule_edit_mode_monitoring_startup()


def register_live_update_handlers() -> None:
    """Install a safe deferred startup and file-load hook."""
    handlers = bpy.app.handlers.load_post
    if _roof_forge_file_loaded not in handlers:
        handlers.append(_roof_forge_file_loaded)
    schedule_edit_mode_monitoring_startup()


def unregister_live_update_handlers() -> None:
    """Remove startup hooks and their deferred callback."""
    _cancel_timer(_start_edit_mode_monitoring_after_load)
    handlers = bpy.app.handlers.load_post
    if _roof_forge_file_loaded in handlers:
        handlers.remove(_roof_forge_file_loaded)


def start_edit_mode_monitoring(scene=None) -> None:
    """Watch saved RoofForge source contours for geometry edits in Edit Mode."""
    scenes = (scene,) if scene is not None else tuple(bpy.data.scenes)
    for current_scene in scenes:
        settings = getattr(current_scene, "roof_forge", None)
        if settings is None or not settings.live_update:
            continue
        try:
            source = settings.source_object
            roof = settings.generated_object
            if source is None or roof is None:
                continue
            _ = source.name
            _ = roof.name
        except (ReferenceError, RuntimeError):
            continue
        if source.type == "MESH" and roof.type == "MESH":
            _schedule_edit_mode_monitor()
            return


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
    _cancel_timer(_run_pending_update)
    try:
        bpy.app.timers.register(
            _run_pending_update,
            # Property callbacks can fire continuously while a slider is
            # dragged. Coalesce them so expensive geometry only runs after
            # the user pauses, even when an older file stores a zero delay.
            first_interval=max(
                _EDIT_MODE_MIN_DEBOUNCE,
                live_update_delay_seconds(settings),
            ),
        )
    except (RuntimeError, ValueError):
        settings.last_status = "Не удалось запланировать Live Update."
    start_edit_mode_monitoring(scene)


def cancel_pending_live_update() -> None:
    """Cancel both the pending rebuild and the persistent Edit-Mode watcher."""
    global _PENDING_SCENE_NAME
    _cancel_timer(_run_pending_update)
    _cancel_timer(_edit_mode_monitor)
    _cancel_timer(_start_edit_mode_monitoring_after_load)
    _PENDING_SCENE_NAME = None
    _EDIT_MODE_WATCH_STATES.clear()


def _stop_for_rename(settings, message: str) -> None:
    settings.live_update = False
    settings.last_status = message


def _contour_signature(points) -> tuple:
    return tuple(
        tuple(round(float(value), 8) for value in point[:3])
        for point in points
    )


def _remember_contour_signature(scene, points) -> None:
    state = _EDIT_MODE_WATCH_STATES.get(scene.name)
    if state is None:
        return
    state["signature"] = _contour_signature(points)
    state["pending_since"] = None
    state["pending_points"] = None


def _rebuild_scene_roof(scene, points=None) -> bool:
    """Rebuild one scene's linked roof; preserve the last good mesh on failure."""
    current_points = None
    settings = getattr(scene, "roof_forge", None)
    if settings is None or not settings.live_update:
        return False

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
        settings.last_status = (
            "Live Update остановлен: объект крыши был удалён. "
            "Нажми «Create / Update Roof» для повторного создания."
        )
        return False

    if source is None or roof is None:
        settings.last_status = "Live Update ожидает исходный объект и созданную крышу."
        return False
    if source.name != settings.source_name_snapshot:
        _stop_for_rename(
            settings,
            "Live Update остановлен: исходный объект переименован. Существующая крыша сохранена."
        )
        return False
    if roof.name != settings.generated_name_snapshot:
        _stop_for_rename(
            settings,
            "Live Update остановлен: объект крыши переименован. Существующая геометрия сохранена."
        )
        return False
    if source.type != "MESH" or roof.type != "MESH":
        settings.last_status = (
            "Live Update остановлен: исходный объект или крыша больше не Mesh."
        )
        return False

    new_mesh = None
    try:
        # In Edit Mode this reads the live BMesh, not the stale object-mode mesh
        # datablock. In Object Mode it reads the ordinary mesh boundary.
        current_points = (
            tuple(tuple(float(value) for value in point) for point in points)
            if points is not None
            else tuple(read_object_boundary(source))
        )
        if len(current_points) < 3:
            raise ValueError("Для обновления нужен замкнутый контур минимум из трёх вершин.")

        # The settings helper preserves angles on unchanged edges, copies the
        # parent value when an edge is split and blends values when one edge
        # replaces a shorter chain after a vertex is removed.
        sync_slope_settings(
            settings, source, len(current_points), points=current_points
        )
        pitches = pitch_values(settings, len(current_points))
        thickness_units = centimeters_to_blender_units(
            settings.thickness_cm, scene
        )
        overhang_units = centimeters_to_blender_units(
            settings.eave_overhang_cm, scene
        )
        surface, shell, solver = build_roof_payload(
            current_points,
            pitches,
            thickness_units,
            overhang_units,
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
                roof,
                source,
                surface,
                shell,
                pitches,
                solver,
                overhang_units,
                settings.thickness_cm,
                settings.eave_overhang_cm,
                bool(settings.overhang_corner_convergence),
            )
        except Exception:
            roof.data = old_mesh
            raise

        if old_mesh is not new_mesh and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
        settings.outline_preview_json = json.dumps(
            current_points, separators=(",", ":")
        )
        settings.roof_plan_json = json.dumps(
            surface_plan_data(surface), separators=(",", ":")
        )

        _remember_contour_signature(scene, current_points)
        try:
            detail_result = rebuild_roof_details(roof, settings, scene)
            if detail_result["errors"]:
                settings.last_status = (
                    "RoofForge live update completed; details need attention: "
                    + "; ".join(detail_result["errors"])
                )
            else:
                settings.last_status = "RoofForge live update completed"
        except Exception as detail_exc:
            settings.last_status = (
                "RoofForge live update completed; detail generation failed: "
                + str(detail_exc)
            )
        return True
    except Exception as exc:
        if new_mesh is not None and new_mesh.users == 0:
            bpy.data.meshes.remove(new_mesh)
        if current_points is not None:
            _remember_contour_signature(scene, current_points)
        settings.last_status = (
            f"Live Update не выполнен; прежняя крыша сохранена: {exc}"
        )
        return False


def _run_pending_update():
    global _PENDING_SCENE_NAME
    scene_name = _PENDING_SCENE_NAME
    _PENDING_SCENE_NAME = None
    scene = bpy.data.scenes.get(scene_name) if scene_name else None
    if scene is None:
        return None
    _rebuild_scene_roof(scene)
    return None


def _edit_mode_monitor(now=None):
    """Poll active source BMeshes and rebuild after their geometry settles.

    Blender's Edit-Mode BMesh changes do not invoke the settings PropertyGroup
    callbacks. A small timer therefore watches only linked RoofForge sources,
    compares their ordered boundary coordinates and debounces consecutive
    edits. The watcher remains registered in Object Mode so entering Edit Mode
    later is also detected.
    """
    current_time = time.monotonic() if now is None else float(now)
    watched_any = False
    active_scene_names = set()

    for scene in tuple(bpy.data.scenes):
        settings = getattr(scene, "roof_forge", None)
        if settings is None or not settings.live_update:
            continue
        try:
            source = settings.source_object
            roof = settings.generated_object
            if source is not None:
                _ = source.name
            if roof is not None:
                _ = roof.name
        except (ReferenceError, RuntimeError):
            source = roof = None

        if source is None or roof is None:
            continue
        if source.type != "MESH" or roof.type != "MESH":
            continue
        if (
            source.name != settings.source_name_snapshot
            or roof.name != settings.generated_name_snapshot
        ):
            continue

        watched_any = True
        active_scene_names.add(scene.name)
        state = _EDIT_MODE_WATCH_STATES.get(scene.name)
        # A first observation primes the signature. Do not rebuild an unchanged
        # roof merely because Blender has just loaded the extension or file.
        if state is None:
            try:
                points = read_object_boundary(source)
            except Exception:
                continue
            current_signature = _contour_signature(points)
            baseline_signature = current_signature
            try:
                stored_points = json.loads(settings.outline_preview_json)
                if len(stored_points) >= 3:
                    baseline_signature = _contour_signature(stored_points)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
            state = {
                "signature": baseline_signature,
                "pending_since": None,
                "pending_points": None,
            }
            _EDIT_MODE_WATCH_STATES[scene.name] = state
            if current_signature != baseline_signature:
                state["signature"] = current_signature
                state["pending_since"] = current_time
                state["pending_points"] = tuple(
                    tuple(float(value) for value in point) for point in points
                )
            continue

        # Read continuously while editing. If the user just left Edit Mode with
        # a pending change, read once more from the committed object mesh.
        if source.mode != "EDIT" and state["pending_since"] is None:
            continue
        try:
            points = read_object_boundary(source)
        except Exception as exc:
            if source.mode == "EDIT":
                settings.last_status = (
                    "Live Update ждёт корректный замкнутый контур: " + str(exc)
                )
            continue

        signature = _contour_signature(points)
        if signature != state["signature"]:
            state["signature"] = signature
            state["pending_since"] = current_time
            state["pending_points"] = tuple(
                tuple(float(value) for value in point) for point in points
            )

        pending_since = state["pending_since"]
        if pending_since is None:
            continue
        debounce = max(
            _EDIT_MODE_MIN_DEBOUNCE,
            live_update_delay_seconds(settings),
        )
        if current_time - pending_since < debounce:
            continue

        pending_points = state["pending_points"]
        state["pending_since"] = None
        state["pending_points"] = None
        _rebuild_scene_roof(scene, points=pending_points)

    for scene_name in tuple(_EDIT_MODE_WATCH_STATES):
        if scene_name not in active_scene_names:
            _EDIT_MODE_WATCH_STATES.pop(scene_name, None)

    return _EDIT_MODE_POLL_INTERVAL if watched_any else None
