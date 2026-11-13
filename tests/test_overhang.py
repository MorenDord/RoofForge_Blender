import math
import unittest

from core.geometry import GeometryInputError, signed_area, validate_simple_polygon
from core.overhang import (
    build_source_anchored_overhang_surface,
    corner_converged_overhang_contour,
    offset_contour_outward,
)
from core.shell import build_roof_shell
from core.validation import validate_closed_mesh


FLAT_RECTANGLE = [
    (0.0, 0.0, 0.0),
    (4.0, 0.0, 0.0),
    (4.0, 3.0, 0.0),
    (0.0, 3.0, 0.0),
]
MIXED_Z_RECTANGLE = [
    (0.0, 0.0, 0.0),
    (4.0, 0.0, 0.2),
    (4.0, 3.0, 0.4),
    (0.0, 3.0, 0.1),
]
CONCAVE_L = [
    (0.0, 0.0, 0.0),
    (8.0, 0.0, 0.0),
    (8.0, 3.0, 0.0),
    (3.0, 3.0, 0.0),
    (3.0, 8.0, 0.0),
    (0.0, 8.0, 0.0),
]
CONCAVE_U = [
    (0.0, 0.0, 0.0),
    (4.0, 0.0, 0.0),
    (4.0, 4.0, 0.0),
    (3.0, 4.0, 0.0),
    (3.0, 1.0, 0.0),
    (1.0, 1.0, 0.0),
    (1.0, 4.0, 0.0),
    (0.0, 4.0, 0.0),
]


class RoofOverhangTests(unittest.TestCase):
    def _build_offset_roof(self, points, pitches, overhang, corner_convergence=False):
        offset = offset_contour_outward(points, overhang)
        offset_xy = [(point[0], point[1]) for point in offset]
        self.assertEqual(validate_simple_polygon(offset_xy), [])
        self.assertGreater(
            abs(signed_area(offset_xy)),
            abs(signed_area([(p[0], p[1]) for p in points])),
        )
        surface = build_source_anchored_overhang_surface(
            points, pitches, overhang,
            corner_convergence=corner_convergence,
        )
        self.assertEqual(surface.boundary_xy, tuple(offset_xy))
        self.assertAlmostEqual(
            surface.surface_area_xy,
            abs(signed_area(offset_xy)),
            delta=max(1e-7, abs(signed_area(offset_xy)) * 1e-7),
        )
        shell = build_roof_shell(surface, 0.01, extrude_up=True)
        self.assertTrue(shell.extrude_up)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])
        self.assertEqual(shell.vertices[len(surface.vertices):], surface.vertices)
        for top, support in zip(shell.vertices[:len(surface.vertices)], surface.vertices):
            self.assertAlmostEqual(top[0], support[0], places=9)
            self.assertAlmostEqual(top[1], support[1], places=9)
            self.assertAlmostEqual(top[2] - support[2], 0.01, places=9)
        self._assert_support_planes(points, surface)
        return offset, surface, shell

    def _assert_support_planes(self, source, surface):
        self.assertEqual(len(surface.planes), len(source))
        for index, start in enumerate(source):
            end = source[(index + 1) % len(source)]
            plane = surface.planes[index]
            self.assertAlmostEqual(plane.height(start[0], start[1]), start[2], places=8)
            self.assertAlmostEqual(plane.height(end[0], end[1]), end[2], places=8)

    def _assert_offset_edge_geometry(self, source, offset, distance):
        source_xy = [(p[0], p[1]) for p in source]
        offset_xy = [(p[0], p[1]) for p in offset]
        winding = 1.0 if signed_area(source_xy) > 0.0 else -1.0
        self.assertEqual(len(source), len(offset))
        for index, start in enumerate(source_xy):
            end = source_xy[(index + 1) % len(source_xy)]
            outer_start = offset_xy[index]
            outer_end = offset_xy[(index + 1) % len(offset_xy)]
            dx, dy = end[0] - start[0], end[1] - start[1]
            length = math.hypot(dx, dy)
            self.assertGreater(length, 1e-9)
            parallel_error = abs(
                dx * (outer_end[1] - outer_start[1])
                - dy * (outer_end[0] - outer_start[0])
            ) / length
            signed_distance = winding * (
                dx * (outer_start[1] - start[1])
                - dy * (outer_start[0] - start[0])
            ) / length
            self.assertAlmostEqual(parallel_error, 0.0, places=7)
            self.assertAlmostEqual(signed_distance, -distance, places=7)

    def test_equal_pitch_rectangle_preserves_original_support_edges(self):
        offset, surface, shell = self._build_offset_roof(
            FLAT_RECTANGLE, [35.0] * 4, 0.25
        )
        expected = (
            (-0.25, -0.25, 0.0), (4.25, -0.25, 0.0),
            (4.25, 3.25, 0.0), (-0.25, 3.25, 0.0),
        )
        for actual, wanted in zip(offset, expected):
            for a, b in zip(actual, wanted):
                self.assertAlmostEqual(a, b, places=7)
        self.assertEqual(len(surface.boundary_xy), 4)
        self.assertEqual(shell.vertices[len(surface.vertices):], surface.vertices)

    def test_custom_pitch_rectangle_uses_original_support_planes(self):
        pitches = [30.0, 35.0, 40.0, 32.0]
        offset, surface, _shell = self._build_offset_roof(FLAT_RECTANGLE, pitches, 0.2)
        self._assert_offset_edge_geometry(FLAT_RECTANGLE, offset, 0.2)
        self.assertEqual(len(surface.face_slope_indices), len(surface.faces))
        self.assertTrue(all(0 <= i < len(pitches) for i in surface.face_slope_indices))

    def test_mixed_z_contour_preserves_source_edge_heights(self):
        pitches = [38.0, 40.0, 42.0, 39.0]
        offset, surface, _shell = self._build_offset_roof(MIXED_Z_RECTANGLE, pitches, 0.2)
        for source_point, offset_point in zip(MIXED_Z_RECTANGLE, offset):
            self.assertAlmostEqual(source_point[2], offset_point[2], places=9)
        self._assert_offset_edge_geometry(MIXED_Z_RECTANGLE, offset, 0.2)
        self._assert_support_planes(MIXED_Z_RECTANGLE, surface)

    def test_mixed_z_equal_pitch_keeps_3d_eave_support(self):
        _offset, surface, _shell = self._build_offset_roof(MIXED_Z_RECTANGLE, [45.0] * 4, 0.2)
        self._assert_support_planes(MIXED_Z_RECTANGLE, surface)

    def test_custom_pitch_overhang_corners_converge_and_keep_boundary_vertex_count(self):
        pitches = [30.0, 35.0, 40.0, 32.0]
        outer = corner_converged_overhang_contour(
            FLAT_RECTANGLE, pitches, 0.2
        )
        self.assertEqual(len(outer), len(FLAT_RECTANGLE))

        surface = build_source_anchored_overhang_surface(
            FLAT_RECTANGLE, pitches, 0.2, corner_convergence=True
        )
        self.assertEqual(len(surface.boundary_xy), len(FLAT_RECTANGLE))
        self.assertEqual(len(surface.planes), len(FLAT_RECTANGLE))
        self._assert_support_planes(FLAT_RECTANGLE, surface)

        for index, point in enumerate(outer):
            previous = surface.planes[index - 1]
            current = surface.planes[index]
            self.assertAlmostEqual(
                previous.height(point[0], point[1]), point[2], places=7
            )
            self.assertAlmostEqual(
                current.height(point[0], point[1]), point[2], places=7
            )

        for index, plane in enumerate(surface.planes):
            for point_index in (index, (index + 1) % len(outer)):
                point = outer[point_index]
                self.assertAlmostEqual(
                    point[2], plane.height(point[0], point[1]), places=7
                )

        distances = []
        for index, point in enumerate(outer):
            for edge_index in ((index - 1) % len(outer), index):
                start = FLAT_RECTANGLE[edge_index]
                end = FLAT_RECTANGLE[(edge_index + 1) % len(FLAT_RECTANGLE)]
                dx, dy = end[0] - start[0], end[1] - start[1]
                length = math.hypot(dx, dy)
                signed_inward = (
                    -dy * point[0] + dx * point[1]
                    + dy * start[0] - dx * start[1]
                ) / length
                distances.append(-signed_inward)
        self.assertTrue(any(abs(value - 0.2) > 1e-4 for value in distances))

        shell = build_roof_shell(surface, 0.01, extrude_up=True)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_corner_convergence_can_be_disabled_for_constant_offset(self):
        pitches = [30.0, 35.0, 40.0, 32.0]
        surface = build_source_anchored_overhang_surface(
            FLAT_RECTANGLE, pitches, 0.2, corner_convergence=False
        )
        self.assertEqual(
            surface.boundary_xy,
            tuple((p[0], p[1]) for p in offset_contour_outward(FLAT_RECTANGLE, 0.2)),
        )

    def test_concave_l_overhang_builds_a_closed_source_aligned_shell(self):
        pitches = [31.0, 32.5, 34.0, 35.5, 37.0, 38.5]
        surface = build_source_anchored_overhang_surface(CONCAVE_L, pitches, 0.1)
        self.assertGreater(
            surface.surface_area_xy,
            abs(signed_area([(p[0], p[1]) for p in CONCAVE_L])),
        )
        self._assert_support_planes(CONCAVE_L, surface)
        shell = build_roof_shell(surface, 0.01, extrude_up=True)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_concave_u_overhang_builds_a_closed_source_aligned_shell(self):
        speeds = [0.8, 0.75, 1.0, 1.25, 1.2, 1.4, 1.0, 0.6]
        pitches = [math.degrees(math.atan(1.0 / speed)) for speed in speeds]
        surface = build_source_anchored_overhang_surface(CONCAVE_U, pitches, 0.1)
        self.assertGreater(
            surface.surface_area_xy,
            abs(signed_area([(p[0], p[1]) for p in CONCAVE_U])),
        )
        self._assert_support_planes(CONCAVE_U, surface)
        shell = build_roof_shell(surface, 0.01, extrude_up=True)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])


    def test_complex_flat_convex_overhang_supports_more_than_64_edges(self):
        edge_count = 72
        points = [
            (
                8.0 * math.cos(2.0 * math.pi * index / edge_count),
                5.0 * math.sin(2.0 * math.pi * index / edge_count),
                0.0,
            )
            for index in range(edge_count)
        ]
        pitches = [
            34.0
            + 0.8 * math.sin(2.0 * math.pi * index / edge_count * 3.0)
            + 0.4 * math.cos(2.0 * math.pi * index / edge_count * 5.0)
            for index in range(edge_count)
        ]

        surface = build_source_anchored_overhang_surface(
            points, pitches, 0.15, corner_convergence=True
        )
        self.assertEqual(len(surface.boundary_xy), edge_count)
        self.assertEqual(len(surface.planes), edge_count)
        self.assertGreater(
            surface.surface_area_xy,
            abs(signed_area([(point[0], point[1]) for point in points])),
        )
        self.assertAlmostEqual(
            surface.surface_area_xy,
            abs(signed_area(surface.boundary_xy)),
            delta=1.0e-5,
        )
        self._assert_support_planes(points, surface)

        shell = build_roof_shell(surface, 0.01, extrude_up=True)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])
        self.assertEqual(len(surface.face_slope_indices), len(surface.faces))
        self.assertTrue(
            all(0 <= index < edge_count for index in surface.face_slope_indices)
        )

    def test_large_flat_convex_overhang_without_corner_convergence_keeps_offset_path(self):
        edge_count = 72
        points = [
            (
                8.0 * math.cos(2.0 * math.pi * index / edge_count),
                5.0 * math.sin(2.0 * math.pi * index / edge_count),
                0.0,
            )
            for index in range(edge_count)
        ]
        surface = build_source_anchored_overhang_surface(
            points, [35.0] * edge_count, 0.15, corner_convergence=False
        )
        expected = offset_contour_outward(points, 0.15)
        self.assertEqual(len(surface.boundary_xy), len(expected))
        for actual, wanted in zip(surface.boundary_xy, expected):
            self.assertAlmostEqual(actual[0], wanted[0], places=8)
            self.assertAlmostEqual(actual[1], wanted[1], places=8)

    def test_too_large_u_offset_is_rejected(self):
        with self.assertRaises(GeometryInputError):
            build_source_anchored_overhang_surface(CONCAVE_U, [35.0] * 8, 1.5)

    def test_clockwise_contour_offsets_outward_and_preserves_order(self):
        clockwise = list(reversed(FLAT_RECTANGLE))
        offset = offset_contour_outward(clockwise, 0.2)
        self._assert_offset_edge_geometry(clockwise, offset, 0.2)
        self.assertGreater(
            abs(signed_area([(p[0], p[1]) for p in offset])),
            abs(signed_area([(p[0], p[1]) for p in clockwise])),
        )

    def test_zero_distance_returns_same_contour(self):
        self.assertEqual(offset_contour_outward(MIXED_Z_RECTANGLE, 0.0), tuple(MIXED_Z_RECTANGLE))

    def test_negative_or_non_finite_distance_is_rejected(self):
        for distance in (-0.1, float("nan"), float("inf")):
            with self.subTest(distance=distance):
                with self.assertRaises(GeometryInputError):
                    offset_contour_outward(FLAT_RECTANGLE, distance)


if __name__ == "__main__":
    unittest.main()
