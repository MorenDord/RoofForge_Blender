# RoofForge 0.2.0 — scope and implementation gates

**Working branch:** `feature/0.2.0-arbitrary-contours-live-pitch`  
**Base:** validated user-facing 0.1.0 alpha  
**Target:** Blender 5.0+  
**Status:** implementation in progress

## User-confirmed priorities

1. Support arbitrary **simple** polygon contours: convex, concave, narrow notches, non-uniform edge lengths and arbitrary vertex counts. Self-intersecting contours, zero-length projected edges and multiple independent boundary loops must be diagnosed, not silently repaired.
2. Do not require selecting vertices or edges in Edit Mode. Selecting the mesh object is enough; RoofForge discovers one outer boundary from the mesh topology. A face mesh uses its boundary edges; a wire-only mesh uses its closed wire loop.
3. Give every boundary edge/slope its own pitch angle. Start with a compact list of numeric fields; a numbered top-view pitch map is not in this milestone.
4. Pitch edits trigger a debounced live rebuild. Keep the last valid roof visible until the replacement is built and validated. Coalesce rapid changes; never regenerate inside a UI draw callback.
5. Remove eaves/overhang feature generation from this milestone. Keep only the basic boundary side faces required to close a thickness shell; those are not an overhang or decorative eaves feature.

Everything else in the 1.0 roadmap is deferred: ridge/valley/hip profiles, standing seams, UV, LOD, export, complex material handling and detach/relink.

## Geometry contract

- Calculations remain in source-object local coordinates and retain all XYZ boundary coordinates.
- Each source boundary edge owns one stable slope ID and one pitch angle.
- Its plane must pass through both endpoint vertices and satisfy the requested total inclination. A mathematically incompatible pitch must fail with a clear message; never clamp it silently.
- The output must cover the source polygon exactly within scale-aware tolerances. Internal surface edges must be shared, and each boundary edge must be covered by the generated surface boundary.
- Output facets must retain source-slope identity and be planar. The final thickness shell must pass edge- and vertex-manifold validation.
- For this milestone, "arbitrary contour" means any valid, non-self-intersecting single-loop polygon. Holes and multiple loops are deferred unless they fall out of the boundary model without destabilizing the core.
- The existing weighted wavefront prototype is **not approved for production integration as-is**. The distance-field prototype is also not an acceptable replacement: its transition patches are approximate and its current uniform refinement has poor scaling.

## Performance is a release gate

Do not choose a solver based only on correctness fixtures. The next geometry implementation must be benchmarked before Blender UI integration.

Benchmark separately:
- boundary extraction;
- geometry solver (event generation and topology updates);
- facet assembly / welding / validation;
- Blender mesh datablock creation;
- complete live rebuild.

Use deterministic synthetic inputs at 8, 16, 32, 64 and 128 boundary edges, plus concave adversarial fixtures (L, U, narrow neck, repeated reflex vertices and near-simultaneous events). Record median and p95 wall time over repeated runs, peak triangle/face count and memory where practical. Run the benchmarks on the same CI runner so revisions are comparable.

Optimization requirements:
- no global uniform four-way refinement of the whole polygon at every depth;
- do not rescan every reflex vertex against every edge after every local event if a conservative spatial index or local event invalidation can reduce the candidate set;
- use stable IDs and generation stamps so stale events are discarded cheaply;
- avoid rebuilding/validating unchanged state more than necessary;
- retain deterministic ordering and all geometric/topological validation gates.

Do not invent a latency guarantee before measuring the first valid implementation. Once the baseline is recorded, set explicit preview/final budgets and fail CI on significant regressions.

## Input acquisition already started

The branch now has automatic object-boundary acquisition:
- face meshes use edges incident to exactly one face;
- wire-only meshes use their loose edges;
- one closed connected loop is ordered deterministically;
- mesh selection flags are ignored;
- multiple loops, branches and malformed boundaries are rejected.

Blender background smoke coverage is being expanded for both wire and face meshes in Object and Edit Mode with all mesh elements deselected.

## Acceptance checklist for 0.2.0

- [ ] User-facing generator uses the new general concave solver, not the old convex-only plane envelope.
- [ ] Seeded simple polygon corpus covers convex/concave contours, random vertex positions, clockwise/counter-clockwise winding and mixed positive per-edge pitch.
- [ ] Every accepted input produces complete domain coverage, planar facets, a fully covered outer boundary and a valid closed manifold shell.
- [ ] Invalid/self-intersecting/degenerate inputs fail with actionable diagnostics.
- [ ] Object selection alone is enough to detect the contour, in Object Mode and Edit Mode, on both wire-only and face meshes.
- [ ] Per-edge pitch values remain mapped to the correct source edge after rebuilds.
- [ ] Changing a pitch causes one debounced live update; rapid changes do not queue unbounded builds.
- [ ] A failed update leaves the last valid output unchanged.
- [ ] Performance baselines exist at 8–128 edges; preview and final thresholds are defined from measured results.
- [ ] No overhang/eaves generator, ridge/valley/hip, seam, UV, LOD or export controls are included.
- [ ] Blender 5.0.1 background smoke and official extension package validation pass; manual viewport QA remains a separate gate.

## Current known mathematical risk

The current weighted-wavefront alpha assumes constant-Z eaves and has only constrained support for simultaneous split/collapse and needle events. "All arbitrary 3D contours" is not a safe claim until a generalized formulation for mixed-height eaves is derived and tested. Preserve XYZ in the input model, keep convex cases on the verified existing path where possible, and explicitly reject mixed-height concave cases until the generalized solver is proven. Do not flatten or silently modify user geometry.
