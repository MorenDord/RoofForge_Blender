"""Pure-Python straight-skeleton roof mesher for RoofForge 2.5.8.

The wavefront implementation is based on the event-driven straight-skeleton
construction of Felkel & Obdrzalek. The roof faces are assembled from the
swept wavefront edges, so every original contour edge produces planar roof
faces; there is no sampled height field or subdivision.

Input polygon must be a simple CCW contour in XY. Output is a minimal polygon
mesh (one or more n-gon components per source edge in degenerate/split cases).
"""

from __future__ import annotations
import heapq
import math
from collections import defaultdict

_EPS = 1.0e-9


class SkeletonError(RuntimeError):
    pass


class _V2:
    __slots__ = ("x", "y")

    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)

    def __add__(self, other):
        return _V2(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return _V2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar):
        return _V2(self.x * scalar, self.y * scalar)

    __rmul__ = __mul__

    def __truediv__(self, scalar):
        return _V2(self.x / scalar, self.y / scalar)

    def __neg__(self):
        return _V2(-self.x, -self.y)

    def __abs__(self):
        return math.hypot(self.x, self.y)

    def normalized(self):
        length = abs(self)
        if length <= _EPS:
            raise SkeletonError("Straight skeleton: вырожденный вектор биссектрисы.")
        return self / length

    def dot(self, other):
        return self.x * other.x + self.y * other.y

    def __eq__(self, other):
        return isinstance(other, _V2) and abs(self - other) <= 1.0e-7

    def __repr__(self):
        return "_V2({:.8g}, {:.8g})".format(self.x, self.y)


def _cross(a, b):
    return a.x * b.y - a.y * b.x


def _approximately_same(a, b, eps=1.0e-7):
    return abs(a - b) <= eps


def _point_on_segment_inclusive(point, a, b, tolerance=1.0e-7):
    """Return True when a point lies on a finite segment, endpoints included.

    Reflex wavefront vertices can collide with an endpoint of an opposite
    active segment at exactly the same time as an adjacent edge collapse.
    Treating only strict interior hits as split events loses these vertex-to-
    vertex events; the remaining wavefront can then contain parallel supports
    that have already crossed and can no longer generate valid events.
    """
    ab = b - a
    length_squared = ab.dot(ab)
    if length_squared <= tolerance * tolerance:
        return abs(point - a) <= tolerance
    length = math.sqrt(length_squared)
    parameter = (point - a).dot(ab) / length_squared
    parameter_tolerance = tolerance / max(length, 1.0)
    if parameter < -parameter_tolerance or parameter > 1.0 + parameter_tolerance:
        return False
    clamped_parameter = max(0.0, min(1.0, parameter))
    nearest = a + ab * clamped_parameter
    return abs(point - nearest) <= tolerance


def _point_strictly_on_segment(point, a, b, tolerance=1.0e-7):
    """Return True only when point lies on the interior of finite segment a-b."""
    ab = b - a
    length_squared = ab.dot(ab)
    if length_squared <= tolerance * tolerance:
        return False
    ap = point - a
    t = ap.dot(ab) / length_squared
    if t <= tolerance or t >= 1.0 - tolerance:
        return False
    nearest = a + ab * t
    return abs(point - nearest) <= tolerance * max(1.0, math.sqrt(length_squared))


class _Line2:
    __slots__ = ("p", "v")

    def __init__(self, point_or_line, direction=None):
        if direction is None:
            self.p = point_or_line.p
            self.v = point_or_line.v
        else:
            self.p = point_or_line
            self.v = direction

    def intersect(self, other):
        denominator = _cross(self.v, other.v)
        if abs(denominator) <= 1.0e-10:
            return None
        t = _cross(other.p - self.p, other.v) / denominator
        return self.p + self.v * t

    def distance(self, point):
        length = abs(self.v)
        if length <= _EPS:
            return abs(point - self.p)
        return abs(_cross(self.v, point - self.p)) / length


class _Ray2(_Line2):
    pass


class _Segment2(_Line2):
    __slots__ = ("index", "speed")

    def __init__(self, a, b, index, speed=1.0):
        super().__init__(a, b - a)
        self.index = int(index)
        self.speed = float(speed)
        if not math.isfinite(self.speed) or self.speed <= 0.0:
            raise SkeletonError("Weighted skeleton: скорость ребра должна быть положительной.")


class _EdgeEvent:
    __slots__ = ("distance", "intersection_point", "vertex_a", "vertex_b")

    def __init__(self, distance, point, vertex_a, vertex_b):
        self.distance = float(distance)
        self.intersection_point = point
        self.vertex_a = vertex_a
        self.vertex_b = vertex_b

    def __lt__(self, other):
        return self.distance < other.distance


class _SplitEvent:
    __slots__ = ("distance", "intersection_point", "vertex", "opposite_edge",
                 "target_start", "target_end")

    def __init__(self, distance, point, vertex, opposite_edge,
                 target_start=None, target_end=None):
        self.distance = float(distance)
        self.intersection_point = point
        self.vertex = vertex
        self.opposite_edge = opposite_edge
        # Retain the exact active wavefront segment hit by this event. An
        # original edge may be represented by more than one live segment
        # after split events, so its edge id alone is not a unique locator.
        self.target_start = target_start
        self.target_end = target_end

    def __lt__(self, other):
        return self.distance < other.distance


class _OriginalEdge:
    __slots__ = ("edge", "bisector_left", "bisector_right")

    def __init__(self, edge, bisector_left, bisector_right):
        self.edge = edge
        self.bisector_left = bisector_left
        self.bisector_right = bisector_right


class _WaveVertex:
    _next_id = 0

    def __init__(self, point, edge_left, edge_right, direction_vectors=None, birth_time=0.0):
        self.point = point
        self.edge_left = edge_left
        self.edge_right = edge_right
        self.prev = None
        self.next = None
        self.lav = None
        self.valid = True
        self.birth_time = float(birth_time)
        self.uid = _WaveVertex._next_id
        _WaveVertex._next_id += 1

        creator_vectors = (-edge_left.v.normalized(), edge_right.v.normalized())
        if direction_vectors is None:
            direction_vectors = creator_vectors
        self.is_reflex = _cross(direction_vectors[0], direction_vectors[1]) < 0.0

        left_direction = edge_left.v.normalized()
        right_direction = edge_right.v.normalized()
        inward_left = _V2(left_direction.y, -left_direction.x)
        inward_right = _V2(right_direction.y, -right_direction.x)
        speed_left = float(edge_left.speed)
        speed_right = float(edge_right.speed)
        determinant = _cross(inward_left, inward_right)

        if abs(determinant) > 1.0e-10:
            # Solve n_left·v=s_left and n_right·v=s_right.
            velocity = _V2(
                (speed_left * inward_right.y - inward_left.y * speed_right) / determinant,
                (inward_left.x * speed_right - speed_left * inward_right.x) / determinant,
            )
        else:
            normal_alignment = inward_left.dot(inward_right)
            speed_delta = abs(speed_left - speed_right)
            if normal_alignment > 1.0 - 1.0e-8:
                if speed_delta > 1.0e-8 * max(speed_left, speed_right, 1.0):
                    raise SkeletonError(
                        "Weighted skeleton: совпадающие параллельные фронты имеют разные скорости."
                    )
                velocity = inward_left * speed_left
            else:
                # At a zero-width collapse the two surviving support lines
                # may be parallel with opposite normals. The classic event
                # construction retains the event bisector as a tangential
                # continuation; use that same deterministic limit here.
                direction = -left_direction + right_direction
                if self.is_reflex:
                    direction = -direction
                if abs(direction) <= _EPS and direction_vectors is not None:
                    direction = direction_vectors[0] + direction_vectors[1]
                if abs(direction) <= _EPS:
                    direction = left_direction
                normal_speed = direction.dot(inward_left)
                velocity = (
                    direction * (speed_left / normal_speed)
                    if abs(normal_speed) > 1.0e-10
                    else direction
                )

        if not math.isfinite(velocity.x) or not math.isfinite(velocity.y):
            raise SkeletonError("Weighted skeleton: скорость вершины стала неконечной.")
        self.bisector = _Ray2(point, velocity)

    def position_at(self, time):
        return self.point + self.bisector.v * (float(time) - self.birth_time)

    @property
    def original_edges(self):
        return self.lav.slav.original_edges

    def next_event(self, current_time, projected_edge_events=False):
        events = []

        # Reflex vertices can hit a non-adjacent moving wavefront segment.
        # Compute the collision directly from the two moving objects instead
        # of constructing an auxiliary bisector from supporting-line
        # intersections. This is especially important for oblique concave L
        # contours, where the old construction could choose the wrong
        # adjacent support line and place the split point outside the outline.
        if self.is_reflex:
            velocity = self.bisector.v
            # P(t) = self.point + velocity * (t - birth_time).
            trajectory_origin = self.point - velocity * self.birth_time
            for original in self.original_edges:
                edge = original.edge
                if edge.index in (self.edge_left.index, self.edge_right.index):
                    continue

                edge_direction = edge.v
                if abs(edge_direction) <= _EPS:
                    continue
                # Input to the wavefront engine is clockwise, so its inward
                # unit normal is the right-hand normal of the original edge.
                inward = _V2(edge_direction.y, -edge_direction.x).normalized()
                relative_velocity = velocity - inward * float(edge.speed)
                denominator = _cross(edge_direction, relative_velocity)
                if abs(denominator) <= 1.0e-12:
                    continue

                # Solve cross(edge_direction, P(t) - (edge.p + inward*t))=0.
                event_time = -_cross(edge_direction, trajectory_origin - edge.p) / denominator
                if event_time < max(current_time, self.birth_time) - 1.0e-7:
                    continue
                hit = self.position_at(event_time)

                # The hit must lie strictly inside one live finite segment of
                # this original edge. Carry the exact endpoint vertices into
                # the event so the topology update cannot select a sibling
                # segment with the same original edge id.
                try:
                    for edge_id, segment_start, segment_end, point_a, point_b in self.lav.slav.active_segments(event_time):
                        if edge_id != edge.index:
                            continue
                        segment_length = abs(point_b - point_a)
                        tolerance = max(1.0e-7, segment_length * 1.0e-7)
                        if _point_on_segment_inclusive(hit, point_a, point_b, tolerance):
                            events.append(_SplitEvent(
                                event_time, hit, self, edge, segment_start, segment_end
                            ))
                            break
                except Exception:
                    # A candidate that cannot be associated with a live
                    # segment is not a valid split event.
                    continue

        # Edge events. The classic solver intersects the two vertex bisectors.
        # The free-angle solver uses the one-dimensional collapse equation on
        # the active wavefront edge. Both endpoints lie on its moving support
        # line, so their signed separation and relative speed determine the exact
        # meeting time without a second line-line intersection.
        if projected_edge_events:
            for vertex_a, vertex_b in ((self.prev, self), (self, self.next)):
                edge = vertex_a.edge_right
                direction = edge.v.normalized()
                point_a = vertex_a.position_at(current_time)
                point_b = vertex_b.position_at(current_time)
                separation = direction.dot(point_b - point_a)
                closing_rate = direction.dot(
                    vertex_b.bisector.v - vertex_a.bisector.v
                )
                if closing_rate >= -1.0e-10:
                    continue
                delta_time = separation / (-closing_rate)
                if delta_time < -1.0e-7 or not math.isfinite(delta_time):
                    continue
                event_time = current_time + max(0.0, delta_time)
                point_a_event = vertex_a.position_at(event_time)
                point_b_event = vertex_b.position_at(event_time)
                hit = (point_a_event + point_b_event) * 0.5
                events.append(_EdgeEvent(event_time, hit, vertex_a, vertex_b))
        else:
            previous_hit = self.bisector.intersect(self.prev.bisector)
            if previous_hit is not None:
                event_time = _Line2(self.edge_left).distance(previous_hit)
                if event_time >= max(current_time, self.birth_time, self.prev.birth_time) - 1.0e-7:
                    events.append(_EdgeEvent(event_time, previous_hit, self.prev, self))

            next_hit = self.bisector.intersect(self.next.bisector)
            if next_hit is not None:
                event_time = _Line2(self.edge_right).distance(next_hit)
                if event_time >= max(current_time, self.birth_time, self.next.birth_time) - 1.0e-7:
                    events.append(_EdgeEvent(event_time, next_hit, self, self.next))

        return min(events, key=lambda event: event.distance) if events else None

    def invalidate(self):
        self.valid = False


class _LAV:
    def __init__(self, slav):
        self.head = None
        self.slav = slav
        self.length = 0

    @classmethod
    def from_polygon(cls, polygon, edges, slav):
        lav = cls(slav)
        count = len(polygon)
        for i, point in enumerate(polygon):
            vertex = _WaveVertex(point, edges[(i - 1) % count], edges[i])
            vertex.lav = lav
            if lav.head is None:
                lav.head = vertex
                vertex.prev = vertex.next = vertex
            else:
                vertex.next = lav.head
                vertex.prev = lav.head.prev
                vertex.prev.next = vertex
                lav.head.prev = vertex
            lav.length += 1
        return lav

    @classmethod
    def from_chain(cls, head, slav):
        lav = cls(slav)
        lav.head = head
        for vertex in lav:
            vertex.lav = lav
            lav.length += 1
        return lav

    def __iter__(self):
        if self.head is None:
            return
        current = self.head
        while True:
            yield current
            current = current.next
            if current == self.head:
                break

    def unify(self, vertex_a, vertex_b, point, time):
        replacement = _WaveVertex(
            point,
            vertex_a.edge_left,
            vertex_b.edge_right,
            (vertex_b.bisector.v.normalized(), vertex_a.bisector.v.normalized()),
            birth_time=time,
        )
        replacement.lav = self
        if self.head in (vertex_a, vertex_b):
            self.head = replacement
        vertex_a.prev.next = replacement
        vertex_b.next.prev = replacement
        replacement.prev = vertex_a.prev
        replacement.next = vertex_b.next
        vertex_a.invalidate()
        vertex_b.invalidate()
        self.length -= 1
        return replacement


class _SLAV:
    def __init__(self, clockwise_polygon, edge_speeds=None):
        self.lavs = []
        count = len(clockwise_polygon)
        if edge_speeds is None:
            edge_speeds = [1.0] * count
        if len(edge_speeds) != count:
            raise SkeletonError("Weighted skeleton: число скоростей не совпадает с числом рёбер.")
        edges = [
            _Segment2(clockwise_polygon[i], clockwise_polygon[(i + 1) % count],
                      i, edge_speeds[i])
            for i in range(count)
        ]
        lav = _LAV.from_polygon(clockwise_polygon, edges, self)
        self.lavs.append(lav)
        # Keep the original edge objects: wavefront vertices refer to these edges.
        self.original_edges = [
            _OriginalEdge(vertex.edge_left, vertex.prev.bisector, vertex.bisector)
            for vertex in lav
        ]

    def active_segments(self, time):
        result = []
        for lav in self.lavs:
            for vertex in lav:
                next_vertex = vertex.next
                edge = vertex.edge_right
                if edge.index != next_vertex.edge_left.index:
                    raise SkeletonError("Straight skeleton: нарушена связность wavefront-рёбер.")
                result.append((edge.index, vertex, next_vertex,
                               vertex.position_at(time), next_vertex.position_at(time)))
        return result

    def handle_edge_event(self, event, projected_edge_events=False):
        lav = event.vertex_a.lav
        if event.vertex_a.prev is event.vertex_b.next:
            # The final three wavefront vertices collapse to one peak.
            self.lavs.remove(lav)
            for vertex in list(lav):
                vertex.invalidate()
            return []

        replacement = lav.unify(
            event.vertex_a, event.vertex_b, event.intersection_point, event.distance
        )
        next_event = replacement.next_event(event.distance, projected_edge_events)
        return [next_event] if next_event is not None else []

    def handle_split_event(self, event, projected_edge_events=False):
        lav = event.vertex.lav
        x = None
        y = None

        # Prefer the exact segment retained by the event calculation. At the
        # event time active_segments stores (segment_start, segment_end), and
        # the edge is segment_start.edge_right.
        target_start = event.target_start
        target_end = event.target_end
        if (target_start is not None and target_end is not None
                and target_start.valid and target_end.valid
                and target_start.next is target_end
                and target_start.edge_right.index == event.opposite_edge.index):
            y = target_start
            x = target_end
        else:
            # Conservative fallback for legacy or invalidated queued events.
            edge_direction = event.opposite_edge.v.normalized()
            for candidate_lav in self.lavs:
                for vertex in candidate_lav:
                    if vertex.edge_right.index == event.opposite_edge.index:
                        candidate_y = vertex
                        candidate_x = vertex.next
                        point_a = candidate_y.position_at(event.distance)
                        point_b = candidate_x.position_at(event.distance)
                        tolerance = max(1.0e-7, abs(point_b - point_a) * 1.0e-7)
                        if _point_strictly_on_segment(
                                event.intersection_point, point_a, point_b, tolerance):
                            y, x = candidate_y, candidate_x
                            break
                if x is not None:
                    break

        if x is None or y is None:
            # The candidate can become ineligible after an earlier simultaneous event.
            return []
        # Preserve the live segment selected by the fallback for local refresh.
        event.target_start = y
        event.target_end = x

        x_left = _cross(
            y.bisector.v.normalized(),
            (event.intersection_point - y.point).normalized(),
        ) >= -1.0e-5
        x_right = _cross(
            x.bisector.v.normalized(),
            (event.intersection_point - x.point).normalized(),
        ) <= 1.0e-5
        if not (x_left and x_right):
            return []

        vertex_1 = _WaveVertex(
            event.intersection_point, event.vertex.edge_left, event.opposite_edge,
            birth_time=event.distance,
        )
        vertex_2 = _WaveVertex(
            event.intersection_point, event.opposite_edge, event.vertex.edge_right,
            birth_time=event.distance,
        )

        vertex_1.prev = event.vertex.prev
        vertex_1.next = x
        event.vertex.prev.next = vertex_1
        x.prev = vertex_1

        vertex_2.prev = y
        vertex_2.next = event.vertex.next
        event.vertex.next.prev = vertex_2
        y.next = vertex_2

        self.lavs.remove(lav)
        if lav is not x.lav:
            self.lavs.remove(x.lav)
            new_lavs = [_LAV.from_chain(vertex_1, self)]
        else:
            new_lavs = [
                _LAV.from_chain(vertex_1, self),
                _LAV.from_chain(vertex_2, self),
            ]

        new_heads = []
        for new_lav in new_lavs:
            if new_lav.length > 2:
                self.lavs.append(new_lav)
                new_heads.append(new_lav.head)
            else:
                for vertex in list(new_lav):
                    vertex.invalidate()

        event.vertex.invalidate()
        events = []
        for head in new_heads:
            next_event = head.next_event(event.distance, projected_edge_events)
            if next_event is not None:
                events.append(next_event)
        return events


def _poly_area_2d(points):
    return 0.5 * sum(
        points[i][0] * points[(i + 1) % len(points)][1]
        - points[(i + 1) % len(points)][0] * points[i][1]
        for i in range(len(points))
    )




def _orthogonalize_nearly_orthogonal_contour(polygon, max_deviation_degrees=0.001):
    """Remove floating-point angular noise from an otherwise orthogonal loop.

    Blender meshes transformed through object/world matrices can contain tiny
    angular deviations (for example 90.000014 degrees). A concave orthogonal
    outline can have simultaneous wavefront events; treating that numerical
    noise as real geometry separates those events by micrometres and leaves
    unmatched patch vertices. This function only snaps a contour when *every*
    edge is within ``max_deviation_degrees`` of one common pair of perpendicular
    axes. Genuinely oblique outlines are returned unchanged.

    The two axes are estimated by a length-weighted circular mean modulo 90
    degrees. Each vertex is then projected to the intersection of the support
    lines of its incident edges. No rectangle dimensions or edge lengths are
    assumed.
    """
    points = [(float(point[0]), float(point[1])) for point in polygon]
    count = len(points)
    if count < 4:
        return points, False

    edge_data = []
    cosine_sum = 0.0
    sine_sum = 0.0
    total_length = 0.0
    scale = 1.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % count]
        dx = nxt[0] - point[0]
        dy = nxt[1] - point[1]
        length = math.hypot(dx, dy)
        if length <= 1.0e-12:
            return points, False
        angle = math.atan2(dy, dx)
        cosine_sum += length * math.cos(4.0 * angle)
        sine_sum += length * math.sin(4.0 * angle)
        total_length += length
        scale = max(scale, length)
        edge_data.append((dx, dy, length))

    if math.hypot(cosine_sum, sine_sum) <= total_length * 1.0e-8:
        return points, False

    axis_angle = 0.25 * math.atan2(sine_sum, cosine_sum)
    axis_u = (math.cos(axis_angle), math.sin(axis_angle))
    axis_v = (-axis_u[1], axis_u[0])
    origin = points[0]

    local = []
    for x, y in points:
        dx = x - origin[0]
        dy = y - origin[1]
        local.append((dx * axis_u[0] + dy * axis_u[1],
                      dx * axis_v[0] + dy * axis_v[1]))

    # For an edge parallel to U, V is constant. For an edge parallel to V,
    # U is constant. Store the fitted support coordinate for both endpoints.
    edge_axes = []
    fixed_u = [[] for _ in range(count)]
    fixed_v = [[] for _ in range(count)]
    max_deviation = 0.0
    for index in range(count):
        nxt = (index + 1) % count
        du = local[nxt][0] - local[index][0]
        dv = local[nxt][1] - local[index][1]
        if abs(du) >= abs(dv):
            edge_axis = 0
            deviation = math.atan2(abs(dv), abs(du))
            support = 0.5 * (local[index][1] + local[nxt][1])
            fixed_v[index].append(support)
            fixed_v[nxt].append(support)
        else:
            edge_axis = 1
            deviation = math.atan2(abs(du), abs(dv))
            support = 0.5 * (local[index][0] + local[nxt][0])
            fixed_u[index].append(support)
            fixed_u[nxt].append(support)
        edge_axes.append(edge_axis)
        max_deviation = max(max_deviation, deviation)

    if max_deviation > math.radians(max_deviation_degrees):
        return points, False

    # A valid simple orthogonal contour alternates axes at corners. Collinear
    # subdivisions are allowed; averaging their support estimates is stable.
    snapped = []
    for index, (u, v) in enumerate(local):
        u_values = fixed_u[index]
        v_values = fixed_v[index]
        snapped_u = sum(u_values) / len(u_values) if u_values else u
        snapped_v = sum(v_values) / len(v_values) if v_values else v
        x = origin[0] + snapped_u * axis_u[0] + snapped_v * axis_v[0]
        y = origin[1] + snapped_u * axis_u[1] + snapped_v * axis_v[1]
        snapped.append((x, y))

    original_area = _poly_area_2d(points)
    snapped_area = _poly_area_2d(snapped)
    if abs(snapped_area) <= scale * scale * 1.0e-12:
        return points, False
    if original_area * snapped_area <= 0.0:
        return points, False

    max_shift = max(math.dist(a, b) for a, b in zip(points, snapped))
    # Do not reinterpret intentional geometry as numerical noise.
    if max_shift > max(scale * 2.0e-5, 1.0e-7):
        return points, False
    if any(math.dist(snapped[i], snapped[(i + 1) % count]) <= scale * 1.0e-10
           for i in range(count)):
        return points, False

    return snapped, True

def _key3(point, tolerance):
    return tuple(int(round(float(value) / tolerance)) for value in point)


def _sub3(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _length3(value):
    return math.sqrt(_dot3(value, value))


def _cross3(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _newell_normal(points):
    normal = [0.0, 0.0, 0.0]
    for i, point in enumerate(points):
        nxt = points[(i + 1) % len(points)]
        normal[0] += (point[1] - nxt[1]) * (point[2] + nxt[2])
        normal[1] += (point[2] - nxt[2]) * (point[0] + nxt[0])
        normal[2] += (point[0] - nxt[0]) * (point[1] + nxt[1])
    return tuple(normal)


def _simplify_loop(loop, tolerance):
    points = list(loop)
    changed = True
    while changed and len(points) > 3:
        changed = False
        cleaned = []
        count = len(points)
        for i, point in enumerate(points):
            previous = points[(i - 1) % count]
            following = points[(i + 1) % count]
            v1 = _sub3(point, previous)
            v2 = _sub3(following, point)
            cross = _cross3(v1, v2)
            # Compare the cross product with a *local* edge scale. Using
            # max(..., 1.0) here turns the collinearity test into an absolute
            # area threshold for sub-metre edges. On long, narrow orthogonal
            # L plans this can erase genuine millimetre-scale wavefront facets
            # at simultaneous 90-degree events and leave open roof seams.
            local_edge_scale = max(_length3(v1), _length3(v2), tolerance)
            cross_tolerance = tolerance * local_edge_scale
            dot_tolerance = tolerance * local_edge_scale
            if (_length3(cross) <= cross_tolerance
                    and _dot3(v1, v2) >= -dot_tolerance):
                changed = True
                continue
            cleaned.append(point)
        points = cleaned
    return points


def _merge_face_patches(patches, scale):
    """Union coplanar swept quads into planar roof-face boundary loops.

    Each patch is first oriented with its normal facing +Z. Internal edges
    then cancel by *directed* use, rather than relying on whichever duplicate
    edge happened to be visited last. At point-touching boundaries, loops are
    traced with a deterministic planar half-edge rule (clockwise predecessor
    from the reverse incoming direction), so a branch cannot arbitrarily
    jump onto a neighbouring boundary and create a spike.
    """
    tolerance = max(1.0e-8, scale * 1.0e-8)

    # Canonicalize points by Euclidean distance before constructing the
    # directed boundary graph. A rounded grid key is not sufficient here:
    # two points closer than tolerance can fall on opposite sides of a grid
    # cell boundary and receive different keys. That creates a microscopic
    # open edge in an otherwise closed swept face patch.
    canonical_points = []
    buckets = defaultdict(list)
    raw_to_canonical = {}
    cell_size = tolerance
    for patch in patches:
        for raw_point in patch:
            raw = tuple(float(v) for v in raw_point)
            if raw in raw_to_canonical:
                continue
            cell = tuple(int(math.floor(v / cell_size)) for v in raw)
            best = None
            best_distance = float("inf")
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        near_cell = (cell[0] + dx, cell[1] + dy, cell[2] + dz)
                        for candidate_id in buckets.get(near_cell, ()):
                            distance = _length3(_sub3(raw, canonical_points[candidate_id]))
                            if distance <= tolerance and distance < best_distance:
                                best = candidate_id
                                best_distance = distance
            if best is None:
                best = len(canonical_points)
                canonical_points.append(raw)
                buckets[cell].append(best)
            raw_to_canonical[raw] = best

    # Replace only numerically coincident coordinates; genuine nearby
    # vertices remain separate when their Euclidean distance exceeds tolerance.
    patches = [
        [canonical_points[raw_to_canonical[tuple(float(v) for v in point)]] for point in patch]
        for patch in patches
    ]
    unique_points = {index: point for index, point in enumerate(canonical_points)}
    point_keys = {point: index for index, point in unique_points.items()}
    all_points = list(unique_points.values())

    # Signed incidence of every split, undirected edge. Adjacent consistently
    # oriented patches contribute opposite signs and cancel exactly.
    signed_uses = defaultdict(int)
    seen_patch_loops = set()
    for patch in patches:
        clean = []
        for point in patch:
            if not clean or _length3(_sub3(point, clean[-1])) > tolerance:
                clean.append(point)
        if len(clean) > 2 and _length3(_sub3(clean[0], clean[-1])) <= tolerance:
            clean.pop()
        if len(clean) < 3:
            continue
        if _newell_normal(clean)[2] < 0.0:
            clean.reverse()

        # Split every edge at all canonical source vertices before comparing
        # patch identity. This also recognizes duplicate swept cells when one
        # event emitted a collinear vertex that the other emission omitted.
        split_segments = []
        split_patch_ids = []
        for i, a in enumerate(clean):
            b = clean[(i + 1) % len(clean)]
            ab = _sub3(b, a)
            denominator = _dot3(ab, ab)
            if denominator <= tolerance * tolerance:
                continue

            on_edge = []
            for point in all_points:
                ap = _sub3(point, a)
                t = _dot3(ap, ab) / denominator
                if t < -1.0e-8 or t > 1.0 + 1.0e-8:
                    continue
                nearest = tuple(a[k] + ab[k] * t for k in range(3))
                if _length3(_sub3(point, nearest)) <= tolerance * 5.0:
                    on_edge.append((max(0.0, min(1.0, t)), point))
            on_edge.sort(key=lambda item: item[0])
            sequence = []
            for _t, point in on_edge:
                if not sequence or _length3(_sub3(point, sequence[-1])) > tolerance:
                    sequence.append(point)

            for p0, p1 in zip(sequence, sequence[1:]):
                k0 = point_keys[tuple(float(v) for v in p0)]
                k1 = point_keys[tuple(float(v) for v in p1)]
                if k0 == k1:
                    continue
                split_patch_ids.append(k0)
                split_segments.append((k0, k1))

        if not split_segments:
            continue
        start_index = min(
            range(len(split_patch_ids)),
            key=lambda index: tuple(
                split_patch_ids[index:] + split_patch_ids[:index]
            ),
        )
        patch_key = tuple(
            split_patch_ids[start_index:] + split_patch_ids[:start_index]
        )
        if patch_key in seen_patch_loops:
            continue
        seen_patch_loops.add(patch_key)

        for k0, k1 in split_segments:
            undirected = (k0, k1) if k0 < k1 else (k1, k0)
            signed_uses[undirected] += 1 if (k0, k1) == undirected else -1

    boundary_edges = []
    for undirected, signed_count in signed_uses.items():
        if signed_count == 0:
            continue
        if abs(signed_count) != 1:
            raise SkeletonError(
                "Straight skeleton: перекрывающиеся участки одного ската "
                "образовали неманифолдную границу."
            )
        boundary_edges.append(undirected if signed_count > 0 else (undirected[1], undirected[0]))

    outgoing = defaultdict(list)
    for edge_id, (a, b) in enumerate(boundary_edges):
        outgoing[a].append(edge_id)

    unused = set(range(len(boundary_edges)))
    loops = []
    while unused:
        first_edge = min(unused)
        start_key = boundary_edges[first_edge][0]
        current_edge = first_edge
        loop_keys = [start_key]
        guard = 0

        while True:
            guard += 1
            if guard > len(boundary_edges) + 4:
                raise SkeletonError("Straight skeleton: не удалось замкнуть границу ската.")
            if current_edge not in unused:
                raise SkeletonError("Straight skeleton: повторное использование граничного ребра.")
            unused.remove(current_edge)
            a_key, b_key = boundary_edges[current_edge]
            loop_keys.append(b_key)
            if b_key == start_key:
                break

            candidates = [edge_id for edge_id in outgoing.get(b_key, ()) if edge_id in unused]
            if not candidates:
                raise SkeletonError("Straight skeleton: скат имеет незамкнутую или разорванную границу.")
            if len(candidates) == 1:
                current_edge = candidates[0]
                continue

            # In XY projection, every patch boundary keeps its interior left.
            # At a point contact the correct continuation is the outgoing
            # half-edge immediately clockwise from the reverse incoming ray.
            vertex = unique_points[b_key]
            previous = unique_points[a_key]
            reverse_angle = math.atan2(previous[1] - vertex[1], previous[0] - vertex[0])
            ranked = []
            for edge_id in candidates:
                _from_key, to_key = boundary_edges[edge_id]
                target = unique_points[to_key]
                out_angle = math.atan2(target[1] - vertex[1], target[0] - vertex[0])
                clockwise_turn = (reverse_angle - out_angle) % (2.0 * math.pi)
                ranked.append((clockwise_turn, edge_id))
            current_edge = min(ranked)[1]

        if len(loop_keys) < 4:
            continue
        loop = _simplify_loop([unique_points[key] for key in loop_keys[:-1]], tolerance)
        if len(loop) < 3:
            continue
        normal = _newell_normal(loop)
        if _length3(normal) <= tolerance * tolerance:
            continue
        if normal[2] < 0.0:
            loop.reverse()
        loops.append(loop)
    return loops


def _split_global_t_junctions(face_loops, scale):
    """Make every shared roof edge use the same vertices on both adjacent faces."""
    tolerance = max(1.0e-8, scale * 1.0e-8)
    # Face patches are merged per source edge, so the same wavefront node can
    # be computed independently by two neighbouring source faces. Canonicalize
    # those cross-face coordinates with a Euclidean neighbourhood search;
    # rounded quantization keys can separate sub-tolerance duplicates when they
    # straddle a cell boundary, leaving an open internal roof edge.
    canonical_points = []
    buckets = defaultdict(list)
    raw_to_canonical = {}
    cell_size = tolerance
    for _source_id, loop in face_loops:
        for raw_point in loop:
            raw = tuple(float(v) for v in raw_point)
            if raw in raw_to_canonical:
                continue
            cell = tuple(int(math.floor(v / cell_size)) for v in raw)
            best = None
            best_distance = float("inf")
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        near_cell = (cell[0] + dx, cell[1] + dy, cell[2] + dz)
                        for candidate_id in buckets.get(near_cell, ()):
                            distance = _length3(_sub3(raw, canonical_points[candidate_id]))
                            if distance <= tolerance and distance < best_distance:
                                best = candidate_id
                                best_distance = distance
            if best is None:
                best = len(canonical_points)
                canonical_points.append(raw)
                buckets[cell].append(best)
            raw_to_canonical[raw] = best

    face_loops = [
        (source_id, [canonical_points[raw_to_canonical[tuple(float(v) for v in point)]]
                     for point in loop])
        for source_id, loop in face_loops
    ]
    points_by_key = {index: point for index, point in enumerate(canonical_points)}
    all_points = list(points_by_key.values())

    result = []
    for source_id, loop in face_loops:
        out = []
        for i, a in enumerate(loop):
            b = loop[(i + 1) % len(loop)]
            ab = _sub3(b, a)
            denominator = _dot3(ab, ab)
            candidates = []
            if denominator > tolerance * tolerance:
                edge_length = math.sqrt(denominator)
                endpoint_parameter_tolerance = min(0.25, (tolerance * 5.0) / edge_length)
                for point in all_points:
                    t = _dot3(_sub3(point, a), ab) / denominator
                    if t <= endpoint_parameter_tolerance or t >= 1.0 - endpoint_parameter_tolerance:
                        # A point numerically close to an existing endpoint is
                        # already represented by that endpoint. Inserting it as a
                        # separate T-junction creates a microscopic extra edge.
                        continue
                    nearest = tuple(a[k] + ab[k] * t for k in range(3))
                    if _length3(_sub3(point, nearest)) <= tolerance * 5.0:
                        candidates.append((t, point))
            candidates.sort(key=lambda item: item[0])
            out.append(a)
            for _t, point in candidates:
                if _length3(_sub3(point, out[-1])) > tolerance:
                    out.append(point)
        result.append((source_id, out))
    return result


def _validate_face_planarity(vertices, faces, tolerance):
    for face_index, face in enumerate(faces):
        if len(face) < 3:
            raise SkeletonError("Straight skeleton: найден скат менее чем с тремя вершинами.")
        origin = vertices[face[0]]
        normal = None
        for i in range(1, len(face) - 1):
            a = _sub3(vertices[face[i]], origin)
            b = _sub3(vertices[face[i + 1]], origin)
            candidate = _cross3(a, b)
            if _length3(candidate) > tolerance * tolerance:
                normal = candidate
                break
        if normal is None:
            raise SkeletonError("Straight skeleton: вырожденный скат.")
        normal_length = _length3(normal)
        for index in face:
            distance = abs(_dot3(normal, _sub3(vertices[index], origin))) / normal_length
            if distance > tolerance * 20.0:
                raise SkeletonError(
                    "Straight skeleton: получен неплоский скат. Проверьте почти вырожденные углы контура."
                )


def _point_on_segment_2d(point, a, b, tolerance):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= tolerance * tolerance:
        return math.hypot(point[0] - a[0], point[1] - a[1]) <= tolerance
    t = ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_sq
    if t < -tolerance or t > 1.0 + tolerance:
        return False
    qx, qy = a[0] + t * dx, a[1] + t * dy
    return math.hypot(point[0] - qx, point[1] - qy) <= tolerance


def _point_in_or_on_polygon(point, polygon, tolerance):
    for i, a in enumerate(polygon):
        b = polygon[(i + 1) % len(polygon)]
        if _point_on_segment_2d(point, a, b, tolerance):
            return True
    x, y = point
    inside = False
    for i, a in enumerate(polygon):
        b = polygon[(i + 1) % len(polygon)]
        if (a[1] > y) != (b[1] > y):
            crossing_x = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x < crossing_x:
                inside = not inside
    return inside


def _orientation_2d(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect_2d(a, b, c, d, tolerance):
    o1 = _orientation_2d(a, b, c)
    o2 = _orientation_2d(a, b, d)
    o3 = _orientation_2d(c, d, a)
    o4 = _orientation_2d(c, d, b)
    eps = tolerance * max(
        math.hypot(b[0] - a[0], b[1] - a[1]),
        math.hypot(d[0] - c[0], d[1] - c[1]), 1.0
    )
    if ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps)) and \
       ((o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps)):
        return True
    if abs(o1) <= eps and _point_on_segment_2d(c, a, b, tolerance):
        return True
    if abs(o2) <= eps and _point_on_segment_2d(d, a, b, tolerance):
        return True
    if abs(o3) <= eps and _point_on_segment_2d(a, c, d, tolerance):
        return True
    if abs(o4) <= eps and _point_on_segment_2d(b, c, d, tolerance):
        return True
    return False


def _validate_roof_mesh_topology(vertices, faces, polygon, tolerance):
    """Reject roof patches that escape the footprint or expose internal holes."""
    for vertex in vertices:
        if not _point_in_or_on_polygon((vertex[0], vertex[1]), polygon, tolerance):
            raise SkeletonError(
                "Straight skeleton: вершина ската вышла за исходный контур крыши. "
                "Построение отменено, чтобы не создавать выпирающий участок."
            )

    edge_uses = defaultdict(int)
    for face_index, face in enumerate(faces):
        points = [(vertices[i][0], vertices[i][1]) for i in face]
        count = len(points)
        for i in range(count):
            for j in range(i + 1, count):
                if j == i or j == (i + 1) % count or (j + 1) % count == i:
                    continue
                if _segments_intersect_2d(
                    points[i], points[(i + 1) % count],
                    points[j], points[(j + 1) % count], tolerance
                ):
                    raise SkeletonError(
                        "Straight skeleton: граница одного ската самопересекается. "
                        "Проверьте узел вогнутого контура."
                    )
        for a, b in zip(face, face[1:] + face[:1]):
            key = (a, b) if a < b else (b, a)
            edge_uses[key] += 1
            if edge_uses[key] > 2:
                raise SkeletonError(
                    "Straight skeleton: у внутреннего ребра ската более двух соседних граней."
                )

    for (a_index, b_index), use_count in edge_uses.items():
        if use_count == 2:
            continue
        a = vertices[a_index]
        b = vertices[b_index]
        on_outline = any(
            _point_on_segment_2d((a[0], a[1]), p0, p1, tolerance)
            and _point_on_segment_2d((b[0], b[1]), p0, p1, tolerance)
            for i, p0 in enumerate(polygon)
            for p1 in [polygon[(i + 1) % len(polygon)]]
        )
        if not on_outline:
            raise SkeletonError(
                "Straight skeleton: между скатами обнаружено незамкнутое внутреннее ребро. "
                "Построение отменено."
            )


def _face_plane_z_coefficients(vertices, face):
    """Return (a, b, c) for the planar face equation z=a*x+b*y+c."""
    if len(face) < 3:
        return None
    origin = vertices[face[0]]
    for i in range(1, len(face) - 1):
        p1 = vertices[face[i]]
        p2 = vertices[face[i + 1]]
        v1 = _sub3(p1, origin)
        v2 = _sub3(p2, origin)
        normal = _cross3(v1, v2)
        if _length3(normal) <= 1.0e-12:
            continue
        if abs(normal[2]) <= 1.0e-12:
            return None
        a = -normal[0] / normal[2]
        b = -normal[1] / normal[2]
        c = origin[2] - a * origin[0] - b * origin[1]
        return (a, b, c)
    return None


def _line_intersection_with_parameters_2d(a, d, b, c, tolerance):
    """Intersect infinite lines A-D and B-C; return x,y,t,u."""
    rx, ry = d[0] - a[0], d[1] - a[1]
    sx, sy = c[0] - b[0], c[1] - b[1]
    denominator = rx * sy - ry * sx
    if abs(denominator) <= tolerance:
        return None
    qx, qy = b[0] - a[0], b[1] - a[1]
    t = (qx * sy - qy * sx) / denominator
    u = (qx * ry - qy * rx) / denominator
    return (a[0] + t * rx, a[1] + t * ry, t, u)


def _resolve_triangle_spike_junctions(vertices, faces, face_source_ids, polygon, scale):
    """Repair a known straight-skeleton degeneracy around a triangular spike.

    In a simultaneous wavefront event, three valid roof planes can meet at a
    point that lies on the extension of an existing seam. The event-driven
    patch union may instead leave a small fourth-plane triangle and let the
    ridge endpoint pass that junction. This pass recognizes the local
    four-face pattern, moves the ridge vertex to the exact three-plane
    intersection, removes the invalid triangular patch, and rewires the three
    neighbouring n-gons. It is deliberately conservative: all three retained
    faces must agree on the new 3D point and the replaced triangle must be on a
    different (lower) plane.
    """
    verts = [tuple(float(c) for c in point) for point in vertices]
    loops = [list(face) for face in faces]
    sources = list(face_source_ids)
    xy_tolerance = max(1.0e-8, float(scale) * 1.0e-8)
    z_tolerance = max(1.0e-7, float(scale) * 1.0e-7)

    for _iteration in range(max(4, len(loops) * 2)):
        changed = False
        edge_faces = defaultdict(list)
        for face_index, face in enumerate(loops):
            for va, vb in zip(face, face[1:] + face[:1]):
                key = (va, vb) if va < vb else (vb, va)
                edge_faces[key].append(face_index)

        for triangle_index, triangle in enumerate(loops):
            if len(triangle) != 3:
                continue
            triangle_edges = [
                (triangle[i], triangle[(i + 1) % 3]) for i in range(3)
            ]
            if any(len(edge_faces.get(tuple(sorted(edge)), ())) != 2
                   for edge in triangle_edges):
                continue

            candidate = None
            for host_index, host in enumerate(loops):
                if host_index == triangle_index or len(host) < 4:
                    continue
                count = len(host)
                for i in range(count):
                    a_index = host[i]
                    b_index = host[(i + 1) % count]
                    if a_index not in triangle or b_index not in triangle:
                        continue

                    x_index = next(v for v in triangle if v not in (a_index, b_index))
                    d_index = host[(i - 1) % count]
                    c_index = host[(i + 2) % count]

                    def other_face(edge_a, edge_b):
                        adjacent = edge_faces.get(tuple(sorted((edge_a, edge_b))), ())
                        return [fi for fi in adjacent if fi != triangle_index]

                    ridge_neighbours = other_face(a_index, x_index)
                    seam_neighbours = other_face(b_index, x_index)
                    first_side_neighbours = other_face(d_index, a_index)
                    second_side_neighbours = other_face(b_index, c_index)
                    if (len(ridge_neighbours) != 1 or len(seam_neighbours) != 1
                            or ridge_neighbours[0] == seam_neighbours[0]
                            or ridge_neighbours[0] not in first_side_neighbours
                            or seam_neighbours[0] not in second_side_neighbours):
                        continue

                    point_a = verts[a_index]
                    point_d = verts[d_index]
                    point_b = verts[b_index]
                    point_c = verts[c_index]
                    intersection = _line_intersection_with_parameters_2d(
                        (point_a[0], point_a[1]),
                        (point_d[0], point_d[1]),
                        (point_b[0], point_b[1]),
                        (point_c[0], point_c[1]),
                        xy_tolerance * xy_tolerance,
                    )
                    if intersection is None:
                        continue
                    x, y, ridge_t, seam_t = intersection
                    # The new point must lie on the current ridge segment and
                    # beyond the endpoint of the neighbouring seam segment.
                    # This is the exact slide direction seen in the reported
                    # concave junction; other triangle patterns are untouched.
                    if not (1.0e-7 < ridge_t < 1.0 - 1.0e-7):
                        continue
                    if not (seam_t < -1.0e-7 or seam_t > 1.0 + 1.0e-7):
                        continue
                    if not _point_in_or_on_polygon((x, y), polygon, xy_tolerance):
                        continue

                    ridge_face = ridge_neighbours[0]
                    seam_face = seam_neighbours[0]
                    retained_faces = (host_index, ridge_face, seam_face)
                    retained_planes = [
                        _face_plane_z_coefficients(verts, loops[fi])
                        for fi in retained_faces
                    ]
                    if any(plane is None for plane in retained_planes):
                        continue
                    heights = [a * x + b * y + c for a, b, c in retained_planes]
                    if max(heights) - min(heights) > z_tolerance:
                        continue

                    triangle_plane = _face_plane_z_coefficients(verts, triangle)
                    if triangle_plane is None:
                        continue
                    triangle_height = (
                        triangle_plane[0] * x + triangle_plane[1] * y + triangle_plane[2]
                    )
                    junction_height = sum(heights) / len(heights)
                    # Do not collapse a legitimate coplanar triangular facet.
                    if triangle_height >= junction_height - z_tolerance:
                        continue

                    candidate = (
                        host_index, ridge_face, seam_face, triangle_index,
                        a_index, b_index, x, y, junction_height,
                    )
                    break
                if candidate is not None:
                    break

            if candidate is None:
                continue

            (host_index, ridge_face, seam_face, triangle_index,
             a_index, b_index, x, y, z) = candidate

            new_index = None
            for vertex_index, point in enumerate(verts):
                if _length3(_sub3(point, (x, y, z))) <= xy_tolerance * 5.0:
                    new_index = vertex_index
                    break
            if new_index is None:
                new_index = len(verts)
                verts.append((float(x), float(y), float(z)))

            # Host face: replace consecutive A-B by the new three-plane node.
            host = loops[host_index]
            for i in range(len(host)):
                if host[i] == a_index and host[(i + 1) % len(host)] == b_index:
                    if i == len(host) - 1:
                        host = [new_index] + host[1:i]
                    else:
                        host = host[:i] + [new_index] + host[i + 2:]
                    break
            loops[host_index] = host

            # The two side faces inherit the same junction vertex.
            loops[ridge_face] = [new_index if v == a_index else v
                                 for v in loops[ridge_face]]
            loops[seam_face] = [new_index if v == b_index else v
                                for v in loops[seam_face]]

            # Remove the fourth-plane triangle that caused the false spike.
            loops.pop(triangle_index)
            sources.pop(triangle_index)
            changed = True
            break

        if not changed:
            break

    # Drop unused vertices and remap the compact low-poly mesh.
    used = sorted({index for face in loops for index in face})
    remap = {old: new for new, old in enumerate(used)}
    compact_vertices = [verts[index] for index in used]
    compact_faces = []
    compact_sources = []
    for source_id, face in zip(sources, loops):
        mapped = []
        for index in face:
            new_index = remap[index]
            if not mapped or mapped[-1] != new_index:
                mapped.append(new_index)
        if len(mapped) > 2 and mapped[0] == mapped[-1]:
            mapped.pop()
        if len(set(mapped)) >= 3:
            compact_faces.append(tuple(mapped))
            compact_sources.append(source_id)
    return compact_vertices, compact_faces, compact_sources



def extend_roof_mesh_eaves(vertices, faces, face_source_ids, polygon_ccw,
                            offset_polygon, overhang, pitch_tan):
    """Extend HIP roof boundary edges along their existing facet planes.

    The straight-skeleton core is intentionally built from the original eave
    loop. Changing overhang must not change its event graph or move internal
    ridge/valley nodes. Only vertices lying on each source eave edge are moved
    to the corresponding offset edge; their height is lowered by
    overhang * pitch_tan. Interior skeleton vertices remain fixed.
    """
    distance = float(overhang)
    if distance <= 1.0e-10:
        return list(vertices), list(faces), list(face_source_ids)
    count = len(polygon_ccw)
    if len(offset_polygon) != count or len(face_source_ids) != len(faces):
        raise SkeletonError("Не удалось согласовать исходный и расширенный контуры карниза.")

    scale = max(1.0, max(math.hypot(
        polygon_ccw[(i + 1) % count][0] - polygon_ccw[i][0],
        polygon_ccw[(i + 1) % count][1] - polygon_ccw[i][1]
    ) for i in range(count)))
    tol = max(1.0e-8, scale * 1.0e-8)
    vertex_map = {}
    out_vertices = []
    out_faces = []

    def add_vertex(point):
        key = _key3(point, tol)
        found = vertex_map.get(key)
        if found is None:
            found = len(out_vertices)
            vertex_map[key] = found
            out_vertices.append(tuple(float(v) for v in point))
        return found

    for face, source_id in zip(faces, face_source_ids):
        source_edges = _source_id_tuple(source_id)
        # Non-HIP faces (e.g. gable) do not have source contour edge ids.
        if not source_edges:
            mapped = tuple(add_vertex(vertices[i]) for i in face)
            out_faces.append(mapped)
            continue

        moved = []
        for vertex_id in face:
            x, y, z = vertices[vertex_id]
            candidates = []
            for edge_index in source_edges:
                edge_index %= count
                a = polygon_ccw[edge_index]
                b = polygon_ccw[(edge_index + 1) % count]
                dx, dy = b[0] - a[0], b[1] - a[1]
                edge_length = math.hypot(dx, dy)
                if edge_length <= tol:
                    continue
                relx, rely = x - a[0], y - a[1]
                along = (relx * dx + rely * dy) / (edge_length * edge_length)
                side_distance = (dx * rely - dy * relx) / edge_length
                if abs(side_distance) <= tol * 20.0 and -tol <= along <= 1.0 + tol:
                    tx, ty = dx / edge_length, dy / edge_length
                    outward = (ty, -tx)  # CCW contour: outward is to the right.
                    if along <= tol / edge_length:
                        ox, oy = offset_polygon[edge_index]
                    elif along >= 1.0 - tol / edge_length:
                        ox, oy = offset_polygon[(edge_index + 1) % count]
                    else:
                        ox, oy = (x + outward[0] * distance,
                                  y + outward[1] * distance)
                    candidates.append((ox, oy))
            if candidates:
                # At a shared contour corner both incident edge ids resolve
                # to the same mitered offset vertex (within tolerance).
                ox = sum(point[0] for point in candidates) / len(candidates)
                oy = sum(point[1] for point in candidates) / len(candidates)
                moved.append((ox, oy, z - distance * float(pitch_tan)))
            else:
                moved.append((x, y, z))
        out_faces.append(tuple(add_vertex(point) for point in moved))

    _validate_face_planarity(out_vertices, out_faces, max(scale * 2.0e-7, 1.0e-8))
    _validate_roof_mesh_topology(
        out_vertices, out_faces, offset_polygon, max(scale * 2.0e-8, 1.0e-8)
    )
    return out_vertices, out_faces, list(face_source_ids)


def _unit_face_normal(vertices, face):
    points = [vertices[index] for index in face]
    normal = _newell_normal(points)
    length = _length3(normal)
    if length <= 1.0e-12:
        raise SkeletonError("Straight skeleton: вырожденная грань при расчёте нормали.")
    result = tuple(component / length for component in normal)
    if result[2] < 0.0:
        result = tuple(-component for component in result)
    return result


def _source_id_tuple(source_id):
    if isinstance(source_id, (tuple, list, set)):
        values = [int(value) for value in source_id if int(value) >= 0]
    else:
        value = int(source_id)
        values = [value] if value >= 0 else []
    return tuple(sorted(set(values)))


def _merge_coplanar_roof_faces(vertices, faces, face_source_ids, scale):
    """Dissolve internal edges between truly coplanar roof facets.

    The merged face keeps the union of its source eave-edge ids so overhang
    extension can still move every boundary segment along the proper offset.
    Shared coplanar edges disappear from the mesh and therefore cannot be
    mistaken for ridge seams.
    """
    verts = list(vertices)
    loops = [list(face) for face in faces]
    sources = list(face_source_ids)
    distance_tol = max(1.0e-8, float(scale) * 2.0e-8)
    normal_tol = 2.0e-8
    max_iterations = max(8, len(loops) * len(loops) * 2)

    for _iteration in range(max_iterations):
        edge_uses = defaultdict(list)
        for face_index, face in enumerate(loops):
            for a, b in zip(face, face[1:] + face[:1]):
                key = (a, b) if a < b else (b, a)
                edge_uses[key].append((face_index, a, b))

        merged = False
        for edge_key, uses in edge_uses.items():
            if len(uses) != 2:
                continue
            (face_a, a0, a1), (face_b, b0, b1) = uses
            if face_a == face_b or not (a0 == b1 and a1 == b0):
                continue

            face_a_loop = loops[face_a]
            face_b_loop = loops[face_b]
            # Only merge a pair that shares exactly one complete edge.
            edges_a = {tuple(sorted((x, y))) for x, y in zip(face_a_loop, face_a_loop[1:] + face_a_loop[:1])}
            edges_b = {tuple(sorted((x, y))) for x, y in zip(face_b_loop, face_b_loop[1:] + face_b_loop[:1])}
            common_edges = edges_a & edges_b
            if len(common_edges) != 1:
                continue

            normal_a = _unit_face_normal(verts, face_a_loop)
            normal_b = _unit_face_normal(verts, face_b_loop)
            dot_normals = _dot3(normal_a, normal_b)
            if dot_normals < 1.0 - normal_tol:
                continue
            origin = verts[face_a_loop[0]]
            if any(abs(_dot3(normal_a, _sub3(verts[index], origin))) > distance_tol
                   for index in face_b_loop):
                continue

            # Cancel the two oppositely directed shared half-edges and trace
            # the remaining single outer boundary. If the union is not a
            # simple loop, leave these two faces untouched.
            boundary = []
            for face_loop in (face_a_loop, face_b_loop):
                for a, b in zip(face_loop, face_loop[1:] + face_loop[:1]):
                    key = (a, b) if a < b else (b, a)
                    if key == edge_key:
                        continue
                    boundary.append((a, b))
            outgoing = defaultdict(list)
            incoming = defaultdict(int)
            for a, b in boundary:
                outgoing[a].append(b)
                incoming[b] += 1
            all_ids = set(outgoing) | set(incoming)
            if not all(len(outgoing.get(index, ())) == 1 and incoming.get(index, 0) == 1
                       for index in all_ids):
                continue

            start_vertex = boundary[0][0]
            merged_loop = [start_vertex]
            current = start_vertex
            seen = {start_vertex}
            valid = True
            for _step in range(len(boundary) + 1):
                next_vertex = outgoing.get(current, [None])[0]
                if next_vertex is None:
                    valid = False
                    break
                if next_vertex == start_vertex:
                    break
                if next_vertex in seen:
                    valid = False
                    break
                merged_loop.append(next_vertex)
                seen.add(next_vertex)
                current = next_vertex
            else:
                valid = False
            if not valid or len(merged_loop) < 3 or len(merged_loop) != len(boundary):
                continue

            # Preserve all contributing eave-edge ids for overhang extension.
            combined_sources = tuple(sorted(set(
                _source_id_tuple(sources[face_a]) + _source_id_tuple(sources[face_b])
            )))
            if not combined_sources:
                combined_source = -1
            elif len(combined_sources) == 1:
                combined_source = combined_sources[0]
            else:
                combined_source = combined_sources

            loops[face_a] = merged_loop
            sources[face_a] = combined_source
            loops.pop(face_b)
            sources.pop(face_b)
            merged = True
            break

        if not merged:
            break

    # Dissolve collinear boundary vertices that are now owned only by one
    # merged face. A point shared with any other (necessarily non-coplanar)
    # face is protected so adjacent facets retain matching edge subdivisions.
    vertex_faces = defaultdict(set)
    for face_index, face in enumerate(loops):
        for vertex_id in face:
            vertex_faces[vertex_id].add(face_index)
    for face_index, face in enumerate(loops):
        changed = True
        while changed and len(face) > 3:
            changed = False
            for local_index, vertex_id in enumerate(face):
                if len(vertex_faces[vertex_id]) != 1:
                    continue
                previous_id = face[(local_index - 1) % len(face)]
                next_id = face[(local_index + 1) % len(face)]
                v1 = _sub3(verts[vertex_id], verts[previous_id])
                v2 = _sub3(verts[next_id], verts[vertex_id])
                cross = _cross3(v1, v2)
                threshold = distance_tol * max(_length3(v1), _length3(v2), 1.0)
                if (_length3(cross) <= threshold and _dot3(v1, v2) >= -distance_tol):
                    face.pop(local_index)
                    changed = True
                    break

    # Compact all points no longer referenced after coplanar edge dissolves.
    used = sorted({index for face in loops for index in face})
    remap = {old: new for new, old in enumerate(used)}
    compact_vertices = [verts[index] for index in used]
    compact_faces = [tuple(remap[index] for index in face) for face in loops]
    return compact_vertices, compact_faces, sources


def _wavefront_event_key(event):
    """Return a stable identity for one currently queued event."""
    if isinstance(event, _EdgeEvent):
        a, b = sorted((event.vertex_a.uid, event.vertex_b.uid))
        return ("EDGE", a, b)
    start_uid = event.target_start.uid if event.target_start is not None else -1
    end_uid = event.target_end.uid if event.target_end is not None else -1
    return ("SPLIT", event.vertex.uid, event.opposite_edge.index,
            start_uid, end_uid)


def _enqueue_missing_wavefront_events(slav, current_time, projected_edge_events,
                                      event_queue, queue_order):
    """Add newly enabled events without disturbing existing queue order.

    A local split/collapse can enable an event on a neighbouring vertex that
    was not replaced. The original solver only scheduled events returned from
    the replacement vertices, so it could exhaust the queue while a live LAV
    remained. We rescan all live vertices after each topology mutation, but
    preserve already queued events and their FIFO tie order. This avoids
    changing the deterministic order of simultaneous collapses.
    """
    present = {_wavefront_event_key(item[2]) for item in event_queue}
    for lav in list(slav.lavs):
        for vertex in list(lav):
            if not vertex.valid:
                continue
            event = vertex.next_event(current_time, projected_edge_events)
            if event is None:
                continue
            key = _wavefront_event_key(event)
            if key in present:
                continue
            present.add(key)
            queue_order += 1
            heapq.heappush(event_queue, (event.distance, queue_order, event))
    return queue_order


def _enqueue_wavefront_events_for_vertices(vertices, current_time,
                                              projected_edge_events, event_queue,
                                              queue_order):
    """Refresh only vertices affected by the latest local topology mutation.

    A collapse changes its replacement vertex and two neighbours; a split
    changes two new vertices and four re-linked endpoints. The full wavefront
    scan remains as a queue-exhaustion recovery path, not the normal event path.
    """
    present = {_wavefront_event_key(item[2]) for item in event_queue}
    seen_vertices = set()
    for vertex in vertices:
        if vertex is None or not getattr(vertex, "valid", False):
            continue
        if vertex.lav is None or vertex.uid in seen_vertices:
            continue
        seen_vertices.add(vertex.uid)
        event = vertex.next_event(current_time, projected_edge_events)
        if event is None:
            continue
        key = _wavefront_event_key(event)
        if key in present:
            continue
        present.add(key)
        queue_order += 1
        heapq.heappush(event_queue, (event.distance, queue_order, event))
    return queue_order


def _build_roof_mesh_impl(polygon_ccw, pitch_tan, eave_lift=0.0,
                          projected_edge_events=False, edge_speeds=None,
                          face_planes=None, validate_topology=True,
                          merge_coplanar=True):
    """Build an exact low-poly roof from a simple CCW XY polygon.

    Returns (vertices, faces, face_source_ids). Each source id is the index of
    the original polygon edge that generated that planar roof facet.
    """
    if len(polygon_ccw) < 3:
        raise SkeletonError("Для крыши нужно не менее трёх точек.")
    if abs(float(pitch_tan)) <= 1.0e-10:
        vertices = [(float(x), float(y), float(eave_lift)) for x, y in polygon_ccw]
        return vertices, [tuple(range(len(vertices)))], [0]

    # Remove only microscopic angular noise from genuinely orthogonal loops.
    # Real free-angle contours are left untouched and use their own solver path.
    if edge_speeds is None:
        polygon_ccw, _was_orthogonalized = _orthogonalize_nearly_orthogonal_contour(
            polygon_ccw
        )

    # The event implementation uses clockwise coordinates. Per-edge speeds
    # and support planes are mapped from the original CCW edge order.
    clockwise = [_V2(x, y) for x, y in reversed(polygon_ccw)]
    clockwise_speeds = None
    clockwise_planes = None
    if edge_speeds is not None:
        count = len(polygon_ccw)
        if len(edge_speeds) != count:
            raise SkeletonError("Weighted skeleton: число скоростей не совпадает с числом рёбер.")
        clockwise_speeds = [
            float(edge_speeds[(count - 2 - j) % count]) for j in range(count)
        ]
        if face_planes is None or len(face_planes) != count:
            raise SkeletonError("Weighted skeleton: для каждого ребра нужна опорная плоскость.")
        clockwise_planes = [
            face_planes[(count - 2 - j) % count] for j in range(count)
        ]
    slav = _SLAV(clockwise, clockwise_speeds)

    def current_segments(time):
        return slav.active_segments(time)

    current_time = 0.0
    snapshots = {
        (edge_id, vertex_a.uid, vertex_b.uid): (point_a, point_b)
        for edge_id, vertex_a, vertex_b, point_a, point_b in current_segments(0.0)
    }
    face_patches = defaultdict(list)

    event_queue = []
    queue_order = 0
    for lav in slav.lavs:
        for vertex in lav:
            event = vertex.next_event(current_time, projected_edge_events)
            if event is not None:
                queue_order += 1
                heapq.heappush(event_queue, (event.distance, queue_order, event))

    processed = 0
    event_mode = bool(projected_edge_events or edge_speeds is not None)
    tried_event_modes = set()
    event_limit = max(100, len(polygon_ccw) * len(polygon_ccw) * 40)
    scale = max(
        max(math.hypot(polygon_ccw[(i + 1) % len(polygon_ccw)][0] - polygon_ccw[i][0],
                       polygon_ccw[(i + 1) % len(polygon_ccw)][1] - polygon_ccw[i][1])
            for i in range(len(polygon_ccw))),
        1.0,
    )
    time_epsilon = max(1.0e-9, scale * 1.0e-9)

    while slav.lavs:
        if not event_queue:
            if edge_speeds is not None:
                event_queue = []
                queue_order = _enqueue_missing_wavefront_events(
                    slav, current_time, True, event_queue, 0
                )
                if not event_queue:
                    raise SkeletonError(
                        "Weighted skeleton не смог завершить wavefront: "
                        "для активных сегментов не найдено допустимых взвешенных событий."
                    )
                event_mode = True
            else:
                tried_event_modes.add(event_mode)
                alternate_mode = not event_mode
                if alternate_mode in tried_event_modes:
                    raise SkeletonError(
                        "Straight skeleton не смог завершить построение: активный "
                        "wavefront остался без допустимых событий схлопывания."
                    )
                event_queue = []
                queue_order = _enqueue_missing_wavefront_events(
                    slav, current_time, alternate_mode, event_queue, 0
                )
                if not event_queue:
                    tried_event_modes.add(alternate_mode)
                    raise SkeletonError(
                        "Straight skeleton не смог завершить построение: для оставшихся "
                        "сегментов не найдено событие ни одним способом расчёта."
                    )
                event_mode = alternate_mode

        _priority, _order, event = heapq.heappop(event_queue)
        if isinstance(event, _EdgeEvent):
            # Queued collapse events become stale when an earlier split/collapse
            # changes the wavefront. Both vertices may still be alive but no
            # longer adjacent; never collapse a non-edge pair.
            if (not event.vertex_a.valid or not event.vertex_b.valid
                    or event.vertex_a.next is not event.vertex_b
                    or event.vertex_a.edge_right.index != event.vertex_b.edge_left.index
                    or event.vertex_a.lav is not event.vertex_b.lav):
                continue
        else:
            if not event.vertex.valid or event.vertex.lav is None:
                continue
            # The target original edge must still be represented by a live
            # wavefront segment. The finite-segment check is repeated at pop
            # time because the event may have waited behind another event.
            target_live = False
            try:
                for edge_id, _va, _vb, segment_a, segment_b in slav.active_segments(event.distance):
                    if (edge_id == event.opposite_edge.index
                            and _point_on_segment_inclusive(
                                event.intersection_point, segment_a, segment_b,
                                max(1.0e-7, abs(segment_b - segment_a) * 1.0e-7))):
                        # A simultaneous collapse may replace the active end
                        # vertices of the same original edge. Rebind the split
                        # to whichever live finite segment still contains the
                        # exact collision point instead of discarding a valid
                        # same-time event because its old endpoint objects are stale.
                        event.target_start = _va
                        event.target_end = _vb
                        target_live = True
                        break
            except Exception:
                target_live = False
            if not target_live:
                continue

        event_time = event.distance
        if event_time < current_time - time_epsilon:
            continue

        if event_time > current_time + time_epsilon:
            next_snapshots = {}
            for edge_id, vertex_a, vertex_b, point_a, point_b in current_segments(event_time):
                key = (edge_id, vertex_a.uid, vertex_b.uid)
                old = snapshots.get(key)
                if old is not None:
                    if clockwise_planes is None:
                        z0 = float(eave_lift) + current_time * float(pitch_tan)
                        z1 = float(eave_lift) + event_time * float(pitch_tan)
                        quad = [
                            (old[0].x, old[0].y, z0),
                            (old[1].x, old[1].y, z0),
                            (point_b.x, point_b.y, z1),
                            (point_a.x, point_a.y, z1),
                        ]
                    else:
                        plane = clockwise_planes[edge_id]
                        def lift_at(point):
                            x_value = float(point.x)
                            y_value = float(point.y)
                            return (
                                x_value, y_value,
                                float(plane[0]) * x_value
                                + float(plane[1]) * y_value
                                + float(plane[2])
                            )
                        quad = [
                            lift_at(old[0]), lift_at(old[1]),
                            lift_at(point_b), lift_at(point_a)
                        ]
                    quad_xy = [(p[0], p[1]) for p in quad]
                    area = abs(_poly_area_2d(quad_xy))
                    edge_lengths = [
                        math.hypot(
                            quad_xy[(i + 1) % 4][0] - quad_xy[i][0],
                            quad_xy[(i + 1) % 4][1] - quad_xy[i][1],
                        )
                        for i in range(4)
                    ]
                    # The swept patch can be much smaller than the overall
                    # footprint (especially around simultaneous collapses in
                    # narrow orthogonal L contours). A global scale^2 cutoff
                    # deletes valid local facets when one limb is long.
                    local_area_scale = max(
                        edge_lengths[i] * edge_lengths[(i + 1) % 4]
                        for i in range(4)
                    )
                    area_tolerance = max(
                        local_area_scale * 1.0e-14,
                        scale * scale * 1.0e-24,
                        1.0e-30,
                    )
                    if area > area_tolerance:
                        face_patches[edge_id].append(quad)
                next_snapshots[key] = (point_a, point_b)

            current_time = event_time
            snapshots = next_snapshots

        if isinstance(event, _EdgeEvent):
            previous_vertex = event.vertex_a.prev
            following_vertex = event.vertex_b.next
            slav.handle_edge_event(event, event_mode)
            topology_changed = not event.vertex_a.valid or not event.vertex_b.valid
            if topology_changed:
                replacement = (
                    previous_vertex.next if previous_vertex is not None else None
                )
                affected_vertices = (
                    previous_vertex, replacement, following_vertex,
                )
            else:
                affected_vertices = ()
        else:
            previous_vertex = event.vertex.prev
            following_vertex = event.vertex.next
            slav.handle_split_event(event, event_mode)
            topology_changed = not event.vertex.valid
            if topology_changed:
                target_start = event.target_start
                target_end = event.target_end
                first_new = (
                    previous_vertex.next if previous_vertex is not None else None
                )
                second_new = (
                    target_start.next if target_start is not None else None
                )
                affected_vertices = (
                    previous_vertex, first_new, target_end,
                    target_start, second_new, following_vertex,
                )
            else:
                affected_vertices = ()

        if topology_changed:
            queue_order = _enqueue_wavefront_events_for_vertices(
                affected_vertices, current_time, event_mode,
                event_queue, queue_order,
            )
            tried_event_modes.clear()

        # Any split/collapse changes the active edge segments at the same wavefront time.
        snapshots = {
            (edge_id, vertex_a.uid, vertex_b.uid): (point_a, point_b)
            for edge_id, vertex_a, vertex_b, point_a, point_b in current_segments(current_time)
        }

        processed += 1
        if processed > event_limit:
            raise SkeletonError("Straight skeleton: превышен лимит событий. Контур слишком вырожден.")

    if slav.lavs:
        raise SkeletonError(
            "Straight skeleton не смог завершить построение для этого контура. "
            "Проверьте острые углы, узкие участки и почти совпадающие вершины."
        )
    if not face_patches:
        raise SkeletonError("Straight skeleton не создал ни одного кровельного ската.")

    # Restore each source edge's original CCW index. The event engine was fed
    # the reversed contour, so edge j in that list corresponds to CCW edge n-2-j.
    count = len(polygon_ccw)
    face_loops = []
    for reversed_edge_id, patches in face_patches.items():
        original_edge_id = (count - 2 - reversed_edge_id) % count
        for loop in _merge_face_patches(patches, scale):
            face_loops.append((original_edge_id, loop))

    if not face_loops:
        raise SkeletonError("Не удалось объединить плоские участки скатов.")

    face_loops = _split_global_t_junctions(face_loops, scale)

    tolerance = max(1.0e-8, scale * 1.0e-8)
    vertex_map = {}
    vertices = []
    faces = []
    face_source_ids = []
    for source_id, loop in face_loops:
        face = []
        for point in loop:
            key = _key3(point, tolerance)
            index = vertex_map.get(key)
            if index is None:
                index = len(vertices)
                vertex_map[key] = index
                vertices.append(tuple(float(v) for v in point))
            if not face or face[-1] != index:
                face.append(index)
        if len(face) > 2 and face[0] == face[-1]:
            face.pop()
        if len(set(face)) >= 3:
            # Every roof facet must face outward/up in the XY projection.
            if _newell_normal([vertices[i] for i in face])[2] < 0.0:
                face.reverse()
            faces.append(tuple(face))
            face_source_ids.append(source_id)

    vertices, faces, face_source_ids = _resolve_triangle_spike_junctions(
        vertices, faces, face_source_ids, polygon_ccw, scale
    )
    if merge_coplanar:
        vertices, faces, face_source_ids = _merge_coplanar_roof_faces(
            vertices, faces, face_source_ids, scale
        )

    _validate_face_planarity(vertices, faces, max(scale * 1.0e-7, 1.0e-8))
    if validate_topology:
        _validate_roof_mesh_topology(
            vertices, faces, polygon_ccw, max(scale * 1.0e-8, 1.0e-8)
        )
    return vertices, faces, face_source_ids




def build_weighted_roof_mesh(polygon_ccw, edge_speeds, face_planes,
                             validate_topology=True, merge_coplanar=True):
    """Build a roof with an independent normal speed/support plane per eave edge."""
    count = len(polygon_ccw)
    if count < 3 or len(edge_speeds) != count or len(face_planes) != count:
        raise SkeletonError("Weighted skeleton: нужны точки, скорости и плоскости на каждое ребро.")
    speeds = []
    planes = []
    for index, speed in enumerate(edge_speeds):
        value = float(speed)
        if not math.isfinite(value) or value <= 0.0:
            raise SkeletonError("Weighted skeleton: скорость ребра {} некорректна.".format(index + 1))
        speeds.append(value)
        plane = tuple(float(v) for v in face_planes[index])
        if len(plane) != 3 or not all(math.isfinite(v) for v in plane):
            raise SkeletonError("Weighted skeleton: опорная плоскость {} некорректна.".format(index + 1))
        planes.append(plane)
    return _build_roof_mesh_impl(
        polygon_ccw, 1.0, 0.0,
        projected_edge_events=True,
        edge_speeds=speeds,
        face_planes=planes,
        validate_topology=bool(validate_topology),
        merge_coplanar=bool(merge_coplanar),
    )


def build_roof_mesh(polygon_ccw, pitch_tan, eave_lift=0.0, allow_oblique=False):
    """Build a roof from a simple CCW contour.

    ``allow_oblique=False`` preserves the established event construction.
    The optional free-angle mode uses direct edge-collapse timing and falls
    back to the established solver only for exact/near-simultaneous cases where
    the projected event sequence is degenerate. Both paths run the same
    straight-skeleton model and the same topology/planarity validators.
    """
    if not allow_oblique:
        return _build_roof_mesh_impl(polygon_ccw, pitch_tan, eave_lift, False)
    try:
        return _build_roof_mesh_impl(polygon_ccw, pitch_tan, eave_lift, True)
    except SkeletonError as projected_error:
        try:
            return _build_roof_mesh_impl(polygon_ccw, pitch_tan, eave_lift, False)
        except SkeletonError as classic_error:
            raise SkeletonError(
                "Режим свободных углов не смог корректно завершить wavefront. "
                "Попробуйте проверить острые/почти совпадающие углы контура. "
                f"Расчёт свободных углов: {projected_error}. "
                f"Резервный расчёт: {classic_error}"
            ) from classic_error


def extract_roof_seams(vertices, faces, face_source_ids, polygon_ccw):
    """Extract only real dihedral breaks between roof facets.

    Coplanar adjacent faces (180-degree continuation) are not seams and never
    create a ridge/valley profile. For all other shared edges, the signed
    dihedral orientation determines whether the edge is a convex ridge or a
    concave valley. This remains valid after coplanar face dissolution has
    combined several original source facets into one n-gon.
    """
    edge_uses = defaultdict(list)
    for face_index, face in enumerate(faces):
        for i, a in enumerate(face):
            b = face[(i + 1) % len(face)]
            key = (a, b) if a < b else (b, a)
            edge_uses[key].append((face_index, a, b))

    normals = [_unit_face_normal(vertices, face) for face in faces]
    records = []
    angle_tolerance = 1.0e-7

    for _key, uses in edge_uses.items():
        if len(uses) != 2:
            continue
        (face_a, a0, a1), (face_b, b0, b1) = uses
        if a0 == b0 and a1 == b1:
            continue

        normal_a = normals[face_a]
        normal_b = normals[face_b]
        cosine = max(-1.0, min(1.0, _dot3(normal_a, normal_b)))
        if cosine >= math.cos(angle_tolerance):
            # A 180-degree surface continuation: no seam, no cap.
            continue

        edge_vector = _sub3(vertices[a1], vertices[a0])
        edge_length = _length3(edge_vector)
        if edge_length <= 1.0e-12:
            continue
        edge_direction = tuple(value / edge_length for value in edge_vector)
        signed_dihedral = _dot3(_cross3(normal_a, normal_b), edge_direction)
        if abs(signed_dihedral) <= math.sin(angle_tolerance):
            continue
        kind = "RIDGE" if signed_dihedral > 0.0 else "VALLEY"
        records.append((vertices[a0], vertices[a1], face_a, face_b, kind))

    return records


def roof_face_plane(vertices, face):
    """Return normalized plane coefficients (z = ax + by + c) for one planar face."""
    points = [vertices[i] for i in face]
    origin = points[0]
    normal = None
    for i in range(1, len(points) - 1):
        a = _sub3(points[i], origin)
        b = _sub3(points[i + 1], origin)
        candidate = _cross3(a, b)
        if _length3(candidate) > 1.0e-10:
            normal = candidate
            break
    if normal is None or abs(normal[2]) < 1.0e-10:
        raise SkeletonError("Невозможно вычислить плоскость одного из скатов.")
    nx, ny, nz = normal
    a = -nx / nz
    b = -ny / nz
    c = origin[2] - a * origin[0] - b * origin[1]
    return (a, b, c)


def build_seam_cap_mesh(
    surface_vertices,
    faces,
    seams,
    profile_kind,
    width,
    extrusion_offset,
    end_extension=0.0,
    seat_sink_offset=(0.0, 0.0, 0.0),
    outline=None,
):
    """Build a welded ridge/valley profile network from the roof seam graph.

    Segment ends are joined with a two-edge miter when a seam continues through
    a degree-two node. At branch nodes (degree >= 3), a small folded junction
    patch is built around the shared node instead of leaving overlapping capped
    prisms. Degree-one ends can be clipped by the actual roof outline: the end
    section is intersected with the outline edge, so the cut follows the eave
    contour rather than making a square cut normal to the seam.

    ``end_extension`` is retained as the stable API/property name for saved
    Blender scenes, but when ``outline`` is supplied it means setback inward
    from the outline. Without an outline it preserves the legacy extension.
    All lengths/vectors use the coordinate space of ``surface_vertices``.
    """
    if not surface_vertices or not faces or not seams:
        return [], []

    kind = str(profile_kind).upper()
    if kind not in {"RIDGE", "VALLEY"}:
        raise SkeletonError("Тип профиля должен быть RIDGE или VALLEY.")

    half_width = max(float(width), 1.0e-5) * 0.5
    extrusion = tuple(float(v) for v in extrusion_offset)
    sink = tuple(float(v) for v in seat_sink_offset)
    end_setback = max(0.0, float(end_extension))
    outline_points = None
    if outline is not None and len(outline) >= 3:
        outline_points = [(float(p[0]), float(p[1])) for p in outline]

    scale = max(
        1.0,
        max(math.hypot(surface_vertices[i][0] - surface_vertices[j][0],
                       surface_vertices[i][1] - surface_vertices[j][1])
            for face in faces for i, j in zip(face, face[1:] + face[:1]))
    )
    tolerance = max(1.0e-8, scale * 1.0e-8)
    node_tolerance = max(1.0e-7, scale * 1.0e-7)

    def add3(a, b):
        return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

    def sub2(a, b):
        return (a[0] - b[0], a[1] - b[1])

    def dot2(a, b):
        return a[0] * b[0] + a[1] * b[1]

    def cross2(a, b):
        return a[0] * b[1] - a[1] * b[0]

    def norm2(v):
        length = math.hypot(v[0], v[1])
        if length <= 1.0e-12:
            return (0.0, 0.0)
        return (v[0] / length, v[1] / length)

    def plane_z(plane, x, y):
        return plane[0] * x + plane[1] * y + plane[2]

    def point_key(point):
        return _key3(point, tolerance)

    planes = [roof_face_plane(surface_vertices, face) for face in faces]
    segments = []
    nodes = defaultdict(list)
    for seam in seams:
        a, b, face_left, face_right, seam_kind = seam
        if str(seam_kind).upper() != kind:
            continue
        if face_left >= len(planes) or face_right >= len(planes):
            continue
        dx = float(b[0]) - float(a[0])
        dy = float(b[1]) - float(a[1])
        length = math.hypot(dx, dy)
        if length <= 1.0e-9:
            continue
        tangent = (dx / length, dy / length)
        normal = (-tangent[1], tangent[0])
        index = len(segments)
        record = {
            "a": tuple(float(v) for v in a),
            "b": tuple(float(v) for v in b),
            "face_left": int(face_left),
            "face_right": int(face_right),
            "tangent": tangent,
            "normal": normal,
            "length": length,
        }
        segments.append(record)
        nodes[point_key(a)].append((index, True))
        nodes[point_key(b)].append((index, False))

    if not segments:
        return [], []

    # Plane intersections can differ by tiny floating-point amounts at a
    # skeleton node. Snap the common centre height to the average incident
    # plane height before welding, keeping the cap network topologically joined.
    node_centres = {}
    for node_key, incident in nodes.items():
        sample = segments[incident[0][0]]["a" if incident[0][1] else "b"]
        x, y = sample[0], sample[1]
        centre_heights = []
        for seg_index, _is_start in incident:
            seg = segments[seg_index]
            centre_heights.append(0.5 * (
                plane_z(planes[seg["face_left"]], x, y)
                + plane_z(planes[seg["face_right"]], x, y)
            ))
        node_centres[node_key] = (x, y, sum(centre_heights) / len(centre_heights))

    def nearest_outline_edge(point):
        if outline_points is None:
            return None
        best = None
        best_distance = float("inf")
        px, py = point[0], point[1]
        for i, a in enumerate(outline_points):
            b = outline_points[(i + 1) % len(outline_points)]
            edge = sub2(b, a)
            length_sq = dot2(edge, edge)
            if length_sq <= tolerance * tolerance:
                continue
            t = max(0.0, min(1.0, dot2(sub2((px, py), a), edge) / length_sq))
            q = (a[0] + edge[0] * t, a[1] + edge[1] * t)
            distance = math.hypot(px - q[0], py - q[1])
            if distance < best_distance:
                best_distance = distance
                best = (q, edge, distance)
        if best is None or best[2] > node_tolerance * 10.0:
            return None
        return best[0], best[1]

    def intersect_parallel_line(point, tangent, line_point, line_direction):
        denominator = cross2(tangent, line_direction)
        if abs(denominator) <= 1.0e-10:
            return (point[0], point[1])
        amount = cross2(sub2(line_point, (point[0], point[1])), line_direction) / denominator
        return (point[0] + tangent[0] * amount, point[1] + tangent[1] * amount)

    def miter_offset(seg_index, is_start):
        incident = nodes[point_key(segments[seg_index]["a" if is_start else "b"])]
        if len(incident) != 2:
            return None
        other_index = incident[0][0] if incident[1][0] == seg_index else incident[1][0]
        n = segments[seg_index]["normal"]
        other_n = segments[other_index]["normal"]
        if dot2(n, other_n) < 0.0:
            other_n = (-other_n[0], -other_n[1])
        bisector = norm2((n[0] + other_n[0], n[1] + other_n[1]))
        denominator = dot2(bisector, n)
        if abs(denominator) <= 1.0e-5:
            return None
        distance = half_width / denominator
        # A sharp reversal should not create a kilometre-long miter spike.
        distance = max(-half_width * 4.0, min(half_width * 4.0, distance))
        return (bisector[0] * distance, bisector[1] * distance)

    def station(seg_index, is_start):
        seg = segments[seg_index]
        center = seg["a"] if is_start else seg["b"]
        tangent = seg["tangent"]
        normal = seg["normal"]
        node_key = point_key(center)
        incident_count = len(nodes[node_key])
        left_plane = planes[seg["face_left"]]
        right_plane = planes[seg["face_right"]]

        offset = miter_offset(seg_index, is_start) if incident_count == 2 else None
        if offset is None:
            offset = (normal[0] * half_width, normal[1] * half_width)
        left_xy = (center[0] + offset[0], center[1] + offset[1])
        right_xy = (center[0] - offset[0], center[1] - offset[1])
        centre_z = node_centres[node_key][2]
        left_z = plane_z(left_plane, left_xy[0], left_xy[1])
        right_z = plane_z(right_plane, right_xy[0], right_xy[1])
        lower = [
            (left_xy[0], left_xy[1], left_z),
            (center[0], center[1], centre_z),
            (right_xy[0], right_xy[1], right_z),
        ]

        # Degree-one ends are clipped against the nearest actual outline edge.
        # The three profile rails are extended only as far as that offset line,
        # which creates a contour-aligned miter cut rather than a square cap.
        if incident_count == 1 and outline_points is not None:
            boundary = nearest_outline_edge(center)
            if boundary is not None:
                edge_point, edge_direction = boundary
                setback = min(end_setback, seg["length"] * 0.45)
                sign = 1.0 if is_start else -1.0
                clip_point = (
                    edge_point[0] + tangent[0] * setback * sign,
                    edge_point[1] + tangent[1] * setback * sign,
                )
                clipped = []
                for i, point in enumerate(lower):
                    xy = intersect_parallel_line(point, tangent, clip_point, edge_direction)
                    plane = left_plane if i == 0 else right_plane if i == 2 else None
                    z = (0.5 * (plane_z(left_plane, xy[0], xy[1])
                                + plane_z(right_plane, xy[0], xy[1])) if plane is None
                         else plane_z(plane, xy[0], xy[1]))
                    clipped.append((xy[0], xy[1], z))
                lower = clipped
        elif incident_count == 1 and outline_points is None and end_setback > 0.0:
            # Legacy external callers without an outline retain the old
            # outward extension behaviour.
            amount = -end_setback if is_start else end_setback
            lower = [
                (p[0] + tangent[0] * amount, p[1] + tangent[1] * amount, p[2])
                for p in lower
            ]

        lower = [add3(point, sink) for point in lower]
        upper = [add3(point, extrusion) for point in lower]
        return lower + upper

    out_vertices = []
    out_faces = []
    vertex_map = {}

    def add_vertex(point, weld_scope=None):
        coordinate_key = point_key(point)
        key = (coordinate_key, weld_scope) if weld_scope is not None else (coordinate_key, None)
        index = vertex_map.get(key)
        if index is None:
            index = len(out_vertices)
            vertex_map[key] = index
            out_vertices.append(tuple(float(v) for v in point))
        return index

    for seg_index, seg in enumerate(segments):
        first = station(seg_index, True)
        second = station(seg_index, False)
        degree_a = len(nodes[point_key(seg["a"])])
        degree_b = len(nodes[point_key(seg["b"])])
        # Degree-two nodes are true continuous runs and are welded through
        # their miter sections. At a multi-branch node, keep each folded prism
        # closed and separately indexed inside this one Mesh object; forcing a
        # shared vertex fan there creates non-manifold overlapping junctions.
        scope_a = (seg_index, "A") if degree_a >= 3 else None
        scope_b = (seg_index, "B") if degree_b >= 3 else None
        ids0 = [add_vertex(p, scope_a) for p in first]
        ids1 = [add_vertex(p, scope_b) for p in second]
        lb0, cb0, rb0, lt0, ct0, rt0 = ids0
        lb1, cb1, rb1, lt1, ct1, rt1 = ids1

        candidate_faces = [
            (lb0, lb1, cb1, cb0),
            (cb0, cb1, rb1, rb0),
            (lt0, ct0, ct1, lt1),
            (ct0, rt0, rt1, ct1),
            (lb0, lb1, lt1, lt0),
            (rb0, rt0, rt1, rb1),
        ]
        # Degree-two ends share their miter section with the adjacent segment.
        # Degree-one ends are contour-clipped; branch ends remain closed as
        # separate folded solids to avoid creating a self-intersecting/non-
        # manifold star at a multi-way node.
        if degree_a != 2:
            candidate_faces.append((lb0, cb0, rb0, rt0, ct0, lt0))
        if degree_b != 2:
            candidate_faces.append((lb1, lt1, ct1, rt1, rb1, cb1))
        for face in candidate_faces:
            clean = tuple(dict.fromkeys(face))
            if len(clean) >= 3:
                out_faces.append(clean)

    # Remove duplicate / collapsed faces created where a seam terminates at
    # exactly the same point as a second graph branch.
    cleaned_faces = []
    seen_faces = set()
    for face in out_faces:
        clean = tuple(face)
        if len(set(clean)) < 3:
            continue
        canonical = tuple(sorted(set(clean)))
        if canonical in seen_faces:
            continue
        seen_faces.add(canonical)
        cleaned_faces.append(clean)

    return out_vertices, cleaned_faces



def _orient_closed_mesh_faces(vertices, faces):
    """Orient a closed polygon mesh consistently, component by component."""
    edge_uses = defaultdict(list)
    for face_index, face in enumerate(faces):
        for a, b in zip(face, face[1:] + face[:1]):
            key = (a, b) if a < b else (b, a)
            edge_uses[key].append((face_index, a, b))
    if any(len(uses) != 2 for uses in edge_uses.values()):
        raise SkeletonError("Нельзя согласовать нормали: профильная оболочка не замкнута.")

    face_edges = [[] for _ in faces]
    for uses in edge_uses.values():
        first, second = uses
        face_edges[first[0]].append((first[1], first[2], second[0], second[1], second[2]))
        face_edges[second[0]].append((second[1], second[2], first[0], first[1], first[2]))

    flip = {}
    components = []
    for start in range(len(faces)):
        if start in flip:
            continue
        flip[start] = False
        stack = [start]
        component = []
        while stack:
            current = stack.pop()
            component.append(current)
            for a, b, neighbour, na, nb in face_edges[current]:
                effective_a, effective_b = (b, a) if flip[current] else (a, b)
                # Neighbour must traverse the shared edge in the opposite direction.
                required_flip = (na == effective_a and nb == effective_b)
                if neighbour not in flip:
                    flip[neighbour] = required_flip
                    stack.append(neighbour)
                elif flip[neighbour] != required_flip:
                    raise SkeletonError("В профильной оболочке обнаружена неориентируемая связность.")
        components.append(component)

    result = [tuple(reversed(face)) if flip[i] else tuple(face)
              for i, face in enumerate(faces)]
    # Choose the outward orientation from the signed volume of each closed shell.
    for component in components:
        volume6 = 0.0
        for face_index in component:
            face = result[face_index]
            if len(face) < 3:
                continue
            origin = vertices[face[0]]
            for i in range(1, len(face) - 1):
                b = vertices[face[i]]
                c = vertices[face[i + 1]]
                volume6 += (
                    origin[0] * (b[1] * c[2] - b[2] * c[1])
                    + origin[1] * (b[2] * c[0] - b[0] * c[2])
                    + origin[2] * (b[0] * c[1] - b[1] * c[0])
                )
        if volume6 < 0.0:
            for face_index in component:
                result[face_index] = tuple(reversed(result[face_index]))
    return result


def build_inset_seam_profile_mesh(
    surface_vertices,
    faces,
    seams,
    profile_kind,
    width,
    extrusion_offset,
    end_setback=0.0,
    end_overhang=0.0,
    seat_sink_offset=(0.0, 0.0, 0.0),
    outline=None,
    end_offset=None,
    boundary_edges=None,
):
    """Create one continuous roof-following band network from face insets.

    Each selected seam edge is inset into its adjacent roof facets by ``width``
    measured on the actual sloping plane. Adjacent selected edges on the same
    facet share their miter corner; adjacent facets share the original seam
    edge. The resulting strip network is therefore welded before extrusion,
    including at connected branch nodes. Only exposed perimeter edges receive
    side walls. A single upper copy is translated by the requested global-Z
    vector to form the profile crown.

    ``end_offset`` moves degree-one seam ends along their tangent only when
    they lie on the supplied polygon outline or extracted mesh boundary:
    positive values extend outward and negative values retract inward. The
    older end_overhang/end_setback keyword pair is
    still accepted for compatibility when end_offset is not supplied.
    """
    if not surface_vertices or not faces or not seams:
        return [], []

    kind = str(profile_kind).upper()
    if kind not in {"RIDGE", "VALLEY"}:
        raise SkeletonError("Тип профиля должен быть RIDGE или VALLEY.")

    band_width = max(1.0e-6, float(width))
    extrusion = tuple(float(v) for v in extrusion_offset)
    sink = tuple(float(v) for v in seat_sink_offset)
    # One signed parameter replaces the old pair: positive extends outward,
    # negative retracts the end inward. The legacy arguments remain accepted
    # for backward compatibility with older test scripts and callers.
    net_end_shift = (float(end_offset) if end_offset is not None
                     else float(end_overhang) - float(end_setback))
    outline_points = [(float(p[0]), float(p[1])) for p in outline] if outline and len(outline) >= 3 else None

    def cross2(a, b):
        return a[0] * b[1] - a[1] * b[0]

    def sub2(a, b):
        return (a[0] - b[0], a[1] - b[1])

    def dot2(a, b):
        return a[0] * b[0] + a[1] * b[1]

    def length3(v):
        return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])

    def norm3(v):
        length = length3(v)
        if length <= 1.0e-12:
            return (0.0, 0.0, 0.0)
        return (v[0] / length, v[1] / length, v[2] / length)

    def cross3(a, b):
        return (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

    def line_intersection(p, r, q, s, eps):
        denominator = cross2(r, s)
        if abs(denominator) <= eps:
            return None
        t = cross2(sub2(q, p), s) / denominator
        return (p[0] + t * r[0], p[1] + t * r[1])

    def project_to_segment(point, a, b):
        ab = sub2(b, a)
        length_sq = dot2(ab, ab)
        if length_sq <= 1.0e-20:
            return a
        t = max(0.0, min(1.0, dot2(sub2(point, a), ab) / length_sq))
        return (a[0] + ab[0] * t, a[1] + ab[1] * t)

    def point_in_polygon(point, polygon, eps):
        x, y = point
        inside = False
        for i, a in enumerate(polygon):
            b = polygon[(i + 1) % len(polygon)]
            ab = sub2(b, a)
            ap = sub2((x, y), a)
            if abs(cross2(ab, ap)) <= eps and dot2(ap, sub2((x, y), b)) <= eps:
                return True
            if (a[1] > y) != (b[1] > y):
                at_x = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                if x < at_x:
                    inside = not inside
        return inside

    scale = max(1.0, max(length3(tuple(surface_vertices[a][k] - surface_vertices[b][k] for k in range(3)))
                         for face in faces for a, b in zip(face, face[1:] + face[:1])))
    tolerance = max(1.0e-8, scale * 1.0e-8)
    xy_epsilon = max(1.0e-10, scale * 1.0e-10)
    weld_tolerance = max(1.0e-8, scale * 1.0e-8)

    def point_key3(point):
        return _key3(point, weld_tolerance)

    boundary_segments = []
    for edge in boundary_edges or ():
        if len(edge) == 2 and len(edge[0]) >= 2 and len(edge[1]) >= 2:
            boundary_segments.append((
                (float(edge[0][0]), float(edge[0][1])),
                (float(edge[1][0]), float(edge[1][1])),
            ))

    def point_on_outline(point):
        x, y = point[0], point[1]
        segments = list(boundary_segments)
        if outline_points is not None:
            segments.extend(
                (outline_points[i], outline_points[(i + 1) % len(outline_points)])
                for i in range(len(outline_points))
            )
        for a, b in segments:
            ab = sub2(b, a)
            length_sq = dot2(ab, ab)
            if length_sq <= tolerance * tolerance:
                continue
            t = max(0.0, min(1.0, dot2(sub2((x, y), a), ab) / length_sq))
            q = (a[0] + ab[0] * t, a[1] + ab[1] * t)
            if math.hypot(x - q[0], y - q[1]) <= tolerance * 20.0:
                return True
        return False

    vertex_lookup = {point_key3(v): i for i, v in enumerate(surface_vertices)}
    selected_edges = set()
    selected_adjacency = defaultdict(list)
    for seam in seams:
        a, b, face_a, face_b, seam_kind = seam
        if str(seam_kind).upper() != kind:
            continue
        ia = vertex_lookup.get(point_key3(a))
        ib = vertex_lookup.get(point_key3(b))
        if ia is None or ib is None or ia == ib:
            continue
        edge_key = (ia, ib) if ia < ib else (ib, ia)
        selected_edges.add(edge_key)
        selected_adjacency[ia].append((ib, face_a, face_b))
        selected_adjacency[ib].append((ia, face_a, face_b))
    if not selected_edges:
        return [], []

    # A degree-one node gets an extension only when it really touches the eave.
    endpoint_shift = {}
    if abs(net_end_shift) > tolerance:
        for vertex_id, incident in selected_adjacency.items():
            if len(incident) != 1:
                continue
            point = surface_vertices[vertex_id]
            # A degree-one seam node can also be an internal termination
            # (for example, a junction left open by the source mesh). Only
            # nodes verified against the real exterior boundary may move.
            if not point_on_outline(point):
                continue
            other = surface_vertices[incident[0][0]]
            direction = norm3((point[0] - other[0], point[1] - other[1], 0.0))
            if length3(direction) > 1.0e-12:
                endpoint_shift[vertex_id] = (direction[0] * net_end_shift,
                                             direction[1] * net_end_shift)

    base_vertices = []
    base_faces = []
    base_face_meta = []
    # For each selected source seam edge and its endpoint, retain the inset
    # corner on both adjacent roof facets. These points define a true miter
    # cross-section when two ridge branches meet at a non-manifold point.
    endpoint_corner_map = {}
    base_vertex_map = {}

    def add_base_vertex(point):
        key = point_key3(point)
        index = base_vertex_map.get(key)
        if index is None:
            index = len(base_vertices)
            base_vertex_map[key] = index
            base_vertices.append(tuple(float(v) for v in point))
        return index

    for face_index, face in enumerate(faces):
        count_face = len(face)
        if count_face < 3:
            continue
        edge_keys = []
        selected = []
        for i, vertex_id in enumerate(face):
            next_id = face[(i + 1) % count_face]
            key = (vertex_id, next_id) if vertex_id < next_id else (next_id, vertex_id)
            edge_keys.append(key)
            selected.append(key in selected_edges)
        if not any(selected):
            continue

        plane = roof_face_plane(surface_vertices, face)
        pa, pb, pc = plane
        plane_normal = norm3((-pa, -pb, 1.0))
        polygon_xy = [(surface_vertices[i][0], surface_vertices[i][1]) for i in face]
        edge_data = []
        for i, vertex_id in enumerate(face):
            next_id = face[(i + 1) % count_face]
            p = surface_vertices[vertex_id]
            q = surface_vertices[next_id]
            direction3 = norm3((q[0] - p[0], q[1] - p[1], q[2] - p[2]))
            inward3 = norm3(cross3(plane_normal, direction3))
            if length3(inward3) <= 1.0e-12:
                edge_data.append(None)
                continue
            edge_data.append({
                "p": (p[0], p[1]),
                "q": (q[0], q[1]),
                "d": (q[0] - p[0], q[1] - p[1]),
                "shifted": (p[0] + inward3[0] * band_width,
                            p[1] + inward3[1] * band_width),
                "inward": inward3,
            })

        def z_on_plane(x, y):
            return pa * x + pb * y + pc

        # At each original face corner, compute the common inner point of the
        # two adjacent selected bands. If only one band touches the corner,
        # intersect its offset rail with the unselected facet boundary.
        corner_points = [None] * count_face
        for i in range(count_face):
            previous = (i - 1) % count_face
            prev_selected = selected[previous]
            curr_selected = selected[i]
            if not (prev_selected or curr_selected):
                continue
            original = surface_vertices[face[i]]
            if edge_data[previous] is None or edge_data[i] is None:
                continue

            if prev_selected and curr_selected:
                prev_edge = edge_data[previous]
                curr_edge = edge_data[i]
                xy = line_intersection(
                    prev_edge["shifted"], prev_edge["d"],
                    curr_edge["shifted"], curr_edge["d"], xy_epsilon,
                )
                if xy is None:
                    n1, n2 = prev_edge["inward"], curr_edge["inward"]
                    bisector = norm3((n1[0] + n2[0], n1[1] + n2[1], n1[2] + n2[2]))
                    xy = (original[0] + bisector[0] * band_width,
                          original[1] + bisector[1] * band_width)
                candidate = (xy[0], xy[1], z_on_plane(xy[0], xy[1]))
                displacement = length3((candidate[0] - original[0],
                                        candidate[1] - original[1],
                                        candidate[2] - original[2]))
                # Limit pathological miter spikes at near-parallel corners.
                if displacement > band_width * 8.0:
                    direction = norm3((candidate[0] - original[0],
                                       candidate[1] - original[1],
                                       candidate[2] - original[2]))
                    candidate = (original[0] + direction[0] * band_width * 8.0,
                                 original[1] + direction[1] * band_width * 8.0,
                                 original[2] + direction[2] * band_width * 8.0)
                if not point_in_polygon((candidate[0], candidate[1]), polygon_xy, tolerance):
                    n1, n2 = prev_edge["inward"], curr_edge["inward"]
                    bisector = norm3((n1[0] + n2[0], n1[1] + n2[1], n1[2] + n2[2]))
                    candidate = (original[0] + bisector[0] * band_width,
                                 original[1] + bisector[1] * band_width,
                                 original[2] + bisector[2] * band_width)
                    if not point_in_polygon((candidate[0], candidate[1]), polygon_xy, tolerance):
                        candidate = (original[0] + curr_edge["inward"][0] * band_width * 0.5,
                                     original[1] + curr_edge["inward"][1] * band_width * 0.5,
                                     original[2] + curr_edge["inward"][2] * band_width * 0.5)
                corner_points[i] = candidate
            else:
                selected_edge_index = i if curr_selected else previous
                boundary_edge_index = previous if curr_selected else i
                selected_edge = edge_data[selected_edge_index]
                boundary_edge = edge_data[boundary_edge_index]
                xy = line_intersection(
                    selected_edge["shifted"], selected_edge["d"],
                    boundary_edge["p"], boundary_edge["d"], xy_epsilon,
                )
                if xy is None:
                    inward = selected_edge["inward"]
                    xy = (original[0] + inward[0] * band_width,
                          original[1] + inward[1] * band_width)
                else:
                    # Keep the cut point on the finite neighbouring facet edge.
                    projected = project_to_segment(
                        xy, boundary_edge["p"], boundary_edge["q"]
                    )
                    if math.hypot(xy[0] - projected[0], xy[1] - projected[1]) > tolerance * 10.0:
                        xy = projected
                corner_points[i] = (xy[0], xy[1], z_on_plane(xy[0], xy[1]))

            # Eave extension/setback shifts only the cap's copy of this corner.
            shift = endpoint_shift.get(face[i])
            if shift is not None:
                point = corner_points[i]
                corner_points[i] = (point[0] + shift[0], point[1] + shift[1],
                                    z_on_plane(point[0] + shift[0], point[1] + shift[1]))

        # Create one inset quad per selected seam edge. Adjacent quads share
        # the same miter corner and radial edge on this roof facet.
        for i in range(count_face):
            if not selected[i] or corner_points[i] is None:
                continue
            j = (i + 1) % count_face
            if corner_points[j] is None:
                continue
            original_a = surface_vertices[face[i]]
            original_b = surface_vertices[face[j]]
            shift_a = endpoint_shift.get(face[i])
            shift_b = endpoint_shift.get(face[j])
            if shift_a is not None:
                original_a = (original_a[0] + shift_a[0], original_a[1] + shift_a[1],
                              z_on_plane(original_a[0] + shift_a[0], original_a[1] + shift_a[1]))
            if shift_b is not None:
                original_b = (original_b[0] + shift_b[0], original_b[1] + shift_b[1],
                              z_on_plane(original_b[0] + shift_b[0], original_b[1] + shift_b[1]))
            ids = (
                add_base_vertex(original_a),
                add_base_vertex(original_b),
                add_base_vertex(corner_points[j]),
                add_base_vertex(corner_points[i]),
            )
            # Miter collapses can turn a nominal quad into a triangle. Remove
            # duplicate indices while preserving the polygon's cyclic order.
            clean_ids = []
            for vertex_id in ids:
                if not clean_ids or clean_ids[-1] != vertex_id:
                    clean_ids.append(vertex_id)
            if len(clean_ids) > 1 and clean_ids[0] == clean_ids[-1]:
                clean_ids.pop()
            if len(set(clean_ids)) >= 3:
                unique_ids = []
                for vertex_id in clean_ids:
                    if vertex_id not in unique_ids:
                        unique_ids.append(vertex_id)
                if len(unique_ids) >= 3:
                    base_faces.append(tuple(unique_ids))
                    seam_vertex_a, seam_vertex_b = face[i], face[j]
                    seam_edge_key = (
                        (seam_vertex_a, seam_vertex_b)
                        if seam_vertex_a < seam_vertex_b
                        else (seam_vertex_b, seam_vertex_a)
                    )
                    base_face_meta.append((seam_edge_key, face_index))
                    # ids are (original_a, original_b, inset_b, inset_a).
                    endpoint_corner_map[(seam_edge_key, seam_vertex_a, face_index)] = ids[3]
                    endpoint_corner_map[(seam_edge_key, seam_vertex_b, face_index)] = ids[2]

    if not base_faces:
        return [], []

    # At some roof nodes two ridge seams meet while their four adjacent
    # facets are separated by valley seams. Per-facet inset strips then touch
    # only at the original node, producing four boundary spokes and a 4-use
    # vertical edge after extrusion. Split that point into two miter sections
    # and bridge the sections with one shared transition patch.
    for vertex_id, incident in selected_adjacency.items():
        if len(incident) != 2:
            continue
        branch_records = []
        face_sets = []
        valid = True
        for other_id, face_a, face_b in incident:
            edge_key = (vertex_id, other_id) if vertex_id < other_id else (other_id, vertex_id)
            corner_a = endpoint_corner_map.get((edge_key, vertex_id, face_a))
            corner_b = endpoint_corner_map.get((edge_key, vertex_id, face_b))
            if corner_a is None or corner_b is None:
                valid = False
                break
            branch_records.append((edge_key, face_a, face_b, corner_a, corner_b))
            face_sets.append({face_a, face_b})
        # Only handle the genuinely pinched case: each ridge branch has its
        # own pair of adjacent roof facets, with no common facet between runs.
        if not valid or face_sets[0] & face_sets[1]:
            continue
        center_key = point_key3(surface_vertices[vertex_id])
        original_center = base_vertex_map.get(center_key)
        if original_center is None:
            continue
        # A local base boundary degree check prevents perturbing ordinary
        # degree-two miter corners, which are already watertight.
        local_boundary_degree = 0
        local_edge_uses = defaultdict(int)
        for face in base_faces:
            for a_id, b_id in zip(face, face[1:] + face[:1]):
                key = (a_id, b_id) if a_id < b_id else (b_id, a_id)
                local_edge_uses[key] += 1
        for (a_id, b_id), uses in local_edge_uses.items():
            if uses == 1 and (a_id == original_center or b_id == original_center):
                local_boundary_degree += 1
        if local_boundary_degree <= 2:
            continue

        branch_sections = []
        for edge_key, face_a, face_b, corner_a, corner_b in branch_records:
            center_copy = len(base_vertices)
            base_vertices.append(tuple(float(v) for v in surface_vertices[vertex_id]))
            # Reassign only the two inset strips belonging to this seam.
            for face_index, meta in enumerate(base_face_meta):
                meta_edge, meta_face = meta
                if meta_edge == edge_key and meta_face in (face_a, face_b):
                    base_faces[face_index] = tuple(
                        center_copy if item == original_center else item
                        for item in base_faces[face_index]
                    )
            # The cross-section triangle closes the two boundary spokes on
            # the opposite facets of this one ridge segment.
            base_faces.append((center_copy, corner_a, corner_b))
            base_face_meta.append((None, -1))
            branch_sections.append((corner_a, corner_b))

        # Bridge the two cross-sections. The side edges of this miter patch
        # become the only exposed boundary around the junction; the profile
        # remains one connected shell rather than two prisms touching at a point.
        a0, a1 = branch_sections[0]
        b0, b1 = branch_sections[1]
        bridge = (a0, a1, b1, b0)
        if len(set(bridge)) == 4:
            # Triangulate the transition patch explicitly. Its four points
            # belong to different roof planes, so retaining a warped quad
            # would leave Blender free to choose an arbitrary diagonal.
            diagonal_02 = _length3(_sub3(base_vertices[a0], base_vertices[b1]))
            diagonal_13 = _length3(_sub3(base_vertices[a1], base_vertices[b0]))
            if diagonal_02 <= diagonal_13:
                base_faces.append((a0, a1, b1))
                base_faces.append((a0, b1, b0))
            else:
                base_faces.append((a0, a1, b0))
                base_faces.append((a1, b1, b0))
            base_face_meta.extend(((None, -1), (None, -1)))

    # Remove centre copies and any vertices made obsolete by the split branch
    # miter. Keeping unused vertices would make the exported object contain
    # detached points even though the polygon shell itself is closed.
    used_base_vertices = sorted({index for face in base_faces for index in face})
    compact_map = {old: new for new, old in enumerate(used_base_vertices)}
    base_vertices = [base_vertices[index] for index in used_base_vertices]
    base_faces = [tuple(compact_map[index] for index in face) for face in base_faces]

    # Welded strip topology must be a manifold surface before extrusion.
    edge_uses = defaultdict(list)
    for face_index, face in enumerate(base_faces):
        for a, b in zip(face, face[1:] + face[:1]):
            key = (a, b) if a < b else (b, a)
            edge_uses[key].append((face_index, a, b))
    if any(len(uses) > 2 for uses in edge_uses.values()):
        raise SkeletonError(
            "Inset-полосы профиля образовали неманифолдальный узел. "
            "Проверьте пересечение ветвей конька в узле крыши."
        )

    bottom_vertices = [
        (p[0] + sink[0], p[1] + sink[1], p[2] + sink[2])
        for p in base_vertices
    ]
    top_vertices = [
        (p[0] + extrusion[0], p[1] + extrusion[1], p[2] + extrusion[2])
        for p in bottom_vertices
    ]
    count = len(base_vertices)
    out_vertices = bottom_vertices + top_vertices
    out_faces = []
    out_faces.extend(tuple(reversed(face)) for face in base_faces)
    out_faces.extend(tuple(index + count for index in face) for face in base_faces)
    for uses in edge_uses.values():
        if len(uses) != 1:
            continue
        _face_index, a, b = uses[0]
        out_faces.append((a, b, b + count, a + count))

    # Refuse to output an open/non-manifold shell. This catches pathological
    # branch junctions instead of leaving overlapping end walls in Blender.
    final_edge_counts = defaultdict(int)
    for face in out_faces:
        for a, b in zip(face, face[1:] + face[:1]):
            key = (a, b) if a < b else (b, a)
            final_edge_counts[key] += 1
    if any(use_count != 2 for use_count in final_edge_counts.values()):
        raise SkeletonError(
            "В узле профиля не удалось собрать замкнутую manifold-оболочку. "
            "Проверьте соединение ветвей конька в узле крыши."
        )

    out_faces = _orient_closed_mesh_faces(out_vertices, out_faces)
    _validate_face_planarity(out_vertices, out_faces, max(scale * 2.0e-7, 1.0e-8))
    return out_vertices, out_faces
