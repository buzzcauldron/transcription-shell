"""U-Net boundary inference using the active registry checkpoint."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from dendro_shell.detect.classical import DetectResult, detect_rings_along_path
from dendro_shell.project import Point


def _require_torch():
    try:
        import torch
        from dendro_shell.train.model import TinyUNet
    except ImportError as e:
        raise RuntimeError(
            "U-Net detect requires the train extra: pip install -e '.[train]'"
        ) from e
    return torch, TinyUNet


def load_model(checkpoint: Path | str, device: str | None = None):
    torch, TinyUNet = _require_torch()
    from dendro_shell.train.registry import resolve_device

    device = resolve_device(device)
    ckpt = torch.load(str(checkpoint), map_location=device, weights_only=False)
    model = TinyUNet(in_ch=1, out_ch=1, base=ckpt.get("base_channels", 16))
    model.load_state_dict(ckpt["state_dict"])
    model.to(device)
    model.eval()
    return model, device, ckpt


def predict_probability(
    image: Image.Image | np.ndarray,
    checkpoint: Path | str | None = None,
    device: str | None = None,
    imgsz: int = 512,
) -> np.ndarray:
    """Return HxW float32 probability map in [0, 1]."""
    torch, _ = _require_torch()
    from dendro_shell.train.registry import get_active_checkpoint

    if checkpoint is None:
        checkpoint = get_active_checkpoint()
    if checkpoint is None:
        raise FileNotFoundError("No active U-Net checkpoint. Train one in the Train panel.")

    model, device, _meta = load_model(checkpoint, device=device)
    if isinstance(image, Image.Image):
        gray = np.asarray(image.convert("L"), dtype=np.float32)
    else:
        arr = np.asarray(image)
        gray = arr.astype(np.float32)
        if gray.ndim == 3:
            gray = gray.mean(axis=2)
    h, w = gray.shape
    scale = imgsz / max(h, w)
    nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
    resized = np.asarray(
        Image.fromarray(gray.astype(np.uint8)).resize((nw, nh), Image.BILINEAR),
        dtype=np.float32,
    )
    # pad to square
    canvas = np.zeros((imgsz, imgsz), dtype=np.float32)
    canvas[:nh, :nw] = resized / 255.0
    tensor = torch.from_numpy(canvas)[None, None].to(device)
    with torch.no_grad():
        logits = model(tensor)
        prob = torch.sigmoid(logits)[0, 0].cpu().numpy()
    crop = prob[:nh, :nw]
    out = np.asarray(
        Image.fromarray((crop * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR),
        dtype=np.float32,
    ) / 255.0
    return out


def detect_rings_unet(
    image,
    path_points: list[Point] | list[tuple[float, float]],
    *,
    checkpoint: Path | str | None = None,
    preset: str = "sanded_core",
    min_distance_px: float = 8.0,
    prominence: float = 0.08,
    device: str | None = None,
) -> DetectResult:
    prob = predict_probability(image, checkpoint=checkpoint, device=device)
    return detect_rings_along_path(
        image,
        path_points,
        preset=preset,
        min_distance_px=min_distance_px,
        prominence=prominence,
        probability=prob,
    )
