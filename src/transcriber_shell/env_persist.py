"""Merge LLM-related keys into a `.env` file without dropping unrelated lines."""

from __future__ import annotations

import re
from pathlib import Path

# Keys the GUI may write; values are written as KEY=value (no quoting — same as typical .env).
MANAGED_KEYS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "TRANSCRIBER_SHELL_OLLAMA_BASE_URL",
        "TRANSCRIBER_SHELL_LLM_USE_PROXY",
        "TRANSCRIBER_SHELL_LLM_HTTP_PROXY",
        "TRANSCRIBER_SHELL_GM_PERSISTENT_PROFILE",
        "TRANSCRIBER_SHELL_GM_USER_DATA_DIR",
        "TRANSCRIBER_SHELL_LINEATION_BACKEND",
    }
)

_ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=")


def merge_dotenv(path: Path, values: dict[str, str]) -> None:
    """Update or remove managed keys in `path`.

    - For each key in `values` that is in MANAGED_KEYS: non-empty value writes/replaces the
      assignment; empty string removes an existing assignment for that key.
    - Other lines (comments, unrelated vars) are preserved.
    - Creates ``path`` only when there is at least one non-empty managed value to write (new
      ``# transcriber-shell`` block). If ``path`` does not exist and every value is empty, the
      function returns without creating a file.
    - If ``path`` exists and all managed lines are removed with nothing else left, the file is
      truncated to empty (keys cleared).
    """
    to_write = {k: v for k, v in values.items() if k in MANAGED_KEYS}
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()

    out: list[str] = []
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#"):
            m = _ASSIGN.match(s)
            if m:
                name = m.group(1)
                if name in to_write:
                    continue
        out.append(line)

    block: list[str] = []
    for k in sorted(to_write.keys()):
        v = to_write[k]
        if v:
            block.append(f"{k}={v}")

    if block:
        if out and out[-1].strip():
            out.append("")
        out.append("# transcriber-shell (keys saved from GUI)")
        out.extend(block)

    text = "\n".join(out)
    if text:
        text += "\n"

    # Do not create an empty `.env` when there is no file yet and nothing to write.
    if not path.is_file() and not block:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
