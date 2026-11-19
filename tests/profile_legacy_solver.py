"""Profile the test-only legacy solver's largest target-range concave cases."""
from __future__ import annotations

import cProfile
import io
import math
import pstats
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests" / "legacy_spatial_solver"))

from legacy_spatial_solver_bench import radial_polygon
from spatial_roof_2_9_0 import build_spatial_roof_mesh


def profile_case(label: str, variable_pitch: bool) -> None:
    points = radial_polygon(64, concave=True)
    if variable_pitch:
        angles = [math.radians(35.0 + ((i * 17 % 19) if (i % 2 == 1) else 0.0))
                  for i in range(len(points))]
    else:
        angles = [math.radians(35.0)] * len(points)

    profiler = cProfile.Profile()
    profiler.enable()
    vertices, faces, sources = build_spatial_roof_mesh(points, angles)
    profiler.disable()

    print(f"=== {label}: {len(points)} edges, {len(vertices)} vertices, "
          f"{len(faces)} faces, {len(set(sources))} source slopes ===")
    buffer = io.StringIO()
    pstats.Stats(profiler, stream=buffer).strip_dirs().sort_stats("cumulative").print_stats(35)
    print(buffer.getvalue())


def main() -> None:
    profile_case("concave_64_equal_pitch", variable_pitch=False)
    profile_case("concave_64_variable_pitch", variable_pitch=True)


if __name__ == "__main__":
    main()
