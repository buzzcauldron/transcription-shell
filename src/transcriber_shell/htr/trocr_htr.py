"""TrOCR line recognition (HuggingFace VisionEncoderDecoder).

Default checkpoint: ``microsoft/trocr-base-handwritten`` for manuscript lines.
Fine-tuned weights: local directory or Hub id via Settings.trocr_model.

Requires: pip install 'transcriber-shell[trocr]'
"""

from __future__ import annotations

from pathlib import Path

from transcriber_shell.htr.base import HtrResult, float_to_confidence_tier
from transcriber_shell.htr.pagexml_lines import iter_text_lines


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def _load_trocr(model_id: str, device: str):
    try:
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    except ImportError as e:
        raise RuntimeError(
            "TrOCR requires transformers. Install with: pip install 'transcriber-shell[trocr]'"
        ) from e

    processor = TrOCRProcessor.from_pretrained(model_id)
    model = VisionEncoderDecoderModel.from_pretrained(model_id)
    import torch

    dev = _resolve_device(device)
    model.to(dev)
    model.eval()
    return processor, model, dev


def run_trocr_htr(
    image_path: Path,
    lines_xml_path: Path,
    *,
    model_id: str = "microsoft/trocr-base-handwritten",
    device: str = "auto",
    pad_px: int = 6,
    max_new_tokens: int = 128,
) -> HtrResult:
    """Crop each PageXML TextLine and run TrOCR."""
    try:
        from PIL import Image
        import torch
    except ImportError as e:
        raise RuntimeError("Pillow and torch are required for TrOCR HTR.") from e

    image_path = Path(image_path).expanduser().resolve()
    lines_xml_path = Path(lines_xml_path).expanduser().resolve()
    if not image_path.is_file():
        raise FileNotFoundError(f"image not found: {image_path}")
    if not lines_xml_path.is_file():
        raise FileNotFoundError(f"lines XML not found: {lines_xml_path}")

    line_records = iter_text_lines(lines_xml_path)
    if not line_records:
        return HtrResult(
            text="",
            backend="trocr-htr",
            line_count=0,
            warnings=["No lines found in XML; TrOCR produced no output."],
        )

    processor, model, dev = _load_trocr(model_id, device)
    im = Image.open(image_path).convert("RGB")
    im.load()
    w, h = im.size

    lines: list[str] = []
    confidences: list[float] = []
    for rec in line_records:
        x0, y0, x1, y1 = rec.bbox
        x0p = max(0, x0 - pad_px)
        y0p = max(0, y0 - pad_px)
        x1p = min(w, x1 + pad_px)
        y1p = min(h, y1 + pad_px)
        if x1p <= x0p or y1p <= y0p:
            lines.append("")
            continue
        crop = im.crop((x0p, y0p, x1p, y1p))
        pixel_values = processor(images=crop, return_tensors="pt").pixel_values.to(dev)
        with torch.no_grad():
            outputs = model.generate(
                pixel_values,
                max_new_tokens=max_new_tokens,
                output_scores=True,
                return_dict_in_generate=True,
            )
        decoded = processor.batch_decode(outputs.sequences, skip_special_tokens=True)
        lines.append((decoded[0] if decoded else "").strip())
        try:
            if outputs.scores:
                import torch.nn.functional as F

                step_max = []
                for score in outputs.scores:
                    probs = F.softmax(score[0], dim=-1)
                    step_max.append(float(probs.max().item()))
                if step_max:
                    confidences.append(sum(step_max) / len(step_max))
        except Exception:  # noqa: BLE001
            pass

    mean_conf_f = float(sum(confidences) / len(confidences)) if confidences else None
    tier = float_to_confidence_tier(mean_conf_f) if mean_conf_f is not None else None
    return HtrResult(
        text="\n".join(lines),
        backend="trocr-htr",
        line_count=len(lines),
        confidence=tier,
        confidence_raw=mean_conf_f,
    )
