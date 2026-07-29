#!/usr/bin/env python3
"""Compare free-LLM retranscriptions against existing baseline YAMLs (CER/WER)."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

import yaml


def extract_plain(path: Path) -> str:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return ""
    root = data.get("transcriptionOutput") or data
    segs = root.get("segments") or []
    parts: list[str] = []
    for seg in segs:
        if not isinstance(seg, dict):
            continue
        t = seg.get("text") or seg.get("normalizedLayer") or ""
        if isinstance(t, dict):
            t = t.get("text") or ""
        if t:
            parts.append(str(t))
    if parts:
        return " ".join(parts)
    return str(root.get("full_text") or "")


def normalize_for_score(text: str) -> str:
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower().replace("v", "u").replace("j", "i")
    t = t.replace("q3", "que").replace("&", " et ").replace("⁊", " et ")
    t = re.sub(r"\[[^\]]*\]", " ", t)
    t = re.sub(r"[^a-z\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    # memory-efficient DP
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            ins, delete, sub = cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def cer_wer(ref: str, hyp: str) -> dict:
    r = normalize_for_score(ref)
    h = normalize_for_score(hyp)
    rc, hc = list(r.replace(" ", "")), list(h.replace(" ", ""))
    rw, hw = r.split(), h.split()
    cdist = levenshtein("".join(rc), "".join(hc))
    wdist = levenshtein(rw, hw) if False else None
    # word-level edit on token sequences
    def tok_lev(a: list[str], b: list[str]) -> int:
        if a == b:
            return 0
        if not a:
            return len(b)
        if not b:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, xa in enumerate(a, 1):
            cur = [i]
            for j, xb in enumerate(b, 1):
                cur.append(min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + (xa != xb)))
            prev = cur
        return prev[-1]

    wdist = tok_lev(rw, hw)
    return {
        "cer": cdist / max(1, len(rc)),
        "wer": wdist / max(1, len(rw)),
        "ref_chars": len(rc),
        "hyp_chars": len(hc),
        "ref_words": len(rw),
        "hyp_words": len(hw),
        "char_edits": cdist,
        "word_edits": wdist,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()
    ref = extract_plain(args.baseline)
    hyp = extract_plain(args.candidate)
    m = cer_wer(ref, hyp)
    m["label"] = args.label or args.candidate.stem
    m["baseline"] = str(args.baseline)
    m["candidate"] = str(args.candidate)
    print(
        f"{m['label']}: CER={m['cer']:.3f} WER={m['wer']:.3f} "
        f"(ref {m['ref_words']}w / hyp {m['hyp_words']}w)"
    )
    if args.json_out:
        args.json_out.write_text(json.dumps(m, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
