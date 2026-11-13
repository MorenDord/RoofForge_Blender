"""Differential tests for the optional Rust geometry extension."""
from __future__ import annotations

import math
import random
import unittest

from core import wavefront as wavefront_module
from core.geometry import (
    _validate_simple_polygon_python,
    validate_simple_polygon,
)
from core.native_bridge import (
    NATIVE_BACKEND_AVAILABLE,
    NATIVE_FACE_CONFORMANCE_AVAILABLE,
    NATIVE_VERTEX_WELD_AVAILABLE,
    NATIVE_WAVEFRONT_EVENTS_AVAILABLE,
    NATIVE_WAVEFRONT_INTERVAL_AVAILABLE,
    record_wavefront_interval_native,
    split_face_edges_at_shared_vertices_native,
    validate_simple_polygon_native,
    weld_vertices_batch_native,
)
from core.wavefront import (
    WavefrontLoop,
    _collect_loop_events_python,
    _record_wavefront_interval,
    _record_wavefront_interval_python,
    build_moving_lines,
    collect_loop_events,
    create_wavefront_state,
)


def _diagnostic_tuples(items):
    return [(item.code, item.message, item.severity) for item in items]


def _radial_polygon(count: int):
    points = []
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        radius = 10.0 + 0.07 * math.sin(7.0 * angle) + 0.03 * math.cos(11.0 * angle)
        points.append((radius * math.cos(angle), radius * math.sin(angle)))
    return points


@unittest.skipUnless(NATIVE_BACKEND_AVAILABLE, "Rust extension wheel is not installed")
class TestRustGeometryParity(unittest.TestCase):
    def test_native_api_matches_python_for_fixed_cases(self):
        fixtures = [
            [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)],
            [(0.0, 1.0), (2.0, 1.0), (2.0, 0.0), (0.0, 0.0)],
            [(0.0, 0.0), (8.0, 0.0), (8.0, 4.0), (4.0, 4.0),
             (4.0, 8.0), (0.0, 8.0)],
            [(0.0, 0.0), (2.0, 2.0), (0.0, 2.0), (2.0, 0.0)],
            [(0.0, 0.0), (1.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
            [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)],
            [(0.0, 0.0), (float("nan"), 0.0), (0.0, 1.0)],
            [(0.0, 0.0), (1.0, 0.0)],
        ]

        for points in fixtures:
            with self.subTest(points=points):
                expected = _diagnostic_tuples(
                    _validate_simple_polygon_python(points)
                )
                actual = validate_simple_polygon_native(points)
                self.assertIsNotNone(actual)
                self.assertEqual(actual, expected)

    def test_native_api_matches_python_for_deterministic_generated_contours(self):
        rng = random.Random(917_204)
        fixtures = [_radial_polygon(count) for count in (24, 32, 48, 64, 96)]

        for count in (24, 40, 72):
            angles = sorted(rng.random() * 2.0 * math.pi for _ in range(count))
            fixtures.append([
                (
                    (5.0 + rng.random() * 4.0) * math.cos(angle),
                    (5.0 + rng.random() * 4.0) * math.sin(angle),
                )
                for angle in angles
            ])

        for points in fixtures:
            with self.subTest(count=len(points)):
                expected = _diagnostic_tuples(
                    _validate_simple_polygon_python(points)
                )
                actual = validate_simple_polygon_native(points)
                self.assertEqual(actual, expected)

    def test_production_dispatch_uses_a_parity_checked_native_path(self):
        points = _radial_polygon(48)
        expected = _validate_simple_polygon_python(points)
        actual = validate_simple_polygon(points)
        self.assertEqual(_diagnostic_tuples(actual), _diagnostic_tuples(expected))




@unittest.skipUnless(
    NATIVE_VERTEX_WELD_AVAILABLE,
    "Rust vertex-welding kernel is not installed",
)
class TestRustVertexWelding(unittest.TestCase):
    @staticmethod
    def _python_weld(points, tolerance):
        from core.mesh import _VertexRegistry

        registry = _VertexRegistry(tolerance)
        indices = [registry.add(point) for point in points]
        return tuple(registry.vertices), tuple(indices)

    def _assert_parity(self, points, tolerance):
        expected_vertices, expected_indices = self._python_weld(points, tolerance)
        actual_vertices, actual_indices = weld_vertices_batch_native(points, tolerance)
        self.assertEqual(actual_indices, expected_indices)
        self.assertEqual(len(actual_vertices), len(expected_vertices))
        for actual, expected in zip(actual_vertices, expected_vertices):
            for a, b in zip(actual, expected):
                self.assertEqual(a, b)

    def test_nearby_and_negative_points_preserve_first_seen_order(self):
        points = [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.5, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            (-0.0000005, 0.0, 0.0),
            (0.0, 1.0, 0.0),
        ]
        self._assert_parity(points, 1.0e-6)

    def test_generated_point_batches_match_python_spatial_hash(self):
        rng = random.Random(61_901)
        for case in range(20):
            tolerance = (case + 1) * 1.0e-7
            points = []
            for index in range(500):
                anchor = (
                    float(rng.randrange(-20, 21)),
                    float(rng.randrange(-20, 21)),
                    float(rng.randrange(-20, 21)),
                )
                jitter = tolerance * rng.uniform(-0.95, 0.95)
                points.append((
                    anchor[0] + jitter,
                    anchor[1] - jitter * 0.5,
                    anchor[2] + jitter * 0.25,
                ))
                if index % 4 == 0:
                    points.append(points[-1])
            with self.subTest(case=case, tolerance=tolerance):
                self._assert_parity(points, tolerance)


@unittest.skipUnless(
    NATIVE_FACE_CONFORMANCE_AVAILABLE,
    "Rust face-conformance kernel is not installed",
)
class TestRustMeshConformance(unittest.TestCase):
    def test_t_junction_splitting_matches_python_reference(self):
        vertices = [
            (0.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (2.0, 1.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 0.5, 0.0),
            (1.0, 0.5, 1.0e-7),
        ]
        faces = [
            (0, 1, 2, 5),
            (0, 3, 4, 5),
            (3, 1, 2, 4),
        ]
        for tolerance in (1.0e-9, 1.0e-6):
            with self.subTest(tolerance=tolerance):
                expected = wavefront_module._split_face_edges_at_shared_vertices(
                    vertices, faces, tolerance
                )
                actual = split_face_edges_at_shared_vertices_native(
                    vertices, faces, tolerance
                )
                self.assertEqual([tuple(face) for face in actual], [tuple(face) for face in expected])

    def test_native_conformance_matches_python_on_deterministic_generated_meshes(self):
        rng = random.Random(917_203)
        for case in range(30):
            vertices = []
            for index in range(18):
                vertices.append((
                    float(index % 6),
                    float(index // 6),
                    rng.uniform(-1.0e-8, 1.0e-8),
                ))
            faces = [
                (0, 5, 17, 12),
                (0, 2, 14, 12),
                (2, 5, 17, 14),
                (1, 4, 16, 13),
            ]
            tolerance = (1.0 + (case % 3)) * 1.0e-7
            expected = wavefront_module._split_face_edges_at_shared_vertices(
                vertices, faces, tolerance
            )
            actual = split_face_edges_at_shared_vertices_native(
                vertices, faces, tolerance
            )
            self.assertEqual([tuple(face) for face in actual], [tuple(face) for face in expected])


@unittest.skipUnless(
    NATIVE_WAVEFRONT_INTERVAL_AVAILABLE,
    "Rust interval recorder is not installed",
)
class TestRustWavefrontInterval(unittest.TestCase):
    def test_native_interval_record_matches_python_for_initial_loop(self):
        points = [
            (0.0, 0.0, 0.0),
            (8.0, 0.0, 0.0),
            (8.0, 6.0, 0.0),
            (0.0, 6.0, 0.0),
        ]
        pitches = [30.0, 35.0, 40.0, 32.0]
        python_state = create_wavefront_state(points, pitches)
        native_state = create_wavefront_state(points, pitches)
        start = python_state.current_time
        end = start + 0.05

        _record_wavefront_interval_python(python_state, start, end)
        _record_wavefront_interval(native_state, start, end)

        self.assertEqual(python_state.skeleton_arcs, native_state.skeleton_arcs)
        self.assertEqual(len(python_state.facets), len(native_state.facets))
        for expected, actual in zip(python_state.facets, native_state.facets):
            self.assertEqual(expected.source_edge_id, actual.source_edge_id)
            self.assertEqual(expected.start_time, actual.start_time)
            self.assertEqual(expected.end_time, actual.end_time)
            self.assertEqual(len(expected.vertices), len(actual.vertices))
            for point_a, point_b in zip(expected.vertices, actual.vertices):
                for value_a, value_b in zip(point_a, point_b):
                    self.assertAlmostEqual(value_a, value_b, delta=1.0e-12)

    def test_native_interval_handles_multiple_loops_in_sorted_order(self):
        points = [
            (0.0, 0.0, 0.0),
            (8.0, 0.0, 0.0),
            (8.0, 6.0, 0.0),
            (0.0, 6.0, 0.0),
        ]
        pitches = [30.0, 35.0, 40.0, 32.0]
        python_state = create_wavefront_state(points, pitches)
        native_state = create_wavefront_state(points, pitches)

        original_loop = python_state.loops[0]
        original_edges = dict(python_state.edges)
        added_edges = {}
        offset = max(original_edges) + 1
        for line in original_edges.values():
            added_edges[offset + line.edge_id] = type(line)(
                edge_id=offset + line.edge_id,
                source_edge_id=line.source_edge_id,
                normal=line.normal,
                offset=line.offset,
                speed=line.speed,
                tangent=line.tangent,
                generation=line.generation,
                base_height=line.base_height,
            )
        second_loop = WavefrontLoop(4, tuple(added_edges), generation=0)
        for state in (python_state, native_state):
            state.loops[8] = WavefrontLoop(8, original_loop.edge_ids, generation=2)
            state.loops[4] = second_loop
            state.edges.update(added_edges)

        for state, recorder in (
            (python_state, _record_wavefront_interval_python),
            (native_state, _record_wavefront_interval),
        ):
            recorder(state, 0.0, 0.05)

        self.assertEqual(python_state.skeleton_arcs, native_state.skeleton_arcs)
        self.assertEqual(python_state.facets, native_state.facets)


@unittest.skipUnless(
    NATIVE_WAVEFRONT_EVENTS_AVAILABLE,
    "Rust wavefront event collector is not installed",
)
class TestRustWavefrontParity(unittest.TestCase):
    @staticmethod
    def _fixture(count: int, clockwise: bool = False):
        points = []
        for index in range(count):
            angle = 2.0 * math.pi * index / count
            radius = 10.0 if index % 2 == 0 else 8.6
            points.append((radius * math.cos(angle), radius * math.sin(angle), 0.0))
        if clockwise:
            points.reverse()
        pitches = [
            32.0 + 4.0 * math.sin(index * 1.371)
            + 2.5 * math.cos(index * 0.613)
            for index in range(count)
        ]
        return points, pitches

    def _assert_event_parity(self, count: int, clockwise: bool = False):
        points, pitches = self._fixture(count, clockwise)
        lines = build_moving_lines(points, pitches)
        edges = {line.edge_id: line for line in lines}
        loop = WavefrontLoop(7, tuple(line.edge_id for line in lines), generation=3)

        expected = _collect_loop_events_python(loop, edges, time=0.0, eps=1e-9)
        actual = collect_loop_events(loop, edges, time=0.0, eps=1e-9)
        self.assertEqual(len(actual), len(expected))

        for native_event, python_event in zip(actual, expected):
            self.assertEqual(native_event.kind, python_event.kind)
            self.assertAlmostEqual(native_event.time, python_event.time, delta=1e-12)
            self.assertEqual(
                (
                    native_event.loop_id,
                    native_event.edge_id,
                    native_event.vertex_id,
                    native_event.target_edge_id,
                ),
                (
                    python_event.loop_id,
                    python_event.edge_id,
                    python_event.vertex_id,
                    python_event.target_edge_id,
                ),
            )
            self.assertAlmostEqual(native_event.position[0], python_event.position[0], delta=1e-12)
            self.assertAlmostEqual(native_event.position[1], python_event.position[1], delta=1e-12)
            self.assertEqual(
                native_event.participant_generations,
                python_event.participant_generations,
            )
            self.assertEqual(native_event.loop_generation, python_event.loop_generation)

    def test_native_events_match_python_for_concave_variable_pitch_loops(self):
        for count in (16, 32, 48, 64):
            with self.subTest(vertices=count):
                self._assert_event_parity(count)

    def test_native_events_match_python_for_clockwise_contour(self):
        self._assert_event_parity(32, clockwise=True)

    def test_native_events_match_python_for_small_active_loops(self):
        for count in range(3, 16):
            with self.subTest(vertices=count):
                self._assert_event_parity(count)


    @staticmethod
    def _run_with_collector(collector, operation, interval_recorder=None):
        original = wavefront_module.collect_loop_events
        original_interval = wavefront_module._record_wavefront_interval
        wavefront_module.collect_loop_events = collector
        if interval_recorder is not None:
            wavefront_module._record_wavefront_interval = interval_recorder
        try:
            return operation()
        finally:
            wavefront_module.collect_loop_events = original
            wavefront_module._record_wavefront_interval = original_interval

    def _assert_trace_parity(self, expected, actual):
        self.assertEqual(expected.terminal_kind, actual.terminal_kind)
        self.assertEqual(expected.input_winding, actual.input_winding)
        self.assertEqual(len(expected.events), len(actual.events))
        self.assertEqual(len(expected.facets), len(actual.facets))
        self.assertEqual(len(expected.skeleton_arcs), len(actual.skeleton_arcs))
        self.assertAlmostEqual(expected.terminal_time, actual.terminal_time, delta=1e-12)
        self.assertAlmostEqual(expected.source_area, actual.source_area, delta=1e-10)
        self.assertAlmostEqual(expected.projected_facet_area, actual.projected_facet_area, delta=1e-10)

        for first, second in zip(expected.events, actual.events):
            self.assertEqual(
                (
                    first.kind, first.loop_id, first.edge_id, first.vertex_id,
                    first.target_edge_id, first.participant_generations,
                    first.loop_generation,
                ),
                (
                    second.kind, second.loop_id, second.edge_id, second.vertex_id,
                    second.target_edge_id, second.participant_generations,
                    second.loop_generation,
                ),
            )
            self.assertAlmostEqual(first.time, second.time, delta=1e-12)
            self.assertEqual(first.position is None, second.position is None)
            if first.position is not None:
                self.assertAlmostEqual(first.position[0], second.position[0], delta=1e-12)
                self.assertAlmostEqual(first.position[1], second.position[1], delta=1e-12)

        for first, second in zip(expected.facets, actual.facets):
            self.assertEqual(first.source_edge_id, second.source_edge_id)
            self.assertAlmostEqual(first.start_time, second.start_time, delta=1e-12)
            self.assertAlmostEqual(first.end_time, second.end_time, delta=1e-12)
            self.assertEqual(len(first.vertices), len(second.vertices))
            for point_a, point_b in zip(first.vertices, second.vertices):
                for value_a, value_b in zip(point_a, point_b):
                    self.assertAlmostEqual(value_a, value_b, delta=1e-12)

        for first, second in zip(expected.skeleton_arcs, actual.skeleton_arcs):
            self.assertAlmostEqual(first.event_time, second.event_time, delta=1e-12)
            for point_a, point_b in ((first.start, second.start), (first.end, second.end)):
                for value_a, value_b in zip(point_a, point_b):
                    self.assertAlmostEqual(value_a, value_b, delta=1e-12)

    def test_full_weighted_wavefront_trace_and_surface_match_python(self):
        points, pitches = self._fixture(64)
        python_collector = wavefront_module._collect_loop_events_python
        native_collector = wavefront_module.collect_loop_events

        python_trace = self._run_with_collector(
            python_collector,
            lambda: wavefront_module.run_weighted_wavefront(points, pitches),
            _record_wavefront_interval_python,
        )
        native_trace = self._run_with_collector(
            native_collector,
            lambda: wavefront_module.run_weighted_wavefront(points, pitches),
            _record_wavefront_interval,
        )
        self._assert_trace_parity(python_trace, native_trace)

        python_surface = self._run_with_collector(
            python_collector,
            lambda: wavefront_module.build_wavefront_roof_surface(points, pitches),
            _record_wavefront_interval_python,
        )
        native_surface = self._run_with_collector(
            native_collector,
            lambda: wavefront_module.build_wavefront_roof_surface(points, pitches),
            _record_wavefront_interval,
        )
        self.assertEqual(python_surface.faces, native_surface.faces)
        self.assertEqual(python_surface.face_slope_indices, native_surface.face_slope_indices)
        self.assertEqual(len(python_surface.vertices), len(native_surface.vertices))
        for point_a, point_b in zip(python_surface.vertices, native_surface.vertices):
            for value_a, value_b in zip(point_a, point_b):
                self.assertAlmostEqual(value_a, value_b, delta=1e-12)
        self.assertAlmostEqual(
            python_surface.source_area_xy, native_surface.source_area_xy, delta=1e-10
        )
        self.assertAlmostEqual(
            python_surface.surface_area_xy, native_surface.surface_area_xy, delta=1e-10
        )


if __name__ == "__main__":
    unittest.main()
