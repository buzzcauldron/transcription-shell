"""``predict_masks`` for transcriber-shell mask lineation backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image

from latin_lineation_mvp.dataset import load_image_rgb
from latin_lineation_mvp.model import LineMaskUNet

_model: LineMaskUNet | None = None
_device: torch.device | None = None
_loaded_ckpt: Path | None = None
_meta: dict[str, Any] | None = None


def _load_bundle(settings: Any) -> tuple[LineMaskUNet, dict[str, Any], torch.device]:
    global _model, _device, _loaded_ckpt, _meta
    wpath = getattr(settings, "mask_weights_path", None)
    if wpath is None:
        raise RuntimeError(
            "latin_lineation_mvp.infer: set TRANSCRIBER_SHELL_MASK_WEIGHTS_PATH to a .pt from latin-lineation-train"
        )
    ckpt_path = Path(wpath).expanduser().resolve()
    if not ckpt_path.is_file():
        raise FileNotFoundError(f"checkpoint not found: {ckpt_path}")

    dev_s = getattr(settings, "mask_device", None) or "cpu"
    device = torch.device(dev_s if isinstance(dev_s, str) else str(dev_s))

    if _model is not None and _loaded_ckpt == ckpt_path and _device == device:
        assert _meta is not None
        return _model, _meta, device

    try:
        payload = torch.load(ckpt_path, map_location=device, weights_only=False)
    except TypeError:
        payload = torch.load(ckpt_path, map_location=device)
    if isinstance(payload, dict) and "state_dict" in payload:
        meta = payload.get("meta", {})
        state = payload["state_dict"]
    else:
        raise ValueError(f"unexpected checkpoint format: {ckpt_path}")

    max_lines = int(meta.get("max_lines", 64))
    model = LineMaskUNet(in_ch=3, max_lines=max_lines).to(device)
    model.load_state_dict(state)
    model.eval()
    _model = model
    _loaded_ckpt = ckpt_path
    _device = device
    _meta = meta
    return model, meta, device


@torch.no_grad()
def predict_masks(image_path: Path, settings: Any) -> np.ndarray:
    """Return ``(L, H, W)`` float masks at training resolution (shell upsamples to page size)."""
    model, meta, device = _load_bundle(settings)
    mask_h = int(meta.get("mask_h", 256))
    mask_w = int(meta.get("mask_w", 256))
    max_lines = int(meta.get("max_lines", model.max_lines))

    rgb = load_image_rgb(Path(image_path))  # H, W, 3
    ih, iw = rgb.shape[0], rgb.shape[1]
    img_rs = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
    img_rs = np.array(
        Image.fromarray(img_rs).resize(
            (mask_w, mask_h), Image.Resampling.BILINEAR
        )
    )
    img_rs = img_rs.astype(np.float32) / 255.0
    chw = np.transpose(img_rs, (2, 0, 1))
    x = torch.from_numpy(chw).unsqueeze(0).to(device)
    logits = model(x)[0]  # (L, h, w)
    prob = torch.sigmoid(logits).cpu().numpy()

    # Drop empty channels; keep channels with enough total mass *or* a strong peak
    # (trained models often spread OOD pages thinly across many channels).
    min_mass = float(
        getattr(settings, "mask_channel_min_mass", 15.0) or 15.0
    )
    min_peak = float(
        getattr(settings, "mask_channel_min_peak", 0.12) or 0.12
    )
    max_out = int(getattr(settings, "mask_max_output_lines", 96) or 96)

    idx_ok: list[int] = []
    for i in range(prob.shape[0]):
        ch = prob[i]
        if float(ch.sum()) >= min_mass or float(ch.max()) >= min_peak:
            idx_ok.append(i)

    if not idx_ok:
        j = int(np.argmax([prob[i].sum() for i in range(prob.shape[0])]))
        keep = [prob[j].astype(np.float32)]
    else:
        idx_ok.sort(key=lambda i: float(prob[i].sum()), reverse=True)
        idx_ok = idx_ok[:max_out]
        keep = [prob[i].astype(np.float32) for i in sorted(idx_ok)]

    out = np.stack(keep, axis=0)
    return out
