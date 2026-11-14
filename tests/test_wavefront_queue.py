"""Differential tests for batched weighted-wavefront event queue insertion."""
from __future__ import annotations

import unittest

from core.geometry import GeometryInputError
from core.wavefront import EventKind, WavefrontEvent, WavefrontEventQueue


def make_event(index: int, *, shared_key: bool = False) -> WavefrontEvent:
    if shared_key:
        # The sort key is identical; sequence order must remain the tie-breaker.
        return WavefrontEvent(
            EventKind.EDGE_COLLAPSE,
            0.25,
            3,
            edge_id=7,
            vertex_id=2,
            target_edge_id=9,
            position=(float(index), -float(index)),
            participant_generations=((1000 + index, index),),
            loop_generation=4,
        )
    kinds = (
        EventKind.EDGE_COLLAPSE,
        EventKind.SPLIT_CANDIDATE,
        EventKind.VERTEX_HIT,
    )
    return WavefrontEvent(
        kinds[index % len(kinds)],
        (index % 23) * 0.01,
        index % 7,
        edge_id=index % 17,
        vertex_id=index % 11,
        target_edge_id=(index * 3) % 19,
        position=(float(index), float(-index)),
        participant_generations=((2000 + index, index % 5),),
        loop_generation=index % 3,
    )


def drain_queue(queue: WavefrontEventQueue):
    result = []
    current_time = 0.0
    while True:
        batch = queue.pop_next_batch(
            current_time=current_time,
            time_tolerance=1.0e-9,
        )
        if batch is None:
            return result
        result.extend(batch.events)
        current_time = batch.time


class WavefrontEventQueueBatchTests(unittest.TestCase):
    def test_bulk_insertion_matches_incremental_order_with_existing_entries(self):
        existing = [make_event(index + 1000) for index in range(19)]
        incoming = [make_event(index) for index in range(512)]

        batched = WavefrontEventQueue()
        incremental = WavefrontEventQueue()
        for event in existing:
            batched.push(event)
            incremental.push(event)

        batched.push_many(incoming)
        for event in incoming:
            incremental.push(event)

        self.assertEqual(drain_queue(batched), drain_queue(incremental))

    def test_bulk_insertion_preserves_stable_order_for_equal_event_keys(self):
        events = [make_event(index, shared_key=True) for index in range(256)]
        queue = WavefrontEventQueue()
        queue.push_many(events)

        popped = drain_queue(queue)
        self.assertEqual(popped, events)

    def test_invalid_late_item_keeps_valid_prefix_queued(self):
        valid = [make_event(index) for index in range(48)]
        invalid = WavefrontEvent(
            EventKind.EDGE_COLLAPSE,
            float("inf"),
            0,
            edge_id=0,
            vertex_id=0,
        )
        queue = WavefrontEventQueue()

        with self.assertRaises(GeometryInputError) as context:
            queue.push_many([*valid, invalid])

        self.assertEqual(context.exception.code, "INVALID_EVENT_TIME")
        self.assertEqual(drain_queue(queue), sorted(
            valid, key=WavefrontEventQueue._event_key
        ))

    def test_small_batch_keeps_incremental_behavior(self):
        events = [make_event(index) for index in range(12)]
        batched = WavefrontEventQueue()
        incremental = WavefrontEventQueue()

        batched.push_many(events)
        for event in events:
            incremental.push(event)

        self.assertEqual(drain_queue(batched), drain_queue(incremental))


if __name__ == "__main__":
    unittest.main()
