"""Ring boundary detectors — classical, boolean bridge, U-Net."""

from dendro_shell.detect.boolean_bridge import detect_rings_boolean_bridge
from dendro_shell.detect.classical import detect_rings_along_path
from dendro_shell.detect.methods import (
    DETECT_STACK,
    METHOD_IDS,
    default_method_for,
    list_detect_methods,
    resolve_method,
)

__all__ = [
    "DETECT_STACK",
    "METHOD_IDS",
    "default_method_for",
    "detect_rings_along_path",
    "detect_rings_boolean_bridge",
    "list_detect_methods",
    "resolve_method",
]
