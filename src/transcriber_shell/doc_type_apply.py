"""Apply document-type YAML specs to Settings and GUI form fields."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from transcriber_shell.config import Settings
from transcriber_shell.document_types import DocumentTypeSpec, load_doc_type
from transcriber_shell.htr.print_ocr_presets import (
    resolve_finetune_path,
    settings_updates_for_doc_type,
)


_PRINT_SCRIPTS = frozenset({"print_latin", "fraktur"})


def prefer_tesseract_ocr(spec: DocumentTypeSpec) -> bool:
    """True when the doc type is meant to use fast in-process Tesseract for print OCR."""
    if spec.script in _PRINT_SCRIPTS:
        return True
    name = spec.name.lower()
    return "print" in name or "fraktur" in name


def default_tesseract_lang(spec: DocumentTypeSpec) -> str:
    if spec.script == "fraktur" or spec.language.startswith("deu"):
        return "deu_latf+frk"
    if spec.language.startswith("ita"):
        return "ita+lat"
    if spec.language.startswith("eng"):
        return "eng+fra+deu"
    return "lat+frk+eng"


def apply_doc_type(
    doc_type: str | None,
    settings: Settings,
    prompt_arg: str | None,
) -> tuple[Settings, str | None]:
    """Load doc-type spec and apply it to settings + prompt path.

    Returns (updated_settings, resolved_prompt_path_str).
    Explicit CLI / form values win over spec defaults when already set on ``settings``.
    """
    if not doc_type:
        return settings, prompt_arg

    extra = [settings.document_types_dir] if settings.document_types_dir else []
    spec = load_doc_type(doc_type, extra_dirs=extra)

    updates: dict = {}

    if not settings.default_model:
        updates["default_provider"] = spec.primary_provider
        updates["default_model"] = spec.primary_model

    use_tesseract = prefer_tesseract_ocr(spec)

    if spec.htr_path and not settings.kraken_htr_model_path and not use_tesseract:
        updates["kraken_htr_model_path"] = spec.htr_path

    if spec.seg_path and not settings.kraken_model_path:
        updates["kraken_model_path"] = spec.seg_path

    if use_tesseract:
        updates["tesseract_enabled"] = True
        if not settings.tesseract_lang or settings.tesseract_lang == "lat+frk+eng":
            updates["tesseract_lang"] = default_tesseract_lang(spec)
        updates["htr_combination"] = "tesseract_htr"
    elif spec.htr_path:
        updates["htr_combination"] = "kraken_htr"

    print_preset = settings_updates_for_doc_type(doc_type)
    for key, val in print_preset.items():
        if key.startswith("htr_preprocess") or key == "tesseract_psm":
            updates[key] = val
        elif key == "tesseract_lang" and (
            not settings.tesseract_lang or settings.tesseract_lang == "lat+frk+eng"
        ):
            updates[key] = val
        elif key not in updates:
            updates[key] = val

    if use_tesseract and not updates.get("htr_preprocess_enabled"):
        updates.setdefault("htr_preprocess_enabled", True)
        updates.setdefault("htr_preprocess_invert", True)
        updates.setdefault("htr_preprocess_contrast", 2.0)

    finetune = resolve_finetune_path()
    if finetune and not settings.tesseract_finetune_path:
        updates.setdefault("tesseract_finetune_path", finetune)
        updates.setdefault("tesseract_finetune_lang", finetune.stem)

    new_settings = settings.model_copy(update=updates) if updates else settings

    resolved_prompt = prompt_arg
    if resolved_prompt is None:
        pp = spec.prompt_path()
        if pp:
            resolved_prompt = str(pp)
        else:
            resolved_prompt = spec.prompt

    return new_settings, resolved_prompt


@dataclass(frozen=True)
class DocTypeFormPreset:
    doc_type: str
    prompt_path: str | None
    provider: str
    model_id: str | None
    kraken_seg_model_path: str | None
    kraken_htr_model_path: str | None
    tesseract_enabled: bool
    tesseract_lang: str | None
    htr_combination: str | None


def form_preset_for_doc_type(
    doc_type: str,
    *,
    settings: Settings | None = None,
    existing_prompt: str | None = None,
) -> DocTypeFormPreset:
    """Resolve GUI field values for a document type (does not mutate settings)."""
    base = settings or Settings()
    updated, prompt = apply_doc_type(doc_type, base, existing_prompt)
    pp = prompt
    if pp and not Path(pp).expanduser().is_file():
        spec = load_doc_type(
            doc_type,
            extra_dirs=[base.document_types_dir] if base.document_types_dir else [],
        )
        resolved = spec.prompt_path()
        pp = str(resolved) if resolved else pp

    return DocTypeFormPreset(
        doc_type=doc_type,
        prompt_path=pp,
        provider=updated.default_provider,
        model_id=updated.default_model,
        kraken_seg_model_path=str(updated.kraken_model_path) if updated.kraken_model_path else None,
        kraken_htr_model_path=str(updated.kraken_htr_model_path)
        if updated.kraken_htr_model_path
        else None,
        tesseract_enabled=updated.tesseract_enabled,
        tesseract_lang=updated.tesseract_lang or None,
        htr_combination=updated.htr_combination or None,
    )
