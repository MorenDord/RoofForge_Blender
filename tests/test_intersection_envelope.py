import math
import unittest

from core.geometry import GeometryInputError, signed_area
from core.intersection_envelope import (
    build_intersection_envelope_surface,
    build_global_plane_intersection_surface,
)
from core.mesh import build_roof_surface
from core.shell import build_roof_shell
from core.validation import validate_closed_mesh


def _wavy_outline(outline, subdivisions, amplitude, z_amplitude=0.0):
    points = []
    total = sum(subdivisions)
    for edge_index, start in enumerate(outline):
        end = outline[(edge_index + 1) % len(outline)]
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        normal = (-dy / length, dx / length)
        for step in range(subdivisions[edge_index]):
            t = step / subdivisions[edge_index]
            bend = amplitude * math.sin(math.pi * t)
            index = len(points)
            z = z_amplitude * math.sin(2.0 * math.pi * index / total)
            points.append((
                start[0] + dx * t + normal[0] * bend,
                start[1] + dy * t + normal[1] * bend,
                z,
            ))
    return points


def _dense_mixed_height_l():
    points = _wavy_outline(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 3.0),
         (4.0, 3.0), (4.0, 10.0), (0.0, 10.0)],
        [16] * 6,
        0.015,
    )
    index = len(points) // 3
    x, y, _z = points[index]
    points[index] = (x, y, 0.08)
    pitches = [
        32.0 + 4.0 * math.sin(i * 1.371) + 2.5 * math.cos(i * 0.613)
        for i in range(len(points))
    ]
    return points, pitches


def _dense_mixed_height_u():
    points = _wavy_outline(
        [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (3.0, 4.0),
         (3.0, 1.0), (1.0, 1.0), (1.0, 4.0), (0.0, 4.0)],
        [12] * 8,
        0.008,
        z_amplitude=0.01,
    )
    pitches = [
        31.0 + 4.5 * math.sin(i * 0.917) + 2.5 * math.cos(i * 0.641)
        for i in range(len(points))
    ]
    return points, pitches


class PlaneIntersectionEnvelopeTests(unittest.TestCase):
    def assert_exact_support_surface(self, points, surface):
        self.assertEqual(surface.approximation_error, 0.0)
        self.assertEqual(surface.refinement_depth, 0)
        self.assertTrue(surface.faces)
        self.assertEqual(
            set(surface.face_slope_indices),
            set(range(len(points))),
            "every authored edge plane must own a non-zero exact roof region",
        )

        edge_uses = {}
        for face, source_index in zip(surface.faces, surface.face_slope_indices):
            self.assertGreaterEqual(source_index, 0)
            plane = surface.planes[source_index]
            projected = []
            for vertex_index in face:
                x, y, z = surface.vertices[vertex_index]
                self.assertAlmostEqual(z, plane.height(x, y), places=7)
                projected.append((x, y))
            self.assertGreater(abs(signed_area(projected)), 1e-10)
            for local_index, first in enumerate(face):
                second = face[(local_index + 1) % len(face)]
                key = (min(first, second), max(first, second))
                edge_uses.setdefault(key, []).append((first, second, source_index))

        for edge, uses in edge_uses.items():
            self.assertLessEqual(len(uses), 2, f"non-manifold roof edge {edge}")
            if len(uses) == 2 and uses[0][2] != uses[1][2]:
                for vertex_index in edge:
                    x, y, z = surface.vertices[vertex_index]
                    for _first, _second, source_index in uses:
                        plane = surface.planes[source_index]
                        self.assertAlmostEqual(
                            z, plane.height(x, y), places=7,
                            msg=f"seam vertex is off support plane {source_index}",
                        )

        expected_area = abs(signed_area([(p[0], p[1]) for p in points]))
        self.assertAlmostEqual(surface.surface_area_xy, expected_area, places=7)
        self.assertAlmostEqual(surface.source_area_xy, expected_area, places=7)

    def assert_reference_surface(self, points, surface):
        self.assertTrue(surface.faces)
        self.assertEqual(surface.approximation_error, 0.0)
        self.assertEqual(surface.refinement_depth, 0)
        self.assertEqual(len(surface.face_slope_indices), len(surface.faces))
        expected_area = abs(signed_area([(p[0], p[1]) for p in points]))
        self.assertAlmostEqual(surface.surface_area_xy, expected_area, places=7)
        self.assertAlmostEqual(surface.source_area_xy, expected_area, places=7)

    def assert_closed_shell(self, surface):
        shell = build_roof_shell(surface, 0.10)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_four_different_pitches_close_without_a_common_apex(self):
        points = [
            (0.0, 0.0, 0.0),
            (10.0, 0.0, 0.0),
            (10.0, 10.0, 0.0),
            (0.0, 10.0, 0.0),
        ]
        surface = build_intersection_envelope_surface(points, [30.0, 40.0, 25.0, 50.0])
        self.assert_exact_support_surface(points, surface)
        self.assert_closed_shell(surface)

    def test_four_support_planes_preserve_a_nonplanar_eave_loop(self):
        points = [
            (0.0, 0.0, 0.0),
            (10.0, 0.0, 0.4),
            (10.0, 8.0, 0.2),
            (0.0, 8.0, 0.0),
        ]
        surface = build_intersection_envelope_surface(points, [30.0, 40.0, 25.0, 50.0])
        self.assert_exact_support_surface(points, surface)
        self.assert_closed_shell(surface)

    def test_impossible_edge_pitch_is_rejected_without_fitting(self):
        points = [
            (0.0, 0.0, 0.0),
            (4.0, 0.0, 2.0),
            (4.0, 3.0, 2.0),
            (0.0, 3.0, 0.0),
        ]
        with self.assertRaises(GeometryInputError) as context:
            build_intersection_envelope_surface(points, [20.0, 35.0, 20.0, 35.0])
        self.assertEqual(context.exception.code, "PITCH_BELOW_EAVE_GRADE")

    def test_dense_mixed_height_l_96_matches_exact_topology_invariants(self):
        points, pitches = _dense_mixed_height_l()
        surface = build_global_plane_intersection_surface(points, pitches)
        reference = build_roof_surface(points, pitches)
        self.assert_exact_support_surface(points, surface)
        self.assert_reference_surface(points, reference)
        self.assert_closed_shell(surface)
        self.assert_closed_shell(reference)

    def test_dense_mixed_height_u_96_matches_exact_topology_invariants(self):
        points, pitches = _dense_mixed_height_u()
        surface = build_global_plane_intersection_surface(points, pitches)
        reference = build_roof_surface(points, pitches)
        self.assert_exact_support_surface(points, surface)
        self.assert_reference_surface(points, reference)
        self.assert_closed_shell(surface)
        self.assert_closed_shell(reference)


if __name__ == "__main__":
    unittest.main()
