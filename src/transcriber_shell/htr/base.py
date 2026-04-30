"""Shared types for HTR backends.

HtrResult carries raw character-recognition output. It is NOT a diplomatic
transcript under the Academic Handwriting Transcription Protocol — no
two-pass self-check, hallucination audit, or uncertainty tokens are applied.
Confidence tiers use the protocol vocabulary (high / medium / low) per §1.1
(default-skeptical: high is exceptional; medium is the normal working state).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ConfidenceTier = Literal["high", "medium", "low"]


def float_to_confidence_tier(score: float) -> ConfidenceTier:
    """Map a raw per-character mean confidence (0–1) to protocol tiers.

    Thresholds are conservative per §1.1: high is reserved for unambiguous
    glyph evidence; medium is the default for typical manuscript work.
      >= 0.90 → high
      >= 0.70 → medium
      <  0.70 → low
    """
    if score >= 0.90:
        return "high"
    if score >= 0.70:
        return "medium"
    return "low"


@dataclass
class HtrResult:
    """Raw HTR output. Not a protocol-compliant diplomatic transcript."""

    text: str
    backend: str
    line_count: int = 0
    # Protocol confidence tier (§1.1): high / medium / low. None = not reported.
    confidence: ConfidenceTier | None = None
    # Raw mean per-character confidence (0–1) from the backend, before tier mapping.
    confidence_raw: float | None = None
    warnings: list[str] = field(default_factory=list)
    # Always False: HTR backends do not run the two-pass check, hallucination
    # audit, or uncertainty-token marking required by the protocol.
    is_protocol_compliant: bool = False
