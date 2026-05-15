"""CER / WER scoring: expanded TEI XML vs PAGE XML ground truth.

The canonical logic; s7_score.sh delegates here via `transcriber-shell score`.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path


_TOKEN_RE = re.compile(
    r"\[(?:illegible|uncertain|gap|damaged|glyph-uncertain|"
    r"deletion|insertion|marginalia|superscript|exp|wrap-join)[^\]]*\]"
)


def _strip_tokens(text: str) -> str:
    def _repl(m: re.Match) -> str:
        tok = m.group(0)
        if tok.startswith("[uncertain:"):
            return tok[len("[uncertain:"):].rstrip("]").strip().split("/")[0].strip()
        return ""
    return _TOKEN_RE.sub(_repl, text)


# Combining diacritics + supralinear marks that vary across transcriptions
# (macron, tilde, breve, etc.) — strip via NFD decomposition + category filter.
_COMBINING_RE = re.compile(r"\p{M}+") if False else None  # placeholder for clarity


def _canonicalize_latin(text: str) -> str:
    """Aggressive Latin-aware normalization so fair CER is not dominated by:
    - capitalization (medieval ms has variable caps)
    - punctuation (LLM adds modern punctuation; ms has none)
    - combining diacritics / supralinear marks (vary by transcription convention)
    - trailing apostrophe abbreviation marks ("Norff'" / "Suff'")
    - common medieval scribal forms ("u"↔"v", "i"↔"j" when intervocalic).

    This canonicalizer is symmetric: applied to BOTH GT and hypothesis so that
    score deltas reflect transcription quality, not formatting convention.
    """
    import unicodedata
    # NFD: decompose then drop combining marks (Mn = nonspacing, Mc = spacing,
    # Me = enclosing). Captures macrons, tildes, supralinear strokes, etc.
    t = unicodedata.normalize("NFD", text)
    t = "".join(c for c in t if unicodedata.category(c)[0] != "M")
    # Lowercase, normalize medieval u/v and i/j (lossy but matches scribal practice).
    t = t.lower()
    t = t.replace("v", "u").replace("j", "i")
    # Drop common scribal punctuation marks but keep word boundaries.
    t = re.sub(r"['\.\,\;\:\!\?\"`’‘“”…—\-\(\)\[\]]+", " ", t)
    # Collapse whitespace.
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _normalize(text: str, *, canonicalize: bool = True) -> str:
    out = re.sub(r"\s+", " ", _strip_tokens(text)).strip()
    if canonicalize:
        out = _canonicalize_latin(out)
    return out


def _levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if not s2:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for c1 in s1:
        curr = [prev[0] + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
        prev = curr
    return prev[-1]


def _word_lev(a: list[str], b: list[str]) -> int:
    if len(a) < len(b):
        return _word_lev(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for w1 in a:
        curr = [prev[0] + 1]
        for j, w2 in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (w1 != w2)))
        prev = curr
    return prev[-1]


def extract_gt_text(xml_path: Path) -> str:
    """Extract plain text from a PAGE XML file (TextLine → Unicode elements)."""
    tree = ET.parse(xml_path)
    lines: list[str] = []
    for tl in tree.getroot().findall(".//{*}TextLine"):
        u = tl.find("{*}TextEquiv/{*}Unicode")
        if u is not None and u.text:
            lines.append(u.text.strip())
    return _normalize(" ".join(lines))


def extract_tei_text(xml_path: Path) -> str:
    """Extract plain text from a TEI XML document."""
    tree = ET.parse(xml_path)
    texts: list[str] = []
    for elem in tree.getroot().iter():
        if elem.text and elem.text.strip():
            texts.append(elem.text.strip())
        if elem.tail and elem.tail.strip():
            texts.append(elem.tail.strip())
    return _normalize(" ".join(texts))


@dataclass
class ScoreCase:
    stem: str
    cer: float
    wer: float
    subs: int
    adds: int
    omits: int
    disposition: str
    gt_chars: int
    gt_words: int

    @staticmethod
    def _disposition(cer: float, wer: float) -> str:
        if cer < 1.0 and wer < 2.0:
            return "PASS"
        if cer < 3.0 and wer < 5.0:
            return "COND_PASS"
        return "FAIL"

    @classmethod
    def compute(cls, stem: str, hyp_text: str, gt_text: str) -> "ScoreCase":
        ced = _levenshtein(gt_text, hyp_text)
        gt_w = gt_text.split()
        hyp_w = hyp_text.split()
        wed = _word_lev(gt_w, hyp_w)
        cer = ced / len(gt_text) * 100 if gt_text else 0.0
        wer = wed / len(gt_w) * 100 if gt_w else 0.0
        sm = SequenceMatcher(None, gt_w, hyp_w)
        subs = adds = omits = 0
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "replace":
                subs += max(i2 - i1, j2 - j1)
            elif op == "insert":
                adds += j2 - j1
            elif op == "delete":
                omits += i2 - i1
        return cls(
            stem=stem,
            cer=round(cer, 2),
            wer=round(wer, 2),
            subs=subs,
            adds=adds,
            omits=omits,
            disposition=cls._disposition(cer, wer),
            gt_chars=len(gt_text),
            gt_words=len(gt_w),
        )


@dataclass
class ScoreReport:
    cases: list[ScoreCase] = field(default_factory=list)
    timestamp: str = ""

    @property
    def aggregate_cer(self) -> float:
        if not self.cases:
            return 0.0
        total_ced = sum(
            round(c.cer * c.gt_chars / 100) for c in self.cases
        )
        total_chars = sum(c.gt_chars for c in self.cases)
        return total_ced / total_chars * 100 if total_chars else 0.0

    @property
    def aggregate_wer(self) -> float:
        if not self.cases:
            return 0.0
        total_wed = sum(
            round(c.wer * c.gt_words / 100) for c in self.cases
        )
        total_words = sum(c.gt_words for c in self.cases)
        return total_wed / total_words * 100 if total_words else 0.0

    @property
    def aggregate_disposition(self) -> str:
        acer = self.aggregate_cer
        awer = self.aggregate_wer
        if acer < 1.0 and awer < 2.0:
            return "PASS"
        if acer < 3.0 and awer < 5.0:
            return "COND_PASS"
        return "FAIL"

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp or datetime.now(timezone.utc).isoformat(),
            "cases": [
                {
                    "stem": c.stem,
                    "cer": c.cer,
                    "wer": c.wer,
                    "subs": c.subs,
                    "adds": c.adds,
                    "omits": c.omits,
                    "disposition": c.disposition,
                    "gt_chars": c.gt_chars,
                    "gt_words": c.gt_words,
                }
                for c in self.cases
            ],
            "aggregate": {
                "cer": round(self.aggregate_cer, 2),
                "wer": round(self.aggregate_wer, 2),
                "disposition": self.aggregate_disposition,
                "n": len(self.cases),
            },
        }

    def write(self, scores_dir: Path) -> None:
        scores_dir.mkdir(parents=True, exist_ok=True)
        d = self.to_dict()
        (scores_dir / "score_report.json").write_text(
            json.dumps(d, indent=2), encoding="utf-8"
        )
        lines = [f"Score report  {d['timestamp']}\n"]
        for c in self.cases:
            lines.append(f"  {c.stem:40s}  CER {c.cer:6.2f}%  WER {c.wer:6.2f}%  [{c.disposition}]")
        agg = d["aggregate"]
        lines.append(f"\nAggregate ({agg['n']} cases): CER {agg['cer']:.2f}%  WER {agg['wer']:.2f}%  [{agg['disposition']}]")
        (scores_dir / "score_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def score_expanded_vs_gt(
    expanded_dir: Path,
    gt_dir: Path,
    *,
    verbose: bool = True,
) -> ScoreReport:
    """Score all *_tei_expanded.xml files against matching GT PAGE XMLs.

    Falls back to case-insensitive stem matching and glob prefix matching.
    """
    report = ScoreReport(timestamp=datetime.now(timezone.utc).isoformat())

    for exp_xml in sorted(expanded_dir.glob("*_tei_expanded.xml")):
        stem = exp_xml.stem.replace("_tei_expanded", "")

        # Exact match, then case-insensitive, then prefix
        gt_xml: Path | None = None
        for cand in [
            gt_dir / f"{stem}.xml",
        ]:
            if cand.is_file():
                gt_xml = cand
                break
        if gt_xml is None:
            matches = list(gt_dir.glob(f"{stem}*.xml"))
            if matches:
                gt_xml = sorted(matches)[0]
        if gt_xml is None:
            if verbose:
                print(f"  [skip] {stem}: no GT found")
            continue

        try:
            hyp = extract_tei_text(exp_xml)
            gt = extract_gt_text(gt_xml)
        except ET.ParseError as e:
            if verbose:
                print(f"  [error] {stem}: {e}")
            continue

        if not gt:
            if verbose:
                print(f"  [skip] {stem}: GT has no text")
            continue

        case = ScoreCase.compute(stem, hyp, gt)
        report.cases.append(case)
        if verbose:
            print(f"  {stem:40s}  CER {case.cer:6.2f}%  WER {case.wer:6.2f}%  [{case.disposition}]")

    return report
