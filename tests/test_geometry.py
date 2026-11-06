import math
import unittest

from core.geometry import (
    GeometryInputError, PlaneZ, clip_half_plane, lower_envelope_cells,
    lower_envelope_regions, signed_area, triangulate_simple_polygon,
    validate_simple_polygon,
)
from core.planes import boundary_envelope_conflicts, build_boundary_planes
from core.envelope import lower_envelope_restricted_cells
from core.shell import build_roof_shell


class PolygonTests(unittest.TestCase):
    def test_rectangle_area(self):
        poly = [(0, 0), (4, 0), (4, 3), (0, 3)]
        self.assertAlmostEqual(signed_area(poly), 12.0)
        self.assertEqual(validate_simple_polygon(poly), [])

    def test_bow_tie_rejected(self):
        poly = [(0, 0), (2, 2), (0, 2), (2, 0)]
        codes = {item.code for item in validate_simple_polygon(poly)}
        self.assertIn("ZERO_AREA", codes)
        self.assertIn("SELF_INTERSECTION", codes)

    def test_half_plane_clip(self):
        square = [(0, 0), (2, 0), (2, 2), (0, 2)]
        clipped = clip_half_plane(square, 1, 0, -1)
        self.assertAlmostEqual(abs(signed_area(clipped)), 2.0)

    def test_lower_envelope_two_planes(self):
        domain = [(0, 0), (2, 0), (2, 2), (0, 2)]
        planes = [PlaneZ(1, 0, 0), PlaneZ(-1, 0, 2)]
        regions = lower_envelope_regions(domain, planes)
        self.assertAlmostEqual(abs(signed_area(regions[0])), 2.0)
        self.assertAlmostEqual(abs(signed_area(regions[1])), 2.0)

    def test_coincident_planes_have_one_deterministic_owner(self):
        domain = [(0, 0), (2, 0), (2, 2), (0, 2)]
        planes = [PlaneZ(0.5, 0.25, 1.0), PlaneZ(0.5, 0.25, 1.0)]
        regions = lower_envelope_regions(domain, planes)
        self.assertAlmostEqual(abs(signed_area(regions[0])), 4.0)
        self.assertEqual(regions[1], [])

    def test_ear_clipping_l_shape_area(self):
        l_shape = [(0, 0), (3, 0), (3, 1), (1, 1), (1, 3), (0, 3)]
        triangles = triangulate_simple_polygon(l_shape)
        self.assertEqual(len(triangles), 4)
        self.assertAlmostEqual(sum(abs(signed_area(t)) for t in triangles), 5.0)

        clockwise = list(reversed(l_shape))
        reverse_triangles = triangulate_simple_polygon(clockwise)
        self.assertAlmostEqual(sum(abs(signed_area(t)) for t in reverse_triangles), 5.0)

    def test_lower_envelope_covers_l_and_u_shapes(self):
        shapes = [
            [(0, 0), (3, 0), (3, 1), (1, 1), (1, 3), (0, 3)],
            [(0, 0), (4, 0), (4, 3), (3, 3), (3, 1), (1, 1), (1, 3), (0, 3)],
        ]
        planes = [PlaneZ(0.2, 0.0, 0.0), PlaneZ(-0.2, 0.0, 0.6),
                  PlaneZ(0.0, 0.2, 0.0), PlaneZ(0.0, -0.2, 0.6)]
        for shape in shapes:
            cells = lower_envelope_cells(shape, planes)
            cell_area = sum(abs(signed_area(cell)) for group in cells for cell in group)
            self.assertAlmostEqual(cell_area, abs(signed_area(shape)), places=7)

    def test_restricted_lower_envelope_covers_concave_domain(self):
        shapes = [
            [(0, 0), (3, 0), (3, 1), (1, 1), (1, 3), (0, 3)],
            [(0, 0), (4, 0), (4, 3), (3, 3), (3, 1), (1, 1), (1, 3), (0, 3)],
        ]
        for shape in shapes:
            points_3d = [(x, y, 0.0) for x, y in shape]
            planes = build_boundary_planes(points_3d, [35.0] * len(points_3d))
            cells = lower_envelope_restricted_cells(shape, planes)
            area = sum(abs(signed_area(cell)) for group in cells for cell in group)
            self.assertAlmostEqual(area, abs(signed_area(shape)), places=7)

    def test_plane_for_horizontal_edge(self):
        pitch = 35.0
        plane = build_boundary_planes(
            [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0), (0.0, 3.0, 0.0)],
            [pitch] * 4,
        )[0]
        self.assertAlmostEqual(plane.a, 0.0, places=7)
        self.assertAlmostEqual(plane.b, math.tan(math.radians(pitch)), places=7)
        self.assertAlmostEqual(plane.pitch_degrees, pitch, places=7)

    def test_plane_preserves_sloped_eave_endpoints(self):
        plane = build_boundary_planes(
            [(0.0, 0.0, 0.0), (4.0, 0.0, 1.0), (4.0, 3.0, 1.0), (0.0, 3.0, 0.0)],
            [30.0, 30.0, 30.0, 30.0],
        )[0]
        self.assertAlmostEqual(plane.height(0.0, 0.0), 0.0)
        self.assertAlmostEqual(plane.height(4.0, 0.0), 1.0)

    def test_pitch_cannot_be_less_than_eave_grade(self):
        with self.assertRaises(GeometryInputError) as ctx:
            build_boundary_planes(
                [(0.0, 0.0, 0.0), (4.0, 0.0, 2.0), (4.0, 3.0, 2.0), (0.0, 3.0, 0.0)],
                [20.0, 30.0, 20.0, 30.0],
            )
        self.assertEqual(ctx.exception.code, "PITCH_BELOW_EAVE_GRADE")

    def test_clockwise_and_counterclockwise_contours(self):
        ccw = [(0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0)]
        cw = list(reversed(ccw))
        for contour in (ccw, cw):
            planes = build_boundary_planes(contour, [30.0] * 4)
            self.assertEqual(len(planes), 4)
            for index, plane in enumerate(planes):
                p = contour[index]
                q = contour[(index + 1) % len(contour)]
                mid_x, mid_y = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
                self.assertAlmostEqual(plane.height(mid_x, mid_y), 0.0, places=7)
                self.assertGreater(plane.height(2.0, 1.5), -1e-8)

    def test_boundary_envelope_conflict_is_reported(self):
        points = [(0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0)]
        planes = build_boundary_planes(points, [30.0] * 4)
        self.assertEqual(boundary_envelope_conflicts(points, planes), [])

    def test_surface_mesh_works_for_rectangle_l_and_u(self):
        from core.mesh import build_roof_surface

        fixtures = [
            [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0), (0.0, 3.0, 0.0)],
            [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (3.0, 1.0, 0.0),
             (1.0, 1.0, 0.0), (1.0, 3.0, 0.0), (0.0, 3.0, 0.0)],
            [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0),
             (3.0, 3.0, 0.0), (3.0, 1.0, 0.0), (1.0, 1.0, 0.0),
             (1.0, 3.0, 0.0), (0.0, 3.0, 0.0)],
        ]
        for points in fixtures:
            surface = build_roof_surface(points, [35.0] * len(points))
            self.assertAlmostEqual(surface.surface_area_xy, surface.source_area_xy, places=7)
            self.assertEqual(len(surface.faces), len(surface.face_slope_indices))
            edge_uses = {}
            for face in surface.faces:
                for index, first in enumerate(face):
                    second = face[(index + 1) % len(face)]
                    key = tuple(sorted((first, second)))
                    edge_uses[key] = edge_uses.get(key, 0) + 1
            self.assertLessEqual(max(edge_uses.values()), 2)
            self.assertTrue(all(len(face) >= 3 for face in surface.faces))


    def test_solid_shell_is_closed_and_extruded_along_global_z(self):
        fixtures = [
            [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0), (0.0, 3.0, 0.0)],
            [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (3.0, 1.0, 0.0),
             (1.0, 1.0, 0.0), (1.0, 3.0, 0.0), (0.0, 3.0, 0.0)],
            [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0),
             (3.0, 3.0, 0.0), (3.0, 1.0, 0.0), (1.0, 1.0, 0.0),
             (1.0, 3.0, 0.0), (0.0, 3.0, 0.0)],
        ]
        for points in fixtures:
            surface = build_roof_surface(points, [35.0] * len(points))
            shell = build_roof_shell(surface, 0.15)
            self.assertEqual(len(shell.vertices), 2 * len(surface.vertices))
            self.assertEqual(shell.top_face_count, len(surface.faces))
            self.assertEqual(shell.bottom_face_count, len(surface.faces))
            self.assertEqual(shell.side_face_count, len(shell.faces) - 2 * len(surface.faces))
            for top, bottom in zip(surface.vertices, shell.vertices[len(surface.vertices):]):
                self.assertAlmostEqual(top[0], bottom[0], places=9)
                self.assertAlmostEqual(top[1], bottom[1], places=9)
                self.assertAlmostEqual(top[2] - bottom[2], 0.15, places=9)

            edge_uses = {}
            for face in shell.faces:
                for index, first in enumerate(face):
                    second = face[(index + 1) % len(face)]
                    key = tuple(sorted((first, second)))
                    edge_uses[key] = edge_uses.get(key, 0) + 1
            self.assertTrue(all(count == 2 for count in edge_uses.values()))

    def test_clockwise_input_still_generates_upward_top_faces(self):
        points = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
                  (4.0, 3.0, 0.0), (0.0, 3.0, 0.0)]
        points.reverse()
        surface = build_roof_surface(points, [35.0] * len(points))
        for face in surface.faces:
            xy = [(surface.vertices[i][0], surface.vertices[i][1]) for i in face]
            self.assertGreater(signed_area(xy), 0.0)
        shell = build_roof_shell(surface, 0.1)
        self.assertEqual(len(shell.faces), shell.top_face_count + shell.bottom_face_count + shell.side_face_count)

    def test_invalid_thickness_is_rejected(self):
        points = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
                  (4.0, 3.0, 0.0), (0.0, 3.0, 0.0)]
        surface = build_roof_surface(points, [35.0] * len(points))
        with self.assertRaises(GeometryInputError) as ctx:
            build_roof_shell(surface, 0.0)
        self.assertEqual(ctx.exception.code, "INVALID_THICKNESS")


if __name__ == "__main__":
    unittest.main()
