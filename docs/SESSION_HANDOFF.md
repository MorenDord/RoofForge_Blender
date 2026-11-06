# RoofForge 0.2.0 — Session Handoff

**Updated:** 2026-11-07  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Validated baseline:** develop at `78f51d34f6a6c79cfa7b5b266b7d872908287b55`  
**Active branch:** `feature/0.2.0-arbitrary-contours-live-pitch`  
**Current branch head:** `65c963ea6faac06ae813120772ef5b1f3a258f06`  
**Current PR:** [#6 — WIP: RoofForge 0.2.0](https://github.com/MorenDord/RoofForge_Blender/pull/6) (open, draft; do not merge)  
**Latest full code CI:** [Run 42296262858](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42296262858), successful on code commit `62adbce0608c5aa9e7d353cfb4900453724ac2ce`. The later branch commit `65c963e...` only refreshes documentation/measurements.  
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
- `core/wavefront.py`: custom Python weighted event solver; useful constrained fixtures, but unresolved simultaneous/multi-split cases. Not approved for production integration.
- `core/distance_field.py`: approximate transition geometry and global uniform refinement. Not an acceptable production replacement.
- Non-planar support-plane lifting/all-pairs experiments are test-only and failed strict topology checks. Do not use them as fallback.

## Latest CI
Run [42296262858](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42296262858) completed successfully:
- Python tests on 3.11 and 3.13;
- Blender 5.0.1 background smoke, package build and official extension validation;
- geometry benchmark (now limited to 64 edges);
- Rust candidate diagnostics (now limited to 64 edges);
- legacy spatial benchmarks (now limited to 64 edges);
- 64-edge cProfile.

The latest code-tested commit is `62adbce...`; the current branch head `65c963e...` is a docs-only follow-up.

## Remaining 0.2.0 blockers and next work

1. **Solver correctness first.** A single production solver must pass convex, L, U, multi-notch and symmetric simultaneous-event fixtures with equal and per-edge pitches. Do not weaken validation or drop facets to make a test pass.
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
