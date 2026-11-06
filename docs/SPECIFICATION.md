# RoofForge 1.0 — Technical Specification

**Status:** Draft for implementation  
**Target:** Blender 5.0+  
**Extension ID:** roof_forge  
**Repository:** MorenDord/RoofForge_Blender  
**Primary users:** 3D environment artists, environment/prop teams, architectural visualization artists

## 1. Product goal

RoofForge generates, edits, validates and prepares production-ready roof meshes from a closed boundary loop. The tool must minimize manual roof construction while preserving predictable topology, non-destructive editing, and explicit artist control.

The 1.0 release prioritizes robust roof geometry, interactive per-slope pitch control, safe live updates/detach, ridge/valley/hip profiles, standing-seam generation, and game-ready output. Dormers, gutters, automatic material authoring and advanced modularization are post-1.0 unless required to validate the core architecture.

## 2. Supported input and coordinate model

### 2.1 Input contract
- One mesh object containing exactly one selected closed edge loop for the initial MVP.
- Boundary vertices may have different local-space Z values.
- Boundary must be simple in XY projection: no self-intersections, duplicate consecutive vertices, zero-length projected edges, or zero-area regions.
- Calculations use source-object local coordinates; the generated object inherits the source world transform.
- A boundary edge with effectively zero XY projection is rejected because a single-valued surface z=f(x,y) cannot contain a vertical projected edge.
- Holes, multiple loops and disconnected islands are out of scope for the first stable 1.0 milestone.

### 2.2 Pitch convention and 3D edge planes
Each ordered boundary edge owns a stable slope ID. Pitch is the total plane inclination above horizontal, in degrees. For edge endpoints P0 and P1:
- L is the length of the edge's XY projection.
- t is the unit tangent of the edge in XY.
- n_in is the unit horizontal inward normal determined from polygon winding.
- g_t = (z1-z0)/L is the slope already present along the eave.
- g_n = sqrt(tan(pitch)^2 - g_t^2) is the remaining inward gradient.

The plane gradient is g = g_t*t + g_n*n_in and the plane is z=ax+by+c. This preserves both endpoint heights and the requested total inclination. If tan(pitch)^2 is smaller than g_t^2, the requested pitch is mathematically incompatible with the eave grade and generation must stop with a clear diagnostic. The tool must never silently clamp the requested pitch.

### 2.3 Units
All stored dimensions use Blender scene units. UI labels must display the active unit system. Core geometry is unit-agnostic; conversion to meters belongs at the Blender adapter boundary only.

## 3. Functional requirements

### FR-01 — Boundary acquisition
- Detect and validate exactly one selected closed edge loop in Edit Mode or Object Mode.
- Preserve source object and never destructively modify it.
- Report invalid loop conditions with a specific reason and offending edge/vertex highlight where possible.
- Preserve XYZ coordinates, not only XY.

### FR-02 — Roof surface generation
- Generate a piecewise-planar upper surface from per-edge planes.
- For convex polygons, compute the lower envelope over the polygon domain.
- For concave polygons, use a weighted straight-skeleton/wavefront construction with edge-collapse, split, parallel-edge and simultaneous-event handling. Each active boundary edge sweeps a planar roof face whose pitch is controlled by its per-edge wavefront speed. See `docs/CONCAVE_GEOMETRY.md`.
- Produce deterministic vertex/face output and weld numerically coincident 3D vertices using scale-aware tolerance.
- Verify XY coverage against the source polygon area.
- Verify that all internal surface edges are shared; single-use edges must lie on the source perimeter and fully cover each perimeter segment.
- Reject unsupported or ambiguous cases instead of silently generating corrupt geometry. The current supporting-line arrangement and finite-segment distance field are experimental only; neither qualifies as the production concave solver. Concave + mixed-height eaves must be rejected until a separate generalized formulation is validated.

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
- Thickness is applied as a constant translation along roof-local -Z, not along face normals.
- Side walls may be created only along validated source-perimeter edges; internal cracks must not be capped as walls.
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
- Detect boundary edges, non-manifold edges/vertices (including disconnected vertex links), zero-area faces, duplicate faces, inconsistent face winding, inverted normals, self-intersections where computationally feasible, and disconnected components.
- Report counts and locations; distinguish warnings from blocking errors.
- Include a one-click Validate Roof operation that runs the same complete surface/shell pipeline as Create Roof without committing output, plus optional debug overlays.

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
- Performance targets must be benchmarked on representative hardware; they are not release guarantees until measured.
- Test geometry kernel independently of bpy where possible.
- No external Python dependencies in the installed extension for core functionality.

## 5. Architecture and algorithms
See `ARCHITECTURE.md` and `CONCAVE_GEOMETRY.md`. The core is independent of bpy. Plane generation, wavefront/skeleton construction, face assembly and Blender datablock creation are separate stages.

## 6. Acceptance criteria for 1.0
1. Rectangle, convex polygon, L and U fixtures build without holes or unintended overlaps.
2. Mixed boundary heights and per-edge pitches produce expected plane equations within a documented floating-point tolerance.
3. Concave contours are correctly supported or rejected with a clear diagnostic; never silently corrupted.
4. Generated closed shells pass manifold and degenerate-face validation.
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
- **R2 — Concave roof continuity:** halfspace-restricted plane sets can switch across artificial lines; global plane envelopes can undercut concave eaves. Mitigation: keep both experimental paths out of production; implement weighted straight-skeleton events and validate every resulting facet. Weighted events and simultaneous/parallel degeneracies need explicit handling.
- **R3 — Shared topology:** tolerance welding can still merge or miss points near degeneracies. Mitigation: plane-membership checks, multi-plane node solving, adversarial tests.
- **R4 — Profile junction topology:** independently swept segments create internal caps and non-manifold junctions. Mitigation: shared junction graph and separate node-patch solver.
- **R5 — Live update lifecycle:** stale callbacks/timers can mutate detached objects. Mitigation: per-roof UUID, generation token, explicit unregister, validity checks before every callback.
- **R6 — Blender API drift:** property/UI/mesh API changes. Mitigation: compatibility layer and automated smoke tests per supported Blender version.
- **R7 — UV/LOD scope:** secondary features can delay core stability. Mitigation: gate behind core geometry release criteria.

## 9. Delivery gates
- **Alpha:** modular extension loads; boundary validation; deterministic convex roof surface; validated vertical-Z shell; pure geometry tests. Concave production geometry remains gated on the weighted wavefront solver; experimental comparison output is not a release feature.
- **Beta:** interactive pitch map; safe live rebuild/detach; solid shell; validation overlays.
- **RC:** ridge/valley/hip profiles; seams; manual roof analysis; Blender integration QA.
- **1.0:** UV, material assignment, optimization/export baseline; documentation; clean install/upgrade; all release gates pass.
