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
from core.exact_spatial import validate_planar_face


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

    def test_global_envelope_rejects_dense_concave_planes_that_undercut_eave(self):
        for fixture in (_dense_mixed_height_l, _dense_mixed_height_u):
            points, pitches = fixture()
            with self.subTest(vertices=len(points)):
                with self.assertRaises(GeometryInputError) as context:
                    build_global_plane_intersection_surface(points, pitches)
                self.assertEqual(
                    context.exception.code,
                    "GLOBAL_ENVELOPE_EAVE_UNDERCUT",
                )

    def assert_transition_faceted_surface(self, surface, source_count):
        transition_faces = [
            face for face, source in zip(
                surface.faces, surface.face_slope_indices
            )
            if source == -1
        ]
        self.assertTrue(
            transition_faces,
            "the completed surface must contain explicit transition facets",
        )
        self.assertEqual(
            set(source for source in surface.face_slope_indices if source >= 0),
            set(range(source_count)),
        )

        edge_uses = {}
        for face, source in zip(surface.faces, surface.face_slope_indices):
            for local_index, first in enumerate(face):
                second = face[(local_index + 1) % len(face)]
                key = (min(first, second), max(first, second))
                edge_uses.setdefault(key, []).append(source)

            if source == -1:
                self.assertEqual(len(face), 3)
                validate_planar_face(surface.vertices, face, eps=1e-8)
            else:
                plane = surface.planes[source]
                for vertex_index in face:
                    x, y, z = surface.vertices[vertex_index]
                    self.assertAlmostEqual(z, plane.height(x, y), places=7)

        for face, source in zip(surface.faces, surface.face_slope_indices):
            if source != -1:
                continue
            for local_index, first in enumerate(face):
                second = face[(local_index + 1) % len(face)]
                key = (min(first, second), max(first, second))
                sources = edge_uses[key]
                self.assertEqual(
                    len(sources), 2,
                    "each transition-facet edge must be shared by one other face",
                )
                other_source = next(
                    value for value in sources if value != -1
                ) if any(value >= 0 for value in sources) else -1
                if other_source >= 0:
                    plane = surface.planes[other_source]
                    for vertex_index in (first, second):
                        x, y, z = surface.vertices[vertex_index]
                        self.assertAlmostEqual(
                            z, plane.height(x, y), places=7,
                            msg="transition seam must stay on the adjacent support plane",
                        )

    def test_dense_mixed_height_concave_contours_use_exact_transition_facets(self):
        for fixture in (_dense_mixed_height_l, _dense_mixed_height_u):
            points, pitches = fixture()
            with self.subTest(vertices=len(points)):
                surface = build_intersection_envelope_surface(points, pitches)
                reference = build_roof_surface(points, pitches)
                self.assert_reference_surface(points, surface)
                self.assert_reference_surface(points, reference)
                self.assert_transition_faceted_surface(surface, len(points))
                self.assert_transition_faceted_surface(reference, len(points))
                self.assert_closed_shell(surface)
                self.assert_closed_shell(reference)

    def test_finite_envelope_can_be_inspected_without_transition_completion(self):
        points, pitches = _dense_mixed_height_l()
        with self.assertRaises(GeometryInputError) as context:
            build_intersection_envelope_surface(
                points, pitches, complete_transition_facets=False
            )
        self.assertEqual(
            context.exception.code,
            "PLANE_ENVELOPE_DISCONTINUITY",
        )


if __name__ == "__main__":
    unittest.main()
