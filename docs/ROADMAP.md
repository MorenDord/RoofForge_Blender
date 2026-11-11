# RoofForge 1.0 — Development Roadmap

## Current implementation state
RoofForge 0.3.9 is the current test build for Blender 5.0+. The add-on generates a closed roof shell from one ordered boundary loop, supports per-edge pitch and live rebuild, and uses the weighted wavefront for tested flat-eave concave fixtures. Positive concave overhang is available on supported L/U contours through planar edge strips; mixed-height concave eaves and unsupported weighted event batches are rejected. Version 0.3.9 adds a geometric intersection check between non-adjacent face triangles. Blender 5.0.1 background smoke, pure-Python CI, package validation and the extension ZIP are the release gates; interactive GUI visual QA remains a user-side check.

## Milestone 0 — Repository and engineering foundation
- [x] Modular Blender extension package and manifest
- [x] CI workflow for syntax checks and pure Python tests
- [x] Versioned specification, architecture and roadmap
**Exit:** clean install/enable/disable through Blender Preferences and visual panel QA in Blender 5.0+. Background registration/unregistration has passed on 5.0.1; manual GUI installation remains unverified.

## Milestone 0.5 — Testable alpha package
- [x] Versioned extension manifest (0.1.0, Blender 5.0.0 minimum)
- [x] Clean extension ZIP includes only manifest, entry point, addon/core sources and Russian test instructions
- [x] Blender 5.0.1 background smoke: Object Mode and Edit Mode input, Validate, Create Roof Shell, source preservation and registration lifecycle
- [x] Official Blender 5.0.1 extension ZIP validation
- [x] SHA256 sidecar and GitHub Actions artifact upload
- [ ] User's manual Install from Disk, viewport panel and visual geometry QA
**Exit:** user confirms the test extension installs and the rectangle/convex-contour workflow behaves as expected in the interactive Blender UI.

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
- [x] End-to-end distinct-time continuation in both L event orders; after compound topology mutation the next event is later than the batching tolerance and references only the live child-loop generation and active edge instances
- [x] Finite-segment endpoint validation for ordinary two-front needle termination; reject partial overlap rather than misclassifying it as a full needle
- [x] T-junction conformance and welded facet assembly into RoofSurface
- [ ] Complete weighted straight-skeleton solver for arbitrary concave contours and all simultaneous/parallel event classes
- [ ] General partial-overlap opposing-front resolver, including multiple overlap intervals and surviving tails not represented by the constrained split/collapse fixture
- [ ] Multiple independent splits on one loop, nested split sequences and higher-order vertex-event resolution
- [x] 3D vertex welding and face-to-slope metadata
- [x] Projected domain coverage check and >2-face edge guard
- [x] Surface boundary-chain check: internal open edges are rejected
- [x] Closed solid shell for the verified rectangle fixture; thickness extrudes along roof-local -Z
- [x] Planar L/U alpha fixtures with equal pitch pass closed-shell manifold tests
- [ ] General L/U support for arbitrary per-edge pitch assignments and degenerate event ordering
- [ ] Generalized concave solver for mixed-height eaves
- [x] Closed-mesh edge/vertex-link validator (boundary edges, edge incidence, winding, connected components, bow-tie vertices)
- [x] Geometric self-intersection detection between non-adjacent face triangles and zero-area diagnostics propagated through the Blender generation operator
- [ ] Robust handling of collinear and near-degenerate contour vertices
- [ ] Multi-plane node solver and adversarial precision suite
- [ ] Eaves overhang, fascia and soffit
**Exit:** verified rectangle, V-notch and supported L/U fixtures pass pure-Python area, boundary, edge/vertex manifold and non-adjacent triangle-intersection checks. Arbitrary concave event coverage and mixed-height concave roofs remain open.

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
Next critical geometry tasks: general partial-overlap opposing-front resolution and multiple independent split events on one loop. Keep unsupported weighted-wavefront event batches explicit and preserve every current exact plane, projected-area, boundary-chain, T-junction, face-area, manifold and self-intersection guard. After that, improve collinear/near-degenerate contour handling and extend Blender diagnostics where possible.
