"""Bridge to buzzcauldron/expand-diplomatic (TEI + PAGE XML abbreviation expansion)."""

from __future__ import annotations

import html
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from transcriber_shell.config import Settings

PAGE_NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15"


def resolve_expand_root(explicit: Path | None = None) -> Path:
    """Locate expand-diplomatic checkout (editable install or sibling clone)."""
    for candidate in (
        explicit,
        _env_path("EXPAND_DIPLOMATIC_ROOT"),
        _env_path("MAGIC_ELISE_ROOT"),
        Path.home() / "Projects" / "expand-diplomatic",
    ):
        if candidate is not None and (candidate / "expand_diplomatic" / "expander.py").is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "expand-diplomatic not found. Clone https://github.com/buzzcauldron/expand-diplomatic "
        "or set EXPAND_DIPLOMATIC_ROOT / MAGIC_ELISE_ROOT."
    )


def _env_path(key: str) -> Path | None:
    raw = (os.environ.get(key) or "").strip()
    return Path(raw).expanduser() if raw else None


def _ensure_expand_import(root: Path | None = None) -> None:
    root = root or resolve_expand_root()
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)


@lru_cache(maxsize=1)
def _default_examples_path(root: Path) -> Path:
    for name in ("examples.json", "expand_examples.json"):
        p = root / name
        if p.is_file():
            return p
    return root / "examples.json"


def load_expand_examples(settings: Settings) -> list[dict[str, str]]:
    root = resolve_expand_root(settings.expand_diplomatic_root)
    _ensure_expand_import(root)
    from expand_diplomatic.examples_io import load_examples

    path = settings.expand_diplomatic_examples or _default_examples_path(root)
    if path.is_file():
        return load_examples(path)
    return []


def _expand_kwargs(settings: Settings, examples: list[dict[str, str]]) -> dict[str, Any]:
    api_key = settings.google_api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get(
        "GOOGLE_API_KEY"
    )
    return {
        "examples": examples,
        "model": settings.expand_diplomatic_model,
        "api_key": api_key,
        "backend": settings.expand_diplomatic_backend,
        "modality": settings.expand_diplomatic_modality,
        "passes": settings.expand_diplomatic_passes,
        "dry_run": settings.expand_diplomatic_dry_run,
        "whole_document": settings.expand_diplomatic_whole_document,
    }


def expand_pagexml_string(xml_source: str, settings: Settings) -> str:
    root = resolve_expand_root(settings.expand_diplomatic_root)
    _ensure_expand_import(root)
    from expand_diplomatic.expander import expand_xml

    examples = load_expand_examples(settings)
    return expand_xml(xml_source, **_expand_kwargs(settings, examples))


def extract_unicode_lines(xml_source: str) -> list[str]:
    root = resolve_expand_root()
    _ensure_expand_import(root)
    from expand_diplomatic.expander import extract_text_lines

    text = extract_text_lines(xml_source, block_tags={"Unicode"})
    if text:
        return [ln for ln in text.splitlines() if ln.strip()]
    text = extract_text_lines(xml_source)
    return [ln for ln in text.splitlines() if ln.strip()]


def build_pagexml_with_lines(
    image_filename: str,
    image_width: int,
    image_height: int,
    lines: list[str],
    *,
    region_id: str = "r1",
) -> str:
    """Minimal PAGE XML with one TextLine + Unicode per HTR line."""
    w, h = max(image_width, 1), max(image_height, 1)
    ap = html.escape(image_filename, quote=True)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<PcGts xmlns="{PAGE_NS}">',
        f'  <Page imageFilename="{ap}" imageWidth="{w}" imageHeight="{h}">',
        f'    <TextRegion id="{region_id}">',
        f'      <Coords points="1,1 {w - 1},1 {w - 1},{h - 1} 1,{h - 1}"/>',
    ]
    bl = max(min(int(h * 0.8), h - 2), 1)
    pts = f"1,1 {w - 1},1 {w - 1},{h - 1} 1,{h - 1}"
    base_y = f"1,{bl} {w - 1},{bl}"
    for i, line in enumerate(lines):
        txt = html.escape((line or "").strip(), quote=False)
        parts.extend(
            [
                f'      <TextLine id="l{i + 1}">',
                f'        <Coords points="{pts}"/>',
                f'        <Baseline points="{base_y}"/>',
                f"        <TextEquiv><Unicode>{txt}</Unicode></TextEquiv>",
                f"      </TextLine>",
            ]
        )
    parts.extend(["    </TextRegion>", "  </Page>", "</PcGts>", ""])
    return "\n".join(parts)


def expand_pagexml_lines(
    image_filename: str,
    image_width: int,
    image_height: int,
    lines: list[str],
    settings: Settings,
) -> tuple[str, list[str]]:
    """Build PAGE XML from diplomatic lines, expand, return (expanded_xml, line texts)."""
    xml_in = build_pagexml_with_lines(image_filename, image_width, image_height, lines)
    xml_out = expand_pagexml_string(xml_in, settings)
    expanded_lines = extract_unicode_lines(xml_out)
    if len(expanded_lines) != len(lines):
        # Pad or trim so callers can zip safely
        if len(expanded_lines) < len(lines):
            expanded_lines.extend(lines[len(expanded_lines) :])
        else:
            expanded_lines = expanded_lines[: len(lines)]
    return xml_out, expanded_lines


def expand_yaml_artifact(
    yaml_path: Path,
    *,
    settings: Settings,
    tei_out: Path | None = None,
    expanded_tei_out: Path | None = None,
    expanded_txt_out: Path | None = None,
) -> tuple[Path, Path]:
    """YAML → TEI → expand-diplomatic → expanded TEI + plain text."""
    from transcriber_shell.xml_tools.tei import yaml_to_tei

    yaml_path = yaml_path.expanduser().resolve()
    stem = yaml_path.stem.replace("_transcription", "")
    parent = yaml_path.parent
    tei_path = tei_out or parent / f"{stem}_diplomatic.tei.xml"
    out_tei = expanded_tei_out or parent / f"{stem}_expanded.tei.xml"
    out_txt = expanded_txt_out or parent / f"{stem}_expanded.txt"

    yaml_to_tei(yaml_path, tei_path)
    tei_xml = tei_path.read_text(encoding="utf-8")
    expanded_xml = expand_pagexml_string(tei_xml, settings)
    out_tei.write_text(expanded_xml, encoding="utf-8")
    root = resolve_expand_root(settings.expand_diplomatic_root)
    _ensure_expand_import(root)
    from expand_diplomatic.expander import extract_text_lines

    out_txt.write_text(extract_text_lines(expanded_xml), encoding="utf-8")
    return out_tei, out_txt


def is_page_xml(xml_source: str) -> bool:
    root = resolve_expand_root()
    _ensure_expand_import(root)
    from expand_diplomatic.expander import is_page_xml as _is_page

    return _is_page(xml_source)


def should_run_expand(prompt_cfg: dict[str, Any], settings: Settings) -> bool:
    if not settings.expand_diplomatic_enabled:
        return False
    mode = str(prompt_cfg.get("normalizationMode") or "diplomatic").strip().lower()
    return mode != "normalized"


def maybe_run_expand_stage(
    yaml_path: Path,
    prompt_cfg: dict[str, Any],
    settings: Settings,
    *,
    log_fn=None,
) -> tuple[Path | None, Path | None, list[str]]:
    """Run expand-diplomatic when enabled; return (expanded_tei, expanded_txt, warnings)."""
    warnings: list[str] = []
    if not should_run_expand(prompt_cfg, settings):
        return None, None, warnings

    _log = log_fn or (lambda _m: None)
    try:
        _log(
            f"expand: starting ({settings.expand_diplomatic_backend}/"
            f"{settings.expand_diplomatic_model})…"
        )
        out_tei, out_txt = expand_yaml_artifact(yaml_path, settings=settings)
        _log(f"expand: wrote {out_tei.name} and {out_txt.name}")
        return out_tei, out_txt, warnings
    except FileNotFoundError as exc:
        warnings.append(f"expand-diplomatic skipped: {exc}")
    except Exception as exc:
        warnings.append(f"expand-diplomatic failed: {type(exc).__name__}: {exc}")
    return None, None, warnings
