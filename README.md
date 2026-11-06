# RoofForge

Procedural roof generation for Blender 5.0+, designed for environment artists and game-ready asset workflows.

> **Development status:** early 1.0 alpha. The current code generates a closed shell from one selected closed edge loop. It is not yet a complete parametric roof editor and has not yet been runtime-tested in Blender 5.0.

## Project documents
- Technical specification: docs/SPECIFICATION.md
- Architecture: docs/ARCHITECTURE.md
- Development roadmap: docs/ROADMAP.md

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
- Unit tests for rectangle, L/U contours, plane constraints, winding and closed-shell topology.

## Development install
1. Clone or download this repository.
2. Install the package as a Blender Extension using Blender's Extension workflow.
3. Enable RoofForge.
4. In the 3D View, open the N-panel and choose RoofForge.
5. In Edit Mode, select exactly one closed edge loop; set pitch and thickness.
6. Run Validate Roof Boundary, then Create Roof Shell.

The generated object is separate from the source and inherits its world transform. The source mesh is not modified.

## Run pure Python tests
From the repository root:

    python -m compileall -q core addon __init__.py
    python -m unittest discover -s tests -v

## Not implemented yet
- Eaves overhang, fascia and soffit.
- Per-slope interactive pitch map and independent slope values.
- Live update, detach, relink and lifecycle handlers.
- Ridge, valley and hip profiles and junction patches.
- Standing seams, UVs, material assignment, LOD and export automation.
- Geometric self-intersection detection and its Blender UI diagnostics.

## Known geometry limitations
- Input must be one simple closed loop in XY.
- Collinear contour vertices and projected-vertical edges are rejected.
- Convex contour shells are covered by the current acceptance fixtures. Some concave L/U roof layouts currently create internal discontinuities in the edge-plane arrangement and are rejected instead of emitting a broken mesh; resolving this is a critical open geometry task.
- The weighted straight-skeleton solver for exact planar concave roofs is not yet implemented. `docs/CONCAVE_GEOMETRY.md` records the target algorithm, event taxonomy, constraints and test fixtures.
- The geometry kernel has unit coverage, but Blender runtime behavior, mesh attributes and Edit Mode workflow have not yet been verified in Blender 5.0.
- Non-uniform object scale can change world-space pitch because geometry is generated in source-local coordinates; apply scale before generation for predictable world-space pitch.

## Development principles
- Source geometry is immutable.
- Build and validate output before linking it into the scene.
- Stable slope indices/UUIDs identify generated regions.
- Pure geometry code must be testable outside Blender.
- Blender datablock changes happen on Blender's main thread.

## License
GPL-3.0-or-later.
