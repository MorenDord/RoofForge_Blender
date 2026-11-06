use std::collections::{BTreeMap, HashMap};
use std::f64::consts::PI;
use std::time::Instant;

use surfer2::{interior_straight_skeleton, straight_skeleton, ComponentMode, Options, Polygon, Pslg, Skeleton};

#[derive(Clone, Copy)]
struct RoofPoint {
    node_id: usize,
    x: f64,
    y: f64,
    z: f64,
}

fn radial_polygon(count: usize, concave: bool) -> Vec<[f64; 2]> {
    (0..count)
        .map(|index| {
            let phase = index as f64;
            let angle = 2.0 * PI * phase / count as f64
                + if concave { 0.045 * (0.7 * phase).sin() } else { 0.0 };
            let radius = if concave {
                8.6 + 1.05 * (1.73 * phase + 0.2).sin()
                    + 0.55 * (2.41 * phase).cos()
            } else {
                10.0 * (1.0 + 0.0015 * (7.0 * angle).sin() + 0.0008 * (11.0 * angle).cos())
            };
            [radius * angle.cos(), radius * angle.sin()]
        })
        .collect()
}

fn symmetric_tooth_polygon(count: usize) -> Vec<[f64; 2]> {
    (0..count)
        .map(|index| {
            let angle = 2.0 * PI * index as f64 / count as f64;
            let radius = if index % 2 == 0 { 10.0 } else { 8.6 };
            [radius * angle.cos(), radius * angle.sin()]
        })
        .collect()
}

fn signed_area(points: &[[f64; 2]]) -> f64 {
    0.5 * points.iter().enumerate().map(|(i, p)| {
        let q = points[(i + 1) % points.len()];
        p[0] * q[1] - q[0] * p[1]
    }).sum::<f64>()
}

fn extract_and_validate_roof(
    skeleton: &Skeleton,
    points: &[[f64; 2]],
    speeds: &[f64],
    time_to_z: f64,
) -> Result<(usize, usize, f64), String> {
    let mut top_faces: Vec<(usize, Vec<RoofPoint>)> = Vec::new();
    let mut degenerate_sources = Vec::new();
    let halfedges = skeleton.halfedges();
    let nodes = skeleton.nodes();

    for face in skeleton.faces() {
        let Some(source_edge) = face.source_input_edge.map(|value| value as usize) else {
            continue;
        };
        let Some(start) = face.halfedge else {
            return Err(format!("source edge {source_edge} has no DCEL halfedge"));
        };
        let mut current = start;
        let mut loop_points = Vec::new();
        let mut guard = 0usize;
        loop {
            guard += 1;
            if guard > halfedges.len() + 1 {
                return Err(format!("DCEL cycle exceeded guard for source edge {source_edge}"));
            }
            let he = halfedges.get(current.0 as usize)
                .ok_or_else(|| format!("invalid halfedge {}", current.0))?;
            let node = nodes.get(he.origin.0 as usize)
                .ok_or_else(|| format!("invalid node {}", he.origin.0))?;
            let point = node.point.ok_or_else(|| {
                format!("bounded source face {source_edge} contains an infinite node")
            })?;
            loop_points.push(RoofPoint {
                node_id: he.origin.0 as usize,
                x: point.x,
                y: point.y,
                z: node.time * time_to_z,
            });
            current = he.next;
            if current == start {
                break;
            }
        }
        if source_edge >= points.len() {
            return Err(format!("source face references invalid boundary edge {source_edge}"));
        }
        if loop_points.len() < 3 || signed_area(&loop_points.iter().map(|p| [p.x, p.y]).collect::<Vec<_>>()).abs() <= 1.0e-12 {
            degenerate_sources.push(source_edge);
            continue;
        }
        top_faces.push((source_edge, loop_points));
    }

    if top_faces.is_empty() {
        return Err("weighted skeleton returned no non-degenerate roof facets".to_string());
    }

    let signed_footprint = signed_area(points);
    let footprint_area = signed_footprint.abs();
    let winding = if signed_footprint >= 0.0 { 1.0 } else { -1.0 };
    let mut projected_area = 0.0;
    let mut edge_uses: HashMap<(usize, usize), Vec<(usize, usize)>> = HashMap::new();
    let mut boundary_source_edges = BTreeMap::<usize, usize>::new();
    let mut boundary_directed = Vec::<(usize, usize)>::new();
    let mut boundary_intervals = vec![Vec::<(f64, f64)>::new(); points.len()];
    let mut max_plane_residual = 0.0f64;

    for (source, face) in &top_faces {
        let xy: Vec<[f64; 2]> = face.iter().map(|p| [p.x, p.y]).collect();
        projected_area += signed_area(&xy).abs();

        let a = points[*source];
        let b = points[(*source + 1) % points.len()];
        let dx = b[0] - a[0];
        let dy = b[1] - a[1];
        let length = dx.hypot(dy);
        if length <= 1.0e-12 {
            return Err(format!("zero-length source edge {source}"));
        }
        let nx = -dy / length * winding;
        let ny = dx / length * winding;
        let speed = speeds[*source];
        for p in face {
            let distance = nx * (p.x - a[0]) + ny * (p.y - a[1]);
            let residual = (distance - speed * (p.z / time_to_z)).abs();
            max_plane_residual = max_plane_residual.max(residual);
        }

        for i in 0..face.len() {
            let p = face[i];
            let q = face[(i + 1) % face.len()];
            edge_uses.entry((p.node_id.min(q.node_id), p.node_id.max(q.node_id)))
                .or_default().push((p.node_id, q.node_id));

            if p.z.abs() <= 1.0e-9 && q.z.abs() <= 1.0e-9 {
                let ap = [p.x - a[0], p.y - a[1]];
                let bp = [q.x - a[0], q.y - a[1]];
                let cross_p = dx * ap[1] - dy * ap[0];
                let cross_q = dx * bp[1] - dy * bp[0];
                let dot_p = ap[0] * dx + ap[1] * dy;
                let dot_q = bp[0] * dx + bp[1] * dy;
                let tol = length * 1.0e-7 + 1.0e-9;
                if cross_p.abs() <= tol && cross_q.abs() <= tol
                    && dot_p >= -tol && dot_p <= length * length + tol
                    && dot_q >= -tol && dot_q <= length * length + tol
                {
                    boundary_source_edges.insert(*source, 1);
                    boundary_directed.push((p.node_id, q.node_id));
                    let t0 = dot_p / (length * length);
                    let t1 = dot_q / (length * length);
                    boundary_intervals[*source].push((t0.min(t1), t0.max(t1)));
                }
            }
        }
    }

    if (projected_area - footprint_area).abs() > footprint_area.max(1.0) * 1.0e-7 {
        return Err(format!(
            "projected coverage mismatch: roof {projected_area:.12}, outline {footprint_area:.12}"
        ));
    }
    for (edge_id, intervals) in boundary_intervals.iter_mut().enumerate() {
        intervals.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
        let mut covered = 0.0f64;
        for (low, high) in intervals.iter().copied() {
            if low > covered + 1.0e-7 {
                return Err(format!("boundary edge {edge_id} has a gap at t={covered:.6} before {low:.6}; degenerate source facets={degenerate_sources:?}"));
            }
            covered = covered.max(high);
        }
        if covered < 1.0 - 1.0e-7 {
            return Err(format!("boundary edge {edge_id} is only covered to t={covered:.6}; degenerate source facets={degenerate_sources:?}"));
        }
    }

    for (edge, uses) in &edge_uses {
        if uses.len() == 1 {
            let (a, b) = uses[0];
            if !boundary_directed.contains(&(a, b)) && !boundary_directed.contains(&(b, a)) {
                return Err(format!("open internal roof edge {}-{}", edge.0, edge.1));
            }
        } else if uses.len() == 2 {
            if uses[0].0 != uses[1].1 || uses[0].1 != uses[1].0 {
                return Err(format!("inconsistent winding on roof edge {}-{}", edge.0, edge.1));
            }
        } else {
            return Err(format!("roof edge {}-{} has {} uses", edge.0, edge.1, uses.len()));
        }
    }

    if max_plane_residual > 1.0e-7 {
        return Err(format!("support-plane residual {max_plane_residual:.3e} exceeds tolerance"));
    }

    // Close a uniform-thickness shell using shared top and bottom node IDs.
    let mut used_nodes = BTreeMap::<usize, usize>::new();
    for (_source, face) in &top_faces {
        for p in face {
            let next = used_nodes.len();
            used_nodes.entry(p.node_id).or_insert(next);
        }
    }
    let count = used_nodes.len();
    let mut shell_edge_uses: HashMap<(usize, usize), usize> = HashMap::new();
    let mut add_face = |face: &[usize]| {
        for i in 0..face.len() {
            let a = face[i];
            let b = face[(i + 1) % face.len()];
            *shell_edge_uses.entry((a.min(b), a.max(b))).or_insert(0) += 1;
        }
    };

    for (_source, face) in &top_faces {
        let ids: Vec<usize> = face.iter().map(|p| used_nodes[&p.node_id]).collect();
        if signed_area(&face.iter().map(|p| [p.x, p.y]).collect::<Vec<_>>()) * winding >= 0.0 {
            add_face(&ids);
            let mut bottom: Vec<usize> = ids.iter().map(|id| id + count).collect();
            bottom.reverse();
            add_face(&bottom);
        } else {
            let mut top = ids.clone();
            top.reverse();
            add_face(&top);
            let bottom: Vec<usize> = ids.iter().map(|id| id + count).collect();
            add_face(&bottom);
        }
    }
    for (a, b) in boundary_directed {
        let a_id = used_nodes[&a];
        let b_id = used_nodes[&b];
        add_face(&[a_id, b_id, b_id + count, a_id + count]);
    }

    if let Some((edge, uses)) = shell_edge_uses.iter().find(|(_, uses)| **uses != 2) {
        return Err(format!("closed shell edge {}-{} has {} uses", edge.0, edge.1, uses));
    }

    if !degenerate_sources.is_empty() {
        return Err(format!("degenerate source facets {:?} were omitted although boundary coverage passed", degenerate_sources));
    }

    Ok((top_faces.len(), used_nodes.len(), max_plane_residual))
}

fn run_points_case(
    label: &str,
    points: &[[f64; 2]],
    pitches_degrees: &[f64],
    repeats: usize,
) {
    run_points_case_mode(label, points, pitches_degrees, repeats, None);
}

fn run_points_case_mode(
    label: &str,
    points: &[[f64; 2]],
    pitches_degrees: &[f64],
    repeats: usize,
    force_pslg: Option<bool>,
) {
    let mut points = points.to_vec();
    let mut pitches_degrees = pitches_degrees.to_vec();
    let count = points.len();
    if signed_area(&points) < 0.0 {
        let old_pitches = pitches_degrees.clone();
        points.reverse();
        pitches_degrees = (0..count)
            .map(|index| old_pitches[(count + count - 2 - index) % count])
            .collect();
    }
    let variable_pitch = pitches_degrees.iter().any(|value| {
        (*value - pitches_degrees[0]).abs() > 1.0e-9
    });
    let concave = (0..count).any(|i| {
        let a = points[i];
        let b = points[(i + 1) % count];
        let c = points[(i + 2) % count];
        let cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
        cross * signed_area(&points).signum() < -1.0e-9
    });
    let edges: Vec<[usize; 2]> = (0..count)
        .map(|index| [index, (index + 1) % count])
        .collect();
    let weights: Vec<f64> = pitches_degrees.iter()
        .map(|pitch| 1.0 / pitch.to_radians().tan())
        .collect();

    // Inputs are normalized to CCW above. The ordinary polygon API uses
    // unit-speed wavefronts; the PSLG API applies multiplicative edge weights.
    // Force both APIs on the same equal-pitch fixtures to separate weighted
    // propagation defects from DCEL extraction / component-selection defects.
    let use_pslg = force_pslg.unwrap_or(variable_pitch);
    let (input_pslg, input_polygon) = if use_pslg {
        match Pslg::from_flat(&points, &edges, Some(&weights)) {
            Ok(value) => (Some(value), None),
            Err(error) => {
                println!("{label},{count},{concave},{variable_pitch},input_error,,,0,0,\"{error}\"");
                return;
            }
        }
    } else {
        match Polygon::from_flat(&points, &[0]) {
            Ok(value) => (None, Some(value)),
            Err(error) => {
                println!("{label},{count},{concave},{variable_pitch},input_error,,,0,0,\"{error}\"");
                return;
            }
        }
    };

    let options = Options { components: ComponentMode::Index(0) };
    let z_scale = if use_pslg { 1.0 } else { weights[0] };
    let speeds = if use_pslg { weights.clone() } else { vec![1.0; count] };

    let mut times_ms = Vec::new();
    let mut segment_count = 0usize;
    let mut face_count = 0usize;
    let mut vertex_count = 0usize;
    let mut max_residual = 0.0f64;
    let mut last_error = None;

    for _ in 0..repeats {
        let start = Instant::now();
        let result = if let Some(input) = &input_pslg {
            straight_skeleton(input, &options)
        } else {
            interior_straight_skeleton(input_polygon.as_ref().unwrap())
        };

        match result {
            Ok(skeleton) => {
                match extract_and_validate_roof(&skeleton, &points, &speeds, z_scale) {
                    Ok((faces, vertices, residual)) => {
                        times_ms.push(start.elapsed().as_secs_f64() * 1000.0);
                        segment_count = skeleton.finite_segments().count();
                        face_count = faces;
                        vertex_count = vertices;
                        max_residual = residual;
                        last_error = None;
                    }
                    Err(error) => {
                        last_error = Some(error);
                        break;
                    }
                }
            }
            Err(error) => {
                last_error = Some(error.to_string());
                break;
            }
        }
    }

    if let Some(error) = last_error {
        let compact = error.chars().take(180).collect::<String>().replace(',', ";");
        println!("{label},{count},{concave},{variable_pitch},error,,,0,0,0,\"{compact}\"");
        return;
    }

    times_ms.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let median = times_ms[times_ms.len() / 2];
    let p95 = times_ms[((times_ms.len() * 95 + 99) / 100 - 1).min(times_ms.len() - 1)];
    println!(
        "{label},{count},{concave},{variable_pitch},ok,{median:.3},{p95:.3},{segment_count},{face_count},{vertex_count},{max_residual:.3e}"
    );
}

fn run_radial_case(count: usize, concave: bool, variable_pitch: bool, repeats: usize) {
    let points = radial_polygon(count, concave);
    let pitches: Vec<f64> = (0..count).map(|index| {
        if variable_pitch { 28.0 + ((index * 17 % 19) as f64) } else { 35.0 }
    }).collect();
    let label = if concave { "radial_concave" } else { "radial_convex" };
    run_points_case(label, &points, &pitches, repeats);
}

fn run_symmetric_adversarial(count: usize, repeats: usize) {
    let points = symmetric_tooth_polygon(count);
    let pitches = vec![35.0; count];
    run_points_case("symmetric_concave_adversarial", &points, &pitches, repeats);
}

fn main() {
    let repeats = 3;
    println!("case,n,concave,variable_pitch,status,median_ms,p95_ms,skeleton_segments,roof_facets,roof_vertices,max_plane_residual");
    for count in [8, 16, 32, 64, 128] {
        run_radial_case(count, false, false, repeats);
        run_radial_case(count, false, true, repeats);
    }
    for count in [8, 16, 32, 64, 128] {
        run_radial_case(count, true, false, repeats);
        run_radial_case(count, true, true, repeats);
    }
    for count in [8, 16] {
        run_symmetric_adversarial(count, repeats);
    }

    let l_shape = [
        [0.0, 0.0], [8.0, 0.0], [8.0, 4.0],
        [4.0, 4.0], [4.0, 8.0], [0.0, 8.0],
    ];
    run_points_case("concave_L_equal_pitch", &l_shape, &[35.0; 6], repeats);
    run_points_case_mode("concave_L_equal_pitch_pslg", &l_shape, &[35.0; 6], repeats, Some(true));
    run_points_case("concave_L_variable_pitch", &l_shape, &[30.0, 36.0, 42.0, 34.0, 39.0, 32.0], repeats);

    let u_shape = [
        [0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [7.0, 8.0],
        [7.0, 3.0], [3.0, 3.0], [3.0, 8.0], [0.0, 8.0],
    ];
    run_points_case("concave_U_equal_pitch", &u_shape, &[35.0; 8], repeats);
    run_points_case_mode("concave_U_equal_pitch_pslg", &u_shape, &[35.0; 8], repeats, Some(true));
    run_points_case("concave_U_variable_pitch", &u_shape, &[32.0, 35.0, 38.0, 40.0, 34.0, 37.0, 31.0, 36.0], repeats);

    let multi_notch = [
        [0.0, 0.0], [12.0, 0.0], [12.0, 8.0], [10.0, 8.0],
        [9.0, 4.0], [8.0, 4.0], [7.0, 7.0], [5.0, 7.0],
        [4.0, 4.0], [3.0, 4.0], [2.0, 8.0], [0.0, 8.0],
    ];
    run_points_case("concave_multi_notch_equal_pitch", &multi_notch, &[35.0; 12], repeats);
    run_points_case("concave_multi_notch_variable_pitch", &multi_notch, &[34.0, 35.0, 36.0, 37.0, 34.0, 38.0, 33.0, 36.0, 35.0, 37.0, 34.0, 36.0], repeats);

    let mut reversed_l = l_shape.to_vec();
    reversed_l.reverse();
    let mut reversed_l_pitch = vec![35.0; 6];
    reversed_l_pitch.reverse();
    run_points_case("concave_L_reversed_winding_equal_pitch", &reversed_l, &reversed_l_pitch, repeats);
}
