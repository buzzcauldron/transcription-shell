"""Install sibling fine-tuned Tesseract models (historical-ocr convention).

Mirrors historical_ocr.backends.tesseract._install_finetune_tessdata so
transcriber-shell can load custom .traineddata without vendoring historical-ocr.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def default_finetune_candidates() -> list[Path]:
    """Likely locations for lat_pre1800 / histnews traineddata."""
    home = Path.home()
    roots = [
        home / "Projects" / "historical ocr",
        home / "Projects" / "historical-ocr",
        Path(os.environ.get("HISTORICAL_OCR_ROOT", "")).expanduser()
        if os.environ.get("HISTORICAL_OCR_ROOT")
        else Path("/nonexistent"),
        Path(__file__).resolve().parents[3] / "historical ocr",
        Path(__file__).resolve().parents[3] / "historical-ocr",
    ]
    names = ("lat_pre1800.traineddata", "histnews.traineddata", "frak2021.traineddata")
    out: list[Path] = []
    for root in roots:
        for name in names:
            for sub in (root / "models", root / "models" / "tessdata"):
                p = sub / name
                if p.is_file():
                    out.append(p)
    return out


def install_finetune_tessdata(
    traineddata_path: Path,
    *,
    lang: str | None = None,
) -> Path | None:
    """Copy *traineddata_path* into a tessdata/ subdir for TESSDATA_PREFIX."""
    src = Path(traineddata_path).expanduser().resolve()
    if not src.is_file():
        return None
    lang_id = lang or src.stem
    dest_dir = src.parent / "tessdata"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{lang_id}.traineddata"
    if not dest.is_file() or dest.stat().st_mtime < src.stat().st_mtime:
        shutil.copy2(src, dest)
    return dest_dir


def apply_tessdata_prefix(prefix: Path | str) -> None:
    os.environ["TESSDATA_PREFIX"] = str(Path(prefix).expanduser().resolve())


def resolve_lang_with_finetune(base_lang: str, finetune_lang: str | None) -> str:
    if not finetune_lang:
        return base_lang
    parts = [p.strip() for p in base_lang.split("+") if p.strip()]
    if finetune_lang not in parts:
        parts.insert(0, finetune_lang)
    return "+".join(parts)


def configure_tesseract_runtime(settings) -> tuple[str, int]:
    """Install fine-tuned tessdata if configured; return (lang_bundle, psm)."""
    from transcriber_shell.htr.print_ocr_presets import resolve_finetune_path

    lang = getattr(settings, "tesseract_lang", "lat+frk+eng")
    psm = int(getattr(settings, "tesseract_psm", 7))
    finetune_lang = getattr(settings, "tesseract_finetune_lang", None)
    finetune_path = getattr(settings, "tesseract_finetune_path", None)

    path = Path(finetune_path).expanduser() if finetune_path else None
    if path is None or not path.is_file():
        auto = resolve_finetune_path()
        if auto is not None:
            path = auto
            if not finetune_lang:
                finetune_lang = auto.stem

    if path is not None and path.is_file():
        tessdata_dir = install_finetune_tessdata(path, lang=finetune_lang or path.stem)
        if tessdata_dir is not None:
            apply_tessdata_prefix(tessdata_dir)
            lang = resolve_lang_with_finetune(lang, finetune_lang or path.stem)

    return lang, psm
