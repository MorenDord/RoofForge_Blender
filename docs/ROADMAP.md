# RoofForge 1.0 — Development Roadmap

## Milestone 0 — Repository and engineering foundation
- [ ] Modular Blender extension package and manifest
- [ ] CI: syntax/import checks and pure Python tests
- [ ] Versioned specification, architecture and contribution guide
- [ ] Baseline regression fixtures from the 0.3 prototype
**Exit:** clean install/enable/disable in Blender 5.0; no registration leaks.

## Milestone 1 — Geometry kernel alpha (Critical)
- [ ] Immutable input model and stable UUIDs
- [ ] Robust boundary validation and diagnostics
- [ ] Plane construction from arbitrary 3D boundary edges
- [ ] Scale-aware 2D half-plane clipping
- [ ] Lower-envelope partition and deterministic shared vertices
- [ ] Concave polygon support with constrained triangulation
- [ ] Solid shell and topology validator
**Exit:** supported fixtures pass unit and Blender integration tests; no known open/non-manifold edges in closed-shell output.

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

## Initial issue candidates
1. Define stable slope identity and source-boundary fingerprint.
2. Implement scale-aware geometry tolerance policy.
3. Implement robust polygon simplicity validation and constrained triangulation.
4. Implement lower-envelope clipping with degeneracy diagnostics.
5. Build deterministic shared vertex registry.
6. Add shell manifold validator.
7. Implement transactional output swap.
8. Implement timer/handler lifecycle manager.
