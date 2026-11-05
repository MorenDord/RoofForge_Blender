"""Tests for the experimental 2.9 spatial topology-lifting solver.

These are pure-Python geometry tests. They do not replace Blender 5.x runtime
validation. The test suite intentionally checks strict manifold and boundary
invariants instead of merely asserting that a mesh was returned.
"""
import math
import unittest
from collections import Counter

from spatial_roof_2_9_0 import (
    build_spatial_roof_mesh, SpatialRoofError, _face_corner_direction
)


def edge_uses(faces):
    result = Counter()
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            result[tuple(sorted((a, b)))] += 1
    return result


class SpatialTopologyLiftTests(unittest.TestCase):
    def assert_closed_footprint_mesh(self, outline, pitches):
        vertices, faces, sources = build_spatial_roof_mesh(outline, pitches)
        self.assertTrue(vertices)
        self.assertTrue(faces)
        self.assertEqual(len(faces), len(sources))
        self.assertTrue(all(len(face) >= 3 for face in faces))
        self.assertTrue(all(math.isfinite(v) for p in vertices for v in p))
        uses = edge_uses(faces)
        self.assertTrue(all(count in (1, 2) for count in uses.values()))
        self.assertTrue(any(count == 1 for count in uses.values()))
        self.assertTrue(any(count == 2 for count in uses.values()))
        return vertices, faces, sources

    def test_flat_rectangle_equal_pitch(self):
        outline = [(0, 0, 0), (8, 0, 0), (8, 5, 0), (0, 5, 0)]
        self.assert_closed_footprint_mesh(outline, [math.radians(35)] * 4)

    def test_nonplanar_convex_rectangle(self):
        outline = [(0, 0, 0), (8, 0, .25), (8, 5, .45), (0, 5, .1)]
        pitches = [math.radians(v) for v in (35, 38, 40, 36)]
        self.assert_closed_footprint_mesh(outline, pitches)

    def test_flat_concave_l_equal_pitch(self):
        outline = [
            (0, 0, 0), (8, 0, 0), (8, 4, 0),
            (4, 4, 0), (4, 8, 0), (0, 8, 0),
        ]
        self.assert_closed_footprint_mesh(outline, [math.radians(35)] * 6)

    def test_flat_concave_u_equal_pitch(self):
        outline = [
            (0, 0, 0), (10, 0, 0), (10, 8, 0),
            (7, 8, 0), (7, 3, 0), (3, 3, 0),
            (3, 8, 0), (0, 8, 0),
        ]
        self.assert_closed_footprint_mesh(outline, [math.radians(35)] * 8)



    def test_flat_concave_l_small_individual_pitch_variation(self):
        outline = [
            (0, 0, 0), (8, 0, 0), (8, 4, 0),
            (4, 4, 0), (4, 8, 0), (0, 8, 0),
        ]
        pitches = [math.radians(v) for v in (34, 35, 36, 35, 34, 36)]
        self.assert_closed_footprint_mesh(outline, pitches)

    def test_flat_concave_l_individual_pitches(self):
        outline = [
            (0, 0, 0), (8, 0, 0), (8, 4, 0),
            (4, 4, 0), (4, 8, 0), (0, 8, 0),
        ]
        pitches = [math.radians(v) for v in (30, 36, 42, 34, 39, 32)]
        self.assert_closed_footprint_mesh(outline, pitches)

    def test_flat_concave_u_individual_pitches(self):
        outline = [
            (0, 0, 0), (10, 0, 0), (10, 8, 0),
            (7, 8, 0), (7, 3, 0), (3, 3, 0),
            (3, 8, 0), (0, 8, 0),
        ]
        pitches = [math.radians(v) for v in (32, 35, 38, 40, 34, 37, 31, 36)]
        self.assert_closed_footprint_mesh(outline, pitches)


    @unittest.expectedFailure
    def test_nonplanar_concave_l_outline(self):
        outline = [
            (0, 0, 0.00), (8, 0, 0.08), (8, 4, 0.12),
            (4, 4, 0.16), (4, 8, 0.20), (0, 8, 0.10),
        ]
        self.assert_closed_footprint_mesh(
            outline, [math.radians(35)] * len(outline)
        )

    @unittest.expectedFailure
    def test_nonplanar_concave_u_outline(self):
        outline = [
            (0, 0, 0.00), (10, 0, 0.08), (10, 8, 0.14),
            (7, 8, 0.20), (7, 3, 0.12), (3, 3, 0.18),
            (3, 8, 0.24), (0, 8, 0.10),
        ]
        self.assert_closed_footprint_mesh(
            outline, [math.radians(35)] * len(outline)
        )


    def test_flat_l_equal_pitch_uses_event_solver(self):
        outline = [
            (0, 0, 1.25), (8, 0, 1.25), (8, 4, 1.25),
            (4, 4, 1.25), (4, 8, 1.25), (0, 8, 1.25),
        ]
        self.assert_closed_footprint_mesh(outline, [math.radians(35)] * 6)

    def test_flat_u_equal_pitch_uses_event_solver(self):
        outline = [
            (0, 0, 0), (10, 0, 0), (10, 8, 0),
            (7, 8, 0), (7, 3, 0), (3, 3, 0),
            (3, 8, 0), (0, 8, 0),
        ]
        self.assert_closed_footprint_mesh(outline, [math.radians(35)] * 8)


    def test_nonplanar_concave_l_millimetre_variation(self):
        outline = [
            (0, 0, 0.0000), (8, 0, 0.0010), (8, 4, 0.0015),
            (4, 4, 0.0017), (4, 8, 0.0020), (0, 8, 0.0010),
        ]
        self.assert_closed_footprint_mesh(
            outline, [math.radians(35)] * len(outline)
        )

    def test_nonplanar_concave_u_millimetre_variation(self):
        outline = [
            (0, 0, 0.0000), (10, 0, 0.0010), (10, 8, 0.0015),
            (7, 8, 0.0020), (7, 3, 0.0012), (3, 3, 0.0018),
            (3, 8, 0.0024), (0, 8, 0.0010),
        ]
        self.assert_closed_footprint_mesh(
            outline, [math.radians(35)] * len(outline)
        )


    def test_reflex_facet_corner_uses_large_interior_wedge(self):
        vertices = [
            (0.0, -1.0, 0.0),  # previous ray: 270 degrees
            (0.0, 0.0, 0.0),   # reflex corner
            (1.0, 0.0, 0.0),   # following ray: 0 degrees
            (1.0, 1.0, 0.0),
            (-1.0, 1.0, 0.0),
            (-1.0, -1.0, 0.0),
        ]
        angle = _face_corner_direction(vertices, (0, 1, 2, 3, 4, 5), 1)
        self.assertAlmostEqual(angle, math.radians(135.0), places=6)

    def test_reversed_winding_preserves_build(self):
        outline = [(0, 0, 0), (8, 0, .2), (8, 5, .4), (0, 5, .1)]
        pitches = [math.radians(v) for v in (35, 38, 40, 36)]
        reversed_outline = list(reversed(outline))
        reversed_pitches = [
            pitches[(len(pitches) - 2 - i) % len(pitches)]
            for i in range(len(pitches))
        ]
        a = build_spatial_roof_mesh(outline, pitches)
        b = build_spatial_roof_mesh(reversed_outline, reversed_pitches)
        self.assertEqual(len(a[1]), len(b[1]))
        self.assertEqual(len(a[2]), len(b[2]))
        expected_reversed_sources = [
            (len(pitches) - 2 - source_id) % len(pitches)
            for source_id in a[2]
        ]
        self.assertEqual(b[2], expected_reversed_sources)

    def test_rejects_pitch_below_eave_grade(self):
        outline = [(0, 0, 0), (1, 0, 2), (1, 1, 2), (0, 1, 0)]
        with self.assertRaises(SpatialRoofError):
            build_spatial_roof_mesh(outline, [math.radians(30)] * 4)

    def test_rejects_zero_pitch(self):
        outline = [(0, 0, 0), (4, 0, 0), (4, 4, 0), (0, 4, 0)]
        with self.assertRaises(SpatialRoofError):
            build_spatial_roof_mesh(outline, [0.0] * 4)

    def test_rejects_non_finite_coordinates(self):
        outline = [(0, 0, 0), (4, 0, 0), (4, 4, float("nan")), (0, 4, 0)]
        with self.assertRaises(SpatialRoofError):
            build_spatial_roof_mesh(outline, [math.radians(35)] * 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
