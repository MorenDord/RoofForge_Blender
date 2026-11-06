# RoofForge 1.0 — Development Roadmap

## Current implementation state
The initial geometry vertical slice builds a closed shell for a verified rectangular fixture. The weighted wavefront alpha now advances multiple loops, handles a strict reflex split, tested L/U cross-needle terminals, and one constrained same-loop simultaneous split-plus-collapse topology. In that compound event, the split partitions the target front; a validated terminal partial segment becomes a skeleton arc while the surviving child loop continues. It validates finite needle segments and explicitly rejects unsupported partial-overlap terminal configurations. End-to-end shells pass for rectangle, V-notch (including unequal pitches), L and U fixtures and two constrained asymmetric L split/collapse cases. CW winding and nonzero constant eave height are also covered. Pure-Python CI passes 61 tests on Python 3.11 and 3.13. Blender 5.0 runtime validation remains pending.

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
- [x] Experimental concave arrangement partition (rejected for production due internal discontinuities)
- [x] Experimental finite-segment distance field builds continuous closed L/U comparison meshes (corner transitions approximated; not a production roof solver)
- [x] Weighted moving-line kinematics with per-edge pitch speeds for constant-Z eaves
- [x] Convex edge-collapse simulation, rectangle needle and simultaneous point fixtures
- [x] Reflex split-candidate detection against finite active edge segments
- [x] Deterministic event queue with same-time batching and stale edge/loop generation filtering
- [x] Pure single-loop split operation: duplicate target edge identity and create two validated child loops
- [x] Global multi-loop event scheduler and earliest-event stepping
- [x] Swept facet-fragment and skeleton-arc collection
- [x] Single reflex split with child-loop replacement and stale event invalidation
- [x] Tested L/U cross-needle terminal events with unequal opposing speeds when finite segments coincide exactly at the event height
- [x] Restricted same-loop simultaneous strict split + one edge-collapse resolver; validates child topology transactionally and permits the resulting terminal partial needle only when its event endpoints lie on both coincident fronts
- [x] Finite-segment endpoint validation for ordinary two-front needle termination; reject partial overlap rather than misclassifying it as a full needle
- [x] T-junction conformance and welded facet assembly into RoofSurface
- [ ] Complete weighted straight-skeleton solver for arbitrary concave contours and all simultaneous/parallel event classes
- [ ] General partial-overlap opposing-front resolver, including multiple overlap intervals and surviving tails not represented by the constrained split/collapse fixture
- [ ] Sequential near-simultaneous split/collapse cases where the events are distinct in time and topology changes between them
- [ ] Multiple independent splits on one loop, nested split sequences and higher-order vertex-event resolution
- [x] 3D vertex welding and face-to-slope metadata
- [x] Projected domain coverage check and >2-face edge guard
- [x] Surface boundary-chain check: internal open edges are rejected
- [x] Closed solid shell for the verified rectangle fixture; thickness extrudes along roof-local -Z
- [x] Planar L/U alpha fixtures with equal pitch pass closed-shell manifold tests
- [ ] General L/U support for arbitrary per-edge pitch assignments and degenerate event ordering
- [ ] Generalized concave solver for mixed-height eaves
- [x] Closed-mesh edge/vertex-link validator (boundary edges, edge incidence, winding, connected components, bow-tie vertices)
- [ ] Geometric self-intersection detection and zero-area diagnostics integrated into the Blender UI
- [ ] Robust handling of collinear and near-degenerate contour vertices
- [ ] Multi-plane node solver and adversarial precision suite
- [ ] Eaves overhang, fascia and soffit
**Exit:** verified rectangle, V-notch, equal-pitch L/U alpha fixtures pass pure-Python area, boundary and edge/vertex manifold checks. Arbitrary concave event coverage, self-intersection checks and Blender integration tests remain open.

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
Extend same-loop topology handling beyond the verified one-split/one-collapse batch. First cover two independently timed events after a topology change and prove that newly scheduled candidates—not stale pre-split candidates—control the next step. Then support multiple independent splits on one loop and generic partial-overlap needle segments with explicit surviving-tail topology. Keep exact source-plane, coverage, boundary-chain, T-junction and closed-shell manifold checks. Treat sub-tolerance sliver faces as rejected geometry, not as a reason to weaken validation. Keep mixed-height eaves out of this solver and do not connect it to Blender until the broader event suite passes.
