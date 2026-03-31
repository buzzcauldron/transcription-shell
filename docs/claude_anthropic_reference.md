# Anthropic (Claude) reference (this project)

Not a general Anthropic product manual — **transcriber-shell** specifics only.

## Auth and env

- **API key:** `ANTHROPIC_API_KEY` or `TRANSCRIBER_SHELL_ANTHROPIC_API_KEY` (see `Settings` in `config.py`).
- **Default model id:** `ANTHROPIC_MODEL` / `TRANSCRIBER_SHELL_ANTHROPIC_MODEL` (see defaults in `config.py`).
- **HTTP timeout:** `TRANSCRIBER_SHELL_ANTHROPIC_TIMEOUT_S` — seconds for the Anthropic client (default 600). Vision plus long YAML can exceed short HTTP defaults.
- **Retries:** `TRANSCRIBER_SHELL_ANTHROPIC_MAX_RETRIES` — extra attempts after the first for **429**, **503**, and **529** only (default 2). Auth and bad-request errors are not retried.
- **HTTP proxy:** When `TRANSCRIBER_SHELL_LLM_USE_PROXY` is true and `TRANSCRIBER_SHELL_LLM_HTTP_PROXY` is set, the Anthropic client uses a custom **httpx** client (same mechanism as OpenAI). Gemini uses scoped `HTTP(S)_PROXY` for the request.

## Code path

- **Adapter:** [`src/transcriber_shell/llm/adapters/anthropic.py`](../src/transcriber_shell/llm/adapters/anthropic.py) — `transcribe_anthropic()` uses the **Messages API** with **streaming** (`messages.stream` → `get_final_text()`). The page image is sent as base64 with `image/jpeg`, `image/png`, `image/webp`, or `image/gif` from the file suffix.
- **Pipeline:** failures are raised as `LLMProviderError` with short, user-facing text (no raw API key material); see [`src/transcriber_shell/pipeline/run.py`](../src/transcriber_shell/pipeline/run.py).
- **Model list:** [`src/transcriber_shell/llm/model_catalog.py`](../src/transcriber_shell/llm/model_catalog.py) — Anthropic entries for the GUI dropdown.

## Streaming and long requests

Non-streaming calls can be rejected when the SDK expects work that may exceed ~10 minutes (large vision plus high `max_tokens`). This adapter always uses **streaming** so long requests are allowed.

## Common failures

| Symptom | What to check |
|--------|----------------|
| Rate limit / 429 | Back off; reduce concurrency; see [Anthropic status](https://status.anthropic.com/). Retries are applied automatically up to the configured max. |
| Overloaded / 529 | Same as above — transient capacity. |
| Invalid or unknown model | Confirm `TRANSCRIBER_SHELL_ANTHROPIC_MODEL` or CLI/GUI override matches a **vision-capable** model id for your account. |
| 401 / auth errors | Key missing, wrong, or revoked — fix `.env` or GUI provider keys. |
| Timeout | Raise `TRANSCRIBER_SHELL_ANTHROPIC_TIMEOUT_S` if runs are legitimately slow; check network stability. |
| Connection errors | Firewall, proxy, or offline — no API reachability. |

---

**Doc workflow inspiration:** [Axel Edin (@axlolo)](https://github.com/axlolo). Adapted for transcriber-shell.
