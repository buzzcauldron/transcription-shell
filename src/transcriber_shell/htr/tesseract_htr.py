"""Tesseract HTR backend, tuned for early modern print.

Mirrors the pattern used by sibling bib-ocr (buzzcauldron/bib-ocr) which feeds
PIL crops through pytesseract for printed-text OCR. Here each TextLine in the
PageXML is cropped from the page image and recognised in turn so the per-line
shape of the output matches the other HTR backends.

Default language stack ``lat+frk+eng`` covers early modern Latin and Fraktur;
override via Settings.tesseract_lang (e.g. ``deu_latf+frk`` for German Fraktur,
``ita+lat`` for Italian humanist print, etc.).

Requires: pip install 'transcriber-shell[tesseract]'  AND a system tesseract
binary with the corresponding *.traineddata files installed.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from transcriber_shell.htr.base import HtrResult, float_to_confidence_tier


def _xml_namespace(element: ET.Element) -> str:
    m = re.match(r"\{.*\}", element.tag)
    return m.group(0)[1:-1] if m else ""


def _parse_points(s: str) -> list[tuple[int, int]]:
    """PageXML points attribute: 'x1,y1 x2,y2 ...' → list of (x,y)."""
    pts: list[tuple[int, int]] = []
    for tok in s.split():
        if "," not in tok:
            continue
        x_s, y_s = tok.split(",", 1)
        try:
            pts.append((int(float(x_s)), int(float(y_s))))
        except ValueError:
            continue
    return pts


def _line_bboxes(lines_xml_path: Path) -> list[tuple[int, int, int, int]]:
    """Return (x0, y0, x1, y1) for each TextLine in document order."""
    tree = ET.parse(str(lines_xml_path))
    root = tree.getroot()
    ns = {"ns": _xml_namespace(root)}
    boxes: list[tuple[int, int, int, int]] = []
    for line in root.findall(".//ns:TextLine", ns):
        if line.get("custom") == "type {type:margin;}":
            continue
        coords = line.find("ns:Coords", ns)
        if coords is None or not coords.get("points"):
            continue
        pts = _parse_points(coords.get("points", ""))
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        boxes.append((min(xs), min(ys), max(xs), max(ys)))
    return boxes


def run_tesseract_htr(
    image_path: Path,
    lines_xml_path: Path,
    *,
    lang: str = "lat+frk+eng",
    psm: int = 7,
    config_extra: str = "",
    pad_px: int = 6,
) -> HtrResult:
    """Crop each PageXML TextLine and run Tesseract on it.

    psm=7 (single line) is the right mode when feeding pre-cropped lines.
    """
    try:
        import pytesseract
    except ImportError as e:
        raise RuntimeError(
            "Tesseract HTR requires pytesseract. Install with: pip install 'transcriber-shell[tesseract]'"
        ) from e
    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError("Pillow is required for Tesseract HTR.") from e

    image_path = Path(image_path).expanduser().resolve()
    lines_xml_path = Path(lines_xml_path).expanduser().resolve()
    if not image_path.is_file():
        raise FileNotFoundError(f"image not found: {image_path}")
    if not lines_xml_path.is_file():
        raise FileNotFoundError(f"lines XML not found: {lines_xml_path}")

    boxes = _line_bboxes(lines_xml_path)
    if not boxes:
        return HtrResult(
            text="",
            backend="tesseract-htr",
            line_count=0,
            warnings=["No lines found in XML; Tesseract produced no output."],
        )

    im = Image.open(image_path)
    im.load()
    w, h = im.size

    config = f"--psm {psm}"
    if config_extra.strip():
        config = f"{config} {config_extra.strip()}"

    lines: list[str] = []
    confidences: list[float] = []
    for x0, y0, x1, y1 in boxes:
        x0p = max(0, x0 - pad_px)
        y0p = max(0, y0 - pad_px)
        x1p = min(w, x1 + pad_px)
        y1p = min(h, y1 + pad_px)
        if x1p <= x0p or y1p <= y0p:
            lines.append("")
            continue
        crop = im.crop((x0p, y0p, x1p, y1p))
        text = pytesseract.image_to_string(crop, lang=lang, config=config)
        lines.append(text.strip())
        # image_to_data returns per-word confidences (0–100); fold them in when present.
        try:
            data = pytesseract.image_to_data(
                crop, lang=lang, config=config, output_type=pytesseract.Output.DICT
            )
            confs = [float(c) for c in data.get("conf", []) if str(c) not in ("-1", "")]
            if confs:
                confidences.append(sum(confs) / len(confs) / 100.0)
        except Exception:  # noqa: BLE001 — per-line confidence is best-effort
            pass

    mean_conf_f = float(sum(confidences) / len(confidences)) if confidences else None
    tier = float_to_confidence_tier(mean_conf_f) if mean_conf_f is not None else None
    return HtrResult(
        text="\n".join(lines),
        backend="tesseract-htr",
        line_count=len(lines),
        confidence=tier,
        confidence_raw=mean_conf_f,
    )
