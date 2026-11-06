# RoofForge 1.0 — Technical Specification

**Status:** Draft for implementation  
**Target:** Blender 5.0+  
**Extension ID:** `roof_forge`  
**Repository:** `MorenDord/RoofForge_Blender`  
**Primary users:** 3D environment artists, environment/prop teams, architectural visualization artists

## 1. Product goal

RoofForge generates, edits, validates and prepares production-ready roof meshes from a closed boundary loop. The tool must minimize manual roof construction while preserving predictable topology, non-destructive editing, and explicit artist control.

The 1.0 release prioritizes robust roof geometry, interactive per-slope pitch control, safe live updates/detach, ridge/valley/hip profiles, standing-seam generation, and game-ready output. Dormers, gutters, automatic material authoring and advanced modularization are post-1.0 unless they are required to validate the core architecture.

## 2. Supported input and coordinate model

### 2.1 Input contract
- One mesh object containing exactly one closed, ordered boundary edge loop for the initial MVP.
- Boundary vertices may have different world-space Z values.
- Boundary must be simple in XY projection: no self-intersections, duplicate consecutive vertices, zero-length edges, or zero-area regions.
- Input transforms must be evaluated consistently. All calculations use a documented local/world-space policy; the initial implementation should convert input vertices into roof-local coordinates and preserve the source transform.
- Multiple loops, holes and disconnected islands are explicitly out of scope for the first stable 1.0 milestone, but data structures must not make them impossible later.

### 2.2 Pitch convention
Each boundary edge owns a stable slope ID. Its pitch is the angle above horizontal, expressed in degrees. The corresponding roof plane passes through both endpoints of that edge and rises toward the interior according to the edge's inward horizontal direction. Pitch range must be validated; vertical/degenerate and numerically unstable cases are rejected with actionable messages.

### 2.3 Units
All stored dimensions use Blender scene units. UI labels must display the active unit system. Internal calculations use meters only after a single explicit conversion boundary; avoid mixing raw Blender units and meters.

## 3. Functional requirements

### FR-01 — Boundary acquisition
- Detect and validate one closed edge loop.
- Preserve source object and never destructively modify it.
- Report invalid loop conditions with a specific reason and offending edge/vertex highlight where possible.
- Support different Z heights at boundary vertices.

### FR-02 — Roof surface generation
- Generate a piecewise-planar upper surface from per-edge planes.
- Compute the lower envelope of the plane set clipped to the polygon domain.
- Produce deterministic vertex/face output independent of selection order.
- Preserve planar slope regions and split only where required by intersections or triangulation.
- Reject or explicitly report unsupported/ambiguous cases instead of silently generating corrupt geometry.

### FR-03 — Per-slope pitch UI
- Display a top-view roof diagram with a thin white outline and a number at each slope region.
- Provide a corresponding editable angle field for each stable slope ID.
- Clicking a diagram region selects its field and highlights the region; editing a field highlights its region.
- Include Apply to All, copy/paste pitch, reset, and multi-region editing.
- Slope IDs must survive parameter edits and rebuilds. If boundary topology changes, reconcile IDs using edge identity/geometry and show a review state when mapping is ambiguous.

### FR-04 — Live preview and rebuild
- Provide Preview and Final quality modes.
- Debounce continuous numeric input; do not rebuild on every intermediate event.
- Run expensive geometry generation outside draw callbacks. Use Blender-safe main-thread scheduling for datablock mutation.
- Keep the last valid generated mesh visible until a replacement has passed validation.
- Rebuild only affected subsystems when dependency analysis proves it safe; otherwise perform a full rebuild.
- Show progress/state and useful errors. Never delete the last valid result on a failed rebuild.

### FR-05 — Detach and link lifecycle
- Generate button becomes Detach after successful generation.
- Detach disables all timers, handlers, dependency-graph callbacks and property update callbacks for that roof.
- Detach preserves all generated objects and artist edits.
- Renaming the source or generated root invalidates the live link and freezes the result, without deleting data.
- Save/load must restore valid links safely or mark them detached/needs-relink; no orphaned timer or stale pointer.
- Provide explicit Rebuild, Relink and Detach actions. Relink must preview the proposed source-to-output mapping before committing.

### FR-06 — Roof thickness and eaves
- Thickness direction and meaning must be explicit. 1.0 supports vertical thickness offset; normal offset is a later optional mode.
- Eaves overhang must be geometrically stable at concave and acute corners; invalid offset results must be reported.
- Top and bottom surfaces and boundary walls must form a closed shell when solid output is requested.
- No silent self-intersections or zero-area faces.

### FR-07 — Ridges, valleys and hips
- Detect adjacency between planar roof regions.
- Classify shared boundaries using signed dihedral/normal relationship and region orientation: convex = hip/ridge family; concave = valley family. Classification must be verified in roof-local coordinates and not depend on face winding alone.
- Generate profile geometry from detected shared boundaries using a consistent cross-section sweep or region inset method.
- Profile mesh must be continuous at junctions, with welded vertices and no internal caps at connected nodes.
- Provide independent width, vertical height (default 0.02 scene meters), profile shape, end treatment and enable/disable controls.
- Extrusion direction is global roof-local +Z by default, not surface normal.
- Provide manual edge classification overrides: Ridge, Valley, Hip, Eave, Ignore.
- Allow profile generation on a user-authored roof mesh without requiring RoofForge roof generation.

### FR-08 — Standing seams
- Generate seams per planar slope region with configurable profile, spacing, width, height, start/end offsets and direction.
- Support at minimum a simplified raised seam and a detailed seam profile.
- Clip seams to each slope boundary and terminate them cleanly at ridges, valleys, eaves and openings.
- Offer geometry, curve/instance, and material/normal representation modes where practical.
- Avoid unnecessary geometry for distant/low-detail use.

### FR-09 — Validation
- Validate boundary input, roof regions, generated shell, profiles and seam geometry.
- Detect boundary edges, non-manifold edges/vertices, zero-area faces, duplicate vertices, inverted normals, self-intersections where computationally feasible, and disconnected components.
- Report counts and locations; distinguish warnings from blocking errors.
- Include a one-click Validate Roof operation and optional debug overlays.

### FR-10 — Game-ready preparation
- Generate UVs per slope or continuous where possible; provide UV padding and texel-density controls.
- Preserve material slots and assign material indices by component category.
- Provide deterministic triangulation and optional planar face dissolve/mesh reduction with silhouette-preservation constraints.
- Provide LOD generation (LOD0–LOD2/3) as a separate non-destructive output operation.
- Provide export preparation: apply transforms (opt-in), normals, naming, collision proxy, FBX/glTF export settings.
- Report triangle count, vertex count, material slots, UV map count and estimated output object count.

### FR-11 — Existing-mesh tools
- Analyze a selected mesh and build an edge/face adjacency graph.
- Classify candidate ridge/valley/hip/eave edges.
- Let artists override classification and preview profiles before creating them.
- Create profiles as separate objects by default; never overwrite source geometry.
- Re-run analysis after source topology changes only on explicit user request.

## 4. Non-functional requirements

- Blender 5.0+ Python API compatibility; no reliance on undocumented APIs.
- Deterministic output for identical input/settings.
- No destructive edits to source mesh.
- Last-valid-result preservation on every failed update.
- Undo/Redo-compatible operators and clear datablock ownership.
- No persistent modal operator or unbounded timer polling.
- UI draw code must not perform geometry generation or filesystem work.
- Performance target: simple roofs (<= 16 boundary edges) preview update under 250 ms on a representative workstation; final build target under 1 s excluding high-detail seams. These are targets to benchmark, not guaranteed values.
- Test geometry kernel independently of bpy where possible.
- No external Python dependencies in the installed extension for core functionality.

## 5. Architecture and modules

See [ARCHITECTURE.md](ARCHITECTURE.md). Keep geometry kernel as pure Python/mathutils functions with explicit input/output structures. Blender adapters own datablocks, UI, handlers and operators.

## 6. Acceptance criteria for 1.0

1. Rectangle, convex polygon, L and U test fixtures build without holes or unintended overlaps.
2. Mixed boundary heights and per-edge pitches produce expected plane equations within a documented floating-point tolerance.
3. Concave contours are either correctly supported or rejected with a clear diagnostic; never silently corrupt.
4. All generated regions pass boundary/manifold/degenerate-face validation for supported solid-shell cases.
5. Pitch map labels and fields stay correctly mapped after rebuilds and save/load.
6. Failed preview/final rebuild leaves the last valid roof untouched.
7. Detach stops all automatic changes and preserves user-edited objects.
8. Renaming the linked source/root freezes the result and never deletes it.
9. Ridge/valley/hip profiles connect continuously at tested two-way, three-way and multi-way junction fixtures.
10. Manual roof analysis can classify and generate profiles on a supported planar roof mesh.
11. Seam geometry clips to all tested slope boundaries without protruding or leaving gaps.
12. UV and export preparation produce repeatable output and do not modify the source.
13. Unit tests, Blender background integration tests and manual QA checklist pass on Blender 5.0 and the latest supported Blender minor.

## 7. Explicit non-goals for 1.0
- Automatic architectural interpretation of arbitrary noisy scans.
- Multiple disjoint roof islands and arbitrary holes unless core data model is ready and schedule allows.
- Full dormer/roof-window construction.
- Automatic gutters/downspouts.
- Physically accurate water-flow simulation.
- Automatic material texture authoring.
- Guaranteed quad-only topology for all arbitrary polygon roofs.

## 8. Risk register
- **R1 — Lower-envelope degeneracies:** coincident/near-parallel planes and multi-plane junctions. Mitigation: robust predicates, scale-aware tolerances, deterministic tie-breaking, adversarial fixtures.
- **R2 — Concave polygon handling:** triangulation and clipping can create invalid cells. Mitigation: validate simple polygons, use robust constrained triangulation or reject unsupported conditions.
- **R3 — Profile junction topology:** independently swept segments create internal caps and non-manifold junctions. Mitigation: build a shared junction graph and solve node patches as a separate stage.
- **R4 — Live update lifecycle:** stale callbacks/timers can mutate detached objects. Mitigation: per-roof UUID, generation token, explicit unregister, validity checks before every callback.
- **R5 — Blender API drift:** property/UI/mesh API changes. Mitigation: compatibility layer and automated smoke tests per supported Blender version.
- **R6 — Performance:** full rebuilds on every field edit. Mitigation: debounce, preview quality, dependency graph and caching with strict invalidation.
- **R7 — UV/LOD scope:** too much secondary functionality before core stability. Mitigation: gate behind core geometry release criteria.

## 9. Delivery gates
- **Alpha:** modular extension loads; boundary validation; deterministic roof kernel; core tests.
- **Beta:** interactive pitch map; safe live rebuild/detach; solid shell; validation overlays.
- **RC:** ridge/valley/hip profiles; seams; manual roof analysis; Blender integration QA.
- **1.0:** UV, material assignment, optimization/export baseline; documentation; clean install/upgrade; all release gates pass.
