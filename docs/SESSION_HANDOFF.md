# RoofForge 0.2.0 — Session Handoff

**Updated:** 2026-11-07  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Validated baseline:** develop at `78f51d34f6a6c79cfa7b5b266b7d872908287b55`  
**Active branch:** `feature/0.2.0-arbitrary-contours-live-pitch`  
**Current branch head:** see [PR #6](https://github.com/MorenDord/RoofForge_Blender/pull/6); latest code-tested commit: `4f970e15e97bc563db52a86d0cd2ef5cc6c1f6b2`  
**Current PR:** [#6 — WIP: RoofForge 0.2.0](https://github.com/MorenDord/RoofForge_Blender/pull/6) (open, draft; do not merge)  
**Latest full code CI:** [Run 42301390659](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42301390659) (push) and [Run 42301399106](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42301399106) (PR), both successful on code commit `4f970e15e97bc563db52a86d0cd2ef5cc6c1f6b2`. The run includes Python 3.11/3.13, variable per-edge pitch concave regression through 64 edges, local face-degeneracy checks, optimized T-junction assembly and Blender 5.0.1 smoke/package validation.  
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

Files: `core/wavefront.py`, `core/validation.py`, `tests/test_geometry.py`, `tests/benchmark_geometry.py`.

The global event-driven state machine supports flat-Z contours with one pitch per source edge, validated reflex splits, child loops, one-split/one-collapse batches, grouped edge collapses, selected endpoint/cross-needle events, exact facet fragments and strict surface boundary validation. It now has:
- strict simultaneous point-termination resolution: only accepted if all current vertices, finite active edges and event positions converge to one point;
- endpoint-hit + collapse resolution for both endpoint orientations, with zero-length finite edge, event position, support-line and successor-loop checks;
- successor-loop generation rescheduling after topology changes;
- strict failure for unsupported mixed event groups and multiple same-time splits on one loop.

Regression coverage:
- `test_wavefront_resolves_symmetric_concave_point_terminations_through_64_edges`: equal pitch, 8/16/32/64;
- `test_wavefront_resolves_variable_pitch_concave_contours_through_64_edges`: deterministic variable pitch, 8/16/32/64; checks projected coverage, facet slope metadata and closed thickness shell;
- local face-area validation distinguishes small well-shaped faces from facets whose altitude is below coordinate tolerance.
All pass on Python 3.11 and 3.13.

Latest CI: [42301390659](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42301390659) (push) and [42301399106](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42301399106) (PR), both successful on code commit `4f970e15e97bc563db52a86d0cd2ef5cc6c1f6b2`.

All timings below are medians of three runs on the Actions Linux runner, comparison only:

| Edges | Equal trace | Equal surface | Variable trace | Variable surface | Variable facets / vertices |
|---:|---:|---:|---:|---:|---:|
| 8 | 0.47 ms | 1.37 ms | 0.84 ms | 2.19 ms | 30 / 32 |
| 16 | 2.40 ms | 5.10 ms | 6.14 ms | 13.47 ms | 133 / 134 |
| 32 | 7.77 ms | 17.09 ms | 35.13 ms | 74.13 ms | 525 / 526 |
| 64 | 21.34 ms | 32.19 ms | 212.63 ms | 474.54 ms | 2089 / 2091 |

The 64-edge variable-pitch surface initially took 28.50 seconds to assemble. `_split_face_edges_at_shared_vertices()` was scanning every mesh vertex for every facet edge. It now builds sorted coordinate indexes on all three axes, queries the narrowest coordinate interval, then performs the same exact 3D projection and distance checks. The measured assembly time fell to 474.54 ms (roughly 60×). This is substantially better, but around half a second at the 64-edge variable-pitch limit is still a borderline live-preview latency.

### Face-area tolerance

The validator previously compared every face to `eps * model_scale²`. That rejected locally well-shaped small facets just because the overall roof was large. It now compares face area to `global_linear_tolerance * this_face_longest_edge`, which corresponds to a local altitude check. A small but well-resolved triangle is accepted; a long, thin triangle whose altitude is below coordinate tolerance still returns `ZERO_AREA_FACE`. Both conditions have explicit tests.

### Boundaries and remaining gaps

- The benchmark uses one deterministic alternating-radius concave family (radii 10.0 / 8.6) and one periodic pitch profile, not a seeded random corpus.
- Existing L/U fixtures and selected simultaneous split/collapse combinations pass, but generic multiple-split groups and some mixed event batches remain unsupported.
- `build_moving_lines()` still rejects different Z eave heights. Do not flatten source XYZ to bypass this.
- The user-facing generator still calls `core.mesh.build_roof_surface()`. `build_wavefront_roof_surface()` is **not yet wired into the Blender operator**.
- Blender smoke/package and official extension validation pass, but manual viewport QA and complete per-edge UI/live rebuild remain open.

This is a promising Python candidate, not yet a production solver. Keep PR #6 in draft until the contour corpus, mixed-height policy, user-facing integration and live-update behaviour are validated.
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

1. **Solver correctness first.** The custom Python wavefront now passes the deterministic symmetric and variable-pitch concave radial family at 8/16/32/64 edges and existing hand-built L/U fixtures. Next gates are seeded/asymmetric/narrow-neck contours, near-simultaneous events and multiple split events at one time. Do not weaken validation or drop facets to make a test pass.
2. **XYZ policy.** Preserve XYZ and support non-planar concave contours if the solver can prove a valid shell. Otherwise reject unsupported combinations with actionable diagnostics. Never flatten silently.
3. **Runtime/distribution.** If using Rust, build and test distributable binaries for Blender-supported Windows/macOS/Linux without requiring users to install a compiler.
4. **Per-edge UI.** Store stable source-edge IDs and a reliable mapping from each edge to its pitch.
5. **Live update.** Debounce edits, coalesce rapid changes, perform geometry outside draw callbacks, and swap in a rebuilt object only after full validation. On failure preserve the last valid output.
6. **Overhang removal.** Audit the full UI and generator for any remaining optional overhang/eaves code; keep only structural shell closure.
7. **Manual QA.** Test a clean ZIP installation and inspect generated roofs in Blender's viewport. CI background smoke is not enough.

The PR remains draft/WIP. Do not package or tag 0.2.0 until solver correctness, UI, live update, runtime distribution and visual QA are closed.

## Useful links
- [PR #6](https://github.com/MorenDord/RoofForge_Blender/pull/6)
- [Latest push CI](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42301390659)
- [Latest PR CI](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42301399106)
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
