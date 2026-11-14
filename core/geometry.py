"""Pure-Python geometry primitives for RoofForge.

No Blender imports are allowed in this module. All input coordinates are
explicit tuples so the geometry kernel can be tested outside Blender.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import atan, degrees, hypot, isfinite, radians, sqrt, tan
from typing import Sequence

from .native_bridge import validate_simple_polygon_native

Point2 = tuple[float, float]
Point3 = tuple[float, float, float]


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    severity: str = "ERROR"


class GeometryInputError(ValueError):
    """An invalid or geometrically inconsistent roof input."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PlaneZ:
    """Plane represented as z = ax + by + c."""
    a: float
    b: float
    c: float

    def height(self, x: float, y: float) -> float:
        return self.a * x + self.b * y + self.c

    @property
    def pitch_degrees(self) -> float:
        """Inclination of the plane above horizontal, in degrees."""
        return degrees(atan(hypot(self.a, self.b)))


def signed_area(poly: Sequence[Point2]) -> float:
    if len(poly) < 3:
        return 0.0
    return 0.5 * sum(
        poly[i][0] * poly[(i + 1) % len(poly)][1]
        - poly[(i + 1) % len(poly)][0] * poly[i][1]
        for i in range(len(poly))
    )


def _cross(a: Point2, b: Point2, c: Point2) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _bbox_scale(poly: Sequence[Point2]) -> float:
    if not poly:
        return 1.0
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return max(1.0, hypot(max(xs) - min(xs), max(ys) - min(ys)))


def _on_segment(p: Point2, a: Point2, b: Point2, cross_eps: float,
                linear_eps: float) -> bool:
    return (
        abs(_cross(a, b, p)) <= cross_eps
        and min(a[0], b[0]) - linear_eps <= p[0] <= max(a[0], b[0]) + linear_eps
        and min(a[1], b[1]) - linear_eps <= p[1] <= max(a[1], b[1]) + linear_eps
    )


def _segments_intersect(a: Point2, b: Point2, c: Point2, d: Point2,
                        cross_eps: float, linear_eps: float) -> bool:
    o1, o2 = _cross(a, b, c), _cross(a, b, d)
    o3, o4 = _cross(c, d, a), _cross(c, d, b)
    if ((o1 > cross_eps and o2 < -cross_eps) or (o1 < -cross_eps and o2 > cross_eps)) and (
        (o3 > cross_eps and o4 < -cross_eps) or (o3 < -cross_eps and o4 > cross_eps)
    ):
        return True
    return (
        _on_segment(c, a, b, cross_eps, linear_eps)
        or _on_segment(d, a, b, cross_eps, linear_eps)
        or _on_segment(a, c, d, cross_eps, linear_eps)
        or _on_segment(b, c, d, cross_eps, linear_eps)
    )


def _validate_simple_polygon_python(poly: Sequence[Point2], eps: float = 1e-9) -> list[Diagnostic]:
    """Validate a simple, non-degenerate XY polygon.

    'eps' is a relative tolerance scaled by the polygon bounding-box size.
    """
    issues: list[Diagnostic] = []
    if len(poly) < 3:
        return [Diagnostic("POLY_TOO_SMALL", "Контур должен содержать минимум 3 вершины.")]
    if any(not (isfinite(x) and isfinite(y)) for x, y in poly):
        return [Diagnostic("NON_FINITE", "Контур содержит NaN или бесконечные координаты.")]

    scale = _bbox_scale(poly)
    linear_eps = eps * scale
    area_eps = eps * scale * scale
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        if hypot(q[0] - p[0], q[1] - p[1]) <= linear_eps:
            issues.append(Diagnostic("ZERO_EDGE", f"Ребро {i} имеет нулевую или слишком малую длину."))
    if abs(signed_area(poly)) <= area_eps:
        issues.append(Diagnostic("ZERO_AREA", "Площадь контура практически равна нулю."))

    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        for j in range(i + 1, n):
            # Adjacent edges share a legal endpoint.
            if j == i or j == (i + 1) % n or (j + 1) % n == i:
                continue
            c, d = poly[j], poly[(j + 1) % n]
            if _segments_intersect(a, b, c, d, area_eps, linear_eps):
                issues.append(Diagnostic("SELF_INTERSECTION", f"Рёбра {i} и {j} пересекаются."))
    return issues


_NATIVE_VALIDATION_MIN_VERTICES = 32


def validate_simple_polygon(poly: Sequence[Point2], eps: float = 1e-9) -> list[Diagnostic]:
    """Validate a contour, preferring the compatible Rust core for dense loops."""
    if len(poly) >= _NATIVE_VALIDATION_MIN_VERTICES:
        native_issues = validate_simple_polygon_native(poly, eps)
        if native_issues is not None:
            return [
                Diagnostic(code, message, severity)
                for code, message, severity in native_issues
            ]
    return _validate_simple_polygon_python(poly, eps)


def clip_half_plane(poly: Sequence[Point2], a: float, b: float, c: float,
                    eps: float = 1e-9) -> list[Point2]:
    """Clip a convex polygon by 'a*x + b*y + c <= 0'.

    Sutherland-Hodgman is appropriate here because callers pass convex cells
    (the source polygon may be concave only after it has been triangulated).
    """
    if not poly:
        return []
    result: list[Point2] = []
    for i, current in enumerate(poly):
        previous = poly[i - 1]
        fp = a * previous[0] + b * previous[1] + c
        fc = a * current[0] + b * current[1] + c
        pin, cin = fp <= eps, fc <= eps
        if pin != cin:
            denom = fp - fc
            if abs(denom) > eps:
                t = fp / denom
                result.append((
                    previous[0] + t * (current[0] - previous[0]),
                    previous[1] + t * (current[1] - previous[1]),
                ))
        if cin:
            result.append(current)

    # Remove consecutive duplicates introduced by vertices lying on the clip line.
    point_eps = 1e-10 * _bbox_scale(poly)
    cleaned: list[Point2] = []
    for point in result:
        if not cleaned or hypot(point[0] - cleaned[-1][0], point[1] - cleaned[-1][1]) > point_eps:
            cleaned.append(point)
    if len(cleaned) > 1 and hypot(cleaned[0][0] - cleaned[-1][0], cleaned[0][1] - cleaned[-1][1]) <= point_eps:
        cleaned.pop()
    return cleaned


def _point_in_triangle(p: Point2, a: Point2, b: Point2, c: Point2, orientation: float,
                       eps: float) -> bool:
    c1 = _cross(a, b, p) * orientation
    c2 = _cross(b, c, p) * orientation
    c3 = _cross(c, a, p) * orientation
    return c1 >= -eps and c2 >= -eps and c3 >= -eps


def triangulate_simple_polygon(poly: Sequence[Point2], eps: float = 1e-9) -> list[tuple[Point2, Point2, Point2]]:
    """Triangulate a simple polygon using deterministic ear clipping.

    This dependency-free implementation is intended for simple, non-self-
    intersecting contours. It handles either winding and concave L/U contours.
    Collinear boundary vertices are rejected explicitly rather than producing
    ambiguous zero-area triangles.
    """
    issues = validate_simple_polygon(poly, eps)
    if issues:
        raise GeometryInputError(issues[0].code, issues[0].message)

    scale = _bbox_scale(poly)
    area_eps = eps * scale * scale
    area = signed_area(poly)
    orientation = 1.0 if area > 0.0 else -1.0
    count = len(poly)

    for i in range(count):
        prev_p, cur_p, next_p = poly[i - 1], poly[i], poly[(i + 1) % count]
        if abs(_cross(prev_p, cur_p, next_p)) <= area_eps:
            raise GeometryInputError(
                "COLLINEAR_VERTEX",
                f"Вершина {i} лежит на прямой между соседями. Удали лишнюю коллинеарную вершину перед триангуляцией."
            )

    remaining = list(range(count))
    triangles: list[tuple[Point2, Point2, Point2]] = []
    # A simple polygon with n vertices has n-2 ears. The guard protects against
    # numerical stalls and makes failure deterministic.
    while len(remaining) > 3:
        ear_found = False
        for pos, current_index in enumerate(remaining):
            prev_index = remaining[pos - 1]
            next_index = remaining[(pos + 1) % len(remaining)]
            a, b, c = poly[prev_index], poly[current_index], poly[next_index]
            if _cross(a, b, c) * orientation <= area_eps:
                continue

            contains_vertex = False
            for candidate_index in remaining:
                if candidate_index in (prev_index, current_index, next_index):
                    continue
                if _point_in_triangle(poly[candidate_index], a, b, c, orientation, area_eps):
                    contains_vertex = True
                    break
            if contains_vertex:
                continue

            triangles.append((a, b, c) if orientation > 0 else (c, b, a))
            del remaining[pos]
            ear_found = True
            break

        if not ear_found:
            raise GeometryInputError(
                "TRIANGULATION_STALLED",
                "Не удалось устойчиво триангулировать контур. Проверь острые углы и почти совпадающие вершины."
            )

    last = tuple(poly[i] for i in remaining)
    if abs(_cross(last[0], last[1], last[2])) <= area_eps:
        raise GeometryInputError("DEGENERATE_TRIANGLE", "Триангуляция создала вырожденный треугольник.")
    triangles.append(last if orientation > 0 else (last[2], last[1], last[0]))
    return triangles


def _planes_coincident(first: PlaneZ, second: PlaneZ, eps: float) -> bool:
    scale = max(1.0, abs(first.a), abs(first.b), abs(first.c),
                abs(second.a), abs(second.b), abs(second.c))
    return (abs(first.a - second.a) <= eps * scale
            and abs(first.b - second.b) <= eps * scale
            and abs(first.c - second.c) <= eps * scale)


def lower_envelope_regions(domain: Sequence[Point2], planes: Sequence[PlaneZ],
                           eps: float = 1e-9) -> list[list[Point2]]:
    """Return one clipped polygon per plane for a convex domain.

    Each output region contains points where its plane is no higher than any
    other plane. Use 'lower_envelope_cells' for concave domains.
    """
    if not planes:
        return []
    regions: list[list[Point2]] = []
    for i, plane in enumerate(planes):
        # Coincident planes would otherwise duplicate the entire same region.
        # The earliest stable input index owns that region deterministically.
        if any(_planes_coincident(plane, planes[j], eps) for j in range(i)):
            regions.append([])
            continue
        cell = list(domain)
        for j, other in enumerate(planes):
            if i == j or _planes_coincident(plane, other, eps):
                continue
            cell = clip_half_plane(
                cell, plane.a - other.a, plane.b - other.b, plane.c - other.c, eps
            )
            if len(cell) < 3 or abs(signed_area(cell)) <= eps:
                cell = []
                break
        regions.append(cell)
    return regions


def lower_envelope_cells(domain: Sequence[Point2], planes: Sequence[PlaneZ],
                         eps: float = 1e-9) -> list[list[list[Point2]]]:
    """Partition a simple (possibly concave) domain by the lower envelope.

    Return 'result[plane_index]' as zero or more convex polygon cells. A
    concave input is ear-clipped first, then every triangle is clipped against
    all pairwise plane inequalities. Adjacent cells belonging to the same
    slope are intentionally not merged here; the topology assembler owns that
    operation so shared vertices can be welded with 3D plane constraints.
    """
    if not planes:
        return []
    triangles = triangulate_simple_polygon(domain, eps)
    output: list[list[list[Point2]]] = [[] for _ in planes]
    scale = _bbox_scale(domain)
    area_eps = eps * scale * scale

    for triangle in triangles:
        for i, plane in enumerate(planes):
            if any(_planes_coincident(plane, planes[j], eps) for j in range(i)):
                continue
            cell: list[Point2] = list(triangle)
            for j, other in enumerate(planes):
                if i == j or _planes_coincident(plane, other, eps):
                    continue
                cell = clip_half_plane(
                    cell, plane.a - other.a, plane.b - other.b, plane.c - other.c,
                    eps * max(1.0, abs(plane.a), abs(plane.b), abs(plane.c),
                              abs(other.a), abs(other.b), abs(other.c))
                )
                if len(cell) < 3:
                    cell = []
                    break
            if len(cell) >= 3 and abs(signed_area(cell)) > area_eps:
                output[i].append(cell)
    return output


def plane_from_boundary_edge(start: Point3, end: Point3, inward_xy: Point2,
                             pitch_degrees: float, eps: float = 1e-9) -> PlaneZ:
    """Construct a z=f(x,y) plane through one 3D boundary edge.

    'inward_xy' must be a unit vector in the horizontal plane pointing into
    the polygon. Pitch is the total plane inclination above horizontal. If the
    eave edge already rises along its length more steeply than the requested
    pitch, no real plane satisfies both constraints and an error is raised.
    """
    values = (*start, *end, *inward_xy, pitch_degrees)
    if not all(isfinite(value) for value in values):
        raise GeometryInputError("NON_FINITE", "Координаты ребра или уклон содержат нечисловые значения.")
    if not (0.0 <= pitch_degrees < 89.9):
        raise GeometryInputError("PITCH_RANGE", "Уклон должен находиться в диапазоне 0–89.9 градусов.")

    dx, dy, dz = end[0] - start[0], end[1] - start[1], end[2] - start[2]
    length_xy = hypot(dx, dy)
    scale = max(1.0, abs(start[0]), abs(start[1]), abs(start[2]),
                abs(end[0]), abs(end[1]), abs(end[2]), length_xy)
    linear_eps = eps * scale
    if length_xy <= linear_eps:
        raise GeometryInputError(
            "VERTICAL_PROJECTED_EDGE",
            "Ребро практически вертикально в XY: поверхность вида z=f(x,y) не может содержать такое ребро."
        )

    nx, ny = inward_xy
    n_len = hypot(nx, ny)
    if abs(n_len - 1.0) > max(1e-7, eps * 10.0):
        raise GeometryInputError("INVALID_INWARD_VECTOR", "Внутренний вектор должен быть нормирован в XY.")

    tx, ty = dx / length_xy, dy / length_xy
    along_gradient = dz / length_xy
    total_gradient = tan(radians(pitch_degrees))
    cross_gradient_sq = total_gradient * total_gradient - along_gradient * along_gradient
    gradient_tol = eps * max(1.0, total_gradient * total_gradient, along_gradient * along_gradient)
    if cross_gradient_sq < -gradient_tol:
        minimum_pitch = degrees(atan(abs(along_gradient)))
        raise GeometryInputError(
            "PITCH_BELOW_EAVE_GRADE",
            f"Уклон {pitch_degrees:.3f}° меньше минимального {minimum_pitch:.3f}°: перепад высоты вдоль карниза уже круче заданной плоскости."
        )
    cross_gradient = sqrt(max(0.0, cross_gradient_sq))

    # The edge-parallel gradient preserves both endpoint heights. The inward
    # component supplies the remaining plane inclination.
    a = along_gradient * tx + cross_gradient * nx
    b = along_gradient * ty + cross_gradient * ny
    c = start[2] - a * start[0] - b * start[1]
    plane = PlaneZ(a, b, c)

    endpoint_error = max(abs(plane.height(start[0], start[1]) - start[2]),
                         abs(plane.height(end[0], end[1]) - end[2]))
    if endpoint_error > linear_eps * max(1.0, abs(start[2]), abs(end[2])):
        raise GeometryInputError("PLANE_ENDPOINT_ERROR", "Построенная плоскость не проходит через обе вершины карниза.")
    return plane


def build_boundary_planes(points: Sequence[Point3], pitches_degrees: Sequence[float],
                          eps: float = 1e-9) -> list[PlaneZ]:
    """Build one pitched roof plane for every ordered 3D boundary edge.

    The polygon interior is determined from XY winding. For a CCW contour the
    interior is to the left of each directed edge; for CW it is to the right.
    'pitches_degrees[i]' belongs to edge 'points[i] -> points[i+1]'.
    """
    if len(points) < 3:
        raise GeometryInputError("POLY_TOO_SMALL", "Контур должен содержать минимум 3 вершины.")
    if len(pitches_degrees) != len(points):
        raise GeometryInputError("PITCH_COUNT", "Количество уклонов должно совпадать с количеством рёбер контура.")
    if any(len(point) != 3 or not all(isfinite(v) for v in point) for point in points):
        raise GeometryInputError("NON_FINITE", "3D-контур содержит неверные или нечисловые координаты.")

    polygon_xy: list[Point2] = [(p[0], p[1]) for p in points]
    issues = validate_simple_polygon(polygon_xy, eps)
    if issues:
        raise GeometryInputError(issues[0].code, issues[0].message)

    winding = 1.0 if signed_area(polygon_xy) > 0 else -1.0
    planes: list[PlaneZ] = []
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        dx, dy = end[0] - start[0], end[1] - start[1]
        edge_len = hypot(dx, dy)
        if edge_len <= eps * _bbox_scale(polygon_xy):
            raise GeometryInputError("VERTICAL_PROJECTED_EDGE", f"Ребро {index} не имеет устойчивой проекции в XY.")
        left_normal = (-dy / edge_len, dx / edge_len)
        inward = (left_normal[0] * winding, left_normal[1] * winding)
        planes.append(plane_from_boundary_edge(start, end, inward, pitches_degrees[index], eps))
    return planes


def boundary_envelope_conflicts(points: Sequence[Point3], planes: Sequence[PlaneZ],
                                eps: float = 1e-8) -> list[Diagnostic]:
    """Report where another plane undercuts a boundary edge's own eave plane.

    A lower-envelope roof that is lower than the authored eave along its own
    boundary cannot preserve that boundary as the visible roof perimeter.
    Because the difference of two planes along an edge is linear, checking both
    endpoints is sufficient to detect an undercut over the whole segment.
    """
    if len(points) != len(planes):
        return [Diagnostic("PLANE_COUNT", "Для каждой грани контура должна быть построена своя плоскость.")]
    diagnostics: list[Diagnostic] = []
    scale = max(1.0, _bbox_scale([(p[0], p[1]) for p in points]))
    tol = eps * scale
    for edge_index, start in enumerate(points):
        end = points[(edge_index + 1) % len(points)]
        own = planes[edge_index]
        for other_index, other in enumerate(planes):
            if other_index == edge_index:
                continue
            for endpoint_index, point in enumerate((start, end)):
                difference = other.height(point[0], point[1]) - own.height(point[0], point[1])
                if difference < -tol:
                    diagnostics.append(Diagnostic(
                        "BOUNDARY_UNDERCUT",
                        f"Плоскость ската {other_index + 1} опускается ниже карниза ската {edge_index + 1} у вершины {endpoint_index + 1}.",
                        "ERROR"
                    ))
                    break
    return diagnostics
