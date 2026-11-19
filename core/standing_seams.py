"""RoofForge standing-seam panel detail generator.

Pure Python geometry; no Blender dependency. Produces only the visible folded
surfaces. The hidden underside is intentionally omitted and the lower edges are
sunk into the roof skin. At ridge-side endpoints the rib is extended slightly
under the ridge cover and its end face is omitted.
"""
from collections import defaultdict
import math

_EPS = 1.0e-10


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _length(a):
    return math.sqrt(_dot(a, a))


def _normalize(a):
    length = _length(a)
    if length <= _EPS:
        return (0.0, 0.0, 0.0)
    return _mul(a, 1.0 / length)


def _face_normal(vertices, face):
    nx = ny = nz = 0.0
    for i, idx in enumerate(face):
        p = vertices[idx]
        q = vertices[face[(i + 1) % len(face)]]
        nx += (p[1] - q[1]) * (p[2] + q[2])
        ny += (p[2] - q[2]) * (p[0] + q[0])
        nz += (p[0] - q[0]) * (p[1] + q[1])
    normal = _normalize((nx, ny, nz))
    if normal[2] < 0.0:
        normal = _mul(normal, -1.0)
    return normal


def _edge_key(a, b):
    return (a, b) if a < b else (b, a)


def _ridge_edges_by_face(vertices, faces, ridge_seams, tolerance):
    # Seam coordinates originate from the same roof vertex table. A tiny
    # distance lookup is retained for callers which copied tuples meanwhile.
    coord_lookup = {}
    for index, point in enumerate(vertices):
        coord_lookup.setdefault(tuple(point), []).append(index)

    def find_index(point):
        exact = coord_lookup.get(tuple(point))
        if exact:
            return exact[0]
        best_index = None
        best_distance = tolerance * tolerance
        for index, candidate in enumerate(vertices):
            d = _sub(candidate, point)
            distance = _dot(d, d)
            if distance <= best_distance:
                best_distance = distance
                best_index = index
        return best_index

    result = defaultdict(set)
    for seam in ridge_seams or ():
        if len(seam) < 5 or str(seam[4]).upper() != "RIDGE":
            continue
        a, b, face_a, face_b = seam[:4]
        ia, ib = find_index(a), find_index(b)
        if ia is None or ib is None or ia == ib:
            continue
        key = _edge_key(ia, ib)
        if 0 <= int(face_a) < len(faces):
            result[int(face_a)].add(key)
        if 0 <= int(face_b) < len(faces):
            result[int(face_b)].add(key)
    return result


def _scanline_intervals(projected, face, across_value, tolerance):
    """Intersect a polygon with v=across_value; return sorted inside intervals.

    projected entries are (u, v), where u runs downhill and v across the slope.
    Even/odd pairing also handles concave planar roof facets.
    """
    hits = []
    count = len(face)
    for i in range(count):
        ia = face[i]
        ib = face[(i + 1) % count]
        ua, va = projected[ia]
        ub, vb = projected[ib]
        if abs(vb - va) <= tolerance:
            continue
        # Half-open crossing rule avoids counting a vertex twice.
        if not ((va <= across_value < vb) or (vb <= across_value < va)):
            continue
        t = (across_value - va) / (vb - va)
        u = ua + (ub - ua) * t
        hits.append((u, _edge_key(ia, ib)))

    hits.sort(key=lambda item: item[0])
    deduped = []
    for hit in hits:
        if deduped and abs(hit[0] - deduped[-1][0]) <= tolerance:
            # Prefer either intersected edge; ridge classification is tested
            # against both when the endpoint is a shared corner.
            previous = deduped[-1]
            deduped[-1] = (0.5 * (previous[0] + hit[0]), previous[1], hit[1])
        else:
            deduped.append((hit[0], hit[1], None))

    intervals = []
    for index in range(0, len(deduped) - 1, 2):
        left, right = deduped[index], deduped[index + 1]
        if right[0] - left[0] > tolerance * 10.0:
            left_edges = tuple(edge for edge in left[1:] if edge is not None)
            right_edges = tuple(edge for edge in right[1:] if edge is not None)
            intervals.append((left[0], right[0], left_edges, right_edges))
    return intervals


def build_standing_seam_mesh(
    surface_vertices,
    surface_faces,
    ridge_seams,
    panel_width=0.6,
    seam_height=0.03,
    seam_base_width=0.014,
    roof_thickness=0.01,
    ridge_height=0.01,
    minimum_segment_length=0.05,
    end_offset=0.0,
    boundary_edges=None,
):
    """Generate visible standing-seam folds as one lightweight mesh.

    Args:
        surface_vertices/faces: upward-facing top roof surface in one consistent
            coordinate space. The roof thickness offset should already be applied.
        ridge_seams: records returned by ``extract_roof_seams``.
        panel_width: target panel module measured on each sloped plane.
        seam_height: requested normal height above the roof plane.
        seam_base_width: width of the buried rib foot, measured on the plane.
        roof_thickness: real roof mesh thickness; rib feet sink by half of it.
        ridge_height: vertical extrusion of the ridge cover. Fold height is
            clamped so its world-Z rise is at most 90% of this value.

    Returns (vertices, faces, stats). Bottom/underside faces are not generated.
    Ridge-side end faces are omitted and the open rib extends under the ridge
    cover by a small hidden distance.
    """
    vertices = [tuple(float(c) for c in point) for point in surface_vertices]
    faces = [tuple(int(i) for i in face) for face in surface_faces]
    if not vertices or not faces:
        return [], [], {"segments": 0, "effective_height_max": 0.0, "reason": "empty_roof"}

    panel_width = max(0.20, float(panel_width))
    requested_height = max(0.0, float(seam_height))
    base_width = max(1.0e-4, float(seam_base_width))
    roof_thickness = max(0.0, float(roof_thickness))
    ridge_height = max(0.0, float(ridge_height))
    tolerance = max(1.0e-8, max(_length(_sub(vertices[a], vertices[b]))
                               for face in faces for a, b in zip(face, face[1:] + face[:1])) * 1.0e-8)
    ridge_edges = _ridge_edges_by_face(vertices, faces, ridge_seams, tolerance * 10.0)
    boundary_segments = [
        (tuple(float(c) for c in edge[0]), tuple(float(c) for c in edge[1]))
        for edge in (boundary_edges or ()) if len(edge) == 2
    ]

    def point_on_boundary(point):
        for edge_a, edge_b in boundary_segments:
            delta = _sub(edge_b, edge_a)
            length_sq = _dot(delta, delta)
            if length_sq <= tolerance * tolerance:
                continue
            relative = _sub(point, edge_a)
            amount = max(0.0, min(1.0, _dot(relative, delta) / length_sq))
            closest = _add(edge_a, _mul(delta, amount))
            if _length(_sub(point, closest)) <= tolerance * 25.0:
                return True
        return False

    # The ridge cap gets a 10% height reserve. Ridge extrusion is a world-Z
    # displacement, while a rib is raised along the local face normal.
    sink_depth = 0.5 * roof_thickness if roof_thickness > 1.0e-9 else 0.0002
    ridge_bury = max(0.5 * roof_thickness, 0.35 * base_width, 0.001)

    out_vertices = []
    out_faces = []
    stats = {
        "segments": 0,
        "panel_lines": 0,
        "ridge_ends_buried": 0,
        "visible_end_caps": 0,
        "hidden_bottom_faces_removed": 0,
        "ridge_end_faces_removed": 0,
        "skipped_flat_faces": 0,
        "effective_height_max": 0.0,
        "requested_height": requested_height,
        "height_limit_world_z": ridge_height * 0.9,
        "sink_depth": sink_depth,
        "ridge_bury_depth": ridge_bury,
        "panel_width_actual_min": None,
        "panel_width_actual_max": None,
        # Vertex-index pairs for the two longitudinal shoulder rails of each
        # folded rib. Blender integration uses these pairs to set edge.use_seam.
        "seam_edge_pairs": [],
    }

    for face_index, face in enumerate(faces):
        if len(face) < 3:
            continue
        normal = _face_normal(vertices, face)
        if normal[2] <= 1.0e-8:
            stats["skipped_flat_faces"] += 1
            continue

        # Project global gravity onto the roof plane: the resulting vector is
        # the direction of steepest descent on this planar facet.
        gravity = (0.0, 0.0, -1.0)
        gravity_dot_normal = _dot(gravity, normal)
        downhill = _normalize(_sub(gravity, _mul(normal, gravity_dot_normal)))
        if _length(downhill) <= 1.0e-8:
            stats["skipped_flat_faces"] += 1
            continue
        across = _normalize(_cross(normal, downhill))
        if _length(across) <= 1.0e-8:
            stats["skipped_flat_faces"] += 1
            continue

        origin = vertices[face[0]]
        projected = {}
        all_u = []
        all_v = []
        for vertex_id in face:
            relative = _sub(vertices[vertex_id], origin)
            u = _dot(relative, downhill)
            v = _dot(relative, across)
            projected[vertex_id] = (u, v)
            all_u.append(u)
            all_v.append(v)

        min_v, max_v = min(all_v), max(all_v)
        span = max_v - min_v
        if span <= tolerance * 10.0:
            continue
        panel_count = max(1, min(512, int(math.ceil(span / panel_width))))
        actual_panel_width = span / panel_count
        current_min = stats["panel_width_actual_min"]
        current_max = stats["panel_width_actual_max"]
        stats["panel_width_actual_min"] = actual_panel_width if current_min is None else min(current_min, actual_panel_width)
        stats["panel_width_actual_max"] = actual_panel_width if current_max is None else max(current_max, actual_panel_width)
        face_ridge_edges = ridge_edges.get(face_index, set())

        def endpoint_touches_ridge(u_value, v_value):
            if not face_ridge_edges:
                return False
            for edge_a, edge_b in face_ridge_edges:
                ua, va = projected[edge_a]
                ub, vb = projected[edge_b]
                du, dv = ub - ua, vb - va
                length_sq = du * du + dv * dv
                if length_sq <= tolerance * tolerance:
                    continue
                t = max(0.0, min(1.0, ((u_value - ua) * du + (v_value - va) * dv) / length_sq))
                q_u, q_v = ua + du * t, va + dv * t
                if math.hypot(u_value - q_u, v_value - q_v) <= tolerance * 25.0:
                    return True
            return False

        for panel_index in range(1, panel_count):
            across_value = min_v + actual_panel_width * panel_index
            intervals = _scanline_intervals(projected, face, across_value, tolerance)
            for u0, u1, edge0_candidates, edge1_candidates in intervals:
                if u1 - u0 < max(float(minimum_segment_length), tolerance * 100.0):
                    continue

                # Interpolate the centerline endpoints in the roof plane.
                p0 = _add(origin, _add(_mul(downhill, u0), _mul(across, across_value)))
                p1 = _add(origin, _add(_mul(downhill, u1), _mul(across, across_value)))
                start_is_ridge = (
                    any(edge in face_ridge_edges for edge in edge0_candidates)
                    or endpoint_touches_ridge(u0, across_value)
                )
                end_is_ridge = (
                    any(edge in face_ridge_edges for edge in edge1_candidates)
                    or endpoint_touches_ridge(u1, across_value)
                )
                line_direction = _normalize(_sub(p1, p0))
                if _length(line_direction) <= 1.0e-8:
                    continue
                profile_across = _normalize(_cross(normal, line_direction))
                if _length(profile_across) <= 1.0e-8:
                    continue

                # Fold height is normal to the local roof facet. Clamp its
                # vertical component to 90% of the ridge-cover extrusion.
                max_normal_height = (ridge_height * 0.9) / max(normal[2], 1.0e-8)
                effective_height = min(requested_height, max_normal_height)
                if effective_height <= 1.0e-7:
                    continue
                stats["effective_height_max"] = max(stats["effective_height_max"], effective_height)

                if start_is_ridge:
                    p0 = _sub(p0, _mul(line_direction, ridge_bury))
                    stats["ridge_ends_buried"] += 1
                    stats["ridge_end_faces_removed"] += 1
                if end_is_ridge:
                    p1 = _add(p1, _mul(line_direction, ridge_bury))
                    stats["ridge_ends_buried"] += 1
                    stats["ridge_end_faces_removed"] += 1

                # A signed offset is applied only where a panel reaches the
                # actual outer boundary of the roof. Internal ridge/valley
                # joints remain governed by their own seam geometry. Positive
                # values extend past the boundary; negative values retract.
                signed_end_offset = float(end_offset)
                if abs(signed_end_offset) > tolerance:
                    # Retraction at both ends must not invert or collapse a rib.
                    max_safe_offset = 0.45 * _length(_sub(p1, p0))
                    signed_end_offset = max(
                        -max_safe_offset, min(max_safe_offset, signed_end_offset)
                    )
                    if not start_is_ridge and point_on_boundary(p0):
                        p0 = _sub(p0, _mul(line_direction, signed_end_offset))
                    if not end_is_ridge and point_on_boundary(p1):
                        p1 = _add(p1, _mul(line_direction, signed_end_offset))

                # Cross-section: buried foot -> folded side -> narrow crown ->
                # folded side -> buried foot. The bottom edge is intentionally
                # open (no hidden base polygon).
                top_width = min(base_width * 0.34, max(0.0015, base_width * 0.25))
                half_base = 0.5 * base_width
                half_top = 0.5 * top_width
                start_index = len(out_vertices)
                for center in (p0, p1):
                    base_left = _sub(_sub(center, _mul(profile_across, half_base)), (0.0, 0.0, sink_depth))
                    top_left = _add(_sub(center, _mul(profile_across, half_top)), _mul(normal, effective_height))
                    top_right = _add(_add(center, _mul(profile_across, half_top)), _mul(normal, effective_height))
                    base_right = _sub(_add(center, _mul(profile_across, half_base)), (0.0, 0.0, sink_depth))
                    out_vertices.extend((base_left, top_left, top_right, base_right))

                # Only three longitudinal visible faces are generated. There
                # is no bottom/underside quad beneath the roof surface.
                b0, t0l, t0r, b0r = start_index, start_index + 1, start_index + 2, start_index + 3
                b1, t1l, t1r, b1r = start_index + 4, start_index + 5, start_index + 6, start_index + 7
                # Mark the two longitudinal shoulder rails where the crown
                # meets the side faces that define the fold height.
                stats["seam_edge_pairs"].extend((
                    (t0l, t1l), (t0r, t1r),
                ))
                out_faces.append((b0, b1, t1l, t0l))
                out_faces.append((t0l, t1l, t1r, t0r))
                out_faces.append((t0r, t1r, b1r, b0r))

                # Eave/valley-facing end caps may be visible. Ridge-facing caps
                # are omitted because that end is buried under the ridge cover.
                if not start_is_ridge:
                    out_faces.append((b0, t0l, t0r, b0r))
                    stats["visible_end_caps"] += 1
                if not end_is_ridge:
                    out_faces.append((b1, b1r, t1r, t1l))
                    stats["visible_end_caps"] += 1

                stats["segments"] += 1
                stats["panel_lines"] += 1
                stats["hidden_bottom_faces_removed"] += 1

    return out_vertices, out_faces, stats
