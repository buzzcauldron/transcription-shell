"""Anthropic Messages API — image + system + user text."""

from __future__ import annotations

import base64
import random
import time
from pathlib import Path

import anthropic
from anthropic._exceptions import OverloadedError, ServiceUnavailableError

from transcriber_shell.config import Settings
from transcriber_shell.llm.errors import LLMProviderError
from transcriber_shell.llm.http_client import llm_httpx_client
from transcriber_shell.llm.transcribe import TranscribeResult

# Not exported from anthropic package root in some versions; subclass of APIStatusError.
_RETRYABLE_STATUS = frozenset({429, 503, 529})


def _mime_for_path(path: Path) -> str:
    suf = path.suffix.lower()
    if suf in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suf == ".png":
        return "image/png"
    if suf == ".webp":
        return "image/webp"
    if suf == ".gif":
        return "image/gif"
    return "application/octet-stream"


def _anthropic_user_message(
    *,
    image_path: Path,
    user_text: str,
) -> dict:
    raw = image_path.read_bytes()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    media = _mime_for_path(image_path)
    return {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media,
                    "data": b64,
                },
            },
            {"type": "text", "text": user_text},
        ],
    }


def _format_anthropic_error(exc: BaseException) -> str:
    """Short, safe message (no API key material)."""
    if isinstance(exc, anthropic.AuthenticationError):
        return (
            "Anthropic rejected the API key (authentication failed). "
            "Check ANTHROPIC_API_KEY or TRANSCRIBER_SHELL_ANTHROPIC_API_KEY in .env or the GUI."
        )
    if isinstance(exc, anthropic.PermissionDeniedError):
        return (
            "Anthropic denied access for this API key (403). "
            "Verify the key is active and allowed for the Messages API."
        )
    if isinstance(exc, anthropic.RateLimitError):
        return (
            "Anthropic rate limit (429). Wait and retry, or reduce concurrency; "
            "see https://status.anthropic.com/"
        )
    if isinstance(exc, OverloadedError):
        return (
            "Anthropic is overloaded (529). Retry after a short wait; "
            "see https://status.anthropic.com/"
        )
    if isinstance(exc, ServiceUnavailableError):
        return (
            "Anthropic service unavailable (503). Retry later; "
            "see https://status.anthropic.com/"
        )
    if isinstance(exc, anthropic.APITimeoutError):
        return (
            "Anthropic request timed out. "
            "Increase TRANSCRIBER_SHELL_ANTHROPIC_TIMEOUT_S if vision+YAML runs are legitimately slow."
        )
    if isinstance(exc, anthropic.APIConnectionError):
        return (
            "Could not reach Anthropic (network error). Check connectivity, proxy, and firewall settings."
        )
    if isinstance(exc, anthropic.BadRequestError):
        msg = getattr(exc, "message", None) or str(exc)
        if "model" in msg.lower():
            return (
                "Anthropic rejected the request (invalid model or parameters). "
                "Check TRANSCRIBER_SHELL_ANTHROPIC_MODEL / model override matches a vision-capable model id."
            )
        return f"Anthropic rejected the request (400): {msg}"
    if isinstance(exc, anthropic.UnprocessableEntityError):
        return f"Anthropic could not process the request (422): {getattr(exc, 'message', str(exc))}"
    if isinstance(exc, anthropic.NotFoundError):
        return (
            "Anthropic returned not found (404). The model id may be wrong or retired for your account."
        )
    if isinstance(exc, anthropic.InternalServerError):
        return "Anthropic returned an internal error (5xx). Retry later."
    if isinstance(exc, anthropic.APIStatusError):
        code = getattr(exc, "status_code", None)
        if code == 401:
            return (
                "Anthropic returned 401 (unauthorized). Check that your API key is correct and not expired."
            )
        if code == 403:
            return (
                "Anthropic returned 403 (forbidden). Verify API key permissions and account status."
            )
        if code == 404:
            return (
                "Anthropic returned 404. The model id may be invalid or unavailable."
            )
        if code in _RETRYABLE_STATUS:
            return (
                f"Anthropic returned HTTP {code}. Retry after a short wait; "
                "see https://status.anthropic.com/"
            )
        body = getattr(exc, "body", None)
        detail = ""
        if isinstance(body, dict) and body.get("error", {}).get("message"):
            detail = str(body["error"]["message"])[:300]
        elif getattr(exc, "message", None):
            detail = str(exc.message)[:300]
        if detail:
            return f"Anthropic API error ({code}): {detail}"
        return f"Anthropic API error ({code})."
    if isinstance(exc, anthropic.AnthropicError):
        return f"Anthropic error: {exc!s}"
    return f"Anthropic request failed: {exc!s}"


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (anthropic.RateLimitError, OverloadedError, ServiceUnavailableError)):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        code = getattr(exc, "status_code", None)
        return code in _RETRYABLE_STATUS
    return False


def _sleep_backoff(attempt: int) -> None:
    base = min(32.0, 2.0**attempt)
    time.sleep(base + random.uniform(0.0, 1.0))


def _usage_from_anthropic_message(msg: object) -> dict[str, int] | None:
    u = getattr(msg, "usage", None)
    if u is None:
        return None
    inp = getattr(u, "input_tokens", None)
    out = getattr(u, "output_tokens", None)
    if inp is None and out is None:
        return None
    d: dict[str, int] = {}
    if inp is not None:
        d["input_tokens"] = int(inp)
    if out is not None:
        d["output_tokens"] = int(out)
    if inp is not None and out is not None:
        d["total_tokens"] = int(inp) + int(out)
    return d or None


def transcribe_anthropic(
    *,
    image_path: Path,
    system: str,
    user_text: str,
    model: str | None = None,
    settings: Settings | None = None,
) -> TranscribeResult:
    s = settings or Settings()
    if not s.anthropic_api_key:
        raise RuntimeError(
            "No Anthropic API key: set ANTHROPIC_API_KEY or TRANSCRIBER_SHELL_ANTHROPIC_API_KEY "
            "in .env or paste under Provider keys in the GUI."
        )
    http_client = llm_httpx_client(s, timeout_seconds=s.anthropic_timeout_seconds)
    client_kw = {
        "api_key": s.anthropic_api_key,
        "timeout": s.anthropic_timeout_seconds,
    }
    if http_client is not None:
        client_kw["http_client"] = http_client
    client = anthropic.Anthropic(**client_kw)
    user_message = _anthropic_user_message(image_path=image_path, user_text=user_text)

    model_id = model or s.resolved_model("anthropic")
    max_attempts = 1 + max(0, s.anthropic_max_retries)

    for attempt in range(max_attempts):
        try:
            # Non-streaming requests are rejected when the SDK expects operations may exceed ~10 minutes
            # (large vision + max_tokens). Streaming satisfies long-request requirements.
            with client.messages.stream(
                model=model_id,
                max_tokens=32_000,
                system=system,
                messages=[user_message],
            ) as stream:
                text = stream.get_final_text()
                usage = _usage_from_anthropic_message(stream.get_final_message())
                return TranscribeResult(text, usage)
        except anthropic.APITimeoutError as e:
            raise LLMProviderError(_format_anthropic_error(e)) from e
        except anthropic.APIConnectionError as e:
            raise LLMProviderError(_format_anthropic_error(e)) from e
        except anthropic.APIStatusError as e:
            if _is_retryable(e) and attempt + 1 < max_attempts:
                _sleep_backoff(attempt)
                continue
            raise LLMProviderError(_format_anthropic_error(e)) from e
        except anthropic.AnthropicError as e:
            raise LLMProviderError(_format_anthropic_error(e)) from e
