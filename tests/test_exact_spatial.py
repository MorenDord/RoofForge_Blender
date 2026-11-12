import unittest

from core.exact_spatial import (
    SupportPlane,
    build_spatial_junction_patch,
    build_support_planes,
    intersect_support_planes,
    intersect_three_support_planes,
    project_to_plane_intersection,
    validate_planar_face,
)
from core.geometry import GeometryInputError


class ExactSpatialPrimitiveTests(unittest.TestCase):
    def test_support_planes_pass_through_every_authored_eave_edge(self):
        points = [
            (0.0, 0.0, 0.0),
            (4.0, 0.0, 0.10),
            (4.0, 3.0, 0.0),
            (0.0, 3.0, 0.0),
        ]
        planes = build_support_planes(points, [35.0] * 4)
        self.assertEqual(len(planes), 4)
        for index, plane in enumerate(planes):
            self.assertAlmostEqual(plane.residual(points[index]), 0.0, places=9)
            self.assertAlmostEqual(plane.residual(points[(index + 1) % 4]), 0.0, places=9)

    def test_pair_intersection_line_is_exact_for_both_support_planes(self):
        planes = (
            SupportPlane(0, 1.0, 0.0, 0.0),
            SupportPlane(1, 0.0, 1.0, 0.0),
        )
        line = intersect_support_planes(planes[0], planes[1])
        self.assertIsNotNone(line)
        for parameter in (-2.0, 0.0, 1.5, 4.0):
            point = line.point_at(parameter)
            self.assertAlmostEqual(planes[0].residual(point), 0.0, places=9)
            self.assertAlmostEqual(planes[1].residual(point), 0.0, places=9)

    def test_three_plane_node_is_a_common_3d_point(self):
        planes = (
            SupportPlane(0, 1.0, 0.0, 0.0),
            SupportPlane(1, 0.0, 1.0, 0.0),
            SupportPlane(2, -1.0, -1.0, 4.0),
        )
        point = intersect_three_support_planes(*planes)
        for plane in planes:
            self.assertAlmostEqual(plane.residual(point), 0.0, places=9)
        self.assertAlmostEqual(point[0], 4.0 / 3.0, places=9)
        self.assertAlmostEqual(point[1], 4.0 / 3.0, places=9)
        self.assertAlmostEqual(point[2], 4.0 / 3.0, places=9)

    def test_parallel_distinct_support_planes_have_no_intersection(self):
        first = SupportPlane(0, 1.0, 0.0, 0.0)
        second = SupportPlane(1, 1.0, 0.0, 1.0)
        self.assertIsNone(intersect_support_planes(first, second))

    def test_coincident_support_planes_are_not_given_a_fake_seam(self):
        first = SupportPlane(0, 1.0, 0.0, 0.0)
        second = SupportPlane(1, 1.0, 0.0, 0.0)
        with self.assertRaises(GeometryInputError) as context:
            intersect_support_planes(first, second)
        self.assertEqual(context.exception.code, "COINCIDENT_SUPPORT_PLANES")

    def test_transition_patch_boundary_edges_stay_on_their_source_planes(self):
        planes = (
            SupportPlane(0, 0.8, 0.1, 0.0),
            SupportPlane(1, -0.2, 0.9, 0.3),
            SupportPlane(2, -0.9, -0.1, 3.0),
            SupportPlane(3, 0.1, -0.8, 3.6),
        )
        patch = build_spatial_junction_patch((0, 1, 2, 3), planes, (1.5, 1.5))
        self.assertFalse(patch.concurrent)
        self.assertGreaterEqual(len(patch.faces), 2)
        for index, source in enumerate(patch.boundary_source_indices):
            first = patch.boundary_points[index - 1]
            second = patch.boundary_points[index]
            self.assertAlmostEqual(planes[source].residual(first), 0.0, places=8)
            self.assertAlmostEqual(planes[source].residual(second), 0.0, places=8)

        all_vertices = patch.boundary_points
        for face in patch.faces:
            validate_planar_face(all_vertices, face, eps=1e-8)

    def test_concurrent_multi_plane_junction_collapses_to_one_exact_node(self):
        planes = (
            SupportPlane(0, 1.0, 0.0, 0.0),
            SupportPlane(1, 0.0, 1.0, 0.0),
            SupportPlane(2, -1.0, 0.0, 4.0),
            SupportPlane(3, 0.0, -1.0, 4.0),
        )
        patch = build_spatial_junction_patch((0, 1, 2, 3), planes, (2.0, 2.0))
        self.assertTrue(patch.concurrent)
        self.assertEqual(len(patch.boundary_points), 1)
        self.assertEqual(patch.faces, ())

    def test_transition_face_that_is_not_planar_is_rejected(self):
        vertices = (
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.1),
        )
        with self.assertRaises(GeometryInputError) as context:
            validate_planar_face(vertices, (0, 1, 2, 3))
        self.assertEqual(context.exception.code, "NON_PLANAR_TRANSITION_FACE")

    def test_projection_to_pair_intersection_is_not_a_height_average(self):
        first = SupportPlane(0, 1.0, 0.0, 0.0)
        second = SupportPlane(1, 0.0, 1.0, 0.0)
        point = project_to_plane_intersection(first, second, (1.0, 2.0))
        self.assertAlmostEqual(point[0], 1.5, places=9)
        self.assertAlmostEqual(point[1], 1.5, places=9)
        self.assertAlmostEqual(first.residual(point), 0.0, places=9)
        self.assertAlmostEqual(second.residual(point), 0.0, places=9)


if __name__ == "__main__":
    unittest.main()
