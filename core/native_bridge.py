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


class NativeGeometryError(RuntimeError):
    """A geometry diagnostic returned by the native kernel."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


NATIVE_WAVEFRONT_EVENTS_AVAILABLE = (
    NATIVE_BACKEND_AVAILABLE
    and callable(getattr(_native, "collect_wavefront_events", None))
)


def collect_wavefront_events_native(lines, loop_id: int, time: float,
                                    eps: float = 1e-9):
    """Collect all event candidates for one active loop in a single Rust call."""
    if not NATIVE_WAVEFRONT_EVENTS_AVAILABLE:
        return None

    records = [
        (
            int(line.edge_id),
            float(line.normal[0]),
            float(line.normal[1]),
            float(line.offset),
            float(line.speed),
            float(line.tangent[0]),
            float(line.tangent[1]),
            int(line.generation),
            float(line.base_height),
        )
        for line in lines
    ]
    try:
        return _native.collect_wavefront_events(
            records, int(loop_id), float(time), float(eps)
        )
    except ValueError as exc:
        raw = str(exc)
        code, separator, message = raw.partition("|")
        if separator:
            raise NativeGeometryError(code, message) from exc
        raise
