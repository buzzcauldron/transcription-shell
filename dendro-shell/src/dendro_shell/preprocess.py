"""Named hard-image presets (OCR / HTR-inspired) for ring imagery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np
from PIL import Image


PresetName = Literal["sanded_core", "dark_disc", "wet_stain", "narrow_rings", "none"]


@dataclass(frozen=True)
class PreprocOptions:
    invert: bool = False
    clahe_clip: float = 0.0  # 0 = off
    clahe_grid: int = 8
    denoise: Literal["none", "bilateral", "median"] = "none"
    morph_open: int = 0  # kernel size; 0 = off
    unsharp_amount: float = 0.0
    unsharp_radius: float = 1.5
    highfreq_boost: float = 0.0

    @property
    def is_noop(self) -> bool:
        return (
            not self.invert
            and self.clahe_clip <= 0
            and self.denoise == "none"
            and self.morph_open <= 0
            and self.unsharp_amount <= 0
            and self.highfreq_boost <= 0
        )


PRESETS: dict[str, PreprocOptions] = {
    "none": PreprocOptions(),
    "sanded_core": PreprocOptions(
        invert=False,
        clahe_clip=2.5,
        clahe_grid=8,
        denoise="bilateral",
        unsharp_amount=0.6,
    ),
    "dark_disc": PreprocOptions(
        invert=True,
        clahe_clip=4.0,
        clahe_grid=8,
        denoise="bilateral",
        unsharp_amount=0.8,
    ),
    "wet_stain": PreprocOptions(
        invert=False,
        clahe_clip=2.0,
        denoise="median",
        morph_open=3,
        unsharp_amount=0.4,
    ),
    "narrow_rings": PreprocOptions(
        invert=False,
        clahe_clip=3.0,
        denoise="bilateral",
        unsharp_amount=1.2,
        unsharp_radius=1.0,
        highfreq_boost=0.8,
    ),
}


def _to_gray_u8(image: Image.Image | np.ndarray) -> np.ndarray:
    if isinstance(image, Image.Image):
        arr = np.asarray(image.convert("RGB"))
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    else:
        arr = np.asarray(image)
        if arr.ndim == 3:
            if arr.shape[2] == 4:
                arr = arr[:, :, :3]
            if arr.dtype != np.uint8:
                a = arr.astype(np.float32)
                a = a - a.min()
                mx = a.max()
                arr = (a * 255.0 / mx).astype(np.uint8) if mx > 0 else a.astype(np.uint8)
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        else:
            gray = arr
    if gray.dtype != np.uint8:
        g = gray.astype(np.float32)
        g = g - g.min()
        mx = g.max()
        gray = (g * 255.0 / mx).astype(np.uint8) if mx > 0 else g.astype(np.uint8)
    return gray


def _unsharp(gray: np.ndarray, amount: float, radius: float) -> np.ndarray:
    if amount <= 0:
        return gray
    k = max(1, int(round(radius * 2)) * 2 + 1)
    blur = cv2.GaussianBlur(gray, (k, k), radius)
    sharp = cv2.addWeighted(gray, 1.0 + amount, blur, -amount, 0)
    return sharp


def _highfreq(gray: np.ndarray, boost: float) -> np.ndarray:
    if boost <= 0:
        return gray
    blur = cv2.GaussianBlur(gray, (0, 0), 1.2)
    hf = cv2.subtract(gray, blur)
    out = cv2.addWeighted(gray, 1.0, hf, boost, 0)
    return out


def preprocess_gray(
    image: Image.Image | np.ndarray,
    opts: PreprocOptions | str | None = None,
) -> np.ndarray:
    """Return uint8 grayscale after the requested transforms."""
    if isinstance(opts, str):
        opts = PRESETS.get(opts, PRESETS["none"])
    if opts is None:
        opts = PRESETS["none"]
    gray = _to_gray_u8(image)
    if opts.is_noop:
        return gray
    if opts.invert:
        gray = cv2.bitwise_not(gray)
    if opts.clahe_clip > 0:
        clahe = cv2.createCLAHE(
            clipLimit=float(opts.clahe_clip),
            tileGridSize=(int(opts.clahe_grid), int(opts.clahe_grid)),
        )
        gray = clahe.apply(gray)
    if opts.denoise == "bilateral":
        gray = cv2.bilateralFilter(gray, d=5, sigmaColor=40, sigmaSpace=40)
    elif opts.denoise == "median":
        gray = cv2.medianBlur(gray, 3)
    if opts.morph_open > 0:
        k = int(opts.morph_open) | 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        gray = cv2.morphologyEx(gray, cv2.MORPH_OPEN, kernel)
    gray = _unsharp(gray, opts.unsharp_amount, opts.unsharp_radius)
    gray = _highfreq(gray, opts.highfreq_boost)
    return gray


def preprocess_pil(
    image: Image.Image,
    opts: PreprocOptions | str | None = None,
) -> Image.Image:
    gray = preprocess_gray(image, opts)
    return Image.fromarray(gray, mode="L")


def list_presets() -> list[str]:
    return list(PRESETS.keys())
