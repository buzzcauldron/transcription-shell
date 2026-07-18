"""Detection stack: classical → boolean bridge → U-Net.

Boolean bridge is a first-class method (not an optional add-on). Discs default
to boolean so cracks/checks are handled in the normal open/detect path.
"""

from __future__ import annotations

from typing import Any, Literal

DetectMethod = Literal["classical", "boolean", "unet"]
MethodChoice = Literal["auto", "classical", "boolean", "unet"]

# Ordered stack shown in CLI / UI / API
DETECT_STACK: list[dict[str, str]] = [
    {
        "id": "classical",
        "label": "Classical",
        "summary": "Path-neighborhood peaks / latewood troughs",
    },
    {
        "id": "boolean",
        "label": "Boolean bridge",
        "summary": "Match ring fragments across cracks and damage",
    },
    {
        "id": "unet",
        "label": "Active U-Net",
        "summary": "In-app trained boundary model (when activated)",
    },
]

METHOD_IDS: tuple[str, ...] = tuple(m["id"] for m in DETECT_STACK)


def list_detect_methods() -> list[dict[str, str]]:
    """Return the detection stack for API / UI population."""
    return [dict(m) for m in DETECT_STACK]


def default_method_for(sample_type: str | None) -> DetectMethod:
    """Discs → boolean (cracks/checks); cores → classical peaks."""
    if (sample_type or "").lower() == "disc":
        return "boolean"
    return "classical"


def resolve_method(
    method: str | None,
    *,
    sample_type: str | None = None,
) -> DetectMethod:
    """Normalize method id; ``auto`` picks the stack default for sample type."""
    m = (method or "auto").strip().lower()
    if m in ("", "auto"):
        return default_method_for(sample_type)
    if m in METHOD_IDS:
        return m  # type: ignore[return-value]
    return default_method_for(sample_type)


def method_payload(*, active_unet: str | None = None) -> dict[str, Any]:
    """JSON blob for /api/models and /api/health."""
    return {
        "methods": list(METHOD_IDS),
        "stack": list_detect_methods(),
        "defaults": {"core": "classical", "disc": "boolean"},
        "active_unet": active_unet,
    }
