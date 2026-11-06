# RoofForge

Procedural roof generation for Blender 5.0+, designed for environment artists and game-ready asset workflows.

> **Test build:** 0.1.0 alpha. The current Blender UI supports one selected closed edge loop, one pitch value shared by all edges, validation, and a separate closed shell. It is not yet a parametric roof editor. A Blender 5.0.1 background smoke test is included in CI; interactive GUI behavior still needs user verification.

## Project documents
- Technical specification: docs/SPECIFICATION.md
- Architecture: docs/ARCHITECTURE.md
- Development roadmap: docs/ROADMAP.md
- Session handoff / restart instructions: docs/SESSION_HANDOFF.md

## Current implementation
- Blender Extension manifest, registration scaffold and 3D View sidebar panel.
- Edit Mode and Object Mode selected closed-edge-loop adapter, preserving local XYZ.
- 3D slope plane construction from pitch angle, eave edge grade and polygon winding.
- Deterministic ear clipping and an experimental concave-domain arrangement (production path rejects discontinuities).
- Experimental finite-segment distance field for continuous closed L/U comparison meshes; corner transitions are approximated and are not the production planar-facet solver.
- Lower-envelope roof surface assembly, 3D vertex welding and projected domain-coverage validation.
- Closed roof shell for contours whose upper surface is continuous, with thickness extruded along roof-local global -Z.
- Separate FACE attributes for top/bottom/eave-wall categories and source slope IDs.
- Closed-mesh validator for edge incidence, face winding, connected components and vertex links.
- Weighted wavefront alpha for constant-height eaves: global multi-loop event stepping, tested split/collapse fixtures, L/U cross-needle nodes and welded RoofSurface assembly. This is not connected to the Blender UI.
- Pure-Python end-to-end geometry fixtures for rectangle, V-notch, constrained L/U shapes and selected asymmetric event cases.

## Test build installation
Download the roof_forge-0.1.0.zip artifact from the latest successful **RoofForge tests** workflow, then install it using Preferences → Get Extensions → Install from Disk. Do not use the repository ZIP: it contains development files and legacy archives. Russian installation and QA steps are included in INSTALL_TEST_RU.md inside the extension package.

The generated object is separate from the source and inherits its world transform. The source mesh is not modified.

## Run pure Python tests
From the repository root:

    python -m compileall -q core addon __init__.py
    python -m unittest discover -s tests -v

## Not implemented yet
- Per-slope pitch map and separate pitch values (the current test UI uses one global pitch).
- Live Update and Detach currently remain future product goals, not implemented in this build.
- Eaves overhang, fascia and soffit.
- Per-slope interactive pitch map and independent slope values.
- Live update, detach, relink and lifecycle handlers.
- Ridge, valley and hip profiles and junction patches.
- Standing seams, UVs, material assignment, LOD and export automation.
- Geometric self-intersection detection and its Blender UI diagnostics.

## Known geometry limitations
- Input must be one simple closed loop in XY.
- Collinear contour vertices and projected-vertical edges are rejected.
- The production Blender operator still uses the existing plane/envelope path. The weighted wavefront path is a separate pure-Python alpha and has not been connected to the UI. Do not treat L/U solver tests as proof of concave Blender generation.
- The current 2D wavefront path requires a constant-Z eave loop. Mixed-height eaves require another formulation. `docs/CONCAVE_GEOMETRY.md` records the algorithm state and remaining event classes.
- Pure geometry has unit coverage. Blender 5.0.1 background checks cover registration, Object Mode/Edit Mode boundary reads, validation and shell creation; manual interactive GUI QA is still required.
- Non-uniform object scale can change world-space pitch because geometry is generated in source-local coordinates; apply scale before generation for predictable world-space pitch.

## Development principles
- Source geometry is immutable.
- Build and validate output before linking it into the scene.
- Stable slope indices/UUIDs identify generated regions.
- Pure geometry code must be testable outside Blender.
- Blender datablock changes happen on Blender's main thread.

## License
GPL-3.0-or-later.
