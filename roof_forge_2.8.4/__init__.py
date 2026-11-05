bl_info = {
    "name": "RoofForge - Parametric Roof Generator",
    "author": "OpenAI",
    "version": (2, 9, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > RoofForge",
    "description": "Low-poly roofs and automatic lightweight standing-seam layout",
    "category": "Add Mesh",
}

import bpy
import bpy.utils.previews
import bmesh
import json
import math
import os
import struct
import tempfile
import time
import zlib
from collections import defaultdict
from mathutils import Vector
from bpy.props import (
    EnumProperty,
    FloatProperty,
    BoolProperty,
    StringProperty,
    PointerProperty,
)

from .straight_skeleton_2_6_0 import (
    SkeletonError,
    build_roof_mesh,
    _orthogonalize_nearly_orthogonal_contour,
    extend_roof_mesh_eaves,
    extract_roof_seams,
    build_inset_seam_profile_mesh,
)
from .standing_seams_2_6_0 import build_standing_seam_mesh
from .spatial_roof_2_8_4 import extend_spatial_roof_eaves
from .spatial_roof_2_9_0 import build_spatial_roof_mesh, SpatialRoofError


# -----------------------------------------------------------------------------
# Geometry core (pure Python; no external packages required)
# -----------------------------------------------------------------------------

_EPS = 1.0e-9


class RoofForgeError(Exception):
    pass


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _mul(a, s):
    return (a[0] * s, a[1] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _length(a):
    return math.hypot(a[0], a[1])


def _normalize(a):
    length = _length(a)
    if length < _EPS:
        raise RoofForgeError("В контуре есть ребро нулевой длины.")
    return (a[0] / length, a[1] / length)


def _signed_area(poly):
    return 0.5 * sum(_cross(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def _orientation(a, b, c):
    return _cross(_sub(b, a), _sub(c, a))


def _on_segment(a, b, p, eps):
    return (
        min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps
        and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps
    )


def _segments_intersect(a, b, c, d, eps):
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)
    if ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps)) and \
       ((o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps)):
        return True
    if abs(o1) <= eps and _on_segment(a, b, c, eps):
        return True
    if abs(o2) <= eps and _on_segment(a, b, d, eps):
        return True
    if abs(o3) <= eps and _on_segment(c, d, a, eps):
        return True
    if abs(o4) <= eps and _on_segment(c, d, b, eps):
        return True
    return False


def _validate_simple_polygon(poly, eps):
    count = len(poly)
    for i in range(count):
        a, b = poly[i], poly[(i + 1) % count]
        for j in range(i + 1, count):
            if j == i or j == (i + 1) % count or (j + 1) % count == i:
                continue
            c, d = poly[j], poly[(j + 1) % count]
            if _segments_intersect(a, b, c, d, eps):
                raise RoofForgeError("Контур самопересекается или касается сам себя. Исправьте порядок рёбер.")


def _simplify_polygon(poly, scale):
    eps = max(1.0e-8, scale * 1.0e-8)
    cleaned = []
    for point in poly:
        if not cleaned or _length(_sub(point, cleaned[-1])) > eps:
            cleaned.append((float(point[0]), float(point[1])))
    if len(cleaned) > 2 and _length(_sub(cleaned[0], cleaned[-1])) <= eps:
        cleaned.pop()

    changed = True
    while changed and len(cleaned) >= 3:
        changed = False
        result = []
        n = len(cleaned)
        for i in range(n):
            prev = cleaned[(i - 1) % n]
            curr = cleaned[i]
            nxt = cleaned[(i + 1) % n]
            a = _sub(curr, prev)
            b = _sub(nxt, curr)
            if abs(_cross(a, b)) <= eps * max(_length(a), _length(b), 1.0) and _dot(a, b) >= -eps:
                changed = True
                continue
            result.append(curr)
        cleaned = result

    if len(cleaned) < 3:
        raise RoofForgeError("В контуре должно быть не менее трёх разных углов.")
    area = _signed_area(cleaned)
    if abs(area) <= eps * eps:
        raise RoofForgeError("Площадь контура слишком мала или контур вырожден.")
    if area < 0.0:
        cleaned.reverse()
    _validate_simple_polygon(cleaned, eps)
    return cleaned


def _line_intersection(p, direction_a, q, direction_b):
    den = _cross(direction_a, direction_b)
    if abs(den) < 1.0e-10:
        return None
    t = _cross(_sub(q, p), direction_b) / den
    return _add(p, _mul(direction_a, t))


def _offset_polygon(poly, distance):
    """Miter offset for simple concave or convex polygons; rejects collapsed/self-crossing offsets."""
    if distance <= 1.0e-10:
        return list(poly)
    shifted = []
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        edge = _normalize(_sub(q, p))
        outward = (edge[1], -edge[0])  # polygon is CCW
        shifted.append((_add(p, _mul(outward, distance)), edge))

    result = []
    for i in range(len(poly)):
        prev_p, prev_dir = shifted[i - 1]
        curr_p, curr_dir = shifted[i]
        hit = _line_intersection(prev_p, prev_dir, curr_p, curr_dir)
        if hit is None:
            raise RoofForgeError("Не удалось построить свес: есть почти параллельные соседние рёбра.")
        result.append(hit)

    scale = max(max(_length(_sub(result[(i + 1) % len(result)], result[i])) for i in range(len(result))), 1.0)
    result = _simplify_polygon(result, scale)
    if _signed_area(result) <= 1.0e-8:
        raise RoofForgeError("Свес слишком велик: контур крыши схлопнулся.")
    return result


def _is_parallelogram(poly, tolerance=1.0e-4):
    if len(poly) != 4:
        return False
    e = [_sub(poly[(i + 1) % 4], poly[i]) for i in range(4)]
    scale = max(max(_length(v) for v in e), 1.0)
    return abs(_cross(e[0], e[2])) <= tolerance * scale * scale and \
           abs(_cross(e[1], e[3])) <= tolerance * scale * scale


def _create_surface_geometry(poly, settings, eave_lift_override=None):
    """Build the only supported roof type: a free-angle hipped roof."""
    lift = settings.eave_lift if eave_lift_override is None else float(eave_lift_override)
    return build_roof_mesh(
        poly, math.tan(settings.pitch_angle), lift, allow_oblique=True
    )


def _order_single_loop(vertex_coordinates, edge_pairs):
    adjacency = defaultdict(list)
    for a, b in edge_pairs:
        if a == b:
            continue
        adjacency[a].append(b)
        adjacency[b].append(a)
    if len(adjacency) < 3:
        raise RoofForgeError("Не найден замкнутый контур минимум из трёх вершин.")
    bad = [vid for vid, neighbours in adjacency.items() if len(neighbours) != 2]
    if bad:
        raise RoofForgeError("Выбранные рёбра должны образовывать один замкнутый loop без ответвлений и разрывов.")
    start = next(iter(adjacency))
    ordered = [start]
    previous = None
    current = start
    for _ in range(len(adjacency) + 1):
        neighbours = adjacency[current]
        nxt = neighbours[0] if neighbours[0] != previous else neighbours[1]
        if nxt == start:
            break
        if nxt in ordered:
            raise RoofForgeError("В выделении найдено больше одного контура или самопересечение.")
        ordered.append(nxt)
        previous, current = current, nxt
    if len(ordered) != len(adjacency):
        raise RoofForgeError("Выделение содержит несколько отдельных контуров. Оставьте один замкнутый loop.")
    try:
        return [vertex_coordinates[index] for index in ordered]
    except KeyError as exc:
        raise RoofForgeError("Не удалось прочитать координаты всех вершин контура.") from exc


def _extract_loop_from_object(obj):
    if obj is None or obj.type != 'MESH':
        raise RoofForgeError("Активным объектом должен быть Mesh с контуром карниза.")
    if obj.mode == 'EDIT':
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.verts.index_update()
        selected_edges = [edge for edge in bm.edges if edge.select]
        if not selected_edges:
            raise RoofForgeError("В Edit Mode выделите одно замкнутое кольцо рёбер карниза.")
        coordinates = {vert.index: (obj.matrix_world @ vert.co) for vert in bm.verts}
        edge_pairs = [(edge.verts[0].index, edge.verts[1].index) for edge in selected_edges]
        return _order_single_loop(coordinates, edge_pairs)

    mesh = obj.data
    if not mesh.edges:
        raise RoofForgeError("У активного Mesh нет рёбер.")
    if len(mesh.polygons) == 0:
        edge_pairs = [tuple(edge.vertices) for edge in mesh.edges]
    else:
        edge_use_count = defaultdict(int)
        for polygon in mesh.polygons:
            for edge_key in polygon.edge_keys:
                edge_use_count[tuple(sorted(edge_key))] += 1
        edge_pairs = [tuple(edge.vertices) for edge in mesh.edges if edge_use_count.get(tuple(sorted(edge.vertices)), 0) == 1]
    if not edge_pairs:
        raise RoofForgeError("Не найдено граничное кольцо. Выделите loop в Edit Mode или используйте mesh-контур без граней.")
    coordinates = {vert.index: (obj.matrix_world @ vert.co) for vert in mesh.vertices}
    return _order_single_loop(coordinates, edge_pairs)


def _prepare_local_polygon(world_points):
    xs = [point.x for point in world_points]
    ys = [point.y for point in world_points]
    zs = [point.z for point in world_points]
    center_x = sum(xs) / len(xs)
    center_y = sum(ys) / len(ys)
    base_z = sum(zs) / len(zs)
    diagonal = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    z_tolerance = max(1.0e-5, diagonal * 1.0e-5)
    if max(zs) - min(zs) > z_tolerance:
        raise RoofForgeError("Контур карниза должен лежать в горизонтальной плоскости XY. Выровняйте вершины по Z.")
    local = [(point.x - center_x, point.y - center_y) for point in world_points]
    local = _simplify_polygon(local, max(diagonal, 1.0))
    return local, (center_x, center_y, base_z)


def _prepare_local_spatial_polygon(world_points):
    """Normalize a 3D eave loop without flattening individual vertex heights."""
    xs = [float(p.x) for p in world_points]
    ys = [float(p.y) for p in world_points]
    zs = [float(p.z) for p in world_points]
    cx, cy, cz = sum(xs)/len(xs), sum(ys)/len(ys), sum(zs)/len(zs)
    local = [(float(p.x)-cx, float(p.y)-cy, float(p.z)-cz) for p in world_points]
    # Keep XYZ; the spatial solver validates XY simplicity and edge grades.
    return local, (cx, cy, cz)


# -----------------------------------------------------------------------------
# Mesh construction and live object rebuilding
# -----------------------------------------------------------------------------


def _extrude_mesh_global_z(vertices, faces, local_offset):
    """Give a roof surface real mesh thickness by translating it along WORLD +Z.

    ``local_offset`` is the world +Z vector transformed into the object's local
    coordinates. The original surface becomes the underside, the translated
    copy is the upper surface, and only boundary edges receive side walls.
    No Solidify modifier is involved.
    """
    if not vertices or not faces:
        return list(vertices), list(faces)
    offset = (float(local_offset[0]), float(local_offset[1]), float(local_offset[2]))
    count = len(vertices)
    bottom = [tuple(map(float, v)) for v in vertices]
    top = [(v[0] + offset[0], v[1] + offset[1], v[2] + offset[2]) for v in bottom]
    out_vertices = bottom + top

    # Reverse the original faces for the underside; translated faces retain
    # their upward-facing winding.
    out_faces = [tuple(reversed(face)) for face in faces]
    out_faces.extend(tuple(index + count for index in face) for face in faces)

    edge_uses = defaultdict(list)
    for face in faces:
        for i, a in enumerate(face):
            b = face[(i + 1) % len(face)]
            key = (a, b) if a < b else (b, a)
            edge_uses[key].append((a, b))

    for uses in edge_uses.values():
        if len(uses) != 1:
            continue
        a, b = uses[0]
        # Winding follows the top boundary so the wall normal points outward.
        out_faces.append((a, b, b + count, a + count))

    return out_vertices, out_faces


def _replace_mesh_data(obj, name, vertices, faces, seam_edges=None, face_source_ids=None):
    """Replace mesh data without remeshing, dissolving, smoothing or subdividing.

    The polygons passed by the roof solver are the intended mathematical faces.
    Keeping them intact is essential: coplanar edges are still meaningful when
    they belong to the actual roof topology (ridge/valley graph).
    """
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(verbose=False)
    mesh.update()
    if len(mesh.polygons):
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
    for polygon in mesh.polygons:
        polygon.use_smooth = False
    if face_source_ids is not None:
        if len(face_source_ids) != len(mesh.polygons):
            raise RoofForgeError(
                "Число face-source меток не совпадает с числом граней итогового меша."
            )
        face_attribute = mesh.attributes.new(
            name="roofforge_face_source", type="INT", domain="FACE"
        )
        for index, source_id in enumerate(face_source_ids):
            face_attribute.data[index].value = int(source_id)
    if seam_edges:
        marked = {
            (int(edge[0]), int(edge[1])) if int(edge[0]) < int(edge[1])
            else (int(edge[1]), int(edge[0]))
            for edge in seam_edges if len(edge) == 2
        }
        for edge in mesh.edges:
            key = tuple(sorted((int(edge.vertices[0]), int(edge.vertices[1]))))
            if key in marked:
                edge.use_seam = True
    old = obj.data
    obj.data = mesh
    if old and old.users == 0:
        bpy.data.meshes.remove(old)


def _remove_helper_object(roof_obj, custom_key):
    helper_name = roof_obj.get(custom_key, "")
    helper = bpy.data.objects.get(helper_name) if helper_name else None
    if helper is not None and helper.get("roofforge_helper", False):
        helper_mesh = helper.data if helper.type == 'MESH' else None
        bpy.data.objects.remove(helper, do_unlink=True)
        if helper_mesh is not None and helper_mesh.users == 0:
            bpy.data.meshes.remove(helper_mesh)
    roof_obj[custom_key] = ""


_ROOFFORGE_HELPER_KEYS = (
    "roofforge_ridges_object",
    "roofforge_valleys_object",
    "roofforge_standing_seams_object",
)


def _helper_owner(obj):
    """Resolve a sibling helper back to its roof, retaining legacy child support."""
    if obj is None or not obj.get("roofforge_helper", False):
        return obj
    for constraint in obj.constraints:
        if (constraint.type == 'COPY_TRANSFORMS'
                and constraint.name == "RoofForge Follow Roof"
                and constraint.target is not None):
            target = constraint.target
            if target.type == 'MESH':
                return target
    owner_name = str(obj.get("roofforge_owner_name", ""))
    owner = bpy.data.objects.get(owner_name) if owner_name else None
    if owner is not None and owner.type == 'MESH':
        return owner
    if obj.parent is not None and obj.parent.type == 'MESH':
        return obj.parent
    return None


def _hide_roof_helpers(roof_obj, hidden):
    """Hide or restore all detail meshes while the roof surface is interactively rebuilt."""
    if roof_obj is None:
        return
    for custom_key in _ROOFFORGE_HELPER_KEYS:
        helper_name = str(roof_obj.get(custom_key, ""))
        helper = bpy.data.objects.get(helper_name) if helper_name else None
        if helper is None or not helper.get("roofforge_helper", False):
            continue
        try:
            if hidden:
                if not helper.get("roofforge_interactive_hidden", False):
                    helper["roofforge_prev_hide_viewport"] = bool(helper.hide_get())
                    helper["roofforge_prev_hide_render"] = bool(helper.hide_render)
                    helper["roofforge_interactive_hidden"] = True
                helper.hide_set(True)
                helper.hide_render = True
            elif helper.get("roofforge_interactive_hidden", False):
                helper.hide_set(bool(helper.get("roofforge_prev_hide_viewport", False)))
                helper.hide_render = bool(helper.get("roofforge_prev_hide_render", False))
                for key in (
                    "roofforge_prev_hide_viewport",
                    "roofforge_prev_hide_render",
                    "roofforge_interactive_hidden",
                ):
                    if key in helper:
                        del helper[key]
        except (ReferenceError, RuntimeError, AttributeError):
            continue


def _remove_roof_helpers(roof_obj):
    """Remove named detail helpers and any legacy child helpers on a roof."""
    if roof_obj is None:
        return
    for custom_key in _ROOFFORGE_HELPER_KEYS:
        _remove_helper_object(roof_obj, custom_key)
    for child in list(roof_obj.children):
        if child.get("roofforge_helper", False):
            mesh = child.data if child.type == 'MESH' else None
            bpy.data.objects.remove(child, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)


def _ensure_helper_object(roof_obj, suffix, custom_key):
    helper_name = roof_obj.get(custom_key, "")
    helper = bpy.data.objects.get(helper_name) if helper_name else None
    if helper is None or helper.type != 'MESH':
        mesh = bpy.data.meshes.new(roof_obj.name + suffix + "_Mesh")
        helper = bpy.data.objects.new(roof_obj.name + suffix, mesh)
        collection = roof_obj.users_collection[0] if roof_obj.users_collection else bpy.context.scene.collection
        collection.objects.link(helper)
        helper["roofforge_helper"] = True
        roof_obj[custom_key] = helper.name

    # Detail objects are siblings in the same collection. Their world transform
    # follows the roof through a constraint, while their mesh coordinates remain
    # in roof-local space as required by the profile and standing-seam builders.
    if helper.parent is not None:
        saved_world = helper.matrix_world.copy()
        helper.parent = None
        helper.matrix_world = saved_world
    collection = roof_obj.users_collection[0] if roof_obj.users_collection else bpy.context.scene.collection
    if collection not in helper.users_collection:
        collection.objects.link(helper)
    helper.parent = None
    helper.matrix_world = roof_obj.matrix_world.copy()
    helper["roofforge_helper"] = True
    helper["roofforge_owner_name"] = roof_obj.name
    constraint = next(
        (item for item in helper.constraints
         if item.type == 'COPY_TRANSFORMS' and item.name == "RoofForge Follow Roof"),
        None,
    )
    if constraint is None:
        constraint = helper.constraints.new(type='COPY_TRANSFORMS')
        constraint.name = "RoofForge Follow Roof"
    constraint.target = roof_obj
    try:
        constraint.owner_space = 'WORLD'
        constraint.target_space = 'WORLD'
    except (AttributeError, TypeError):
        pass
    return helper


def _settings_values(settings):
    return {
        "roof_type": settings.roof_type,
        "pitch_angle": settings.pitch_angle,
        "interactive_update_rate": settings.interactive_update_rate,
        "overhang": settings.overhang,
        "eave_lift": settings.eave_lift,
        "thickness": settings.thickness,
        "make_solid": settings.make_solid,
        "show_ridges": settings.show_ridges,
        "ridge_width": settings.ridge_width,
        "ridge_extrusion": settings.ridge_extrusion,
        "ridge_end_offset": settings.ridge_end_offset,
        "show_valleys": settings.show_valleys,
        "valley_width": settings.valley_width,
        "valley_extrusion": settings.valley_extrusion,
        "valley_end_offset": settings.valley_end_offset,
        "show_standing_seams": settings.show_standing_seams,
        "standing_panel_width": settings.standing_panel_width,
        "standing_seam_height": settings.standing_seam_height,
        "standing_seam_width": settings.standing_seam_width,
        "standing_end_offset": settings.standing_end_offset,
        "end_offsets_migrated": True,
        **{f"spatial_pitch_{i:02d}": getattr(settings, f"spatial_pitch_{i:02d}") for i in range(1, 33)},
    }


def _update_roof_modifiers(roof_obj, settings):
    # RoofForge thickness is explicit mesh geometry; no Solidify or Bevel.
    for modifier in tuple(roof_obj.modifiers):
        if modifier.name in {"RoofForge Thickness", "RoofForge Bevel"}:
            roof_obj.modifiers.remove(modifier)


def _mesh_boundary_segments(vertices, faces):
    """Return the geometric boundary edges of a polygon surface."""
    uses = defaultdict(list)
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            key = (a, b) if a < b else (b, a)
            uses[key].append((a, b))
    result = []
    for edge_uses in uses.values():
        if len(edge_uses) == 1:
            a, b = edge_uses[0]
            result.append((tuple(vertices[a]), tuple(vertices[b])))
    return result


def _world_surface_from_mesh_object(roof_obj):
    """Extract upward roof facets, preserving generated per-face source tags."""
    source_mesh = roof_obj.data
    source_attribute = (
        source_mesh.attributes.get("roofforge_face_source")
        if source_mesh is not None else None
    )
    if source_attribute is not None and len(source_attribute.data) == len(source_mesh.polygons):
        transform = roof_obj.matrix_world
        world_points = [transform @ vertex.co for vertex in source_mesh.vertices]
        source_faces = []
        face_sources = []
        for polygon in source_mesh.polygons:
            source_id = int(source_attribute.data[polygon.index].value)
            # -2: transition cap, -3: underside, -4: thickness sidewall.
            # -1 remains a real overhang facet and can carry a panel to eave.
            if source_id in (-2, -3, -4) or len(polygon.vertices) < 3:
                continue
            coords = [world_points[index] for index in polygon.vertices]
            nx = ny = nz = 0.0
            for i, point in enumerate(coords):
                nxt = coords[(i + 1) % len(coords)]
                nx += (point.y - nxt.y) * (point.z + nxt.z)
                ny += (point.z - nxt.z) * (point.x + nxt.x)
                nz += (point.x - nxt.x) * (point.y + nxt.y)
            length = math.sqrt(nx * nx + ny * ny + nz * nz)
            if length <= 1.0e-12 or nz / length <= 0.05:
                continue
            source_faces.append(tuple(int(index) for index in polygon.vertices))
            face_sources.append(source_id)

        if not source_faces:
            raise RoofForgeError(
                "В меше не найдены верхние скаты, пригодные для построения фальцев."
            )
        used = sorted({index for face in source_faces for index in face})
        remap = {old: new for new, old in enumerate(used)}
        surface_vertices = [
            (float(world_points[index].x), float(world_points[index].y), float(world_points[index].z))
            for index in used
        ]
        surface_faces = [tuple(remap[index] for index in face) for face in source_faces]
        ridge_graph = extract_roof_seams(
            surface_vertices, surface_faces, face_sources, []
        )
        boundary_edges = _mesh_boundary_segments(surface_vertices, surface_faces)
        return surface_vertices, surface_faces, ridge_graph, boundary_edges

    """Extract evaluated upward-facing roof facets without changing the source.

    Modifiers are evaluated first, then a temporary BMesh dissolves tiny
    coplanar partitions (including triangulation) so panel lines are not
    restarted at invisible internal edges. Coordinates are transformed to
    world space so all panel dimensions remain scene-unit values.
    """
    evaluated_obj = None
    evaluated_mesh = None
    bm = bmesh.new()
    try:
        source_mesh = roof_obj.data
        try:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            evaluated_obj = roof_obj.evaluated_get(depsgraph)
            evaluated_mesh = evaluated_obj.to_mesh()
            if evaluated_mesh is not None:
                source_mesh = evaluated_mesh
        except (AttributeError, RuntimeError, TypeError):
            evaluated_obj = None
            evaluated_mesh = None

        if source_mesh is None or not source_mesh.polygons:
            raise RoofForgeError("У выбранного объекта нет граней крыши.")

        bm.from_mesh(source_mesh)
        bm.verts.ensure_lookup_table()
        # Imported roof planes are sometimes stored as separate face islands
        # with coincident but unwelded vertices. Weld only microscopic gaps in
        # this temporary copy so their true shared dihedral edges can be found;
        # the user's original mesh is never touched.
        if bm.verts:
            local_coords = [vert.co for vert in bm.verts]
            spans = [
                max(float(co[axis]) for co in local_coords)
                - min(float(co[axis]) for co in local_coords)
                for axis in range(3)
            ]
            local_scale = max(1.0, *spans)
            try:
                bmesh.ops.remove_doubles(
                    bm, verts=list(bm.verts), dist=local_scale * 1.0e-8
                )
            except (TypeError, RuntimeError, AttributeError):
                pass
        bm.normal_update()
        try:
            bmesh.ops.dissolve_limit(
                bm,
                angle_limit=math.radians(0.01),
                use_dissolve_boundaries=False,
                verts=list(bm.verts),
                edges=list(bm.edges),
            )
            bm.normal_update()
        except (TypeError, RuntimeError, AttributeError):
            # Keep the evaluated input intact if a particular build cannot
            # perform limited dissolve on the temporary BMesh.
            pass

        bm.verts.index_update()
        transform = evaluated_obj.matrix_world if evaluated_obj is not None else roof_obj.matrix_world
        world_points = [transform @ vert.co for vert in bm.verts]
        source_faces = []
        for face in bm.faces:
            if len(face.verts) < 3:
                continue
            coords = [world_points[v.index] for v in face.verts]
            nx = ny = nz = 0.0
            for i, point in enumerate(coords):
                nxt = coords[(i + 1) % len(coords)]
                nx += (point.y - nxt.y) * (point.z + nxt.z)
                ny += (point.z - nxt.z) * (point.x + nxt.x)
                nz += (point.x - nxt.x) * (point.y + nxt.y)
            length = math.sqrt(nx * nx + ny * ny + nz * nz)
            if length <= 1.0e-12:
                continue
            if nz / length > 0.05:
                source_faces.append(tuple(v.index for v in face.verts))

        if not source_faces:
            raise RoofForgeError(
                "Не найдены верхние грани крыши. Проверьте нормали и геометрию объекта."
            )

        used = sorted({index for face in source_faces for index in face})
        remap = {old: new for new, old in enumerate(used)}
        surface_vertices = [
            (float(world_points[index].x), float(world_points[index].y), float(world_points[index].z))
            for index in used
        ]
        surface_faces = [tuple(remap[index] for index in face) for face in source_faces]
        face_sources = [-1] * len(surface_faces)
        ridge_graph = extract_roof_seams(surface_vertices, surface_faces, face_sources, [])
        boundary_edges = _mesh_boundary_segments(surface_vertices, surface_faces)
        return surface_vertices, surface_faces, ridge_graph, boundary_edges
    finally:
        bm.free()
        if evaluated_obj is not None and evaluated_mesh is not None:
            try:
                evaluated_obj.to_mesh_clear()
            except (AttributeError, RuntimeError, ReferenceError):
                pass



def _store_spatial_profile_source_mesh(roof_obj, vertices, faces, face_source_ids=None):
    """Persist the pre-overhang surface and per-face source IDs in a hidden mesh datablock."""
    key = "roofforge_spatial_profile_source_mesh"
    old_name = str(roof_obj.get(key, ""))
    mesh = bpy.data.meshes.new(roof_obj.name + "_RF_ProfileSource")
    try:
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        if face_source_ids is not None:
            if len(face_source_ids) != len(faces):
                raise RoofForgeError(
                    "Число идентификаторов исходных скатов не совпадает с числом граней профиля."
                )
            attribute = mesh.attributes.new(
                name="roofforge_face_source", type="INT", domain="FACE"
            )
            for index, source_id in enumerate(face_source_ids):
                attribute.data[index].value = int(source_id)
        mesh.use_fake_user = True
    except Exception:
        bpy.data.meshes.remove(mesh)
        raise
    roof_obj[key] = mesh.name
    old = bpy.data.meshes.get(old_name) if old_name else None
    if old is not None and old != mesh:
        old.use_fake_user = False
        if old.users == 0:
            bpy.data.meshes.remove(old)


def _spatial_profile_surface_from_source_mesh(roof_obj):
    """Read the saved source surface in world space for ridge/valley tools."""
    mesh_name = str(roof_obj.get("roofforge_spatial_profile_source_mesh", ""))
    mesh = bpy.data.meshes.get(mesh_name) if mesh_name else None
    if mesh is None or not mesh.polygons:
        return None
    transform = roof_obj.matrix_world
    vertices = []
    for vertex in mesh.vertices:
        point = transform @ vertex.co
        vertices.append((float(point.x), float(point.y), float(point.z)))
    faces = [tuple(int(i) for i in polygon.vertices) for polygon in mesh.polygons]
    source_attribute = mesh.attributes.get("roofforge_face_source")
    if source_attribute is not None and len(source_attribute.data) == len(faces):
        face_sources = [int(item.value) for item in source_attribute.data]
    else:
        face_sources = [-1] * len(faces)
    seams = extract_roof_seams(vertices, faces, face_sources, [])
    boundary = _mesh_boundary_segments(vertices, faces)
    return vertices, faces, seams, boundary

def _rebuild_existing_roof_profiles(roof_obj, kinds=None):
    """Build ridge/valley profiles from an existing mesh surface, never from a skeleton.

    The source mesh is evaluated (including modifiers), copied into a temporary
    BMesh, and reduced only across coplanar partitions. Shared top-surface edges
    are classified by their actual dihedral angle. The source object is never
    edited; the resulting profiles are separate child meshes.
    """
    if (not roof_obj or roof_obj.type != 'MESH'
            or roof_obj.get('roofforge_profiles_updating', False)):
        return

    settings = roof_obj.roofforge_settings
    if kinds is None:
        kinds = tuple(
            kind for kind in ('RIDGE', 'VALLEY')
            if roof_obj.get('roofforge_external_' + kind.lower(), False)
        )
    else:
        kinds = tuple(str(kind).upper() for kind in kinds)

    if not kinds:
        return

    roof_obj['roofforge_profiles_updating'] = True
    try:
        source_surface = None
        if roof_obj.get("roofforge_generated", False):
            has_edge_pitches = int(roof_obj.get("roofforge_edge_pitch_count", 0)) >= 3
            has_saved_source = bool(roof_obj.get("roofforge_spatial_profile_source_mesh", ""))
            if roof_obj.get("roofforge_spatial", False) or has_edge_pitches or has_saved_source:
                source_surface = _spatial_profile_surface_from_source_mesh(roof_obj)
        surface_vertices, surface_faces, seam_graph, boundary_edges = (
            source_surface if source_surface is not None
            else _world_surface_from_mesh_object(roof_obj)
        )
        inverse = roof_obj.matrix_world.inverted_safe()
        for kind in kinds:
            if kind == 'RIDGE':
                enabled = bool(settings.show_ridges)
                width = float(settings.ridge_width)
                extrusion = float(settings.ridge_extrusion)
                end_offset = float(settings.ridge_end_offset)
                custom_key = 'roofforge_ridges_object'
                suffix = '_Ridges'
                error_key = 'roofforge_ridge_error'
            elif kind == 'VALLEY':
                enabled = bool(settings.show_valleys)
                width = float(settings.valley_width)
                extrusion = float(settings.valley_extrusion)
                end_offset = float(settings.valley_end_offset)
                custom_key = 'roofforge_valleys_object'
                suffix = '_Valleys'
                error_key = 'roofforge_valley_error'
            else:
                continue

            if (not roof_obj.get('roofforge_generated', False)
                    and not roof_obj.get('roofforge_external_' + kind.lower(), False)):
                continue
            if not enabled:
                _remove_helper_object(roof_obj, custom_key)
                roof_obj[error_key] = ''
                roof_obj['roofforge_' + kind.lower() + '_edge_count'] = 0
                continue

            world_vertices, world_faces = build_inset_seam_profile_mesh(
                surface_vertices, surface_faces, seam_graph, kind, width,
                (0.0, 0.0, extrusion),
                end_offset=end_offset,
                seat_sink_offset=(0.0, 0.0, -0.0002),
                boundary_edges=boundary_edges,
            )
            local_vertices = []
            for vertex in world_vertices:
                local_point = inverse @ Vector(vertex)
                local_vertices.append((
                    float(local_point.x), float(local_point.y), float(local_point.z)
                ))
            helper = _ensure_helper_object(roof_obj, suffix, custom_key)
            _replace_mesh_data(helper, helper.name + '_Mesh', local_vertices, world_faces)
            roof_obj[error_key] = ''
            roof_obj['roofforge_' + kind.lower() + '_edge_count'] = sum(
                1 for edge in seam_graph if str(edge[4]).upper() == kind
            )
            roof_obj['roofforge_' + kind.lower() + '_face_count'] = len(world_faces)

        roof_obj['roofforge_profile_error'] = ''
    except Exception as exc:
        message = str(exc)
        roof_obj['roofforge_profile_error'] = message
        for kind in kinds:
            error_key = 'roofforge_' + str(kind).lower() + '_error'
            roof_obj[error_key] = message
    finally:
        roof_obj['roofforge_profiles_updating'] = False


def _rebuild_standing_seams_for_mesh(roof_obj):
    """Live-rebuild standing seams on a selected/generated roof mesh object."""
    if not roof_obj or roof_obj.type != 'MESH' or roof_obj.get('roofforge_standing_updating', False):
        return
    roof_obj['roofforge_standing_updating'] = True
    try:
        settings = roof_obj.roofforge_settings
        if settings.show_standing_seams:
            standing_obj = _ensure_helper_object(
                roof_obj, "_StandingSeams", "roofforge_standing_seams_object"
            )
            surface_vertices, surface_faces, ridge_graph, boundary_edges = _world_surface_from_mesh_object(roof_obj)
            if roof_obj.get("roofforge_generated", False):
                roof_thickness = float(settings.thickness) if settings.make_solid else 0.0
            else:
                # For an imported solid roof, this is the thickness used to
                # sink invisible rib feet inside the existing shell.
                roof_thickness = float(settings.thickness)
            sv, sf, stats = build_standing_seam_mesh(
                surface_vertices,
                surface_faces,
                ridge_graph,
                panel_width=settings.standing_panel_width,
                seam_height=settings.standing_seam_height,
                seam_base_width=settings.standing_seam_width,
                roof_thickness=roof_thickness,
                ridge_height=settings.ridge_extrusion,
                end_offset=settings.standing_end_offset,
                boundary_edges=boundary_edges,
            )
            inverse = roof_obj.matrix_world.inverted_safe()
            local_vertices = []
            for vertex in sv:
                point = inverse @ Vector(vertex)
                local_vertices.append((float(point.x), float(point.y), float(point.z)))
            _replace_mesh_data(
                standing_obj, standing_obj.name + "_Mesh", local_vertices, sf,
                seam_edges=stats.get("seam_edge_pairs", ()),
            )
            roof_obj["roofforge_standing_effective_height"] = stats.get("effective_height_max", 0.0)
            roof_obj["roofforge_standing_segment_count"] = stats.get("segments", 0)
            roof_obj["roofforge_standing_stats"] = json.dumps(stats, separators=(",", ":"))
        else:
            _remove_helper_object(roof_obj, "roofforge_standing_seams_object")
            roof_obj["roofforge_standing_effective_height"] = 0.0
            roof_obj["roofforge_standing_segment_count"] = 0
        roof_obj["roofforge_standing_error"] = ""
    except Exception as exc:
        roof_obj["roofforge_standing_error"] = str(exc)
    finally:
        roof_obj["roofforge_standing_updating"] = False


def _rebuild_generated_roof(roof_obj, rebuild_details=True):
    if not roof_obj or roof_obj.type != 'MESH' or not roof_obj.get('roofforge_generated', False):
        return
    if roof_obj.get('roofforge_updating', False):
        return
    roof_obj['roofforge_updating'] = True
    try:
        settings = roof_obj.roofforge_settings
        source_poly = json.loads(roof_obj.get('roofforge_outline', '[]'))
        if len(source_poly) < 3:
            raise RoofForgeError(
                "В объекте крыши отсутствует сохранённый исходный контур. Создайте крышу заново."
            )
        is_spatial = bool(roof_obj.get("roofforge_spatial", False))
        profile_outline = None
        profile_vertices = None
        profile_faces = None
        profile_sources = None
        has_edge_pitches = False

        if is_spatial:
            source_xyz = [tuple(float(c) for c in p[:3]) for p in source_poly]
            profile_outline = [(p[0], p[1]) for p in source_xyz]
            pitches = json.loads(roof_obj.get(
                "roofforge_edge_pitches",
                roof_obj.get("roofforge_spatial_pitches", "[]")
            ))
            if len(pitches) != len(source_xyz):
                raise RoofForgeError("Не совпадает число индивидуальных уклонов и рёбер 3D-контура.")
            has_edge_pitches = True
            try:
                # Keep the source surface intact for seam detection. The eave
                # extension is added as planar strips afterwards and must not
                # be interpreted as extra ridge/valley junctions.
                profile_vertices, profile_faces, profile_sources = build_spatial_roof_mesh(
                    source_xyz, pitches, eave_lift=settings.eave_lift
                )
                surface_vertices, surface_faces, face_source_ids = (
                    extend_spatial_roof_eaves(
                        profile_vertices, profile_faces, profile_sources, settings.overhang
                    )
                )
            except SpatialRoofError as exc:
                raise RoofForgeError("Пространственная крыша: " + str(exc)) from exc
            poly = list(profile_outline)
        else:
            source_poly = [(float(p[0]), float(p[1])) for p in source_poly]
            # Keep the eave extension and seam clipping on the exact same
            # normalized footprint as the free-angle skeleton.
            source_poly, _was_orthogonalized = _orthogonalize_nearly_orthogonal_contour(source_poly)
            edge_pitches = json.loads(roof_obj.get("roofforge_edge_pitches", "[]"))
            if edge_pitches and len(edge_pitches) != len(source_poly):
                raise RoofForgeError("Число индивидуальных углов не совпадает с числом рёбер контура.")
            has_edge_pitches = bool(edge_pitches)
            if edge_pitches:
                # Build each edge's own support plane, then lift the
                # reflex-aware 2D roof partition onto those planes.
                source_xyz = [(p[0], p[1], 0.0) for p in source_poly]
                profile_vertices, profile_faces, profile_sources = build_spatial_roof_mesh(
                    source_xyz, edge_pitches, eave_lift=settings.eave_lift
                )
                profile_outline = list(source_poly)
                surface_vertices, surface_faces, face_source_ids = (
                    extend_spatial_roof_eaves(
                        profile_vertices, profile_faces, profile_sources, settings.overhang
                    )
                )
                poly = list(source_poly)
            else:
                poly = _offset_polygon(source_poly, settings.overhang)
                surface_vertices, surface_faces, face_source_ids = _create_surface_geometry(source_poly, settings)
                if settings.overhang > 1.0e-10:
                    surface_vertices, surface_faces, face_source_ids = extend_roof_mesh_eaves(
                        surface_vertices, surface_faces, face_source_ids,
                        source_poly, poly, settings.overhang, math.tan(settings.pitch_angle)
                    )
                profile_vertices = surface_vertices
                profile_faces = surface_faces
                profile_sources = face_source_ids
                profile_outline = poly

        # The roof thickness is real mesh geometry translated along world +Z.
        world_thickness = Vector((0.0, 0.0, settings.thickness if settings.make_solid else 0.0))
        local_thickness = roof_obj.matrix_world.inverted_safe().to_3x3() @ world_thickness
        thickness_offset = (float(local_thickness.x), float(local_thickness.y), float(local_thickness.z))
        if settings.make_solid and settings.thickness > 0.0:
            mesh_vertices, mesh_faces = _extrude_mesh_global_z(
                surface_vertices, surface_faces, thickness_offset
            )
            cap_surface_vertices = [
                (v[0] + thickness_offset[0], v[1] + thickness_offset[1], v[2] + thickness_offset[2])
                for v in surface_vertices
            ]
            profile_cap_surface_vertices = [
                (v[0] + thickness_offset[0], v[1] + thickness_offset[1], v[2] + thickness_offset[2])
                for v in profile_vertices
            ]
        else:
            mesh_vertices, mesh_faces = list(surface_vertices), list(surface_faces)
            cap_surface_vertices = list(surface_vertices)
            profile_cap_surface_vertices = list(profile_vertices)

        mesh_face_source_ids = None
        if is_spatial or has_edge_pitches:
            surface_face_count = len(surface_faces)
            if len(mesh_faces) == surface_face_count:
                mesh_face_source_ids = [int(source_id) for source_id in face_source_ids]
            elif len(mesh_faces) >= surface_face_count * 2:
                sidewall_count = len(mesh_faces) - surface_face_count * 2
                mesh_face_source_ids = (
                    [-3] * surface_face_count
                    + [int(source_id) for source_id in face_source_ids]
                    + [-4] * sidewall_count
                )
            else:
                raise RoofForgeError(
                    "Не удалось сопоставить source ID с верхом/низом/стенками меша крыши."
                )
        _replace_mesh_data(
            roof_obj, roof_obj.name + "_Mesh", mesh_vertices, mesh_faces,
            face_source_ids=mesh_face_source_ids
        )
        _update_roof_modifiers(roof_obj, settings)
        if is_spatial or has_edge_pitches:
            _store_spatial_profile_source_mesh(
                roof_obj, profile_cap_surface_vertices, profile_faces, profile_sources
            )

        if not rebuild_details:
            roof_obj["roofforge_interactive_mode"] = True
            _hide_roof_helpers(roof_obj, True)
        else:
            if is_spatial or has_edge_pitches:
                seams = extract_roof_seams(
                    profile_cap_surface_vertices, profile_faces, profile_sources, profile_outline
                )
            else:
                seams = extract_roof_seams(
                    cap_surface_vertices, surface_faces, face_source_ids, source_poly
                )
    
            if is_spatial and roof_obj.get("roofforge_profile_source", False):
                # Once standalone profile tools are enabled, rebuilding their
                # settings must analyse the existing mesh only, not rerun the roof
                # solver. This also keeps the create/update commands independent.
                _rebuild_existing_roof_profiles(roof_obj, ("RIDGE", "VALLEY"))
            elif not roof_obj.get("roofforge_profile_source", False):
                ridge_obj = _ensure_helper_object(roof_obj, "_Ridges", "roofforge_ridges_object")
                valley_obj = _ensure_helper_object(roof_obj, "_Valleys", "roofforge_valleys_object")
    
                # For spatial roofs, profile geometry is inset on the original
                # planar facets. For horizontal roofs it follows the eave-extended
                # surface, preserving the legacy behavior.
                profile_input_vertices = profile_cap_surface_vertices
                profile_input_faces = profile_faces
                profile_input_outline = profile_outline
                if settings.show_ridges:
                    ridge_world_vector = Vector((0.0, 0.0, settings.ridge_extrusion))
                    ridge_local_vector = roof_obj.matrix_world.inverted_safe().to_3x3() @ ridge_world_vector
                    sink_world_vector = Vector((0.0, 0.0, -0.0002))
                    sink_local_vector = roof_obj.matrix_world.inverted_safe().to_3x3() @ sink_world_vector
                    rv, rf = build_inset_seam_profile_mesh(
                        profile_input_vertices, profile_input_faces, seams, "RIDGE",
                        settings.ridge_width,
                        (ridge_local_vector.x, ridge_local_vector.y, ridge_local_vector.z),
                        end_offset=settings.ridge_end_offset,
                        seat_sink_offset=(sink_local_vector.x, sink_local_vector.y, sink_local_vector.z),
                        outline=profile_input_outline,
                        boundary_edges=_mesh_boundary_segments(profile_input_vertices, profile_input_faces) if (is_spatial or has_edge_pitches) else None,
                    )
                else:
                    rv, rf = [], []
    
                if settings.show_valleys:
                    valley_world_vector = Vector((0.0, 0.0, settings.valley_extrusion))
                    valley_local_vector = roof_obj.matrix_world.inverted_safe().to_3x3() @ valley_world_vector
                    sink_world_vector = Vector((0.0, 0.0, -0.0002))
                    sink_local_vector = roof_obj.matrix_world.inverted_safe().to_3x3() @ sink_world_vector
                    vv, vf = build_inset_seam_profile_mesh(
                        profile_input_vertices, profile_input_faces, seams, "VALLEY",
                        settings.valley_width,
                        (valley_local_vector.x, valley_local_vector.y, valley_local_vector.z),
                        end_offset=settings.valley_end_offset,
                        seat_sink_offset=(sink_local_vector.x, sink_local_vector.y, sink_local_vector.z),
                        outline=profile_input_outline,
                        boundary_edges=_mesh_boundary_segments(profile_input_vertices, profile_input_faces) if is_spatial else None,
                    )
                else:
                    vv, vf = [], []
    
                _replace_mesh_data(ridge_obj, ridge_obj.name + "_Mesh", rv, rf)
                _replace_mesh_data(valley_obj, valley_obj.name + "_Mesh", vv, vf)
            else:
                # Non-spatial generated roofs that have been converted to the
                # standalone profile workflow are refreshed from their current mesh.
                _rebuild_existing_roof_profiles(roof_obj, ("RIDGE", "VALLEY"))
    
            if settings.show_standing_seams:
                standing_obj = _ensure_helper_object(
                    roof_obj, "_StandingSeams", "roofforge_standing_seams_object"
                )
                # Build the detail in world space so panel width, sink depth and
                # fold height remain real scene-unit values even after roof scale.
                world_surface = []
                for vertex in cap_surface_vertices:
                    world_point = roof_obj.matrix_world @ Vector(vertex)
                    world_surface.append((float(world_point.x), float(world_point.y), float(world_point.z)))
                standing_face_pairs = [
                    (face, source_id)
                    for face, source_id in zip(surface_faces, face_source_ids)
                    if source_id != -2
                ]
                standing_faces = [face for face, _source_id in standing_face_pairs]
                standing_sources = [source_id for _face, source_id in standing_face_pairs]
                world_ridge_graph = extract_roof_seams(
                    world_surface, standing_faces, standing_sources,
                    profile_outline if (is_spatial or has_edge_pitches) else source_poly
                )
                seam_world_vertices, seam_faces, seam_stats = build_standing_seam_mesh(
                    world_surface,
                    standing_faces,
                    world_ridge_graph,
                    panel_width=settings.standing_panel_width,
                    seam_height=settings.standing_seam_height,
                    seam_base_width=settings.standing_seam_width,
                    roof_thickness=(settings.thickness if settings.make_solid else 0.0),
                    ridge_height=settings.ridge_extrusion,
                    end_offset=settings.standing_end_offset,
                    boundary_edges=_mesh_boundary_segments(world_surface, standing_faces),
                )
                inverse_world = roof_obj.matrix_world.inverted_safe()
                seam_vertices = []
                for vertex in seam_world_vertices:
                    local_point = inverse_world @ Vector(vertex)
                    seam_vertices.append((float(local_point.x), float(local_point.y), float(local_point.z)))
                _replace_mesh_data(
                    standing_obj, standing_obj.name + "_Mesh", seam_vertices, seam_faces,
                    seam_edges=seam_stats.get("seam_edge_pairs", ()),
                )
            else:
                _remove_helper_object(roof_obj, "roofforge_standing_seams_object")
                seam_stats = {"segments": 0, "effective_height_max": 0.0}
            roof_obj["roofforge_standing_effective_height"] = seam_stats.get("effective_height_max", 0.0)
            roof_obj["roofforge_standing_segment_count"] = seam_stats.get("segments", 0)
            roof_obj["roofforge_standing_stats"] = json.dumps(seam_stats, separators=(",", ":"))
            roof_obj["roofforge_standing_error"] = ""
            roof_obj["roofforge_spatial_detail_notice"] = ""
        roof_obj["roofforge_error"] = ""
        roof_obj["roofforge_last_type"] = settings.roof_type
        roof_obj["roofforge_top_vertices"] = len(surface_vertices)
        roof_obj["roofforge_top_faces"] = len(surface_faces)
        roof_obj["roofforge_seam_edges"] = len(seams)
        roof_obj["roofforge_ridge_edge_count"] = sum(1 for edge in seams if str(edge[4]).upper() == "RIDGE")
        roof_obj["roofforge_valley_edge_count"] = sum(1 for edge in seams if str(edge[4]).upper() == "VALLEY")
    except Exception as exc:
        roof_obj["roofforge_error"] = str(exc)
    finally:
        roof_obj["roofforge_updating"] = False
        if rebuild_details:
            _PENDING_ROOF_FINALIZATIONS.pop(roof_obj.name, None)
            roof_obj["roofforge_interactive_mode"] = False
            _hide_roof_helpers(roof_obj, False)


# Roof geometry is refreshed at a configurable frame rate. Individual-angle
# edits use a roof-only path; detail meshes are rebuilt once the slider settles.
_PENDING_ROOF_UPDATES = {}
_PENDING_ROOF_FINALIZATIONS = {}
_LAST_ROOF_UPDATE = {}
_INTERACTIVE_FINALIZE_DELAY = 0.25


def _roof_update_interval(owner):
    try:
        rate = float(owner.roofforge_settings.interactive_update_rate)
    except (AttributeError, ReferenceError, TypeError, ValueError):
        rate = 30.0
    return 1.0 / max(1.0, min(60.0, rate))


def _flush_pending_roof_updates():
    next_due_times = []
    now = time.monotonic()

    for key, (owner, due_time, update_kind) in list(_PENDING_ROOF_UPDATES.items()):
        if now < due_time:
            next_due_times.append(due_time)
            continue
        _PENDING_ROOF_UPDATES.pop(key, None)
        try:
            if owner is None or owner.name not in bpy.data.objects:
                _PENDING_ROOF_FINALIZATIONS.pop(key, None)
                _LAST_ROOF_UPDATE.pop(key, None)
                continue
            if not owner.get("roofforge_generated", False):
                _PENDING_ROOF_FINALIZATIONS.pop(key, None)
                continue
            if update_kind == "interactive":
                _rebuild_generated_roof(owner, rebuild_details=False)
                update_finished = time.monotonic()
                _LAST_ROOF_UPDATE[key] = update_finished
                if owner.get("roofforge_error", ""):
                    _PENDING_ROOF_FINALIZATIONS.pop(key, None)
                    owner["roofforge_interactive_mode"] = False
                    _hide_roof_helpers(owner, False)
                else:
                    # The solver itself may take longer than the idle grace
                    # period. Start the detail-restoration pause only after the
                    # new roof surface is available.
                    pending_finalize = _PENDING_ROOF_FINALIZATIONS.get(key)
                    if pending_finalize is not None:
                        _PENDING_ROOF_FINALIZATIONS[key] = (
                            owner,
                            max(
                                pending_finalize[1],
                                update_finished + _INTERACTIVE_FINALIZE_DELAY,
                            ),
                        )
            elif update_kind == "roof":
                _rebuild_generated_roof(owner, rebuild_details=True)
                _LAST_ROOF_UPDATE[key] = time.monotonic()
                _PENDING_ROOF_FINALIZATIONS.pop(key, None)
            elif update_kind == "profiles":
                _rebuild_existing_roof_profiles(owner, ("RIDGE", "VALLEY"))
        except (ReferenceError, RuntimeError):
            continue

    for key, (owner, due_time) in list(_PENDING_ROOF_FINALIZATIONS.items()):
        pending = _PENDING_ROOF_UPDATES.get(key)
        if pending is not None and pending[2] in {"interactive", "roof"}:
            due_time = max(due_time, pending[1] + _INTERACTIVE_FINALIZE_DELAY)
            _PENDING_ROOF_FINALIZATIONS[key] = (owner, due_time)
            next_due_times.append(due_time)
            continue
        if now < due_time:
            next_due_times.append(due_time)
            continue
        _PENDING_ROOF_FINALIZATIONS.pop(key, None)
        try:
            if owner is None or owner.name not in bpy.data.objects:
                continue
            if not owner.get("roofforge_generated", False):
                continue
            # Both detail builders read the just-built mesh; neither executes a
            # second weighted straight-skeleton calculation.
            _rebuild_existing_roof_profiles(owner, ("RIDGE", "VALLEY"))
            _rebuild_standing_seams_for_mesh(owner)
        finally:
            if owner is not None:
                owner["roofforge_interactive_mode"] = False
                _hide_roof_helpers(owner, False)

    if not _PENDING_ROOF_UPDATES and not _PENDING_ROOF_FINALIZATIONS:
        return None
    if next_due_times:
        return max(0.001, min(next_due_times) - time.monotonic())
    return 0.001


def _schedule_roof_update(owner, update_kind="roof"):
    if not owner or owner.get("roofforge_updating", False):
        return
    key = owner.name
    now = time.monotonic()
    due_time = max(now, _LAST_ROOF_UPDATE.get(key, 0.0) + _roof_update_interval(owner))
    previous = _PENDING_ROOF_UPDATES.get(key)
    if previous is not None:
        if previous[2] == "roof":
            update_kind = "roof"
        elif previous[2] == "interactive" and update_kind == "profiles":
            update_kind = "interactive"
        due_time = min(due_time, previous[1])
    _PENDING_ROOF_UPDATES[key] = (owner, due_time, update_kind)

    try:
        if not bpy.app.timers.is_registered(_flush_pending_roof_updates):
            bpy.app.timers.register(
                _flush_pending_roof_updates,
                first_interval=max(0.001, due_time - now),
            )
    except (AttributeError, ReferenceError, RuntimeError):
        if update_kind == "interactive":
            _rebuild_generated_roof(owner, rebuild_details=False)
        elif update_kind == "profiles":
            _rebuild_existing_roof_profiles(owner, ("RIDGE", "VALLEY"))
        else:
            _rebuild_generated_roof(owner)


def _schedule_interactive_roof_update(owner):
    if not owner or owner.get("roofforge_updating", False):
        return
    now = time.monotonic()
    owner["roofforge_interactive_mode"] = True
    _hide_roof_helpers(owner, True)
    _PENDING_ROOF_FINALIZATIONS[owner.name] = (
        owner, now + _INTERACTIVE_FINALIZE_DELAY
    )
    _schedule_roof_update(owner, "interactive")


def _settings_update(self, context):
    owner = getattr(self, "id_data", None)
    if not isinstance(owner, bpy.types.Object):
        return
    if owner.get("roofforge_generated", False):
        _schedule_roof_update(owner, "roof")
    elif owner.get("roofforge_profile_source", False):
        _rebuild_existing_roof_profiles(owner)
    if owner.get("roofforge_standing_source", False):
        _rebuild_standing_seams_for_mesh(owner)


def _profile_settings_update(self, context):
    """Rebuild only the ridge/valley details; do not run the roof solver."""
    owner = getattr(self, "id_data", None)
    if not isinstance(owner, bpy.types.Object) or owner.get("roofforge_profiles_updating", False):
        return
    if owner.get("roofforge_profile_source", False):
        _rebuild_existing_roof_profiles(owner)
    elif owner.get("roofforge_generated", False):
        _schedule_roof_update(owner, "profiles")
    if owner.get("roofforge_standing_source", False):
        _rebuild_standing_seams_for_mesh(owner)
    elif owner.get("roofforge_profile_source", False) and owner.get("roofforge_generated", False):
        settings = owner.roofforge_settings
        if settings.show_standing_seams:
            _rebuild_standing_seams_for_mesh(owner)



# -----------------------------------------------------------------------------
# Spatial eave plan preview: numbered edge map
# -----------------------------------------------------------------------------
_SPATIAL_PREVIEW_COLLECTION = None
_SPATIAL_PREVIEW_PATH = None
_SPATIAL_PREVIEW_SIGNATURE = None
_SPATIAL_PREVIEW_REQUEST = None
_SPATIAL_PREVIEW_DUE = 0.0


def _spatial_preview_png(
    points, size=320, pitch_angles=None, facet_polygons=None, source_ids=None
):
    """Transparent, antialiased plan view; reuse supplied facets when available."""
    pts3 = [tuple(float(v) for v in p[:3]) if len(p) >= 3
            else (float(p[0]), float(p[1]), 0.0) for p in points]
    if len(pts3) < 3:
        raise ValueError("Для схемы нужно не менее трёх точек.")
    if pitch_angles is None or len(pitch_angles) != len(pts3):
        pitch_angles = [math.radians(35.0)] * len(pts3)
    if facet_polygons is not None:
        facet_polygons = [
            [(float(point[0]), float(point[1])) for point in polygon]
            for polygon in facet_polygons if len(polygon) >= 3
        ]
        if source_ids is None or len(source_ids) != len(facet_polygons):
            source_ids = list(range(len(facet_polygons)))
    else:
        try:
            roof_vertices, roof_faces, source_ids = build_spatial_roof_mesh(
                pts3, pitch_angles
            )
            facet_polygons = [[(roof_vertices[i][0], roof_vertices[i][1]) for i in face]
                              for face in roof_faces]
        except Exception:
            facet_polygons = [[(p[0], p[1]) for p in pts3]]
            source_ids = [0]
    if not facet_polygons:
        facet_polygons = [[(p[0], p[1]) for p in pts3]]
        source_ids = [0]

    all_xy = [p for poly in facet_polygons for p in poly]
    min_x, max_x = min(p[0] for p in all_xy), max(p[0] for p in all_xy)
    min_y, max_y = min(p[1] for p in all_xy), max(p[1] for p in all_xy)
    span = max(max_x-min_x, max_y-min_y, 1.0e-9)
    margin = max(20.0, size*0.09)
    scale = (size-2.0*margin)/span
    ox = (size-(max_x-min_x)*scale)*0.5
    oy = (size-(max_y-min_y)*scale)*0.5
    ss = 2
    high = size*ss
    alpha = bytearray(high*high)

    def screen(p):
        return ((ox+(p[0]-min_x)*scale)*ss,
                (size-(oy+(p[1]-min_y)*scale))*ss)

    def segment(a,b,radius):
        ax,ay=screen(a); bx,by=screen(b)
        dx,dy=bx-ax,by-ay
        den=dx*dx+dy*dy
        x0=max(0,int(math.floor(min(ax,bx)-radius-1)))
        x1=min(high-1,int(math.ceil(max(ax,bx)+radius+1)))
        y0=max(0,int(math.floor(min(ay,by)-radius-1)))
        y1=min(high-1,int(math.ceil(max(ay,by)+radius+1)))
        for yy in range(y0,y1+1):
            for xx in range(x0,x1+1):
                px,py=xx+0.5,yy+0.5
                t=0.0 if den<=1.0e-12 else max(0.0,min(1.0,((px-ax)*dx+(py-ay)*dy)/den))
                qx,qy=ax+t*dx,ay+t*dy
                if (px-qx)**2+(py-qy)**2<=radius*radius:
                    alpha[yy*high+xx]=255

    def inside(p,poly):
        x,y=p; result=False
        for i,a in enumerate(poly):
            b=poly[(i+1)%len(poly)]
            if (a[1]>y)!=(b[1]>y):
                ix=a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1])
                if x<ix: result=not result
        return result

    def boundary_distance(p,poly):
        x,y=p; best=float("inf")
        for i,a in enumerate(poly):
            b=poly[(i+1)%len(poly)]
            dx,dy=b[0]-a[0],b[1]-a[1]
            den=dx*dx+dy*dy
            t=0.0 if den<1.0e-20 else max(0.0,min(1.0,((x-a[0])*dx+(y-a[1])*dy)/den))
            best=min(best,math.hypot(x-a[0]-t*dx,y-a[1]-t*dy))
        return best

    def label_anchor(poly):
        best=(sum(p[0] for p in poly)/len(poly),sum(p[1] for p in poly)/len(poly))
        pxs=[p[0] for p in poly]; pys=[p[1] for p in poly]
        lo_x,hi_x=min(pxs),max(pxs); lo_y,hi_y=min(pys),max(pys)
        score=-1.0
        for gy in range(1,13):
            for gx in range(1,13):
                p=(lo_x+(hi_x-lo_x)*gx/13.0,lo_y+(hi_y-lo_y)*gy/13.0)
                if inside(p,poly):
                    d=boundary_distance(p,poly)
                    if d>score: best,score=p,d
        return best, max(0.0, score)

    glyphs={
      '0':('111','101','101','101','111'),'1':('010','110','010','010','111'),
      '2':('111','001','111','100','111'),'3':('111','001','111','001','111'),
      '4':('101','101','111','001','001'),'5':('111','100','111','001','111'),
      '6':('111','100','111','101','111'),'7':('111','001','010','010','010'),
      '8':('111','101','111','101','111'),'9':('111','101','111','001','111')}
    for fi,poly in enumerate(facet_polygons):
        if len(poly)<3: continue
        for i,a in enumerate(poly):
            segment(a,poly[(i+1)%len(poly)],ss*0.48)
        source=int(source_ids[fi]) if len(source_ids)==len(facet_polygons) else fi
        # Negative IDs identify transition caps, not pitched roof facets.
        # Keep their outlines visible but do not number them as a roof slope.
        if source < 0:
            continue
        label=str(source+1)
        anchor, clearance = label_anchor(poly)
        # Fit each fixed-style label to the local facet clearance. This keeps
        # the digits centred and prevents them from touching narrow facet rims.
        available_radius = clearance * scale * ss * 0.78
        glyph_radius_per_cell = math.hypot(2.0*len(label)-0.5, 2.5)
        fit_cell = int(math.floor(
            available_radius / max(glyph_radius_per_cell, 1.0e-9)
        ))
        if fit_cell < 2:
            continue
        cell=min(max(2,int(round(size/160.0))*ss),fit_cell)
        cx,cy=screen(anchor)
        gw,gh=3*cell,5*cell
        width=len(label)*(gw+cell)-cell
        sx,sy=int(round(cx-width/2)),int(round(cy-gh/2))
        for ci,ch in enumerate(label):
            for gy,row in enumerate(glyphs.get(ch,())):
                for gx,bit in enumerate(row):
                    if bit=="1":
                        for yy in range(sy+gy*cell,sy+(gy+1)*cell):
                            for xx in range(sx+ci*(gw+cell)+gx*cell,sx+ci*(gw+cell)+(gx+1)*cell):
                                if 0<=xx<high and 0<=yy<high: alpha[yy*high+xx]=255

    rgba=bytearray(size*size*4)
    for y in range(size):
        for x in range(size):
            total=0
            for sy in range(ss):
                start=(y*ss+sy)*high+x*ss
                total+=sum(alpha[start:start+ss])
            a=int(round(total/(ss*ss)))
            i=(y*size+x)*4
            rgba[i:i+4]=bytes((255,255,255,a))
    raw=b''.join(b'\x00'+bytes(rgba[y*size*4:(y+1)*size*4]) for y in range(size))
    import struct,zlib
    def chunk(tag,data):
        return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',size,size,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw,6))+chunk(b'IEND',b'')


def _flush_spatial_preview_request():
    global _SPATIAL_PREVIEW_REQUEST,_SPATIAL_PREVIEW_DUE
    global _SPATIAL_PREVIEW_COLLECTION,_SPATIAL_PREVIEW_PATH,_SPATIAL_PREVIEW_SIGNATURE
    request = _SPATIAL_PREVIEW_REQUEST
    if request is None:
        return None
    now = time.monotonic()
    if now < _SPATIAL_PREVIEW_DUE:
        return max(0.001, _SPATIAL_PREVIEW_DUE - now)

    (points, pitch_angles, facet_polygons, source_ids,
     signature, area) = request
    _SPATIAL_PREVIEW_REQUEST = None
    try:
        if _SPATIAL_PREVIEW_COLLECTION is None:
            _SPATIAL_PREVIEW_COLLECTION = bpy.utils.previews.new()
        if _SPATIAL_PREVIEW_PATH is None:
            fd, _SPATIAL_PREVIEW_PATH = tempfile.mkstemp(
                prefix="roofforge_spatial_", suffix=".png"
            )
            os.close(fd)
        with open(_SPATIAL_PREVIEW_PATH, "wb") as handle:
            handle.write(_spatial_preview_png(
                points,
                pitch_angles=pitch_angles,
                facet_polygons=facet_polygons,
                source_ids=source_ids,
            ))
        if "spatial_plan" in _SPATIAL_PREVIEW_COLLECTION:
            del _SPATIAL_PREVIEW_COLLECTION["spatial_plan"]
        _SPATIAL_PREVIEW_COLLECTION.load(
            "spatial_plan", _SPATIAL_PREVIEW_PATH, "IMAGE"
        )
        _SPATIAL_PREVIEW_SIGNATURE = signature
        try:
            if area is not None:
                area.tag_redraw()
        except (ReferenceError, RuntimeError):
            pass
    except Exception:
        # A failed preview should not block roof creation or other UI work.
        _SPATIAL_PREVIEW_REQUEST = None
    return None


def _get_spatial_preview_icon(points, pitch_angles=None, roof_obj=None, area=None, update_rate=30.0):
    global _SPATIAL_PREVIEW_COLLECTION,_SPATIAL_PREVIEW_PATH,_SPATIAL_PREVIEW_SIGNATURE
    global _SPATIAL_PREVIEW_REQUEST,_SPATIAL_PREVIEW_DUE
    if not points or len(points)<3: return 0
    if pitch_angles is None: pitch_angles=[math.radians(35.0)]*len(points)

    facet_polygons = None
    source_ids = None
    saved_mesh_signature = None
    if roof_obj is not None and roof_obj.get("roofforge_generated", False):
        try:
            mesh_name = str(roof_obj.get("roofforge_spatial_profile_source_mesh", ""))
            source_mesh = bpy.data.meshes.get(mesh_name) if mesh_name else None
            if source_mesh is not None and source_mesh.polygons:
                facet_polygons = [
                    [tuple(source_mesh.vertices[index].co) for index in polygon.vertices]
                    for polygon in source_mesh.polygons
                ]
                source_attribute = source_mesh.attributes.get("roofforge_face_source")
                if source_attribute is not None and len(source_attribute.data) == len(facet_polygons):
                    source_ids = [int(item.value) for item in source_attribute.data]
                else:
                    source_ids = list(range(len(facet_polygons)))
                saved_mesh_signature = (
                    source_mesh.name,
                    len(source_mesh.vertices),
                    len(source_mesh.polygons),
                )
        except (ReferenceError, RuntimeError, TypeError):
            facet_polygons = None
            source_ids = None
            saved_mesh_signature = None

    signature=(
        tuple(tuple(round(float(c),6) for c in p[:3]) for p in points),
        tuple(round(float(v),6) for v in pitch_angles),
        saved_mesh_signature,
    )
    try:
        if roof_obj is None and signature != _SPATIAL_PREVIEW_SIGNATURE:
            # The source-outline preview needs its own geometry solve. Delay it
            # until the user pauses a slider drag, then redraw only that panel.
            _SPATIAL_PREVIEW_REQUEST = (
                [tuple(float(value) for value in point[:3]) for point in points],
                list(pitch_angles),
                facet_polygons,
                source_ids,
                signature,
                area,
            )
            preview_interval = 1.0 / max(1.0, min(60.0, float(update_rate)))
            _SPATIAL_PREVIEW_DUE = time.monotonic() + preview_interval
            if not bpy.app.timers.is_registered(_flush_spatial_preview_request):
                bpy.app.timers.register(
                    _flush_spatial_preview_request,
                    first_interval=preview_interval,
                )
            if (_SPATIAL_PREVIEW_COLLECTION is not None
                    and 'spatial_plan' in _SPATIAL_PREVIEW_COLLECTION):
                return _SPATIAL_PREVIEW_COLLECTION['spatial_plan'].icon_id
            return 0

        if _SPATIAL_PREVIEW_COLLECTION is None:
            _SPATIAL_PREVIEW_COLLECTION=bpy.utils.previews.new()
        if signature != _SPATIAL_PREVIEW_SIGNATURE:
            if _SPATIAL_PREVIEW_PATH is None:
                fd,_SPATIAL_PREVIEW_PATH=tempfile.mkstemp(prefix='roofforge_spatial_',suffix='.png')
                os.close(fd)
            with open(_SPATIAL_PREVIEW_PATH,'wb') as f:
                f.write(_spatial_preview_png(
                    points,
                    pitch_angles=pitch_angles,
                    facet_polygons=facet_polygons,
                    source_ids=source_ids,
                ))
            if 'spatial_plan' in _SPATIAL_PREVIEW_COLLECTION:
                del _SPATIAL_PREVIEW_COLLECTION['spatial_plan']
            _SPATIAL_PREVIEW_COLLECTION.load('spatial_plan',_SPATIAL_PREVIEW_PATH,'IMAGE')
            _SPATIAL_PREVIEW_SIGNATURE=signature
        return _SPATIAL_PREVIEW_COLLECTION['spatial_plan'].icon_id
    except Exception:
        return 0


def _clear_spatial_preview():
    global _SPATIAL_PREVIEW_COLLECTION,_SPATIAL_PREVIEW_PATH,_SPATIAL_PREVIEW_SIGNATURE
    global _SPATIAL_PREVIEW_REQUEST,_SPATIAL_PREVIEW_DUE
    _SPATIAL_PREVIEW_REQUEST = None
    _SPATIAL_PREVIEW_DUE = 0.0
    try:
        if bpy.app.timers.is_registered(_flush_spatial_preview_request):
            bpy.app.timers.unregister(_flush_spatial_preview_request)
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    if _SPATIAL_PREVIEW_COLLECTION is not None:
        try: bpy.utils.previews.remove(_SPATIAL_PREVIEW_COLLECTION)
        except Exception: pass
        _SPATIAL_PREVIEW_COLLECTION=None
    if _SPATIAL_PREVIEW_PATH:
        try: os.remove(_SPATIAL_PREVIEW_PATH)
        except OSError: pass
        _SPATIAL_PREVIEW_PATH=None
    _SPATIAL_PREVIEW_SIGNATURE=None


def _spatial_outline_for_panel(active,roof_obj,is_generated):
    if is_generated and roof_obj and roof_obj.get('roofforge_generated',False):
        try:
            return json.loads(roof_obj.get('roofforge_outline','[]'))
        except Exception:
            return None
    try:
        points=_extract_loop_from_object(active)
        if len(points)>=3:
            return [(float(p.x),float(p.y),float(p.z)) for p in points]
    except Exception:
        pass
    return None


def _spatial_pitch_settings_update(self, context):
    owner = getattr(self, "id_data", None)
    if not isinstance(owner, bpy.types.Object) or not owner.get("roofforge_generated", False):
        return
    if owner.get("roofforge_updating", False):
        return
    count = int(owner.get("roofforge_edge_pitch_count", owner.get("roofforge_spatial_edge_count", 0)))
    if count < 3:
        return
    values = [float(getattr(self, f"spatial_pitch_{i:02d}")) for i in range(1, count+1)]
    owner["roofforge_edge_pitches"] = json.dumps(values, separators=(",", ":"))
    # Keep the legacy key populated for existing spatial roof files.
    if owner.get("roofforge_spatial", False):
        owner["roofforge_spatial_pitches"] = json.dumps(values, separators=(",", ":"))
    _schedule_interactive_roof_update(owner)


def _standing_seam_settings_update(self, context):
    """Rebuild only the seam detail; do not recalculate the roof skeleton."""
    owner = getattr(self, "id_data", None)
    if isinstance(owner, bpy.types.Object) and not owner.get("roofforge_updating", False) and (
        owner.get("roofforge_generated", False)
        or owner.get("roofforge_standing_source", False)
    ):
        _rebuild_standing_seams_for_mesh(owner)


# -----------------------------------------------------------------------------
# Properties
# -----------------------------------------------------------------------------


class ROOFFORGE_PG_Settings(bpy.types.PropertyGroup):
    roof_type: EnumProperty(
        name="Внутренний режим построения",
        description="Скрытый параметр совместимости; используется только режим свободных углов",
        items=[
            ('HIP_FREE', "Вальмовая / свободные углы",
             "Единый straight-skeleton режим для ортогональных и произвольных контуров"),
        ],
        default='HIP_FREE', options={'HIDDEN'}, update=_settings_update,
    )
    pitch_angle: FloatProperty(
        name="Уклон ската", description="Угол кровельной поверхности к горизонтали",
        default=math.radians(30.0), min=math.radians(0.0), max=math.radians(75.0),
        subtype='ANGLE', unit='ROTATION', update=_settings_update,
    )
    interactive_update_rate: FloatProperty(
        name="Частота обновления",
        description="Ограничивает частоту пересборки во время перетаскивания углов скатов",
        default=30.0, min=1.0, max=60.0, step=1, precision=0,
    )
    pitch_default_migrated: BoolProperty(
        name="Миграция уклона выполнена", default=False, options={'HIDDEN'},
    )
    overhang: FloatProperty(
        name="Свес карниза", description="Для плоского контура — горизонтальный вынос; для пространственного — расстояние по плоскости каждого ската. Исходный контур остаётся линией опирания нижней поверхности.",
        default=0.0, min=0.0, max=5.0, unit='LENGTH', update=_settings_update,
    )
    eave_lift: FloatProperty(
        name="Подъём от контура", description="Вертикальное смещение всей крыши вверх от уровня карниза",
        default=0.0, min=-10.0, max=10.0, unit='LENGTH', update=_settings_update,
    )
    thickness: FloatProperty(
        name="Толщина кровли", description="Реальная экструзия меша вверх по глобальной оси Z", default=0.01, min=0.001, max=2.0,
        unit='LENGTH', update=_settings_update,
    )
    make_solid: BoolProperty(
        name="Экструдировать вверх по Z", description="Создать нижнюю и верхнюю поверхности и боковые стенки геометрией меша", default=True, update=_settings_update,
    )
    shed_rise_angle: FloatProperty(
        name="Направление подъёма", description="Азимут подъёма односкатной крыши относительно мировой оси X",
        default=math.radians(90.0), min=math.radians(-360.0), max=math.radians(360.0),
        subtype='ANGLE', unit='ROTATION', options={'HIDDEN'}, update=_settings_update,
    )
    show_ridges: BoolProperty(
        name="Создать отдельный объект коньков", default=True, update=_profile_settings_update,
    )
    ridge_width: FloatProperty(
        name="Ширина конька", default=0.18, min=0.01, max=2.0, unit='LENGTH', update=_profile_settings_update,
    )
    ridge_extrusion: FloatProperty(
        name="Экструзия конька вверх", description="Высота профиля над поверхностью крыши",
        default=0.01, min=0.001, max=1.0, unit='LENGTH', update=_profile_settings_update,
    )
    ridge_end_offset: FloatProperty(
        name="Смещение концов конька",
        description="Положительное значение — вылет за карниз, отрицательное — отступ внутрь",
        default=0.0, min=-3.0, max=3.0, unit='LENGTH', update=_profile_settings_update,
    )
    # Hidden legacy values remain available for migration from 2.5.3 and older.
    ridge_end_extension: FloatProperty(
        name="Legacy: вылет конца конька", description="Совместимость со старыми .blend-файлами",
        default=0.10, min=0.0, max=3.0, unit='LENGTH', options={'HIDDEN'},
    )
    ridge_end_setback: FloatProperty(
        name="Legacy: отступ конца конька", default=0.0, min=0.0, max=3.0,
        unit='LENGTH', options={'HIDDEN'},
    )
    ridge_end_overhang: FloatProperty(
        name="Legacy: вылет конца конька", default=0.0, min=0.0, max=3.0,
        unit='LENGTH', options={'HIDDEN'},
    )
    show_valleys: BoolProperty(
        name="Создать отдельный объект ендов", default=True, update=_profile_settings_update,
    )
    valley_width: FloatProperty(
        name="Ширина ендовы", default=0.24, min=0.01, max=2.0, unit='LENGTH', update=_profile_settings_update,
    )
    valley_extrusion: FloatProperty(
        name="Экструзия ендовы вверх", description="Высота отдельного профиля ендовы над линией пересечения скатов",
        default=0.01, min=0.001, max=1.0, unit='LENGTH', update=_profile_settings_update,
    )
    valley_end_offset: FloatProperty(
        name="Смещение концов ендовы",
        description="Положительное значение — вылет за карниз, отрицательное — отступ внутрь",
        default=0.0, min=-3.0, max=3.0, unit='LENGTH', update=_profile_settings_update,
    )
    # Hidden legacy values remain available for migration from 2.5.3 and older.
    valley_end_extension: FloatProperty(
        name="Legacy: вылет конца ендовы", description="Совместимость со старыми .blend-файлами",
        default=0.10, min=0.0, max=3.0, unit='LENGTH', options={'HIDDEN'},
    )
    valley_end_setback: FloatProperty(
        name="Legacy: отступ конца ендовы", default=0.0, min=0.0, max=3.0,
        unit='LENGTH', options={'HIDDEN'},
    )
    valley_end_overhang: FloatProperty(
        name="Legacy: вылет конца ендовы", default=0.0, min=0.0, max=3.0,
        unit='LENGTH', options={'HIDDEN'},
    )
    show_standing_seams: BoolProperty(
        name="Создать фальцевую раскладку",
        description="Построить лёгкие продольные рёбра фальцев по верхним граням скатов",
        default=False, update=_standing_seam_settings_update,
    )
    standing_panel_width: FloatProperty(
        name="Ширина панели",
        description="Модуль фальцев, измеряемый по плоскости каждого ската; крайние панели автоматически балансируются",
        default=0.60, min=0.20, max=2.0, unit='LENGTH', update=_standing_seam_settings_update,
    )
    standing_seam_height: FloatProperty(
        name="Высота фальца",
        description="Высота над скатом; автоматически ограничивается 90% вертикальной экструзии конька",
        default=0.03, min=0.001, max=0.5, unit='LENGTH', update=_standing_seam_settings_update,
    )
    standing_seam_width: FloatProperty(
        name="Ширина основания фальца",
        description="Ширина узкой folded-полосы на поверхности ската",
        default=0.014, min=0.004, max=0.08, unit='LENGTH', update=_standing_seam_settings_update,
    )
    standing_end_offset: FloatProperty(
        name="Смещение концов",
        description="Положительное значение — вылет за внешний контур крыши, отрицательное — отступ внутрь",
        default=0.0, min=-3.0, max=3.0, unit='LENGTH', update=_standing_seam_settings_update,
    )
    end_offsets_migrated: BoolProperty(
        name="Legacy endpoint settings migrated", default=False, options={'HIDDEN'},
    )


# Per-eave-edge pitch controls. Dynamically declared to keep the PropertyGroup
# compact while still exposing stable RNA properties in Blender's UI.
for _edge_index in range(1, 33):
    ROOFFORGE_PG_Settings.__annotations__[f"spatial_pitch_{_edge_index:02d}"] = FloatProperty(
        name=f"Уклон ребра карниза {_edge_index}",
        description="Индивидуальный угол ската, связанного с этим ребром карниза",
        default=math.radians(35.0), min=math.radians(1.0), max=math.radians(85.0),
        subtype='ANGLE', unit='ROTATION', update=_spatial_pitch_settings_update,
    )


# -----------------------------------------------------------------------------
# Operators and UI
# -----------------------------------------------------------------------------


class ROOFFORGE_OT_Create(bpy.types.Operator):
    bl_idname = "roofforge.create_roof"
    bl_label = "Создать крышу"
    bl_description = "Создать параметрическую крышу; её ползунки будут пересобирать геометрию в реальном времени"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.object is not None and context.object.type == 'MESH'

    def execute(self, context):
        source_obj = context.object
        scene_settings = context.scene.roofforge_settings
        was_edit_mode = bool(source_obj and source_obj.mode == 'EDIT')
        roof_obj = None
        try:
            world_points = _extract_loop_from_object(source_obj)
            z_values = [float(point.z) for point in world_points]
            z_span = max(z_values) - min(z_values)
            xy_span = max(
                max(float(point.x) for point in world_points) - min(float(point.x) for point in world_points),
                max(float(point.y) for point in world_points) - min(float(point.y) for point in world_points),
                1.0,
            )
            is_spatial = z_span > max(1.0e-5, xy_span * 1.0e-6)
            if is_spatial:
                polygon, origin = _prepare_local_spatial_polygon(world_points)
            else:
                polygon, origin = _prepare_local_polygon(world_points)
            # Validate the selected outline before creating a scene object.
            if was_edit_mode:
                bpy.ops.object.mode_set(mode='OBJECT')

            mesh = bpy.data.meshes.new(source_obj.name + "_Roof_Mesh")
            roof_obj = bpy.data.objects.new(source_obj.name + "_Roof", mesh)
            collection = context.collection or context.scene.collection
            collection.objects.link(roof_obj)
            roof_obj.location = origin
            roof_obj["roofforge_source"] = source_obj.name
            roof_obj["roofforge_outline"] = json.dumps(polygon, separators=(",", ":"))
            roof_obj["roofforge_spatial"] = bool(is_spatial)
            roof_obj["roofforge_spatial_edge_count"] = len(polygon) if is_spatial else 0
            roof_obj["roofforge_edge_pitch_count"] = len(polygon)
            roof_obj["roofforge_ridges_object"] = ""
            roof_obj["roofforge_valleys_object"] = ""
            roof_obj["roofforge_standing_seams_object"] = ""

            target_settings = roof_obj.roofforge_settings
            for prop_name in _settings_values(scene_settings):
                setattr(target_settings, prop_name, getattr(scene_settings, prop_name))
            edge_pitches = [float(getattr(target_settings, f"spatial_pitch_{i:02d}")) for i in range(1, len(polygon)+1)]
            roof_obj["roofforge_edge_pitches"] = json.dumps(edge_pitches, separators=(",", ":"))
            if is_spatial:
                roof_obj["roofforge_spatial_pitches"] = json.dumps(edge_pitches, separators=(",", ":"))
            # Enable callbacks only after all starting values have been copied.
            roof_obj["roofforge_generated"] = True

            _rebuild_generated_roof(roof_obj)
            error = roof_obj.get("roofforge_error", "")
            if error:
                raise RoofForgeError(error)

            bpy.ops.object.select_all(action='DESELECT')
            roof_obj.select_set(True)
            context.view_layer.objects.active = roof_obj
            self.report({'INFO'}, "Параметрическая крыша создана. Настройки доступны в RoofForge.")
            return {'FINISHED'}
        except RoofForgeError as exc:
            if roof_obj is not None:
                _remove_roof_helpers(roof_obj)
                bpy.data.objects.remove(roof_obj, do_unlink=True)
            if was_edit_mode and source_obj and source_obj.mode != 'EDIT':
                try:
                    bpy.ops.object.select_all(action='DESELECT')
                    source_obj.select_set(True)
                    context.view_layer.objects.active = source_obj
                    bpy.ops.object.mode_set(mode='EDIT')
                except Exception:
                    pass
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        except Exception as exc:
            if roof_obj is not None:
                _remove_roof_helpers(roof_obj)
                bpy.data.objects.remove(roof_obj, do_unlink=True)
            if was_edit_mode and source_obj and source_obj.mode != 'EDIT':
                try:
                    bpy.ops.object.select_all(action='DESELECT')
                    source_obj.select_set(True)
                    context.view_layer.objects.active = source_obj
                    bpy.ops.object.mode_set(mode='EDIT')
                except Exception:
                    pass
            self.report({'ERROR'}, "RoofForge: ошибка: " + str(exc))
            return {'CANCELLED'}



class ROOFFORGE_OT_GenerateStandingSeams(bpy.types.Operator):
    bl_idname = "roofforge.generate_standing_seams"
    bl_label = "Создать фальцы на выбранной крыше"
    bl_description = "Анализировать верхние грани выбранного меша и создать фальцы отдельным лёгким объектом"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return (
            obj is not None and obj.type == 'MESH'
            and obj.mode == 'OBJECT'
            and not obj.get("roofforge_helper", False)
        )

    def execute(self, context):
        obj = context.object
        try:
            scene_settings = context.scene.roofforge_settings
            target = obj.roofforge_settings
            obj["roofforge_standing_updating"] = True
            try:
                for name in ("show_standing_seams", "standing_panel_width", "standing_seam_height", "standing_seam_width", "standing_end_offset", "thickness", "make_solid", "ridge_extrusion"):
                    setattr(target, name, getattr(scene_settings, name))
                target.show_standing_seams = True
                obj["roofforge_standing_source"] = True
            finally:
                obj["roofforge_standing_updating"] = False
            _rebuild_standing_seams_for_mesh(obj)
            error = obj.get("roofforge_standing_error", "")
            if error:
                self.report({'ERROR'}, error)
                return {'CANCELLED'}
            count = int(obj.get("roofforge_standing_segment_count", 0))
            self.report({'INFO'}, f"Создано фальцевых рёбер: {count}.")
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, "RoofForge: " + str(exc))
            return {'CANCELLED'}


class ROOFFORGE_OT_RebuildStandingSeams(bpy.types.Operator):
    bl_idname = "roofforge.rebuild_standing_seams"
    bl_label = "Обновить фальцы"
    bl_description = "Повторно проанализировать верхние грани исходного меша"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        obj = _helper_owner(obj)
        return obj is not None and obj.type == 'MESH' and obj.get("roofforge_standing_source", False)

    def execute(self, context):
        obj = context.object
        obj = _helper_owner(obj)
        _rebuild_standing_seams_for_mesh(obj)
        error = obj.get("roofforge_standing_error", "")
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}
        self.report({'INFO'}, "Фальцы обновлены.")
        return {'FINISHED'}


class _RoofForgeProfileOperator:
    """Shared implementation for external-mesh ridge and valley commands."""
    profile_kind = "RIDGE"
    profile_action = "CREATE"

    @classmethod
    def poll(cls, context):
        obj = context.object
        obj = _helper_owner(obj)
        return (obj is not None and obj.type == 'MESH' and obj.mode == 'OBJECT'
                and not obj.get("roofforge_helper", False))

    def execute(self, context):
        obj = context.object
        obj = _helper_owner(obj)
        kind = self.profile_kind
        lower = kind.lower()
        scene_settings = context.scene.roofforge_settings
        settings = obj.roofforge_settings
        try:
            if self.profile_action == "CREATE":
                obj["roofforge_profiles_updating"] = True
                try:
                    if not obj.get("roofforge_external_" + lower, False):
                        names = (
                            ("show_ridges", "ridge_width", "ridge_extrusion", "ridge_end_offset")
                            if kind == "RIDGE" else
                            ("show_valleys", "valley_width", "valley_extrusion", "valley_end_offset")
                        )
                        if not obj.get("roofforge_generated", False):
                            for name in names:
                                setattr(settings, name, getattr(scene_settings, name))
                    setattr(settings, "show_ridges" if kind == "RIDGE" else "show_valleys", True)
                    obj["roofforge_profile_source"] = True
                    obj["roofforge_external_" + lower] = True
                finally:
                    obj["roofforge_profiles_updating"] = False
            elif not obj.get("roofforge_external_" + lower, False):
                if obj.get("roofforge_generated", False):
                    obj["roofforge_profiles_updating"] = True
                    try:
                        obj["roofforge_profile_source"] = True
                        obj["roofforge_external_" + lower] = True
                    finally:
                        obj["roofforge_profiles_updating"] = False
                else:
                    self.report({'ERROR'}, "Сначала создайте этот профиль на выбранной крыше.")
                    return {'CANCELLED'}

            _rebuild_existing_roof_profiles(obj, (kind,))
            error = obj.get("roofforge_" + lower + "_error", "")
            if error:
                self.report({'ERROR'}, str(error))
                return {'CANCELLED'}
            count = int(obj.get("roofforge_" + lower + "_edge_count", 0))
            verb = "создан" if self.profile_action == "CREATE" else "обновлён"
            self.report({'INFO'}, f"Профиль {lower} {verb}; найдено стыков: {count}.")
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, "RoofForge: " + str(exc))
            return {'CANCELLED'}


class ROOFFORGE_OT_CreateRidges(_RoofForgeProfileOperator, bpy.types.Operator):
    bl_idname = "roofforge.create_ridges"
    bl_label = "Создать на выбранной крыше"
    bl_description = "Найти реальные стыки скатов в выбранном меше и создать отдельный объект коньков"
    bl_options = {'REGISTER', 'UNDO'}
    profile_kind = "RIDGE"
    profile_action = "CREATE"


class ROOFFORGE_OT_UpdateRidges(_RoofForgeProfileOperator, bpy.types.Operator):
    bl_idname = "roofforge.update_ridges"
    bl_label = "Обновить"
    bl_description = "Повторно проанализировать выбранный меш и обновить только объект коньков"
    bl_options = {'REGISTER', 'UNDO'}
    profile_kind = "RIDGE"
    profile_action = "UPDATE"


class ROOFFORGE_OT_CreateValleys(_RoofForgeProfileOperator, bpy.types.Operator):
    bl_idname = "roofforge.create_valleys"
    bl_label = "Создать на выбранной крыше"
    bl_description = "Найти реальные вогнутые стыки скатов в выбранном меше и создать отдельный объект ендов"
    bl_options = {'REGISTER', 'UNDO'}
    profile_kind = "VALLEY"
    profile_action = "CREATE"


class ROOFFORGE_OT_UpdateValleys(_RoofForgeProfileOperator, bpy.types.Operator):
    bl_idname = "roofforge.update_valleys"
    bl_label = "Обновить"
    bl_description = "Повторно проанализировать выбранный меш и обновить только объект ендов"
    bl_options = {'REGISTER', 'UNDO'}
    profile_kind = "VALLEY"
    profile_action = "UPDATE"


class ROOFFORGE_OT_Rebuild(bpy.types.Operator):
    bl_idname = "roofforge.rebuild_roof"
    bl_label = "Пересобрать крышу"
    bl_description = "Перестроить активную параметрическую крышу"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object
        obj = _helper_owner(obj)
        return obj is not None and obj.type == 'MESH' and obj.get("roofforge_generated", False)

    def execute(self, context):
        obj = context.object
        obj = _helper_owner(obj)
        _rebuild_generated_roof(obj)
        error = obj.get("roofforge_error", "")
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}
        self.report({'INFO'}, "Крыша обновлена.")
        return {'FINISHED'}


class ROOFFORGE_PT_Panel(bpy.types.Panel):
    bl_label = "RoofForge"
    bl_idname = "ROOFFORGE_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "RoofForge"

    def draw(self, context):
        layout = self.layout
        active = context.object
        roof_obj = _helper_owner(active)

        is_generated = bool(roof_obj and roof_obj.type == 'MESH' and roof_obj.get("roofforge_generated", False))
        is_spatial_generated = bool(is_generated and roof_obj.get("roofforge_spatial", False))
        is_standing_source = bool(roof_obj and roof_obj.type == 'MESH' and roof_obj.get("roofforge_standing_source", False))
        is_profile_source = bool(roof_obj and roof_obj.type == 'MESH' and roof_obj.get("roofforge_profile_source", False))
        settings = roof_obj.roofforge_settings if (is_generated or is_standing_source or is_profile_source) else context.scene.roofforge_settings

        if is_generated:
            layout.label(text="Параметрическая крыша", icon='HOME')
            layout.label(text=roof_obj.name, icon='MESH_DATA')
            err = roof_obj.get("roofforge_error", "")
            if err:
                box = layout.box()
                box.alert = True
                box.label(text="Ошибка пересборки", icon='ERROR')
                box.label(text=err[:120])
            layout.label(text=("Пространственные плоские скаты." if is_spatial_generated else "Плоские скаты, без сеточного подразделения."), icon='TIME')
            if roof_obj.get("roofforge_top_vertices", 0):
                layout.label(text=f"Скаты: {roof_obj.get('roofforge_top_vertices', 0)} вершин / {roof_obj.get('roofforge_top_faces', 0)} граней")
        elif is_profile_source or is_standing_source:
            layout.label(text="Инструменты для готовой крыши", icon='MESH_DATA')
            layout.label(text=roof_obj.name)
            error = roof_obj.get("roofforge_profile_error", "")
            if error:
                box = layout.box()
                box.alert = True
                box.label(text=error[:140], icon='ERROR')
            standing_error = roof_obj.get("roofforge_standing_error", "")
            if standing_error:
                box = layout.box()
                box.alert = True
                box.label(text=standing_error[:140], icon='ERROR')
        else:
            layout.label(text="Источник: замкнутый контур карниза", icon='MESH_CIRCLE')
            layout.label(text="Edit Mode: выделите рёбра одного edge loop.")
            layout.label(text="Object Mode: используйте отдельный граничный loop.")
            spatial_outline = _spatial_outline_for_panel(active, roof_obj, is_generated)
            if spatial_outline:
                edge_box = layout.box()
                edge_box.label(text="План крыши — номера соответствуют скатам", icon='MESH_CIRCLE')
                pitch_values = [float(getattr(settings, f"spatial_pitch_{i:02d}"))
                                for i in range(1, min(len(spatial_outline), 32)+1)]
                preview_icon = _get_spatial_preview_icon(
                    spatial_outline, pitch_values, area=context.area,
                    update_rate=settings.interactive_update_rate,
                )
                if preview_icon:
                    region_width = max(240, getattr(context.region, "width", 320))
                    preview_scale = max(4.0, min(14.0, region_width / 42.0))
                    edge_box.template_icon(preview_icon, scale=preview_scale)
                edge_box.label(text="Нумерация скатов соответствует рёбрам исходного контура.")
                edge_box.label(text=f"Рёбер карниза: {len(spatial_outline)}")
                for edge_index in range(1, min(len(spatial_outline), 32)+1):
                    edge_box.prop(settings, f"spatial_pitch_{edge_index:02d}", text=f"Скат {edge_index}")
                edge_box.prop(settings, "interactive_update_rate", text="Частота обновления")

        # Roof shape controls are available only for a source loop or a
        # parametric RoofForge roof. Imported roof meshes are never rebuilt.
        if is_generated or (not is_profile_source and not is_standing_source):
            layout.separator()
            layout.label(text="Геометрия крыши", icon='MOD_BUILD')
            edge_pitch_count = int(roof_obj.get(
                "roofforge_edge_pitch_count",
                roof_obj.get("roofforge_spatial_edge_count", 0)
            )) if is_generated else 0
            if is_generated and edge_pitch_count >= 3:
                layout.label(
                    text=("Пространственный карниз: индивидуальные углы" if is_spatial_generated
                          else "Индивидуальные углы скатов"),
                    icon='ORIENTATION_GLOBAL'
                )
                edge_count = edge_pitch_count
                spatial_outline = _spatial_outline_for_panel(active, roof_obj, True)
                pitch_values = json.loads(roof_obj.get(
                    "roofforge_edge_pitches",
                    roof_obj.get("roofforge_spatial_pitches", "[]")
                ))
                preview_icon = _get_spatial_preview_icon(
                    spatial_outline, pitch_values, roof_obj=roof_obj, area=context.area,
                    update_rate=settings.interactive_update_rate,
                ) if spatial_outline else 0
                if preview_icon:
                    region_width = max(240, getattr(context.region, "width", 320))
                    preview_scale = max(4.0, min(14.0, region_width / 42.0))
                    layout.template_icon(preview_icon, scale=preview_scale)
                layout.label(text="Номер внутри контура = номер угла ската.")
                for edge_index in range(1, min(edge_count, 32)+1):
                    layout.prop(settings, f"spatial_pitch_{edge_index:02d}", text=f"Скат {edge_index}")
                layout.prop(settings, "interactive_update_rate", text="Частота обновления")
                layout.prop(settings, "overhang", text="Свес карниза")
                layout.prop(settings, "eave_lift")
                if is_spatial_generated:
                    layout.label(text="Свес измеряется по плоскости каждого ската.", icon='INFO')
            else:
                layout.prop(settings, "pitch_angle")
                layout.prop(settings, "overhang")
                layout.prop(settings, "eave_lift")

            layout.separator()
            layout.label(text="Толщина кровли", icon='OUTLINER_OB_MESH')
            layout.prop(settings, "make_solid")
            if settings.make_solid:
                layout.prop(settings, "thickness")
                layout.label(text="Реальная геометрия: экструзия +Z", icon='INFO')

        # Ridge and valley tools analyse the actual finished roof mesh. For
        # generated spatial roofs the same mesh-derived path is used after the
        # first explicit Create command; it never calls the roof solver.
        ridge_box = layout.box()
        ridge_box.label(text="Коньки — анализ стыков готовой крыши", icon='MESH_CUBE')
        ridge_box.prop(settings, "show_ridges")
        if settings.show_ridges:
            ridge_box.prop(settings, "ridge_width")
            ridge_box.prop(settings, "ridge_extrusion")
            ridge_box.prop(settings, "ridge_end_offset")
        row = ridge_box.row(align=True)
        row.operator("roofforge.create_ridges", text="Создать на выбранной крыше", icon='ADD')
        row.operator("roofforge.update_ridges", text="Обновить", icon='FILE_REFRESH')
        ridge_error = roof_obj.get("roofforge_ridge_error", "") if roof_obj else ""
        if ridge_error:
            ridge_box.alert = True
            ridge_box.label(text=ridge_error[:120], icon='ERROR')
        elif is_spatial_generated:
            ridge_box.label(text=f"3D-стыков конька: {int(roof_obj.get('roofforge_ridge_edge_count', 0))}", icon='INFO')

        valley_box = layout.box()
        valley_box.label(text="Ендовы — анализ стыков готовой крыши", icon='MOD_BOOLEAN')
        valley_box.prop(settings, "show_valleys")
        if settings.show_valleys:
            valley_box.prop(settings, "valley_width")
            valley_box.prop(settings, "valley_extrusion")
            valley_box.prop(settings, "valley_end_offset")
        row = valley_box.row(align=True)
        row.operator("roofforge.create_valleys", text="Создать на выбранной крыше", icon='ADD')
        row.operator("roofforge.update_valleys", text="Обновить", icon='FILE_REFRESH')
        valley_error = roof_obj.get("roofforge_valley_error", "") if roof_obj else ""
        if valley_error:
            valley_box.alert = True
            valley_box.label(text=valley_error[:120], icon='ERROR')
        elif is_spatial_generated:
            valley_box.label(text=f"3D-стыков ендовы: {int(roof_obj.get('roofforge_valley_edge_count', 0))}", icon='INFO')

        seam_box = layout.box()
        seam_box.label(text="Фальцевая кровля", icon='MOD_ARRAY')
        if is_generated or is_standing_source:
            seam_box.prop(settings, "show_standing_seams")
            if settings.show_standing_seams:
                seam_box.prop(settings, "standing_panel_width")
                seam_box.prop(settings, "standing_seam_height")
                seam_box.prop(settings, "standing_seam_width")
                seam_box.prop(settings, "standing_end_offset")
                if is_standing_source:
                    seam_box.prop(settings, "thickness", text="Толщина для заглубления")
                    seam_box.prop(settings, "ridge_extrusion", text="Высота ограничивающего конька")
                effective = float(roof_obj.get("roofforge_standing_effective_height", 0.0))
                seam_box.label(text=f"Фактическая высота: {effective:.4f} м")
                seam_box.label(text="Высота по нормали; лимит 90% от конька.", icon='INFO')
                seam_box.label(text="Две продольные кромки плеча фальца помечены Seam.", icon='INFO')
                seam_error = roof_obj.get("roofforge_standing_error", "")
                if seam_error:
                    seam_box.alert = True
                    seam_box.label(text=seam_error[:100], icon='ERROR')
        else:
            scene_settings = context.scene.roofforge_settings
            seam_box.prop(scene_settings, "show_standing_seams")
            if scene_settings.show_standing_seams:
                seam_box.prop(scene_settings, "standing_panel_width")
                seam_box.prop(scene_settings, "standing_seam_height")
                seam_box.prop(scene_settings, "standing_seam_width")
                seam_box.prop(scene_settings, "standing_end_offset")
            seam_box.prop(scene_settings, "ridge_extrusion", text="Высота ограничивающего конька")
            seam_box.operator("roofforge.generate_standing_seams", icon='MOD_ARRAY')
            seam_box.label(text="Работает по верхним граням выбранного меша.", icon='INFO')

        layout.separator()
        if is_generated:
            layout.operator("roofforge.rebuild_roof", icon='FILE_REFRESH')
            layout.label(text="Исходный контур сохранён внутри объекта крыши.", icon='INFO')
        elif is_standing_source:
            layout.operator("roofforge.rebuild_standing_seams", icon='FILE_REFRESH')
        elif is_profile_source:
            layout.label(text="Исходная геометрия не изменяется.", icon='INFO')
        else:
            layout.operator("roofforge.create_roof", icon='HOME')
        layout.label(text="Размеры задаются в единицах Blender.", icon='INFO')


CLASSES = (
    ROOFFORGE_PG_Settings,
    ROOFFORGE_OT_Create,
    ROOFFORGE_OT_GenerateStandingSeams,
    ROOFFORGE_OT_RebuildStandingSeams,
    ROOFFORGE_OT_CreateRidges,
    ROOFFORGE_OT_UpdateRidges,
    ROOFFORGE_OT_CreateValleys,
    ROOFFORGE_OT_UpdateValleys,
    ROOFFORGE_OT_Rebuild,
    ROOFFORGE_PT_Panel,
)


def _migrate_legacy_thickness():
    """Migrate the old 0.18 m default after Blender has finished registration.

    Blender may expose bpy.data as _RestrictData while an extension's register()
    function is running. This callback is deliberately deferred through the
    application timer, where normal data access is available.
    """
    try:
        scenes = tuple(bpy.data.scenes)
        objects = tuple(bpy.data.objects)
    except (AttributeError, ReferenceError, RuntimeError):
        # Keep retrying if Blender is still in its restricted startup phase.
        return 0.5

    for scene in scenes:
        settings = getattr(scene, "roofforge_settings", None)
        if settings is None:
            continue
        _migrate_to_free_angle(settings)
        if abs(settings.thickness - 0.18) < 1.0e-7:
            settings.thickness = 0.01
        _migrate_endpoint_offsets(settings)
        _migrate_pitch_default(settings)

    for obj in objects:
        settings = getattr(obj, "roofforge_settings", None)
        if settings is None:
            continue
        _migrate_to_free_angle(settings)
        if (obj.get("roofforge_generated", False)
                or obj.get("roofforge_standing_source", False)
                or obj.get("roofforge_profile_source", False)):
            if abs(settings.thickness - 0.18) < 1.0e-7:
                settings.thickness = 0.01
            _migrate_endpoint_offsets(settings)
            _migrate_pitch_default(settings)

    return None


def _migrate_to_free_angle(settings):
    """Map every saved legacy roof type to the single supported free-angle mode."""
    try:
        if settings.roof_type != 'HIP_FREE':
            settings.roof_type = 'HIP_FREE'
    except (AttributeError, TypeError, ValueError, RuntimeError):
        pass


def _migrate_endpoint_offsets(settings):
    """Convert old overhang/setback pairs into one signed endpoint offset."""
    if getattr(settings, "end_offsets_migrated", False):
        return
    settings.ridge_end_offset = (
        float(settings.ridge_end_overhang) - float(settings.ridge_end_setback)
    )
    settings.valley_end_offset = (
        float(settings.valley_end_overhang) - float(settings.valley_end_setback)
    )
    settings.end_offsets_migrated = True


def _migrate_pitch_default(settings):
    """Convert the accidental saved 0-degree default to the intended 30 degrees once.

    Explicit non-zero user values are retained. The hidden marker prevents a
    user from being forced back to 30 degrees after intentionally editing the
    slope later in the project.
    """
    if getattr(settings, "pitch_default_migrated", False):
        return
    try:
        current_pitch = float(settings.pitch_angle)
    except (AttributeError, TypeError, ValueError):
        current_pitch = math.radians(30.0)
    if abs(current_pitch) <= 1.0e-8:
        settings.pitch_angle = math.radians(30.0)
    settings.pitch_default_migrated = True


def _schedule_legacy_migration():
    """Schedule migration without touching bpy.data during register()."""
    try:
        if not bpy.app.timers.is_registered(_migrate_legacy_thickness):
            bpy.app.timers.register(_migrate_legacy_thickness, first_interval=0.5)
    except (AttributeError, ReferenceError, RuntimeError):
        # Registration itself must remain successful even in restricted context.
        pass


def _roofforge_load_post(_unused):
    # Re-run after a .blend is opened: the add-on can be enabled before the
    # user's project data is loaded, so an initial registration timer is not
    # sufficient for every startup order.
    _schedule_legacy_migration()


# Mark the handler persistent so opening another .blend keeps migration support.
_roofforge_load_post = bpy.app.handlers.persistent(_roofforge_load_post)


def register():
    # Do not enumerate bpy.data here. Blender can pass _RestrictData while
    # importing/registering extensions, which has no .scenes/.objects access.
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.roofforge_settings = PointerProperty(type=ROOFFORGE_PG_Settings)
    bpy.types.Object.roofforge_settings = PointerProperty(type=ROOFFORGE_PG_Settings)

    if _roofforge_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_roofforge_load_post)
    _schedule_legacy_migration()


def unregister():
    _clear_spatial_preview()
    _PENDING_ROOF_UPDATES.clear()
    _PENDING_ROOF_FINALIZATIONS.clear()
    _LAST_ROOF_UPDATE.clear()
    try:
        if bpy.app.timers.is_registered(_flush_pending_roof_updates):
            bpy.app.timers.unregister(_flush_pending_roof_updates)
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    if _roofforge_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_roofforge_load_post)

    try:
        if bpy.app.timers.is_registered(_migrate_legacy_thickness):
            bpy.app.timers.unregister(_migrate_legacy_thickness)
    except (AttributeError, ReferenceError, RuntimeError):
        pass

    if hasattr(bpy.types.Scene, "roofforge_settings"):
        del bpy.types.Scene.roofforge_settings
    if hasattr(bpy.types.Object, "roofforge_settings"):
        del bpy.types.Object.roofforge_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
