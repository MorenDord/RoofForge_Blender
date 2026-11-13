//! Native, Blender-independent geometry primitives for RoofForge.
//!
//! The Rust crate owns plain numeric data only. It must not depend on bpy,
//! Blender data blocks, UI state, or Blender-specific coordinate types.

#[derive(Debug, Clone, PartialEq, Eq)]
struct Diagnostic {
    code: &'static str,
    message: String,
    severity: &'static str,
}

impl Diagnostic {
    fn error(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
            severity: "ERROR",
        }
    }
}

fn signed_area(points: &[[f64; 2]]) -> f64 {
    if points.len() < 3 {
        return 0.0;
    }

    let twice_area = points
        .iter()
        .enumerate()
        .map(|(index, point)| {
            let next = points[(index + 1) % points.len()];
            point[0] * next[1] - next[0] * point[1]
        })
        .sum::<f64>();

    0.5 * twice_area
}

fn bbox_scale(points: &[[f64; 2]]) -> f64 {
    if points.is_empty() {
        return 1.0;
    }

    let mut min_x = points[0][0];
    let mut max_x = points[0][0];
    let mut min_y = points[0][1];
    let mut max_y = points[0][1];

    for point in points.iter().skip(1) {
        min_x = min_x.min(point[0]);
        max_x = max_x.max(point[0]);
        min_y = min_y.min(point[1]);
        max_y = max_y.max(point[1]);
    }

    1.0_f64.max((max_x - min_x).hypot(max_y - min_y))
}

fn cross(a: [f64; 2], b: [f64; 2], c: [f64; 2]) -> f64 {
    (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
}

fn on_segment(
    point: [f64; 2],
    start: [f64; 2],
    end: [f64; 2],
    cross_eps: f64,
    linear_eps: f64,
) -> bool {
    cross(start, end, point).abs() <= cross_eps
        && point[0] >= start[0].min(end[0]) - linear_eps
        && point[0] <= start[0].max(end[0]) + linear_eps
        && point[1] >= start[1].min(end[1]) - linear_eps
        && point[1] <= start[1].max(end[1]) + linear_eps
}

fn segments_intersect(
    a: [f64; 2],
    b: [f64; 2],
    c: [f64; 2],
    d: [f64; 2],
    cross_eps: f64,
    linear_eps: f64,
) -> bool {
    let o1 = cross(a, b, c);
    let o2 = cross(a, b, d);
    let o3 = cross(c, d, a);
    let o4 = cross(c, d, b);

    let proper_intersection = ((o1 > cross_eps && o2 < -cross_eps)
        || (o1 < -cross_eps && o2 > cross_eps))
        && ((o3 > cross_eps && o4 < -cross_eps) || (o3 < -cross_eps && o4 > cross_eps));

    proper_intersection
        || on_segment(c, a, b, cross_eps, linear_eps)
        || on_segment(d, a, b, cross_eps, linear_eps)
        || on_segment(a, c, d, cross_eps, linear_eps)
        || on_segment(b, c, d, cross_eps, linear_eps)
}

/// Mirrors core.geometry._validate_simple_polygon_python.
///
/// Diagnostic codes, ordering, messages, and tolerance scaling are part of
/// the Python/Rust compatibility contract.
fn validate_simple_polygon(points: &[[f64; 2]], eps: f64) -> Vec<Diagnostic> {
    let mut issues = Vec::new();

    if points.len() < 3 {
        return vec![Diagnostic::error(
            "POLY_TOO_SMALL",
            "Контур должен содержать минимум 3 вершины.",
        )];
    }

    if points
        .iter()
        .any(|point| !point[0].is_finite() || !point[1].is_finite())
    {
        return vec![Diagnostic::error(
            "NON_FINITE",
            "Контур содержит NaN или бесконечные координаты.",
        )];
    }

    let scale = bbox_scale(points);
    let linear_eps = eps * scale;
    let area_eps = eps * scale * scale;

    for (index, point) in points.iter().enumerate() {
        let next = points[(index + 1) % points.len()];
        if (next[0] - point[0]).hypot(next[1] - point[1]) <= linear_eps {
            issues.push(Diagnostic::error(
                "ZERO_EDGE",
                format!("Ребро {index} имеет нулевую или слишком малую длину."),
            ));
        }
    }

    if signed_area(points).abs() <= area_eps {
        issues.push(Diagnostic::error(
            "ZERO_AREA",
            "Площадь контура практически равна нулю.",
        ));
    }

    let count = points.len();
    for i in 0..count {
        let a = points[i];
        let b = points[(i + 1) % count];

        for j in (i + 1)..count {
            // Adjacent edges share a legal endpoint.
            if j == (i + 1) % count || (j + 1) % count == i {
                continue;
            }

            let c = points[j];
            let d = points[(j + 1) % count];
            if segments_intersect(a, b, c, d, area_eps, linear_eps) {
                issues.push(Diagnostic::error(
                    "SELF_INTERSECTION",
                    format!("Рёбра {i} и {j} пересекаются."),
                ));
            }
        }
    }

    issues
}

#[derive(Debug, Clone, Copy)]
struct IntervalLineData {
    edge_id: usize,
    source_edge_id: usize,
    normal: [f64; 2],
    offset: f64,
    speed: f64,
    tangent: [f64; 2],
    base_height: f64,
}

#[derive(Debug, Clone, Copy)]
struct IntervalVertex {
    point: [f64; 2],
}

fn interval_line_intersection(
    first: &IntervalLineData,
    second: &IntervalLineData,
    time: f64,
    eps: f64,
) -> Result<IntervalVertex, Diagnostic> {
    let [a, b] = first.normal;
    let [c, d] = second.normal;
    let determinant = a * d - b * c;
    if determinant.abs() <= eps {
        return Err(Diagnostic::error(
            "PARALLEL_WAVEFRONT_EDGES",
            format!(
                "Соседние фронты рёбер {} и {} параллельны или почти параллельны.",
                first.edge_id, second.edge_id
            ),
        ));
    }

    let rhs_first = first.offset + first.speed * (time - first.base_height);
    let rhs_second = second.offset + second.speed * (time - second.base_height);
    let point = [
        (rhs_first * d - b * rhs_second) / determinant,
        (a * rhs_second - rhs_first * c) / determinant,
    ];
    if point.iter().any(|value| !value.is_finite())
    {
        return Err(Diagnostic::error(
            "NON_FINITE_WAVEFRONT_VERTEX",
            "Пересечение подвижных рёбер породило нечисловую вершину.",
        ));
    }
    Ok(IntervalVertex { point })
}

fn interval_dedupe_polygon(points: &[[f64; 3]], tolerance: f64) -> Vec<[f64; 3]> {
    let mut result: Vec<[f64; 3]> = Vec::with_capacity(points.len());
    for point in points {
        let keep = if let Some(previous) = result.last() {
            let distance = (point[0] - previous[0])
                .hypot(point[1] - previous[1])
                .hypot(point[2] - previous[2]);
            distance > tolerance
        } else {
            true
        };
        if keep {
            result.push(*point);
        }
    }

    if result.len() > 1 {
        let first = result[0];
        let last = result[result.len() - 1];
        let distance = (first[0] - last[0])
            .hypot(first[1] - last[1])
            .hypot(first[2] - last[2]);
        if distance <= tolerance {
            result.pop();
        }
    }
    result
}

fn record_wavefront_interval_core(
    loop_counts: &[usize],
    lines: &[IntervalLineData],
    start_time: f64,
    end_time: f64,
    time_tolerance: f64,
    epsilon: f64,
) -> Result<(Vec<SkeletonArcTuple>, Vec<FacetFragmentTuple>), Diagnostic> {
    if !start_time.is_finite()
        || !end_time.is_finite()
        || !time_tolerance.is_finite()
        || !epsilon.is_finite()
        || time_tolerance < 0.0
        || epsilon < 0.0
    {
        return Err(Diagnostic::error(
            "INVALID_INTERVAL_INPUT",
            "Времена интервала и геометрические допуски должны быть конечными и неотрицательными.",
        ));
    }

    let dt = end_time - start_time;
    if dt < -time_tolerance {
        return Err(Diagnostic::error(
            "TIME_ORDER",
            "Нельзя записать интервал волнового фронта с отрицательной длительностью.",
        ));
    }
    if dt <= time_tolerance {
        return Ok((Vec::new(), Vec::new()));
    }

    let expected_count = loop_counts
        .iter()
        .try_fold(0_usize, |sum, count| sum.checked_add(*count));
    if expected_count != Some(lines.len()) || loop_counts.iter().any(|count| *count < 3) {
        return Err(Diagnostic::error(
            "INVALID_WAVEFRONT_INTERVAL_LOOPS",
            "Список активных wavefront-loop не соответствует переданным рёбрам.",
        ));
    }
    for line in lines {
        if line
            .normal
            .iter()
            .chain(line.tangent.iter())
            .any(|value| !value.is_finite())
            || !line.offset.is_finite()
            || !line.speed.is_finite()
            || !line.base_height.is_finite()
            || line.speed.abs() <= f64::EPSILON
        {
            return Err(Diagnostic::error(
                "INVALID_WAVEFRONT_INTERVAL_LINE",
                format!(
                    "Параметры активного ребра {} не являются конечными или имеют нулевую скорость.",
                    line.edge_id
                ),
            ));
        }
    }

    let mut skeleton_arcs = Vec::new();
    let mut facets = Vec::new();
    let mut line_offset = 0_usize;

    for &loop_count in loop_counts {
        let loop_lines = &lines[line_offset..line_offset + loop_count];
        line_offset += loop_count;

        let mut vertices_start = Vec::with_capacity(loop_count);
        let mut vertices_end = Vec::with_capacity(loop_count);
        for index in 0..loop_count {
            let previous = &loop_lines[(index + loop_count - 1) % loop_count];
            let current = &loop_lines[index];
            vertices_start.push(interval_line_intersection(
                previous, current, start_time, epsilon,
            )?);
            vertices_end.push(interval_line_intersection(
                previous, current, end_time, epsilon,
            )?);
        }

        for (first, second) in vertices_start.iter().zip(vertices_end.iter()) {
            let distance =
                (second.point[0] - first.point[0]).hypot(second.point[1] - first.point[1]);
            if distance > epsilon {
                skeleton_arcs.push((
                    (first.point[0], first.point[1], start_time),
                    (second.point[0], second.point[1], end_time),
                    end_time,
                ));
            }
        }

        for index in 0..loop_count {
            let edge = &loop_lines[index];
            let start_vertex = vertices_start[index];
            let end_vertex = vertices_start[(index + 1) % loop_count];
            let start = start_vertex.point;
            let end = end_vertex.point;

            let start1 = vertices_end[index].point;
            let end1 = vertices_end[(index + 1) % loop_count].point;
            let end_dx = end1[0] - start1[0];
            let end_dy = end1[1] - start1[1];
            let end_length = end_dx * edge.tangent[0] + end_dy * edge.tangent[1];
            if end_length < -time_tolerance {
                return Err(Diagnostic::error(
                    "NEGATIVE_EDGE_AT_EVENT",
                    format!(
                        "Ребро wavefront {} получило отрицательную длину перед событием.",
                        edge.edge_id
                    ),
                ));
            }

            let raw_fragment = [
                [start[0], start[1], start_time],
                [end[0], end[1], start_time],
                [end1[0], end1[1], end_time],
                [start1[0], start1[1], end_time],
            ];
            let fragment = interval_dedupe_polygon(&raw_fragment, time_tolerance);
            if fragment.len() < 3 {
                continue;
            }

            let projected: Vec<[f64; 2]> =
                fragment.iter().map(|point| [point[0], point[1]]).collect();
            if signed_area(&projected).abs() <= time_tolerance * time_tolerance {
                continue;
            }

            for point in &fragment {
                let expected_z = edge.base_height
                    + ((edge.normal[0] * point[0] + edge.normal[1] * point[1]) - edge.offset)
                        / edge.speed;
                let z_tolerance =
                    (time_tolerance * 10.0).max(epsilon * 1.0_f64.max(point[2].abs()) * 1000.0);
                if (expected_z - point[2]).abs() > z_tolerance {
                    return Err(Diagnostic::error(
                        "FACET_NOT_PLANAR",
                        format!(
                            "Фрагмент исходного ската {} не лежит на его точной плоскости.",
                            edge.source_edge_id + 1
                        ),
                    ));
                }
            }

            facets.push((
                edge.source_edge_id,
                start_time,
                end_time,
                fragment
                    .into_iter()
                    .map(|point| (point[0], point[1], point[2]))
                    .collect(),
            ));
        }
    }

    Ok((skeleton_arcs, facets))
}

type IntervalLineTuple = (usize, usize, f64, f64, f64, f64, f64, f64, f64);
type Point3Tuple = (f64, f64, f64);
type SkeletonArcTuple = (Point3Tuple, Point3Tuple, f64);
type FacetFragmentTuple = (usize, f64, f64, Vec<Point3Tuple>);
type WavefrontIntervalTuple = (Vec<SkeletonArcTuple>, Vec<FacetFragmentTuple>);

fn weld_vertices_batch_core(
    points: &[[f64; 3]],
    tolerance: f64,
) -> Result<(Vec<[f64; 3]>, Vec<usize>), Diagnostic> {
    if !tolerance.is_finite() || tolerance <= 0.0 {
        return Err(Diagnostic::error(
            "INVALID_WELD_TOLERANCE",
            "Допуск объединения вершин должен быть конечным и положительным.",
        ));
    }

    let tolerance_sq = tolerance * tolerance;
    let mut vertices: Vec<[f64; 3]> = Vec::with_capacity(points.len());
    let mut point_indices = Vec::with_capacity(points.len());
    let mut buckets: std::collections::HashMap<[i64; 3], Vec<usize>> =
        std::collections::HashMap::new();

    for point in points {
        if point.iter().any(|value| !value.is_finite()) {
            return Err(Diagnostic::error(
                "NON_FINITE_WELD_POINT",
                "Список объединяемых вершин содержит NaN или бесконечные координаты.",
            ));
        }

        let mut key = [0_i64; 3];
        for axis in 0..3 {
            let cell = (point[axis] / tolerance).floor();
            if cell < i64::MIN as f64 || cell >= 9_223_372_036_854_775_808.0 {
                return Err(Diagnostic::error(
                    "WELD_COORDINATE_OUT_OF_RANGE",
                    "Координата слишком велика для пространственного индекса Rust.",
                ));
            }
            key[axis] = cell as i64;
        }

        let mut matched = None;
        for dx in -1_i64..=1 {
            for dy in -1_i64..=1 {
                for dz in -1_i64..=1 {
                    let Some(x) = key[0].checked_add(dx) else {
                        continue;
                    };
                    let Some(y) = key[1].checked_add(dy) else {
                        continue;
                    };
                    let Some(z) = key[2].checked_add(dz) else {
                        continue;
                    };
                    if let Some(nearby) = buckets.get(&[x, y, z]) {
                        for &index in nearby {
                            let existing = vertices[index];
                            let dx = existing[0] - point[0];
                            let dy = existing[1] - point[1];
                            let dz = existing[2] - point[2];
                            let distance_sq = dx * dx + dy * dy + dz * dz;
                            if distance_sq <= tolerance_sq {
                                matched = Some(index);
                                break;
                            }
                        }
                    }
                    if matched.is_some() {
                        break;
                    }
                }
                if matched.is_some() {
                    break;
                }
            }
            if matched.is_some() {
                break;
            }
        }

        let index = if let Some(index) = matched {
            index
        } else {
            let index = vertices.len();
            vertices.push(*point);
            buckets.entry(key).or_default().push(index);
            index
        };
        point_indices.push(index);
    }

    Ok((vertices, point_indices))
}

fn split_face_edges_at_shared_vertices_core(
    vertices: &[[f64; 3]],
    faces: &[Vec<usize>],
    tolerance: f64,
) -> Result<Vec<Vec<usize>>, Diagnostic> {
    if !tolerance.is_finite() || tolerance <= 0.0 {
        return Err(Diagnostic::error(
            "INVALID_TOLERANCE",
            "Допуск согласования рёбер должен быть конечным и положительным.",
        ));
    }
    if vertices.iter().flatten().any(|value| !value.is_finite()) {
        return Err(Diagnostic::error(
            "NON_FINITE_SURFACE_VERTEX",
            "Сетка содержит NaN или бесконечную координату.",
        ));
    }

    let tolerance_sq = tolerance * tolerance;
    let mut axis_orders: [Vec<usize>; 3] = std::array::from_fn(|_| Vec::new());
    let mut axis_values: [Vec<f64>; 3] = std::array::from_fn(|_| Vec::new());

    for axis in 0..3 {
        let mut order: Vec<usize> = (0..vertices.len()).collect();
        order.sort_by(|first, second| {
            vertices[*first][axis]
                .partial_cmp(&vertices[*second][axis])
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| first.cmp(second))
        });
        let values = order
            .iter()
            .map(|vertex_id| vertices[*vertex_id][axis])
            .collect();
        axis_orders[axis] = order;
        axis_values[axis] = values;
    }

    let mut output = Vec::with_capacity(faces.len());
    for face in faces {
        if face.is_empty() {
            return Err(Diagnostic::error(
                "DEGENERATE_CONFORMED_FACE",
                "Разбиение T-junction создало вырожденную грань.",
            ));
        }
        if face.iter().any(|vertex_id| *vertex_id >= vertices.len()) {
            return Err(Diagnostic::error(
                "INVALID_FACE_VERTEX",
                "Грань ссылается на отсутствующую вершину сетки.",
            ));
        }

        let mut expanded = Vec::new();
        for edge_index in 0..face.len() {
            let start_id = face[edge_index];
            let end_id = face[(edge_index + 1) % face.len()];
            let start = vertices[start_id];
            let end = vertices[end_id];
            let direction = [end[0] - start[0], end[1] - start[1], end[2] - start[2]];
            let length_sq = direction.iter().map(|value| value * value).sum::<f64>();
            if !length_sq.is_finite() || length_sq <= tolerance_sq {
                return Err(Diagnostic::error(
                    "ZERO_LENGTH_FACE_EDGE",
                    "После объединения фасет найдено ребро нулевой длины.",
                ));
            }

            let mut search_axis = 0_usize;
            for axis in 1..3 {
                if direction[axis].abs() < direction[search_axis].abs() {
                    search_axis = axis;
                }
            }
            let lower_value = start[search_axis].min(end[search_axis]) - tolerance;
            let upper_value = start[search_axis].max(end[search_axis]) + tolerance;
            let values = &axis_values[search_axis];
            let order = &axis_orders[search_axis];
            let candidate_start = values.partition_point(|value| *value < lower_value);
            let candidate_end = values.partition_point(|value| *value <= upper_value);

            let mut points_on_edge: Vec<(f64, usize)> = Vec::new();
            let edge_length = length_sq.sqrt();
            let endpoint_margin = tolerance / edge_length;
            for &candidate_id in order.iter().take(candidate_end).skip(candidate_start) {
                if candidate_id == start_id || candidate_id == end_id {
                    continue;
                }
                let candidate = vertices[candidate_id];
                let mut outside = false;
                for axis in 0..3 {
                    if axis == search_axis {
                        continue;
                    }
                    if candidate[axis] < start[axis].min(end[axis]) - tolerance
                        || candidate[axis] > start[axis].max(end[axis]) + tolerance
                    {
                        outside = true;
                        break;
                    }
                }
                if outside {
                    continue;
                }

                let relative = [
                    candidate[0] - start[0],
                    candidate[1] - start[1],
                    candidate[2] - start[2],
                ];
                let parameter = (relative[0] * direction[0]
                    + relative[1] * direction[1]
                    + relative[2] * direction[2])
                    / length_sq;
                if parameter <= endpoint_margin || parameter >= 1.0 - endpoint_margin {
                    continue;
                }

                let projected = [
                    start[0] + parameter * direction[0],
                    start[1] + parameter * direction[1],
                    start[2] + parameter * direction[2],
                ];
                let dx = candidate[0] - projected[0];
                let dy = candidate[1] - projected[1];
                let dz = candidate[2] - projected[2];
                let distance_sq = dx * dx + dy * dy + dz * dz;
                if distance_sq <= tolerance_sq {
                    points_on_edge.push((parameter, candidate_id));
                }
            }

            points_on_edge.sort_by(|first, second| {
                first
                    .0
                    .partial_cmp(&second.0)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| first.1.cmp(&second.1))
            });
            if expanded.is_empty() {
                expanded.push(start_id);
            }
            expanded.extend(points_on_edge.into_iter().map(|(_, vertex_id)| vertex_id));
            if expanded.last().copied() != Some(end_id) {
                expanded.push(end_id);
            }
        }

        let mut compact = Vec::with_capacity(expanded.len());
        for vertex_id in expanded {
            if compact.last().copied() != Some(vertex_id) {
                compact.push(vertex_id);
            }
        }
        if compact.len() > 1 && compact.first() == compact.last() {
            compact.pop();
        }
        let unique_count = compact
            .iter()
            .copied()
            .collect::<std::collections::HashSet<_>>()
            .len();
        if unique_count < 3 {
            return Err(Diagnostic::error(
                "DEGENERATE_CONFORMED_FACE",
                "Разбиение T-junction создало вырожденную грань.",
            ));
        }
        output.push(compact);
    }

    Ok(output)
}

#[derive(Debug, Clone, Copy)]
struct WavefrontLineData {
    edge_id: usize,
    normal: [f64; 2],
    offset: f64,
    speed: f64,
    tangent: [f64; 2],
    generation: u64,
    base_height: f64,
}

impl WavefrontLineData {
    fn offset_at(&self, time: f64) -> f64 {
        self.offset + self.speed * (time - self.base_height)
    }
}

#[derive(Debug, Clone, Copy)]
struct WavefrontKinematicVertex {
    point: [f64; 2],
    velocity: [f64; 2],
}

#[derive(Debug, Clone)]
struct RawWavefrontEvent {
    kind: u8,
    time: f64,
    loop_id: usize,
    edge_id: usize,
    vertex_id: usize,
    target_edge_id: Option<usize>,
    position: [f64; 2],
    participants: Vec<(usize, u64)>,
}

fn dot2(a: [f64; 2], b: [f64; 2]) -> f64 {
    a[0] * b[0] + a[1] * b[1]
}

fn sub2(a: [f64; 2], b: [f64; 2]) -> [f64; 2] {
    [a[0] - b[0], a[1] - b[1]]
}

fn add_scaled2(point: [f64; 2], vector: [f64; 2], scale: f64) -> [f64; 2] {
    [point[0] + vector[0] * scale, point[1] + vector[1] * scale]
}

fn cross2(a: [f64; 2], b: [f64; 2]) -> f64 {
    a[0] * b[1] - a[1] * b[0]
}

fn wavefront_line_intersection(
    first: &WavefrontLineData,
    second: &WavefrontLineData,
    time: f64,
    eps: f64,
) -> Result<WavefrontKinematicVertex, Diagnostic> {
    let [a, b] = first.normal;
    let [c, d] = second.normal;
    let determinant = a * d - b * c;
    if determinant.abs() <= eps {
        return Err(Diagnostic::error(
            "PARALLEL_WAVEFRONT_EDGES",
            format!(
                "Соседние фронты рёбер {} и {} параллельны или почти параллельны.",
                first.edge_id, second.edge_id
            ),
        ));
    }

    let rhs_first = first.offset_at(time);
    let rhs_second = second.offset_at(time);
    let point = [
        (rhs_first * d - b * rhs_second) / determinant,
        (a * rhs_second - rhs_first * c) / determinant,
    ];
    let velocity = [
        (first.speed * d - b * second.speed) / determinant,
        (a * second.speed - first.speed * c) / determinant,
    ];
    if !point[0].is_finite()
        || !point[1].is_finite()
        || !velocity[0].is_finite()
        || !velocity[1].is_finite()
    {
        return Err(Diagnostic::error(
            "NON_FINITE_WAVEFRONT_VERTEX",
            "Пересечение подвижных рёбер породило нечисловую вершину.",
        ));
    }
    Ok(WavefrontKinematicVertex { point, velocity })
}

fn collect_wavefront_events_core(
    lines: &[WavefrontLineData],
    loop_id: usize,
    time: f64,
    eps: f64,
) -> Result<Vec<RawWavefrontEvent>, Diagnostic> {
    let count = lines.len();
    if count < 3 {
        return Err(Diagnostic::error(
            "WAVEFRONT_TOO_SMALL",
            "Для замкнутого wavefront-loop нужны минимум три активных ребра.",
        ));
    }
    if !time.is_finite() || !eps.is_finite() || eps < 0.0 {
        return Err(Diagnostic::error(
            "INVALID_WAVEFRONT_INPUT",
            "Время и допуск волнового фронта должны быть конечными, допуск неотрицательным.",
        ));
    }
    for line in lines {
        if !line.normal[0].is_finite()
            || !line.normal[1].is_finite()
            || !line.offset.is_finite()
            || !line.speed.is_finite()
            || !line.tangent[0].is_finite()
            || !line.tangent[1].is_finite()
            || !line.base_height.is_finite()
        {
            return Err(Diagnostic::error(
                "INVALID_WAVEFRONT_INPUT",
                "Параметры активного ребра волнового фронта содержат NaN или бесконечность.",
            ));
        }
    }

    let mut vertices = Vec::with_capacity(count);
    for index in 0..count {
        let previous = &lines[(index + count - 1) % count];
        let current = &lines[index];
        vertices.push(wavefront_line_intersection(previous, current, time, eps)?);
    }

    let polygon: Vec<[f64; 2]> = vertices.iter().map(|vertex| vertex.point).collect();
    let winding = if signed_area(&polygon) > 0.0 {
        1.0
    } else {
        -1.0
    };
    let (mut min_x, mut max_x) = (polygon[0][0], polygon[0][0]);
    let (mut min_y, mut max_y) = (polygon[0][1], polygon[0][1]);
    for point in polygon.iter().skip(1) {
        min_x = min_x.min(point[0]);
        max_x = max_x.max(point[0]);
        min_y = min_y.min(point[1]);
        max_y = max_y.max(point[1]);
    }
    let scale = 1.0_f64.max(max_x - min_x).max(max_y - min_y);
    let length_eps = eps * scale * 100.0;
    let time_eps = eps * scale.max(1.0) * 100.0;

    let mut events = Vec::new();

    // Batch edge-collapse candidates for the complete active loop.
    for index in 0..count {
        let edge = &lines[index];
        let previous = &lines[(index + count - 1) % count];
        let next = &lines[(index + 1) % count];
        let start_vertex = vertices[index];
        let end_vertex = vertices[(index + 1) % count];
        let start = start_vertex.point;
        let end = end_vertex.point;
        let length = dot2(sub2(end, start), edge.tangent);
        let length_rate = dot2(
            sub2(end_vertex.velocity, start_vertex.velocity),
            edge.tangent,
        );

        if length < -length_eps {
            return Err(Diagnostic::error(
                "NEGATIVE_WAVEFRONT_EDGE",
                format!(
                    "Активное ребро {} имеет отрицательную ориентированную длину.",
                    edge.edge_id
                ),
            ));
        }

        let dt = if length <= length_eps {
            0.0
        } else if length_rate < -time_eps {
            length / -length_rate
        } else {
            continue;
        };
        if dt < -time_eps {
            continue;
        }
        let future_dt = dt.max(0.0);
        let event_position = [
            (start[0] + end[0]) * 0.5
                + (start_vertex.velocity[0] + end_vertex.velocity[0]) * 0.5 * future_dt,
            (start[1] + end[1]) * 0.5
                + (start_vertex.velocity[1] + end_vertex.velocity[1]) * 0.5 * future_dt,
        ];
        events.push(RawWavefrontEvent {
            kind: 0,
            time: time + future_dt,
            loop_id,
            edge_id: edge.edge_id,
            vertex_id: index,
            target_edge_id: None,
            position: event_position,
            participants: vec![
                (previous.edge_id, previous.generation),
                (edge.edge_id, edge.generation),
                (next.edge_id, next.generation),
            ],
        });
    }

    // Find reflex-vertex hits against finite target segments.
    for vertex_index in 0..count {
        let vertex = vertices[vertex_index];
        let previous_point = vertices[(vertex_index + count - 1) % count].point;
        let next_point = vertices[(vertex_index + 1) % count].point;
        let incoming = sub2(vertex.point, previous_point);
        let outgoing = sub2(next_point, vertex.point);
        let turn = cross2(incoming, outgoing);
        if turn * winding >= -eps {
            continue;
        }

        let adjacent_previous = &lines[(vertex_index + count - 1) % count];
        let adjacent_current = &lines[vertex_index];

        for target_index in 0..count {
            let target = &lines[target_index];
            if target.edge_id == adjacent_previous.edge_id
                || target.edge_id == adjacent_current.edge_id
            {
                continue;
            }

            let signed_distance = dot2(target.normal, vertex.point) - target.offset_at(time);
            let closing_rate = dot2(target.normal, vertex.velocity) - target.speed;
            if closing_rate >= -eps {
                continue;
            }
            let dt = -signed_distance / closing_rate;
            if dt <= eps {
                continue;
            }

            let hit_time = time + dt;
            let hit = add_scaled2(vertex.point, vertex.velocity, dt);
            let target_start = wavefront_line_intersection(
                &lines[(target_index + count - 1) % count],
                target,
                hit_time,
                eps,
            )?;
            let target_end = wavefront_line_intersection(
                target,
                &lines[(target_index + 1) % count],
                hit_time,
                eps,
            )?;
            let start = target_start.point;
            let end = target_end.point;
            let target_length = dot2(sub2(end, start), target.tangent);
            let coordinate = dot2(sub2(hit, start), target.tangent);
            let margin = eps * 1.0_f64.max(target_length.abs());
            if target_length < -margin
                || coordinate < -margin
                || coordinate > target_length + margin
            {
                continue;
            }

            let kind = if margin < coordinate && coordinate < target_length - margin {
                1
            } else {
                2
            };
            let target_previous = &lines[(target_index + count - 1) % count];
            let target_next = &lines[(target_index + 1) % count];
            events.push(RawWavefrontEvent {
                kind,
                time: hit_time,
                loop_id,
                edge_id: adjacent_current.edge_id,
                vertex_id: vertex_index,
                target_edge_id: Some(target.edge_id),
                position: hit,
                participants: vec![
                    (adjacent_previous.edge_id, adjacent_previous.generation),
                    (adjacent_current.edge_id, adjacent_current.generation),
                    (target.edge_id, target.generation),
                    (target_previous.edge_id, target_previous.generation),
                    (target_next.edge_id, target_next.generation),
                ],
            });
        }
    }

    let priority = |kind: u8| match kind {
        0 => 0_u8,
        1 => 1_u8,
        _ => 2_u8,
    };
    events.sort_by(|first, second| {
        first
            .time
            .total_cmp(&second.time)
            .then_with(|| priority(first.kind).cmp(&priority(second.kind)))
            .then_with(|| first.loop_id.cmp(&second.loop_id))
            .then_with(|| first.vertex_id.cmp(&second.vertex_id))
            .then_with(|| first.edge_id.cmp(&second.edge_id))
            .then_with(|| {
                first
                    .target_edge_id
                    .unwrap_or(usize::MAX)
                    .cmp(&second.target_edge_id.unwrap_or(usize::MAX))
            })
    });
    Ok(events)
}

type WavefrontLineTuple = (usize, f64, f64, f64, f64, f64, f64, u64, f64);
type WavefrontEventTuple = (
    u8,
    f64,
    usize,
    usize,
    Option<usize>,
    (f64, f64),
    Vec<(usize, u64)>,
);
type WeldedVerticesTuple = (Vec<(f64, f64, f64)>, Vec<usize>);

#[cfg(feature = "python-extension")]
mod python {
    use super::{
        collect_wavefront_events_core, record_wavefront_interval_core,
        split_face_edges_at_shared_vertices_core, validate_simple_polygon,
        weld_vertices_batch_core, IntervalLineData, IntervalLineTuple, WavefrontEventTuple,
        WavefrontIntervalTuple, WavefrontLineData, WavefrontLineTuple, WeldedVerticesTuple,
    };
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;
    use pyo3::types::PyModule;

    #[pyfunction(name = "api_version")]
    fn py_api_version() -> u32 {
        1
    }

    #[pyfunction(name = "validate_simple_polygon", signature = (points, eps=1e-9))]
    fn py_validate_simple_polygon(
        points: Vec<(f64, f64)>,
        eps: f64,
    ) -> Vec<(String, String, String)> {
        let points = points.into_iter().map(|(x, y)| [x, y]).collect::<Vec<_>>();

        validate_simple_polygon(&points, eps)
            .into_iter()
            .map(|diagnostic| {
                (
                    diagnostic.code.to_string(),
                    diagnostic.message,
                    diagnostic.severity.to_string(),
                )
            })
            .collect()
    }

    #[pyfunction(name = "record_wavefront_interval")]
    fn py_record_wavefront_interval(
        loop_counts: Vec<usize>,
        lines: Vec<IntervalLineTuple>,
        start_time: f64,
        end_time: f64,
        time_tolerance: f64,
        epsilon: f64,
    ) -> PyResult<WavefrontIntervalTuple> {
        let lines = lines
            .into_iter()
            .map(
                |(edge_id, source_edge_id, nx, ny, offset, speed, tx, ty, base_height)| {
                    IntervalLineData {
                        edge_id,
                        source_edge_id,
                        normal: [nx, ny],
                        offset,
                        speed,
                        tangent: [tx, ty],
                        base_height,
                    }
                },
            )
            .collect::<Vec<_>>();
        record_wavefront_interval_core(
            &loop_counts,
            &lines,
            start_time,
            end_time,
            time_tolerance,
            epsilon,
        )
        .map_err(|diagnostic| {
            PyValueError::new_err(format!("{}|{}", diagnostic.code, diagnostic.message))
        })
    }

    #[pyfunction(name = "weld_vertices_batch")]
    fn py_weld_vertices_batch(
        points: Vec<(f64, f64, f64)>,
        tolerance: f64,
    ) -> PyResult<WeldedVerticesTuple> {
        let points = points
            .into_iter()
            .map(|(x, y, z)| [x, y, z])
            .collect::<Vec<_>>();
        weld_vertices_batch_core(&points, tolerance)
            .map(|(vertices, indices)| {
                let vertices = vertices
                    .into_iter()
                    .map(|point| (point[0], point[1], point[2]))
                    .collect();
                (vertices, indices)
            })
            .map_err(|diagnostic| {
                PyValueError::new_err(format!("{}|{}", diagnostic.code, diagnostic.message))
            })
    }

    #[pyfunction(name = "split_face_edges_at_shared_vertices")]
    fn py_split_face_edges_at_shared_vertices(
        vertices: Vec<(f64, f64, f64)>,
        faces: Vec<Vec<usize>>,
        tolerance: f64,
    ) -> PyResult<Vec<Vec<usize>>> {
        let vertices = vertices
            .into_iter()
            .map(|(x, y, z)| [x, y, z])
            .collect::<Vec<_>>();
        split_face_edges_at_shared_vertices_core(&vertices, &faces, tolerance).map_err(
            |diagnostic| {
                PyValueError::new_err(format!("{}|{}", diagnostic.code, diagnostic.message))
            },
        )
    }

    #[pyfunction(name = "collect_wavefront_events", signature = (lines, loop_id, time, eps=1e-9))]
    fn py_collect_wavefront_events(
        lines: Vec<WavefrontLineTuple>,
        loop_id: usize,
        time: f64,
        eps: f64,
    ) -> PyResult<Vec<WavefrontEventTuple>> {
        let lines = lines
            .into_iter()
            .map(
                |(edge_id, nx, ny, offset, speed, tx, ty, generation, base_height)| {
                    WavefrontLineData {
                        edge_id,
                        normal: [nx, ny],
                        offset,
                        speed,
                        tangent: [tx, ty],
                        generation,
                        base_height,
                    }
                },
            )
            .collect::<Vec<_>>();

        collect_wavefront_events_core(&lines, loop_id, time, eps)
            .map(|events| {
                events
                    .into_iter()
                    .map(|event| {
                        (
                            event.kind,
                            event.time,
                            event.edge_id,
                            event.vertex_id,
                            event.target_edge_id,
                            (event.position[0], event.position[1]),
                            event.participants,
                        )
                    })
                    .collect()
            })
            .map_err(|diagnostic| {
                PyValueError::new_err(format!("{}|{}", diagnostic.code, diagnostic.message))
            })
    }

    #[pymodule]
    fn roof_forge_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
        module.add_function(wrap_pyfunction!(py_api_version, module)?)?;
        module.add_function(wrap_pyfunction!(py_validate_simple_polygon, module)?)?;
        module.add_function(wrap_pyfunction!(py_collect_wavefront_events, module)?)?;
        module.add_function(wrap_pyfunction!(
            py_split_face_edges_at_shared_vertices,
            module
        )?)?;
        module.add_function(wrap_pyfunction!(py_weld_vertices_batch, module)?)?;
        module.add_function(wrap_pyfunction!(py_record_wavefront_interval, module)?)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::{
        collect_wavefront_events_core, split_face_edges_at_shared_vertices_core,
        validate_simple_polygon, weld_vertices_batch_core, WavefrontLineData,
    };

    #[test]
    fn accepts_clockwise_and_counter_clockwise_squares() {
        let ccw = [[0.0, 0.0], [2.0, 0.0], [2.0, 1.0], [0.0, 1.0]];
        let cw = [[0.0, 1.0], [2.0, 1.0], [2.0, 0.0], [0.0, 0.0]];

        assert!(validate_simple_polygon(&ccw, 1.0e-9).is_empty());
        assert!(validate_simple_polygon(&cw, 1.0e-9).is_empty());
    }

    #[test]
    fn reports_a_self_intersecting_bow_tie() {
        let bow_tie = [[0.0, 0.0], [2.0, 2.0], [0.0, 2.0], [2.0, 0.0]];
        let issues = validate_simple_polygon(&bow_tie, 1.0e-9);

        assert!(issues.iter().any(|issue| issue.code == "ZERO_AREA"));
        assert!(issues.iter().any(|issue| issue.code == "SELF_INTERSECTION"));
    }

    #[test]
    fn reports_zero_length_edges() {
        let repeated = [[0.0, 0.0], [1.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]];
        let issues = validate_simple_polygon(&repeated, 1.0e-9);

        assert!(issues.iter().any(|issue| issue.code == "ZERO_EDGE"));
    }

    #[test]
    fn collects_square_wavefront_collapse_events() {
        let lines = [
            WavefrontLineData {
                edge_id: 0,
                normal: [0.0, 1.0],
                offset: 0.0,
                speed: 1.0,
                tangent: [1.0, 0.0],
                generation: 0,
                base_height: 0.0,
            },
            WavefrontLineData {
                edge_id: 1,
                normal: [-1.0, 0.0],
                offset: -4.0,
                speed: 1.0,
                tangent: [0.0, 1.0],
                generation: 0,
                base_height: 0.0,
            },
            WavefrontLineData {
                edge_id: 2,
                normal: [0.0, -1.0],
                offset: -4.0,
                speed: 1.0,
                tangent: [-1.0, 0.0],
                generation: 0,
                base_height: 0.0,
            },
            WavefrontLineData {
                edge_id: 3,
                normal: [1.0, 0.0],
                offset: 0.0,
                speed: 1.0,
                tangent: [0.0, -1.0],
                generation: 0,
                base_height: 0.0,
            },
        ];
        let events = collect_wavefront_events_core(&lines, 5, 0.0, 1.0e-9).unwrap();
        assert_eq!(events.len(), 4);
        assert!(events.iter().all(|event| event.kind == 0));
        assert!(events.iter().all(|event| (event.time - 2.0).abs() < 1.0e-9));
        assert!(events
            .iter()
            .all(|event| (event.position[0] - 2.0).abs() < 1.0e-9));
        assert!(events
            .iter()
            .all(|event| (event.position[1] - 2.0).abs() < 1.0e-9));
        assert!(events.iter().all(|event| event.loop_id == 5));
    }

    #[test]
    fn welds_points_in_first_seen_order_and_preserves_bucket_search_order() {
        let points = [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.000_000_5, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [-0.000_000_5, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ];
        let (vertices, indices) = weld_vertices_batch_core(&points, 1.0e-6).unwrap();
        assert_eq!(
            vertices,
            vec![[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        );
        assert_eq!(indices, vec![0, 1, 0, 0, 0, 2]);
    }

    #[test]
    fn rejects_non_finite_points_and_invalid_tolerance() {
        let points = [[f64::NAN, 0.0, 0.0]];
        let error = weld_vertices_batch_core(&points, 1.0e-6).unwrap_err();
        assert_eq!(error.code, "NON_FINITE_WELD_POINT");
        let error = weld_vertices_batch_core(&[], 0.0).unwrap_err();
        assert_eq!(error.code, "INVALID_WELD_TOLERANCE");
    }

    #[test]
    fn splits_face_edges_at_shared_vertices_without_changing_face_regions() {
        let vertices = [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [2.0, 1.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
        ];
        let faces = vec![vec![0, 1, 2], vec![0, 3, 4, 2]];
        let result = split_face_edges_at_shared_vertices_core(&vertices, &faces, 1.0e-9).unwrap();
        assert_eq!(result[0], vec![0, 3, 1, 2]);
        assert_eq!(result[1], vec![0, 3, 4, 2]);
    }

    #[test]
    fn reports_too_few_and_non_finite_points() {
        let too_few = [[0.0, 0.0], [1.0, 0.0]];
        let non_finite = [[0.0, 0.0], [f64::NAN, 0.0], [0.0, 1.0]];

        assert_eq!(
            validate_simple_polygon(&too_few, 1.0e-9)[0].code,
            "POLY_TOO_SMALL"
        );
        assert_eq!(
            validate_simple_polygon(&non_finite, 1.0e-9)[0].code,
            "NON_FINITE"
        );
    }
}
