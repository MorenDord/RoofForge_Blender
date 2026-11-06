use std::f64::consts::PI;
use std::time::Instant;

use surfer2::{straight_skeleton, ComponentMode, Options, Pslg};

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
            // The RoofForge moving-line convention uses inward speed cot(pitch).
            1.0 / pitch_deg.to_radians().tan()
        })
        .collect();

    let input = match Pslg::from_flat(&points, &edges, Some(&weights)) {
        Ok(value) => value,
        Err(error) => {
            println!(
                "case,n,concave,variable_pitch,status,median_ms,p95_ms,segments,error",
                "case" = "case",
            );
            eprintln!("INPUT_ERROR n={count}: {error}");
            return;
        }
    };
    let options = Options {
        // CCW input: the interior lies to the left of the first boundary edge.
        components: ComponentMode::Index(0),
    };

    let mut times_ms = Vec::new();
    let mut segment_count = 0usize;
    let mut last_error = None;
    for _ in 0..repeats {
        let start = Instant::now();
        match straight_skeleton(&input, &options) {
            Ok(skeleton) => {
                times_ms.push(start.elapsed().as_secs_f64() * 1000.0);
                segment_count = skeleton.finite_segments().count();
                last_error = None;
            }
            Err(error) => {
                last_error = Some(error.to_string());
                break;
            }
        }
    }

    let label = if concave { "concave" } else { "convex" };
    if let Some(error) = last_error {
        let compact = error.chars().take(180).collect::<String>().replace(',', ";");
        println!("{label},{count},{concave},{variable_pitch},error,,,0,\"{compact}\"");
        return;
    }

    times_ms.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let median = times_ms[times_ms.len() / 2];
    let p95 = times_ms[((times_ms.len() * 95 + 99) / 100 - 1).min(times_ms.len() - 1)];
    println!(
        "{label},{count},{concave},{variable_pitch},ok,{median:.3},{p95:.3},{segment_count},"
    );
}

fn main() {
    let repeats = 3;
    println!("case,n,concave,variable_pitch,status,median_ms,p95_ms,segments,error");
    for count in [8, 16, 32, 64, 128] {
        run_case(count, false, false, repeats);
        run_case(count, false, true, repeats);
    }
    for count in [8, 16, 32, 64] {
        run_case(count, true, false, repeats);
        run_case(count, true, true, repeats);
    }
}
