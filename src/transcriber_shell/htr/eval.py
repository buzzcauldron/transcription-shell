"""HTR model evaluation: transcription accuracy (all formats) + baseline accuracy (XML only).

Format detection:
  *.xml (PAGE or ALTO)  →  ketos test -f page/alto  +  optional baseline comparison
  *.png/*.jpg + *.gt.txt →  ketos test -f path  (transcription only)

Baseline accuracy requires --seg-model. It runs Kraken segmentation on each test image
and compares the predicted baselines against the ground-truth baselines in the XML using
the same Chamfer-distance + recall/precision metrics as compare-lines-xml.
"""

from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


_IMG_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
_XML_EXTS = {".xml"}


# ── result types ──────────────────────────────────────────────────────────────

@dataclass
class TranscriptionMetrics:
    char_accuracy: float          # 0–1
    word_accuracy: float | None   # 0–1 when available
    num_lines: int
    fmt: str                      # "page" | "alto" | "path"

    def cer(self) -> float:
        return 1.0 - self.char_accuracy

    def wer(self) -> float | None:
        return None if self.word_accuracy is None else 1.0 - self.word_accuracy


@dataclass
class BaselineMetrics:
    recall: float
    precision: float
    mean_chamfer_px: float | None
    num_images: int


@dataclass
class EvalResult:
    transcription: TranscriptionMetrics | None = None
    baseline: BaselineMetrics | None = None
    fmt: str = ""
    warnings: list[str] = field(default_factory=list)


# ── format detection ──────────────────────────────────────────────────────────

def _sniff_xml_format(path: Path) -> str:
    """Return 'alto' if the file is ALTO XML, else 'page'."""
    try:
        for event, elem in ET.iterparse(str(path), events=("start",)):
            tag = elem.tag
            ns = tag.split("}", 1)[0].lstrip("{") if "}" in tag else ""
            local = tag.split("}", 1)[-1] if "}" in tag else tag
            if "alto" in ns.lower() or local.lower() in ("alto", "alto4"):
                return "alto"
            return "page"
    except ET.ParseError:
        pass
    return "page"


def detect_format(paths: list[Path]) -> str:
    """Return ketos -f format string for the given file list."""
    xml_files = [p for p in paths if p.suffix.lower() in _XML_EXTS]
    if xml_files:
        return _sniff_xml_format(xml_files[0])
    img_files = [p for p in paths if p.suffix.lower() in _IMG_EXTS]
    if img_files:
        return "path"
    return "page"


# ── file collection ───────────────────────────────────────────────────────────

def collect_gt_files(gt: Path) -> list[Path]:
    """Return sorted list of ground-truth files from a directory or single file."""
    if gt.is_file():
        return [gt]
    xml = sorted(gt.rglob("*.xml"))
    if xml:
        return xml
    imgs = sorted(
        p for p in gt.rglob("*")
        if p.suffix.lower() in _IMG_EXTS and p.with_suffix(".gt.txt").exists()
    )
    return imgs


def _get_image_from_pagexml(xml_path: Path) -> Path | None:
    """Extract imageFilename from a PAGE XML and resolve relative to the XML's directory."""
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        for el in root.iter():
            tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if tag == "Page":
                fname = el.get("imageFilename")
                if fname:
                    p = Path(fname)
                    if p.is_absolute():
                        return p if p.exists() else None
                    resolved = (xml_path.parent / p).resolve()
                    return resolved if resolved.exists() else None
    except ET.ParseError:
        pass
    return None


# ── ketos test ────────────────────────────────────────────────────────────────

def _parse_ketos_test_output(text: str) -> tuple[float | None, float | None, int]:
    """Parse ketos test stdout/stderr for char accuracy, word accuracy, and line count."""
    char_acc: float | None = None
    word_acc: float | None = None
    num_lines = 0

    for line in text.splitlines():
        # "Character Accuracy: 0.9355" or "character accuracy │ 0.9355" or "0.9355"
        m = re.search(r"[Cc]haracter\s+[Aa]ccuracy[^0-9]*([0-9]+\.?[0-9]*)", line)
        if m:
            v = float(m.group(1))
            char_acc = v if v <= 1.0 else v / 100.0
            continue
        m = re.search(r"[Ww]ord\s+[Aa]ccuracy[^0-9]*([0-9]+\.?[0-9]*)", line)
        if m:
            v = float(m.group(1))
            word_acc = v if v <= 1.0 else v / 100.0
            continue
        # ketos 7 sometimes prints only a bare float accuracy on its own line
        m = re.fullmatch(r"\s*([0-9]\.[0-9]{3,})\s*", line)
        if m and char_acc is None:
            char_acc = float(m.group(1))
            continue
        m = re.search(r"([0-9]+)\s+(?:lines?|samples?)", line, re.IGNORECASE)
        if m:
            num_lines = max(num_lines, int(m.group(1)))

    return char_acc, word_acc, num_lines


def run_ketos_test(
    model: Path,
    files: list[Path],
    fmt: str,
    *,
    device: str = "cpu",
) -> TranscriptionMetrics:
    """Run `ketos test` as a subprocess and return parsed metrics."""
    cmd = [
        sys.executable, "-m", "kraken.ketos",
        "-d", device,
        "test",
        "-m", str(model),
        "-f", fmt,
    ]
    cmd += [str(f) for f in files]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    combined = result.stdout + result.stderr

    # Fall back to the ketos CLI entry point if the above fails
    if result.returncode != 0 and "No module named" in combined:
        cmd[0:3] = ["ketos"]
        cmd.insert(1, "-d")
        cmd.insert(2, device)
        # ketos [global opts] test [opts] files
        cmd = ["ketos", "-d", device, "test", "-m", str(model), "-f", fmt] + [str(f) for f in files]
        result = subprocess.run(cmd, capture_output=True, text=True)
        combined = result.stdout + result.stderr

    if result.returncode not in (0, 1):
        raise RuntimeError(f"ketos test failed (exit {result.returncode}):\n{combined[:2000]}")

    char_acc, word_acc, num_lines = _parse_ketos_test_output(combined)
    if char_acc is None:
        raise RuntimeError(
            f"Could not parse accuracy from ketos test output:\n{combined[:2000]}"
        )
    return TranscriptionMetrics(
        char_accuracy=char_acc,
        word_accuracy=word_acc,
        num_lines=num_lines,
        fmt=fmt,
    )


# ── baseline evaluation ───────────────────────────────────────────────────────

def run_baseline_eval(
    xml_files: list[Path],
    seg_model: Path,
    *,
    device: str = "cpu",
    centroid_match_px: float = 120.0,
) -> BaselineMetrics:
    """Segment each test image with seg_model and compare baselines to XML ground truth."""
    try:
        from PIL import Image as PILImage
        from kraken import blla
        from kraken.lib import models as kraken_models
    except ImportError as e:
        raise RuntimeError(f"kraken not importable for baseline eval: {e}") from e

    from transcriber_shell.xml_tools.lines_compare import (
        extract_textline_baselines,
        match_baselines,
        chamfer_distance_px,
    )

    seg = kraken_models.load_any(str(seg_model))
    recalls, precisions, chamfers = [], [], []
    skipped = 0

    for xml_path in xml_files:
        img_path = _get_image_from_pagexml(xml_path)
        if img_path is None:
            skipped += 1
            continue

        ref_polys = extract_textline_baselines(xml_path)
        if not ref_polys:
            skipped += 1
            continue

        try:
            im = PILImage.open(img_path).convert("RGB")
            res = blla.segment(im, model=seg)
        except Exception:
            skipped += 1
            continue

        hyp_polys: list[list[tuple[float, float]]] = []
        for line in getattr(res, "lines", []):
            bl = getattr(line, "baseline", None)
            if bl:
                hyp_polys.append(list(bl))

        if not hyp_polys:
            skipped += 1
            continue

        pairs, uref, uhyp = match_baselines(
            ref_polys, hyp_polys, centroid_match_px=centroid_match_px
        )
        import math
        for ri, hj, _ in pairs:
            c = chamfer_distance_px(ref_polys[ri], hyp_polys[hj])
            if not math.isnan(c):
                chamfers.append(c)

        n_ref = len(ref_polys)
        n_hyp = len(hyp_polys)
        matched = len(pairs)
        recalls.append(matched / n_ref if n_ref else 1.0)
        precisions.append(matched / n_hyp if n_hyp else 1.0)

    if not recalls:
        raise RuntimeError(
            f"Baseline eval: no usable image/XML pairs ({skipped} skipped)"
        )

    return BaselineMetrics(
        recall=sum(recalls) / len(recalls),
        precision=sum(precisions) / len(precisions),
        mean_chamfer_px=sum(chamfers) / len(chamfers) if chamfers else None,
        num_images=len(recalls),
    )


# ── top-level entry point ─────────────────────────────────────────────────────

def evaluate(
    model: Path,
    gt: Path,
    *,
    seg_model: Path | None = None,
    device: str = "cpu",
    centroid_match_px: float = 120.0,
) -> EvalResult:
    """Full evaluation: transcription always; baseline when XML + seg_model provided."""
    result = EvalResult()
    warnings: list[str] = []

    files = collect_gt_files(gt)
    if not files:
        raise FileNotFoundError(f"No ground-truth files found under {gt}")

    fmt = detect_format(files)
    result.fmt = fmt

    # Transcription accuracy
    try:
        result.transcription = run_ketos_test(model, files, fmt, device=device)
    except RuntimeError as e:
        warnings.append(f"ketos test: {e}")

    # Baseline accuracy (XML only, requires seg model)
    if fmt in ("page", "alto"):
        xml_files = [f for f in files if f.suffix.lower() == ".xml"]
        if seg_model:
            try:
                result.baseline = run_baseline_eval(
                    xml_files,
                    seg_model,
                    device=device,
                    centroid_match_px=centroid_match_px,
                )
            except RuntimeError as e:
                warnings.append(f"baseline eval: {e}")
        else:
            warnings.append(
                "Baseline accuracy skipped: provide --seg-model to evaluate line detection."
            )
    else:
        warnings.append(
            "Baseline accuracy not available for PNG+.gt.txt format "
            "(no coordinate ground truth)."
        )

    result.warnings = warnings
    return result


# ── report formatting ─────────────────────────────────────────────────────────

def format_eval_report(result: EvalResult, *, as_json: bool = False) -> str:
    import json

    if as_json:
        d: dict = {"format": result.fmt, "warnings": result.warnings}
        if result.transcription:
            t = result.transcription
            d["transcription"] = {
                "char_accuracy": round(t.char_accuracy, 6),
                "cer": round(t.cer(), 6),
                "word_accuracy": round(t.word_accuracy, 6) if t.word_accuracy is not None else None,
                "wer": round(t.wer(), 6) if t.wer() is not None else None,
                "num_lines": t.num_lines,
            }
        if result.baseline:
            b = result.baseline
            d["baseline"] = {
                "recall": round(b.recall, 4),
                "precision": round(b.precision, 4),
                "mean_chamfer_px": round(b.mean_chamfer_px, 2) if b.mean_chamfer_px is not None else None,
                "num_images": b.num_images,
            }
        return json.dumps(d, indent=2)

    lines = [f"format: {result.fmt}"]
    if result.transcription:
        t = result.transcription
        lines += [
            "",
            "── Transcription accuracy ──",
            f"  char_accuracy : {t.char_accuracy:.4f}   CER: {t.cer():.4f}",
        ]
        if t.word_accuracy is not None:
            lines.append(f"  word_accuracy : {t.word_accuracy:.4f}   WER: {t.wer():.4f}")
        if t.num_lines:
            lines.append(f"  lines tested  : {t.num_lines}")
    if result.baseline:
        b = result.baseline
        lines += [
            "",
            "── Baseline accuracy ──",
            f"  recall        : {b.recall:.4f}",
            f"  precision     : {b.precision:.4f}",
        ]
        if b.mean_chamfer_px is not None:
            lines.append(f"  mean_chamfer  : {b.mean_chamfer_px:.1f} px")
        lines.append(f"  images tested : {b.num_images}")
    for w in result.warnings:
        lines.append(f"\nwarn: {w}")
    return "\n".join(lines) + "\n"
