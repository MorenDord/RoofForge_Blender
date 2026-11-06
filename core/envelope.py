"""Lower-envelope partitioning for roof slope planes."""
from .geometry import (
    GeometryInputError,
    PlaneZ,
    lower_envelope_cells,
    lower_envelope_regions,
    triangulate_simple_polygon,
)

__all__ = [
    "GeometryInputError",
    "PlaneZ",
    "lower_envelope_cells",
    "lower_envelope_regions",
    "triangulate_simple_polygon",
]
