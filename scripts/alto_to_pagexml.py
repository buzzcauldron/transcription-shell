"""Convert Paris Bible (and generic) ALTO v4 page XML to PAGE-XML for ketos -f page."""

from __future__ import annotations

import html
import re
from pathlib import Path
from xml.etree import ElementTree as ET

ALTO_NS = "http://www.loc.gov/standards/alto/ns-v4#"
PAGE_NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".JPG", ".JPEG", ".PNG", ".TIF")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find_image(images_dir: Path, stem: str) -> Path | None:
    for ext in IMAGE_EXTS:
        candidate = images_dir / f"{stem}{ext}"
        if candidate.is_file():
            return candidate.resolve()
    for path in images_dir.iterdir():
        if path.is_file() and path.stem == stem:
            return path.resolve()
    return None


def _line_text(line_el: ET.Element) -> str:
    parts: list[str] = []
    for el in line_el.iter():
        if _local(el.tag) == "String" and el.get("CONTENT"):
            parts.append(el.get("CONTENT", "").strip())
    return " ".join(p for p in parts if p).strip()


def _baseline_points(line_el: ET.Element) -> str | None:
    raw = (line_el.get("BASELINE") or "").strip()
    if raw:
        return raw
    for el in line_el.iter():
        if _local(el.tag) == "Baseline" and (el.get("POINTS") or el.text):
            return (el.get("POINTS") or el.text or "").strip()
    return None


def _line_box(line_el: ET.Element) -> tuple[int, int, int, int]:
    """Return x1, y1, x2, y2 from ALTO TextLine attributes."""
    hpos = int(line_el.get("HPOS") or 0)
    vpos = int(line_el.get("VPOS") or 0)
    width = int(line_el.get("WIDTH") or 1)
    height = int(line_el.get("HEIGHT") or 1)
    return hpos, vpos, hpos + max(width, 1), vpos + max(height, 1)


def _page_size(root: ET.Element) -> tuple[int, int]:
    for el in root.iter():
        if _local(el.tag) == "Page":
            w = int(el.get("WIDTH") or 0)
            h = int(el.get("HEIGHT") or 0)
            if w > 0 and h > 0:
                return w, h
    return 1, 1


def alto_to_pagexml(
    alto_path: Path,
    image_path: Path,
    *,
    page_width: int | None = None,
    page_height: int | None = None,
) -> str:
    """Build PAGE-XML string from one ALTO file and its page image."""
    tree = ET.parse(alto_path)
    root = tree.getroot()
    pw, ph = page_width or 0, page_height or 0
    if pw <= 0 or ph <= 0:
        pw, ph = _page_size(root)

    lines: list[tuple[str, str, str, str]] = []
    for el in root.iter():
        if _local(el.tag) != "TextLine":
            continue
        text = _line_text(el)
        if not text:
            continue
        x1, y1, x2, y2 = _line_box(el)
        coords = f"{x1},{y1} {x2},{y1} {x2},{y2} {x1},{y2}"
        baseline = _baseline_points(el)
        if not baseline:
            bl = max(min(int((y1 + y2) / 2), ph - 1), 0)
            baseline = f"{x1},{bl} {x2},{bl}"
        lines.append((coords, baseline, text, el.get("ID") or f"l{len(lines) + 1}"))

    if not lines:
        raise ValueError(f"no TextLine content in {alto_path}")

    ap = html.escape(str(image_path.resolve()), quote=True)
    chunks = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<PcGts xmlns="{PAGE_NS}">',
        f'  <Page imageFilename="{ap}" imageWidth="{pw}" imageHeight="{ph}">',
        '    <TextRegion id="r1">',
    ]
    for coords, baseline, text, lid in lines:
        txt = html.escape(text, quote=False)
        chunks.extend(
            [
                f'      <TextLine id="{html.escape(lid, quote=True)}">',
                f'        <Coords points="{coords}"/>',
                f'        <Baseline points="{baseline}"/>',
                f'        <TextEquiv><Unicode>{txt}</Unicode></TextEquiv>',
                "      </TextLine>",
            ]
        )
    chunks.extend(["    </TextRegion>", "  </Page>", "</PcGts>", ""])
    return "\n".join(chunks)


def convert_alto_pair(
    alto_path: Path,
    images_dir: Path,
    out_dir: Path,
    *,
    overwrite: bool = False,
) -> str:
    """Return 'ok', 'skip', or 'error'."""
    alto_path = alto_path.resolve()
    stem = alto_path.stem
    image = _find_image(images_dir, stem)
    if image is None:
        return "error"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}.xml"
    if out_path.exists() and not overwrite:
        return "skip"
    try:
        xml = alto_to_pagexml(alto_path, image)
        out_path.write_text(xml, encoding="utf-8")
    except (OSError, ValueError, ET.ParseError):
        return "error"
    return "ok"


def convert_alto_corpus(
    alto_dir: Path,
    images_dir: Path,
    out_dir: Path,
    *,
    workers: int = 4,
    overwrite: bool = False,
) -> tuple[int, int, int]:
    """Convert all ALTO XML files under alto_dir. Returns ok, skip, error counts."""
    altos = sorted(p for p in alto_dir.glob("*.xml") if p.is_file())
    if not altos:
        return 0, 0, 0

    ok = skip = err = 0
    if workers <= 1:
        for alto in altos:
            r = convert_alto_pair(alto, images_dir, out_dir, overwrite=overwrite)
            if r == "ok":
                ok += 1
            elif r == "skip":
                skip += 1
            else:
                err += 1
        return ok, skip, err

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(convert_alto_pair, a, images_dir, out_dir, overwrite=overwrite): a
            for a in altos
        }
        for fut in as_completed(futs):
            r = fut.result()
            if r == "ok":
                ok += 1
            elif r == "skip":
                skip += 1
            else:
                err += 1
    return ok, skip, err


def convert_paris_bible(
    corpus_dir: Path,
    *,
    workers: int = 4,
    overwrite: bool = False,
) -> tuple[int, int, int]:
    """Paris Bible ground_truth layout: PBP 1.0/ALTO + PBP 1.0/Images → page-xml/."""
    pbp = corpus_dir / "PBP 1.0"
    alto_dir = pbp / "ALTO"
    images_dir = pbp / "Images"
    out_dir = corpus_dir / "page-xml"
    if not alto_dir.is_dir():
        return 0, 0, 0
    if not images_dir.is_dir():
        return 0, 0, 0
    return convert_alto_corpus(
        alto_dir, images_dir, out_dir, workers=workers, overwrite=overwrite
    )


# LAD 1.3 blind-eval pages (Louvre Abu Dhabi 2013.051) — text GT only in repo; no public images.
LAD_HOLDOUT_MS = "2013.051"
LAD_HOLDOUT_FOLIOS = re.compile(r"^1[rv]-20[rv]$|^[1-9][rv]$|^1[0-9][rv]$", re.I)


if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus-dir", type=Path, required=True)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()
    ok, skip, err = convert_paris_bible(
        args.corpus_dir.expanduser().resolve(),
        workers=args.workers,
        overwrite=args.overwrite,
    )
    print(f"ok={ok} skip={skip} err={err}")
    sys.exit(1 if err and not ok else 0)
