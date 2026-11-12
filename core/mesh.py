"""Roof surface mesh assembly from plane-envelope cells."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from math import floor
from typing import Sequence

from .geometry import GeometryInputError, PlaneZ, _bbox_scale, signed_area
from .planes import boundary_envelope_conflicts, build_boundary_planes
from .envelope import lower_envelope_cells, lower_envelope_restricted_cells

Point2 = tuple[float, float]
Point3 = tuple[float, float, float]
Face = tuple[int, ...]


@dataclass(frozen=True)
class RoofSurface:
    """Open upper roof surface; thickness and eaves are later build stages."""
    vertices: tuple[Point3, ...]
    faces: tuple[Face, ...]
    face_slope_indices: tuple[int, ...]
    planes: tuple[PlaneZ, ...]
    source_area_xy: float
    surface_area_xy: float
    boundary_xy: tuple[Point2, ...]
    approximation_error: float = 0.0
    refinement_depth: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.faces


class _VertexRegistry:
    """Deterministic 3D vertex welding with a scale-aware spatial hash."""

    def __init__(self, tolerance: float):
        self.tolerance = tolerance
        self.vertices: list[Point3] = []
        self.buckets: dict[tuple[int, int, int], list[int]] = {}

    def _key(self, point: Point3) -> tuple[int, int, int]:
        return tuple(floor(value / self.tolerance) for value in point)

    def add(self, point: Point3) -> int:
        key = self._key(point)
        tol_sq = self.tolerance * self.tolerance
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    nearby = self.buckets.get((key[0] + dx, key[1] + dy, key[2] + dz), ())
                    for index in nearby:
                        existing = self.vertices[index]
                        distance_sq = sum((existing[i] - point[i]) ** 2 for i in range(3))
                        if distance_sq <= tol_sq:
                            return index
        index = len(self.vertices)
        self.vertices.append(point)
        self.buckets.setdefault(key, []).append(index)
        return index


def _split_face_edges_at_shared_vertices(
    vertices: Sequence[Point3],
    faces: Sequence[Face],
    tolerance: float,
) -> list[Face]:
    """Conform face boundaries by inserting shared vertices on long edges.

    Clipped cells created from different triangulation/arrangement regions can
    produce a T-junction: one face uses a long edge while its neighbour uses
    two shorter edges meeting at a vertex. This pass inserts that existing
    vertex into the long edge without moving geometry or changing the face
    region, so edge-incidence validation sees matching topology.
    """
    tolerance_sq = tolerance * tolerance
    output: list[Face] = []
    axis_orders: list[list[int]] = []
    axis_values: list[list[float]] = []
    for axis in range(3):
        order = sorted(
            range(len(vertices)),
            key=lambda vertex_id: (vertices[vertex_id][axis], vertex_id),
        )
        axis_orders.append(order)
        axis_values.append([vertices[vertex_id][axis] for vertex_id in order])

    for face in faces:
        expanded: list[int] = []
        for edge_index, start_id in enumerate(face):
            end_id = face[(edge_index + 1) % len(face)]
            start = vertices[start_id]
            end = vertices[end_id]
            direction = tuple(end[axis] - start[axis] for axis in range(3))
            length_sq = sum(value * value for value in direction)
            if length_sq <= tolerance_sq:
                raise GeometryInputError(
                    "ZERO_LENGTH_FACE_EDGE",
                    "После сборки фасет найдено ребро нулевой длины.",
                )

            points_on_edge: list[tuple[float, int]] = []
            search_axis = min(range(3), key=lambda axis: abs(direction[axis]))
            lower_value = min(start[search_axis], end[search_axis]) - tolerance
            upper_value = max(start[search_axis], end[search_axis]) + tolerance
            values = axis_values[search_axis]
            order = axis_orders[search_axis]
            candidate_start = bisect_left(values, lower_value)
            candidate_end = bisect_right(values, upper_value)

            for candidate_position in range(candidate_start, candidate_end):
                candidate_id = order[candidate_position]
                if candidate_id == start_id or candidate_id == end_id:
                    continue
                candidate = vertices[candidate_id]
                if any(
                    candidate[axis] < min(start[axis], end[axis]) - tolerance
                    or candidate[axis] > max(start[axis], end[axis]) + tolerance
                    for axis in range(3)
                    if axis != search_axis
                ):
                    continue
                relative = tuple(candidate[axis] - start[axis] for axis in range(3))
                parameter = sum(
                    relative[axis] * direction[axis] for axis in range(3)
                ) / length_sq
                endpoint_margin = tolerance / (length_sq ** 0.5)
                if parameter <= endpoint_margin or parameter >= 1.0 - endpoint_margin:
                    continue
                projected = tuple(
                    start[axis] + parameter * direction[axis] for axis in range(3)
                )
                distance_sq = sum(
                    (candidate[axis] - projected[axis]) ** 2 for axis in range(3)
                )
                if distance_sq <= tolerance_sq:
                    points_on_edge.append((parameter, candidate_id))

            points_on_edge.sort(key=lambda item: (item[0], item[1]))
            if not expanded:
                expanded.append(start_id)
            expanded.extend(candidate_id for _, candidate_id in points_on_edge)
            if expanded[-1] != end_id:
                expanded.append(end_id)

        compact: list[int] = []
        for vertex_id in expanded:
            if not compact or compact[-1] != vertex_id:
                compact.append(vertex_id)
        if len(compact) > 1 and compact[0] == compact[-1]:
            compact.pop()
        if len(set(compact)) < 3:
            raise GeometryInputError(
                "DEGENERATE_CONFORMED_FACE",
                "Разбиение T-junction создало вырожденную грань.",
            )
        output.append(tuple(compact))
    return output


def _mesh_edge_usage(faces: Sequence[Face]) -> dict[tuple[int, int], int]:
    usage: dict[tuple[int, int], int] = {}
    for face in faces:
        for index, first in enumerate(face):
            second = face[(index + 1) % len(face)]
            edge = (min(first, second), max(first, second))
            usage[edge] = usage.get(edge, 0) + 1
    return usage



def _point_on_boundary_segment(point: tuple[float, float], start: Point2, end: Point2,
                               tolerance: float) -> bool:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length <= tolerance:
        return False
    px, py = point[0] - start[0], point[1] - start[1]
    if abs(dx * py - dy * px) / length > tolerance:
        return False
    projection = (px * dx + py * dy) / (length * length)
    margin = tolerance / length
    return -margin <= projection <= 1.0 + margin


def validate_surface_boundary_edges(vertices: Sequence[Point3], faces: Sequence[Face],
                                     boundary_xy: Sequence[Point2],
                                     tolerance: float) -> list[tuple[int, int]]:
    """Return directed outer boundary edges or reject internal cracks.

    Every single-use edge must lie on exactly one source-contour segment, and
    the edge chain must cover each source segment exactly once in XY.
    """
    edge_uses: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for face in faces:
        for index, first in enumerate(face):
            second = face[(index + 1) % len(face)]
            key = (min(first, second), max(first, second))
            edge_uses.setdefault(key, []).append((first, second))

    open_edges: list[tuple[int, int]] = []
    for uses in edge_uses.values():
        if len(uses) > 2:
            raise GeometryInputError(
                "NON_MANIFOLD_SURFACE",
                "Верхняя поверхность содержит ребро с более чем двумя смежными гранями."
            )
        if len(uses) == 1:
            open_edges.append(uses[0])

    covered = [0.0 for _ in boundary_xy]
    for first, second in open_edges:
        p, q = vertices[first], vertices[second]
        matches = []
        for index, start in enumerate(boundary_xy):
            end = boundary_xy[(index + 1) % len(boundary_xy)]
            if (_point_on_boundary_segment((p[0], p[1]), start, end, tolerance)
                    and _point_on_boundary_segment((q[0], q[1]), start, end, tolerance)):
                matches.append(index)
        if len(matches) != 1:
            raise GeometryInputError(
                "INTERNAL_OPEN_EDGE",
                f"Верхняя поверхность разорвана: открытое ребро "
                f"({p[0]:.6g}, {p[1]:.6g}) → ({q[0]:.6g}, {q[1]:.6g}) "
                f"не является частью исходного контура."
            )
        covered[matches[0]] += ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5

    for index, start in enumerate(boundary_xy):
        end = boundary_xy[(index + 1) % len(boundary_xy)]
        expected = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
        allowed = max(tolerance * 10.0, expected * 1e-7)
        if abs(covered[index] - expected) > allowed:
            raise GeometryInputError(
                "BOUNDARY_COVERAGE_MISMATCH",
                f"Карнизный сегмент {index + 1} покрыт не полностью: "
                f"{covered[index]:.8g} из {expected:.8g}."
            )
    return open_edges

def build_roof_surface_from_planes(
    domain: Sequence[Point2],
    planes: Sequence[PlaneZ],
    *,
    source_area_xy: float | None = None,
    eps: float = 1e-9,
    active_contour: Sequence[Point2] | None = None,
) -> RoofSurface:
    """Assemble a continuous lower envelope over an expanded build domain.

    The optional active contour retains ownership of the original eave planes.
    Exterior overhang cells inherit the active set from their nearest point on
    that contour, so shifted reflex edges cannot undercut the source roof.
    """
    if len(planes) < 3:
        raise GeometryInputError(
            "PLANE_COUNT",
            "Для расширенной поверхности нужны минимум три плоскости скатов.",
        )
    if len(domain) < 3 or len(planes) < 3:
        raise GeometryInputError(
            "INPUT_COUNT",
            "Для построения поверхности нужны минимум три вершины и три плоскости.",
        )

    domain_area = abs(signed_area(domain))
    if domain_area <= eps:
        raise GeometryInputError(
            "DEGENERATE_DOMAIN",
            "Расширенный контур имеет нулевую площадь.",
        )
    activation_area = (
        float(source_area_xy)
        if source_area_xy is not None
        else domain_area
    )

    scale = max(
        1.0,
        _bbox_scale(domain),
    )
    weld_tolerance = max(1e-12, eps * scale * 100.0)
    area_tolerance = eps * scale * scale

    cells_by_slope = lower_envelope_restricted_cells(
        domain, planes, eps, active_contour=active_contour
    )
    registry = _VertexRegistry(weld_tolerance)
    faces: list[Face] = []
    face_slope_indices: list[int] = []
    face_keys: set[tuple[int, ...]] = set()

    for slope_index, cells in enumerate(cells_by_slope):
        plane = planes[slope_index]
        for cell in cells:
            if len(cell) < 3 or abs(signed_area(cell)) <= area_tolerance:
                continue
            face_indices = [
                registry.add((x, y, plane.height(x, y)))
                for x, y in cell
            ]
            compact: list[int] = []
            for vertex_index in face_indices:
                if not compact or compact[-1] != vertex_index:
                    compact.append(vertex_index)
            if len(compact) > 1 and compact[0] == compact[-1]:
                compact.pop()
            if len(set(compact)) < 3:
                continue
            if signed_area(cell) < 0.0:
                compact.reverse()
            key = tuple(sorted(compact))
            if key in face_keys:
                continue
            face_keys.add(key)
            faces.append(tuple(compact))
            face_slope_indices.append(slope_index)

    if not faces:
        raise GeometryInputError(
            "EMPTY_ROOF",
            "Нижняя огибающая не создала ни одной области расширенной крыши.",
        )

    faces = _split_face_edges_at_shared_vertices(
        registry.vertices, faces, weld_tolerance * 5.0
    )

    surface_area_xy = sum(
        abs(signed_area([
            (registry.vertices[index][0], registry.vertices[index][1])
            for index in face
        ]))
        for face in faces
    )
    if abs(surface_area_xy - domain_area) > max(
        area_tolerance * 100.0, domain_area * 1e-7
    ):
        raise GeometryInputError(
            "DOMAIN_COVERAGE_MISMATCH",
            f"Области расширенной крыши покрывают {surface_area_xy:.9g} "
            f"из {domain_area:.9g} квадратных единиц внешнего контура.",
        )

    edge_usage = _mesh_edge_usage(faces)
    non_manifold_edges = [
        edge for edge, count in edge_usage.items() if count > 2
    ]
    if non_manifold_edges:
        raise GeometryInputError(
            "NON_MANIFOLD_SURFACE",
            f"При сборке расширенной поверхности обнаружено рёбер с более чем "
            f"двумя гранями: {len(non_manifold_edges)}.",
        )

    validate_surface_boundary_edges(
        registry.vertices, faces, domain, weld_tolerance * 5.0
    )

    return RoofSurface(
        vertices=tuple(registry.vertices),
        faces=tuple(faces),
        face_slope_indices=tuple(face_slope_indices),
        planes=tuple(planes),
        source_area_xy=activation_area,
        surface_area_xy=surface_area_xy,
        boundary_xy=tuple(domain),
    )


def _has_reflex_vertex(domain: Sequence[Point2], eps: float) -> bool:
    """Return whether a simple XY contour contains a genuine reflex turn."""
    area = signed_area(domain)
    if abs(area) <= eps:
        return False
    winding = 1.0 if area > 0.0 else -1.0
    scale = max(_bbox_scale(domain), 1.0)
    turn_tolerance = eps * scale * scale
    count = len(domain)
    for index, current in enumerate(domain):
        previous = domain[index - 1]
        following = domain[(index + 1) % count]
        turn = (
            (current[0] - previous[0]) * (following[1] - current[1])
            - (current[1] - previous[1]) * (following[0] - current[0])
        )
        if turn * winding < -turn_tolerance:
            return True
    return False


def build_roof_surface(points: Sequence[Point3], pitches_degrees: Sequence[float],
                       eps: float = 1e-9) -> RoofSurface:
    """Build an open planar upper surface from a closed 3D boundary loop.

    Returned roof-face winding is always counter-clockwise in XY, so normals
    point toward the roof-local +Z direction even if the source loop is CW.
    The source contour is never modified.
    """
    planes = build_boundary_planes(points, pitches_degrees, eps)
    domain = [(point[0], point[1]) for point in points]
    domain_area = abs(signed_area(domain))
    scale = max(
        1.0,
        max(point[0] for point in points) - min(point[0] for point in points),
        max(point[1] for point in points) - min(point[1] for point in points),
        max(point[2] for point in points) - min(point[2] for point in points),
    )

    # Infinite inward half-planes are not valid influence regions for a
    # concave contour. Their extensions cross the polygon interior and can
    # switch candidate planes off along an internal line. For a mixed-height
    # concave contour, use each authored edge's finite projection interval.
    mixed_height_concave = (
        _has_reflex_vertex(domain, eps)
        and max(point[2] for point in points) - min(point[2] for point in points)
        > eps * scale * 10.0
    )
    active_support = points if mixed_height_concave else None
    active_support_xy = domain if mixed_height_concave else None

    conflicts = boundary_envelope_conflicts(
        points, planes, eps, active_contour=active_support
    )
    if conflicts:
        raise GeometryInputError(conflicts[0].code, conflicts[0].message)

    weld_tolerance = max(1e-12, eps * scale * 100.0)
    area_tolerance = eps * scale * scale

    cells_by_slope = lower_envelope_restricted_cells(
        domain, planes, eps, active_contour=active_support_xy
    )
    registry = _VertexRegistry(weld_tolerance)
    faces: list[Face] = []
    face_slope_indices: list[int] = []
    face_keys: set[tuple[int, ...]] = set()

    for slope_index, cells in enumerate(cells_by_slope):
        plane = planes[slope_index]
        for cell in cells:
            if len(cell) < 3 or abs(signed_area(cell)) <= area_tolerance:
                continue
            face_indices = [
                registry.add((x, y, plane.height(x, y)))
                for x, y in cell
            ]
            compact: list[int] = []
            for vertex_index in face_indices:
                if not compact or compact[-1] != vertex_index:
                    compact.append(vertex_index)
            if len(compact) > 1 and compact[0] == compact[-1]:
                compact.pop()
            if len(set(compact)) < 3:
                continue
            if signed_area(cell) < 0.0:
                compact.reverse()
            key = tuple(sorted(compact))
            if key in face_keys:
                continue
            face_keys.add(key)
            faces.append(tuple(compact))
            face_slope_indices.append(slope_index)

    if not faces:
        raise GeometryInputError("EMPTY_ROOF", "Нижняя огибающая не создала ни одной области крыши.")

    faces = _split_face_edges_at_shared_vertices(
        registry.vertices, faces, weld_tolerance * 5.0
    )
    surface_area_xy = sum(
        abs(signed_area([(registry.vertices[i][0], registry.vertices[i][1]) for i in face]))
        for face in faces
    )
    if abs(surface_area_xy - domain_area) > max(area_tolerance * 100.0, domain_area * 1e-7):
        raise GeometryInputError(
            "DOMAIN_COVERAGE_MISMATCH",
            f"Области крыши покрывают {surface_area_xy:.9g} из {domain_area:.9g} квадратных единиц контура."
        )

    edge_usage = _mesh_edge_usage(faces)
    non_manifold_edges = [edge for edge, count in edge_usage.items() if count > 2]
    if non_manifold_edges:
        raise GeometryInputError(
            "NON_MANIFOLD_SURFACE",
            f"При сборке поверхности обнаружено рёбер с более чем двумя гранями: {len(non_manifold_edges)}."
        )

    # A projected-area match alone can hide cracks whose missing and
    # overlapping regions cancel. Validate all open edges against the exact
    # source boundary before exposing the surface to Blender.
    validate_surface_boundary_edges(
        registry.vertices, faces, domain, weld_tolerance * 5.0
    )

    return RoofSurface(
        vertices=tuple(registry.vertices),
        faces=tuple(faces),
        face_slope_indices=tuple(face_slope_indices),
        planes=tuple(planes),
        source_area_xy=domain_area,
        surface_area_xy=surface_area_xy,
        boundary_xy=tuple(domain),
    )
