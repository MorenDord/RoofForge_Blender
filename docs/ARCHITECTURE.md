# RoofForge 1.0 — Architecture

## Design principles
1. Separate pure geometry from Blender UI and datablock operations.
2. Keep source meshes immutable.
3. Use stable IDs, not list indices or object names, as the primary identity of slopes and generated parts.
4. Build new output in temporary datablocks, validate it, then atomically swap it into the scene.
5. Every live link has an explicit lifecycle and generation token.
6. Prefer deterministic algorithms and scale-aware tolerances.

## Package layout

- addon/registration.py, properties.py
- addon/operators/generate.py, validate.py, rebuild.py, detach.py, analyze_existing.py, profiles.py, export.py
- addon/ui/panel.py, pitch_map.py, draw_helpers.py, state.py
- addon/handlers/lifecycle.py, live_update.py, depsgraph.py
- addon/adapters/mesh_io.py, object_registry.py, collections.py, units.py
- core/geometry.py — predicates, clipping, plane primitives and shared math
- core/planes.py — boundary-edge plane generation and active-halfspace checks
- core/envelope.py — convex and concave lower-envelope partition
- core/mesh.py — welded mesh payload assembly, projected coverage and outer-boundary continuity checks
- core/shell.py — closed shell construction by global roof-local -Z extrusion
- core/validation.py — edge incidence, face winding, connected-component and vertex-link validation
- core/model.py, ids.py, adjacency.py, classification.py, profiles.py, seams.py, uv.py, optimization.py, lod.py
- tests/ — pure Python fixtures and Blender background integration tests

## Data flow

1. Acquire: adapter reads one source boundary loop into ordered XYZ tuples in source-local coordinates.
2. Validate: polygon simplicity, edge lengths, winding, projected vertical edges and pitch compatibility.
3. Build planes: one plane per boundary edge, identified by a stable slope index/UUID at the model layer.
4. Convex partition: clip the domain by pairwise plane equality halfplanes.
5. Concave partition: ear-clip the simple polygon; split each triangle by all source-edge supporting lines; determine the active inward-halfspace planes per convex arrangement cell; calculate a lower envelope only among active planes.
6. Assemble surface: evaluate Z from the owning plane, weld numerically coincident XYZ vertices with a scale-aware spatial hash, and store the slope index as face metadata.
7. Validate surface: compare projected face area with the source polygon, then require every single-use edge to lie on one source boundary segment and require complete edge-chain coverage. Internal open edges are blocking errors.
8. Shell: duplicate the upper-surface vertices at z-thickness, reverse bottom face winding, create side walls only along validated source-boundary edges, and require every final undirected edge to have exactly two incident faces.
9. Closed-mesh validation: verify valid face indices, non-zero face area, duplicate faces, opposite edge use, one connected component and a single cyclic link around every vertex. The cyclic-link check detects bow-tie vertices that edge counts miss.
10. Features: derive adjacency graph from roof regions; classify shared edges; generate ridge/valley/hip profiles and seams as dependent feature meshes.
11. Validate output and commit temporary datablocks only after success.
12. Lifecycle: attach metadata UUIDs and generation tokens; detach removes all callbacks and invalidates tokens.

## Core data structures
- RoofInput: source UUID, local transform, ordered boundary points, stable boundary edge IDs, unit scale.
- SlopeSpec: slope UUID, boundary edge UUID, pitch degrees, plane coefficients.
- RoofRegion: slope UUID, ordered 3D boundary vertices, 2D polygon, adjacency references.
- RoofSurface: welded XYZ vertex list, polygon index lists, face-to-slope indices, source/surface projected areas and source XY boundary.
- RoofShell: top/bottom/side face payload, component counts and vertical thickness.
- RoofBuildSettings: overhang, thickness, quality, tolerance policy.
- FeatureGraph: nodes and shared region boundaries with semantic type.
- GeneratedPart: stable part UUID, type, source UUID, mesh payload, dependency signature.
- BuildResult: meshes, diagnostics, statistics, dependency signature.

## Geometry algorithms

### A. Plane from a 3D boundary edge
Given edge endpoints P0 and P1, projected XY edge length L, unit tangent t, inward unit normal n, and edge grade g_t=(z1-z0)/L, require plane gradient magnitude |g|=tan(pitch). The remaining inward component is g_n=sqrt(tan(pitch)^2-g_t^2), and g=g_t*t+g_n*n. This exactly preserves both endpoints. If the radicand is negative, the requested pitch is incompatible with the existing eave grade and the build is rejected.

### B. Lower envelope for convex contours
Represent each plane as z_i(x,y)=a_i*x+b_i*y+c_i. For candidate plane i, clip the domain by every inequality z_i<=z_j. Coincident planes are assigned to the earliest stable input index so they do not duplicate the same region.

### C. Concave contours and finite plane domains
An infinite extension of a concave edge plane may cut across remote parts of the polygon. The current experimental approach ear-clips the contour, splits triangles by source-edge supporting lines, and computes a lower envelope among locally active planes. This can create discontinuities along artificial arrangement boundaries. The mesh validator therefore rejects any resulting internal open edge instead of capping it. Continuous L/U support requires a stronger finite-face-domain and junction solver; do not mark concave roofs supported merely because their projected cell areas sum correctly.

### D. Shared topology
Build a vertex registry keyed by 3D position with scale-aware tolerance. Never merge solely by XY. The current registry uses a 3D spatial hash; face area and boundary-chain continuity checks guard the result. A full multi-plane node solver and plane-membership constraints are still required for release quality.

### E. Profile construction
Generate profile strips from the shared boundary graph, not isolated per-edge solids. Each edge has a cross-section profile. At nodes, solve a junction patch that trims/joins incident strips; remove internal caps and weld compatible vertices. Default extrusion/rise vector is roof-local +Z. Profile generation is transactional and separate from roof generation.

### F. Live rebuild
Property updates enqueue a dirty-set with a debounce interval. A per-roof token cancels stale queued work. Build into temporary mesh data, validate, then swap. Detach increments token, unregisters timers/handlers, clears pending work and freezes current objects. Rename or missing source invalidates link and transitions to FROZEN with reason.

## Blender adapter boundaries
- All bpy/bmesh operations live in addon/adapters or operators.
- UI draw functions only read cached state and draw controls.
- Timer callbacks validate UUID/token and scene membership before work.
- No geometry generation inside draw callbacks.
- Register/unregister is idempotent and removes all callbacks/properties.
- Persist UUIDs and settings as Blender ID properties or PropertyGroups; do not persist raw Python pointers.

## Test strategy
- Pure unit tests for 2D predicates, clipping, plane construction, restricted envelopes, vertex welding and surface coverage.
- Seeded random simple polygon tests and adversarial polygons.
- Golden fixtures: rectangle, convex pentagon, L, U, narrow notch, acute corner, different boundary Z, mixed pitch, parallel planes and coincident planes.
- Topology tests: manifold shell, shared ridge, valley, hip, three-way and four-way junctions.
- Blender background tests for registration, save/reopen, live update, detach, rename invalidation, undo/redo and export.
- Performance benchmarks at 4, 8, 16, 32 and 64 boundary edges.
