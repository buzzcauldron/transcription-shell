"""HTR using the Zenodo medieval documentary model.

Model credit:
  Pinche, Ariane; Camps, Jean-Baptiste; Ing, Lionel (2023).
  "HTR model for medieval documentary sources (Latin/French)"
  Zenodo. https://doi.org/10.5281/zenodo.7547438
  Licence: CC BY 4.0

Requires: pip install 'transcriber-shell[kraken]'
"""

from __future__ import annotations

from pathlib import Path

from transcriber_shell.htr.base import HtrResult, float_to_confidence_tier


def run_kraken_htr(
    image_path: Path,
    lines_xml_path: Path,
    model_path: Path,
    *,
    device: str = "cpu",
) -> HtrResult:
    """Recognise text lines with kraken rpred and return concatenated text."""
    try:
        from kraken.lib import models as kraken_models
        from kraken.lib.xml import XMLPage
        from kraken import rpred
    except ImportError as e:
        raise RuntimeError(
            "Kraken is not installed. Install with: pip install 'transcriber-shell[kraken]'"
        ) from e

    model_path = Path(model_path).expanduser().resolve()
    if not model_path.is_file():
        raise FileNotFoundError(f"HTR model not found: {model_path}")
    if not lines_xml_path.is_file():
        raise FileNotFoundError(f"lines XML not found: {lines_xml_path}")
    if not image_path.is_file():
        raise FileNotFoundError(f"image not found: {image_path}")

    from PIL import Image

    im = Image.open(image_path)
    im.load()

    page = XMLPage(str(lines_xml_path)).to_container()

    htr_model = kraken_models.load_any(str(model_path), device=device)

    bounds = page.lines if hasattr(page, "lines") else []
    if not bounds:
        return HtrResult(text="", backend="kraken-htr", line_count=0,
                         warnings=["No lines found in XML; HTR produced no output."])

    pred_it = rpred.rpred(htr_model, im, page, pad=16)

    lines: list[str] = []
    confidences: list[float] = []
    for record in pred_it:
        lines.append(record.prediction)
        if hasattr(record, "cuts") and record.cuts:
            confidences.append(float(sum(record.confidences) / len(record.confidences)))

    mean_conf_f = float(sum(confidences) / len(confidences)) if confidences else None
    tier = float_to_confidence_tier(mean_conf_f) if mean_conf_f is not None else None
    return HtrResult(
        text="\n".join(lines),
        backend="kraken-htr",
        line_count=len(lines),
        confidence=tier,
        confidence_raw=mean_conf_f,
    )
