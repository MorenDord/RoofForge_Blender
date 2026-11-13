"""Experimental exact lower-envelope solver with finite inward edge supports.

Each 3D eave edge defines one analytical support plane. The support plane is
eligible only in the inward halfspace of its own finite source segment. The
XY domain is split along exact support/endpoint lines; within each resulting
cell, all active support-plane equalities are solved analytically.

This implementation is intentionally separate from the legacy overhang and
roof-surface assembly paths, whose edge-activation semantics are different.
"""
from __future__ import annotations

from math import hypot
from typing import Sequence

from .geometry import (
    GeometryInputError,
    PlaneZ,
    _bbox_scale,
    clip_half_plane,
    lower_envelope_cells,
    lower_envelope_regions,
    signed_area,
    triangulate_simple_polygon,
)
from .mesh import (
    RoofSurface,
    _VertexRegistry,
    _mesh_edge_usage,
    _split_face_edges_at_shared_vertices,
    validate_surface_boundary_edges,
)
from .planes import build_boundary_planes

Point2 = tuple[float, float]
Point3 = tuple[float, float, float]
Face = tuple[int, ...]


def _validate_finite_inward_eave_support(
    points: Sequence[Point3],
    planes: Sequence[PlaneZ],
    eps: float,
) -> None:
    """Reject only competitors active on a finite source edge's inward side."""
    domain = [(point[0], point[1]) for point in points]
    winding = 1.0 if signed_area(domain) > 0.0 else -1.0
    scale = max(_bbox_scale(domain), 1.0)
    z_tolerance = eps * scale
    projection_tolerance = max(eps * 10.0, 1e-12)

    for edge_index, start in enumerate(points):
        end = points[(edge_index + 1) % len(points)]
        own = planes[edge_index]
        for other_index, other in enumerate(planes):
            if other_index == edge_index:
                continue
            other_start = points[other_index]
            other_end = points[(other_index + 1) % len(points)]
            ox = other_end[0] - other_start[0]
            oy = other_end[1] - other_start[1]
            length_sq = ox * ox + oy * oy
            edge_length = hypot(ox, oy)
            if edge_length <= eps * scale:
                continue

            def projection_at(t: float) -> float:
                x = start[0] + (end[0] - start[0]) * t
                y = start[1] + (end[1] - start[1]) * t
                return ((x - other_start[0]) * ox + (y - other_start[1]) * oy) / length_sq

            side_tolerance = eps * scale * edge_length

            def inward_side_at(t: float) -> float:
                x = start[0] + (end[0] - start[0]) * t
                y = start[1] + (end[1] - start[1]) * t
                return winding * (
                    ox * (y - other_start[1])
                    - oy * (x - other_start[0])
                )

            breaks = [0.0, 1.0]
            p0, p1 = projection_at(0.0), projection_at(1.0)
            projection_delta = p1 - p0
            if abs(projection_delta) > projection_tolerance:
                for boundary in (0.0, 1.0):
                    crossing = (boundary - p0) / projection_delta
                    if 0.0 < crossing < 1.0:
                        breaks.append(crossing)

            side0, side1 = inward_side_at(0.0), inward_side_at(1.0)
            side_delta = side1 - side0
            if abs(side_delta) > side_tolerance:
                crossing = (-side_tolerance - side0) / side_delta
                if 0.0 < crossing < 1.0:
                    breaks.append(crossing)

            breaks.sort()
            for t0, t1 in zip(breaks, breaks[1:]):
                midpoint = 0.5 * (t0 + t1)
                projection = projection_at(midpoint)
                if not (
                    projection_tolerance < projection < 1.0 - projection_tolerance
                    and inward_side_at(midpoint) >= -side_tolerance
                ):
                    continue
                for t in (t0, midpoint, t1):
                    x = start[0] + (end[0] - start[0]) * t
                    y = start[1] + (end[1] - start[1]) * t
                    if other.height(x, y) - own.height(x, y) < -z_tolerance:
                        raise GeometryInputError(
                            "BOUNDARY_UNDERCUT",
                            f"Плоскость ската {other_index + 1} опускается ниже "
                            f"карниза ската {edge_index + 1} в своей конечной "
                            "внутренней области влияния.",
                        )


def _lower_envelope_finite_inward_cells(
    domain: Sequence[Point2],
    planes: Sequence[PlaneZ],
    eps: float,
) -> list[list[list[Point2]]]:
    """Partition a concave footprint by finite inward support activation.

    Projection endpoint lines and source support lines make the active set
    constant inside every arrangement cell. Each cell is then clipped by
    exact affine plane-equality halfspaces to form the lower envelope.
    """
    count = len(domain)
    if count < 3 or len(planes) != count:
        raise GeometryInputError(
            "PLANE_COUNT",
            "Для каждого ребра 3D-контура нужна одна опорная плоскость.",
        )

    triangles = triangulate_simple_polygon(domain, eps)
    output: list[list[list[Point2]]] = [[] for _ in planes]
    scale = max(_bbox_scale(domain), 1.0)
    # Preserve small but resolvable arrangement cells near acute corners.
    # Topology validation below rejects genuinely degenerate faces/edges.
    area_tolerance = eps * scale * scale * 1.0e-3
    point_tolerance = eps * scale * 20.0
    winding = 1.0 if signed_area(domain) > 0.0 else -1.0

    edge_data: list[tuple[float, float, float, float, float, float]] = []
    for index, start in enumerate(domain):
        end = domain[(index + 1) % count]
        dx, dy = end[0] - start[0], end[1] - start[1]
        length_sq = dx * dx + dy * dy
        length = hypot(dx, dy)
        if length <= eps * scale:
            raise GeometryInputError(
                "DEGENERATE_EDGE",
                f"Ребро {index + 1} исходного контура имеет нулевую длину.",
            )
        edge_data.append((start[0], start[1], dx, dy, length_sq, length))

    def split_cells(
        cells: Sequence[Sequence[Point2]],
        a: float,
        b: float,
        c: float,
    ) -> list[list[Point2]]:
        function_tolerance = eps * scale * hypot(a, b)
        next_cells: list[list[Point2]] = []
        for cell in cells:
            negative = clip_half_plane(cell, -a, -b, -c, function_tolerance)
            positive = clip_half_plane(cell, a, b, c, function_tolerance)
            negative_valid = (
                len(negative) >= 3
                and abs(signed_area(negative)) > area_tolerance
            )
            positive_valid = (
                len(positive) >= 3
                and abs(signed_area(positive)) > area_tolerance
            )
            if negative_valid and positive_valid:
                next_cells.extend((negative, positive))
            elif negative_valid:
                next_cells.append(negative)
            elif positive_valid:
                next_cells.append(positive)
        return next_cells

    for triangle in triangles:
        arrangement_cells: list[list[Point2]] = [list(triangle)]
        for sx, sy, dx, dy, _length_sq, _length in edge_data:
            # Inward-support line.
            arrangement_cells = split_cells(
                arrangement_cells, -dy, dx, dy * sx - dx * sy
            )
            # Start and end of the finite orthogonal projection interval.
            arrangement_cells = split_cells(
                arrangement_cells, dx, dy, -(dx * sx + dy * sy)
            )
            ex, ey = sx + dx, sy + dy
            arrangement_cells = split_cells(
                arrangement_cells, dx, dy, -(dx * ex + dy * ey)
            )
            if not arrangement_cells:
                break

        for cell in arrangement_cells:
            sample = (
                sum(point[0] for point in cell) / len(cell),
                sum(point[1] for point in cell) / len(cell),
            )
            active: list[int] = []
            for index, (sx, sy, dx, dy, length_sq, edge_length) in enumerate(edge_data):
                projection = (
                    (sample[0] - sx) * dx + (sample[1] - sy) * dy
                ) / length_sq
                inward_side = winding * (
                    dx * (sample[1] - sy) - dy * (sample[0] - sx)
                )
                if (
                    point_tolerance < projection < 1.0 - point_tolerance
                    and inward_side >= -point_tolerance * edge_length
                ):
                    active.append(index)

            # A corner wedge has no interior projection onto either adjacent
            # finite segment. Its only valid supports are the two incident
            # source edges at the nearest contour vertex.
            if not active:
                nearest_vertex = min(
                    range(count),
                    key=lambda index: (
                        (sample[0] - domain[index][0]) ** 2
                        + (sample[1] - domain[index][1]) ** 2
                    ),
                )
                active = [(nearest_vertex - 1) % count, nearest_vertex]

            # The general helper uses eps both for clipping and as an
            # absolute projected-area cutoff. Dense concave roofs can contain
            # valid tiny cells near corners, so use a tighter local clipping
            # threshold here and let mesh topology validation reject degeneracy.
            region_eps = max(eps * 1.0e-3, 1.0e-14)
            regions = lower_envelope_regions(
                cell, [planes[index] for index in active], region_eps
            )
            for local_index, region in enumerate(regions):
                if (
                    len(region) >= 3
                    and abs(signed_area(region)) > area_tolerance
                ):
                    output[active[local_index]].append(region)

    return output


def _build_finite_intersection_envelope_surface(
    points: Sequence[Point3],
    pitches_degrees: Sequence[float],
    eps: float = 1e-9,
) -> RoofSurface:
    """Build the local finite-support envelope before transition completion.

    One plane is constructed through every authored 3D eave edge at its
    requested pitch. Finite inward edge supports define which planes may
    compete at each point. The active planes are partitioned by exact pairwise
    height equalities, then assembled into a conforming planar mesh.
    """
    if len(points) < 3:
        raise GeometryInputError(
            "POLY_TOO_SMALL",
            "Контур должен содержать минимум три вершины.",
        )
    normalized: tuple[Point3, ...] = tuple(
        tuple(float(value) for value in point)
        for point in points
    )  # type: ignore[assignment]
    domain: tuple[Point2, ...] = tuple(
        (point[0], point[1]) for point in normalized
    )
    planes = build_boundary_planes(normalized, pitches_degrees, eps)

    _validate_finite_inward_eave_support(normalized, planes, eps)
    cells_by_slope = _lower_envelope_finite_inward_cells(domain, planes, eps)

    scale = max(
        _bbox_scale(domain),
        max(point[2] for point in normalized) - min(point[2] for point in normalized),
        1.0,
    )
    weld_tolerance = max(1e-12, eps * scale * 2.0)
    area_tolerance = eps * scale * scale * 1.0e-3
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
            "Пересечения опорных плоскостей не создали областей крыши.",
        )

    faces = _split_face_edges_at_shared_vertices(
        registry.vertices,
        faces,
        weld_tolerance * 2.0,
        minimum_edge_length=weld_tolerance,
    )
    edge_usage = _mesh_edge_usage(faces)
    if any(uses > 2 for uses in edge_usage.values()):
        raise GeometryInputError(
            "NON_MANIFOLD_SURFACE",
            "Пересечения опорных плоскостей создали неманифолдное ребро.",
        )

    try:
        boundary_edges = validate_surface_boundary_edges(
            registry.vertices,
            faces,
            domain,
            weld_tolerance * 2.0,
        )
    except GeometryInputError as exc:
        if exc.code == "INTERNAL_OPEN_EDGE":
            raise GeometryInputError(
                "PLANE_ENVELOPE_DISCONTINUITY",
                "Конечные области влияния опорных плоскостей не образовали "
                "непрерывную поверхность: " + exc.message,
            ) from exc
        raise
    for first, second in boundary_edges:
        p, q = registry.vertices[first], registry.vertices[second]
        matches = []
        for edge_index, start in enumerate(normalized):
            end = normalized[(edge_index + 1) % len(normalized)]
            dx, dy = end[0] - start[0], end[1] - start[1]
            length_sq = dx * dx + dy * dy
            if length_sq <= weld_tolerance * weld_tolerance:
                continue

            def parameter_and_distance(point: Point3):
                rx, ry = point[0] - start[0], point[1] - start[1]
                parameter = (rx * dx + ry * dy) / length_sq
                distance = abs(dx * ry - dy * rx) / (length_sq ** 0.5)
                return parameter, distance

            tp, dp = parameter_and_distance(p)
            tq, dq = parameter_and_distance(q)
            if (
                dp <= weld_tolerance * 5.0
                and dq <= weld_tolerance * 5.0
                and -weld_tolerance <= tp <= 1.0 + weld_tolerance
                and -weld_tolerance <= tq <= 1.0 + weld_tolerance
            ):
                zp = start[2] + tp * (end[2] - start[2])
                zq = start[2] + tq * (end[2] - start[2])
                if (
                    abs(p[2] - zp) <= weld_tolerance * max(1.0, abs(zp))
                    and abs(q[2] - zq) <= weld_tolerance * max(1.0, abs(zq))
                ):
                    matches.append(edge_index)
        if len(matches) != 1:
            raise GeometryInputError(
                "SUPPORT_PLANE_EAVE_MISMATCH",
                "Огибающая не сохранила исходную 3D-линию карниза.",
            )

    used_sources = set(face_slope_indices)
    missing_sources = sorted(set(range(len(planes))) - used_sources)
    if missing_sources:
        raise GeometryInputError(
            "PLANE_ENVELOPE_UNUSED_SUPPORT",
            "Не сохранились области следующих опорных плоскостей: "
            + ", ".join(str(index + 1) for index in missing_sources),
        )

    for face_index, (face, source_index) in enumerate(
        zip(faces, face_slope_indices)
    ):
        plane = planes[source_index]
        for vertex_index in face:
            x, y, z = registry.vertices[vertex_index]
            if abs(z - plane.height(x, y)) > weld_tolerance * max(1.0, abs(z)):
                raise GeometryInputError(
                    "PLANE_ENVELOPE_OFF_SUPPORT",
                    f"Вершина грани {face_index + 1} вышла из плоскости ската {source_index + 1}.",
                )

    surface_area = sum(
        abs(signed_area([
            (registry.vertices[index][0], registry.vertices[index][1])
            for index in face
        ]))
        for face in faces
    )
    source_area = abs(signed_area(domain))
    if abs(surface_area - source_area) > max(
        area_tolerance * 100.0, source_area * 1e-7
    ):
        raise GeometryInputError(
            "DOMAIN_COVERAGE_MISMATCH",
            "Ячейки опорных плоскостей не покрывают контур без дыр и перекрытий.",
        )

    return RoofSurface(
        vertices=tuple(registry.vertices),
        faces=tuple(faces),
        face_slope_indices=tuple(face_slope_indices),
        planes=tuple(planes),
        source_area_xy=source_area,
        surface_area_xy=surface_area,
        boundary_xy=domain,
        approximation_error=0.0,
        refinement_depth=0,
    )





def _has_reflex_vertex(domain: Sequence[Point2], eps: float) -> bool:
    area = signed_area(domain)
    if abs(area) <= eps:
        return False
    winding = 1.0 if area > 0.0 else -1.0
    scale = max(_bbox_scale(domain), 1.0)
    turn_tolerance = eps * scale * scale
    for index, current in enumerate(domain):
        previous = domain[index - 1]
        following = domain[(index + 1) % len(domain)]
        turn = (
            (current[0] - previous[0]) * (following[1] - current[1])
            - (current[1] - previous[1]) * (following[0] - current[0])
        )
        if turn * winding < -turn_tolerance:
            return True
    return False


def _validate_transition_faceted_surface(
    surface: RoofSurface,
    source_count: int,
    eps: float,
) -> int:
    """Validate exact planar transition facets and their support-plane seams."""
    from .exact_spatial import validate_planar_face

    if len(surface.faces) != len(surface.face_slope_indices):
        raise GeometryInputError(
            "TRANSITION_FACE_SOURCE_COUNT",
            "Для каждой грани переходной поверхности должен быть задан источник.",
        )

    transition_indices = [
        index for index, source in enumerate(surface.face_slope_indices)
        if source == -1
    ]
    if not transition_indices:
        raise GeometryInputError(
            "TRANSITION_FACETS_MISSING",
            "Событийная топология не создала ни одной отдельной переходной грани.",
        )

    used_sources = {
        source for source in surface.face_slope_indices
        if source >= 0
    }
    missing_sources = sorted(set(range(source_count)) - used_sources)
    if missing_sources:
        raise GeometryInputError(
            "TRANSITION_SUPPORT_PLANE_UNUSED",
            "Переходная топология не сохранила отдельные области скатов: "
            + ", ".join(str(index + 1) for index in missing_sources),
        )

    scale = max(
        _bbox_scale(surface.boundary_xy),
        max((abs(value) for point in surface.vertices for value in point), default=1.0),
        1.0,
    )
    tolerance = max(eps * scale * 20.0, 1e-10)
    edge_uses: dict[tuple[int, int], list[tuple[int, int]]] = {}

    for face_index, (face, source) in enumerate(
        zip(surface.faces, surface.face_slope_indices)
    ):
        if len(face) < 3:
            raise GeometryInputError(
                "TRANSITION_DEGENERATE_FACE",
                f"Грань {face_index + 1} не содержит трёх вершин.",
            )
        if source < -1 or source >= source_count:
            raise GeometryInputError(
                "TRANSITION_FACE_SOURCE_INDEX",
                f"Грань {face_index + 1} ссылается на неверный источник {source}.",
            )
        if source == -1:
            if len(face) != 3:
                raise GeometryInputError(
                    "TRANSITION_FACE_NOT_TRIANGULATED",
                    "Переходная область должна быть разбита на отдельные треугольные фасеты.",
                )
            validate_planar_face(
                surface.vertices, face, eps=max(eps * 10.0, 1e-10)
            )
        else:
            plane = surface.planes[source]
            for vertex_index in face:
                x, y, z = surface.vertices[vertex_index]
                residual = abs(z - plane.height(x, y))
                if residual > tolerance * max(1.0, abs(z)):
                    raise GeometryInputError(
                        "TRANSITION_SUPPORT_FACE_OFF_PLANE",
                        f"Грань {face_index + 1} не лежит на своей опорной плоскости {source + 1}.",
                    )

        for local_index, first in enumerate(face):
            second = face[(local_index + 1) % len(face)]
            key = (min(first, second), max(first, second))
            edge_uses.setdefault(key, []).append((face_index, source))

    # Every transition-facet edge is an internal seam: it must be shared by
    # exactly one other planar face. If that face is an authored slope, the
    # common edge must lie on that slope's exact support plane.
    for face_index in transition_indices:
        face = surface.faces[face_index]
        for local_index, first in enumerate(face):
            second = face[(local_index + 1) % len(face)]
            key = (min(first, second), max(first, second))
            uses = edge_uses.get(key, ())
            if len(uses) != 2:
                raise GeometryInputError(
                    "TRANSITION_FACET_OPEN_EDGE",
                    f"Ребро фасеты {face_index + 1} не разделяется ровно двумя гранями.",
                )
            other = next(
                (entry for entry in uses if entry[0] != face_index),
                None,
            )
            if other is None:
                raise GeometryInputError(
                    "TRANSITION_FACET_SELF_EDGE",
                    "Переходная фасета использует одно ребро дважды.",
                )
            other_source = other[1]
            if other_source >= 0:
                plane = surface.planes[other_source]
                for vertex_index in (first, second):
                    x, y, z = surface.vertices[vertex_index]
                    if abs(z - plane.height(x, y)) > tolerance * max(1.0, abs(z)):
                        raise GeometryInputError(
                            "TRANSITION_SEAM_OFF_SUPPORT",
                            f"Стык переходной фасеты с плоскостью ската {other_source + 1} неточен.",
                        )

    return len(transition_indices)


def build_intersection_envelope_surface(
    points: Sequence[Point3],
    pitches_degrees: Sequence[float],
    eps: float = 1e-9,
    *,
    complete_transition_facets: bool = True,
) -> RoofSurface:
    """Build an exact roof, completing finite-support gaps with planar facets.

    Convex/simple cases first use the finite inward edge-support envelope.
    Mixed-height concave contours go directly to the exact seam-event
    arrangement: adjacent source planes define each seam, a third support
    plane defines its exact event node, and the remaining transition cells
    are triangulated into individually planar facets.

    If the finite envelope itself exposes an internal crack, the same exact
    event-facet completion is used when enabled. No height averaging,
    interpolation, smoothing, or relaxed planarity tolerance is used.
    Set complete_transition_facets=False to inspect the finite envelope
    alone and retain its fail-closed diagnostic.
    """
    if len(points) < 3:
        raise GeometryInputError(
            "POLY_TOO_SMALL",
            "Контур должен содержать минимум три вершины.",
        )
    domain = tuple((float(point[0]), float(point[1])) for point in points)
    z_values = tuple(float(point[2]) for point in points)
    scale = max(
        _bbox_scale(domain),
        max(z_values) - min(z_values),
        1.0,
    )
    mixed_height = max(z_values) - min(z_values) > eps * scale * 10.0
    needs_event_topology = _has_reflex_vertex(domain, eps) and mixed_height

    def build_transition_completion() -> RoofSurface:
        from .exact_spatial import build_exact_planar_ring_surface

        completed = build_exact_planar_ring_surface(
            points, pitches_degrees, eps
        )
        _validate_transition_faceted_surface(completed, len(points), eps)
        return completed

    if complete_transition_facets and needs_event_topology:
        return build_transition_completion()

    try:
        return _build_finite_intersection_envelope_surface(
            points, pitches_degrees, eps
        )
    except GeometryInputError as finite_error:
        if (
            not complete_transition_facets
            or finite_error.code != "PLANE_ENVELOPE_DISCONTINUITY"
        ):
            raise
        try:
            return build_transition_completion()
        except GeometryInputError as transition_error:
            raise GeometryInputError(
                "PLANE_ENVELOPE_TRANSITION_UNRESOLVED",
                "Конечные области влияния не образовали непрерывную поверхность "
                f"({finite_error.code}: {finite_error.message}). "
                "Точная событийная топология переходных фасет также не прошла "
                f"проверку ({transition_error.code}: {transition_error.message}).",
            ) from transition_error



def build_global_plane_intersection_surface(
    points: Sequence[Point3],
    pitches_degrees: Sequence[float],
    eps: float = 1e-9,
) -> RoofSurface:
    """Build the global lower envelope of all authored edge support planes.

    This is the direct "intersect the planes" model: every support plane
    competes over the full footprint, and their pairwise equal-height lines
    define the exact ridge/valley arrangement. The authored 3D eave is
    accepted only when no other global plane lies below it.
    """
    if len(points) < 3:
        raise GeometryInputError(
            "POLY_TOO_SMALL",
            "Контур должен содержать минимум три вершины.",
        )
    normalized: tuple[Point3, ...] = tuple(
        tuple(float(value) for value in point)
        for point in points
    )  # type: ignore[assignment]
    domain: tuple[Point2, ...] = tuple(
        (point[0], point[1]) for point in normalized
    )
    planes = build_boundary_planes(normalized, pitches_degrees, eps)
    scale = max(_bbox_scale(domain), 1.0)
    z_tolerance = eps * scale

    # A global minimum envelope must preserve every boundary segment. Since
    # each plane difference is affine along an edge, checking both endpoints
    # is sufficient for the complete segment.
    for edge_index, start in enumerate(normalized):
        end = normalized[(edge_index + 1) % len(normalized)]
        own = planes[edge_index]
        for other_index, other in enumerate(planes):
            if other_index == edge_index:
                continue
            for endpoint in (start, end):
                if (
                    other.height(endpoint[0], endpoint[1])
                    - own.height(endpoint[0], endpoint[1])
                    < -z_tolerance
                ):
                    raise GeometryInputError(
                        "GLOBAL_ENVELOPE_EAVE_UNDERCUT",
                        f"Глобальная плоскость ската {other_index + 1} "
                        f"опускается ниже карниза ската {edge_index + 1}. "
                        "Эти плоскости не сохраняют исходную 3D-границу.",
                    )

    cells_by_slope = lower_envelope_cells(domain, planes, eps)
    weld_tolerance = max(1e-12, eps * scale * 2.0)
    area_tolerance = eps * scale * scale
    registry = _VertexRegistry(weld_tolerance)
    faces: list[Face] = []
    face_sources: list[int] = []
    face_keys: set[tuple[int, ...]] = set()

    for slope_index, cells in enumerate(cells_by_slope):
        plane = planes[slope_index]
        for cell in cells:
            if len(cell) < 3 or abs(signed_area(cell)) <= area_tolerance:
                continue
            indices = [
                registry.add((x, y, plane.height(x, y)))
                for x, y in cell
            ]
            compact: list[int] = []
            for vertex_index in indices:
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
            face_sources.append(slope_index)

    if not faces:
        raise GeometryInputError(
            "EMPTY_GLOBAL_PLANE_ENVELOPE",
            "Глобальная огибающая не создала граней крыши.",
        )

    faces = _split_face_edges_at_shared_vertices(
        registry.vertices, faces, weld_tolerance * 2.0
    )
    if any(count > 2 for count in _mesh_edge_usage(faces).values()):
        raise GeometryInputError(
            "GLOBAL_ENVELOPE_NON_MANIFOLD",
            "Глобальная огибающая создала неманифолдное ребро.",
        )

    boundary_edges = validate_surface_boundary_edges(
        registry.vertices, faces, domain, weld_tolerance * 2.0
    )
    for first, second in boundary_edges:
        p, q = registry.vertices[first], registry.vertices[second]
        matches = []
        for edge_index, start in enumerate(normalized):
            end = normalized[(edge_index + 1) % len(normalized)]
            dx, dy = end[0] - start[0], end[1] - start[1]
            length_sq = dx * dx + dy * dy
            if length_sq <= weld_tolerance * weld_tolerance:
                continue

            def parameter_and_distance(point: Point3):
                rx, ry = point[0] - start[0], point[1] - start[1]
                parameter = (rx * dx + ry * dy) / length_sq
                distance = abs(dx * ry - dy * rx) / (length_sq ** 0.5)
                return parameter, distance

            tp, dp = parameter_and_distance(p)
            tq, dq = parameter_and_distance(q)
            if (
                dp <= weld_tolerance * 5.0
                and dq <= weld_tolerance * 5.0
                and -weld_tolerance <= tp <= 1.0 + weld_tolerance
                and -weld_tolerance <= tq <= 1.0 + weld_tolerance
            ):
                zp = start[2] + tp * (end[2] - start[2])
                zq = start[2] + tq * (end[2] - start[2])
                if (
                    abs(p[2] - zp) <= weld_tolerance * max(1.0, abs(zp))
                    and abs(q[2] - zq) <= weld_tolerance * max(1.0, abs(zq))
                ):
                    matches.append(edge_index)
        if len(matches) != 1:
            raise GeometryInputError(
                "GLOBAL_ENVELOPE_EAVE_MISMATCH",
                "Глобальная огибающая изменила исходную 3D-линию карниза.",
            )

    used_sources = set(face_sources)
    missing = sorted(set(range(len(planes))) - used_sources)
    if missing:
        raise GeometryInputError(
            "GLOBAL_ENVELOPE_UNUSED_PLANE",
            "Следующие плоскости не имеют области ненулевой площади: "
            + ", ".join(str(index + 1) for index in missing),
        )

    for face_index, (face, source_index) in enumerate(zip(faces, face_sources)):
        plane = planes[source_index]
        for vertex_index in face:
            x, y, z = registry.vertices[vertex_index]
            if abs(z - plane.height(x, y)) > weld_tolerance * max(1.0, abs(z)):
                raise GeometryInputError(
                    "GLOBAL_ENVELOPE_OFF_SUPPORT",
                    f"Вершина грани {face_index + 1} не лежит на плоскости ската {source_index + 1}.",
                )

    surface_area = sum(
        abs(signed_area([
            (registry.vertices[index][0], registry.vertices[index][1])
            for index in face
        ]))
        for face in faces
    )
    source_area = abs(signed_area(domain))
    if abs(surface_area - source_area) > max(
        area_tolerance * 100.0, source_area * 1e-7
    ):
        raise GeometryInputError(
            "GLOBAL_ENVELOPE_COVERAGE",
            "Глобальные ячейки не покрывают исходный контур без дыр и перекрытий.",
        )

    return RoofSurface(
        vertices=tuple(registry.vertices),
        faces=tuple(faces),
        face_slope_indices=tuple(face_sources),
        planes=tuple(planes),
        source_area_xy=source_area,
        surface_area_xy=surface_area,
        boundary_xy=domain,
        approximation_error=0.0,
        refinement_depth=0,
    )


__all__ = [
    "build_intersection_envelope_surface",
    "build_global_plane_intersection_surface",
]
