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
from core.wavefront import run_weighted_wavefront, build_wavefront_roof_surface


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


def wavy_outline(
    outline: list[tuple[float, float]],
    subdivisions: list[int],
    amplitude: float,
    z_amplitude: float = 0.0,
) -> list[tuple[float, float, float]]:
    points = []
    for edge_index, start in enumerate(outline):
        end = outline[(edge_index + 1) % len(outline)]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        normal = (-dy / length, dx / length)
        for step in range(subdivisions[edge_index]):
            t = step / subdivisions[edge_index]
            bend = amplitude * math.sin(math.pi * t)
            point_index = len(points)
            z = z_amplitude * math.sin(
                2.0 * math.pi * point_index / sum(subdivisions)
            )
            points.append((
                start[0] + dx * t + normal[0] * bend,
                start[1] + dy * t + normal[1] * bend,
                z,
            ))
    issues = validate_simple_polygon([(p[0], p[1]) for p in points])
    if issues:
        raise RuntimeError(f"Generated wavy outline is invalid: {issues[0].message}")
    return points


def wavy_l_fixture() -> list[tuple[float, float, float]]:
    return wavy_outline(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 3.0),
         (4.0, 3.0), (4.0, 10.0), (0.0, 10.0)],
        [11, 11, 10, 11, 10, 11],
        0.015,
    )


def wavy_u_fixture() -> list[tuple[float, float, float]]:
    return wavy_outline(
        [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (3.0, 4.0),
         (3.0, 1.0), (1.0, 1.0), (1.0, 4.0), (0.0, 4.0)],
        [8] * 8,
        0.008,
    )


def l_pitch_profile(count: int) -> list[float]:
    return [
        30.0 + 5.0 * math.sin(index * 0.817)
        + 2.0 * math.cos(index * 0.613)
        for index in range(count)
    ]


def u_pitch_profile(count: int) -> list[float]:
    return [
        31.0 + 4.5 * math.sin(index * 0.917)
        + 2.5 * math.cos(index * 0.641)
        for index in range(count)
    ]


def percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def variable_pitch_profile(count: int) -> list[float]:
    """Deterministic asymmetric pitch profile; values stay within valid limits."""
    return [
        32.0 + 4.0 * math.sin(index * 1.371)
        + 2.5 * math.cos(index * 0.613)
        for index in range(count)
    ]


def measure(
    label: str,
    points,
    builder,
    repeats: int,
    pitches_degrees: list[float] | None = None,
) -> dict:
    pitches = [35.0] * len(points) if pitches_degrees is None else list(pitches_degrees)
    if len(pitches) != len(points):
        raise ValueError("Benchmark pitch count must match the contour edge count.")
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
            "facets_out": len(getattr(output, "facets", ())),
        }
    except Exception as exc:  # Keep unsupported geometry visible in the report.
        return {
            "case": label,
            "status": "error",
            "vertices_in": len(points),
            "error": f"{type(exc).__name__}: {exc}"[:1200],
            "error_truncated": len(f"{type(exc).__name__}: {exc}") > 1200,
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
    for count in (8, 16, 32, 64):
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
        results.append(measure(
            f"weighted_wavefront_convex_variable_pitch_n{count}",
            convex,
            run_weighted_wavefront,
            args.repeats,
            variable_pitch_profile(count),
        ))

    for count in (8, 16, 32, 64):
        concave = radial_polygon(count, concave=True)
        results.append(measure(
            f"weighted_wavefront_trace_concave_n{count}",
            concave,
            run_weighted_wavefront,
            args.repeats,
        ))
        results.append(measure(
            f"weighted_wavefront_surface_concave_n{count}",
            concave,
            build_wavefront_roof_surface,
            args.repeats,
        ))
        variable_pitches = variable_pitch_profile(count)
        results.append(measure(
            f"weighted_wavefront_trace_concave_variable_pitch_n{count}",
            concave,
            run_weighted_wavefront,
            args.repeats,
            variable_pitches,
        ))
        results.append(measure(
            f"weighted_wavefront_surface_concave_variable_pitch_n{count}",
            concave,
            build_wavefront_roof_surface,
            args.repeats,
            variable_pitches,
        ))
        results.append(measure(
            f"distance_field_uniform_refine_depth2_concave_n{count}",
            concave,
            lambda points, pitches: build_distance_field_roof_surface(
                points, pitches, height_tolerance=1e-6, max_depth=2
            ),
            args.repeats,
        ))

    for label, points, pitches in (
        ("wavy_l", wavy_l_fixture(), l_pitch_profile(64)),
        ("wavy_u", wavy_u_fixture(), u_pitch_profile(64)),
    ):
        results.append(measure(
            f"weighted_wavefront_trace_{label}_variable_pitch_n64",
            points,
            run_weighted_wavefront,
            args.repeats,
            pitches,
        ))
        results.append(measure(
            f"weighted_wavefront_surface_{label}_variable_pitch_n64",
            points,
            build_wavefront_roof_surface,
            args.repeats,
            pitches,
        ))

    # Exercise the exact spatial path, rather than the flat-eave
    # wavefront solver, on dense mixed-height concave outlines.
    mixed_height_l = wavy_outline(
        [(0.0, 0.0), (10.0, 0.0), (10.0, 3.0),
         (4.0, 3.0), (4.0, 10.0), (0.0, 10.0)],
        [16] * 6,
        0.015,
        z_amplitude=0.01,
    )
    results.append(measure(
        "exact_spatial_mixed_height_wavy_l_n96",
        mixed_height_l,
        build_roof_surface,
        args.repeats,
        l_pitch_profile(len(mixed_height_l)),
    ))

    mixed_height_u = wavy_outline(
        [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (3.0, 4.0),
         (3.0, 1.0), (1.0, 1.0), (1.0, 4.0), (0.0, 4.0)],
        [12] * 8,
        0.008,
        z_amplitude=0.01,
    )
    results.append(measure(
        "exact_spatial_mixed_height_wavy_u_n96",
        mixed_height_u,
        build_roof_surface,
        args.repeats,
        u_pitch_profile(len(mixed_height_u)),
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
