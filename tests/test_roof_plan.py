import unittest

from core.roof_plan import (
    normalise_roof_plan,
    point_in_polygon,
    polygon_area_centroid,
    slope_region_centers,
    surface_plan_data,
    visible_roof_edges,
)


def square_plan(second_plane=(0.0, 0.0, 0.0), second_slope=1):
    return {
        "vertices": [
            (0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
            (4.0, 3.0, 0.0), (0.0, 3.0, 0.0),
        ],
        "faces": [(0, 1, 2), (0, 2, 3)],
        "face_slope_indices": [0, second_slope],
        "planes": [(0.0, 0.0, 0.0)] + (
            [(0.0, 0.0, 0.0)] * (second_slope - 1) + [second_plane]
        ),
    }


def split_rectangle(split_x):
    return {
        "vertices": [
            (0.0, 0.0, 0.0), (split_x, 0.0, 0.0), (10.0, 0.0, 0.0),
            (10.0, 4.0, 0.0), (split_x, 4.0, 0.0), (0.0, 4.0, 0.0),
        ],
        "faces": [(0, 1, 4, 5), (1, 2, 3, 4)],
        "face_slope_indices": [0, 0],
        "planes": [(0.0, 0.0, 0.0)],
    }


class RoofPlanGeometryTests(unittest.TestCase):
    def test_ridge_is_visible_between_different_planes(self):
        self.assertEqual(
            len(visible_roof_edges(square_plan((1.0, -4.0 / 3.0, 0.0))),
            5,
        )

    def test_coplanar_internal_edge_is_hidden(self):
        self.assertEqual(len(visible_roof_edges(square_plan()), 4)

    def test_polygon_area_centroid_is_exact_for_rectangle(self):
        area, center = polygon_area_centroid(
            [(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (0.0, 4.0)]
        )
        self.assertAlmostEqual(area, 40.0)
        self.assertAlmostEqual(center[0], 5.0)
        self.assertAlmostEqual(center[1], 2.0)

    def test_slope_label_centroid_does_not_jump_when_faces_change_size(self):
        anchors_a = slope_region_centers(
            *normalise_roof_plan(split_rectangle(4.0))[:3]
        )
        anchors_b = slope_region_centers(
            *normalise_roof_plan(split_rectangle(6.0))[:3]
        )
        self.assertEqual(len(anchors_a), 1)
        self.assertEqual(len(anchors_b), 1)
        self.assertAlmostEqual(anchors_a[0][1][0], 5.0)
        self.assertAlmostEqual(anchors_b[0][1][0], 5.0)
        self.assertAlmostEqual(anchors_a[0][1][1], 2.0)
        self.assertAlmostEqual(anchors_b[0][1][1], 2.0)

    def test_point_in_polygon_includes_boundary(self):
        polygon = [(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0)]
        self.assertTrue(point_in_polygon((2.0, 1.5), polygon))
        self.assertTrue(point_in_polygon((0.0, 1.5), polygon))
        self.assertFalse(point_in_polygon((5.0, 1.5), polygon))

    def test_concave_slope_region_anchor_remains_inside(self):
        vertices = [
            (0, 0, 0), (8, 0, 0), (8, 3, 0),
            (3, 3, 0), (3, 8, 0), (0, 8, 0),
        ]
        plan = {
            "vertices": vertices,
            "faces": [tuple(range(len(vertices)))],
            "face_slope_indices": [0],
            "planes": [(0.0, 0.0, 0.0)],
        }
        anchors = slope_region_centers(*normalise_roof_plan(plan)[:3])
        self.assertEqual(len(anchors), 1)
        self.assertTrue(point_in_polygon(anchors[0][1], [(p[0], p[1]) for p in vertices]))

    def test_surface_data_is_json_safe(self):
        class Plane:
            a, b, c = 1.0, 2.0, 3.0

        class Surface:
            vertices = ((0.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 1.0, 2.0))
            faces = ((0, 1, 2),)
            face_slope_indices = (0,)
            planes = (Plane(),)

        data = surface_plan_data(Surface())
        self.assertEqual(data["faces"], [[0, 1, 2]])
        self.assertEqual(data["planes"], [[1.0, 2.0, 3.0]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
