"""Lightweight doc-type auto-detection from a manuscript image.

Sends the image to the configured LLM with a brief identification prompt and
matches the response to the nearest available doc-type spec name.  Designed to
run in a background thread so the GUI stays responsive.

Falls back to ``fallback`` (default "medieval_latin_legal") on any error.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable


_SYSTEM = (
    "You are an expert paleographer. "
    "Identify the document type from the image using the choices provided. "
    "Reply with valid JSON only — no prose, no markdown."
)

_USER_TMPL = """\
Available document types and their descriptions:
{choices}

Examine the image carefully (script style, language, era, layout) and pick the \
single best match from the list above.

Reply with exactly this JSON and nothing else:
{{"doc_type": "<exact_name_from_list>", "confidence": "high|medium|low", \
"reasoning": "<one sentence>"}}
"""


def _build_choices(doc_types: list[tuple[str, str]]) -> str:
    lines = []
    for name, notes in doc_types:
        line = f"  {name}"
        if notes:
            line += f": {notes}"
        lines.append(line)
    return "\n".join(lines)


def _parse_response(text: str, valid: set[str]) -> str | None:
    text = text.strip()
    # Strip markdown fences
    text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```$", "", text, flags=re.MULTILINE).strip()
    try:
        obj = json.loads(text)
        candidate = obj.get("doc_type", "")
        if candidate in valid:
            return candidate
    except (json.JSONDecodeError, AttributeError):
        pass
    # Fallback: scan raw text for any valid name
    for name in sorted(valid, key=len, reverse=True):
        if name in text:
            return name
    return None


def detect_doc_type(
    image_path: Path,
    *,
    provider: str = "gemini",
    api_key: str | None = None,
    model: str | None = None,
    fallback: str = "medieval_latin_legal",
    progress_cb: Callable[[str], None] | None = None,
) -> str:
    """Return the best matching doc-type name for *image_path*.

    Uses the LLM provider / key / model already configured in the environment.
    Never raises — returns *fallback* on any failure.
    """
    from transcriber_shell.document_types import list_doc_types, load_doc_type
    from transcriber_shell.config import Settings
    from transcriber_shell.llm.image_prep import prepare_image

    if progress_cb:
        progress_cb("detecting…")

    try:
        available = list_doc_types()
        if not available:
            return fallback

        doc_infos: list[tuple[str, str]] = []
        for name in available:
            try:
                spec = load_doc_type(name)
                notes = spec.notes.strip().split("\n")[0][:120] if spec.notes else ""
            except Exception:
                notes = ""
            doc_infos.append((name, notes))

        valid = {name for name, _ in doc_infos}
        user_text = _USER_TMPL.format(choices=_build_choices(doc_infos))

        s = Settings()
        # Override key/model when caller supplies them.
        if api_key and provider == "gemini":
            import os
            os.environ.setdefault("GOOGLE_API_KEY", api_key)
        if api_key and provider == "anthropic":
            import os
            os.environ.setdefault("ANTHROPIC_API_KEY", api_key)

        raw, _mime = prepare_image(image_path)

        if provider == "gemini":
            from transcriber_shell.llm.adapters.gemini import transcribe_gemini
            result = transcribe_gemini(
                image_path=image_path,
                system=_SYSTEM,
                user_text=user_text,
                model=model,
                settings=s,
            )
            text = result.text
        elif provider == "anthropic":
            from transcriber_shell.llm.adapters.anthropic import transcribe_anthropic
            result = transcribe_anthropic(
                image_path=image_path,
                system=_SYSTEM,
                user_text=user_text,
                model=model,
                settings=s,
            )
            text = result.text
        elif provider == "openai":
            from transcriber_shell.llm.adapters.openai import transcribe_openai
            result = transcribe_openai(
                image_path=image_path,
                system=_SYSTEM,
                user_text=user_text,
                model=model,
                settings=s,
            )
            text = result.text
        else:
            if progress_cb:
                progress_cb(f"detect failed (unsupported provider {provider!r})")
            return fallback

        detected = _parse_response(text, valid)
        if detected:
            if progress_cb:
                progress_cb(f"detected: {detected}")
            return detected

        if progress_cb:
            progress_cb("detect failed (unrecognised response)")
        return fallback

    except Exception as exc:
        if progress_cb:
            progress_cb(f"detect failed ({exc!s:.60})")
        return fallback
