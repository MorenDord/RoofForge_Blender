# RoofForge 0.2.0 — Session Handoff

**Updated:** 2026-11-07  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Validated baseline:** develop at `78f51d34f6a6c79cfa7b5b266b7d872908287b55`  
**Active branch:** `feature/0.2.0-arbitrary-contours-live-pitch`  
**Current branch head:** see [PR #6](https://github.com/MorenDord/RoofForge_Blender/pull/6); latest code-tested commit: `edc8a2422d911c315179d43f6c820227fcda1d7b`  
**Current PR:** [#6 — WIP: RoofForge 0.2.0](https://github.com/MorenDord/RoofForge_Blender/pull/6) (open, draft; do not merge)  
**Latest full code CI:** [Run 42298606023](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42298606023) (push) and [Run 42298615339](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42298615339) (PR), both successful on code commit `edc8a2422d911c315179d43f6c820227fcda1d7b`. The run includes the whole-point resolver, 8/16/32/64 concave regression, Blender 5.0.1 smoke/package validation and the geometry benchmarks.  
**Important:** `main` and `develop` have not been modified. Continue only on the feature branch.

## Confirmed 0.2.0 product scope

1. Simple, single-loop contour, convex or concave, with up to **64 boundary edges**. 64 is the maximum 0.2.0 target. There is no need to benchmark or optimize 128-edge contours for this release.
2. Select the active mesh object only. No selected vertices or edges required. Detect one outer boundary for both wire-only and face meshes.
3. One independent pitch angle per source boundary edge.
4. Debounced live rebuild after a pitch edit. Coalesce rapid changes; keep the last valid roof if a rebuild fails.
5. Preserve source XYZ coordinates. Never flatten or silently modify the source object.
6. Remove optional eaves/overhang generation and UI controls. Keep only structural side walls that close the shell thickness.
7. Keep the UI compact: a numbered list of per-edge angle fields is sufficient.

Defer ridge/valley/hip profiles, standing seams, UV, LOD, export, detach/relink and complex material systems.

## Current implementation on the feature branch

### Automatic object boundary
Files:
- `addon/adapters/mesh_io.py`
- `addon/operators/generate.py`
- `addon/operators/validate.py`
- `addon/ui/panel.py`

`read_object_boundary(obj)`:
- reads the active object's mesh without relying on selection flags;
- for face meshes, finds edges with exactly one linked face;
- for wire-only meshes, finds loose edges;
- orders one closed loop deterministically;
- rejects disconnected loops, branches and malformed boundaries;
- returns object-local XYZ coordinates.

Validate/Create use this path. UI text no longer asks users to select an edge loop.

### Blender smoke and packaging
File: `tests/blender_smoke.py`

Background smoke covers wire-only and face meshes, in Object and Edit Mode, with all mesh elements deselected. Latest CI passed Blender 5.0.1 smoke, ZIP package build and official extension validation. This does not replace manual GUI/viewport QA, nor does it prove native runtime compatibility on Windows/macOS.

### Custom Python weighted wavefront — alpha candidate

Files: `core/wavefront.py`, `tests/test_geometry.py`, `tests/benchmark_geometry.py`.

The current implementation is a global event-driven state machine, not merely a convex-only solver. It supports flat-Z contours with one pitch per source edge, validated reflex split operations, separate child loops, one-split/one-collapse batches, grouped edge collapses, selected endpoint/cross-needle events, exact facet fragments, and strict surface boundary validation. Unsupported mixed event groups and multiple same-time splits on one loop are still rejected.

A concrete failure was found in the deterministic alternating-radius concave fixture: from 16 through 64 edges the batch contained many `VERTEX_HIT` and `EDGE_COLLAPSE` events, all converging at one center point, but the resolver treated it as an unsupported cross-needle. Added `_resolve_simultaneous_point_termination()` now accepts that case only after rechecking every current vertex, every finite active edge, and every event position against the same point. It does not accept partial collapses or multiple terminal nodes.

Regression coverage: `test_wavefront_resolves_symmetric_concave_point_terminations_through_64_edges` runs 8/16/32/64 edges, verifies full projected-area coverage, assembles the surface, builds the thickness shell and checks closed-mesh validity. It passes on Python 3.11/3.13.

Latest CI artifact timings on the Actions Linux runner (three repeats; comparative only; equal pitch 35°):

| Edges | Convex trace median | Concave trace median | Concave surface median |
|---:|---:|---:|---:|
| 8 | 1.33 ms | 0.40 ms | 1.12 ms |
| 16 | 3.74 ms | 1.99 ms | 4.16 ms |
| 32 | 13.76 ms | 6.29 ms | 13.86 ms |
| 64 | 54.31 ms | 21.83 ms | 48.62 ms |

The 64-edge concave case yields 64 faces and 65 welded vertices. This is one deterministic family, not a general correctness claim. Per-edge variable pitch on this radial family, narrow-neck cases, more general simultaneous split groups and mixed-height eaves remain to be tested. `build_moving_lines()` explicitly rejects mixed Z eaves. **The user-facing operator still calls `core.mesh.build_roof_surface()`; `build_wavefront_roof_surface()` is not yet wired into Blender.** Keep the PR draft until this is addressed.

### Historical solver optimization — test-only
The old 2.6/2.9 Python solvers are copied under `tests/legacy_spatial_solver/` strictly for comparisons; they are not included in the installable extension.

Changes made during this session:
- indexed live wavefront segments by their source edge, rebuilding that index only after split/collapse topology changes;
- measured separate facet-assembly indexes for unweighted and weighted paths;
- retained dominant-axis point range filtering for the unweighted path;
- retained 2D XY voxel traversal plus exact XYZ distance checks for the weighted path;
- added a 64-edge cProfile harness and capped routine benchmark matrices at 8, 16, 32 and 64 edges.

Do not wire these historical copies into the production Blender operator without a separate integration/review.

## Solver research and current measured findings

All figures below are from GitHub Actions Linux runners and are comparative only.

### Rust candidate: surfer2 0.1.0
Research harness: `tests/rust_skeleton_bench/`. Not integrated into the extension, and no distributable Windows/macOS/Linux runtime builds exist.

At 64 edges:
- convex radial: about 0.56 ms equal pitch, 0.40 ms variable pitch;
- asymmetric concave radial: about 0.42 ms equal pitch, 0.39 ms variable pitch;
- projected coverage, plane residual and closed-shell checks pass for those radial cases;
- 12-edge multi-notch passes at about 0.09 ms;
- small event-focused L/U cases pass, including split/collapse order controls.

Blocking failures:
- the main 8×8 L contour with individual edge pitches loses the facets for source edges 4 and 5 (roof projected area 32 vs outline 48);
- symmetric simultaneous-event fixtures fail coverage or produce an edge with four uses;
- raw weighted speeds are less numerically stable; common normalization fixes some U cases but not the main L case;
- mixed-height XYZ contours are not supported through this Rust route.

Conclusion: extremely fast on passing fixtures, but not yet a production solver.

### Historical Python spatial solver 2.9
Latest 64-edge benchmark from run [42296262858](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42296262858):
- radial convex 64 edges: about 342 ms equal pitch / 530 ms variable pitch;
- radial concave 64 edges: about 712 ms equal pitch / 491 ms variable pitch;
- flat L/U cases: about 3.4–5.4 ms;
- flat 12-edge multi-notch: about 11–15 ms;
- non-planar L/U XYZ fixtures fail strict source-adjacency/manifold validation;
- all-pairs alternatives for non-planar L/U also leave internal open edges and are rejected.

64-edge cProfile, same CI run:
- concave equal pitch: 2.23 s under cProfile;
- concave variable pitch: 1.44 s under cProfile.
Profiling overhead is included. Remaining cost is split between wavefront event generation and facet assembly.

Conclusion: useful as a correctness/reference implementation for small flat L/U cases, but too slow for a genuinely live rebuild on complex 64-edge contours and not a validated general 3D solution.

### Other prototypes
- `core/distance_field.py`: approximate transition geometry and global uniform refinement. Not an acceptable production replacement.
- Non-planar support-plane lifting/all-pairs experiments are test-only and failed strict topology checks. Do not use them as fallback.
- `surfer2 0.1.0`: source review found that weighted-event refinement work is discarded by the Rust port instead of being processed like the C++ engine. This is a source-level limitation, not merely a RoofForge test-harness issue; see [refine.rs](https://github.com/atsyplenkov/surfer2-rs/blob/master/src/triangulation/refine.rs). Do not keep tuning speed normalization as a substitute for implementing that missing logic.

## Latest CI
Runs [42298606023](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42298606023) (push) and [42298615339](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42298615339) (PR) both completed successfully on `edc8a2422d911c315179d43f6c820227fcda1d7b`:
- Python tests on 3.11 and 3.13, including the new simultaneous-point regression for 8/16/32/64 edges;
- Blender 5.0.1 background smoke, package build and official extension validation;
- geometry benchmark for convex and concave wavefront traces/surface assembly through 64 edges;
- Rust candidate diagnostics (64-edge scope);
- legacy spatial benchmarks (64-edge scope);
- 64-edge cProfile.

The geometry benchmark artifact shows the symmetric concave 64-edge wavefront surface completing in 48.62 ms median, with 65 vertices and 64 faces.

## Remaining 0.2.0 blockers and next work

1. **Solver correctness first.** The custom Python wavefront now passes the deterministic symmetric concave radial family at 8/16/32/64 edges and existing hand-built L/U fixtures. Next gates are asymmetric/narrow-neck concave contours, per-edge variable pitch on the 64-edge family, near-simultaneous events and multiple split events at one time. Do not weaken validation or drop facets to make a test pass.
2. **XYZ policy.** Preserve XYZ and support non-planar concave contours if the solver can prove a valid shell. Otherwise reject unsupported combinations with actionable diagnostics. Never flatten silently.
3. **Runtime/distribution.** If using Rust, build and test distributable binaries for Blender-supported Windows/macOS/Linux without requiring users to install a compiler.
4. **Per-edge UI.** Store stable source-edge IDs and a reliable mapping from each edge to its pitch.
5. **Live update.** Debounce edits, coalesce rapid changes, perform geometry outside draw callbacks, and swap in a rebuilt object only after full validation. On failure preserve the last valid output.
6. **Overhang removal.** Audit the full UI and generator for any remaining optional overhang/eaves code; keep only structural shell closure.
7. **Manual QA.** Test a clean ZIP installation and inspect generated roofs in Blender's viewport. CI background smoke is not enough.

The PR remains draft/WIP. Do not package or tag 0.2.0 until solver correctness, UI, live update, runtime distribution and visual QA are closed.

## Useful links
- [PR #6](https://github.com/MorenDord/RoofForge_Blender/pull/6)
- [Latest code CI](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42296262858)
- [Implementation plan](https://github.com/MorenDord/RoofForge_Blender/blob/feature/0.2.0-arbitrary-contours-live-pitch/docs/PLAN_0.2.0_RU.md)
- [Issue #3: weighted wavefront arbitrary events](https://github.com/MorenDord/RoofForge_Blender/issues/3)

From the repository root:
```bash
python -m compileall -q core addon __init__.py
python -m unittest discover -s tests -v
python tests/benchmark_geometry.py --repeats 3
python tests/legacy_spatial_solver_bench.py
cargo run --release --manifest-path tests/rust_skeleton_bench/Cargo.toml
```
