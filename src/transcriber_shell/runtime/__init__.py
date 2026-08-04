"""Runtime host detection and efficiency helpers."""

from __future__ import annotations

from transcriber_shell.runtime.machine_profile import (
    MachineProfile,
    apply_machine_efficiency,
    detect_machine_profile,
    recommend_settings,
    stage_routing_advice,
)

__all__ = [
    "MachineProfile",
    "apply_machine_efficiency",
    "detect_machine_profile",
    "recommend_settings",
    "stage_routing_advice",
]
