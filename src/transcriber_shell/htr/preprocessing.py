"""HTR-input preprocessing: contrast + invert + optional binarisation.

Mirrors the chain used by sibling buzzcauldron/bib-ocr
(``bib_ocr/preprocessing.py``) which is tuned for early modern printed pages
with bleed-through and weak contrast. Applied just before the page or
per-line image is handed to the HTR backend (kraken / tesseract / gm).

Toggled by ``Settings.htr_preprocess_enabled`` (default False); explicit
fields control individual steps so the caller can mix-and-match.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreprocOptions:
    """Knobs for ``preprocess_for_htr``.

    All defaults are no-ops; the caller enables steps they want. The values
    mirror bib-ocr's tested defaults: invert + 2× contrast for early modern
    print.
    """

    invert: bool = False
    contrast: float = 1.0          # 1.0 = no change; bib-ocr uses 2.0
    sharpen: bool = False
    binarise: bool = False
    deskew_degrees: float = 0.0    # rotation in degrees, clockwise

    @classmethod
    def from_settings(cls, settings) -> "PreprocOptions":
        """Build options from a Settings instance (or anything quacking like one).

        Reads ``htr_preprocess_invert``, ``htr_preprocess_contrast``,
        ``htr_preprocess_sharpen``, ``htr_preprocess_binarise``,
        ``htr_preprocess_deskew_degrees``.
        """
        g = getattr
        return cls(
            invert=bool(g(settings, "htr_preprocess_invert", False)),
            contrast=float(g(settings, "htr_preprocess_contrast", 1.0)),
            sharpen=bool(g(settings, "htr_preprocess_sharpen", False)),
            binarise=bool(g(settings, "htr_preprocess_binarise", False)),
            deskew_degrees=float(g(settings, "htr_preprocess_deskew_degrees", 0.0)),
        )

    @property
    def is_noop(self) -> bool:
        return (
            not self.invert
            and self.contrast == 1.0
            and not self.sharpen
            and not self.binarise
            and self.deskew_degrees == 0.0
        )


# Suggested presets — call sites can pull one of these instead of hand-rolling.
PRESET_EARLY_MODERN_PRINT = PreprocOptions(invert=True, contrast=2.0, sharpen=False, binarise=False)
PRESET_FRAKTUR_NOISY = PreprocOptions(invert=True, contrast=2.0, sharpen=True, binarise=True)
PRESET_MEDIEVAL_PARCHMENT = PreprocOptions(invert=False, contrast=1.3, sharpen=False, binarise=False)


def preprocess_for_htr(image, opts: PreprocOptions):
    """Return a new PIL image with the requested transforms applied.

    Mirrors bib-ocr's ``prepare_for_tesseract`` ordering: RGBA→RGB →
    optional invert → contrast enhance → optional binarise → optional
    rotate / sharpen. Returns the input unchanged if ``opts.is_noop``.
    """
    if opts.is_noop:
        return image

    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    except ImportError as e:
        raise RuntimeError(
            "PIL/Pillow is required for HTR preprocessing. Install: pip install Pillow"
        ) from e

    # Normalise mode — match bib-ocr's branch logic.
    if image.mode == "RGBA":
        r, g, b, _ = image.split()
        image = Image.merge("RGB", (r, g, b))
    elif image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    if opts.invert:
        image = ImageOps.invert(image.convert("RGB"))

    if opts.contrast != 1.0:
        image = ImageEnhance.Contrast(image).enhance(opts.contrast)

    if opts.binarise:
        image = image.convert("L").point(lambda x: 0 if x < 128 else 255, "1")

    if opts.sharpen:
        image = image.filter(ImageFilter.SHARPEN)

    if opts.deskew_degrees:
        image = image.rotate(-opts.deskew_degrees, Image.NEAREST, expand=True)

    return image
