"""CTC beam-search decoder with optional KenLM n-gram language model.

Provides a thin wrapper around pyctcdecode so Kraken HTR inference can benefit
from a language model without changing the model architecture.

When kenlm is unavailable (local dev, macOS) the decoder falls back to CTC beam
search without an LM — still better than greedy at long-tail characters.

Build a Latin n-gram model on Bridges:
    bash scripts/build_latin_ngram_lm.sh

Reference:
    Strickland et al., "End-to-end HTR for Anglo-American legal manuscripts",
    2026.  N-gram LM boosted word accuracy from 79 % → 82 %.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)


def _build_decoder(
    vocab: list[str],
    lm_path: Path | None,
    *,
    alpha: float = 0.5,
    beta: float = 1.5,
    beam_width: int = 100,
):
    """Build a pyctcdecode BeamSearchDecoderCTC, optionally with a KenLM model."""
    try:
        from pyctcdecode import build_ctcdecoder
    except ImportError as exc:
        raise RuntimeError(
            "pyctcdecode is not installed. "
            "Run: pip install 'transcriber-shell[gm-htr]'"
        ) from exc

    kenlm_model = None
    if lm_path is not None and lm_path.is_file():
        try:
            import kenlm as _kenlm  # noqa: F401 — presence check
            kenlm_model = str(lm_path)
            logger.debug("ctc_lm: using KenLM model %s", lm_path)
        except ImportError:
            logger.warning(
                "ctc_lm: kenlm not installed — running beam search without LM. "
                "On Bridges: pip install kenlm"
            )

    decoder = build_ctcdecoder(
        labels=vocab,
        kenlm_model=kenlm_model,
        alpha=alpha if kenlm_model else 0.0,
        beta=beta if kenlm_model else 0.0,
    )
    return decoder


def rescore_with_lm(
    logits: "list[list[float]] | None",
    greedy_text: str,
    vocab: list[str],
    lm_path: Path | None,
    *,
    alpha: float = 0.5,
    beta: float = 1.5,
    beam_width: int = 100,
) -> str:
    """Rescore Kraken CTC output with beam search + optional KenLM LM.

    Args:
        logits:      Per-timestep character log-probabilities from Kraken rpred.
                     If None (Kraken didn't expose them), returns greedy_text
                     unchanged.
        greedy_text: Output from Kraken greedy decoding (fallback).
        vocab:       Ordered character vocabulary used during Kraken training.
        lm_path:     Path to a KenLM binary (.bin) or ARPA model; may be None.
        alpha:       LM weight (0 = no LM contribution).
        beta:        Word insertion bonus.
        beam_width:  Beam width for beam search.

    Returns:
        Rescored text, or greedy_text if logits are unavailable.
    """
    if logits is None:
        return greedy_text

    import numpy as np

    try:
        decoder = _build_decoder(
            vocab, lm_path, alpha=alpha, beta=beta, beam_width=beam_width
        )
        logits_np = np.array(logits, dtype=np.float32)
        return decoder.decode(logits_np)
    except Exception as exc:
        logger.warning("ctc_lm: beam search failed (%s), using greedy output", exc)
        return greedy_text


def rescore_lines(
    line_logits: "Sequence[list[list[float]] | None]",
    greedy_lines: list[str],
    vocab: list[str],
    lm_path: Path | None,
    *,
    alpha: float = 0.5,
    beta: float = 1.5,
    beam_width: int = 100,
) -> list[str]:
    """Rescore a list of lines, returning greedy text for any that fail."""
    return [
        rescore_with_lm(
            lgt, grd, vocab, lm_path, alpha=alpha, beta=beta, beam_width=beam_width
        )
        for lgt, grd in zip(line_logits, greedy_lines)
    ]
