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
    # CUDA first. The previous order was `mps if available else cpu`, which never
    # selected CUDA at all -- so on the 4090 and the 3080 this ran on CPU, which
    # is the difference between minutes and hours over a 20k-page corpus.
    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
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
    batch_size: int = 16,
) -> list[str]:
    """Batch-normalize multiple lines through one ``generate()`` call per batch.

    The previous implementation looped over :func:`normalize_medieval_text`, so
    despite the docstring claiming to reuse the pipeline it issued one
    ``generate()`` per line -- roughly 350,000 calls for the manuscript corpus,
    each paying full kernel-launch and decode overhead on a single short
    sequence. ByT5 works on bytes, so medieval lines are short and the GPU is
    almost entirely idle at batch size 1.

    Empty and whitespace-only lines are held out of the batch and mapped back to
    "" afterwards, so padding never reaches the model and positions still line up
    with the input.
    """
    import torch

    if not lines:
        return []
    tokenizer, model, device = _load_model(model_id)

    out: list[str] = [""] * len(lines)
    todo = [(i, ln.strip()) for i, ln in enumerate(lines) if (ln or "").strip()]

    for start in range(0, len(todo), max(1, batch_size)):
        chunk = todo[start : start + max(1, batch_size)]
        inputs = tokenizer(
            [_prepare_input(t) for _i, t in chunk],
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding=True,
        ).to(device)
        with torch.no_grad():
            output_ids = model.generate(
                **inputs, max_new_tokens=max_new_tokens, do_sample=False
            )
        decoded = tokenizer.batch_decode(output_ids, skip_special_tokens=True)
        for (idx, original), gen in zip(chunk, decoded):
            gen = (gen or "").strip()
            # Fall back to the input rather than emitting an empty line: losing a
            # line silently would corrupt the line-index alignment that the
            # PageXML and stylometry paths depend on.
            out[idx] = gen if gen else original

    return out
