"""CoMMA pre-editorial normalization (ByT5) for Latin and Old French HTR output.

Model: https://huggingface.co/comma-project/normalization-byt5-small
Demo:  https://huggingface.co/spaces/comma-project/pre-editorial-normalization

Use on raw HTR/CATMuS lines before LLM diplomatic correction or for browse/search
layers. This is *not* diplomatic transcription — it may over-normalize punctuation.
"""

from __future__ import annotations

import re
import unicodedata
import warnings
from functools import lru_cache

DEFAULT_MODEL = "comma-project/normalization-byt5-small"

# ByT5 is a BYTE-level model: one token per UTF-8 byte, not per word-piece. So
# `max_length` and `max_new_tokens` are byte budgets, and a 400-word manuscript
# chunk (~2,500 bytes) blows straight through the old fixed 256-token output cap.
# Measured before this was fixed: feeding manifest chunks in whole returned
# output capped at exactly 256 characters for 200/200 chunks -- a silent 90% loss
# that looked like success because the surviving text was correctly normalized.
#
# The model was trained on single manuscript LINES, so the fix is to feed it
# line-sized segments rather than to raise the cap and hope.
MAX_INPUT_BYTES = 512
# Headroom over the input: normalization expands abbreviations (ñ -> non,
# dñi -> domini), so the output is routinely longer than the input.
OUTPUT_BYTE_HEADROOM = 2.0
MIN_OUTPUT_TOKENS = 64


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


def _budget(texts: list[str], max_new_tokens: int | None) -> int:
    """Output byte budget for a batch, derived from its longest input.

    A fixed budget is what caused the silent 90% truncation; scale it instead.
    """
    if max_new_tokens is not None:
        return max_new_tokens
    longest = max((len(t.encode("utf-8")) for t in texts), default=0)
    return max(MIN_OUTPUT_TOKENS, int(longest * OUTPUT_BYTE_HEADROOM) + 16)


def normalize_medieval_text(
    text: str,
    *,
    model_id: str = DEFAULT_MODEL,
    max_new_tokens: int | None = None,
) -> str:
    """Normalize one LINE of Latin or Old French HTR output.

    One line. Passing a whole page or a multi-hundred-word chunk silently loses
    most of it -- see MAX_INPUT_BYTES. Use :func:`normalize_long_text` for
    anything longer than a line.
    """
    import torch
    raw = (text or "").strip()
    if not raw:
        return ""
    tokenizer, model, device = _load_model(model_id)
    n_bytes = len(_prepare_input(raw).encode("utf-8"))
    if n_bytes > MAX_INPUT_BYTES:
        warnings.warn(
            f"[transcriber-shell] ByT5 input is {n_bytes} bytes, over the "
            f"{MAX_INPUT_BYTES}-byte limit; it will be TRUNCATED. ByT5 is "
            "byte-level and line-trained -- use normalize_long_text() to segment "
            "longer text instead of losing the tail.",
            stacklevel=2,
        )
    budget = _budget([raw], max_new_tokens)
    inputs = tokenizer(
        _prepare_input(raw),
        return_tensors="pt",
        truncation=True,
        max_length=MAX_INPUT_BYTES,
    ).to(device)
    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=budget,
            do_sample=False,
        )
    generated = tokenizer.decode(output_ids[0], skip_special_tokens=True)
    return generated.strip() if generated else raw


def normalize_lines(
    lines: list[str],
    *,
    model_id: str = DEFAULT_MODEL,
    max_new_tokens: int | None = None,
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

    # LENGTH BUCKETING. Generation is autoregressive over BYTES and runs to the
    # batch's token budget, which _budget() derives from the LONGEST member. Mixed
    # lengths therefore make every short segment pay the longest one's decode
    # steps, and padding wastes the rest. Sorting by length before batching makes
    # each batch nearly uniform, so the budget is tight for everyone in it.
    # Original positions are carried through and restored by index, so output
    # order is unaffected.
    todo.sort(key=lambda p: len(p[1]))

    def _run(chunk: list[tuple[int, str]], bs_note: int) -> None:
        """Normalize one batch, writing results into ``out`` by index."""
        texts = [_prepare_input(t) for _i, t in chunk]
        budget = _budget(texts, max_new_tokens)
        inputs = tokenizer(
            texts,
            return_tensors="pt",
            truncation=True,
            max_length=MAX_INPUT_BYTES,
            padding=True,
        ).to(device)
        with torch.no_grad():
            output_ids = model.generate(
                **inputs, max_new_tokens=budget, do_sample=False
            )
        decoded = tokenizer.batch_decode(output_ids, skip_special_tokens=True)
        for (idx, original), gen in zip(chunk, decoded):
            gen = (gen or "").strip()
            # Fall back to the input rather than emitting an empty line: losing a
            # line silently would corrupt the line-index alignment that the
            # PageXML and stylometry paths depend on.
            out[idx] = gen if gen else original

    # OOM-ADAPTIVE BATCHING. Attention memory grows with batch x seqlen^2, and the
    # longest bucket therefore peaks far above the average -- a run at batch 256
    # died with CUDA OOM 5,624 chunks into a 25,883-chunk corpus, on a GPU shared
    # with other work. Rather than pick a timid batch for every bucket to suit the
    # worst one, halve and retry only the batch that actually failed. Progress
    # already written to `out` is untouched, so a split costs nothing but time.
    step = max(1, batch_size)
    start = 0
    while start < len(todo):
        chunk = todo[start : start + step]
        try:
            _run(chunk, step)
            start += len(chunk)
        except torch.OutOfMemoryError:
            torch.cuda.empty_cache() if torch.cuda.is_available() else None
            if len(chunk) == 1:
                # A single segment cannot be split further; skip it rather than
                # abandoning the corpus, and keep the source text for that line.
                idx, original = chunk[0]
                out[idx] = original
                warnings.warn(
                    "[transcriber-shell] ByT5 OOM on a single segment "
                    f"({len(original)} chars); keeping it unnormalized.",
                    stacklevel=2,
                )
                start += 1
                continue
            step = max(1, len(chunk) // 2)
            warnings.warn(
                f"[transcriber-shell] ByT5 CUDA OOM; halving batch to {step} "
                "and retrying this batch.",
                stacklevel=2,
            )

    return out


# ── Long text ─────────────────────────────────────────────────────────────────

# Segment target in bytes. Comfortably under MAX_INPUT_BYTES so the doubled
# output budget also stays in range, and close to the manuscript-line lengths the
# model was trained on.
SEGMENT_BYTES = 220

_SENT_SPLIT = re.compile(r"(?<=[.;:?!])\s+")


def segment_for_byt5(text: str, *, target_bytes: int = SEGMENT_BYTES) -> list[str]:
    """Split text into ByT5-sized pieces, preferring sentence then word breaks.

    Needed because ByT5 is byte-level and line-trained: handed a 400-word chunk
    it returned a correctly-normalized *first fragment* and dropped the rest, and
    because the fragment was clean the loss did not look like an error.

    Splits on sentence boundaries first so each piece is a plausible unit of
    language; only falls back to word boundaries when a single sentence is itself
    over budget. Never splits mid-word -- a half word would be normalized into a
    different word.
    """
    text = (text or "").strip()
    if not text:
        return []
    pieces: list[str] = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf.strip():
            pieces.append(buf.strip())
        buf = ""

    for sent in _SENT_SPLIT.split(text):
        if not sent.strip():
            continue
        if len(sent.encode("utf-8")) > target_bytes:
            flush()
            words, cur = sent.split(), ""
            for w in words:
                cand = f"{cur} {w}".strip()
                if cur and len(cand.encode("utf-8")) > target_bytes:
                    pieces.append(cur)
                    cur = w
                else:
                    cur = cand
            if cur:
                pieces.append(cur)
            continue
        cand = f"{buf} {sent}".strip()
        if buf and len(cand.encode("utf-8")) > target_bytes:
            flush()
            buf = sent
        else:
            buf = cand
    flush()
    return pieces


def normalize_long_text(
    text: str,
    *,
    model_id: str = DEFAULT_MODEL,
    batch_size: int = 32,
    target_bytes: int = SEGMENT_BYTES,
) -> str:
    """Normalize text of any length by segmenting, normalizing, and rejoining.

    Use this for manifest chunks, pages, or whole works.
    :func:`normalize_medieval_text` is for a single line and truncates past
    MAX_INPUT_BYTES.
    """
    pieces = segment_for_byt5(text, target_bytes=target_bytes)
    if not pieces:
        return ""
    normed = normalize_lines(pieces, model_id=model_id, batch_size=batch_size)
    return " ".join(p for p in normed if p)


# ── Hallucination guard ───────────────────────────────────────────────────────

# The PEN paper notes that normalizing models "tend to over-normalize and
# hallucinate", and that is what we measured: given unreadable HTR
# ("d UMxI5u 1 pos 0. si cilium p. 12e."), the model emitted invented Greek
# ("Πολισμοῦς et Πολισμοῦς et"). Rare -- 1 chunk in 100 -- but it fabricates text
# that was never on the page, which is exactly what must not reach a corpus.
#
# Script drift is the cheap, precise signal. Legitimate normalization of Latin
# stays in Latin script; it expands abbreviations and fixes orthography. It never
# introduces Greek or Cyrillic. So a segment whose output gains a script its
# input did not have is rejected and the input is kept instead.
#
# Deliberately narrow: it does not try to judge whether an expansion is correct,
# only whether the model changed alphabet. Broader heuristics (novel-token rate)
# cannot work here -- 67.5% of output tokens are absent from the input by design,
# because expanding e~ -> est creates a new token every time.
_SCRIPT_RANGES = (
    ("greek", 0x0370, 0x03FF),
    ("greek_ext", 0x1F00, 0x1FFF),
    ("cyrillic", 0x0400, 0x04FF),
    ("hebrew", 0x0590, 0x05FF),
    ("arabic", 0x0600, 0x06FF),
)


def _scripts_present(text: str) -> set[str]:
    found = set()
    for ch in text:
        cp = ord(ch)
        for name, lo, hi in _SCRIPT_RANGES:
            if lo <= cp <= hi:
                found.add(name)
                break
    return found


def rejects_script_drift(source: str, generated: str) -> bool:
    """True when *generated* introduces a script absent from *source*."""
    return bool(_scripts_present(generated) - _scripts_present(source))


def normalize_long_text_guarded(
    text: str,
    *,
    model_id: str = DEFAULT_MODEL,
    batch_size: int = 32,
    target_bytes: int = SEGMENT_BYTES,
) -> tuple[str, int]:
    """:func:`normalize_long_text` with the script-drift guard applied per segment.

    Returns ``(text, n_segments_rejected)``. Rejection is per SEGMENT, not per
    chunk, so one unreadable line does not discard the normalization of the
    dozens of good lines around it.
    """
    pieces = segment_for_byt5(text, target_bytes=target_bytes)
    if not pieces:
        return "", 0
    normed = normalize_lines(pieces, model_id=model_id, batch_size=batch_size)
    kept: list[str] = []
    rejected = 0
    for src, gen in zip(pieces, normed):
        if gen and rejects_script_drift(src, gen):
            rejected += 1
            kept.append(src)
        else:
            kept.append(gen or src)
    return " ".join(p for p in kept if p), rejected
