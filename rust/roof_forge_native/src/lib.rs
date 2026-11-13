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

#[cfg(feature = "python-extension")]
mod python {
    use super::validate_simple_polygon;
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

    #[pymodule]
    fn roof_forge_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
        module.add_function(wrap_pyfunction!(py_api_version, module)?)?;
        module.add_function(wrap_pyfunction!(py_validate_simple_polygon, module)?)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::validate_simple_polygon;

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
