"""Profile the Python weighted-wavefront state machine with Rust kernels enabled.

The contour and initial event queue are prepared outside the timed region.
Rust remains enabled for event candidate collection and interval geometry;
this report therefore isolates the remaining Python event/queue state machine.
"""
from __future__ import annotations

import argparse
import cProfile
import json
import math
import pstats
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import native_bridge, wavefront


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


def drain_state(state, max_batches: int = 10000):
    batches = 0
    while not state.is_complete:
        if batches >= max_batches:
            raise RuntimeError(f"state machine exceeded {max_batches} event batches")
        wavefront.advance_wavefront_state(state)
        batches += 1
    return batches


def stats_rows(profile: cProfile.Profile, *, limit: int, order: str):
    stats = pstats.Stats(profile)
    rows = []
    for (filename, line, function), values in stats.stats.items():
        _, total_calls, self_seconds, cumulative_seconds, _ = values
        if "/core/wavefront.py" not in filename.replace("\\", "/"):
            continue
        rows.append({
            "function": f"{Path(filename).name}:{line}({function})",
            "name": function,
            "calls": total_calls,
            "self_seconds": round(self_seconds, 6),
            "cumulative_seconds": round(cumulative_seconds, 6),
        })
    field = "self_seconds" if order == "self" else "cumulative_seconds"
    rows.sort(key=lambda row: row[field], reverse=True)
    return rows[:limit], rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    if not 3 <= args.runs <= 15:
        raise SystemExit("--runs must be between 3 and 15")
    if not native_bridge.NATIVE_WAVEFRONT_EVENTS_AVAILABLE:
        raise SystemExit("Rust wavefront event collector is not installed.")
    if not native_bridge.NATIVE_WAVEFRONT_INTERVAL_AVAILABLE:
        raise SystemExit("Rust wavefront interval kernel is not installed.")

    points, pitches = fixture(64)

    queue_type = wavefront.WavefrontEventQueue
    optimized_push_many = queue_type.push_many

    def incremental_push_many(self, events):
        for event in events:
            self.push(event)

    def state_signature(state):
        return (
            tuple(state.processed_events),
            tuple(state.facets),
            tuple(state.skeleton_arcs),
            tuple(sorted(state.terminal_loops.items())),
            tuple(sorted(state.loops.items())),
            tuple(sorted(state.edges.items())),
            state.current_time,
        )

    # Warm both strategies once, then alternate them to reduce CI-runner drift.
    previous_push_many = queue_type.push_many
    warm_batches = 0
    try:
        for implementation in (incremental_push_many, optimized_push_many):
            queue_type.push_many = implementation
            warm_state = wavefront.create_wavefront_state(points, pitches)
            warm_batches = drain_state(warm_state)

        variant_samples = {"incremental": [], "adaptive_batch": []}
        variant_signatures = {}
        for run_index in range(args.runs):
            order = (
                (("incremental", incremental_push_many),
                 ("adaptive_batch", optimized_push_many))
                if run_index % 2 == 0
                else (("adaptive_batch", optimized_push_many),
                      ("incremental", incremental_push_many))
            )
            for label, implementation in order:
                queue_type.push_many = implementation
                state = wavefront.create_wavefront_state(points, pitches)
                started = time.perf_counter()
                drain_state(state)
                variant_samples[label].append(
                    (time.perf_counter() - started) * 1000.0
                )
                variant_signatures[label] = state_signature(state)
    finally:
        queue_type.push_many = previous_push_many

    if variant_signatures["incremental"] != variant_signatures["adaptive_batch"]:
        raise RuntimeError("Incremental and adaptive batch queue paths changed wavefront output.")

    incremental_ms = statistics.median(variant_samples["incremental"])
    adaptive_batch_ms = statistics.median(variant_samples["adaptive_batch"])
    push_many_ab = {
        "incremental_ms_median": round(incremental_ms, 3),
        "adaptive_batch_ms_median": round(adaptive_batch_ms, 3),
        "adaptive_batch_speedup": round(incremental_ms / adaptive_batch_ms, 4)
        if adaptive_batch_ms else None,
        "incremental_ms_samples": [round(value, 3) for value in variant_samples["incremental"]],
        "adaptive_batch_ms_samples": [round(value, 3) for value in variant_samples["adaptive_batch"]],
    }

    # Profile only the state-machine loop. State creation and contour
    # validation deliberately remain outside the profiled region.
    profiled_state = wavefront.create_wavefront_state(points, pitches)
    profiler = cProfile.Profile()
    profiled_batches = profiler.runcall(drain_state, profiled_state)
    top_self, all_rows = stats_rows(profiler, limit=25, order="self")
    top_cumulative, _ = stats_rows(profiler, limit=25, order="cumulative")

    queue_names = {"push", "push_many", "pop_next_batch", "_is_current"}
    resolver_names = {
        "_resolve_edge_collapse_group",
        "_resolve_simultaneous_point_termination",
        "_resolve_vertex_hit_on_collapsing_edge",
        "_resolve_cross_needle_vertex_hit",
        "_resolve_split_collapse_batch",
        "_resolve_multiple_split_batch",
        "apply_split_event",
    }
    queue_rows = [row for row in all_rows if row["name"] in queue_names]
    resolver_rows = [row for row in all_rows if row["name"] in resolver_names]
    queue_self = sum(row["self_seconds"] for row in queue_rows)
    resolver_self = sum(row["self_seconds"] for row in resolver_rows)

    report = {
        "fixture": "64-vertex alternating-radius concave contour with variable per-edge pitch",
        "backend": {
            "wavefront_event_candidates": "Rust",
            "wavefront_interval_geometry": "Rust",
            "python_state_machine": "enabled",
        },
        "scope": "advance_wavefront_state loop only; state creation, contour validation and final roof mesh assembly excluded",
        "runs": args.runs,
        "timing_unit": "milliseconds",
        "state_machine_wall_ms_median": round(adaptive_batch_ms, 3),
        "push_many_ab": push_many_ab,
        "event_batches": profiled_batches,
        "processed_events": len(profiled_state.processed_events),
        "discarded_stale_events": profiled_state.event_queue.discarded_stale,
        "facets_recorded": len(profiled_state.facets),
        "skeleton_arcs_recorded": len(profiled_state.skeleton_arcs),
        "warmup_event_batches": warm_batches,
        "profiled_python_time_seconds": round(pstats.Stats(profiler).total_tt, 6),
        "queue_self_time_seconds": round(queue_self, 6),
        "resolver_self_time_seconds": round(resolver_self, 6),
        "queue_functions": queue_rows,
        "resolver_functions": resolver_rows,
        "top_wavefront_functions_by_self_time": top_self,
        "top_wavefront_functions_by_cumulative_time": top_cumulative,
    }

    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.json_output:
        args.json_output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
