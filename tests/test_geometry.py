import math
import unittest

from core.geometry import (
    GeometryInputError, PlaneZ, clip_half_plane, lower_envelope_cells,
    lower_envelope_regions, signed_area, triangulate_simple_polygon,
    validate_simple_polygon,
)
from core.planes import boundary_envelope_conflicts, build_boundary_planes
from core.envelope import lower_envelope_restricted_cells
from core.mesh import build_roof_surface
from core.shell import build_roof_shell
from core.validation import validate_closed_mesh
from core.distance_field import build_distance_field_roof_surface
from core.wavefront import (
    EventBatch, EventKind, WavefrontEvent, WavefrontEventQueue, WavefrontLoop,
    advance_wavefront_state, apply_split_event, build_moving_lines,
    build_wavefront_roof_surface,
    collect_loop_events, create_wavefront_state, find_split_candidates,
    run_weighted_wavefront, is_flat_eave_contour,
    simulate_convex_wavefront, _line_intersection, _resolve_edge_collapse_group,
)


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

    def test_surface_mesh_for_convex_rectangle(self):
        points = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
                  (4.0, 3.0, 0.0), (0.0, 3.0, 0.0)]
        surface = build_roof_surface(points, [35.0] * len(points))
        self.assertAlmostEqual(surface.surface_area_xy, surface.source_area_xy, places=7)
        self.assertTrue(all(signed_area([(surface.vertices[i][0], surface.vertices[i][1])
                                         for i in face]) > 0.0
                            for face in surface.faces))

    def test_mixed_height_concave_surface_falls_back_to_continuous_field(self):
        # A Z-varying L contour selects the 3D support-plane solver rather than
        # the flat-eave weighted wavefront. Infinite supporting half-planes
        # change candidate sets across an internal line and leave a crack.
        points = [
            (0.0, 0.0, 0.00),
            (3.0, 0.0, 0.05),
            (3.0, 1.0, 0.08),
            (1.0, 1.0, 0.12),
            (1.0, 3.0, 0.16),
            (0.0, 3.0, 0.10),
        ]
        pitches = [40.0, 42.0, 38.0, 45.0, 41.0, 39.0]
        surface = build_roof_surface(points, pitches)
        self.assertGreater(surface.approximation_error, 0.0)
        self.assertGreater(surface.refinement_depth, 0)
        self.assertLess(
            len(surface.faces), 256,
            "mixed-height fallback must refine locally, not subdivide the entire roof",
        )
        self.assertAlmostEqual(
            surface.surface_area_xy,
            abs(signed_area([(point[0], point[1]) for point in points])),
            places=7,
        )
        self.assertEqual(len(surface.face_slope_indices), len(surface.faces))
        shell = build_roof_shell(surface, 0.10)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

        for index, start in enumerate(points):
            end = points[(index + 1) % len(points)]
            plane = surface.planes[index]
            self.assertAlmostEqual(plane.height(start[0], start[1]), start[2], places=7)
            self.assertAlmostEqual(plane.height(end[0], end[1]), end[2], places=7)

    def test_discontinuous_concave_surface_is_rejected(self):
        fixtures = [
            [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (3.0, 1.0, 0.0),
             (1.0, 1.0, 0.0), (1.0, 3.0, 0.0), (0.0, 3.0, 0.0)],
            [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0),
             (3.0, 3.0, 0.0), (3.0, 1.0, 0.0), (1.0, 1.0, 0.0),
             (1.0, 3.0, 0.0), (0.0, 3.0, 0.0)],
        ]
        for points in fixtures:
            with self.assertRaises(GeometryInputError) as ctx:
                build_roof_surface(points, [35.0] * len(points))
            self.assertIn(ctx.exception.code, {
                "INTERNAL_OPEN_EDGE", "BOUNDARY_COVERAGE_MISMATCH"
            })

    def test_solid_shell_is_closed_and_extruded_along_global_z(self):
        fixtures = [
            [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
             (4.0, 3.0, 0.0), (0.0, 3.0, 0.0)],
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


    def test_closed_mesh_validator_accepts_generated_shell(self):
        points = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
                  (4.0, 3.0, 0.0), (0.0, 3.0, 0.0)]
        surface = build_roof_surface(points, [35.0] * len(points))
        shell = build_roof_shell(surface, 0.12)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_closed_mesh_validator_rejects_open_surface(self):
        vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        diagnostics = validate_closed_mesh(vertices, [(0, 1, 2)])
        self.assertIn("BOUNDARY_EDGE", {item.code for item in diagnostics})

    def test_closed_mesh_validator_uses_local_face_scale_for_area(self):
        # A small but well-shaped base triangle remains numerically resolvable
        # even though the complete closed tetrahedron spans a much larger range.
        vertices = [
            (0.0, 0.0, 0.0),
            (0.0004, 0.0, 0.0),
            (0.0002, 0.0003464101615, 0.0),
            (10.0, 10.0, 10.0),
        ]
        faces = [
            (1, 2, 3),
            (0, 3, 2),
            (0, 1, 3),
            (0, 2, 1),
        ]
        self.assertEqual(validate_closed_mesh(vertices, faces, eps=1e-9), [])

    def test_closed_mesh_validator_rejects_sliver_below_coordinate_tolerance(self):
        vertices = [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.5, 1e-10, 0.0),
            (10.0, 10.0, 10.0),
        ]
        faces = [
            (1, 2, 3),
            (0, 3, 2),
            (0, 1, 3),
            (0, 2, 1),
        ]
        codes = {
            item.code
            for item in validate_closed_mesh(vertices, faces, eps=1e-9)
        }
        self.assertIn("ZERO_AREA_FACE", codes)

    def test_closed_mesh_validator_detects_bow_tie_vertex(self):
        vertices = [
            (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1),
            (-1, 0, 0), (0, -1, 0), (0, 0, -1),
        ]
        faces = [
            (0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3),
            (0, 5, 4), (0, 4, 6), (0, 6, 5), (4, 5, 6),
        ]
        codes = {item.code for item in validate_closed_mesh(vertices, faces)}
        self.assertIn("NON_MANIFOLD_VERTEX", codes)



    def test_segment_distance_field_builds_closed_l_and_u_shells(self):
        shapes = [
            [(0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (3.0, 1.0, 0.0),
             (1.0, 1.0, 0.0), (1.0, 3.0, 0.0), (0.0, 3.0, 0.0)],
            [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0),
             (3.0, 3.0, 0.0), (3.0, 1.0, 0.0), (1.0, 1.0, 0.0),
             (1.0, 3.0, 0.0), (0.0, 3.0, 0.0)],
        ]
        for points in shapes:
            surface = build_distance_field_roof_surface(
                points, [35.0] * len(points), max_depth=3
            )
            shell = build_roof_shell(surface, 0.12)
            self.assertAlmostEqual(surface.surface_area_xy, surface.source_area_xy, places=7)
            self.assertGreater(len(surface.faces), len(points) - 2)
            self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])
            self.assertGreaterEqual(surface.refinement_depth, 0)
            self.assertGreaterEqual(surface.approximation_error, 0.0)

    def test_segment_distance_field_accepts_individual_pitches(self):
        points = [
            (0.0, 0.0, 0.0), (3.0, 0.0, 0.0), (3.0, 1.0, 0.0),
            (1.0, 1.0, 0.0), (1.0, 3.0, 0.0), (0.0, 3.0, 0.0),
        ]
        pitches = [28.0, 32.0, 38.0, 42.0, 34.0, 30.0]
        surface = build_distance_field_roof_surface(points, pitches, max_depth=3)
        shell = build_roof_shell(surface, 0.10)
        self.assertEqual(len(surface.planes), len(pitches))
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_segment_distance_field_preserves_all_boundary_heights(self):
        points = [
            (0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
            (4.0, 3.0, 0.0), (0.0, 3.0, 0.0),
        ]
        surface = build_distance_field_roof_surface(points, [30.0, 35.0, 40.0, 32.0], max_depth=2)
        for x, y, z in points:
            matches = [
                vertex for vertex in surface.vertices
                if abs(vertex[0] - x) < 1e-8 and abs(vertex[1] - y) < 1e-8
            ]
            self.assertTrue(matches)
            self.assertTrue(all(abs(vertex[2] - z) < 1e-8 for vertex in matches))



    def test_wavefront_line_intersection_and_velocity(self):
        points = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
                  (4.0, 2.0, 0.0), (0.0, 2.0, 0.0)]
        edges = build_moving_lines(points, [45.0] * 4)
        vertex = _line_intersection(edges[3], edges[0], 0.0, 1e-9)
        self.assertAlmostEqual(vertex.point[0], 0.0, places=7)
        self.assertAlmostEqual(vertex.point[1], 0.0, places=7)
        self.assertAlmostEqual(vertex.velocity[0], 1.0, places=7)
        self.assertAlmostEqual(vertex.velocity[1], 1.0, places=7)

    def test_weighted_wavefront_rectangle_ends_in_needle_and_covers_domain(self):
        points = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
                  (4.0, 2.0, 0.0), (0.0, 2.0, 0.0)]
        trace = simulate_convex_wavefront(points, [45.0] * 4)
        self.assertEqual(trace.terminal_kind, "NEEDLE")
        self.assertAlmostEqual(trace.terminal_time, 1.0, places=7)
        self.assertAlmostEqual(trace.projected_facet_area, 8.0, places=7)
        self.assertEqual(len(trace.facets), 4)
        self.assertEqual(len(trace.skeleton_arcs), 1)
        arc = trace.skeleton_arcs[0]
        self.assertAlmostEqual(arc.start[2], 1.0, places=7)
        self.assertAlmostEqual(arc.end[2], 1.0, places=7)
        self.assertAlmostEqual(abs(arc.start[0] - arc.end[0]), 2.0, places=7)

    def test_wavefront_square_ends_in_simultaneous_point_event(self):
        points = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0),
                  (2.0, 2.0, 0.0), (0.0, 2.0, 0.0)]
        trace = simulate_convex_wavefront(points, [45.0] * 4)
        self.assertEqual(trace.terminal_kind, "POINT")
        self.assertAlmostEqual(trace.terminal_time, 1.0, places=7)
        self.assertAlmostEqual(trace.projected_facet_area, 4.0, places=7)
        simultaneous = [event for event in trace.events if event.kind == EventKind.SIMULTANEOUS]
        self.assertEqual(len(simultaneous), 1)

    def test_weighted_wavefront_supports_unequal_pitch_rectangle(self):
        points = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
                  (4.0, 3.0, 0.0), (0.0, 3.0, 0.0)]
        pitches = [45.0, 30.0, 45.0, 30.0]
        trace = simulate_convex_wavefront(points, pitches)
        self.assertTrue(trace.is_complete)
        self.assertAlmostEqual(trace.projected_facet_area, 12.0, places=7)
        for facet in trace.facets:
            self.assertGreaterEqual(facet.end_time, facet.start_time)

    def test_wavefront_rejects_mixed_eave_heights(self):
        points = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.5),
                  (4.0, 2.0, 0.5), (0.0, 2.0, 0.0)]
        with self.assertRaises(GeometryInputError) as ctx:
            build_moving_lines(points, [45.0] * 4)
        self.assertEqual(ctx.exception.code, "MIXED_EAVE_HEIGHTS_UNSUPPORTED")

    def test_flat_eave_detection_is_independent_of_absolute_z_offset(self):
        flat = [
            (0.0, 0.0, 1_000_000_000.0),
            (4.0, 0.0, 1_000_000_000.0),
            (4.0, 2.0, 1_000_000_000.0),
            (0.0, 2.0, 1_000_000_000.0),
        ]
        stepped = list(flat)
        stepped[1] = (stepped[1][0], stepped[1][1], 1_000_000_000.5)

        self.assertTrue(is_flat_eave_contour(flat))
        self.assertFalse(is_flat_eave_contour(stepped))
        with self.assertRaises(GeometryInputError) as ctx:
            build_moving_lines(stepped, [45.0] * 4)
        self.assertEqual(ctx.exception.code, "MIXED_EAVE_HEIGHTS_UNSUPPORTED")

    def test_wavefront_convex_simulation_rejects_reflex_contour(self):
        points = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 1.0, 0.0),
                  (1.0, 1.0, 0.0), (1.0, 4.0, 0.0), (0.0, 4.0, 0.0)]
        with self.assertRaises(GeometryInputError) as ctx:
            simulate_convex_wavefront(points, [45.0] * len(points))
        self.assertEqual(ctx.exception.code, "REFLEX_SPLIT_REQUIRED")

    def test_wavefront_detects_reflex_split_candidate_on_finite_edge(self):
        points = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 1.0, 0.0),
                  (1.0, 1.0, 0.0), (1.0, 4.0, 0.0), (0.0, 4.0, 0.0)]
        pitches = [45.0, 45.0, 45.0, 78.6900675, 45.0, 78.6900675]
        moving = build_moving_lines(points, pitches)
        loop = WavefrontLoop(0, tuple(range(len(moving))))
        candidates = find_split_candidates(loop, {edge.edge_id: edge for edge in moving})
        split_events = [event for event in candidates if event.kind == EventKind.SPLIT_CANDIDATE]
        self.assertTrue(split_events)
        expected_time = 0.5
        self.assertTrue(any(abs(event.time - expected_time) < 1e-6 for event in split_events))
        self.assertTrue(any(event.target_edge_id == 0 for event in split_events))



    def test_event_queue_groups_simultaneous_events_deterministically(self):
        queue = WavefrontEventQueue()
        events = [
            WavefrontEvent(
                EventKind.SPLIT_CANDIDATE, 1.0 + 5e-10, 0,
                edge_id=3, vertex_id=2, target_edge_id=1,
                participant_generations=((1, 0), (2, 0), (3, 0)),
            ),
            WavefrontEvent(
                EventKind.EDGE_COLLAPSE, 1.0, 0,
                edge_id=2, vertex_id=1,
                participant_generations=((1, 0), (2, 0), (3, 0)),
            ),
            WavefrontEvent(EventKind.NEEDLE, 2.0, 0),
        ]
        queue.push_many(events)
        batch = queue.pop_next_batch(
            current_time=0.0,
            time_tolerance=1e-9,
            current_edge_generations={1: 0, 2: 0, 3: 0},
            current_loop_generations={0: 0},
        )
        self.assertIsNotNone(batch)
        self.assertAlmostEqual(batch.time, 1.0)
        self.assertEqual(
            [event.kind for event in batch.events],
            [EventKind.EDGE_COLLAPSE, EventKind.SPLIT_CANDIDATE],
        )
        self.assertEqual(len(queue), 1)

    def test_event_queue_discards_stale_edge_and_loop_generations(self):
        queue = WavefrontEventQueue()
        queue.push(WavefrontEvent(
            EventKind.EDGE_COLLAPSE, 1.0, 5,
            edge_id=2,
            participant_generations=((1, 4), (2, 8)),
            loop_generation=3,
        ))
        queue.push(WavefrontEvent(
            EventKind.EDGE_COLLAPSE, 2.0, 5,
            edge_id=2,
            participant_generations=((1, 5), (2, 8)),
            loop_generation=4,
        ))
        batch = queue.pop_next_batch(
            current_edge_generations={1: 5, 2: 8},
            current_loop_generations={5: 4},
        )
        self.assertIsNotNone(batch)
        self.assertEqual(batch.time, 2.0)
        self.assertEqual(queue.discarded_stale, 1)
        self.assertEqual(len(queue), 0)

    def test_event_queue_discards_events_before_current_time(self):
        queue = WavefrontEventQueue()
        queue.push(WavefrontEvent(EventKind.EDGE_COLLAPSE, 0.5, 0))
        queue.push(WavefrontEvent(EventKind.EDGE_COLLAPSE, 1.5, 0))
        batch = queue.pop_next_batch(current_time=1.0, time_tolerance=1e-9)
        self.assertIsNotNone(batch)
        self.assertEqual(batch.time, 1.5)
        self.assertEqual(queue.discarded_stale, 1)

    def test_collect_loop_events_adds_loop_generation_to_events(self):
        points = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
                  (4.0, 2.0, 0.0), (0.0, 2.0, 0.0)]
        moving = build_moving_lines(points, [45.0] * 4)
        edges = {edge.edge_id: edge for edge in moving}
        loop = WavefrontLoop(7, tuple(range(4)), generation=12)
        events = collect_loop_events(loop, edges)
        self.assertTrue(events)
        self.assertTrue(all(event.loop_generation == 12 for event in events))



    def test_wavefront_split_event_splits_concave_loop_into_two_valid_loops(self):
        # A symmetric V-notch has a reflex vertex whose trajectory hits
        # the non-parallel bottom edge in its live interior (a genuine split,
        # not the parallel-edge needle degeneracy of an L-shaped fixture).
        points = [
            (0.0, 0.0, 0.0), (6.0, 0.0, 0.0), (6.0, 4.0, 0.0),
            (4.0, 4.0, 0.0), (3.0, 2.0, 0.0), (2.0, 4.0, 0.0),
            (0.0, 4.0, 0.0),
        ]
        pitches = [45.0] * len(points)
        moving = build_moving_lines(points, pitches)
        edges = {edge.edge_id: edge for edge in moving}
        loop = WavefrontLoop(0, tuple(range(len(moving))), generation=4)
        candidates = find_split_candidates(loop, edges)
        event = next(
            item for item in candidates
            if item.kind == EventKind.SPLIT_CANDIDATE
            and item.target_edge_id == 0
            and item.vertex_id == 4
        )
        result = apply_split_event(loop, edges, event)
        self.assertEqual(len(result.loops), 2)
        self.assertTrue(all(child.generation == 5 for child in result.loops))
        self.assertEqual(len(result.loops[0].edge_ids), 4)
        self.assertEqual(len(result.loops[1].edge_ids), 4)
        self.assertNotIn(0, result.edges)
        self.assertEqual(
            sum(1 for edge in result.edges.values() if edge.source_edge_id == 0),
            2,
        )
        self.assertAlmostEqual(result.event_position[0], event.position[0], places=8)
        self.assertAlmostEqual(result.event_position[1], event.position[1], places=8)

    def test_wavefront_split_rejects_stale_loop_generation(self):
        points = [
            (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 1.0, 0.0),
            (1.0, 1.0, 0.0), (1.0, 4.0, 0.0), (0.0, 4.0, 0.0),
        ]
        pitches = [45.0, 45.0, 45.0, 78.6900675, 45.0, 78.6900675]
        moving = build_moving_lines(points, pitches)
        edges = {edge.edge_id: edge for edge in moving}
        loop = WavefrontLoop(0, tuple(range(len(moving))), generation=4)
        event = next(
            item for item in find_split_candidates(loop, edges)
            if item.kind == EventKind.SPLIT_CANDIDATE
        )
        changed_loop = WavefrontLoop(loop.loop_id, loop.edge_ids, generation=5)
        with self.assertRaises(GeometryInputError) as ctx:
            apply_split_event(changed_loop, edges, event)
        self.assertEqual(ctx.exception.code, "STALE_SPLIT_EVENT")



    def test_wavefront_split_topology_is_winding_independent(self):
        ccw = [
            (0.0, 0.0, 0.0), (6.0, 0.0, 0.0), (6.0, 4.0, 0.0),
            (4.0, 4.0, 0.0), (3.0, 2.0, 0.0), (2.0, 4.0, 0.0),
            (0.0, 4.0, 0.0),
        ]
        for points in (ccw, list(reversed(ccw))):
            moving = build_moving_lines(points, [45.0] * len(points))
            edges = {edge.edge_id: edge for edge in moving}
            loop = WavefrontLoop(0, tuple(range(len(moving))), generation=2)
            candidates = find_split_candidates(loop, edges)
            event = next(item for item in candidates if item.kind == EventKind.SPLIT_CANDIDATE)
            result = apply_split_event(loop, edges, event)
            self.assertEqual(len(result.loops), 2)
            self.assertEqual(sorted(len(child.edge_ids) for child in result.loops), [4, 4])
            self.assertEqual(result.loops[0].generation, 3)
            self.assertEqual(result.loops[1].generation, 3)



    def test_global_wavefront_state_resolves_rectangle_needle(self):
        points = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
                  (4.0, 2.0, 0.0), (0.0, 2.0, 0.0)]
        state = create_wavefront_state(points, [45.0] * 4)
        batch = advance_wavefront_state(state)
        self.assertIsNotNone(batch)
        self.assertAlmostEqual(state.current_time, 1.0, places=7)
        self.assertTrue(state.is_complete)
        self.assertEqual(state.terminal_loops, {0: "NEEDLE"})

    def test_global_wavefront_state_resolves_square_point(self):
        points = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0),
                  (2.0, 2.0, 0.0), (0.0, 2.0, 0.0)]
        state = create_wavefront_state(points, [45.0] * 4)
        batch = advance_wavefront_state(state)
        self.assertIsNotNone(batch)
        self.assertAlmostEqual(state.current_time, 1.0, places=7)
        self.assertTrue(state.is_complete)
        self.assertEqual(state.terminal_loops, {0: "POINT"})

    def test_global_wavefront_state_processes_v_notch_split(self):
        points = [
            (0.0, 0.0, 0.0), (6.0, 0.0, 0.0), (6.0, 4.0, 0.0),
            (4.0, 4.0, 0.0), (3.0, 2.0, 0.0), (2.0, 4.0, 0.0),
            (0.0, 4.0, 0.0),
        ]
        state = create_wavefront_state(points, [45.0] * len(points))
        split_seen = False
        for _ in range(16):
            batch = advance_wavefront_state(state)
            if batch is None:
                break
            if any(event.kind == EventKind.SPLIT_CANDIDATE for event in batch.events):
                split_seen = True
                break
        self.assertTrue(split_seen)
        self.assertEqual(len(state.loops), 2)
        self.assertEqual(sorted(len(loop.edge_ids) for loop in state.loops.values()), [4, 4])
        self.assertEqual(
            sorted(loop.generation for loop in state.loops.values()),
            [1, 1],
        )



    def test_global_wavefront_collects_planar_facets_and_skeleton_arcs(self):
        points = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
                  (4.0, 2.0, 0.0), (0.0, 2.0, 0.0)]
        state = create_wavefront_state(points, [45.0] * 4)
        while not state.is_complete:
            advance_wavefront_state(state)
        self.assertEqual(len(state.facets), 4)
        projected_area = sum(
            abs(signed_area([(p[0], p[1]) for p in facet.vertices]))
            for facet in state.facets
        )
        self.assertAlmostEqual(projected_area, 8.0, places=7)
        self.assertGreaterEqual(len(state.skeleton_arcs), 5)
        for facet in state.facets:
            self.assertGreaterEqual(facet.end_time, facet.start_time)
            line = next(
                item for item in build_moving_lines(points, [45.0] * 4)
                if item.source_edge_id == facet.source_edge_id
            )
            for x, y, z in facet.vertices:
                expected = line.base_height + (
                    line.normal[0] * x + line.normal[1] * y - line.offset
                ) / line.speed
                self.assertAlmostEqual(z, expected, places=7)

    def test_wavefront_respects_nonzero_constant_eave_height(self):
        base_z = 2.5
        points = [(0.0, 0.0, base_z), (4.0, 0.0, base_z),
                  (4.0, 2.0, base_z), (0.0, 2.0, base_z)]
        state = create_wavefront_state(points, [45.0] * 4)
        self.assertAlmostEqual(state.current_time, base_z)
        while not state.is_complete:
            advance_wavefront_state(state)
        self.assertAlmostEqual(state.current_time, base_z + 1.0, places=7)
        self.assertTrue(all(
            abs(vertex[2] - base_z) < 1e-7
            for facet in state.facets
            for vertex in facet.vertices
            if abs(vertex[2] - base_z) < 1e-7
        ))



    def test_run_weighted_wavefront_returns_complete_rectangle_trace(self):
        points = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
                  (4.0, 2.0, 0.0), (0.0, 2.0, 0.0)]
        trace = run_weighted_wavefront(points, [45.0] * 4)
        self.assertTrue(trace.is_complete)
        self.assertEqual(trace.terminal_kind, "NEEDLE")
        self.assertAlmostEqual(trace.projected_facet_area, 8.0, places=7)
        self.assertEqual(len(trace.facets), 4)
        self.assertGreaterEqual(len(trace.skeleton_arcs), 5)

    def test_run_weighted_wavefront_returns_complete_v_notch_trace(self):
        points = [
            (0.0, 0.0, 0.0), (6.0, 0.0, 0.0), (6.0, 4.0, 0.0),
            (4.0, 4.0, 0.0), (3.0, 2.0, 0.0), (2.0, 4.0, 0.0),
            (0.0, 4.0, 0.0),
        ]
        trace = run_weighted_wavefront(points, [45.0] * len(points))
        self.assertTrue(trace.is_complete)
        self.assertGreaterEqual(len(trace.facets), len(points))
        self.assertAlmostEqual(trace.projected_facet_area, abs(signed_area(
            [(point[0], point[1]) for point in points]
        )), places=6)
        self.assertTrue(any(event.kind == EventKind.SPLIT_CANDIDATE for event in trace.events))

    def test_run_weighted_wavefront_preserves_absolute_eave_height(self):
        base_z = 3.25
        points = [(0.0, 0.0, base_z), (4.0, 0.0, base_z),
                  (4.0, 2.0, base_z), (0.0, 2.0, base_z)]
        trace = run_weighted_wavefront(points, [45.0] * 4)
        self.assertAlmostEqual(trace.terminal_time, base_z + 1.0, places=7)
        self.assertTrue(all(
            vertex[2] >= base_z - 1e-8
            for facet in trace.facets for vertex in facet.vertices
        ))



    def test_wavefront_surface_assembles_rectangle_into_welded_mesh(self):
        points = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0),
                  (4.0, 2.0, 0.0), (0.0, 2.0, 0.0)]
        surface = build_wavefront_roof_surface(points, [45.0] * 4)
        self.assertAlmostEqual(surface.source_area_xy, 8.0, places=7)
        self.assertAlmostEqual(surface.surface_area_xy, 8.0, places=7)
        self.assertEqual(len(surface.faces), 4)
        shell = build_roof_shell(surface, 0.15)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_wavefront_surface_assembles_v_notch_into_manifold_shell(self):
        points = [
            (0.0, 0.0, 0.0), (6.0, 0.0, 0.0), (6.0, 4.0, 0.0),
            (4.0, 4.0, 0.0), (3.0, 2.0, 0.0), (2.0, 4.0, 0.0),
            (0.0, 4.0, 0.0),
        ]
        surface = build_wavefront_roof_surface(points, [45.0] * len(points))
        self.assertAlmostEqual(surface.surface_area_xy, 22.0, places=6)
        shell = build_roof_shell(surface, 0.12)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])



    def test_wavefront_surface_assembles_asymmetric_weighted_v_notch(self):
        points = [
            (0.0, 0.0, 0.0), (6.0, 0.0, 0.0), (6.0, 4.0, 0.0),
            (4.0, 4.0, 0.0), (3.0, 2.0, 0.0), (2.0, 4.0, 0.0),
            (0.0, 4.0, 0.0),
        ]
        pitches = [45.0, 50.0, 42.0, 58.0, 47.0, 55.0, 48.0]
        surface = build_wavefront_roof_surface(points, pitches)
        self.assertAlmostEqual(surface.surface_area_xy, 22.0, places=6)
        self.assertEqual(len(surface.planes), len(pitches))
        shell = build_roof_shell(surface, 0.10)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])
        for face, slope_index in zip(surface.faces, surface.face_slope_indices):
            plane = surface.planes[slope_index]
            z_values = [plane.height(surface.vertices[i][0], surface.vertices[i][1])
                        for i in face]
            self.assertTrue(all(
                abs(surface.vertices[i][2] - z) < 1e-6
                for i, z in zip(face, z_values)
            ))





    def test_wavefront_surface_resolves_l_shape_cross_needle_node(self):
        points = [
            (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 1.0, 0.0),
            (1.0, 1.0, 0.0), (1.0, 4.0, 0.0), (0.0, 4.0, 0.0),
        ]
        surface = build_wavefront_roof_surface(points, [45.0] * len(points))
        self.assertAlmostEqual(surface.source_area_xy, 7.0, places=7)
        self.assertAlmostEqual(surface.surface_area_xy, 7.0, places=6)
        trace = run_weighted_wavefront(points, [45.0] * len(points))
        self.assertEqual(trace.terminal_kind, "MULTI_TERMINAL")
        terminal_arcs = [
            arc for arc in trace.skeleton_arcs
            if abs(arc.start[2] - trace.terminal_time) < 1e-8
            and abs(arc.end[2] - trace.terminal_time) < 1e-8
        ]
        self.assertEqual(len(terminal_arcs), 2)
        shell = build_roof_shell(surface, 0.10)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])



    def test_wavefront_surface_assembles_u_shape(self):
        points = [
            (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 4.0, 0.0),
            (3.0, 4.0, 0.0), (3.0, 1.0, 0.0), (1.0, 1.0, 0.0),
            (1.0, 4.0, 0.0), (0.0, 4.0, 0.0),
        ]
        surface = build_wavefront_roof_surface(points, [45.0] * len(points))
        self.assertAlmostEqual(surface.source_area_xy, 10.0, places=7)
        self.assertAlmostEqual(surface.surface_area_xy, 10.0, places=6)
        shell = build_roof_shell(surface, 0.10)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])



    def test_wavefront_surface_resolves_u_shape_multi_needle_event(self):
        points = [
            (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 4.0, 0.0),
            (3.0, 4.0, 0.0), (3.0, 1.0, 0.0), (1.0, 1.0, 0.0),
            (1.0, 4.0, 0.0), (0.0, 4.0, 0.0),
        ]
        trace = run_weighted_wavefront(points, [45.0] * len(points))
        self.assertEqual(trace.terminal_kind, "MULTI_TERMINAL")
        terminal_arcs = [
            arc for arc in trace.skeleton_arcs
            if abs(arc.start[2] - trace.terminal_time) < 1e-8
            and abs(arc.end[2] - trace.terminal_time) < 1e-8
        ]
        self.assertEqual(len(terminal_arcs), 3)
        self.assertAlmostEqual(trace.projected_facet_area, 10.0, places=6)



    def test_wavefront_surface_handles_clockwise_l_shape(self):
        points = [
            (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 1.0, 0.0),
            (1.0, 1.0, 0.0), (1.0, 4.0, 0.0), (0.0, 4.0, 0.0),
        ]
        points.reverse()
        surface = build_wavefront_roof_surface(points, [45.0] * len(points))
        self.assertAlmostEqual(surface.source_area_xy, 7.0, places=7)
        self.assertAlmostEqual(surface.surface_area_xy, 7.0, places=6)
        shell = build_roof_shell(surface, 0.10)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_wavefront_surface_preserves_nonzero_eave_elevation(self):
        base_z = 2.75
        points = [
            (0.0, 0.0, base_z), (6.0, 0.0, base_z),
            (6.0, 4.0, base_z), (4.0, 4.0, base_z),
            (3.0, 2.0, base_z), (2.0, 4.0, base_z),
            (0.0, 4.0, base_z),
        ]
        surface = build_wavefront_roof_surface(points, [45.0] * len(points))
        self.assertAlmostEqual(surface.surface_area_xy, 22.0, places=6)
        self.assertTrue(all(vertex[2] >= base_z - 1e-8 for vertex in surface.vertices))
        shell = build_roof_shell(surface, 0.12)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])



    def test_wavefront_l_shape_resolves_unequal_opposing_speeds(self):
        points = [
            (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 1.0, 0.0),
            (1.0, 1.0, 0.0), (1.0, 4.0, 0.0), (0.0, 4.0, 0.0),
        ]
        # Opposing speeds differ, while both pairs meet at the same event height.
        speeds = [0.8, 1.0, 1.2, 1.3, 1.0, 0.7]
        pitches = [math.degrees(math.atan(1.0 / speed)) for speed in speeds]
        trace = run_weighted_wavefront(points, pitches)
        self.assertEqual(trace.terminal_kind, "MULTI_TERMINAL")
        terminal_arcs = [
            arc for arc in trace.skeleton_arcs
            if abs(arc.start[2] - trace.terminal_time) < 1e-8
            and abs(arc.end[2] - trace.terminal_time) < 1e-8
        ]
        self.assertEqual(len(terminal_arcs), 2)
        surface = build_wavefront_roof_surface(points, pitches)
        self.assertAlmostEqual(surface.surface_area_xy, 7.0, places=6)
        shell = build_roof_shell(surface, 0.10)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_wavefront_u_shape_resolves_unequal_opposing_speeds(self):
        points = [
            (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 4.0, 0.0),
            (3.0, 4.0, 0.0), (3.0, 1.0, 0.0), (1.0, 1.0, 0.0),
            (1.0, 4.0, 0.0), (0.0, 4.0, 0.0),
        ]
        # Three full segment pairs coincide at the same height, but no pair
        # has to propagate at equal inward speed.
        speeds = [0.8, 0.75, 1.0, 1.25, 1.2, 1.4, 1.0, 0.6]
        pitches = [math.degrees(math.atan(1.0 / speed)) for speed in speeds]
        trace = run_weighted_wavefront(points, pitches)
        self.assertEqual(trace.terminal_kind, "MULTI_TERMINAL")
        terminal_arcs = [
            arc for arc in trace.skeleton_arcs
            if abs(arc.start[2] - trace.terminal_time) < 1e-8
            and abs(arc.end[2] - trace.terminal_time) < 1e-8
        ]
        self.assertEqual(len(terminal_arcs), 3)
        self.assertAlmostEqual(trace.projected_facet_area, 10.0, places=6)
        surface = build_wavefront_roof_surface(points, pitches)
        self.assertAlmostEqual(surface.surface_area_xy, 10.0, places=6)
        shell = build_roof_shell(surface, 0.10)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_wavefront_l_shape_handles_near_equal_opposing_speeds(self):
        points = [
            (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 1.0, 0.0),
            (1.0, 1.0, 0.0), (1.0, 4.0, 0.0), (0.0, 4.0, 0.0),
        ]
        speeds = [0.999999, 1.0, 1.000001, 1.000001, 1.0, 0.999999]
        pitches = [math.degrees(math.atan(1.0 / speed)) for speed in speeds]
        trace = run_weighted_wavefront(points, pitches)
        self.assertEqual(trace.terminal_kind, "MULTI_TERMINAL")
        self.assertEqual(len([
            arc for arc in trace.skeleton_arcs
            if abs(arc.start[2] - trace.terminal_time) < 1e-8
            and abs(arc.end[2] - trace.terminal_time) < 1e-8
        ]), 2)

    def test_wavefront_l_shape_event_order_changes_around_equal_pair_sums(self):
        points = [
            (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 1.0, 0.0),
            (1.0, 1.0, 0.0), (1.0, 4.0, 0.0), (0.0, 4.0, 0.0),
        ]

        def first_batch(speeds):
            pitches = [math.degrees(math.atan(1.0 / speed)) for speed in speeds]
            moving = build_moving_lines(points, pitches)
            edges = {line.edge_id: line for line in moving}
            loop = WavefrontLoop(0, tuple(line.edge_id for line in moving))
            candidates = collect_loop_events(loop, edges, 0.0)
            first_time = min(event.time for event in candidates)
            return [
                event for event in candidates
                if abs(event.time - first_time) <= 1e-8
            ]

        # When the right opposing pair closes first, edge 4 collapses and the
        # reflex vertex reaches the interior of target edge 5.
        right_first = first_batch([0.8, 1.0, 1.2, 1.3002, 1.0, 0.7])
        self.assertEqual(
            {event.edge_id for event in right_first if event.kind == EventKind.EDGE_COLLAPSE},
            {4},
        )
        self.assertEqual(
            {(event.vertex_id, event.target_edge_id) for event in right_first
             if event.kind == EventKind.SPLIT_CANDIDATE},
            {(3, 5)},
        )

        # When the bottom opposing pair closes first, edge 1 collapses and the
        # same reflex vertex reaches the interior of target edge 0.
        bottom_first = first_batch([0.8, 1.0, 1.2, 1.2998, 1.0, 0.7])
        self.assertEqual(
            {event.edge_id for event in bottom_first if event.kind == EventKind.EDGE_COLLAPSE},
            {1},
        )
        self.assertEqual(
            {(event.vertex_id, event.target_edge_id) for event in bottom_first
             if event.kind == EventKind.SPLIT_CANDIDATE},
            {(3, 0)},
        )

    def test_wavefront_l_shape_resolves_simultaneous_split_collapse_batches(self):
        points = [
            (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 1.0, 0.0),
            (1.0, 1.0, 0.0), (1.0, 4.0, 0.0), (0.0, 4.0, 0.0),
        ]
        scenarios = (
            # The right-side cross-needle is first: split 3 -> edge 5,
            # simultaneous with collapse of edge 4. The bottom event follows.
            ([0.8, 1.0, 1.2, 1.32, 1.0, 0.7], 5, 4),
            # The bottom cross-needle is first: split 3 -> edge 0,
            # simultaneous with collapse of edge 1. The right event follows.
            ([0.8, 1.0, 1.2, 1.28, 1.0, 0.7], 0, 1),
        )
        for speeds, expected_target, expected_collapse in scenarios:
            pitches = [math.degrees(math.atan(1.0 / speed)) for speed in speeds]
            state = create_wavefront_state(points, pitches)
            first_batch = advance_wavefront_state(state)
            self.assertIsNotNone(first_batch)
            self.assertEqual(
                {event.kind for event in first_batch.events},
                {EventKind.SPLIT_CANDIDATE, EventKind.EDGE_COLLAPSE},
            )
            split = next(
                event for event in first_batch.events
                if event.kind == EventKind.SPLIT_CANDIDATE
            )
            collapse = next(
                event for event in first_batch.events
                if event.kind == EventKind.EDGE_COLLAPSE
            )
            self.assertEqual((split.vertex_id, split.target_edge_id), (3, expected_target))
            self.assertEqual(collapse.edge_id, expected_collapse)
            self.assertEqual(len(state.loops), 1)
            self.assertTrue(state.terminal_loops)

            # A distinct later event must be generated from the surviving
            # child loop, not consumed from the original loop's event batch.
            time_after_compound = state.current_time
            live_loops_before = dict(state.loops)
            live_edges_before = dict(state.edges)
            second_batch = advance_wavefront_state(state)
            self.assertIsNotNone(second_batch)
            self.assertGreater(
                second_batch.time,
                time_after_compound + state.time_tolerance,
            )
            self.assertTrue(all(
                event.loop_id in live_loops_before
                and event.loop_generation == live_loops_before[event.loop_id].generation
                for event in second_batch.events
            ))
            self.assertTrue(all(
                edge_id in live_edges_before
                for event in second_batch.events
                for edge_id, _ in event.participant_generations
            ))

            while not state.is_complete:
                advance_wavefront_state(state)

            trace = run_weighted_wavefront(points, pitches)
            self.assertTrue(trace.is_complete)
            self.assertAlmostEqual(trace.projected_facet_area, 7.0, places=6)
            surface = build_wavefront_roof_surface(points, pitches)
            self.assertAlmostEqual(surface.surface_area_xy, 7.0, places=6)
            shell = build_roof_shell(surface, 0.10)
            self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_wavefront_resolves_symmetric_concave_point_terminations_through_64_edges(self):
        # Alternating radii create a simple concave star-like contour whose
        # weighted fronts all converge at the origin at one terminal height.
        # The event batch contains endpoint hits and edge collapses together.
        for count in (8, 16, 32, 64):
            with self.subTest(edge_count=count):
                points = []
                for index in range(count):
                    angle = 2.0 * math.pi * index / count
                    radius = 10.0 if index % 2 == 0 else 8.6
                    points.append((
                        radius * math.cos(angle),
                        radius * math.sin(angle),
                        0.0,
                    ))
                pitches = [35.0] * count

                trace = run_weighted_wavefront(points, pitches)
                self.assertTrue(trace.is_complete)
                self.assertEqual(trace.terminal_kind, "POINT")
                self.assertAlmostEqual(
                    trace.projected_facet_area,
                    abs(signed_area([(point[0], point[1]) for point in points])),
                    places=5,
                )

                surface = build_wavefront_roof_surface(points, pitches)
                self.assertAlmostEqual(
                    surface.surface_area_xy,
                    abs(signed_area([(point[0], point[1]) for point in points])),
                    places=5,
                )
                shell = build_roof_shell(surface, 0.10)
                self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_wavefront_resolves_variable_pitch_concave_contours_through_64_edges(self):
        # Asymmetric pitches break the single central-point event and force
        # the solver to process local endpoint-hit/collapse batches.
        for count in (8, 16, 32, 64):
            with self.subTest(edge_count=count):
                points = []
                pitches = []
                for index in range(count):
                    angle = 2.0 * math.pi * index / count
                    radius = 10.0 if index % 2 == 0 else 8.6
                    points.append((
                        radius * math.cos(angle),
                        radius * math.sin(angle),
                        0.0,
                    ))
                    pitches.append(
                        32.0 + 4.0 * math.sin(index * 1.371)
                        + 2.5 * math.cos(index * 0.613)
                    )

                trace = run_weighted_wavefront(points, pitches)
                self.assertTrue(trace.is_complete)
                self.assertAlmostEqual(
                    trace.projected_facet_area,
                    abs(signed_area([(point[0], point[1]) for point in points])),
                    places=5,
                )

                surface = build_wavefront_roof_surface(points, pitches)
                self.assertAlmostEqual(
                    surface.surface_area_xy,
                    abs(signed_area([(point[0], point[1]) for point in points])),
                    places=5,
                )
                self.assertEqual(
                    len(surface.face_slope_indices), len(surface.faces)
                )

                shell = build_roof_shell(surface, 0.10)
                self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_wavefront_handles_asymmetric_reflex_radial_contours_through_64_edges(self):
        # Break the exact alternating-radius symmetry while retaining a
        # simple star-shaped contour with many reflex vertices.
        for count in (16, 32, 64):
            with self.subTest(edge_count=count):
                points = []
                pitches = []
                for index in range(count):
                    angle = 2.0 * math.pi * index / count
                    base_radius = 10.0 if index % 2 == 0 else 8.6
                    radius = (
                        base_radius
                        + 0.23 * math.sin(index * 0.793)
                        + 0.17 * math.cos(index * 1.317)
                    )
                    points.append((
                        radius * math.cos(angle),
                        radius * math.sin(angle),
                        0.0,
                    ))
                    pitches.append(
                        30.0 + 5.0 * math.sin(index * 1.173)
                        + 2.0 * math.cos(index * 0.537)
                    )

                trace = run_weighted_wavefront(points, pitches)
                self.assertTrue(trace.is_complete)
                self.assertAlmostEqual(
                    trace.projected_facet_area,
                    abs(signed_area([(point[0], point[1]) for point in points])),
                    places=5,
                )
                surface = build_wavefront_roof_surface(points, pitches)
                self.assertAlmostEqual(
                    surface.surface_area_xy,
                    abs(signed_area([(point[0], point[1]) for point in points])),
                    places=5,
                )
                self.assertEqual(len(surface.face_slope_indices), len(surface.faces))
                shell = build_roof_shell(surface, 0.10)
                self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_wavefront_handles_64_edge_wavy_l_contour_with_variable_pitch(self):
        outline = [
            (0.0, 0.0), (10.0, 0.0), (10.0, 3.0),
            (4.0, 3.0), (4.0, 10.0), (0.0, 10.0),
        ]
        subdivisions = (11, 11, 10, 11, 10, 11)
        points = []
        for edge_index, start in enumerate(outline):
            end = outline[(edge_index + 1) % len(outline)]
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length = math.hypot(dx, dy)
            left_normal = (-dy / length, dx / length)
            for step in range(subdivisions[edge_index]):
                t = step / subdivisions[edge_index]
                bend = 0.015 * math.sin(math.pi * t)
                points.append((
                    start[0] + dx * t + left_normal[0] * bend,
                    start[1] + dy * t + left_normal[1] * bend,
                    0.0,
                ))

        self.assertEqual(len(points), 64)
        pitches = [
            30.0 + 5.0 * math.sin(index * 0.817)
            + 2.0 * math.cos(index * 0.613)
            for index in range(len(points))
        ]
        trace = run_weighted_wavefront(points, pitches)
        self.assertTrue(trace.is_complete)
        self.assertAlmostEqual(
            trace.projected_facet_area,
            abs(signed_area([(point[0], point[1]) for point in points])),
            places=5,
        )

        surface = build_wavefront_roof_surface(points, pitches)
        self.assertAlmostEqual(
            surface.surface_area_xy,
            abs(signed_area([(point[0], point[1]) for point in points])),
            places=5,
        )
        self.assertEqual(len(surface.face_slope_indices), len(surface.faces))
        shell = build_roof_shell(surface, 0.10)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_wavefront_handles_64_edge_wavy_u_contour_with_variable_pitch(self):
        outline = [
            (0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (3.0, 4.0),
            (3.0, 1.0), (1.0, 1.0), (1.0, 4.0), (0.0, 4.0),
        ]
        points = []
        for edge_index, start in enumerate(outline):
            end = outline[(edge_index + 1) % len(outline)]
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length = math.hypot(dx, dy)
            left_normal = (-dy / length, dx / length)
            for step in range(8):
                t = step / 8.0
                bend = 0.008 * math.sin(math.pi * t)
                points.append((
                    start[0] + dx * t + left_normal[0] * bend,
                    start[1] + dy * t + left_normal[1] * bend,
                    0.0,
                ))

        self.assertEqual(len(points), 64)
        pitches = [
            31.0 + 4.5 * math.sin(index * 0.917)
            + 2.5 * math.cos(index * 0.641)
            for index in range(len(points))
        ]
        trace = run_weighted_wavefront(points, pitches)
        self.assertTrue(trace.is_complete)
        self.assertAlmostEqual(
            trace.projected_facet_area,
            abs(signed_area([(point[0], point[1]) for point in points])),
            places=5,
        )
        surface = build_wavefront_roof_surface(points, pitches)
        self.assertAlmostEqual(
            surface.surface_area_xy,
            abs(signed_area([(point[0], point[1]) for point in points])),
            places=5,
        )
        self.assertEqual(len(surface.face_slope_indices), len(surface.faces))
        shell = build_roof_shell(surface, 0.10)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_wavefront_keeps_small_resolvable_split_collapse_sliver_in_shell(self):
        points = [
            (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 1.0, 0.0),
            (1.0, 1.0, 0.0), (1.0, 4.0, 0.0), (0.0, 4.0, 0.0),
        ]
        # This produces a small but locally resolved terminal facet. Its area
        # is small relative to the whole roof, not relative to its own edges.
        speeds = [0.8, 1.0, 1.2, 1.3002, 1.0, 0.7]
        pitches = [math.degrees(math.atan(1.0 / speed)) for speed in speeds]
        surface = build_wavefront_roof_surface(points, pitches)
        self.assertAlmostEqual(surface.surface_area_xy, 7.0, places=6)
        shell = build_roof_shell(surface, 0.10)
        self.assertEqual(validate_closed_mesh(shell.vertices, shell.faces), [])

    def test_wavefront_rejects_partial_overlap_as_complete_needle(self):
        points = [
            (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 1.0, 0.0),
            (1.0, 1.0, 0.0), (1.0, 4.0, 0.0), (0.0, 4.0, 0.0),
        ]
        speeds = [0.8, 1.0, 1.2, 1.3002, 1.0, 0.7]
        pitches = [math.degrees(math.atan(1.0 / speed)) for speed in speeds]
        state = create_wavefront_state(points, pitches)
        loop = state.loops[0]
        state.current_time = 1.0 / (speeds[3] + speeds[5])
        fake_collapse_batch = tuple(
            WavefrontEvent(EventKind.EDGE_COLLAPSE, state.current_time, loop.loop_id,
                           edge_id=edge_id)
            for edge_id in (0, 1, 2, 4)
        )
        with self.assertRaises(GeometryInputError) as ctx:
            _resolve_edge_collapse_group(state, loop, fake_collapse_batch)
        self.assertEqual(ctx.exception.code, "PARTIAL_OVERLAP_NEEDLE_UNRESOLVED")


if __name__ == "__main__":
    unittest.main()
