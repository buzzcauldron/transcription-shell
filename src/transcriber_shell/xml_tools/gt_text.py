"""Manual ground-truth text annotation: PAGE XML ↔ sidecar text file.

Workflow for adding human transcriptions to lineation-only PAGE XML files
(so they can be scored against pipeline output via s7_score.sh):

1. ``gt-template`` — for each PAGE XML in a directory:
     * write a `<stem>.gt.txt` with one numbered placeholder per TextLine
     * optionally crop each TextLine to a PNG tile in `<stem>.gt_tiles/`
2. Human transcribes each numbered line in the .gt.txt (one line of text
   per source line; blank lines remain blank).
3. ``gt-inject`` — reads each `<stem>.gt.txt` and writes
   `<TextEquiv><Unicode>…</Unicode></TextEquiv>` into the matching
   TextLine element of the XML (in place or to an output dir).

The .gt.txt format::

    # source: CP40-642m439b.xml
    # 36 lines. Edit the text after the colon. Lines that stay blank are
    # treated as missing GT and skipped by the scorer.
    001: <line 1 transcription here>
    002:
    003: <line 3 transcription here>
    ...
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterator


_LINE_RE = re.compile(r"^(\d{3,}):\s*(.*)$")


def _iter_text_lines(root: ET.Element) -> Iterator[ET.Element]:
    for el in root.iter():
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "TextLine":
            yield el


def _polygon_from_coords(coords_el: ET.Element) -> list[tuple[int, int]]:
    pts_attr = coords_el.get("points") or ""
    toks = pts_attr.split()
    if not toks:
        return []
    if "," in toks[0]:
        out: list[tuple[int, int]] = []
        for tok in toks:
            if "," in tok:
                xs, _, ys = tok.partition(",")
                try:
                    out.append((int(round(float(xs))), int(round(float(ys)))))
                except ValueError:
                    continue
        return out
    nums: list[float] = []
    for tok in toks:
        try:
            nums.append(float(tok))
        except ValueError:
            return []
    return [(int(round(nums[i])), int(round(nums[i + 1]))) for i in range(0, len(nums) - 1, 2)]


def write_template(
    xml_path: Path,
    out_txt: Path,
    *,
    image_path: Path | None = None,
    crop_tiles_dir: Path | None = None,
) -> int:
    """Write a numbered .gt.txt template for the TextLines in an XML.

    If ``image_path`` and ``crop_tiles_dir`` are both given, also crop each
    TextLine to a PNG tile so the human can read it directly while typing.

    Returns the number of TextLines written.
    """
    root = ET.parse(str(xml_path)).getroot()
    lines = list(_iter_text_lines(root))
    n = len(lines)

    lines_to_write: list[str] = []
    lines_to_write.append(f"# source: {xml_path.name}")
    lines_to_write.append(
        f"# {n} lines. Edit the text after the colon. Blank lines are "
        f"treated as missing GT and skipped by the scorer."
    )
    for i in range(n):
        lines_to_write.append(f"{i + 1:03d}: ")
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text("\n".join(lines_to_write) + "\n", encoding="utf-8")

    if image_path is not None and crop_tiles_dir is not None and n > 0:
        try:
            from PIL import Image, ImageDraw
        except ImportError as e:
            raise RuntimeError("PIL required for --crop-tiles") from e
        if not image_path.is_file():
            raise FileNotFoundError(f"image not found: {image_path}")
        im = Image.open(image_path)
        im.load()
        crop_tiles_dir.mkdir(parents=True, exist_ok=True)
        for i, tl in enumerate(lines):
            coords = None
            for c in tl:
                ctag = c.tag.split("}")[-1] if "}" in c.tag else c.tag
                if ctag == "Coords":
                    coords = c
                    break
            if coords is None:
                continue
            poly = _polygon_from_coords(coords)
            if len(poly) < 3:
                continue
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            # Pad 4px for legibility
            x0, x1 = max(0, min(xs) - 4), min(im.width, max(xs) + 5)
            y0, y1 = max(0, min(ys) - 4), min(im.height, max(ys) + 5)
            if x1 - x0 < 4 or y1 - y0 < 4:
                continue
            tile_path = crop_tiles_dir / f"{i + 1:03d}.png"
            im.crop((x0, y0, x1, y1)).save(tile_path)

    return n


def inject_text(
    xml_path: Path,
    txt_path: Path,
    out_path: Path | None = None,
) -> tuple[int, int]:
    """Inject text from a `.gt.txt` file into TextEquiv/Unicode elements of XML.

    Returns ``(n_lines, n_filled)`` — total TextLines and how many got text.
    Blank-text lines in the template are silently skipped (no TextEquiv added).
    Writes to ``out_path`` if given, else overwrites ``xml_path``.
    """
    # Parse text file
    by_idx: dict[int, str] = {}
    for raw in txt_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        idx = int(m.group(1))
        text = m.group(2).strip()
        if text:
            by_idx[idx] = text

    # Parse XML, preserve namespace via simple wildcard-aware insert
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    ns_uri = ""
    if "}" in root.tag:
        ns_uri = root.tag.split("}")[0].lstrip("{")
        ET.register_namespace("", ns_uri)

    def _qn(local: str) -> str:
        return f"{{{ns_uri}}}{local}" if ns_uri else local

    lines = list(_iter_text_lines(root))
    n_filled = 0
    for i, tl in enumerate(lines):
        text = by_idx.get(i + 1)
        if not text:
            continue
        # Remove any existing TextEquiv to avoid duplicates
        for existing in list(tl):
            etag = existing.tag.split("}")[-1] if "}" in existing.tag else existing.tag
            if etag == "TextEquiv":
                tl.remove(existing)
        te = ET.SubElement(tl, _qn("TextEquiv"))
        uc = ET.SubElement(te, _qn("Unicode"))
        uc.text = text
        n_filled += 1

    dst = out_path if out_path is not None else xml_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(dst), xml_declaration=True, encoding="utf-8")
    return len(lines), n_filled
