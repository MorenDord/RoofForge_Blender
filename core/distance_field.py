"""Continuous finite-segment roof field (experimental concave-contour path).

This is a comparison/fallback prototype, not the final planar-facet solution.
For every boundary edge it evaluates a plane while the perpendicular foot lies
on that finite segment; beyond either endpoint it evaluates a radial corner
transition. The lower envelope of these continuous segment features is
continuous, unlike the current per-supporting-line active-set arrangement.

The adaptive triangulation approximates the corner transition regions while
preserving exact planar edge strips wherever the closest point lies inside an
edge segment.
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

Point2 = tuple[float, float, float]
Triangle2 = tuple[tuple[float, float], tuple[float, float], tuple[float, float]]


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


def _refine_uniform(triangles, evaluator, height_tolerance, max_depth):
    current = triangles
    measured_error = 0.0
    final_depth = 0
    for depth in range(max_depth + 1):
        measured_error = 0.0
        needs_refine = False
        for triangle in current:
            samples = [evaluator(*point) for point in triangle]
            z_values = [sample.height for sample in samples]
            owners = {sample.slope_index for sample in samples}
            for first, second in ((0, 1), (1, 2), (2, 0)):
                midpoint = _midpoint(triangle[first], triangle[second])
                exact = evaluator(*midpoint)
                linear = 0.5 * (z_values[first] + z_values[second])
                error = abs(exact.height - linear)
                measured_error = max(measured_error, error)
                if error > height_tolerance or exact.slope_index not in owners:
                    needs_refine = True
            center = _centroid(triangle)
            exact_center = evaluator(*center)
            center_error = abs(exact_center.height - sum(z_values) / 3.0)
            measured_error = max(measured_error, center_error)
            if center_error > height_tolerance or exact_center.slope_index not in owners:
                needs_refine = True
        final_depth = depth
        if not needs_refine or depth >= max_depth:
            break
        current = [child for triangle in current for child in _split_triangle(triangle)]
    return current, measured_error, final_depth


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
    This is an experimental comparison path; the main builder remains strict.
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
    triangles, approximation_error, refinement_depth = _refine_uniform(
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
