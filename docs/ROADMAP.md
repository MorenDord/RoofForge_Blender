# RoofForge 1.0 — Development Roadmap

## Current implementation state
The initial surface-generation vertical slice is on branch develop. Pure-Python tests cover plane construction and open-surface generation for rectangle, L and U fixtures. The Blender operator and UI entry point are scaffolded but still need runtime validation in Blender 5.0.

## Milestone 0 — Repository and engineering foundation
- [x] Modular Blender extension package and manifest
- [x] CI workflow for syntax checks and pure Python tests
- [x] Versioned specification, architecture and roadmap
**Exit:** clean install/enable/disable in Blender 5.0; no registration leaks. Not yet verified.

## Milestone 1 — Geometry kernel alpha (Critical)
- [x] Selected closed-loop acquisition in Edit/Object Mode (adapter implemented; Blender test pending)
- [x] Simple XY contour validation and winding detection
- [x] Plane construction from ordered 3D boundary edges and per-edge pitch values
- [x] Deterministic ear-clipping for simple concave contours without collinear vertices
- [x] Restricted lower-envelope partition for concave contours
- [x] 3D vertex welding and face-to-slope metadata
- [x] Projected domain coverage check and >2-face edge guard
- [ ] Full boundary-loop and non-manifold vertex validator
- [ ] Robust handling of collinear and near-degenerate contour vertices
- [ ] Multi-plane node solver and adversarial precision suite
- [ ] Closed solid shell with thickness and eaves
**Exit:** supported fixtures pass unit and Blender integration tests; closed-shell output is manifold.

## Milestone 2 — Artist workflow (Critical)
- [ ] Numbered top-view pitch map
- [ ] Stable per-slope property fields and multi-select pitch editing
- [ ] Preview/final quality modes and debounce
- [ ] Transactional rebuild preserving last valid output
- [ ] Detach, relink, rename invalidation, save/load lifecycle
**Exit:** edits never destroy last-valid geometry; detached assets never update.

## Milestone 3 — Feature graph and profiles (Critical)
- [ ] Region adjacency graph
- [ ] Convex/concave classification and manual overrides
- [ ] Ridge, valley and hip profile cross-sections
- [ ] Multi-way junction patch generation
- [ ] Existing mesh analysis and profile preview
**Exit:** continuous profile meshes pass node continuity and manifold tests on fixture suite.

## Milestone 4 — Standing seams (High)
- [ ] Seam layout per slope
- [ ] Simplified and detailed profiles
- [ ] Boundary clipping and clean terminations
- [ ] Geometry/curve representation and detail presets
**Exit:** no seam overhangs/gaps on supported roof fixtures; predictable triangle budget.

## Milestone 5 — Game-ready output (High)
- [ ] UV generation and texel-density checks
- [ ] Material assignment by part type
- [ ] Planar optimization and deterministic triangulation
- [ ] LOD0–LOD2 baseline
- [ ] Collision proxy and export preparation
**Exit:** repeatable FBX/glTF export tests; source remains unchanged.

## Milestone 6 — Release hardening
- [ ] Full regression and performance benchmarks
- [ ] Blender 5.0 clean install/update/uninstall QA
- [ ] User documentation and example files
- [ ] Known limitations and migration notes
- [ ] 1.0 release candidate and signed release notes
**Exit:** all acceptance criteria in SPECIFICATION.md met or explicitly deferred with documented limitation.

## Next implementation task
Close the geometry alpha gate by adding a boundary/manifold validator, stress tests for near-degenerate intersections and a watertight thickness/eaves builder. Do not begin the pitch-map UI until the geometry core can produce a closed shell reliably.
