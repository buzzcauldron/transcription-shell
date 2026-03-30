"""Google Gemini — optional extra transcriber-shell[gemini]."""

from __future__ import annotations

from pathlib import Path

from transcriber_shell.config import Settings


def transcribe_gemini(
    *,
    image_path: Path,
    system: str,
    user_text: str,
    model: str | None = None,
    settings: Settings | None = None,
) -> str:
    try:
        import google.generativeai as genai
    except ImportError as e:
        raise RuntimeError("Install gemini extra: pip install 'transcriber-shell[gemini]'") from e

    s = settings or Settings()
    if not s.google_api_key:
        raise RuntimeError("GOOGLE_API_KEY / TRANSCRIBER_SHELL_GOOGLE_API_KEY not set")
    genai.configure(api_key=s.google_api_key)
    raw = image_path.read_bytes()
    suf = image_path.suffix.lower()
    if suf in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    elif suf == ".png":
        mime = "image/png"
    else:
        mime = "image/jpeg"

    model_id = model or s.resolved_model("gemini")
    gen_model = genai.GenerativeModel(model_id, system_instruction=system)
    r = gen_model.generate_content(
        [
            {"mime_type": mime, "data": raw},
            user_text,
        ]
    )
    return (r.text or "").strip()
