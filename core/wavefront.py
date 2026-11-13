"""Event-driven weighted inward wavefront kinematics.

The solver supports flat-eave contours with per-edge pitch, including strict
reflex splits and a deliberately limited set of simultaneous topology events.
Unsupported event combinations and mixed-height eaves are rejected explicitly;
this module does not depend on bpy.

Line convention:
    n . x = c + speed * t
where n is the unit inward normal and speed > 0. Roof height is t. For pitch
theta above horizontal, speed = cot(theta), hence the lifted source-edge facet
obeys t = (n . x - c) / speed and has gradient magnitude tan(theta).
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
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
    base_height: float = 0.0

    def offset_at(self, time: float) -> float:
        return self.offset + self.speed * (time - self.base_height)


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
class SplitResult:
    """Topology replacement produced by one validated reflex split event."""
    loops: tuple[WavefrontLoop, WavefrontLoop]
    edges: dict[int, MovingLine]
    event_position: Point2
    next_edge_id: int
    next_loop_id: int


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
        return self.terminal_kind in {"POINT", "NEEDLE", "MULTI_TERMINAL"}


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
        if not isfinite(event.time):
            raise GeometryInputError(
                "INVALID_EVENT_TIME",
                "Время события волнового фронта должно быть конечным."
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


@dataclass
class WavefrontSimulationState:
    """Mutable event-driven state for one or more wavefront loops."""

    current_time: float
    loops: dict[int, WavefrontLoop]
    edges: dict[int, MovingLine]
    event_queue: WavefrontEventQueue
    next_edge_id: int
    next_loop_id: int
    time_tolerance: float
    epsilon: float
    terminal_loops: dict[int, str] = field(default_factory=dict)
    processed_events: list[WavefrontEvent] = field(default_factory=list)
    facets: list[FacetFragment] = field(default_factory=list)
    skeleton_arcs: list[SkeletonArc] = field(default_factory=list)
    source_area: float = 0.0
    input_winding: int = 1

    @property
    def is_complete(self) -> bool:
        return not self.loops


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


def is_flat_eave_contour(points: Sequence[Point3], eps: float = 1e-9) -> bool:
    """Return whether all eaves share one Z height within an XY-scale tolerance.

    The test is translation-invariant: moving a roof contour far above the
    world origin must not make visibly different eave heights appear equal.
    """
    if not points or not isfinite(eps) or eps < 0.0:
        return False
    if any(not all(isfinite(value) for value in point) for point in points):
        return False
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    zs = [point[2] for point in points]
    xy_scale = max(1.0, max(xs) - min(xs), max(ys) - min(ys))
    return max(zs) - min(zs) <= eps * xy_scale


def build_moving_lines(points: Sequence[Point3], pitches_degrees: Sequence[float],
                       eps: float = 1e-9) -> tuple[MovingLine, ...]:
    """Create one positively weighted moving line per ordered contour edge."""
    if len(points) < 3 or len(points) != len(pitches_degrees):
        raise GeometryInputError("INPUT_COUNT", "Нужно минимум три вершины и по одному уклону на каждое ребро.")
    z_values = [point[2] for point in points]
    if not is_flat_eave_contour(points, eps):
        raise GeometryInputError(
            "MIXED_EAVE_HEIGHTS_UNSUPPORTED",
            "Weighted 2D wavefront первой версии поддерживает только контур с постоянной высотой карнизов."
        )

    polygon = [(point[0], point[1]) for point in points]
    issues = validate_simple_polygon(polygon, eps)
    if issues:
        raise GeometryInputError(issues[0].code, issues[0].message)
    winding = 1 if signed_area(polygon) > 0.0 else -1
    base_height = sum(z_values) / len(z_values)

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
        result.append(MovingLine(
            index, index, normal, offset, speed, tangent,
            generation=0, base_height=base_height,
        ))
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
                          time: float | None = None, eps: float = 1e-9) -> tuple[WavefrontEvent, ...]:
    """Find future reflex-vertex hits on live finite edge segments.

    These are candidate events only. The caller must pop the earliest event,
    recompute the wavefront, and revalidate the target segment before topology
    mutation. Hits at a target endpoint are reported separately as VERTEX_HIT.
    """
    if time is None:
        time = min((edge.base_height for edge in edges.values()), default=0.0)
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


def _collect_loop_events_python(
    loop: WavefrontLoop,
    edges: dict[int, MovingLine],
    time: float | None = None,
    eps: float = 1e-9,
) -> tuple[WavefrontEvent, ...]:
    """Reference Python implementation used when Rust is unavailable."""
    if time is None:
        time = min((edge.base_height for edge in edges.values()), default=0.0)
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


def collect_loop_events(
    loop: WavefrontLoop,
    edges: dict[int, MovingLine],
    time: float | None = None,
    eps: float = 1e-9,
) -> tuple[WavefrontEvent, ...]:
    """Collect events, preferring one batched Rust call for larger active loops."""
    if time is None:
        time = min((edge.base_height for edge in edges.values()), default=0.0)

    if len(loop.edge_ids) >= 16:
        from .native_bridge import (
            NativeGeometryError,
            collect_wavefront_events_native,
        )

        try:
            raw_events = collect_wavefront_events_native(
                (edges[edge_id] for edge_id in loop.edge_ids),
                loop.loop_id,
                time,
                eps,
            )
        except NativeGeometryError as exc:
            raise GeometryInputError(exc.code, exc.message) from exc

        if raw_events is not None:
            kinds = (
                EventKind.EDGE_COLLAPSE,
                EventKind.SPLIT_CANDIDATE,
                EventKind.VERTEX_HIT,
            )
            return tuple(
                WavefrontEvent(
                    kinds[kind],
                    event_time,
                    loop.loop_id,
                    edge_id=edge_id,
                    vertex_id=vertex_id,
                    target_edge_id=target_edge_id,
                    position=position,
                    participant_generations=tuple(participants),
                    loop_generation=loop.generation,
                )
                for (
                    kind,
                    event_time,
                    edge_id,
                    vertex_id,
                    target_edge_id,
                    position,
                    participants,
                ) in raw_events
            )

    return _collect_loop_events_python(loop, edges, time, eps)



def apply_split_event(
    loop: WavefrontLoop,
    edges: dict[int, MovingLine],
    event: WavefrontEvent,
    *,
    next_edge_id: int | None = None,
    next_loop_id: int | None = None,
    eps: float = 1e-9,
    validate_children: bool = True,
) -> SplitResult:
    """Split one wavefront loop at a validated reflex-vertex/edge hit.

    The target edge is replaced by two collinear moving-edge instances that
    retain the same source-edge identity and weighted supporting line. The
    old loop becomes two child loops. This operation is pure: it returns new
    dictionaries and never mutates the caller's loop or edge map.

    Only strict interior split events are supported. Endpoint hits, stale
    generations, non-reflex vertices, and degenerate child loops are rejected.
    """
    if event.kind != EventKind.SPLIT_CANDIDATE:
        raise GeometryInputError(
            "NOT_A_SPLIT_EVENT",
            "Для изменения топологии требуется подтверждённый SPLIT_CANDIDATE."
        )
    if event.loop_id != loop.loop_id or event.loop_generation != loop.generation:
        raise GeometryInputError("STALE_SPLIT_EVENT", "Split-событие относится к устаревшей версии контура.")
    if event.vertex_id is None or event.target_edge_id is None:
        raise GeometryInputError("INCOMPLETE_SPLIT_EVENT", "Split-событие не содержит вершину или целевое ребро.")
    count = len(loop.edge_ids)
    if count < 4 or not (0 <= event.vertex_id < count):
        raise GeometryInputError("INVALID_SPLIT_TOPOLOGY", "Для split требуется контур минимум из четырёх рёбер.")
    if event.edge_id != loop.edge_ids[event.vertex_id]:
        raise GeometryInputError("STALE_SPLIT_EVENT", "Активное ребро рефлексной вершины уже изменилось.")
    if event.target_edge_id not in loop.edge_ids:
        raise GeometryInputError("STALE_SPLIT_EVENT", "Целевое ребро больше не принадлежит волновому фронту.")

    vertex_index = event.vertex_id
    target_index = loop.edge_ids.index(event.target_edge_id)
    adjacent_ids = {
        loop.edge_ids[vertex_index - 1],
        loop.edge_ids[vertex_index],
    }
    if event.target_edge_id in adjacent_ids:
        raise GeometryInputError("ADJACENT_SPLIT_TARGET", "Рефлексная вершина не может расщеплять соседнее ребро.")

    required_edge_ids = {
        loop.edge_ids[vertex_index - 1],
        loop.edge_ids[vertex_index],
        event.target_edge_id,
        loop.edge_ids[target_index - 1],
        loop.edge_ids[(target_index + 1) % count],
    }
    for edge_id, generation in event.participant_generations:
        if edge_id in required_edge_ids and (
            edge_id not in edges or edges[edge_id].generation != generation
        ):
            raise GeometryInputError("STALE_SPLIT_EVENT", "Версия одного из рёбер-участников split-события изменилась.")

    time_scale = max(1.0, abs(event.time))
    tolerance = eps * time_scale * 100.0
    vertices = _loop_vertices(loop, edges, event.time, eps)
    current = vertices[vertex_index]
    polygon_now = [vertex.point for vertex in vertices]
    winding = 1 if signed_area(polygon_now) > 0.0 else -1
    incoming = _sub(current.point, polygon_now[vertex_index - 1])
    outgoing = _sub(polygon_now[(vertex_index + 1) % count], current.point)
    turn = _cross2(incoming, outgoing)
    if turn * winding >= -tolerance:
        raise GeometryInputError("SPLIT_VERTEX_NOT_REFLEX", "В момент события вершина уже не является рефлексной.")

    target = edges[event.target_edge_id]
    line_distance = _dot(target.normal, current.point) - target.offset_at(event.time)
    if abs(line_distance) > tolerance:
        raise GeometryInputError("SPLIT_MISS", "Рефлексная вершина не лежит на целевой движущейся прямой в момент события.")

    target_start = _line_intersection(
        edges[loop.edge_ids[target_index - 1]], target, event.time, eps
    ).point
    target_end = _line_intersection(
        target, edges[loop.edge_ids[(target_index + 1) % count]], event.time, eps
    ).point
    target_length = _dot(_sub(target_end, target_start), target.tangent)
    coordinate = _dot(_sub(current.point, target_start), target.tangent)
    segment_tolerance = eps * max(1.0, abs(target_length)) * 100.0
    if target_length <= segment_tolerance:
        raise GeometryInputError("SPLIT_TARGET_COLLAPSED", "Целевое ребро схлопнулось до split-события.")
    if coordinate <= segment_tolerance or coordinate >= target_length - segment_tolerance:
        raise GeometryInputError("SPLIT_ENDPOINT_HIT", "Попадание в конец ребра не является внутренним split-событием.")

    if event.position is not None and hypot(
        event.position[0] - current.point[0],
        event.position[1] - current.point[1],
    ) > tolerance * 10.0:
        raise GeometryInputError("STALE_SPLIT_POSITION", "Позиция split-события не совпадает с текущей траекторией вершины.")

    # Generate two new edge instances for the two finite portions of the same
    # moving target line. Both preserve the authored source-edge identity.
    first_new_edge = max(edges, default=-1) + 1 if next_edge_id is None else next_edge_id
    second_new_edge = first_new_edge + 1
    if first_new_edge in edges or second_new_edge in edges or first_new_edge == second_new_edge:
        raise GeometryInputError("EDGE_ID_COLLISION", "Новые edge-instance ID уже используются.")
    left_copy = MovingLine(
        first_new_edge, target.source_edge_id, target.normal, target.offset,
        target.speed, target.tangent, 0, target.base_height,
    )
    right_copy = MovingLine(
        second_new_edge, target.source_edge_id, target.normal, target.offset,
        target.speed, target.tangent, 0, target.base_height,
    )

    def cyclic_path(start_index: int, stop_index: int) -> tuple[int, ...]:
        path = []
        index = start_index
        while index != stop_index:
            path.append(loop.edge_ids[index])
            index = (index + 1) % count
            if len(path) > count:
                raise GeometryInputError("INVALID_SPLIT_PATH", "Не удалось разделить последовательность рёбер.")
        return tuple(path)

    first_path = cyclic_path(vertex_index, target_index)
    second_path = cyclic_path((target_index + 1) % count, vertex_index)
    first_ids = first_path + (first_new_edge,)
    second_ids = (second_new_edge,) + second_path
    if len(first_ids) < 3 or len(second_ids) < 3:
        raise GeometryInputError("DEGENERATE_SPLIT_LOOP", "Split-событие создало контур менее чем из трёх рёбер.")

    first_loop_id = loop.loop_id
    second_loop_id = max(loop.loop_id, next_loop_id - 1) + 1 if next_loop_id is not None else loop.loop_id + 1
    if second_loop_id == first_loop_id:
        raise GeometryInputError("LOOP_ID_COLLISION", "Новый loop ID совпадает с исходным.")

    new_edges = dict(edges)
    del new_edges[event.target_edge_id]
    new_edges[first_new_edge] = left_copy
    new_edges[second_new_edge] = right_copy
    generation = loop.generation + 1
    children = (
        WavefrontLoop(first_loop_id, first_ids, generation),
        WavefrontLoop(second_loop_id, second_ids, generation),
    )

    # The split point is shared by both child loops at the event instant. Each
    # child must form a non-degenerate, consistently oriented polygon. A
    # compound split/collapse event may temporarily contain its explicitly
    # collapsing edge; that case validates the children after the collapse.
    if validate_children:
        for child in children:
            child_vertices = _loop_vertices(child, new_edges, event.time, eps)
            child_polygon = [vertex.point for vertex in child_vertices]
            child_area = signed_area(child_polygon)
            if abs(child_area) <= tolerance * tolerance:
                raise GeometryInputError("DEGENERATE_SPLIT_LOOP", "Split-событие создало контур нулевой площади.")
            if (1 if child_area > 0.0 else -1) != winding:
                raise GeometryInputError("SPLIT_WINDING_CHANGED", "После split изменилась ориентация одного из дочерних контуров.")
            if validate_simple_polygon(child_polygon, eps):
                raise GeometryInputError("SPLIT_LOOP_NOT_SIMPLE", "Split-событие создало самопересекающийся контур.")

    next_loop = max(first_loop_id, second_loop_id) + 1
    return SplitResult(
        loops=children,
        edges=new_edges,
        event_position=current.point,
        next_edge_id=second_new_edge + 1,
        next_loop_id=next_loop,
    )


def create_wavefront_state(
    points: Sequence[Point3],
    pitches_degrees: Sequence[float],
    eps: float = 1e-9,
) -> WavefrontSimulationState:
    """Initialize a global event-driven wavefront state from one flat-eave loop."""
    edges_tuple = build_moving_lines(points, pitches_degrees, eps)
    edges = {edge.edge_id: edge for edge in edges_tuple}
    loop = WavefrontLoop(0, tuple(edge.edge_id for edge in edges_tuple), 0)
    base_height = sum(point[2] for point in points) / len(points)
    vertices = _loop_vertices(loop, edges, base_height, eps)
    if abs(_signed_area_at(vertices)) <= eps:
        raise GeometryInputError("DEGENERATE_INITIAL_WAVEFRONT", "Начальный волновой фронт имеет нулевую площадь.")

    scale = max(
        1.0,
        max(point[0] for point in points) - min(point[0] for point in points),
        max(point[1] for point in points) - min(point[1] for point in points),
    )
    queue = WavefrontEventQueue()
    source_area = abs(signed_area([(point[0], point[1]) for point in points]))
    queue.push_many(collect_loop_events(loop, edges, base_height, eps))
    return WavefrontSimulationState(
        current_time=base_height,
        loops={loop.loop_id: loop},
        edges=edges,
        event_queue=queue,
        next_edge_id=max(edges, default=-1) + 1,
        next_loop_id=loop.loop_id + 1,
        time_tolerance=eps * max(1.0, scale) * 100.0,
        epsilon=eps,
        source_area=source_area,
        input_winding=1 if signed_area([(point[0], point[1]) for point in points]) > 0.0 else -1,
    )


def _current_generation_maps(
    state: WavefrontSimulationState,
) -> tuple[dict[int, int], dict[int, int]]:
    edge_generations = {edge_id: edge.generation for edge_id, edge in state.edges.items()}
    loop_generations = {loop_id: loop.generation for loop_id, loop in state.loops.items()}
    return edge_generations, loop_generations


def _resolve_edge_collapse_group(
    state: WavefrontSimulationState,
    loop: WavefrontLoop,
    events: Sequence[WavefrontEvent],
    *,
    needle_endpoints: tuple[Point2, Point2] | None = None,
) -> WavefrontLoop | None:
    """Apply one same-loop edge-collapse batch; return a child loop or terminate it."""
    collapsed = {event.edge_id for event in events}
    if None in collapsed or not collapsed:
        raise GeometryInputError("INCOMPLETE_COLLAPSE_BATCH", "Событие схлопывания не содержит ID ребра.")
    if any(edge_id not in loop.edge_ids for edge_id in collapsed):
        raise GeometryInputError("STALE_COLLAPSE_EVENT", "Схлопываемое ребро больше не принадлежит активному контуру.")

    remaining = tuple(edge_id for edge_id in loop.edge_ids if edge_id not in collapsed)
    needle_arc: tuple[Point2, Point2] | None = None

    # When two fronts remain, validate their finite segments, not only their
    # infinite supporting lines. This prevents a partial overlap from being
    # silently promoted to a complete needle.
    if len(remaining) == 2:
        first, second = state.edges[remaining[0]], state.edges[remaining[1]]
        alignment = _dot(first.normal, second.normal)
        first_offset = first.offset_at(state.current_time)
        second_offset = second.offset_at(state.current_time)
        gap = first_offset + second_offset
        if alignment > -1.0 + state.epsilon * 100.0 or abs(gap) > (
            state.epsilon * max(1.0, abs(first_offset), abs(second_offset)) * 100.0
        ):
            raise GeometryInputError(
                "TWO_EDGE_TERMINATION_UNRESOLVED",
                "После схлопывания остались два фронта, но их опорные прямые не образуют needle-пару."
            )

        if needle_endpoints is not None:
            # In a compound split/collapse event the two fronts can already be
            # coincident and adjacent in the child loop. Their intersection is
            # undefined, so use the independently revalidated split and
            # collapse event points as the finite overlap endpoints.
            scale = max(
                1.0,
                abs(first_offset),
                abs(second_offset),
                hypot(
                    needle_endpoints[1][0] - needle_endpoints[0][0],
                    needle_endpoints[1][1] - needle_endpoints[0][1],
                ),
            )
            tolerance = state.epsilon * scale * 100.0
            if any(
                abs(_dot(line.normal, point) - line.offset_at(state.current_time)) > tolerance
                for line in (first, second)
                for point in needle_endpoints
            ):
                raise GeometryInputError(
                    "SPLIT_COLLAPSE_NEEDLE_ENDPOINT_MISMATCH",
                    "Точки split/collapse не лежат на обеих совпавших конечных линиях."
                )
            if hypot(
                needle_endpoints[1][0] - needle_endpoints[0][0],
                needle_endpoints[1][1] - needle_endpoints[0][1],
            ) <= tolerance:
                raise GeometryInputError(
                    "DEGENERATE_SPLIT_COLLAPSE_NEEDLE",
                    "Общая конечная часть фронтов выродилась в точку."
                )
            needle_arc = needle_endpoints
        else:
            vertices = _loop_vertices(loop, state.edges, state.current_time, state.epsilon)
            first_index = loop.edge_ids.index(remaining[0])
            second_index = loop.edge_ids.index(remaining[1])
            first_segment = _edge_segment(
                loop, first_index, vertices, state.edges, state.current_time
            )
            second_segment = _edge_segment(
                loop, second_index, vertices, state.edges, state.current_time
            )
            tolerance = state.epsilon * max(
                1.0, abs(first_offset), abs(second_offset),
                first_segment[3], second_segment[3],
            ) * 100.0
            endpoints_match = (
                hypot(first_segment[0][0] - second_segment[1][0],
                      first_segment[0][1] - second_segment[1][1]) <= tolerance
                and hypot(first_segment[1][0] - second_segment[0][0],
                          first_segment[1][1] - second_segment[0][1]) <= tolerance
            )
            if (
                first_segment[3] <= tolerance
                or second_segment[3] <= tolerance
                or not endpoints_match
            ):
                raise GeometryInputError(
                    "PARTIAL_OVERLAP_NEEDLE_UNRESOLVED",
                    "Оставшиеся противоположные фронты совпадают не полными конечными отрезками; "
                    "частичное перекрытие требует отдельного split/overlap-разрешителя."
                )
            needle_arc = (first_segment[0], first_segment[1])

    for edge_id in collapsed:
        state.edges.pop(edge_id, None)

    if len(remaining) >= 3:
        return WavefrontLoop(loop.loop_id, remaining, loop.generation + 1)

    if len(remaining) == 2:
        state.terminal_loops[loop.loop_id] = "NEEDLE"
        if needle_arc is not None:
            start, end = needle_arc
            state.skeleton_arcs.append(SkeletonArc(
                (start[0], start[1], state.current_time),
                (end[0], end[1], state.current_time),
                state.current_time,
            ))
        state.edges.pop(remaining[0], None)
        state.edges.pop(remaining[1], None)
        return None

    state.terminal_loops[loop.loop_id] = "POINT"
    for edge_id in remaining:
        state.edges.pop(edge_id, None)
    return None


def _record_wavefront_interval(
    state: WavefrontSimulationState,
    start_time: float,
    end_time: float,
) -> None:
    """Collect exact swept edge fragments and vertex trajectories for one interval."""
    dt = end_time - start_time
    if dt < -state.time_tolerance:
        raise GeometryInputError("TIME_ORDER", "Нельзя записать интервал волнового фронта с отрицательной длительностью.")
    if dt <= state.time_tolerance:
        return

    for loop_id in sorted(state.loops):
        loop = state.loops[loop_id]
        vertices_start = _loop_vertices(loop, state.edges, start_time, state.epsilon)
        vertices_end = _loop_vertices(loop, state.edges, end_time, state.epsilon)

        # Each moving wavefront vertex traces a straight skeleton arc between
        # two consecutive event heights.
        for first, second in zip(vertices_start, vertices_end):
            distance = hypot(
                second.point[0] - first.point[0],
                second.point[1] - first.point[1],
            )
            if distance > state.epsilon:
                state.skeleton_arcs.append(SkeletonArc(
                    (first.point[0], first.point[1], start_time),
                    (second.point[0], second.point[1], end_time),
                    end_time,
                ))

        for index, edge_id in enumerate(loop.edge_ids):
            start0, end0, _, _ = _edge_segment(
                loop, index, vertices_start, state.edges, start_time
            )
            start1, end1, _, end_length = _edge_segment(
                loop, index, vertices_end, state.edges, end_time
            )
            if end_length < -state.time_tolerance:
                raise GeometryInputError(
                    "NEGATIVE_EDGE_AT_EVENT",
                    f"Ребро wavefront {edge_id} получило отрицательную длину перед событием."
                )
            line = state.edges[edge_id]
            fragment = _dedupe_polygon((
                (start0[0], start0[1], start_time),
                (end0[0], end0[1], start_time),
                (end1[0], end1[1], end_time),
                (start1[0], start1[1], end_time),
            ), state.time_tolerance)
            if len(fragment) < 3 or _projected_area(fragment) <= state.time_tolerance ** 2:
                continue
            for x, y, z in fragment:
                expected_z = line.base_height + (
                    _dot(line.normal, (x, y)) - line.offset
                ) / line.speed
                if abs(expected_z - z) > max(
                    state.time_tolerance * 10.0,
                    state.epsilon * max(1.0, abs(z)) * 1000.0,
                ):
                    raise GeometryInputError(
                        "FACET_NOT_PLANAR",
                        f"Фрагмент исходного ската {line.source_edge_id + 1} не лежит на его точной плоскости."
                    )
            state.facets.append(FacetFragment(
                source_edge_id=line.source_edge_id,
                start_time=start_time,
                end_time=end_time,
                vertices=fragment,
            ))



def _resolve_simultaneous_point_termination(
    state: WavefrontSimulationState,
    loop: WavefrontLoop,
    events: Sequence[WavefrontEvent],
) -> bool:
    """Resolve a mixed endpoint/collapse batch only when the whole loop dies at one point.

    Some symmetric concave contours make every active front collapse at the
    same node. Their event queue contains many endpoint hits as well as edge
    collapses, which is not a cross-needle. Revalidate the complete geometry
    at the batch time before accepting this terminal case.
    """
    if not events or len(loop.edge_ids) < 3:
        return False
    if any(
        event.kind not in {EventKind.EDGE_COLLAPSE, EventKind.VERTEX_HIT}
        or event.loop_id != loop.loop_id
        or event.loop_generation != loop.generation
        or event.position is None
        for event in events
    ):
        return False

    edge_ids = set(loop.edge_ids)
    for event in events:
        if event.kind == EventKind.EDGE_COLLAPSE:
            if event.edge_id not in edge_ids:
                return False
        else:
            if (
                event.edge_id not in edge_ids
                or event.target_edge_id not in edge_ids
                or event.vertex_id is None
                or not 0 <= event.vertex_id < len(loop.edge_ids)
                or event.edge_id != loop.edge_ids[event.vertex_id]
            ):
                return False

    # The event-time tolerance is based on the original contour scale. A
    # slightly wider spatial tolerance accommodates the time-batch grouping,
    # but does not allow a finite surviving edge or multiple terminal nodes.
    tolerance = state.time_tolerance * 10.0
    vertices = _loop_vertices(loop, state.edges, state.current_time, state.epsilon)
    anchor = vertices[0].point
    if any(
        hypot(vertex.point[0] - anchor[0], vertex.point[1] - anchor[1]) > tolerance
        for vertex in vertices[1:]
    ):
        return False

    if any(
        hypot(event.position[0] - anchor[0], event.position[1] - anchor[1]) > tolerance
        for event in events
    ):
        return False

    for index in range(len(loop.edge_ids)):
        _, _, _, length = _edge_segment(
            loop, index, vertices, state.edges, state.current_time
        )
        if abs(length) > tolerance:
            return False

    state.terminal_loops[loop.loop_id] = "POINT"
    state.loops.pop(loop.loop_id, None)
    for edge_id in loop.edge_ids:
        state.edges.pop(edge_id, None)
    return True


def _resolve_vertex_hit_on_collapsing_edge(
    state: WavefrontSimulationState,
    loop: WavefrontLoop,
    events: Sequence[WavefrontEvent],
) -> bool:
    """Consume endpoint hits that are exactly an endpoint of a collapsing edge.

    A reflex vertex can hit the neighboring edge beyond a collapsing front at
    the same instant that the front collapses. The hit is not a separate split:
    removing the collapsed edge already creates that successor vertex.
    """
    collapse_events = [
        event for event in events if event.kind == EventKind.EDGE_COLLAPSE
    ]
    hit_events = [
        event for event in events if event.kind == EventKind.VERTEX_HIT
    ]
    if not collapse_events or not hit_events:
        return False
    if len(collapse_events) + len(hit_events) != len(events):
        return False

    collapse_by_edge = {
        event.edge_id: event for event in collapse_events
        if event.edge_id is not None
    }
    if len(collapse_by_edge) != len(collapse_events):
        return False
    loop_edge_ids = loop.edge_ids
    edge_set = set(loop_edge_ids)
    if not set(collapse_by_edge).issubset(edge_set):
        return False

    tolerance = state.time_tolerance * 10.0
    vertices = _loop_vertices(
        loop, state.edges, state.current_time, state.epsilon
    )
    paired_hits: dict[int, WavefrontEvent] = {}

    for event in hit_events:
        if (
            event.edge_id is None
            or event.edge_id not in edge_set
            or event.target_edge_id is None
            or event.target_edge_id not in edge_set
            or event.position is None
            or event.vertex_id is None
            or event.loop_id != loop.loop_id
            or event.loop_generation != loop.generation
            or not 0 <= event.vertex_id < len(loop_edge_ids)
            or loop_edge_ids[event.vertex_id] != event.edge_id
        ):
            return False

        vertex_index = event.vertex_id
        count = len(loop_edge_ids)
        current_edge = loop_edge_ids[vertex_index]
        next_edge = loop_edge_ids[(vertex_index + 1) % count]
        previous_edge = loop_edge_ids[(vertex_index - 1) % count]
        previous_previous_edge = loop_edge_ids[(vertex_index - 2) % count]

        candidates = []
        # The hit vertex is the start endpoint of the collapsing current edge.
        if (
            current_edge in collapse_by_edge
            and event.target_edge_id == next_edge
            and next_edge not in collapse_by_edge
        ):
            candidates.append(current_edge)
        # Or it is the end endpoint of the collapsing previous edge.
        if (
            previous_edge in collapse_by_edge
            and event.target_edge_id == previous_previous_edge
            and previous_previous_edge not in collapse_by_edge
        ):
            candidates.append(previous_edge)
        if len(candidates) != 1:
            return False

        collapsed_edge_id = candidates[0]
        if collapsed_edge_id in paired_hits:
            return False
        collapse = collapse_by_edge[collapsed_edge_id]
        if collapse.position is None:
            return False

        edge_index = loop_edge_ids.index(collapsed_edge_id)
        start, end, _, length = _edge_segment(
            loop, edge_index, vertices, state.edges, state.current_time
        )
        if abs(length) > tolerance:
            return False

        event_point = collapse.position
        for point in (
            event.position,
            vertices[vertex_index].point,
            start,
            end,
        ):
            if hypot(point[0] - event_point[0], point[1] - event_point[1]) > tolerance:
                return False

        target = state.edges[event.target_edge_id]
        residual = (
            _dot(target.normal, event_point)
            - target.offset_at(state.current_time)
        )
        if abs(residual) > tolerance:
            return False
        paired_hits[collapsed_edge_id] = event

    collapsed = set(collapse_by_edge)
    remaining = tuple(
        edge_id for edge_id in loop_edge_ids if edge_id not in collapsed
    )
    if len(remaining) >= 3:
        prospective = WavefrontLoop(
            loop.loop_id, remaining, loop.generation + 1
        )
        new_vertices = _loop_vertices(
            prospective, state.edges, state.current_time, state.epsilon
        )
        polygon = [vertex.point for vertex in new_vertices]
        scale = max(
            1.0,
            max(point[0] for point in polygon) - min(point[0] for point in polygon),
            max(point[1] for point in polygon) - min(point[1] for point in polygon),
        )
        area = signed_area(polygon)
        if (
            abs(area) <= state.epsilon * scale * scale * 100.0
            or (1 if area > 0.0 else -1) != state.input_winding
            or validate_simple_polygon(polygon, state.epsilon)
        ):
            return False

    child = _resolve_edge_collapse_group(
        state, loop, collapse_events
    )
    state.loops.pop(loop.loop_id, None)
    if child is not None:
        state.loops[child.loop_id] = child
    return True


def _resolve_cross_needle_vertex_hit(
    state: WavefrontSimulationState,
    loop: WavefrontLoop,
    events: Sequence[WavefrontEvent],
) -> bool:
    """Resolve simultaneous reflex endpoint hits forming multiple needle nodes.

    Endpoint hits are grouped by reflex vertex. Each group must contain exactly
    two hits on adjacent target edges, proving the reflex vertex reached their
    common wavefront endpoint. After the simultaneous edge collapses, every
    remaining finite front must pair with one opposite, coincident finite
    segment at the event height. The paired segments must match endpoint to
    endpoint, but their propagation speeds may differ: equality is required
    at the collision instant, not throughout motion.

    This covers the L-shaped one-node cross-needle and the U-shaped
    multi-node event. It is deliberately not a generic simultaneous-event
    resolver.
    """
    endpoint_hits = [event for event in events if event.kind == EventKind.VERTEX_HIT]
    collapse_events = [event for event in events if event.kind == EventKind.EDGE_COLLAPSE]
    if len(endpoint_hits) < 2 or len(endpoint_hits) % 2:
        return False
    if len(endpoint_hits) + len(collapse_events) != len(events):
        return False

    hits_by_vertex: dict[int, list[WavefrontEvent]] = {}
    for event in endpoint_hits:
        if event.vertex_id is None:
            return False
        hits_by_vertex.setdefault(event.vertex_id, []).append(event)

    if not hits_by_vertex:
        return False
    positions: list[Point2] = []
    for vertex_id, hits in sorted(hits_by_vertex.items()):
        if len(hits) != 2:
            return False
        first_hit, second_hit = hits
        if (
            first_hit.edge_id is None
            or first_hit.edge_id != second_hit.edge_id
            or first_hit.target_edge_id is None
            or second_hit.target_edge_id is None
            or first_hit.position is None
            or second_hit.position is None
        ):
            return False
        if hypot(
            first_hit.position[0] - second_hit.position[0],
            first_hit.position[1] - second_hit.position[1],
        ) > state.time_tolerance * 10.0:
            return False
        target_a = loop.edge_ids.index(first_hit.target_edge_id)
        target_b = loop.edge_ids.index(second_hit.target_edge_id)
        count = len(loop.edge_ids)
        if (target_a - target_b) % count not in {1, count - 1}:
            return False
        positions.append(first_hit.position)

    # Distinct reflex vertices must hit distinct nodes. If two groups collapse
    # to the same point, they belong to a higher-order event not handled here.
    for index, first in enumerate(positions):
        for second in positions[index + 1:]:
            if hypot(first[0] - second[0], first[1] - second[1]) <= state.time_tolerance * 10.0:
                return False

    collapsed = {event.edge_id for event in collapse_events}
    if None in collapsed:
        return False
    remaining = [edge_id for edge_id in loop.edge_ids if edge_id not in collapsed]
    if len(remaining) < 2 or len(remaining) % 2:
        return False

    vertices = _loop_vertices(loop, state.edges, state.current_time, state.epsilon)
    segments = {}
    for index, edge_id in enumerate(loop.edge_ids):
        if edge_id in collapsed:
            continue
        start, end, tangent, length = _edge_segment(
            loop, index, vertices, state.edges, state.current_time
        )
        segments[edge_id] = (start, end, tangent, length)

    unused = set(remaining)
    matched_pairs: list[tuple[int, int, Point2, Point2]] = []
    while unused:
        first_id = min(unused)
        first_line = state.edges[first_id]
        first_segment = segments[first_id]
        partner = None
        for second_id in sorted(unused - {first_id}):
            second_line = state.edges[second_id]
            second_segment = segments[second_id]
            alignment = _dot(first_line.normal, second_line.normal)
            line_gap = first_line.offset_at(state.current_time) + second_line.offset_at(state.current_time)
            scale = max(
                1.0,
                abs(first_line.offset_at(state.current_time)),
                abs(second_line.offset_at(state.current_time)),
                first_segment[3],
                second_segment[3],
            )
            tol = state.epsilon * scale * 100.0
            endpoints_match = (
                hypot(first_segment[0][0] - second_segment[1][0],
                      first_segment[0][1] - second_segment[1][1]) <= tol
                and hypot(first_segment[1][0] - second_segment[0][0],
                           first_segment[1][1] - second_segment[0][1]) <= tol
            )
            if (
                alignment <= -1.0 + state.epsilon * 100.0
                and abs(line_gap) <= tol
                and first_segment[3] > tol
                and second_segment[3] > tol
                and abs(first_segment[3] - second_segment[3]) <= tol
                and endpoints_match
            ):
                partner = second_id
                break
        if partner is None:
            return False
        matched_pairs.append((first_id, partner, first_segment[0], first_segment[1]))
        unused.remove(first_id)
        unused.remove(partner)

    for first_id, second_id, start, end in matched_pairs:
        state.skeleton_arcs.append(SkeletonArc(
            (start[0], start[1], state.current_time),
            (end[0], end[1], state.current_time),
            state.current_time,
        ))

    state.terminal_loops[loop.loop_id] = "MULTI_NEEDLE"
    for edge_id in loop.edge_ids:
        state.edges.pop(edge_id, None)
    state.loops.pop(loop.loop_id, None)
    return True


def _resolve_split_collapse_batch(
    state: WavefrontSimulationState,
    loop: WavefrontLoop,
    events: Sequence[WavefrontEvent],
) -> tuple[WavefrontLoop, ...]:
    """Resolve one strict split and one collapse occurring on the same loop/time.

    The split partitions the target front at the reflex hit. The collapsing
    edge must belong to exactly one child. That child's post-collapse topology
    is then validated independently; an opposite pair is terminal only when
    its finite segments coincide endpoint-to-endpoint.
    """
    split_events = [event for event in events if event.kind == EventKind.SPLIT_CANDIDATE]
    collapse_events = [event for event in events if event.kind == EventKind.EDGE_COLLAPSE]
    if len(split_events) != 1 or len(collapse_events) != 1 or len(events) != 2:
        raise GeometryInputError(
            "SIMULTANEOUS_SPLIT_COLLAPSE_UNRESOLVED",
            "Поддерживается только один строгий split вместе с одним схлопыванием на том же контуре."
        )

    collapse_event = collapse_events[0]
    if collapse_event.edge_id is None:
        raise GeometryInputError(
            "INCOMPLETE_COLLAPSE_BATCH",
            "Смешанное split/collapse-событие не содержит ID схлопываемого ребра."
        )

    split_result = apply_split_event(
        loop,
        state.edges,
        split_events[0],
        next_edge_id=state.next_edge_id,
        next_loop_id=state.next_loop_id,
        eps=state.epsilon,
        validate_children=False,
    )
    collapse_children = [
        child for child in split_result.loops
        if collapse_event.edge_id in child.edge_ids
    ]
    if len(collapse_children) != 1:
        raise GeometryInputError(
            "SPLIT_COLLAPSE_TOPOLOGY_UNRESOLVED",
            "Схлопываемое ребро должно принадлежать ровно одному дочернему контуру после split."
        )
    collapse_child = collapse_children[0]

    trial_state = WavefrontSimulationState(
        current_time=state.current_time,
        loops={child.loop_id: child for child in split_result.loops},
        edges=dict(split_result.edges),
        event_queue=WavefrontEventQueue(),
        next_edge_id=split_result.next_edge_id,
        next_loop_id=split_result.next_loop_id,
        time_tolerance=state.time_tolerance,
        epsilon=state.epsilon,
        terminal_loops=dict(state.terminal_loops),
        source_area=state.source_area,
        input_winding=state.input_winding,
    )

    collapse_index = collapse_child.edge_ids.index(collapse_event.edge_id)
    previous_edge = trial_state.edges[
        collapse_child.edge_ids[collapse_index - 1]
    ]
    collapsing_edge = trial_state.edges[collapse_event.edge_id]
    next_edge = trial_state.edges[
        collapse_child.edge_ids[(collapse_index + 1) % len(collapse_child.edge_ids)]
    ]
    collapse_start = _line_intersection(
        previous_edge, collapsing_edge,
        trial_state.current_time, trial_state.epsilon,
    ).point
    collapse_end = _line_intersection(
        collapsing_edge, next_edge,
        trial_state.current_time, trial_state.epsilon,
    ).point
    collapse_length = _dot(
        _sub(collapse_end, collapse_start), collapsing_edge.tangent
    )
    if (
        abs(collapse_length) > trial_state.time_tolerance * 10.0
        or collapse_event.position is None
        or hypot(
            (collapse_start[0] + collapse_end[0]) * 0.5 - collapse_event.position[0],
            (collapse_start[1] + collapse_end[1]) * 0.5 - collapse_event.position[1],
        ) > trial_state.time_tolerance * 10.0
    ):
        raise GeometryInputError(
            "SPLIT_COLLAPSE_TIME_MISMATCH",
            "После split заявленное схлопываемое ребро не имеет подтверждённой нулевой длины в момент общего события."
        )

    collapsed_child = _resolve_edge_collapse_group(
        trial_state, collapse_child, (collapse_event,),
        needle_endpoints=(split_result.event_position, collapse_event.position),
    )
    if collapsed_child is None:
        trial_state.loops.pop(collapse_child.loop_id, None)
    else:
        trial_state.loops[collapse_child.loop_id] = collapsed_child

    # Validate every surviving child after the zero-length edge has been
    # removed. No degenerate intermediate contour is exposed to the caller.
    for child in trial_state.loops.values():
        vertices = _loop_vertices(
            child, trial_state.edges, trial_state.current_time, trial_state.epsilon
        )
        polygon = [vertex.point for vertex in vertices]
        scale = max(
            1.0,
            max(point[0] for point in polygon) - min(point[0] for point in polygon),
            max(point[1] for point in polygon) - min(point[1] for point in polygon),
        )
        area = signed_area(polygon)
        if abs(area) <= trial_state.epsilon * scale * scale * 100.0:
            raise GeometryInputError(
                "DEGENERATE_SPLIT_COLLAPSE_CHILD",
                "Комбинированное событие создало активный контур нулевой площади."
            )
        if (1 if area > 0.0 else -1) != trial_state.input_winding:
            raise GeometryInputError(
                "SPLIT_COLLAPSE_WINDING_CHANGED",
                "Комбинированное событие изменило ориентацию дочернего контура."
            )
        if validate_simple_polygon(polygon, trial_state.epsilon):
            raise GeometryInputError(
                "SPLIT_COLLAPSE_CHILD_NOT_SIMPLE",
                "После split/collapse остался самопересекающийся дочерний контур."
            )

    # Commit the compound topology only after both resulting children pass.
    state.loops.pop(loop.loop_id, None)
    state.loops.update(trial_state.loops)
    state.edges = trial_state.edges
    state.next_edge_id = trial_state.next_edge_id
    state.next_loop_id = trial_state.next_loop_id
    state.terminal_loops = trial_state.terminal_loops
    state.skeleton_arcs.extend(trial_state.skeleton_arcs)
    return tuple(state.loops[key] for key in sorted(trial_state.loops))



def _resolve_multiple_split_batch(
    state: WavefrontSimulationState,
    loop: WavefrontLoop,
    events: Sequence[WavefrontEvent],
) -> tuple[WavefrontLoop, ...]:
    """Resolve several same-time split candidates by repeated revalidation.

    A split replaces its target edge with two instances, so later events from
    the original queue can become stale by edge ID even though the geometric
    event is still valid. Recompute candidates after each accepted split and
    match by authored source-edge IDs plus event position. This allows
    independent multi-notch splits without accepting stale or ambiguous
    topology.
    """
    if len(events) < 2 or any(event.kind != EventKind.SPLIT_CANDIDATE for event in events):
        raise GeometryInputError(
            "MULTI_SPLIT_INVALID_BATCH",
            "Для multi-split resolver требуется минимум два строгих split-события."
        )

    original_edges = dict(state.edges)
    working_edges = dict(state.edges)
    working_loops: list[WavefrontLoop] = [loop]
    next_edge_id = state.next_edge_id
    next_loop_id = state.next_loop_id
    position_tolerance = state.time_tolerance * 10.0

    ordered_events = sorted(events, key=WavefrontEventQueue._event_key)
    for original_event in ordered_events:
        if original_event.edge_id is None or original_event.target_edge_id is None:
            raise GeometryInputError(
                "INCOMPLETE_SPLIT_EVENT",
                "Одновременный split не содержит ID исходной вершины или целевого ребра."
            )
        if original_event.position is None:
            raise GeometryInputError(
                "INCOMPLETE_SPLIT_EVENT",
                "Одновременный split не содержит подтверждённую позицию события."
            )
        try:
            original_edge = original_edges[original_event.edge_id]
            original_target = original_edges[original_event.target_edge_id]
        except KeyError as exc:
            raise GeometryInputError(
                "STALE_SPLIT_EVENT",
                "Одно из одновременных split-событий уже не имеет исходного ребра."
            ) from exc

        candidates: list[tuple[WavefrontLoop, WavefrontEvent]] = []
        for candidate_loop in working_loops:
            fresh_events = find_split_candidates(
                candidate_loop,
                working_edges,
                state.current_time,
                state.epsilon,
            )
            for fresh_event in fresh_events:
                if fresh_event.kind != EventKind.SPLIT_CANDIDATE:
                    continue
                if fresh_event.position is None:
                    continue
                if abs(fresh_event.time - original_event.time) > state.time_tolerance:
                    continue
                if (
                    working_edges[fresh_event.edge_id].source_edge_id
                    != original_edge.source_edge_id
                    or working_edges[fresh_event.target_edge_id].source_edge_id
                    != original_target.source_edge_id
                ):
                    continue
                if hypot(
                    fresh_event.position[0] - original_event.position[0],
                    fresh_event.position[1] - original_event.position[1],
                ) > position_tolerance:
                    continue
                candidates.append((candidate_loop, fresh_event))

        if len(candidates) != 1:
            details = [
                (
                    candidate_loop.loop_id,
                    candidate_event.edge_id,
                    candidate_event.target_edge_id,
                    candidate_event.position,
                    candidate_event.time,
                )
                for candidate_loop, candidate_event in candidates
            ]
            raise GeometryInputError(
                "SIMULTANEOUS_SPLIT_AMBIGUOUS",
                "Одновременный split нельзя однозначно переподтвердить после предыдущих split-событий. "
                f"Исходное событие: {original_event}; кандидаты: {details}."
            )

        candidate_loop, fresh_event = candidates[0]
        result = apply_split_event(
            candidate_loop,
            working_edges,
            fresh_event,
            next_edge_id=next_edge_id,
            next_loop_id=next_loop_id,
            eps=state.epsilon,
            validate_children=False,
        )
        remaining_loops = [
            candidate
            for candidate in working_loops
            if candidate.loop_id != candidate_loop.loop_id
        ]
        working_loops = remaining_loops + list(result.loops)
        working_edges = result.edges
        next_edge_id = result.next_edge_id
        next_loop_id = result.next_loop_id

    for child in working_loops:
        vertices = _loop_vertices(
            child, working_edges, state.current_time, state.epsilon
        )
        polygon = [vertex.point for vertex in vertices]
        scale = max(
            1.0,
            max(point[0] for point in polygon) - min(point[0] for point in polygon),
            max(point[1] for point in polygon) - min(point[1] for point in polygon),
        )
        area = signed_area(polygon)
        if abs(area) <= state.epsilon * scale * scale * 100.0:
            raise GeometryInputError(
                "DEGENERATE_MULTI_SPLIT_CHILD",
                "Одновременные split-события создали контур нулевой площади."
            )
        if (1 if area > 0.0 else -1) != state.input_winding:
            raise GeometryInputError(
                "MULTI_SPLIT_WINDING_CHANGED",
                "После одновременных split-событий изменилась ориентация дочернего контура."
            )
        if validate_simple_polygon(polygon, state.epsilon):
            raise GeometryInputError(
                "MULTI_SPLIT_CHILD_NOT_SIMPLE",
                "После одновременных split-событий остался самопересекающийся контур."
            )

    state.loops.pop(loop.loop_id, None)
    state.loops.update({child.loop_id: child for child in working_loops})
    state.edges = working_edges
    state.next_edge_id = next_edge_id
    state.next_loop_id = next_loop_id
    return tuple(
        state.loops[loop_id]
        for loop_id in sorted(state.loops)
        if loop_id in {child.loop_id for child in working_loops}
    )


def advance_wavefront_state(
    state: WavefrontSimulationState,
) -> EventBatch | None:
    """Advance all live loops to and process the globally earliest event batch.

    Independent loops may process events at the same time. A same-loop
    batch is resolved only when every topology mutation is explicitly
    revalidated; unsupported mixed event groups fail without partial output.
    """
    if state.is_complete:
        return None

    edge_generations, loop_generations = _current_generation_maps(state)
    batch = state.event_queue.pop_next_batch(
        current_time=state.current_time,
        time_tolerance=state.time_tolerance,
        current_edge_generations=edge_generations,
        current_loop_generations=loop_generations,
    )
    if batch is None:
        raise GeometryInputError(
            "NO_VALID_WAVEFRONT_EVENTS",
            "Для активных контуров не осталось актуальных событий волнового фронта."
        )

    previous_time = state.current_time
    _record_wavefront_interval(state, previous_time, batch.time)
    state.current_time = batch.time
    state.processed_events.extend(batch.events)
    events_by_loop: dict[int, list[WavefrontEvent]] = {}
    for event in batch.events:
        events_by_loop.setdefault(event.loop_id, []).append(event)

    changed_loops: list[WavefrontLoop] = []
    for loop_id in sorted(events_by_loop):
        loop = state.loops.get(loop_id)
        if loop is None:
            # This should be impossible after generation validation, but keep
            # the state machine fail-safe if an external caller mutates state.
            raise GeometryInputError("STALE_LOOP_EVENT", "Событие ссылается на отсутствующий активный контур.")
        loop_events = events_by_loop[loop_id]
        kinds = {event.kind for event in loop_events}

        if kinds == {EventKind.SPLIT_CANDIDATE, EventKind.EDGE_COLLAPSE}:
            changed_loops.extend(_resolve_split_collapse_batch(state, loop, loop_events))

        elif kinds == {EventKind.SPLIT_CANDIDATE}:
            if len(loop_events) == 1:
                result = apply_split_event(
                    loop,
                    state.edges,
                    loop_events[0],
                    next_edge_id=state.next_edge_id,
                    next_loop_id=state.next_loop_id,
                    eps=state.epsilon,
                )
                del state.loops[loop_id]
                state.edges = result.edges
                for child in result.loops:
                    state.loops[child.loop_id] = child
                    changed_loops.append(child)
                state.next_edge_id = result.next_edge_id
                state.next_loop_id = result.next_loop_id
            else:
                changed_loops.extend(
                    _resolve_multiple_split_batch(state, loop, loop_events)
                )

        elif kinds == {EventKind.EDGE_COLLAPSE}:
            child = _resolve_edge_collapse_group(state, loop, loop_events)
            del state.loops[loop_id]
            if child is not None:
                state.loops[child.loop_id] = child
                changed_loops.append(child)

        elif EventKind.VERTEX_HIT in kinds:
            resolved = (
                _resolve_simultaneous_point_termination(state, loop, loop_events)
                or _resolve_vertex_hit_on_collapsing_edge(state, loop, loop_events)
                or (
                    kinds.issubset({EventKind.EDGE_COLLAPSE, EventKind.VERTEX_HIT})
                    and _resolve_cross_needle_vertex_hit(state, loop, loop_events)
                )
            )
            if not resolved:
                details = [
                    (event.kind.value, event.edge_id, event.vertex_id,
                     event.target_edge_id, event.position, event.time)
                    for event in sorted(loop_events, key=WavefrontEventQueue._event_key)
                ]
                raise GeometryInputError(
                    "SIMULTANEOUS_EVENT_BATCH_UNRESOLVED",
                    "Смешанный endpoint/edge event не является ни подтверждённым общим point-termination, "
                    "ни проверенным cross-needle узлом. "
                    f"Контур {loop_id}, события: {details}."
                )
            # The collapse-endpoint resolver can replace the loop in-place.
            # Its new generation must be rescheduled just like other topology
            # mutations, otherwise the simulation would run out of events.
            child_loop = state.loops.get(loop_id)
            if child_loop is not None and child_loop.generation != loop.generation:
                changed_loops.append(child_loop)
        else:
            details = [
                (
                    event.kind.value,
                    event.edge_id,
                    event.vertex_id,
                    event.target_edge_id,
                    event.position,
                    event.time,
                )
                for event in sorted(loop_events, key=WavefrontEventQueue._event_key)
            ]
            raise GeometryInputError(
                "SIMULTANEOUS_EVENT_BATCH_UNRESOLVED",
                "Одновременные события разных типов для одного контура пока не разрешаются автоматически. "
                f"Контур {loop_id}, поколение {loop.generation}, события: {details}."
            )

    # Events for changed loop generations are invalidated lazily by the queue.
    # New candidates are scheduled from the new topology at the same global time.
    for loop in changed_loops:
        state.event_queue.push_many(
            collect_loop_events(loop, state.edges, state.current_time, state.epsilon)
        )

    return batch


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



def run_weighted_wavefront(
    points: Sequence[Point3],
    pitches_degrees: Sequence[float],
    *,
    eps: float = 1e-9,
    max_event_batches: int = 10000,
    require_area_coverage: bool = True,
) -> WavefrontTrace:
    """Run the global multi-loop event state machine to terminal completion.

    This is still an alpha trace builder: it returns source-edge facet
    fragments and skeleton arcs, not a final welded roof mesh. Ambiguous
    simultaneous events, unsupported vertex hits and unresolved needle
    topologies raise GeometryInputError rather than producing partial output.
    """
    if max_event_batches < 1:
        raise GeometryInputError("INVALID_EVENT_LIMIT", "Лимит событий должен быть положительным.")
    state = create_wavefront_state(points, pitches_degrees, eps)
    batches = 0
    while not state.is_complete:
        if batches >= max_event_batches:
            raise GeometryInputError(
                "MAX_WAVEFRONT_EVENTS",
                f"Достигнут лимит пакетов событий волнового фронта: {max_event_batches}."
            )
        advance_wavefront_state(state)
        batches += 1

    if not state.facets:
        raise GeometryInputError("EMPTY_WAVEFRONT_ROOF", "Волновой фронт не сформировал фасеты крыши.")

    projected_area = sum(_projected_area(facet.vertices) for facet in state.facets)
    area_tolerance = max(
        eps * max(1.0, state.source_area) * 1000.0,
        state.source_area * 1e-7,
    )
    if require_area_coverage and abs(projected_area - state.source_area) > area_tolerance:
        raise GeometryInputError(
            "WAVEFRONT_COVERAGE_MISMATCH",
            f"Фасеты волнового фронта покрывают {projected_area:.9g} из {state.source_area:.9g} единиц площади."
        )

    terminal_values = set(state.terminal_loops.values())
    if terminal_values == {"POINT"}:
        terminal_kind = "POINT"
    elif terminal_values == {"NEEDLE"}:
        terminal_kind = "NEEDLE"
    else:
        terminal_kind = "MULTI_TERMINAL"

    return WavefrontTrace(
        facets=tuple(state.facets),
        events=tuple(state.processed_events),
        skeleton_arcs=tuple(state.skeleton_arcs),
        terminal_time=state.current_time,
        terminal_kind=terminal_kind,
        source_area=state.source_area,
        projected_facet_area=projected_area,
        input_winding=state.input_winding,
    )




def _split_face_edges_at_shared_vertices(
    vertices: Sequence[Point3],
    faces: Sequence[tuple[int, ...]],
    tolerance: float,
) -> list[tuple[int, ...]]:
    """Insert every existing mesh vertex lying strictly inside a face edge.

    Wavefront split events can create a T-junction: an earlier facet contains
    one long edge while later facets use two sub-edges meeting at the split
    point. This conforming pass subdivides the long edge without adding
    geometry or changing the face's planar region.
    """
    tolerance_sq = tolerance * tolerance
    output: list[tuple[int, ...]] = []

    # Build one deterministic coordinate index per axis. For each face edge,
    # query the axis with the narrowest AABB interval, then apply exact 3D
    # projection/distance checks to this conservative candidate subset.
    axis_orders: list[list[int]] = []
    axis_values: list[list[float]] = []
    for axis in range(3):
        order = sorted(
            range(len(vertices)),
            key=lambda vertex_id: (vertices[vertex_id][axis], vertex_id),
        )
        axis_orders.append(order)
        axis_values.append([vertices[vertex_id][axis] for vertex_id in order])

    for face in faces:
        expanded: list[int] = []
        for edge_index, start_id in enumerate(face):
            end_id = face[(edge_index + 1) % len(face)]
            start = vertices[start_id]
            end = vertices[end_id]
            direction = tuple(end[axis] - start[axis] for axis in range(3))
            length_sq = sum(value * value for value in direction)
            if length_sq <= tolerance_sq:
                raise GeometryInputError(
                    "ZERO_LENGTH_FACE_EDGE",
                    "После объединения фасет найдено ребро нулевой длины."
                )

            points_on_edge: list[tuple[float, int]] = []
            search_axis = min(range(3), key=lambda axis: abs(direction[axis]))
            lower_value = min(start[search_axis], end[search_axis]) - tolerance
            upper_value = max(start[search_axis], end[search_axis]) + tolerance
            axis_values_for_edge = axis_values[search_axis]
            axis_order_for_edge = axis_orders[search_axis]
            candidate_start = bisect_left(axis_values_for_edge, lower_value)
            candidate_end = bisect_right(axis_values_for_edge, upper_value)

            for candidate_position in range(candidate_start, candidate_end):
                candidate_id = axis_order_for_edge[candidate_position]
                if candidate_id == start_id or candidate_id == end_id:
                    continue
                candidate = vertices[candidate_id]
                if any(
                    candidate[axis] < min(start[axis], end[axis]) - tolerance
                    or candidate[axis] > max(start[axis], end[axis]) + tolerance
                    for axis in range(3)
                    if axis != search_axis
                ):
                    continue
                relative = tuple(candidate[axis] - start[axis] for axis in range(3))
                parameter = sum(relative[axis] * direction[axis] for axis in range(3)) / length_sq
                if parameter <= tolerance / (length_sq ** 0.5) or parameter >= 1.0 - tolerance / (length_sq ** 0.5):
                    continue
                projected = tuple(
                    start[axis] + parameter * direction[axis] for axis in range(3)
                )
                distance_sq = sum(
                    (candidate[axis] - projected[axis]) ** 2 for axis in range(3)
                )
                if distance_sq <= tolerance_sq:
                    points_on_edge.append((parameter, candidate_id))

            points_on_edge.sort(key=lambda item: (item[0], item[1]))
            if not expanded:
                expanded.append(start_id)
            expanded.extend(candidate_id for _, candidate_id in points_on_edge)
            if expanded[-1] != end_id:
                expanded.append(end_id)
        compact: list[int] = []
        for vertex_id in expanded:
            if not compact or compact[-1] != vertex_id:
                compact.append(vertex_id)
        if len(compact) > 1 and compact[0] == compact[-1]:
            compact.pop()
        if len(set(compact)) < 3:
            raise GeometryInputError(
                "DEGENERATE_CONFORMED_FACE",
                "Разбиение T-junction создало вырожденную грань."
            )
        output.append(tuple(compact))
    return output


def build_wavefront_roof_surface(
    points: Sequence[Point3],
    pitches_degrees: Sequence[float],
    *,
    eps: float = 1e-9,
    max_event_batches: int = 10000,
):
    """Assemble and validate welded roof facets from a completed wavefront trace.

    The result is the same RoofSurface payload used by the Blender add-on
    and the existing shell builder. This geometry function remains bpy-free.
    """
    from .mesh import RoofSurface, _VertexRegistry, validate_surface_boundary_edges
    from .planes import build_boundary_planes

    trace = run_weighted_wavefront(
        points, pitches_degrees, eps=eps,
        max_event_batches=max_event_batches,
        require_area_coverage=True,
    )
    boundary_xy = tuple((point[0], point[1]) for point in points)
    source_area = abs(signed_area(boundary_xy))
    scale = max(
        1.0,
        max(point[0] for point in points) - min(point[0] for point in points),
        max(point[1] for point in points) - min(point[1] for point in points),
        max(point[2] for point in points) - min(point[2] for point in points),
    )
    weld_tolerance = max(1e-12, eps * scale * 100.0)
    area_tolerance = max(eps * scale * scale * 100.0, source_area * 1e-7)
    # Coverage tolerance is intentionally much looser than the threshold for
    # discarding a face. Real event ordering can create very small but valid
    # sliver facets; dropping them opens an otherwise conforming surface.
    min_fragment_area = max(1e-24, weld_tolerance * weld_tolerance * 10.0)
    planes = build_boundary_planes(points, pitches_degrees, eps)

    registry = _VertexRegistry(weld_tolerance)
    faces: list[tuple[int, ...]] = []
    slope_ids: list[int] = []
    face_keys: set[tuple[int, ...]] = set()

    fragments = tuple(trace.facets)
    fragment_ranges: list[tuple[int, int]] = []
    flattened_points: list[Point3] = []
    for fragment in fragments:
        if not (0 <= fragment.source_edge_id < len(planes)):
            raise GeometryInputError(
                "INVALID_SOURCE_SLOPE_ID",
                f"Фрагмент ссылается на неизвестный исходный скат {fragment.source_edge_id}."
            )
        start = len(flattened_points)
        flattened_points.extend(fragment.vertices)
        fragment_ranges.append((start, len(flattened_points)))

    native_weld_indices = None
    if len(flattened_points) >= 128:
        from .native_bridge import (
            NATIVE_VERTEX_WELD_AVAILABLE,
            NativeGeometryError,
            weld_vertices_batch_native,
        )

        if NATIVE_VERTEX_WELD_AVAILABLE:
            try:
                welded_vertices, native_weld_indices = weld_vertices_batch_native(
                    flattened_points, weld_tolerance
                )
            except NativeGeometryError as exc:
                raise GeometryInputError(exc.code, exc.message) from exc
            registry.vertices = list(welded_vertices)

    for fragment_index, fragment in enumerate(fragments):
        if native_weld_indices is None:
            indices = [registry.add(point) for point in fragment.vertices]
        else:
            start, end = fragment_ranges[fragment_index]
            indices = list(native_weld_indices[start:end])
        compact: list[int] = []
        for index in indices:
            if not compact or compact[-1] != index:
                compact.append(index)
        if len(compact) > 1 and compact[0] == compact[-1]:
            compact.pop()
        if len(set(compact)) < 3:
            continue

        projected = [(registry.vertices[index][0], registry.vertices[index][1]) for index in compact]
        signed = signed_area(projected)
        if abs(signed) <= min_fragment_area:
            continue
        if signed < 0.0:
            compact.reverse()
            projected.reverse()

        plane = planes[fragment.source_edge_id]
        for vertex_index in compact:
            x, y, z = registry.vertices[vertex_index]
            expected_z = plane.height(x, y)
            if abs(expected_z - z) > max(weld_tolerance * 20.0, eps * scale * 1000.0):
                raise GeometryInputError(
                    "FACET_PLANE_MISMATCH",
                    f"Фрагмент ската {fragment.source_edge_id + 1} отклоняется от плоскости на "
                    f"{abs(expected_z - z):.9g}."
                )

        key = tuple(sorted(compact))
        if key in face_keys:
            raise GeometryInputError(
                "DUPLICATE_WAVEFRONT_FACET",
                "Волновой фронт сформировал две одинаковые фасеты."
            )
        face_keys.add(key)
        faces.append(tuple(compact))
        slope_ids.append(fragment.source_edge_id)

    if not faces:
        raise GeometryInputError("EMPTY_WAVEFRONT_SURFACE", "После объединения фасет не осталось граней.")

    # A split can introduce a vertex in the interior of an earlier facet edge.
    # Make every incident face use the same edge segmentation before manifold
    # validation; otherwise a geometric T-junction appears as an open edge.
    conformed_faces = None
    if len(faces) >= 64 and len(registry.vertices) >= 128:
        from .native_bridge import (
            NATIVE_FACE_CONFORMANCE_AVAILABLE,
            NativeGeometryError,
            split_face_edges_at_shared_vertices_native,
        )

        if NATIVE_FACE_CONFORMANCE_AVAILABLE:
            try:
                conformed_faces = split_face_edges_at_shared_vertices_native(
                    registry.vertices, faces, weld_tolerance * 5.0
                )
            except NativeGeometryError as exc:
                raise GeometryInputError(exc.code, exc.message) from exc

    if conformed_faces is None:
        faces = _split_face_edges_at_shared_vertices(
            registry.vertices, faces, weld_tolerance * 5.0
        )
    else:
        faces = [tuple(face) for face in conformed_faces]

    surface_area = sum(
        abs(signed_area([(registry.vertices[i][0], registry.vertices[i][1]) for i in face]))
        for face in faces
    )
    if abs(surface_area - source_area) > area_tolerance:
        raise GeometryInputError(
            "WAVEFRONT_MESH_COVERAGE_MISMATCH",
            f"Собранная сетка покрывает {surface_area:.9g} из {source_area:.9g} единиц площади."
        )

    try:
        validate_surface_boundary_edges(
            registry.vertices, faces, boundary_xy, weld_tolerance * 5.0
        )
    except GeometryInputError as exc:
        if exc.code == "INTERNAL_OPEN_EDGE":
            from .mesh import _mesh_edge_usage, _point_on_boundary_segment
            usage = _mesh_edge_usage(faces)
            for (first, second), count in usage.items():
                if count != 1:
                    continue
                p, q = registry.vertices[first], registry.vertices[second]
                matches = []
                for boundary_index, boundary_start in enumerate(boundary_xy):
                    boundary_end = boundary_xy[(boundary_index + 1) % len(boundary_xy)]
                    if (
                        _point_on_boundary_segment((p[0], p[1]), boundary_start, boundary_end, weld_tolerance * 5.0)
                        and _point_on_boundary_segment((q[0], q[1]), boundary_start, boundary_end, weld_tolerance * 5.0)
                    ):
                        matches.append(boundary_index)
                if len(matches) != 1:
                    incident_faces = [
                        (face_index, slope_ids[face_index])
                        for face_index, face in enumerate(faces)
                        if first in face and second in face
                    ]
                    detail = (
                        f" Открытое внутреннее ребро ({p[0]:.6g}, {p[1]:.6g}, {p[2]:.6g}) → "
                        f"({q[0]:.6g}, {q[1]:.6g}, {q[2]:.6g}); "
                        f"инцидентные фасеты (face, source_slope): {incident_faces}."
                    )
                    raise GeometryInputError(exc.code, exc.message + detail) from exc
        raise
    return RoofSurface(
        vertices=tuple(registry.vertices),
        faces=tuple(faces),
        face_slope_indices=tuple(slope_ids),
        planes=tuple(planes),
        source_area_xy=source_area,
        surface_area_xy=surface_area,
        boundary_xy=boundary_xy,
    )


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
    current_time = sum(point[2] for point in points) / len(points)
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
                    expected_z = line.base_height + (line.normal[0] * x + line.normal[1] * y - line.offset) / line.speed
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
