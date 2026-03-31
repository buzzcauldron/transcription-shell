# Red team / stress-test notes (transcriber-shell)

Living document: threat assumptions, findings, and mitigations. Not a formal audit.

## Threat model (short)

| Surface | Trust boundary |
|--------|----------------|
| **Desktop GUI** | Single user, local machine; keys in memory and optional `.env`. |
| **CLI** | Same user; shell history may leak args. |
| **HTTP API** | **Untrusted network** if exposed; optional `TRANSCRIBER_SHELL_API_KEY` Bearer gate. |

## Findings and mitigations

### HTTP API — unbounded upload size (addressed)

**Risk:** `await uf.read()` loaded entire parts into memory with no per-file cap → memory exhaustion / DoS.

**Mitigation:** `MAX_UPLOAD_BYTES_PER_IMAGE` (40 MiB per image part) → HTTP 413 if exceeded. `MAX_PROMPT_FIELD_CHARS` on the `prompt` form field → 413 if exceeded.

**Residual:** Total multipart body can still be large: the per-part cap does **not** cap **N × 40 MiB** when many files are uploaded. Put **nginx** or another reverse proxy in front for a **global** body limit if the API is Internet-facing.

**Example (nginx):** set `client_max_body_size 50m;` (or similar) in `http`, `server`, or `location` so the edge rejects oversized bodies before the app. Tune to your max batch size; remember **multipart overhead** and that **N images × 40 MiB** each can still approach **N × 40 MiB** before other fields.

### HTTP API — auth timing

**Risk:** Bearer comparison is constant-time in Python 3 for `==` on strings of equal length only; length mismatch short-circuits. Low severity for API key use case.

**Residual:** Use a reverse proxy TLS termination and rate limiting for public deployments.

### Secrets in logs / UI

**Risk:** Pipeline or LLM errors might echo paths or provider messages; run log is user-visible.

**Mitigation:** Do not log raw API keys in adapters; errors shown in GUI banner are pipeline messages, not env dumps.

**Residual:** User can still paste keys into the run log if they copy them there manually.

### `.env` merge (`env_persist.merge_dotenv`)

**Risk:** Values are written as raw `KEY=value` without shell quoting; values containing newlines could break the file format.

**Mitigation:** GUI strips `\n`/`\r` from key fields on write. Prefer keys without embedded newlines.

**Convention:** In merge-style `.env` lines, avoid wrapping values in **quotes** unless your tooling expects them; the merge helper writes **unquoted** values. Values containing `=` can be ambiguous for some parsers — prefer keys/values without raw `=` inside the value when using this merge path.

**Behavior:** Clearing all managed keys on an existing file that only contained those keys yields an **empty file** (documented in tests).

### GUI — log queue

**Risk:** Background worker can enqueue many log lines; unbounded queues → memory growth on pathological runs.

**Mitigation:** The GUI uses a **bounded** log line queue with a drop policy when full (oldest line dropped to make room; one “truncated” notice). Long runs should still use **Save log** if you need a full transcript.

### GUI — drag-and-drop paths

**Risk:** Dropped paths are filesystem paths; only image extensions and folders are ingested. Symlinks resolve like normal paths.

### Subprocess (`open` / `xdg-open` / `explorer`)

**Risk:** Opens `artifacts_dir` only (from settings), not user-controlled arbitrary strings in normal code paths.

### YAML / prompt parsing

**Risk:** `yaml.safe_load` (where used) reduces arbitrary code execution vs `yaml.load`.

**Residual:** Huge YAML can still consume CPU/memory — API `prompt` field length limit helps for HTTP.

### Dependency / supply chain

**Risk:** Same as any PyPI project — pin versions in production, verify hashes where required.

## Stress ideas (manual / CI)

- Run **batch** with many small images and **Skip GM** to exercise sequential pipeline and disk.
- **API:** concurrent `POST /v1/transcribe` with auth enabled (rate limit at proxy).
- **GUI:** rapid **Transcribe** clicks — `run_id` cancels stale workers; verify log does not interleave confusingly.

## References

- API route: `src/transcriber_shell/api/app.py`
- GUI: `src/transcriber_shell/gui.py`
- Env merge: `src/transcriber_shell/env_persist.py`
