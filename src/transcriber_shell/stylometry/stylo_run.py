"""Run chunk-level FW/MFW style discrimination for a Latin text or job."""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from transcriber_shell.stylometry.reference_corpus import (
    default_reference_dir,
    load_reference_chunks,
)
from transcriber_shell.stylometry.stylo_delta import (
    burrows_delta_ranking,
    normalize_tokens,
    rolling_delta_classify,
)

# Latin function / stop words (style / register) — aligned with stylometry-r control lists.
LATIN_FUNCTION_WORDS: tuple[str, ...] = (
    "et", "in", "est", "non", "de", "ad", "per", "ut", "cum", "ex", "sed", "uel",
    "enim", "nam", "ergo", "igitur", "quia", "quod", "qui", "que", "ab", "pro",
    "si", "ante", "post", "sub", "super", "inter", "esse", "sunt", "hoc", "hec",
    "hic", "illa", "ille", "ita", "sic", "aut", "nec", "neque", "atque", "ac",
    "quoque", "tamen", "autem", "uero", "vero", "iam", "nunc", "tunc", "ubi",
    "unde", "quomodo", "quam", "quidem", "modo", "magis", "minus", "satis",
)


@dataclass
class StyloSummary:
    primary_register: str
    secondary_content: str
    function_whole: str
    mfw_whole: str
    function_rolling_majority: str
    mfw_rolling_majority: str
    function_rolling_counts: dict[str, int] = field(default_factory=dict)
    mfw_rolling_counts: dict[str, int] = field(default_factory=dict)
    n_words: int = 0
    n_function_windows: int = 0
    n_mfw_windows: int = 0
    reference_dir: str = ""
    note: str = (
        "HTR targets are often genre-mixed; primary_register is FW/register evidence, "
        "secondary_content is MFW topical neighborhood — not a single whole-MS genre."
    )

    def format_text(self) -> str:
        lines = [
            f"Primary register (FW): {self.primary_register}",
            f"Secondary content (MFW): {self.secondary_content}",
            f"Whole-text neighborhood: FW={self.function_whole} · MFW={self.mfw_whole}",
            f"Rolling majorities: FW={self.function_rolling_majority or '—'} "
            f"({self.n_function_windows} windows) · "
            f"MFW={self.mfw_rolling_majority or '—'} ({self.n_mfw_windows} windows)",
            f"Words: {self.n_words}",
        ]
        if self.function_rolling_counts:
            top = ", ".join(f"{g}:{n}" for g, n in Counter(self.function_rolling_counts).most_common(5))
            lines.append(f"FW chunk distribution: {top}")
        if self.mfw_rolling_counts:
            top = ", ".join(f"{g}:{n}" for g, n in Counter(self.mfw_rolling_counts).most_common(5))
            lines.append(f"MFW chunk distribution: {top}")
        lines.append(self.note)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mfw_features(references: dict[str, list[str]], n: int = 100) -> list[str]:
    counts: Counter[str] = Counter()
    fw = set(LATIN_FUNCTION_WORDS)
    for texts in references.values():
        for text in texts:
            for tok in normalize_tokens(text):
                if tok not in fw and len(tok) > 2:
                    counts[tok] += 1
    return [w for w, _ in counts.most_common(n)]


def analyze_text(
    text: str,
    *,
    ref_dir: Path | None = None,
) -> StyloSummary:
    root = ref_dir or default_reference_dir()
    refs = load_reference_chunks(root)
    if not refs:
        raise FileNotFoundError(
            "No medieval mixed reference set found. Set STYLOMETRY_R_REF or install "
            "stylometry-r output/de_luce_r_rescore/reference_set_medieval_mixed/."
        )
    n_words = len(text.split())
    fw_rank = burrows_delta_ranking(refs, text, LATIN_FUNCTION_WORDS)
    mfw_feats = _mfw_features(refs)
    mfw_rank = burrows_delta_ranking(refs, text, mfw_feats) if mfw_feats else []
    fw_roll = rolling_delta_classify(refs, text, LATIN_FUNCTION_WORDS)
    mfw_roll = rolling_delta_classify(refs, text, mfw_feats) if mfw_feats else None

    fw_whole = fw_rank[0].label if fw_rank else ""
    mfw_whole = mfw_rank[0].label if mfw_rank else ""
    fw_maj = ""
    mfw_maj = ""
    fw_counts: dict[str, int] = {}
    mfw_counts: dict[str, int] = {}
    if fw_roll.predictions:
        fw_counts = dict(fw_roll.counts)
        fw_maj = Counter(fw_roll.predictions).most_common(1)[0][0]
    if mfw_roll and mfw_roll.predictions:
        mfw_counts = dict(mfw_roll.counts)
        mfw_maj = Counter(mfw_roll.predictions).most_common(1)[0][0]

    primary = fw_maj or fw_whole
    secondary = mfw_maj or mfw_whole
    return StyloSummary(
        primary_register=primary,
        secondary_content=secondary,
        function_whole=fw_whole,
        mfw_whole=mfw_whole,
        function_rolling_majority=fw_maj,
        mfw_rolling_majority=mfw_maj,
        function_rolling_counts=fw_counts,
        mfw_rolling_counts=mfw_counts,
        n_words=n_words,
        n_function_windows=len(fw_roll.predictions),
        n_mfw_windows=len(mfw_roll.predictions) if mfw_roll else 0,
        reference_dir=str(root) if root else "",
    )


def load_text_from_path(path: Path) -> str:
    path = path.expanduser().resolve()
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    for cand in (
        path / f"{path.name}_whole_manuscript_text.txt",
        path / f"{path.name}_stylo.txt",
    ):
        if cand.is_file():
            return cand.read_text(encoding="utf-8", errors="replace")
    artifacts = path / "03_artifacts_2500"
    search = artifacts if artifacts.is_dir() else path
    yamls = sorted(search.rglob("*_transcription.yaml"))
    if not yamls:
        raise FileNotFoundError(f"No text or *_transcription.yaml under {path}")
    import importlib.util

    extract_path = Path(__file__).resolve().parents[3] / "scripts" / "extract_corpus_text.py"
    spec = importlib.util.spec_from_file_location("extract_corpus_text", extract_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {extract_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    pages = []
    for yp in yamls:
        t = mod.normalise_latin(mod.extract_yaml_text(yp, layer="normalized"))
        if len(t.split()) >= 50:
            pages.append(t)
    if not pages:
        raise FileNotFoundError(f"No usable transcription text under {path}")
    return "\n\n".join(pages)


def try_run_r_stylo(
    text_path: Path,
    out_dir: Path,
    *,
    target_label: str = "target",
) -> Path | None:
    """Optional shell-out to stylometry-r ``run_stylo_target.R`` when R is available."""
    r_script = Path.home() / "Projects" / "stylometry-r" / "scripts" / "run_stylo_target.R"
    if not r_script.is_file():
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "Rscript",
                str(r_script),
                "--target",
                str(text_path),
                "--label",
                target_label,
                "--out",
                str(out_dir),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return out_dir


def write_summary_json(summary: StyloSummary, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")
    return path
