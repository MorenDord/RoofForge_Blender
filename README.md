# RoofForge

Procedural roof generation for Blender 5.0+, designed for environment artists and game-ready asset workflows.

> **Development status:** early 1.0 alpha. Current code builds an open planar upper roof surface from one selected closed edge loop. It is not yet a complete solid roof generator and has not yet been runtime-tested in Blender 5.0.

## Project documents
- Technical specification: docs/SPECIFICATION.md
- Architecture: docs/ARCHITECTURE.md
- Development roadmap: docs/ROADMAP.md

## Current implementation
- Blender Extension manifest, registration scaffold and 3D View sidebar panel.
- Edit Mode and Object Mode selected closed-edge-loop adapter, preserving local XYZ.
- 3D slope plane construction from pitch angle, eave edge grade and polygon winding.
- Deterministic ear clipping for simple concave polygons without collinear vertices.
- Concave-domain arrangement partition that restricts planes to the inward halfspace of their source edge.
- Lower-envelope roof surface assembly with 3D vertex welding, face-to-slope integer attribute, and projected domain-coverage validation.
- Create Roof Surface operator (open upper surface only; no thickness, eaves, overhang or live link).

## Development install
1. Clone or download this repository.
2. Install the package as a Blender Extension using Blender's Extension workflow.
3. Enable RoofForge.
4. In the 3D View, open the N-panel and choose RoofForge.
5. In Edit Mode, select exactly one closed edge loop and set the default pitch.
6. Run Validate Roof Boundary, then Create Roof Surface.

The generated object is a separate object and inherits the source object's world transform. The source mesh is not modified.

## Run pure Python tests
From the repository root:

    python -m compileall -q core addon __init__.py
    python -m unittest discover -s tests -v

## Not implemented yet
- A closed roof shell, thickness, overhang and fascia.
- Per-slope interactive pitch map and individual UI values.
- Live update, detach, relink and lifecycle handlers.
- Ridge, valley and hip profiles and junction patches.
- Standing seams, UVs, material assignment, LOD and export automation.
- Full topology and self-intersection validator.

## Known geometry limitations
- Input must be one simple closed loop in XY.
- Collinear contour vertices and projected-vertical edges are rejected.
- Ear clipping and arrangement splitting are dependency-free but need more adversarial precision/performance tests.
- The current mesh checks projected area coverage and edge use count; it is not yet a complete manifold/solid validator.
- Blender runtime behavior, mesh attributes and Edit Mode adapter have not yet been verified in Blender 5.0.

## Development principles
- Source geometry is immutable.
- Build into temporary data, validate, then swap.
- Never destroy last-valid output on failed rebuild.
- Stable UUIDs identify slopes and generated parts.
- Pure geometry code must be testable outside Blender.
- Blender datablock changes happen on Blender's main thread.

## License
GPL-3.0-or-later.
