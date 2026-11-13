"""Optional bridge to the in-process Rust geometry extension.

The Python implementation remains the compatibility fallback while native
wheels are built and distributed for each supported Blender platform.
"""
from __future__ import annotations

try:
    import roof_forge_native as _native
except (ImportError, OSError):
    _native = None

_NATIVE_API_VERSION = 1
NATIVE_BACKEND_AVAILABLE = (
    _native is not None
    and callable(getattr(_native, "api_version", None))
    and _native.api_version() == _NATIVE_API_VERSION
)


def validate_simple_polygon_native(points, eps: float = 1e-9):
    """Return native diagnostics, or None when the compatible wheel is absent."""
    if not NATIVE_BACKEND_AVAILABLE:
        return None

    normalised = [(float(point[0]), float(point[1])) for point in points]
    return _native.validate_simple_polygon(normalised, float(eps))
