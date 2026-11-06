# RoofForge 1.0 — Architecture

## Design principles
1. Separate pure geometry from Blender UI and datablock operations.
2. Keep source meshes immutable.
3. Use stable IDs, not list indices or object names, as the primary identity of slopes and generated parts.
4. Build new output in temporary datablocks, validate it, then atomically swap it into the scene.
5. Every live link has an explicit lifecycle and generation token.
6. Prefer deterministic algorithms and scale-aware tolerances.

## Package layout

```text
roof_forge/
  blender_manifest.toml
  __init__.py
  addon/
    registration.py
    properties.py
    operators/
      generate.py
      rebuild.py
      detach.py
      validate.py
      analyze_existing.py
      profiles.py
      export.py
    ui/
      panel.py
      pitch_map.py
      draw_helpers.py
      state.py
    handlers/
      lifecycle.py
      live_update.py
      depsgraph.py
    adapters/
      mesh_io.py
      object_registry.py
      collections.py
      units.py
  core/
    model.py
    ids.py
    validation.py
    polygon2d.py
    triangulation.py
    planes.py
    envelope.py
    topology.py
    shell.py
    adjacency.py
    classification.py
    profiles.py
    seams.py
    uv.py
    optimization.py
    lod.py
  tests/
    fixtures/
    test_polygon2d.py
    test_planes.py
    test_envelope.py
    test_topology.py
    test_profiles.py
    blender/
      smoke_test.py
docs/
  SPECIFICATION.md
  ARCHITECTURE.md
  ROADMAP.md
```

## Data flow

1. **Acquire:** adapter reads one source boundary loop into immutable `RoofInput`.
2. **Validate input:** polygon simplicity, edge lengths, winding, coordinate scale and pitch values.
3. **Build planes:** one plane per boundary edge, identified by persistent `slope_id`.
4. **Partition:** clip the domain by pairwise plane equality half-planes; each region is where its plane is the lower envelope. Use a robust 2D polygon clipping strategy; do not rely on arbitrary face inset or XY-only welding.
5. **Assemble surface:** create shared vertices from quantized/clustered XYZ with scale-aware tolerance, preserving exact plane constraints. Resolve multi-plane nodes deterministically.
6. **Shell:** create bottom surface and boundary walls. Validate before commit.
7. **Features:** derive adjacency graph from final roof regions; classify shared edges; generate ridge/valley/hip profiles and seams as dependent feature meshes.
8. **Validate output:** manifold, degeneracy, normal, intersection and continuity checks.
9. **Commit:** swap temporary output to scene only if valid; otherwise keep last-valid output.
10. **Lifecycle:** attach metadata UUIDs and generation tokens; register only the required callbacks; detach removes all callbacks and invalidates tokens.

## Core data structures

- `RoofInput`: source UUID, local transform, ordered boundary points, stable boundary edge IDs, unit scale.
- `SlopeSpec`: slope UUID, boundary edge UUID, pitch radians/degrees, plane coefficients.
- `RoofRegion`: slope UUID, ordered 3D boundary vertices, 2D polygon, adjacency references.
- `RoofBuildSettings`: overhang, thickness, quality, tolerance policy.
- `FeatureGraph`: nodes and shared region boundaries with semantic type.
- `GeneratedPart`: stable part UUID, type, source UUID, mesh payload, dependency signature.
- `BuildResult`: meshes, diagnostics, statistics, dependency signature.

## Algorithms

### A. Lower envelope
For plane i, represent height as z_i(x,y)=a_i x+b_i y+c_i. For each candidate region i, start with the roof domain polygon and clip it against every inequality z_i <= z_j + eps. Each inequality is a 2D half-plane. The surviving polygon is the region where plane i is lowest. Empty regions are discarded. Coincident planes require deterministic ownership and diagnostics. Use adaptive eps based on bounding-box scale.

### B. Concave domain
Validate polygon simplicity first. Triangulate with a constrained polygon triangulator and clip each triangle or use a robust polygon library only if it can be shipped without dependency risk. Merge resulting coplanar cells by slope ID while preserving shared boundaries. Do not use unconstrained fan triangulation for concave shapes.

### C. Shared topology
Build a vertex registry keyed by 3D position with scale-aware tolerance and plane-membership metadata. Never merge solely by XY. At multi-plane intersections, solve/verify all participating plane equations and choose a canonical coordinate. Record any merge that exceeds tolerance as an error.

### D. Feature classification
Build a region adjacency graph. For each shared boundary, compare oriented region normals and interior-side relationship. Classify convex and concave junctions with signed dihedral angle in roof-local frame. Boundary edges are eaves unless overridden. Manual overrides take precedence and are stored by stable edge/feature IDs.

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
- Pure unit tests for 2D predicates, clipping, plane intersections, lower envelope and stable IDs.
- Property-based/random polygon tests with seeded reproducibility.
- Golden fixtures: rectangle, convex pentagon, L, U, narrow notch, acute corner, different boundary Z, mixed pitch, parallel planes, coincident planes.
- Topology tests: manifold shell, shared ridge, valley, hip, three-way and four-way junctions.
- Blender background tests for registration, save/reopen, live update, detach, rename invalidation, undo/redo and export.
- Performance benchmarks at 4, 8, 16, 32 and 64 boundary edges.
