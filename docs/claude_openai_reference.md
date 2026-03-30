# OpenAI reference (this project)

Not a general OpenAI product manual — **transcriber-shell** specifics only.

## Auth and env

- **API key:** `OPENAI_API_KEY` or `TRANSCRIBER_SHELL_OPENAI_API_KEY` (see `Settings` in `config.py`).
- **Default model id:** `OPENAI_MODEL` / `TRANSCRIBER_SHELL_OPENAI_MODEL` (default `gpt-4o` in config).

## Code path

- **Adapter:** [`src/transcriber_shell/llm/adapters/openai.py`](../src/transcriber_shell/llm/adapters/openai.py) — `transcribe_openai()` uses **Chat Completions** with a **vision** message: page image as base64 data URL (`image/jpeg`, `image/png`, `image/webp` from file suffix).
- **Model list:** [`src/transcriber_shell/llm/model_catalog.py`](../src/transcriber_shell/llm/model_catalog.py) — `OPENAI_BUDGET_MODELS`, `OPENAI_PREMIUM_MODELS`; GUI dropdowns pull from these.

## Behavior notes

- `max_tokens` is set high for long YAML outputs; adjust in the adapter if you hit limits.
- **No audio** transcription in this package — vision + text for manuscript pages only.

---

**Doc workflow inspiration:** [Axel Edin (@axlolo)](https://github.com/axlolo). Adapted for transcriber-shell.
