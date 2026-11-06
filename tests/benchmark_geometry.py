"""Reproducible geometry performance baseline for RoofForge.

Run from the repository root:
    python tests/benchmark_geometry.py --json-output benchmark-results.json

This is an opt-in benchmark, not a correctness test. Unsupported fixtures are
recorded as errors rather than hidden; all timings use the same Python runner.
"""
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

from core.geometry import validate_simple_polygon
from core.mesh import build_roof_surface
from core.distance_field import build_distance_field_roof_surface
from core.wavefront import run_weighted_wavefront


def radial_polygon(count: int, *, concave: bool) -> list[tuple[float, float, float]]:
    points = []
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        if concave:
            radius = 10.0 if index % 2 == 0 else 8.6
        else:
            radius = 10.0 * (
                1.0
                + 0.0015 * math.sin(7.0 * angle)
                + 0.0008 * math.cos(11.0 * angle)
            )
        points.append((radius * math.cos(angle), radius * math.sin(angle), 0.0))
    issues = validate_simple_polygon([(p[0], p[1]) for p in points])
    if issues:
        raise RuntimeError(f"Generated benchmark polygon is invalid: {issues[0].message}")
    return points


def percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def measure(label: str, points, builder, repeats: int) -> dict:
    pitches = [35.0] * len(points)
    durations = []
    output = None
    try:
        for _ in range(repeats):
            start = time.perf_counter()
            output = builder(points, pitches)
            durations.append((time.perf_counter() - start) * 1000.0)
        return {
            "case": label,
            "status": "ok",
            "vertices_in": len(points),
            "median_ms": round(statistics.median(durations), 3),
            "p95_ms": round(percentile_95(durations), 3),
            "vertices_out": len(getattr(output, "vertices", ())),
            "faces_out": len(getattr(output, "faces", ())),
        }
    except Exception as exc:  # Keep unsupported geometry visible in the report.
        return {
            "case": label,
            "status": "error",
            "vertices_in": len(points),
            "error": f"{type(exc).__name__}: {exc}",
            "median_ms": None,
            "p95_ms": None,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1 or args.repeats > 20:
        raise SystemExit("--repeats must be between 1 and 20")

    results = []
    for count in (8, 16, 32, 64, 128):
        convex = radial_polygon(count, concave=False)
        results.append(measure(
            f"convex_lower_envelope_n{count}",
            convex,
            build_roof_surface,
            args.repeats,
        ))
        results.append(measure(
            f"weighted_wavefront_convex_n{count}",
            convex,
            run_weighted_wavefront,
            args.repeats,
        ))

    for count in (8, 16, 32, 64):
        concave = radial_polygon(count, concave=True)
        results.append(measure(
            f"distance_field_uniform_refine_depth2_concave_n{count}",
            concave,
            lambda points, pitches: build_distance_field_roof_surface(
                points, pitches, height_tolerance=1e-6, max_depth=2
            ),
            args.repeats,
        ))

    report = {
        "python": __import__("sys").version,
        "repeats": args.repeats,
        "timing_unit": "milliseconds",
        "results": results,
    }
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    print(rendered)
    if args.json_output:
        args.json_output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
