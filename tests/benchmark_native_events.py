"""Benchmark batched Python/Rust weighted-wavefront event collection."""
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

from core.native_bridge import NATIVE_WAVEFRONT_EVENTS_AVAILABLE
from core.wavefront import (
    WavefrontLoop,
    _collect_loop_events_python,
    build_moving_lines,
    collect_loop_events,
)


def fixture(count: int):
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
    lines = build_moving_lines(points, pitches)
    edges = {line.edge_id: line for line in lines}
    loop = WavefrontLoop(1, tuple(line.edge_id for line in lines))
    return loop, edges


def measure(function, iterations: int, repeats: int = 7) -> float:
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        for _ in range(iterations):
            function()
        samples.append((time.perf_counter() - started) * 1000.0 / iterations)
    return statistics.median(samples)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    if not NATIVE_WAVEFRONT_EVENTS_AVAILABLE:
        raise SystemExit("The Rust wavefront event collector is not installed.")

    results = []
    for count in (16, 32, 48, 64):
        loop, edges = fixture(count)
        python_function = lambda: _collect_loop_events_python(loop, edges, 0.0)
        native_function = lambda: collect_loop_events(loop, edges, 0.0)

        expected = python_function()
        actual = native_function()
        if len(actual) != len(expected):
            raise RuntimeError(f"Event count mismatch for {count} edges.")
        for first, second in zip(actual, expected):
            if (
                first.kind != second.kind
                or abs(first.time - second.time) > 1e-12
                or first.edge_id != second.edge_id
                or first.vertex_id != second.vertex_id
                or first.target_edge_id != second.target_edge_id
                or first.participant_generations != second.participant_generations
            ):
                raise RuntimeError(f"Event parity mismatch for {count} edges.")

        iterations = max(10, min(500, 12000 // count))
        python_ms = measure(python_function, iterations)
        native_ms = measure(native_function, iterations)
        results.append({
            "edges": count,
            "events": len(expected),
            "iterations_per_sample": iterations,
            "python_ms_per_call": round(python_ms, 6),
            "rust_dispatch_ms_per_call": round(native_ms, 6),
            "speedup": round(python_ms / native_ms, 3) if native_ms else None,
        })

    report = {
        "native_wavefront_events_available": True,
        "timing_unit": "milliseconds_per_loop_event_collection",
        "method": "median of 7 samples; each sample averages repeated event-collection calls",
        "results": results,
    }
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.json_output:
        args.json_output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
