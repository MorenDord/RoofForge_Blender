"""Event-driven weighted inward wavefront kinematics.

This first slice deliberately handles strictly convex contours end-to-end.
For concave contours it provides validated split-event candidate detection,
but does not yet mutate wavefront topology at split events. It is pure Python
and does not depend on bpy.

Line convention:
    n . x = c + speed * t
where n is the unit inward normal and speed > 0. Roof height is t. For pitch
theta above horizontal, speed = cot(theta), hence the lifted source-edge facet
obeys t = (n . x - c) / speed and has gradient magnitude tan(theta).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from heapq import heappop, heappush
from math import hypot, isfinite, tan, radians
from typing import Sequence

from .geometry import GeometryInputError, Point2, Point3, signed_area, validate_simple_polygon
from .planes import build_boundary_planes


class EventKind(str, Enum):
    EDGE_COLLAPSE = "EDGE_COLLAPSE"
    SPLIT_CANDIDATE = "SPLIT_CANDIDATE"
    VERTEX_HIT = "VERTEX_HIT"
    NEEDLE = "NEEDLE"
    SIMULTANEOUS = "SIMULTANEOUS"


@dataclass(frozen=True)
class MovingLine:
    edge_id: int
    source_edge_id: int
    normal: Point2
    offset: float
    speed: float
    tangent: Point2
    generation: int = 0

    def offset_at(self, time: float) -> float:
        return self.offset + self.speed * time


@dataclass(frozen=True)
class KinematicVertex:
    point: Point2
    velocity: Point2
    previous_edge_id: int
    next_edge_id: int


@dataclass(frozen=True)
class WavefrontLoop:
    loop_id: int
    edge_ids: tuple[int, ...]
    generation: int = 0


@dataclass(frozen=True)
class WavefrontEvent:
    kind: EventKind
    time: float
    loop_id: int
    edge_id: int | None = None
    vertex_id: int | None = None
    target_edge_id: int | None = None
    position: Point2 | None = None
    participant_generations: tuple[tuple[int, int], ...] = ()
    loop_generation: int = 0


@dataclass(frozen=True)
class EventBatch:
    """All valid events whose times are equal within the configured tolerance."""
    time: float
    events: tuple[WavefrontEvent, ...]


@dataclass(frozen=True)
class FacetFragment:
    source_edge_id: int
    start_time: float
    end_time: float
    vertices: tuple[Point3, ...]


@dataclass(frozen=True)
class SkeletonArc:
    start: Point3
    end: Point3
    event_time: float


@dataclass(frozen=True)
class WavefrontTrace:
    facets: tuple[FacetFragment, ...]
    events: tuple[WavefrontEvent, ...]
    skeleton_arcs: tuple[SkeletonArc, ...]
    terminal_time: float
    terminal_kind: str
    source_area: float
    projected_facet_area: float
    input_winding: int

    @property
    def is_complete(self) -> bool:
        return self.terminal_kind in {"POINT", "NEEDLE"}


class WavefrontEventQueue:
    """Deterministic priority queue with lazy invalidation of stale events.

    Event participants carry edge-generation stamps. A loop-generation stamp
    invalidates all events computed before that loop's topology changed. The
    queue never mutates wavefront topology; the simulation owns that operation.
    """

    _PRIORITY = {
        EventKind.EDGE_COLLAPSE: 0,
        EventKind.SPLIT_CANDIDATE: 1,
        EventKind.VERTEX_HIT: 2,
        EventKind.NEEDLE: 3,
        EventKind.SIMULTANEOUS: 4,
    }

    def __init__(self) -> None:
        self._heap: list[tuple[tuple, int, WavefrontEvent]] = []
        self._sequence = 0
        self.discarded_stale = 0

    @staticmethod
    def _event_key(event: WavefrontEvent) -> tuple:
        missing = 2**63 - 1
        return (
            event.time,
            WavefrontEventQueue._PRIORITY[event.kind],
            event.loop_id,
            event.vertex_id if event.vertex_id is not None else missing,
            event.edge_id if event.edge_id is not None else missing,
            event.target_edge_id if event.target_edge_id is not None else missing,
        )

    def push(self, event: WavefrontEvent) -> None:
        if not isfinite(event.time) or event.time < 0.0:
            raise GeometryInputError(
                "INVALID_EVENT_TIME",
                "Время события волнового фронта должно быть конечным и неотрицательным."
            )
        heappush(self._heap, (self._event_key(event), self._sequence, event))
        self._sequence += 1

    def push_many(self, events: Sequence[WavefrontEvent]) -> None:
        for event in events:
            self.push(event)

    def __len__(self) -> int:
        return len(self._heap)

    def _is_current(
        self,
        event: WavefrontEvent,
        current_time: float,
        time_tolerance: float,
        current_edge_generations: dict[int, int] | None,
        current_loop_generations: dict[int, int] | None,
    ) -> bool:
        if event.time < current_time - time_tolerance:
            return False
        if current_loop_generations is not None:
            if current_loop_generations.get(event.loop_id) != event.loop_generation:
                return False
        if current_edge_generations is not None:
            for edge_id, generation in event.participant_generations:
                if current_edge_generations.get(edge_id) != generation:
                    return False
        return True

    def pop_next_batch(
        self,
        *,
        current_time: float = 0.0,
        time_tolerance: float = 1e-9,
        current_edge_generations: dict[int, int] | None = None,
        current_loop_generations: dict[int, int] | None = None,
    ) -> EventBatch | None:
        """Pop the earliest valid time batch, lazily dropping stale entries.

        All events within 'time_tolerance' of the earliest valid event are
        returned together so a caller can resolve simultaneous topology changes
        as one operation. Staleness is tested both for source edges and loops.
        """
        if not isfinite(current_time) or not isfinite(time_tolerance) or time_tolerance < 0.0:
            raise GeometryInputError("INVALID_QUEUE_TIME", "Неверные параметры времени очереди событий.")

        first: WavefrontEvent | None = None
        while self._heap:
            _, _, candidate = heappop(self._heap)
            if self._is_current(
                candidate, current_time, time_tolerance,
                current_edge_generations, current_loop_generations,
            ):
                first = candidate
                break
            self.discarded_stale += 1

        if first is None:
            return None

        batch = [first]
        cutoff = first.time + time_tolerance
        deferred: list[tuple[tuple, int, WavefrontEvent]] = []
        while self._heap and self._heap[0][2].time <= cutoff:
            item = heappop(self._heap)
            candidate = item[2]
            if self._is_current(
                candidate, current_time, time_tolerance,
                current_edge_generations, current_loop_generations,
            ):
                batch.append(candidate)
            else:
                self.discarded_stale += 1

        batch.sort(key=self._event_key)
        return EventBatch(first.time, tuple(batch))


def _dot(a: Point2, b: Point2) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _sub(a: Point2, b: Point2) -> Point2:
    return (a[0] - b[0], a[1] - b[1])


def _add_scaled(point: Point2, vector: Point2, scale: float) -> Point2:
    return (point[0] + vector[0] * scale, point[1] + vector[1] * scale)


def _cross2(a: Point2, b: Point2) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _line_intersection(first: MovingLine, second: MovingLine, time: float,
                       eps: float) -> KinematicVertex:
    """Intersect two moving lines and solve their constant vertex velocity."""
    a, b = first.normal
    c, d = second.normal
    determinant = a * d - b * c
    if abs(determinant) <= eps:
        raise GeometryInputError(
            "PARALLEL_WAVEFRONT_EDGES",
            f"Соседние фронты рёбер {first.edge_id} и {second.edge_id} параллельны или почти параллельны."
        )

    rhs_first = first.offset_at(time)
    rhs_second = second.offset_at(time)
    x = (rhs_first * d - b * rhs_second) / determinant
    y = (a * rhs_second - rhs_first * c) / determinant

    vx = (first.speed * d - b * second.speed) / determinant
    vy = (a * second.speed - first.speed * c) / determinant
    return KinematicVertex((x, y), (vx, vy), first.edge_id, second.edge_id)


def _loop_vertices(loop: WavefrontLoop, edges: dict[int, MovingLine], time: float,
                   eps: float) -> tuple[KinematicVertex, ...]:
    edge_ids = loop.edge_ids
    if len(edge_ids) < 3:
        raise GeometryInputError("WAVEFRONT_TOO_SMALL", "Для замкнутого wavefront-loop нужны минимум три активных ребра.")
    vertices = []
    for index, edge_id in enumerate(edge_ids):
        previous = edges[edge_ids[index - 1]]
        current = edges[edge_id]
        vertices.append(_line_intersection(previous, current, time, eps))
    return tuple(vertices)


def _edge_segment(loop: WavefrontLoop, edge_index: int,
                  vertices: Sequence[KinematicVertex], edges: dict[int, MovingLine],
                  time: float, dt: float = 0.0) -> tuple[Point2, Point2, Point2, float]:
    """Return start/end positions, edge tangent, and directed segment length."""
    edge_id = loop.edge_ids[edge_index]
    start_vertex = vertices[edge_index]
    end_vertex = vertices[(edge_index + 1) % len(vertices)]
    start = _add_scaled(start_vertex.point, start_vertex.velocity, dt)
    end = _add_scaled(end_vertex.point, end_vertex.velocity, dt)
    tangent = edges[edge_id].tangent
    length = _dot(_sub(end, start), tangent)
    return start, end, tangent, length


def _signed_area_at(vertices: Sequence[KinematicVertex]) -> float:
    return signed_area([vertex.point for vertex in vertices])


def _is_convex_loop(vertices: Sequence[KinematicVertex], winding: int, eps: float) -> bool:
    points = [vertex.point for vertex in vertices]
    for index, current in enumerate(points):
        previous = points[index - 1]
        following = points[(index + 1) % len(points)]
        turn = _cross2(_sub(current, previous), _sub(following, current))
        if turn * winding < -eps:
            return False
    return True


def build_moving_lines(points: Sequence[Point3], pitches_degrees: Sequence[float],
                       eps: float = 1e-9) -> tuple[MovingLine, ...]:
    """Create one positively weighted moving line per ordered contour edge."""
    if len(points) < 3 or len(points) != len(pitches_degrees):
        raise GeometryInputError("INPUT_COUNT", "Нужно минимум три вершины и по одному уклону на каждое ребро.")
    z_values = [point[2] for point in points]
    z_tolerance = eps * max(1.0, max(z_values) - min(z_values), *(abs(z) for z in z_values))
    if max(z_values) - min(z_values) > z_tolerance:
        raise GeometryInputError(
            "MIXED_EAVE_HEIGHTS_UNSUPPORTED",
            "Weighted 2D wavefront первой версии поддерживает только контур с постоянной высотой карнизов."
        )

    polygon = [(point[0], point[1]) for point in points]
    issues = validate_simple_polygon(polygon, eps)
    if issues:
        raise GeometryInputError(issues[0].code, issues[0].message)
    winding = 1 if signed_area(polygon) > 0.0 else -1

    # Reuse the exact 3D plane builder for compatibility validation and pitch
    # semantics. With flat eaves, its edge gradient is purely inward.
    planes = build_boundary_planes(points, pitches_degrees, eps)
    result = []
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = hypot(dx, dy)
        tangent = (dx / length, dy / length)
        normal = (-tangent[1] * winding, tangent[0] * winding)
        pitch = pitches_degrees[index]
        if not (0.1 <= pitch < 89.9):
            raise GeometryInputError(
                "WAVEFRONT_PITCH_RANGE",
                f"Для волнового фронта уклон ребра {index + 1} должен быть от 0.1° до 89.9°."
            )
        from math import tan, radians
        speed = 1.0 / tan(radians(pitch))
        offset = _dot(normal, (start[0], start[1]))
        # Guard the speed mapping against a future change in plane convention.
        if abs(planes[index].pitch_degrees - pitch) > 1e-6:
            raise GeometryInputError(
                "PITCH_PLANE_MISMATCH",
                f"Плоскость ребра {index + 1} не соответствует заданному уклону."
            )
        result.append(MovingLine(index, index, normal, offset, speed, tangent))
    return tuple(result)


def _edge_collapse_events(loop: WavefrontLoop, edges: dict[int, MovingLine],
                          vertices: Sequence[KinematicVertex], time: float,
                          length_eps: float, time_eps: float) -> list[WavefrontEvent]:
    candidates = []
    for index, edge_id in enumerate(loop.edge_ids):
        start, end, tangent, length = _edge_segment(loop, index, vertices, edges, time)
        start_velocity = vertices[index].velocity
        end_velocity = vertices[(index + 1) % len(vertices)].velocity
        length_rate = _dot(_sub(end_velocity, start_velocity), tangent)
        if length < -length_eps:
            raise GeometryInputError(
                "NEGATIVE_WAVEFRONT_EDGE",
                f"Активное ребро {edge_id} имеет отрицательную ориентированную длину."
            )
        if length <= length_eps:
            dt = 0.0
        elif length_rate < -time_eps:
            dt = length / -length_rate
        else:
            continue
        if dt < -time_eps:
            continue
        event_time = time + max(0.0, dt)
        event_position = (
            (start[0] + end[0]) * 0.5 + (start_velocity[0] + end_velocity[0]) * 0.5 * max(0.0, dt),
            (start[1] + end[1]) * 0.5 + (start_velocity[1] + end_velocity[1]) * 0.5 * max(0.0, dt),
        )
        participants = (
            (loop.edge_ids[index - 1], edges[loop.edge_ids[index - 1]].generation),
            (edge_id, edges[edge_id].generation),
            (loop.edge_ids[(index + 1) % len(loop.edge_ids)],
             edges[loop.edge_ids[(index + 1) % len(loop.edge_ids)]].generation),
        )
        candidates.append(WavefrontEvent(
            EventKind.EDGE_COLLAPSE, event_time, loop.loop_id, edge_id=edge_id,
            vertex_id=index, position=event_position,
            participant_generations=participants,
            loop_generation=loop.generation,
        ))
    return candidates


def find_split_candidates(loop: WavefrontLoop, edges: dict[int, MovingLine],
                          time: float = 0.0, eps: float = 1e-9) -> tuple[WavefrontEvent, ...]:
    """Find future reflex-vertex hits on live finite edge segments.

    These are candidate events only. The caller must pop the earliest event,
    recompute the wavefront, and revalidate the target segment before topology
    mutation. Hits at a target endpoint are reported separately as VERTEX_HIT.
    """
    vertices = _loop_vertices(loop, edges, time, eps)
    winding = 1 if _signed_area_at(vertices) > 0.0 else -1
    points = [vertex.point for vertex in vertices]
    events = []
    count = len(loop.edge_ids)

    for vertex_index, vertex in enumerate(vertices):
        previous_point = points[vertex_index - 1]
        next_point = points[(vertex_index + 1) % count]
        incoming = _sub(vertex.point, previous_point)
        outgoing = _sub(next_point, vertex.point)
        turn = _cross2(incoming, outgoing)
        if turn * winding >= -eps:
            continue  # Not a reflex wavefront vertex.

        adjacent_ids = {
            loop.edge_ids[vertex_index - 1],
            loop.edge_ids[vertex_index],
        }
        for target_index, target_id in enumerate(loop.edge_ids):
            if target_id in adjacent_ids:
                continue
            target = edges[target_id]
            signed_distance = _dot(target.normal, vertex.point) - target.offset_at(time)
            closing_rate = _dot(target.normal, vertex.velocity) - target.speed
            if closing_rate >= -eps:
                continue
            dt = -signed_distance / closing_rate
            if dt <= eps:
                continue
            hit_time = time + dt
            hit = _add_scaled(vertex.point, vertex.velocity, dt)
            target_start_vertex = _line_intersection(
                edges[loop.edge_ids[target_index - 1]], target, hit_time, eps
            )
            target_end_vertex = _line_intersection(
                target, edges[loop.edge_ids[(target_index + 1) % count]], hit_time, eps
            )
            start = target_start_vertex.point
            end = target_end_vertex.point
            tangent = target.tangent
            target_length = _dot(_sub(end, start), tangent)
            coordinate = _dot(_sub(hit, start), tangent)
            margin = eps * max(1.0, abs(target_length))
            if target_length < -margin:
                continue
            if coordinate < -margin or coordinate > target_length + margin:
                continue
            kind = (
                EventKind.SPLIT_CANDIDATE
                if margin < coordinate < target_length - margin
                else EventKind.VERTEX_HIT
            )
            generations = (
                (loop.edge_ids[vertex_index - 1], edges[loop.edge_ids[vertex_index - 1]].generation),
                (loop.edge_ids[vertex_index], edges[loop.edge_ids[vertex_index]].generation),
                (target_id, target.generation),
                (loop.edge_ids[target_index - 1], edges[loop.edge_ids[target_index - 1]].generation),
                (loop.edge_ids[(target_index + 1) % count],
                 edges[loop.edge_ids[(target_index + 1) % count]].generation),
            )
            events.append(WavefrontEvent(
                kind, hit_time, loop.loop_id, edge_id=loop.edge_ids[vertex_index],
                vertex_id=vertex_index, target_edge_id=target_id, position=hit,
                participant_generations=generations,
                loop_generation=loop.generation,
            ))

    events.sort(key=lambda event: (
        event.time,
        event.vertex_id if event.vertex_id is not None else 2**63 - 1,
        event.target_edge_id if event.target_edge_id is not None else 2**63 - 1,
    ))
    return tuple(events)


def collect_loop_events(
    loop: WavefrontLoop,
    edges: dict[int, MovingLine],
    time: float = 0.0,
    eps: float = 1e-9,
) -> tuple[WavefrontEvent, ...]:
    """Collect collapse and split candidates for one current loop state."""
    vertices = _loop_vertices(loop, edges, time, eps)
    scale = max(
        1.0,
        max(vertex.point[0] for vertex in vertices) - min(vertex.point[0] for vertex in vertices),
        max(vertex.point[1] for vertex in vertices) - min(vertex.point[1] for vertex in vertices),
    )
    collapse = _edge_collapse_events(
        loop, edges, vertices, time,
        length_eps=eps * scale * 100.0,
        time_eps=eps * max(1.0, scale) * 100.0,
    )
    split = find_split_candidates(loop, edges, time, eps)
    events = (*collapse, *split)
    return tuple(sorted(events, key=WavefrontEventQueue._event_key))


def _dedupe_polygon(points: Sequence[Point3], tolerance: float) -> tuple[Point3, ...]:
    result = []
    for point in points:
        if not result or hypot(hypot(point[0] - result[-1][0], point[1] - result[-1][1]),
                               point[2] - result[-1][2]) > tolerance:
            result.append(point)
    if len(result) > 1 and hypot(hypot(result[0][0] - result[-1][0], result[0][1] - result[-1][1]),
                                 result[0][2] - result[-1][2]) <= tolerance:
        result.pop()
    return tuple(result)


def _projected_area(points: Sequence[Point3]) -> float:
    return abs(signed_area([(point[0], point[1]) for point in points]))


def simulate_convex_wavefront(points: Sequence[Point3], pitches_degrees: Sequence[float],
                              eps: float = 1e-9, max_events: int = 10000) -> WavefrontTrace:
    """Simulate a strictly convex constant-height contour to its first terminal wavefront.

    Edge fragments are lifted immediately into exact planar roof patches. The
    routine stops at a point or a two-edge needle. Concave split topology is
    deliberately not applied yet; use find_split_candidates() for diagnostics.
    """
    if len(points) < 3 or len(points) != len(pitches_degrees):
        raise GeometryInputError("INPUT_COUNT", "Нужно минимум три вершины и по одному уклону на каждое ребро.")
    polygon = [(point[0], point[1]) for point in points]
    issues = validate_simple_polygon(polygon, eps)
    if issues:
        raise GeometryInputError(issues[0].code, issues[0].message)
    winding = 1 if signed_area(polygon) > 0 else -1
    lines = build_moving_lines(points, pitches_degrees, eps)
    edges = {line.edge_id: line for line in lines}
    loop = WavefrontLoop(0, tuple(line.edge_id for line in lines))
    initial_vertices = _loop_vertices(loop, edges, 0.0, eps)
    if not _is_convex_loop(initial_vertices, winding, eps):
        raise GeometryInputError(
            "REFLEX_SPLIT_REQUIRED",
            "В контуре есть рефлексная вершина. Для построения крыши нужен обработчик split-event; пока доступно только обнаружение split-кандидатов."
        )

    scale = max(
        1.0,
        max(p[0] for p in points) - min(p[0] for p in points),
        max(p[1] for p in points) - min(p[1] for p in points),
    )
    length_eps = eps * scale * 100.0
    time_eps = eps * max(1.0, scale) * 100.0
    current_time = 0.0
    facets: list[FacetFragment] = []
    events: list[WavefrontEvent] = []
    skeleton_arcs: list[SkeletonArc] = []
    terminal_kind = "MAX_EVENTS"

    for _ in range(max_events):
        if len(loop.edge_ids) < 3:
            terminal_kind = "POINT" if len(loop.edge_ids) == 0 else "DEGENERATE"
            break
        vertices_now = _loop_vertices(loop, edges, current_time, eps)
        if not _is_convex_loop(vertices_now, winding, eps * scale):
            raise GeometryInputError(
                "REFLEX_CREATED_DURING_CONVEX_SIMULATION",
                "После события wavefront перестал быть выпуклым; требуется split-event обработчик."
            )
        candidates = _edge_collapse_events(
            loop, edges, vertices_now, current_time, length_eps, time_eps
        )
        if not candidates:
            raise GeometryInputError(
                "NO_WAVEFRONT_EVENT",
                "Не найдено следующее событие схлопывания; возможен параллельный или вырожденный wavefront."
            )
        next_time = min(event.time for event in candidates)
        if next_time < current_time - time_eps:
            raise GeometryInputError("TIME_ORDER", "События волнового фронта нарушили хронологический порядок.")
        dt = max(0.0, next_time - current_time)

        vertices_next = tuple(
            KinematicVertex(
                _add_scaled(vertex.point, vertex.velocity, dt),
                vertex.velocity,
                vertex.previous_edge_id,
                vertex.next_edge_id,
            )
            for vertex in vertices_now
        )
        collapsed_ids = []
        collapse_positions = []
        for index, edge_id in enumerate(loop.edge_ids):
            start0, end0, tangent, length0 = _edge_segment(
                loop, index, vertices_now, edges, current_time
            )
            start1, end1, _, length1 = _edge_segment(
                loop, index, vertices_next, edges, next_time
            )
            if length1 < -length_eps:
                raise GeometryInputError(
                    "EVENT_OVERSHOOT",
                    f"Событие перескочило точку схлопывания ребра {edge_id}."
                )

            line = edges[edge_id]
            start3 = (start0[0], start0[1], current_time)
            end3 = (end0[0], end0[1], current_time)
            end13 = (end1[0], end1[1], next_time)
            start13 = (start1[0], start1[1], next_time)
            face = _dedupe_polygon((start3, end3, end13, start13), length_eps)
            if len(face) >= 3 and _projected_area(face) > length_eps * length_eps:
                for x, y, z in face:
                    expected_z = (line.normal[0] * x + line.normal[1] * y - line.offset) / line.speed
                    if abs(expected_z - z) > max(length_eps, eps * scale * 1000.0):
                        raise GeometryInputError(
                            "FACET_NOT_PLANAR",
                            f"Фрагмент ската {line.source_edge_id + 1} не лежит на заданной плоскости."
                        )
                facets.append(FacetFragment(line.source_edge_id, current_time, next_time, face))

            if length1 <= length_eps * 5.0:
                collapsed_ids.append(edge_id)
                point = ((start1[0] + end1[0]) * 0.5, (start1[1] + end1[1]) * 0.5)
                collapse_positions.append(point)

        if not collapsed_ids:
            raise GeometryInputError(
                "NO_EDGE_COLLAPSED_AT_EVENT",
                "Расчётное событие не схлопнуло ни одного ребра в пределах допуска."
            )

        generation_pairs = tuple(
            (edge_id, edges[edge_id].generation) for edge_id in sorted(collapsed_ids)
        )
        kind = EventKind.SIMULTANEOUS if len(collapsed_ids) > 1 else EventKind.EDGE_COLLAPSE
        for edge_id, position in zip(collapsed_ids, collapse_positions):
            events.append(WavefrontEvent(
                EventKind.EDGE_COLLAPSE, next_time, loop.loop_id,
                edge_id=edge_id, position=position,
                participant_generations=generation_pairs,
            ))
        if len(collapsed_ids) > 1:
            events.append(WavefrontEvent(
                EventKind.SIMULTANEOUS, next_time, loop.loop_id,
                position=collapse_positions[0],
                participant_generations=generation_pairs,
            ))

        remaining = tuple(edge_id for edge_id in loop.edge_ids if edge_id not in set(collapsed_ids))
        current_time = next_time
        if len(remaining) <= 1:
            terminal_kind = "POINT"
            if collapse_positions:
                terminal = tuple(collapse_positions)
                if len(terminal) > 1 and all(
                    hypot(p[0] - terminal[0][0], p[1] - terminal[0][1]) <= length_eps * 5.0
                    for p in terminal[1:]
                ):
                    terminal_kind = "POINT"
                else:
                    raise GeometryInputError(
                        "MULTI_POINT_TERMINATION",
                        "Одновременное схлопывание оставило несколько разных терминальных узлов."
                    )
            break

        if len(remaining) == 2:
            first, second = edges[remaining[0]], edges[remaining[1]]
            alignment = _dot(first.normal, second.normal)
            if alignment > -1.0 + eps * 100.0:
                raise GeometryInputError(
                    "TWO_EDGE_TERMINATION",
                    "После схлопывания осталось два фронта, которые не являются противоположными параллельными линиями."
                )
            line_gap = first.offset_at(current_time) + second.offset_at(current_time)
            if abs(line_gap) > length_eps * 10.0:
                raise GeometryInputError(
                    "NEEDLE_NOT_COINCIDENT",
                    "Два противоположных фронта ещё не совпали; требуется отдельная обработка needle-event."
                )
            unique_points = []
            for point in collapse_positions:
                if not any(hypot(point[0] - old[0], point[1] - old[1]) <= length_eps * 5.0 for old in unique_points):
                    unique_points.append(point)
            if len(unique_points) == 2:
                skeleton_arcs.append(SkeletonArc(
                    (unique_points[0][0], unique_points[0][1], current_time),
                    (unique_points[1][0], unique_points[1][1], current_time),
                    current_time,
                ))
            elif len(unique_points) > 2:
                raise GeometryInputError(
                    "AMBIGUOUS_NEEDLE_ARC",
                    "Невозможно однозначно определить концы финальной skeleton-дуги."
                )
            events.append(WavefrontEvent(
                EventKind.NEEDLE, current_time, loop.loop_id,
                edge_id=remaining[0], target_edge_id=remaining[1],
                position=unique_points[0] if unique_points else None,
                participant_generations=tuple(
                    (edge_id, edges[edge_id].generation) for edge_id in remaining
                ),
            ))
            terminal_kind = "NEEDLE"
            break

        loop = WavefrontLoop(loop.loop_id, remaining, loop.generation + 1)
    else:
        raise GeometryInputError(
            "MAX_WAVEFRONT_EVENTS",
            f"Достигнут лимит событий волнового фронта: {max_events}."
        )

    if not facets:
        raise GeometryInputError("EMPTY_WAVEFRONT_ROOF", "Волновой фронт не сформировал ни одного участка крыши.")
    projected_area = sum(_projected_area(facet.vertices) for facet in facets)
    source_area = abs(signed_area(polygon))
    if abs(projected_area - source_area) > max(length_eps * length_eps * 100.0, source_area * 1e-7):
        raise GeometryInputError(
            "WAVEFRONT_COVERAGE_MISMATCH",
            f"Волновые фасеты покрывают {projected_area:.9g} из {source_area:.9g} единиц площади."
        )
    return WavefrontTrace(
        tuple(facets), tuple(events), tuple(skeleton_arcs),
        current_time, terminal_kind, source_area, projected_area, winding,
    )
