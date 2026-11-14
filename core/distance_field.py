"""Continuous finite-segment roof field for mixed-height concave fallback.

For every boundary edge the field evaluates its authored plane while the
perpendicular foot lies on that finite segment; beyond either endpoint it
evaluates a radial corner transition. The lower envelope of these continuous
segment features avoids the jumps caused by infinite supporting-line
active-set arrangements.

Adaptive triangulation approximates the corner-transition regions while
preserving exact planar edge strips wherever the closest point lies inside an
edge segment. The production mesh builder invokes this path only when its exact
planar arrangement fails continuity validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot, radians, sqrt, tan
from typing import Sequence

from .geometry import GeometryInputError, signed_area, triangulate_simple_polygon
from .mesh import (
    RoofSurface,
    _VertexRegistry,
    _mesh_edge_usage,
    validate_surface_boundary_edges,
)
from .planes import build_boundary_planes

Point2 = tuple[float, float]
Point3 = tuple[float, float, float]
Triangle2 = tuple[Point2, Point2, Point2]


@dataclass(frozen=True)
class _SegmentFeature:
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    length: float
    dx: float
    dy: float
    dz: float
    normal_rise: float

    @classmethod
    def create(cls, start, end, pitch_degrees: float) -> "_SegmentFeature":
        dx, dy, dz = end[0] - start[0], end[1] - start[1], end[2] - start[2]
        length = hypot(dx, dy)
        if length <= 1e-12:
            raise GeometryInputError("ZERO_EDGE", "Граница содержит ребро с нулевой длиной в XY.")
        tangent_grade = dz / length
        total_grade = tan(radians(pitch_degrees))
        normal_sq = total_grade * total_grade - tangent_grade * tangent_grade
        tolerance = 1e-9 * max(1.0, total_grade * total_grade, tangent_grade * tangent_grade)
        if normal_sq < -tolerance:
            raise GeometryInputError(
                "PITCH_BELOW_EAVE_GRADE",
                "Уклон ската меньше уже существующего перепада высоты вдоль карниза."
            )
        return cls(start, end, length, dx, dy, dz, sqrt(max(0.0, normal_sq)))

    def evaluate(self, x: float, y: float) -> tuple[float, bool]:
        px, py = x - self.start[0], y - self.start[1]
        raw_t = (px * self.dx + py * self.dy) / (self.length * self.length)
        t = min(1.0, max(0.0, raw_t))
        qx = self.start[0] + t * self.dx
        qy = self.start[1] + t * self.dy
        qz = self.start[2] + t * self.dz
        distance = hypot(x - qx, y - qy)
        return qz + self.normal_rise * distance, raw_t < 0.0 or raw_t > 1.0


@dataclass(frozen=True)
class RoofFieldSample:
    height: float
    slope_index: int
    endpoint_transition: bool


def _midpoint(a, b):
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)


def _centroid(triangle):
    return (
        (triangle[0][0] + triangle[1][0] + triangle[2][0]) / 3.0,
        (triangle[0][1] + triangle[1][1] + triangle[2][1]) / 3.0,
    )


def _split_triangle(triangle):
    a, b, c = triangle
    ab, bc, ca = _midpoint(a, b), _midpoint(b, c), _midpoint(c, a)
    return (
        (a, ab, ca),
        (ab, b, bc),
        (ca, bc, c),
        (ab, bc, ca),
    )


def _domain_scale(points) -> float:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    zs = [point[2] for point in points]
    return max(1.0, hypot(max(xs) - min(xs), max(ys) - min(ys)), max(zs) - min(zs))


def _check_boundary_heights(points, evaluator, tolerance, samples_per_edge=16):
    for edge_index, start in enumerate(points):
        end = points[(edge_index + 1) % len(points)]
        for sample_index in range(samples_per_edge + 1):
            t = sample_index / samples_per_edge
            x = start[0] + (end[0] - start[0]) * t
            y = start[1] + (end[1] - start[1]) * t
            expected_z = start[2] + (end[2] - start[2]) * t
            actual = evaluator(x, y).height
            if actual < expected_z - tolerance:
                raise GeometryInputError(
                    "BOUNDARY_UNDERCUT",
                    f"Граница ската {edge_index + 1} занижается другой частью контура "
                    f"около точки ({x:.6g}, {y:.6g})."
                )


def _edge_key(a, b):
    """Return a stable undirected key for a shared triangle edge."""
    return (a, b) if a <= b else (b, a)


def _split_triangle_on_marked_edges(triangle, marked_midpoints):
    """Split one triangle along every globally marked edge midpoint.

    A neighbour that did not request refinement still receives the same
    midpoint on its shared edge. This keeps the adaptive mesh conforming
    without forcing a uniform 1-to-4 split across the whole roof.
    """
    a, b, c = triangle
    mab = marked_midpoints.get(_edge_key(a, b))
    mbc = marked_midpoints.get(_edge_key(b, c))
    mca = marked_midpoints.get(_edge_key(c, a))
    split_count = sum(point is not None for point in (mab, mbc, mca))

    if split_count == 0:
        return [triangle]
    if split_count == 3:
        return [
            (a, mab, mca),
            (mab, b, mbc),
            (mca, mbc, c),
            (mab, mbc, mca),
        ]
    if split_count == 1:
        if mab is not None:
            return [(a, mab, c), (mab, b, c)]
        if mbc is not None:
            return [(b, mbc, a), (mbc, c, a)]
        return [(c, mca, b), (mca, a, b)]

    # Two marked edges always meet at one triangle vertex. Rotate the
    # triangle so those edges are U-V and V-W, then split into three cells.
    if mab is not None and mbc is not None:
        u, v, w, first_mid, second_mid = a, b, c, mab, mbc
    elif mbc is not None and mca is not None:
        u, v, w, first_mid, second_mid = b, c, a, mbc, mca
    else:
        u, v, w, first_mid, second_mid = c, a, b, mca, mab
    return [
        (u, first_mid, w),
        (first_mid, v, second_mid),
        (first_mid, second_mid, w),
    ]


def _refine_adaptive(triangles, evaluator, height_tolerance, max_depth):
    """Refine only triangles near curvature or feature-ownership changes.

    Refinement is edge-based rather than a global 1-to-4 subdivision. Every
    marked edge midpoint is shared by both incident triangles; a neighbour
    is split along that edge even when it did not independently request
    refinement. Thus planar roof regions remain coarse while transition
    regions gain the needed resolution, with no T-junctions.
    """
    current = [(tuple(triangle), 0) for triangle in triangles]
    max_triangles = 50000

    for _iteration in range(max_depth + 1):
        marked_edges = set()
        for triangle, depth in current:
            vertex_samples = [evaluator(*point) for point in triangle]
            owners = {sample.slope_index for sample in vertex_samples}
            edge_scores = []
            needs_refine = False

            for edge_index in range(3):
                next_index = (edge_index + 1) % 3
                start = triangle[edge_index]
                end = triangle[next_index]
                midpoint = _midpoint(start, end)
                exact = evaluator(*midpoint)
                linear_height = (
                    vertex_samples[edge_index].height
                    + vertex_samples[next_index].height
                ) * 0.5
                error = abs(exact.height - linear_height)
                endpoint_owners = {
                    vertex_samples[edge_index].slope_index,
                    vertex_samples[next_index].slope_index,
                }
                owner_mismatch = exact.slope_index not in endpoint_owners
                if error > height_tolerance or exact.slope_index not in owners:
                    needs_refine = True
                edge_length_sq = (
                    (end[0] - start[0]) ** 2
                    + (end[1] - start[1]) ** 2
                )
                edge_scores.append((
                    int(owner_mismatch),
                    error,
                    edge_length_sq,
                    _edge_key(start, end),
                ))

            center = _centroid(triangle)
            exact_center = evaluator(*center)
            center_error = abs(
                exact_center.height
                - sum(sample.height for sample in vertex_samples) / 3.0
            )
            if (
                center_error > height_tolerance
                or exact_center.slope_index not in owners
            ):
                needs_refine = True

            if needs_refine and depth < max_depth:
                # Prioritise an edge whose midpoint crosses a feature boundary,
                # then the largest height error, then the longest edge.
                chosen = max(edge_scores, key=lambda item: item[:3])
                marked_edges.add(chosen[3])

        if not marked_edges:
            break

        marked_midpoints = {
            edge: _midpoint(*edge)
            for edge in marked_edges
        }
        refined = []
        for triangle, depth in current:
            children = _split_triangle_on_marked_edges(
                triangle, marked_midpoints
            )
            child_depth = depth + 1 if len(children) > 1 else depth
            refined.extend((child, child_depth) for child in children)

        if len(refined) > max_triangles:
            raise GeometryInputError(
                "REFINEMENT_BUDGET",
                "Слишком много полигонов после локального уточнения поверхности.",
            )
        current = refined

    # Report the measured error of the actual returned mesh, not the error
    # observed before the final conforming edge splits.
    measured_error = 0.0
    final_depth = 0
    output = []
    for triangle, depth in current:
        output.append(triangle)
        final_depth = max(final_depth, depth)
        vertex_samples = [evaluator(*point) for point in triangle]
        for edge_index in range(3):
            midpoint = _midpoint(
                triangle[edge_index],
                triangle[(edge_index + 1) % 3],
            )
            exact = evaluator(*midpoint)
            linear = (
                vertex_samples[edge_index].height
                + vertex_samples[(edge_index + 1) % 3].height
            ) * 0.5
            measured_error = max(measured_error, abs(exact.height - linear))
        exact_center = evaluator(*_centroid(triangle))
        linear_center = sum(
            sample.height for sample in vertex_samples
        ) / 3.0
        measured_error = max(
            measured_error,
            abs(exact_center.height - linear_center),
        )
    return output, measured_error, final_depth

def build_distance_field_roof_surface(
    points: Sequence[tuple[float, float, float]],
    pitches_degrees: Sequence[float],
    *,
    height_tolerance: float | None = None,
    max_depth: int = 4,
    eps: float = 1e-9,
) -> RoofSurface:
    """Build a continuous approximated roof field from finite boundary segments.

    Edge-interior regions lie on the authored per-edge planes. Near contour
    vertices, radial transition patches are adaptively triangulated, so the
    result is continuous but is not a purely planar-per-boundary-face solution.
    The main builder uses this as a guarded fallback for mixed-height concave
    contours when the exact planar arrangement fails continuity validation.
    """
    if len(points) < 3:
        raise GeometryInputError("POLY_TOO_SMALL", "Контур должен содержать минимум три вершины.")
    if len(points) != len(pitches_degrees):
        raise GeometryInputError("PITCH_COUNT", "Нужно задать по одному уклону на каждое ребро.")
    if max_depth < 0 or max_depth > 6:
        raise GeometryInputError("REFINEMENT_DEPTH", "Глубина уточнения должна быть в диапазоне 0–6.")

    boundary_xy = [(point[0], point[1]) for point in points]
    planes = build_boundary_planes(points, pitches_degrees, eps)
    features = [
        _SegmentFeature.create(points[index], points[(index + 1) % len(points)], pitches_degrees[index])
        for index in range(len(points))
    ]
    scale = _domain_scale(points)
    target_error = height_tolerance if height_tolerance is not None else scale * 0.001
    if target_error <= 0.0:
        raise GeometryInputError("INVALID_HEIGHT_TOLERANCE", "Допуск аппроксимации должен быть положительным.")

    cache = {}
    cache_scale = max(1e-12, eps * scale * 10.0)

    def evaluate(x, y):
        key = (round(x / cache_scale), round(y / cache_scale))
        cached = cache.get(key)
        if cached is not None:
            return cached
        best_height = float("inf")
        best_index = -1
        best_endpoint = False
        for index, feature in enumerate(features):
            height, endpoint_transition = feature.evaluate(x, y)
            if height < best_height - eps * scale:
                best_height = height
                best_index = index
                best_endpoint = endpoint_transition
        sample = RoofFieldSample(best_height, best_index, best_endpoint)
        cache[key] = sample
        return sample

    _check_boundary_heights(points, evaluate, eps * scale * 100.0)
    base_triangles = triangulate_simple_polygon(boundary_xy, eps)
    triangles, approximation_error, refinement_depth = _refine_adaptive(
        base_triangles, evaluate, target_error, max_depth
    )
    if len(triangles) > 50000:
        raise GeometryInputError("REFINEMENT_BUDGET", "Слишком много полигонов после уточнения поверхности.")

    registry = _VertexRegistry(max(1e-12, eps * scale * 100.0))
    faces = []
    face_slope_indices = []
    for triangle in triangles:
        indices = [registry.add((x, y, evaluate(x, y).height)) for x, y in triangle]
        if len(set(indices)) != 3:
            raise GeometryInputError("DEGENERATE_TRIANGLE", "Уточнение создало вырожденный треугольник.")
        if signed_area(triangle) < 0.0:
            indices.reverse()
        faces.append(tuple(indices))
        face_slope_indices.append(evaluate(*_centroid(triangle)).slope_index)

    source_area = abs(signed_area(boundary_xy))
    surface_area = sum(
        abs(signed_area([(registry.vertices[i][0], registry.vertices[i][1]) for i in face]))
        for face in faces
    )
    if abs(surface_area - source_area) > max(eps * scale * scale * 100.0, source_area * 1e-7):
        raise GeometryInputError(
            "DOMAIN_COVERAGE_MISMATCH",
            "Триангулированная поверхность не покрывает исходный контур полностью."
        )
    if any(count > 2 for count in _mesh_edge_usage(faces).values()):
        raise GeometryInputError("NON_MANIFOLD_SURFACE", "Верхняя поверхность имеет ребро с более чем двумя гранями.")

    validate_surface_boundary_edges(
        registry.vertices, faces, boundary_xy, max(1e-12, eps * scale * 500.0)
    )

    return RoofSurface(
        vertices=tuple(registry.vertices),
        faces=tuple(faces),
        face_slope_indices=tuple(face_slope_indices),
        planes=tuple(planes),
        source_area_xy=source_area,
        surface_area_xy=surface_area,
        boundary_xy=tuple(boundary_xy),
        approximation_error=approximation_error,
        refinement_depth=refinement_depth,
    )
