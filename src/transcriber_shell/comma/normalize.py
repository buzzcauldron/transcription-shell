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
def _load_model(model_id: str):
    try:
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        import torch
    except ImportError as e:
        raise RuntimeError(
            "CoMMA normalization requires transformers. "
            "Install with: pip install 'transcriber-shell[comma]'"
        ) from e
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_id)
    model.eval()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = model.to(device)
    return tokenizer, model, device


def normalize_medieval_text(
    text: str,
    *,
    model_id: str = DEFAULT_MODEL,
    max_new_tokens: int = 256,
) -> str:
    """Normalize one line of Latin or Old French HTR output."""
    import torch
    raw = (text or "").strip()
    if not raw:
        return ""
    tokenizer, model, device = _load_model(model_id)
    inputs = tokenizer(
        _prepare_input(raw),
        return_tensors="pt",
        truncation=True,
        max_length=512,
    ).to(device)
    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )
    generated = tokenizer.decode(output_ids[0], skip_special_tokens=True)
    return generated.strip() if generated else raw


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
