"""PDF page extraction.

Mirrors the convention used by sibling projects manuscript-fingerprint
(src/manuscript_fingerprint/pdf.py) and bib-ocr (pymupdf-based). Pages are
rendered to per-page images under a deterministic cache directory so they
can be fed to the rest of the pipeline like any other image input.

Requires: pip install 'transcriber-shell[pdf]'
"""

from __future__ import annotations

import hashlib
from pathlib import Path

PDF_CACHE_DIRNAME = ".pdf-pages"


def _cache_dir_for(pdf_path: Path, root: Path) -> Path:
    digest = hashlib.sha1(str(pdf_path.resolve()).encode("utf-8")).hexdigest()[:10]
    return root / PDF_CACHE_DIRNAME / f"{pdf_path.stem}-{digest}"


def extract_pdf_pages(
    pdf_path: Path,
    out_dir: Path,
    *,
    dpi: int = 300,
    jpeg_quality: int = 92,
) -> list[Path]:
    """Render each page of ``pdf_path`` to ``out_dir/<stem>_page_NNNN.jpg``.

    Idempotent: if the output already exists with the expected page count, the
    existing files are returned without re-rendering.
    """
    try:
        import fitz
    except ImportError as e:
        raise RuntimeError(
            "PDF support requires pymupdf. Install with: pip install 'transcriber-shell[pdf]'"
        ) from e

    pdf_path = Path(pdf_path).expanduser().resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    try:
        n = len(doc)
        width = max(4, len(str(max(0, n - 1))))
        stem = pdf_path.stem
        existing = sorted(out_dir.glob(f"{stem}_page_*.jpg"))
        if len(existing) == n and n > 0:
            return existing

        out_paths: list[Path] = []
        for i in range(n):
            page = doc[i]
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            out = out_dir / f"{stem}_page_{i:0{width}d}.jpg"
            pix.pil_save(str(out), format="JPEG", quality=jpeg_quality)
            out_paths.append(out)
        return out_paths
    finally:
        doc.close()


def expand_pdf_to_images(pdf_path: Path, artifacts_dir: Path, *, dpi: int = 300) -> list[Path]:
    """Convenience wrapper: rasterise into ``artifacts_dir/.pdf-pages/<stem>-<hash>/``."""
    pdf_path = Path(pdf_path).expanduser().resolve()
    cache = _cache_dir_for(pdf_path, Path(artifacts_dir))
    return extract_pdf_pages(pdf_path, cache, dpi=dpi)
