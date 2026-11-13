"""End-to-end Python/Rust weighted-wavefront and roof-surface benchmark."""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import wavefront


def fixture(count: int = 64):
    points = []
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        radius = 10.0 if index % 2 == 0 else 8.6
        points.append((radius * math.cos(angle), radius * math.sin(angle), 0.0))
    pitches = [
        32.0 + 4.0 * math.sin(index * 1.371)
        + 2.5 * math.cos(index * 0.613)
        for index in range(count)
    ]
    return points, pitches


def run_with_collector(collector, operation):
    original = wavefront.collect_loop_events
    wavefront.collect_loop_events = collector
    try:
        return operation()
    finally:
        wavefront.collect_loop_events = original


def assert_close(first: float, second: float, tolerance: float = 1.0e-12):
    if abs(first - second) > tolerance:
        raise RuntimeError(f"Python/Rust parity mismatch: {first!r} != {second!r}")


def assert_trace_parity(expected, actual):
    if (
        expected.terminal_kind != actual.terminal_kind
        or expected.input_winding != actual.input_winding
        or len(expected.events) != len(actual.events)
        or len(expected.facets) != len(actual.facets)
        or len(expected.skeleton_arcs) != len(actual.skeleton_arcs)
    ):
        raise RuntimeError("Python/Rust wavefront trace topology mismatch.")

    assert_close(expected.terminal_time, actual.terminal_time)
    assert_close(expected.source_area, actual.source_area, 1.0e-10)
    assert_close(expected.projected_facet_area, actual.projected_facet_area, 1.0e-10)

    for first, second in zip(expected.events, actual.events):
        if (
            first.kind != second.kind
            or first.loop_id != second.loop_id
            or first.edge_id != second.edge_id
            or first.vertex_id != second.vertex_id
            or first.target_edge_id != second.target_edge_id
            or first.participant_generations != second.participant_generations
            or first.loop_generation != second.loop_generation
            or (first.position is None) != (second.position is None)
        ):
            raise RuntimeError("Python/Rust event sequence mismatch.")
        assert_close(first.time, second.time)
        if first.position is not None:
            assert_close(first.position[0], second.position[0])
            assert_close(first.position[1], second.position[1])

    for first, second in zip(expected.facets, actual.facets):
        if first.source_edge_id != second.source_edge_id or len(first.vertices) != len(second.vertices):
            raise RuntimeError("Python/Rust facet topology mismatch.")
        assert_close(first.start_time, second.start_time)
        assert_close(first.end_time, second.end_time)
        for point_a, point_b in zip(first.vertices, second.vertices):
            for value_a, value_b in zip(point_a, point_b):
                assert_close(value_a, value_b)

    for first, second in zip(expected.skeleton_arcs, actual.skeleton_arcs):
        assert_close(first.event_time, second.event_time)
        for point_a, point_b in ((first.start, second.start), (first.end, second.end)):
            for value_a, value_b in zip(point_a, point_b):
                assert_close(value_a, value_b)


def assert_surface_parity(expected, actual):
    if (
        expected.faces != actual.faces
        or expected.face_slope_indices != actual.face_slope_indices
        or len(expected.vertices) != len(actual.vertices)
    ):
        raise RuntimeError("Python/Rust assembled roof mesh topology mismatch.")
    for point_a, point_b in zip(expected.vertices, actual.vertices):
        for value_a, value_b in zip(point_a, point_b):
            assert_close(value_a, value_b)
    assert_close(expected.source_area_xy, actual.source_area_xy, 1.0e-10)
    assert_close(expected.surface_area_xy, actual.surface_area_xy, 1.0e-10)


def measure(collector, operation, repeats: int = 5) -> float:
    values = []
    for _ in range(repeats):
        started = time.perf_counter()
        run_with_collector(collector, operation)
        values.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(values)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if not 3 <= args.repeats <= 15:
        raise SystemExit("--repeats must be between 3 and 15")

    from core.native_bridge import NATIVE_WAVEFRONT_EVENTS_AVAILABLE
    if not NATIVE_WAVEFRONT_EVENTS_AVAILABLE:
        raise SystemExit("The Rust wavefront event collector is not installed.")

    points, pitches = fixture(64)
    python_collector = wavefront._collect_loop_events_python
    rust_dispatch = wavefront.collect_loop_events

    python_trace = run_with_collector(
        python_collector,
        lambda: wavefront.run_weighted_wavefront(points, pitches),
    )
    rust_trace = run_with_collector(
        rust_dispatch,
        lambda: wavefront.run_weighted_wavefront(points, pitches),
    )
    assert_trace_parity(python_trace, rust_trace)

    python_surface = run_with_collector(
        python_collector,
        lambda: wavefront.build_wavefront_roof_surface(points, pitches),
    )
    rust_surface = run_with_collector(
        rust_dispatch,
        lambda: wavefront.build_wavefront_roof_surface(points, pitches),
    )
    assert_surface_parity(python_surface, rust_surface)

    measurements = []
    for label, operation in (
        ("weighted_wavefront_trace_64", lambda: wavefront.run_weighted_wavefront(points, pitches)),
        ("weighted_wavefront_surface_64", lambda: wavefront.build_wavefront_roof_surface(points, pitches)),
    ):
        python_ms = measure(python_collector, operation, args.repeats)
        rust_ms = measure(rust_dispatch, operation, args.repeats)
        measurements.append({
            "case": label,
            "vertices_in": len(points),
            "vertices_out": len(getattr(rust_surface, "vertices", ())) if "surface" in label else None,
            "faces_out": len(getattr(rust_surface, "faces", ())) if "surface" in label else None,
            "python_ms": round(python_ms, 3),
            "rust_dispatch_ms": round(rust_ms, 3),
            "speedup": round(python_ms / rust_ms, 3) if rust_ms else None,
        })

    report = {
        "fixture": "64-vertex alternating-radius concave contour with variable per-edge pitch",
        "parity": "full event sequence, wavefront facets, skeleton arcs, welded surface faces and vertices",
        "repeats": args.repeats,
        "timing_unit": "milliseconds",
        "results": measurements,
    }
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.json_output:
        args.json_output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
