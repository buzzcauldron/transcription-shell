"""Convert arbitrary image formats to provider-compatible (bytes, mime_type) pairs.

Native pass-through: JPEG, PNG, WebP — no re-encoding.
Converted to JPEG: TIFF, BMP, GIF (first frame), HEIC/HEIF, and any other PIL-readable format.
PDFs: first page rendered to JPEG via pymupdf (optional dep); raises ImportError if absent.

Size guardrails (applied to converted images only):
  - Max dimension: 8000 px (Anthropic hard limit; Gemini comfortable range)
  - JPEG quality: 92
"""

from __future__ import annotations

import io
from pathlib import Path


# Provider-native formats that can be sent as-is.
_NATIVE: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

_MAX_DIM = 8000  # px — Anthropic hard limit; beyond this resize
_JPEG_QUALITY = 92


def _pdf_to_jpeg(path: Path) -> bytes:
    try:
        import fitz  # pymupdf
    except ImportError as exc:
        raise ImportError(
            "pymupdf is required to transcribe PDFs. "
            "Install with: pip install 'transcriber-shell[pdf]'"
        ) from exc
    doc = fitz.open(str(path))
    page = doc[0]
    mat = fitz.Matrix(2.0, 2.0)  # 2× zoom → ~144 dpi from 72 dpi base
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return pix.tobytes("jpeg")


def _pil_to_jpeg(path: Path) -> bytes:
    from PIL import Image
    img = Image.open(path)
    # For animated/multi-frame sources (GIF, multi-page TIFF), take frame 0.
    if hasattr(img, "n_frames") and img.n_frames > 1:
        img.seek(0)
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > _MAX_DIM:
        scale = _MAX_DIM / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), resample=Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def prepare_image(path: Path) -> tuple[bytes, str]:
    """Return ``(raw_bytes, mime_type)`` ready to send to any vision LLM.

    Native JPEG/PNG/WebP files are read as-is.  All other formats are
    converted to JPEG via PIL (or pymupdf for PDFs).
    """
    path = Path(path)
    suf = path.suffix.lower()

    if suf in _NATIVE:
        return path.read_bytes(), _NATIVE[suf]

    if suf == ".pdf":
        return _pdf_to_jpeg(path), "image/jpeg"

    # TIFF, BMP, GIF, HEIC, and anything else PIL can open.
    return _pil_to_jpeg(path), "image/jpeg"
