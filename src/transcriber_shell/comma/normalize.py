"""CoMMA pre-editorial normalization (ByT5) for Latin and Old French HTR output.

Model: https://huggingface.co/comma-project/normalization-byt5-small
Demo:  https://huggingface.co/spaces/comma-project/pre-editorial-normalization

Use on raw HTR/CATMuS lines before LLM diplomatic correction or for browse/search
layers. This is *not* diplomatic transcription — it may over-normalize punctuation.
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache

DEFAULT_MODEL = "comma-project/normalization-byt5-small"


def _prepare_input(text: str) -> str:
    return unicodedata.normalize("NFD", text.strip())


@lru_cache(maxsize=2)
def _load_pipeline(model_id: str):
    try:
        from transformers import pipeline
    except ImportError as e:
        raise RuntimeError(
            "CoMMA normalization requires transformers. "
            "Install with: pip install 'transcriber-shell[comma]'"
        ) from e
    return pipeline(
        task="text2text-generation",
        model=model_id,
        tokenizer=model_id,
    )


def normalize_medieval_text(
    text: str,
    *,
    model_id: str = DEFAULT_MODEL,
    max_new_tokens: int = 256,
) -> str:
    """Normalize one line of Latin or Old French HTR output."""
    raw = (text or "").strip()
    if not raw:
        return ""
    pipe = _load_pipeline(model_id)
    out = pipe(
        _prepare_input(raw),
        max_new_tokens=max_new_tokens,
        do_sample=False,
    )
    if not out:
        return raw
    generated = out[0].get("generated_text", "")
    return generated.strip() if isinstance(generated, str) else raw


def normalize_lines(
    lines: list[str],
    *,
    model_id: str = DEFAULT_MODEL,
    max_new_tokens: int = 256,
) -> list[str]:
    """Batch-normalize multiple lines (reuses loaded pipeline)."""
    return [
        normalize_medieval_text(line, model_id=model_id, max_new_tokens=max_new_tokens)
        for line in lines
    ]
