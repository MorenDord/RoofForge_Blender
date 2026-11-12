"""Closed roof shell generation with an optional source-contour underside."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
import re

from .geometry import GeometryInputError, triangulate_simple_polygon
from .mesh import RoofSurface, validate_surface_boundary_edges
from .validation import validate_closed_mesh

Point3 = tuple[float, float, float]
Face = tuple[int, ...]


@dataclass(frozen=True)
class RoofShell:
    """Closed mesh payload split into top, bottom and boundary-wall faces."""
    vertices: tuple[Point3, ...]
    faces: tuple[Face, ...]
    top_face_count: int
    bottom_face_count: int
    side_face_count: int
    thickness: float
    extrude_up: bool = False




def _orient_shell_faces(
    faces: Sequence[Face],
    fixed_face_count: int,
) -> tuple[Face, ...]:
    """Orient bottom and wall faces consistently with fixed top-face winding.

    The source roof surface is the authoritative oriented boundary. A breadth-
    first traversal propagates its winding across the shell's edge adjacency.
    It never flips a top face; a conflict between two fixed top faces is
    reported as an invalid roof surface.
    """
    edge_uses: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
    for face_index, face in enumerate(faces):
        for local_index, first in enumerate(face):
            second = face[(local_index + 1) % len(face)]
            key = (min(first, second), max(first, second))
            edge_uses.setdefault(key, []).append((face_index, first, second))

    adjacency: list[list[tuple[int, bool]]] = [[] for _ in faces]
    for edge_key, uses in edge_uses.items():
        if len(uses) > 2:
            raise GeometryInputError(
                "SHELL_NON_MANIFOLD_EDGE",
                f"Ребро оболочки {edge_key} принадлежит более чем двум граням.",
            )
        if len(uses) != 2:
            continue
        first_use, second_use = uses
        same_direction = (
            first_use[1] == second_use[1]
            and first_use[2] == second_use[2]
        )
        adjacency[first_use[0]].append((second_use[0], same_direction))
        adjacency[second_use[0]].append((first_use[0], same_direction))

    flips: list[bool | None] = [None] * len(faces)
    for top_face in range(fixed_face_count):
        if flips[top_face] is None:
            flips[top_face] = False
        queue = [top_face]
        cursor = 0
        while cursor < len(queue):
            current = queue[cursor]
            cursor += 1
            current_flip = bool(flips[current])
            for neighbour, same_direction in adjacency[current]:
                required_flip = current_flip ^ same_direction
                if flips[neighbour] is None:
                    if neighbour < fixed_face_count and required_flip:
                        raise GeometryInputError(
                            "TOP_FACE_WINDING_CONFLICT",
                            f"Исходные верхние грани {current} и {neighbour} имеют несовместимую ориентацию.",
                        )
                    flips[neighbour] = required_flip
                    queue.append(neighbour)
                elif bool(flips[neighbour]) != required_flip:
                    raise GeometryInputError(
                        "SHELL_WINDING_CONFLICT",
                        f"Нельзя согласовать направление граней {current} и {neighbour} вокруг их общего ребра.",
                    )

    # Any component not connected to a top face is invalid for this shell
    # construction, but still orient it deterministically for diagnostics.
    for start in range(len(faces)):
        if flips[start] is not None:
            continue
        flips[start] = False
        queue = [start]
        cursor = 0
        while cursor < len(queue):
            current = queue[cursor]
            cursor += 1
            for neighbour, same_direction in adjacency[current]:
                required_flip = bool(flips[current]) ^ same_direction
                if flips[neighbour] is None:
                    flips[neighbour] = required_flip
                    queue.append(neighbour)
                elif bool(flips[neighbour]) != required_flip:
                    raise GeometryInputError(
                        "SHELL_WINDING_CONFLICT",
                        f"Изолированный компонент оболочки неориентируем: грани {current} и {neighbour}.",
                    )

    return tuple(
        tuple(reversed(face)) if flips[index] else tuple(face)
        for index, face in enumerate(faces)
    )

def _normal_offset_shell(
    surface: RoofSurface,
    thickness: float,
    eps: float,
    *,
    extrude_up: bool,
) -> RoofShell:
    """Build a closed shell around a piecewise-planar surface with vertical caps.

    Unlike global-Z extrusion, vertex-normal offsetting also works for
    vertical transition faces. The top surface is preserved byte-for-byte.
    Bottom faces are triangulated individually, so even a mildly warped
    vertex-normal offset remains a valid piecewise-planar underside.
    """
    top_vertices = tuple(tuple(float(value) for value in point) for point in surface.vertices)
    vertex_count = len(top_vertices)
    scale = max(
        1.0,
        *(
            max(point[axis] for point in top_vertices)
            - min(point[axis] for point in top_vertices)
            for axis in range(3)
        ),
    )
    tolerance = max(1e-12, eps * scale * 10.0)

    face_normals: list[Point3] = []
    vertex_normal_sums = [[0.0, 0.0, 0.0] for _ in top_vertices]

    for face_index, face in enumerate(surface.faces):
        if len(face) < 3:
            raise GeometryInputError(
                "DEGENERATE_TOP_FACE",
                f"Верхняя грань {face_index} содержит менее трёх вершин.",
            )
        nx = ny = nz = 0.0
        for local_index, vertex_index in enumerate(face):
            current = top_vertices[vertex_index]
            following = top_vertices[face[(local_index + 1) % len(face)]]
            nx += (current[1] - following[1]) * (current[2] + following[2])
            ny += (current[2] - following[2]) * (current[0] + following[0])
            nz += (current[0] - following[0]) * (current[1] + following[1])
        magnitude = sqrt(nx * nx + ny * ny + nz * nz)
        if magnitude <= tolerance * tolerance:
            raise GeometryInputError(
                "DEGENERATE_TOP_FACE",
                f"Верхняя грань {face_index} имеет нулевую площадь.",
            )
        normal = (nx / magnitude, ny / magnitude, nz / magnitude)
        face_normals.append(normal)
        for vertex_index in face:
            vertex_normal_sums[vertex_index][0] += nx
            vertex_normal_sums[vertex_index][1] += ny
            vertex_normal_sums[vertex_index][2] += nz

    offset_sign = 1.0 if extrude_up else -1.0
    bottom_vertices: list[Point3] = []
    for vertex_index, point in enumerate(top_vertices):
        normal_sum = vertex_normal_sums[vertex_index]
        magnitude = sqrt(sum(value * value for value in normal_sum))
        if magnitude <= tolerance * tolerance:
            raise GeometryInputError(
                "UNDEFINED_OFFSET_NORMAL",
                f"Не удалось вычислить устойчивую нормаль для вершины {vertex_index}.",
            )
        normal = tuple(value / magnitude for value in normal_sum)
        bottom_vertices.append(tuple(
            point[axis] + offset_sign * thickness * normal[axis]
            for axis in range(3)
        ))

    if extrude_up:
        output_top_vertices = tuple(bottom_vertices)
        output_bottom_vertices = top_vertices
    else:
        output_top_vertices = top_vertices
        output_bottom_vertices = tuple(bottom_vertices)

    vertices = tuple(output_top_vertices + output_bottom_vertices)
    output_faces: list[Face] = [tuple(face) for face in surface.faces]
    bottom_faces: list[Face] = []

    for face_index, face in enumerate(surface.faces):
        normal = face_normals[face_index]
        points = [top_vertices[index] for index in face]
        drop_axis = max(range(3), key=lambda axis: abs(normal[axis]))
        keep_axes = tuple(axis for axis in range(3) if axis != drop_axis)
        projected = [(point[keep_axes[0]], point[keep_axes[1]]) for point in points]

        # Remove projected collinear degree-two points before ear clipping.
        compact_indices = list(range(len(face)))
        changed = True
        while changed and len(compact_indices) > 3:
            changed = False
            for local_index in range(len(compact_indices)):
                previous = projected[compact_indices[local_index - 1]]
                current = projected[compact_indices[local_index]]
                following = projected[
                    compact_indices[(local_index + 1) % len(compact_indices)]
                ]
                cross = (
                    (current[0] - previous[0]) * (following[1] - current[1])
                    - (current[1] - previous[1]) * (following[0] - current[0])
                )
                if abs(cross) <= tolerance * max(
                    1.0,
                    sqrt((current[0] - previous[0]) ** 2 + (current[1] - previous[1]) ** 2),
                    sqrt((following[0] - current[0]) ** 2 + (following[1] - current[1]) ** 2),
                ):
                    del compact_indices[local_index]
                    changed = True
                    break

        if len(compact_indices) < 3:
            raise GeometryInputError(
                "DEGENERATE_BOTTOM_FACE",
                f"Нижняя грань {face_index} схлопнулась после смещения по нормали.",
            )
        compact_projected = [projected[index] for index in compact_indices]
        coordinate_map = {
            point: face[original_index]
            for point, original_index in zip(compact_projected, compact_indices)
        }
        try:
            triangles = triangulate_simple_polygon(compact_projected, max(1e-12, tolerance / scale))
        except GeometryInputError as exc:
            raise GeometryInputError(
                "BOTTOM_TRIANGULATION_FAILED",
                f"Не удалось триангулировать смещённую нижнюю грань {face_index}: {exc.message}",
            ) from exc

        for triangle in triangles:
            original_ids = tuple(coordinate_map[point] for point in triangle)
            bottom_ids = tuple(index + vertex_count for index in original_ids)
            # Preserve the original top-face winding when orienting the
            # underside triangle. The normal-offset bottom may be warped
            # slightly at creases, so its local triangle normal must not be
            # allowed to flip the combinatorial face orientation.
            a, b, c = (top_vertices[index] for index in original_ids)
            ux = b[0] - a[0]
            uy = b[1] - a[1]
            uz = b[2] - a[2]
            vx = c[0] - a[0]
            vy = c[1] - a[1]
            vz = c[2] - a[2]
            triangle_normal = (
                uy * vz - uz * vy,
                uz * vx - ux * vz,
                ux * vy - uy * vx,
            )
            if sum(triangle_normal[axis] * normal[axis] for axis in range(3)) > 0.0:
                bottom_ids = tuple(reversed(bottom_ids))
            bottom_faces.append(bottom_ids)

    output_faces.extend(bottom_faces)
    boundary_edges = validate_surface_boundary_edges(
        surface.vertices, surface.faces, surface.boundary_xy, tolerance * 5.0
    )
    side_faces: list[Face] = []
    for first, second in boundary_edges:
        first_bottom = first + vertex_count
        second_bottom = second + vertex_count
        side_faces.append((first, first_bottom, second_bottom))
        side_faces.append((first, second_bottom, second))

    output_faces.extend(side_faces)
    output_faces = list(_orient_shell_faces(
        output_faces, len(surface.faces)
    ))
    diagnostics = validate_closed_mesh(vertices, output_faces, eps)
    if diagnostics:
        first = diagnostics[0]
        face_indices = [
            int(value) for value in re.findall(r"\\d+", first.message)
            if int(value) < len(output_faces)
        ][:2]
        details = []
        for face_index in face_indices:
            face = output_faces[face_index]
            details.append(
                f"face {face_index}: "
                + repr(tuple(vertices[index] for index in face))
            )
        context = (" Геометрия: " + "; ".join(details)) if details else ""
        raise GeometryInputError(first.code, first.message + context)

    return RoofShell(
        vertices=vertices,
        faces=tuple(output_faces),
        top_face_count=len(surface.faces),
        bottom_face_count=len(bottom_faces),
        side_face_count=len(side_faces),
        thickness=thickness,
        extrude_up=bool(extrude_up),
    )

def build_roof_shell(
    surface: RoofSurface,
    thickness: float,
    eps: float = 1e-9,
    *,
    extrude_up: bool = False,
) -> RoofShell:
    """Create a closed Z-extruded shell.

    When extrude_up is true, the supplied surface is the support/underside
    surface. It remains at its authored elevation, including the original
    eave contour, while roof thickness is added above it.
    """
    if not isfinite(thickness) or thickness <= 0.0:
        raise GeometryInputError("INVALID_THICKNESS", "Толщина крыши должна быть положительным конечным числом.")
    if not surface.vertices or not surface.faces:
        raise GeometryInputError("EMPTY_SURFACE", "Нельзя создать оболочку из пустой поверхности.")
    if len(surface.face_slope_indices) != len(surface.faces):
        raise GeometryInputError("FACE_METADATA_MISMATCH", "Количество идентификаторов скатов не совпадает с количеством граней.")
    if len(surface.boundary_xy) < 3:
        raise GeometryInputError("MISSING_BOUNDARY", "Поверхность не содержит исходный контур карниза.")

    scale = max(
        1.0,
        max(v[0] for v in surface.vertices) - min(v[0] for v in surface.vertices),
        max(v[1] for v in surface.vertices) - min(v[1] for v in surface.vertices),
        max(v[2] for v in surface.vertices) - min(v[2] for v in surface.vertices),
        thickness,
    )
    tolerance = max(1e-12, eps * scale * 100.0)
    # Keep the exact planar roof partition unchanged through shell creation.
    # A vertex-normal offset averages normals across sharp source-plane seams;
    # on non-concurrent concave junctions that can fold the underside back
    # through itself. Global-Z extrusion preserves every planar face and the
    # XY topology, including exact transition triangles.
    boundary_edges = validate_surface_boundary_edges(
        surface.vertices, surface.faces, surface.boundary_xy, tolerance * 5.0
    )
    vertex_count = len(surface.vertices)
    if extrude_up:
        top_vertices = tuple((x, y, z + thickness) for x, y, z in surface.vertices)
        bottom_vertices = tuple(surface.vertices)
    else:
        top_vertices = tuple(surface.vertices)
        bottom_vertices = tuple((x, y, z - thickness) for x, y, z in surface.vertices)
    vertices = top_vertices + bottom_vertices
    top_faces = [tuple(face) for face in surface.faces]
    bottom_faces = [
        tuple(index + vertex_count for index in reversed(face))
        for face in surface.faces
    ]
    side_faces = [
        (first, first + vertex_count, second + vertex_count, second)
        for first, second in boundary_edges
    ]
    faces = tuple(top_faces + bottom_faces + side_faces)

    diagnostics = validate_closed_mesh(vertices, faces, eps)
    if diagnostics:
        first = diagnostics[0]
        raise GeometryInputError(first.code, first.message)
    return RoofShell(
        vertices=vertices,
        faces=faces,
        top_face_count=len(top_faces),
        bottom_face_count=len(bottom_faces),
        side_face_count=len(side_faces),
        thickness=thickness,
        extrude_up=bool(extrude_up),
    )
