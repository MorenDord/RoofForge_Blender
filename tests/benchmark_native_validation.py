"""Compare the optional Rust contour validator with its Python reference."""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path

from core.geometry import _validate_simple_polygon_python, validate_simple_polygon
from core.native_bridge import (
    NATIVE_BACKEND_AVAILABLE,
    validate_simple_polygon_native,
)


def radial_polygon(count: int):
    result = []
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        radius = 10.0 + 0.07 * math.sin(7.0 * angle) + 0.03 * math.cos(11.0 * angle)
        result.append((radius * math.cos(angle), radius * math.sin(angle)))
    return result


def measure(function, points, iterations: int, repeats: int = 7) -> float:
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        for _iteration in range(iterations):
            function(points)
        samples.append((time.perf_counter() - start) * 1000.0 / iterations)
    return statistics.median(samples)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    if not NATIVE_BACKEND_AVAILABLE:
        raise SystemExit("Rust extension is not installed; build and install its wheel first.")

    results = []
    for count in (16, 32, 48, 64, 96, 128, 256):
        points = radial_polygon(count)
        iterations = max(10, min(200, 25_000 // (count * count)))
        python_ms = measure(_validate_simple_polygon_python, points, iterations)
        native_ms = measure(validate_simple_polygon_native, points, iterations)
        dispatch_ms = measure(validate_simple_polygon, points, iterations)
        results.append({
            "vertices": count,
            "iterations_per_sample": iterations,
            "python_ms_per_call": round(python_ms, 6),
            "native_ms_per_call": round(native_ms, 6),
            "dispatch_ms_per_call": round(dispatch_ms, 6),
            "native_speedup": round(python_ms / native_ms, 3) if native_ms else None,
            "dispatch_speedup": round(python_ms / dispatch_ms, 3) if dispatch_ms else None,
        })

    report = {
        "native_backend_available": NATIVE_BACKEND_AVAILABLE,
        "timing_unit": "milliseconds_per_validation",
        "method": "median of 7 samples; each sample is an average over repeated calls",
        "results": results,
    }
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.json_output:
        args.json_output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
