"""DeepL translation adapter (https://www.deepl.com/en/docs-api).

Used as the backend for provider="deepl" (or provider="kagi", which was
historically a DeepL-backed wrapper).  Requires a DeepL API key — free tier
covers 500K characters/month, which is ample for post-transcription passes.

Set DEEPL_API_KEY (or TRANSCRIBER_SHELL_DEEPL_API_KEY) in .env.

Free-tier endpoint: https://api-free.deepl.com/v2/translate
Pro-tier endpoint:  https://api.deepl.com/v2/translate
The correct endpoint is selected automatically based on whether the key ends
with ":fx" (free tier keys always do).
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
import json

from transcriber_shell.config import Settings

# Maps our internal language tags (BCP-47 / ISO 639-1 style) to DeepL codes.
# DeepL uses its own variant of language codes; most are straightforward.
_LANG_MAP: dict[str, str] = {
    "english": "EN-US",
    "en": "EN-US",
    "en-us": "EN-US",
    "en-gb": "EN-GB",
    "french": "FR",
    "fr": "FR",
    "german": "DE",
    "de": "DE",
    "spanish": "ES",
    "es": "ES",
    "italian": "IT",
    "it": "IT",
    "dutch": "NL",
    "nl": "NL",
    "latin": None,  # DeepL does not support Latin
    "lat": None,
    "lat-latn": None,
}


def _deepl_lang(target_language: str) -> str:
    key = target_language.lower().strip()
    code = _LANG_MAP.get(key)
    if code is None and key not in _LANG_MAP:
        # Unknown tag — pass through upper-cased and hope DeepL accepts it.
        return target_language.upper()
    if code is None:
        raise ValueError(
            f"DeepL does not support translation to {target_language!r}. "
            "Use an LLM provider (anthropic/gemini/openai) for Latin and other "
            "unsupported target languages."
        )
    return code


def translate_deepl(
    *,
    text: str,
    target_language: str = "English",
    settings: Settings | None = None,
) -> tuple[str, dict[str, int] | None]:
    """Translate *text* to *target_language* via the DeepL REST API.

    Returns (translated_text, usage_dict | None).
    usage_dict has key "characters" with the billed character count.
    """
    s = settings or Settings()
    api_key = s.deepl_api_key
    if not api_key:
        raise RuntimeError(
            "No DeepL API key found. Set DEEPL_API_KEY or "
            "TRANSCRIBER_SHELL_DEEPL_API_KEY in your .env file. "
            "Get a free key at https://www.deepl.com/en/api"
        )

    # Free-tier keys end with ":fx"; select endpoint accordingly.
    base = (
        "https://api-free.deepl.com/v2"
        if api_key.endswith(":fx")
        else "https://api.deepl.com/v2"
    )
    url = f"{base}/translate"
    target_code = _deepl_lang(target_language)

    payload = urllib.parse.urlencode(
        {"text": text, "target_lang": target_code}
    ).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"DeepL-Auth-Key {api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(
            f"DeepL API error {exc.code}: {detail}"
        ) from exc

    translations = body.get("translations", [])
    if not translations:
        raise RuntimeError(f"DeepL returned no translations: {body}")

    translated = translations[0].get("text", "")
    chars = sum(len(t.get("text", "")) for t in translations)
    usage: dict[str, int] = {"characters": chars}
    return translated, usage
