# RoofForge 0.2.0 — Session Handoff

**Updated:** 2026-11-06  
**Repository:** https://github.com/MorenDord/RoofForge_Blender  
**Validated baseline:** `develop` at `78f51d34f6a6c79cfa7b5b266b7d872908287b55`  
**Active development branch:** `feature/0.2.0-arbitrary-contours-live-pitch`  
**Current PR:** [#6 — WIP: RoofForge 0.2.0](https://github.com/MorenDord/RoofForge_Blender/pull/6) (open, draft; do not merge yet)  
**Latest tested code snapshot:** `aa04e163428348b8a3637bcc99449656a3257baf`  
**Latest docs/plan snapshot before this handoff refresh:** `4dbb835ff471b98b0fd6e086fef5283279e29041` (all commits after tested code `aa04e...` are documentation-only).  
**Latest full CI for code snapshot `aa04e...`:** [Run 42286264952](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42286264952) — all six jobs succeeded. Later commits only corrected/expanded documentation and PR notes.  
**Important:** `main` and `develop` were not changed. Continue on the 0.2 feature branch only.

## User-confirmed product direction

The user manually tested RoofForge 0.1.0 on many quadrilaterals, including irregular shapes with vertices at random positions on all three axes, and confirmed that the current workflow works. This makes 0.1.0 a validated starting point.

The next version should focus only on:

1. Any valid simple single-loop polygon in 3D: convex, concave, arbitrary vertex count, uneven edges and non-planar XYZ eaves. Self-intersections and geometrically impossible settings must be rejected with clear diagnostics.
2. Selecting the mesh object is enough. RoofForge automatically detects the contour; no vertex/edge selection in Edit Mode.
3. A separate pitch angle for every source boundary edge / roof slope.
4. Fast debounced live update when a pitch changes. Keep the last valid roof visible if a rebuild fails. Rapid changes must coalesce rather than create an unbounded queue.
5. Remove the eaves/overhang creation feature and its user-facing controls. Keep only the minimal perimeter side walls needed to close the roof thickness shell; those are structural shell faces, not a decorative eaves/overhang feature.
6. Keep the UI simple for this milestone: a clear numbered list of per-edge angle fields is enough. No pitch diagram or other 1.0 roadmap features.

Do not spend time on ridge/valley/hip profiles, seams, UV, LOD, export, detach/relink or material systems in 0.2.0.

## What is implemented on the feature branch

### Automatic boundary acquisition

Files:
- `addon/adapters/mesh_io.py`
- `addon/operators/generate.py`
- `addon/operators/validate.py`
- `addon/ui/panel.py`

The new `read_object_boundary(obj)`:
- Uses the active mesh object without inspecting selection flags.
- For a face mesh, gets edges incident to exactly one face.
- For a wire-only mesh, gets loose edges.
- Orders one connected closed loop deterministically.
- Rejects branches, disconnected/multiple loops and malformed boundaries.
- Reads coordinates in object-local XYZ.
- Preserves the source mesh; output generation remains a separate object.

The Validate/Create operators use this reader. Panel instructions no longer require selecting a loop in Edit Mode.

### Blender smoke tests

File: `tests/blender_smoke.py`

The smoke suite was expanded to run with every mesh vertex/edge deselected for:
- wire-only mesh in Object Mode;
- wire-only mesh in Edit Mode;
- face mesh in Object Mode;
- face mesh in Edit Mode.

Blender 5.0.1 background smoke, extension ZIP build and the official Blender package validator all pass on CI. This is not a manual GUI viewport test and does not prove Windows/macOS compatibility.

### Overhang property

`addon/properties.py` no longer defines the old unused overhang setting. Keep the 0.2 UI clear of overhang/eaves controls. Audit the rest of the UI and generator before release to ensure no overhang-generation feature is still exposed or called.

## Geometry solver research and measured findings

All timings below are measured on GitHub Actions Linux runners; they are comparative measurements, not a promise of desktop latency. Full reports are attached to CI run 42286264952 (artifacts expire 2026-12-06).

### Fast Rust candidate: `surfer2 = 0.1.0`

Harness: `tests/rust_skeleton_bench/`

This is a research/benchmark harness only. It is not integrated into the Blender extension and there are no distributable Windows/macOS runtime binaries yet.

What currently passes:
- Asymmetric convex and concave radial polygons, 8–128 vertices, equal pitch and variable per-edge pitch.
- A 12-edge multi-notch concave contour, equal and variable pitch.
- L/U with equal pitch.
- Clockwise/reversed L with equal pitch after winding normalization.
- Projected coverage, source support-plane residuals, edge incidence and closed-shell edge-use checks for passing fixtures.

Approximate 128-edge geometric build + DCEL extraction/validation times:
- Asymmetric concave, equal pitch: ~1.18 ms.
- Asymmetric concave, variable pitch: ~1.15 ms.
- Convex: ~1.0–1.5 ms depending on fixture/run.

Known failures:
- L with individual edge pitches: projected coverage mismatch.
- U with individual edge pitches: projected coverage mismatch.
- Symmetric tooth-pattern concave fixtures: one fails projected coverage; another has an edge with four uses (non-manifold).
- Mixed-height XYZ eaves have not been validated through this Rust route.
- This harness does not test Blender datablock creation, UI live-update latency, or native extension integration.

Do not call this solver production-ready yet. Do not treat the benchmark's speed as evidence of arbitrary-shape correctness.

### Historical Python spatial solver 2.9

The old implementation is kept in:
- `tests/legacy_spatial_solver/`
- `tests/legacy_spatial_solver_bench.py`

This is test-only source; it must not be included in the packaged extension. The current package builder includes only the manifest, root entrypoint, addon/core Python trees and install guide.

Latest measured results from CI run 42286264952:
- Flat L/U with equal and variable per-edge pitches: ~2.8–5.0 ms.
- Flat 12-edge multi-notch with equal/variable pitches: ~12–13.5 ms.
- Convex 128-edge: ~4.3–4.4 seconds.
- Asymmetric concave 128-edge: ~8.7 seconds with variable pitch and ~81 seconds with equal pitch.
- Asymmetric concave 64-edge: ~1.0 seconds with variable pitch and ~4.3 seconds with equal pitch.
- Non-planar L and U XYZ fixtures fail strict arrangement/source-adjacency validation.

Conclusion: this historical Python implementation is useful as a correctness reference for small flat L/U cases, but is not an acceptable universal live-update solver for large contours or general 3D eaves.

### Other prototypes

- `core/wavefront.py`: custom Python weighted event solver; has useful constrained fixtures but not a general solution for simultaneous/multi-split events. It was previously slow and must not be wired into the production operator without new proof and benchmarks.
- `core/distance_field.py`: approximate transition geometry and global uniform refinement. Not accepted as the production geometry engine.
- The old spatial 2.9 code has a topology-template / support-plane lifting path for XYZ eaves, but the tested non-planar L/U arrangements failed validation. Do not simply copy it into production.

## Latest CI state

Run: https://github.com/MorenDord/RoofForge_Blender/actions/runs/42286264952

All six jobs passed:
- Python unit tests on Python 3.11.
- Python unit tests on Python 3.13.
- Blender 5.0.1 background smoke, package build and official extension validation.
- Python geometry benchmark.
- Historical spatial solver benchmark.
- Rust skeleton candidate benchmark.

The 61 existing pure-Python tests pass on both supported CI interpreters. These tests mainly validate the existing 0.1/core code; the new Rust and legacy solver cases are opt-in benchmark outputs, not all hard-failing acceptance tests.

Artifacts from that run:
- `roof-forge-rust-skeleton-candidate`: ID `13537187823`.
- `roof-forge-legacy-spatial-bench`: ID `13537927069`.
- `roof-forge-geometry-benchmarks`: ID `13537677025`.
- `roof_forge-0.1.0-blender-5.0.1`: ID `13537637041`.

## Exact next-session plan

The next session should aim to leave a complete, installable 0.2.0 alpha, but do not force a release if a correctness gate is still failing. Work in this order:

### 1. Solver decision / closure of blockers
- Reproduce Rust L/U per-edge failures with minimal fixtures and print each DCEL source face, its node/half-edge cycle, signed projected area and source boundary interval.
- Determine whether the failed source faces are genuinely zero-area/vanished slopes or whether the source-edge labeling/DCEL extraction is wrong.
- Inspect weighted event/tie handling for the symmetric tooth fixtures. Add deterministic simultaneous-event handling / a safe exact fallback; never perturb input coordinates randomly just to dodge simultaneous events.
- Add explicit fixtures for clockwise/counter-clockwise winding, flat and mixed-height XYZ eaves, L, U, multiple notches, acute/narrow necks, repeated reflex vertices and near-simultaneous event times.
- Compare a possible hybrid route (Rust for scalable cases; historical Python only as a deliberately bounded flat small-contour fallback) against one coherent production contract. Do not silently route cases to a solver that can return a different roof topology.
- If the Rust dependency cannot be shipped reliably across Blender-supported platforms, evaluate a pure-Python binding strategy or another embeddable route early. Users must not need Rust/Cargo or a compiler installed.

### 2. Integrate one validated geometry API
- Define a pure geometry entry point that accepts ordered local XYZ points and one pitch per source edge.
- Return roof facets plus stable source-edge IDs.
- Validate the source loop, pitch constraints, full XY-domain coverage, every source boundary interval, facet plane residuals, edge/vertex manifoldness, winding and geometric self-intersections.
- Build the thickness shell only after the upper roof surface passes all checks.
- Keep the source object unchanged and retain the original world transform.
- Do not loosen tolerances or silently drop a source facet to make a fixture pass.

### 3. Per-slope UI and live updates
- Persist a stable mapping between source boundary edge IDs and pitch values. Do not rely only on the current vertex iteration order if topology can change.
- Provide a compact numbered list of pitch fields, with a clear mapping to contour edges.
- Changing one field must debounce the rebuild.
- Do geometry calculation outside the panel draw callback. Use a timer/modal/deferred execution pattern appropriate for Blender 5.0, and guard against stale callbacks after object deletion or add-on unregister.
- Build into temporary data; validate fully; swap/update the generated roof only on success. On failure keep the previous valid roof unchanged and show an actionable error.
- Avoid rebuilding for changes to inactive/unrelated objects and avoid queueing a rebuild for every intermediate keystroke.

### 4. Remove eaves/overhang functionality
- Remove any remaining eaves/overhang properties, UI controls and generator calls for optional overhang extrusion.
- Keep perimeter side walls only for shell thickness closure.
- Add tests that ensure the user-facing 0.2 UI has no overhang parameter/control.

### 5. Packaging and release gates
- If using native Rust, build distributable binaries/wheels for Blender's Python ABI and supported OS/architectures (at minimum Windows, macOS Intel/Apple Silicon as applicable, and Linux); no compiler at user install time.
- Add Blender background smoke coverage for automatic boundary extraction, per-edge pitch persistence, timer/live update, failed-update rollback, source immutability and shell manifoldness.
- Validate the final extension ZIP with Blender 5.0.1; run a clean install in GUI and visual viewport QA if available.
- Update `blender_manifest.toml`, `bl_info.version`, build tooling and README/installation instructions to 0.2.0 only after a real 0.2 package is built.
- Re-run CI from the exact final branch head and record artifact IDs/checksum.

## Definition of done for 0.2.0

- Arbitrary valid single-loop concave/convex contours work in 3D XYZ, not just flat XY.
- Independent angle values per source edge are correctly preserved and applied.
- Fast, debounced live rebuild works; rapid edits coalesce.
- Last valid roof is preserved when a requested pitch/contour is invalid.
- No optional eaves/overhang creation controls or paths remain; shell thickness closure remains.
- Source object stays unchanged.
- Top coverage, boundary continuity, planar facets, self-intersection and closed-shell manifold checks pass.
- Blender 5.0.1 install/package validation and smoke pass. Platform support is stated honestly based on actual platform tests.
- A user can install the ZIP and test the feature end-to-end.

## Repository / workflow rules

- Continue on `feature/0.2.0-arbitrary-contours-live-pitch`; do not modify `main` or `develop`.
- PR #6 remains draft until all production, UI, live-update and package gates pass.
- Temporary CI PRs #7 and #8 were closed; do not reopen them.
- Read current GitHub files/PR/CI before editing. This handoff is a snapshot, not a substitute for checking current branch state.
- Keep geometry code independent of `bpy`.
- Never mutate the user's source mesh.
- Keep all validation gates. Never claim arbitrary-shape support based only on a handful of fixtures or a fast skeleton timing.
- Update this handoff at the end of the next session as well.

## Useful links and commands

- [PR #6](https://github.com/MorenDord/RoofForge_Blender/pull/6)
- [Latest CI run](https://github.com/MorenDord/RoofForge_Blender/actions/runs/42286264952)
- [0.2.0 implementation plan](https://github.com/MorenDord/RoofForge_Blender/blob/feature/0.2.0-arbitrary-contours-live-pitch/docs/PLAN_0.2.0_RU.md)
- [Issue #3: weighted wavefront arbitrary events](https://github.com/MorenDord/RoofForge_Blender/issues/3)

From the repository root:
```bash
python -m compileall -q core addon __init__.py
python -m unittest discover -s tests -v
python tests/benchmark_geometry.py --repeats 3
python tests/legacy_spatial_solver_bench.py
cargo run --release --manifest-path tests/rust_skeleton_bench/Cargo.toml
```
