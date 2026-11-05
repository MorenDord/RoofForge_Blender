"""Additional adversarial coverage for arbitrary spatial roof plans in 2.9.0."""

import math
import unittest
from collections import Counter

from spatial_roof_2_8_4 import extend_spatial_roof_eaves
from spatial_roof_2_9_0 import build_spatial_roof_mesh
from straight_skeleton_2_6_0 import (
    build_inset_seam_profile_mesh,
    extract_roof_seams,
)


def edge_uses(faces):
    result = Counter()
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1]):
            result[tuple(sorted((int(a), int(b))))] += 1
    return result


def projected_area(vertices, face):
    points = [vertices[index] for index in face]
    return 0.5 * sum(
        a[0] * b[1] - b[0] * a[1]
        for a, b in zip(points, points[1:] + points[:1])
    )


class MultiReflexSpatialStressTests(unittest.TestCase):
    """Exercise plans with more reflex events than the basic L/U fixtures."""

    def assert_surface_is_manifold(self, vertices, faces):
        self.assertTrue(vertices)
        self.assertTrue(faces)
        uses = edge_uses(faces)
        self.assertTrue(uses)
        self.assertTrue(all(count in (1, 2) for count in uses.values()))
        self.assertTrue(any(count == 1 for count in uses.values()))
        self.assertTrue(any(count == 2 for count in uses.values()))
        self.assertTrue(all(
            math.isfinite(float(value))
            for point in vertices for value in point
        ))
        for face in faces:
            self.assertGreaterEqual(len(face), 3)
            self.assertGreater(abs(projected_area(vertices, face)), 1.0e-10)
        return uses

    def assert_profiles_are_closed(self, vertices, faces, sources, outline):
        seams = extract_roof_seams(
            vertices, faces, sources, [(point[0], point[1]) for point in outline]
        )
        seam_types = {str(edge[4]).upper() for edge in seams}
        self.assertIn("RIDGE", seam_types)
        self.assertIn("VALLEY", seam_types)

        for kind, width in (("RIDGE", 0.18), ("VALLEY", 0.22)):
            profile_vertices, profile_faces = build_inset_seam_profile_mesh(
                vertices,
                faces,
                seams,
                kind,
                width,
                (0.0, 0.0, 0.015),
                end_offset=0.0,
                seat_sink_offset=(0.0, 0.0, -0.0002),
                outline=[(point[0], point[1]) for point in outline],
            )
            self.assertTrue(profile_vertices, kind + " profile has no vertices")
            self.assertTrue(profile_faces, kind + " profile has no faces")
            profile_uses = edge_uses(profile_faces)
            self.assertTrue(profile_uses)
            self.assertTrue(all(count == 2 for count in profile_uses.values()))

    def assert_overhang_is_manifold(self, vertices, faces, sources):
        before_boundary = sum(
            count == 1 for count in edge_uses(faces).values()
        )
        extended_vertices, extended_faces, extended_sources = extend_spatial_roof_eaves(
            vertices, faces, sources, 0.20
        )
        self.assertEqual(len(extended_faces), len(extended_sources))
        extended_uses = self.assert_surface_is_manifold(
            extended_vertices, extended_faces
        )
        after_boundary = sum(count == 1 for count in extended_uses.values())
        self.assertEqual(after_boundary, before_boundary)

    def test_nonplanar_plus_plan_with_many_reflex_junctions(self):
        # A 12-edge plus outline has four reflex corners and several
        # simultaneous wavefront events. The eave heights are deliberately
        # non-coplanar rather than a single linear grade.
        xy = [
            (3, 0), (7, 0), (7, 3), (10, 3),
            (10, 7), (7, 7), (7, 10), (3, 10),
            (3, 7), (0, 7), (0, 3), (3, 3),
        ]
        heights = [
            0.000, 0.020, 0.055, 0.070,
            0.045, 0.090, 0.120, 0.080,
            0.050, 0.040, 0.010, 0.015,
        ]
        outline = [(x, y, z) for (x, y), z in zip(xy, heights)]
        pitches = [math.radians(35.0)] * len(outline)

        vertices, faces, sources = build_spatial_roof_mesh(outline, pitches)
        self.assertEqual(len(faces), len(sources))
        self.assert_surface_is_manifold(vertices, faces)
        self.assert_profiles_are_closed(vertices, faces, sources, outline)
        self.assert_overhang_is_manifold(vertices, faces, sources)

    def test_flat_multi_notch_plan_with_individual_pitches(self):
        # An oblique saw-tooth recess creates several adjacent reflex events
        # without relying on orthogonal-only contour handling.
        xy = [
            (0, 0), (12, 0), (12, 8), (10, 8),
            (9, 4), (8, 4), (7, 7), (5, 7),
            (4, 4), (3, 4), (2, 8), (0, 8),
        ]
        outline = [(x, y, 0.0) for x, y in xy]
        degrees = (34, 35, 36, 37, 34, 38, 33, 36, 35, 37, 34, 36)
        pitches = [math.radians(value) for value in degrees]

        vertices, faces, sources = build_spatial_roof_mesh(outline, pitches)
        self.assertEqual(len(faces), len(sources))
        self.assert_surface_is_manifold(vertices, faces)
        self.assert_profiles_are_closed(vertices, faces, sources, outline)
        self.assert_overhang_is_manifold(vertices, faces, sources)


if __name__ == "__main__":
    unittest.main(verbosity=2)
