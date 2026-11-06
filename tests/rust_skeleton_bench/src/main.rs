use std::collections::{BTreeMap, HashMap};
use std::f64::consts::PI;
use std::time::Instant;

use surfer2::{straight_skeleton, ComponentMode, Options, Pslg, Skeleton};

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
            let angle = 2.0 * PI * index as f64 / count as f64;
            let radius = if concave {
                if index % 2 == 0 { 10.0 } else { 8.6 }
            } else {
                10.0 * (1.0 + 0.0015 * (7.0 * angle).sin() + 0.0008 * (11.0 * angle).cos())
            };
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
    weights: &[f64],
) -> Result<(usize, usize, f64), String> {
    let mut top_faces: Vec<(usize, Vec<RoofPoint>)> = Vec::new();
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
                z: node.time,
            });
            current = he.next;
            if current == start {
                break;
            }
        }
        if source_edge >= points.len() || loop_points.len() < 3 {
            return Err(format!("invalid source face {source_edge} with {} vertices", loop_points.len()));
        }
        top_faces.push((source_edge, loop_points));
    }

    if top_faces.len() != points.len() {
        return Err(format!("expected {} source facets, got {}", points.len(), top_faces.len()));
    }

    let footprint_area = signed_area(points).abs();
    let mut projected_area = 0.0;
    let mut edge_uses: HashMap<(usize, usize), Vec<(usize, usize)>> = HashMap::new();
    let mut boundary_source_edges = BTreeMap::<usize, usize>::new();
    let mut boundary_directed = Vec::<(usize, usize)>::new();
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
        let nx = -dy / length;
        let ny = dx / length;
        let speed = weights[*source];
        for p in face {
            let distance = nx * (p.x - a[0]) + ny * (p.y - a[1]);
            let residual = (distance - speed * p.z).abs();
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
                    && dot_p >= -tol && dot_q <= length * length + tol
                {
                    boundary_source_edges.insert(*source, 1);
                    boundary_directed.push((p.node_id, q.node_id));
                }
            }
        }
    }

    if (projected_area - footprint_area).abs() > footprint_area.max(1.0) * 1.0e-7 {
        return Err(format!(
            "projected coverage mismatch: roof {projected_area:.12}, outline {footprint_area:.12}"
        ));
    }
    if boundary_source_edges.len() != points.len() {
        return Err(format!(
            "boundary coverage mismatch: {}/{} source edges touched",
            boundary_source_edges.len(), points.len()
        ));
    }

    for (edge, uses) in &edge_uses {
        if uses.len() == 1 {
            let (a, b) = uses[0];
            if !boundary_directed.contains(&(a, b)) {
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
        if signed_area(&face.iter().map(|p| [p.x, p.y]).collect::<Vec<_>>()) >= 0.0 {
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

    Ok((top_faces.len(), used_nodes.len(), max_plane_residual))
}

fn run_case(count: usize, concave: bool, variable_pitch: bool, repeats: usize) {
    let points = radial_polygon(count, concave);
    let edges: Vec<[usize; 2]> = (0..count)
        .map(|index| [index, (index + 1) % count])
        .collect();
    let weights: Vec<f64> = (0..count)
        .map(|index| {
            let pitch_deg = if variable_pitch {
                28.0 + ((index * 17 % 19) as f64)
            } else {
                35.0
            };
            1.0 / pitch_deg.to_radians().tan()
        })
        .collect();

    let label = if concave { "concave" } else { "convex" };
    let input = match Pslg::from_flat(&points, &edges, Some(&weights)) {
        Ok(value) => value,
        Err(error) => {
            println!("{label},{count},{concave},{variable_pitch},input_error,,,0,0,\"{error}\"");
            return;
        }
    };
    let options = Options { components: ComponentMode::Index(0) };

    let mut times_ms = Vec::new();
    let mut segment_count = 0usize;
    let mut face_count = 0usize;
    let mut vertex_count = 0usize;
    let mut max_residual = 0.0f64;
    let mut last_error = None;

    for _ in 0..repeats {
        let start = Instant::now();
        match straight_skeleton(&input, &options) {
            Ok(skeleton) => {
                match extract_and_validate_roof(&skeleton, &points, &weights) {
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
        println!("{label},{count},{concave},{variable_pitch},error,,,0,0,\"{compact}\"");
        return;
    }

    times_ms.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let median = times_ms[times_ms.len() / 2];
    let p95 = times_ms[((times_ms.len() * 95 + 99) / 100 - 1).min(times_ms.len() - 1)];
    println!(
        "{label},{count},{concave},{variable_pitch},ok,{median:.3},{p95:.3},{segment_count},{face_count},{vertex_count},{max_residual:.3e}"
    );
}

fn main() {
    let repeats = 3;
    println!("case,n,concave,variable_pitch,status,median_ms,p95_ms,skeleton_segments,roof_facets,roof_vertices,max_plane_residual");
    for count in [8, 16, 32, 64, 128] {
        run_case(count, false, false, repeats);
        run_case(count, false, true, repeats);
    }
    for count in [8, 16, 32, 64, 128] {
        run_case(count, true, false, repeats);
        run_case(count, true, true, repeats);
    }
}
