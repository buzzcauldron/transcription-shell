#!/usr/bin/env python3
"""Minimal local HTTP review server for human adjudication of CoMMA line records.

Serves a single-page UI to accept/edit/reject lines from review_queue.jsonl
and appends decisions to adjudicated.jsonl.

Usage:
    python scripts/comma_review.py \\
        --queue /ocean/.../comma-rerecognition/filtered/review_queue.jsonl \\
        --out /ocean/.../comma-rerecognition/adjudicated.jsonl \\
        [--port 8765] \\
        [--crops-root /ocean/.../comma-rerecognition/pilot]

Keyboard shortcuts:
    Enter           Accept current transcription as-is
    Shift+Enter     Focus the text input for editing
    Escape          Reject current line
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _adjudicated_keys(path: Path) -> set[tuple]:
    """Return (ms_id, page_idx, line_idx) tuples already in adjudicated.jsonl."""
    keys: set[tuple] = set()
    for row in _load_jsonl(path):
        keys.add((row.get("ms_id"), row.get("page_idx"), row.get("line_idx")))
    return keys


# ---------------------------------------------------------------------------
# Inline HTML
# ---------------------------------------------------------------------------

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CoMMA Line Review</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #1a1a1e;
    color: #e0dfd8;
    font-family: 'Georgia', serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    min-height: 100vh;
    padding: 2rem 1rem;
  }
  h1 { font-size: 1.2rem; font-weight: normal; color: #aaa; margin-bottom: 1.5rem; }
  #progress { font-size: 0.9rem; color: #888; margin-bottom: 1.5rem; }
  #crop-wrap {
    background: #111;
    border: 1px solid #333;
    border-radius: 4px;
    padding: 0.5rem;
    margin-bottom: 1.5rem;
    max-width: 900px;
    width: 100%;
    display: flex;
    justify-content: center;
    min-height: 60px;
  }
  #crop-img {
    max-width: 100%;
    max-height: 260px;
    object-fit: contain;
    display: block;
  }
  #no-crop {
    color: #555;
    font-style: italic;
    align-self: center;
    font-size: 0.9rem;
  }
  #meta {
    font-size: 0.78rem;
    color: #666;
    margin-bottom: 1rem;
    text-align: center;
  }
  #transcript-wrap {
    width: 100%;
    max-width: 900px;
    margin-bottom: 1.5rem;
  }
  #transcript {
    width: 100%;
    padding: 0.6rem 0.8rem;
    font-size: 1.4rem;
    font-family: 'Georgia', serif;
    background: #23232b;
    color: #f0ece0;
    border: 1px solid #444;
    border-radius: 4px;
    outline: none;
  }
  #transcript:focus { border-color: #888; }
  #buttons {
    display: flex;
    gap: 1rem;
    margin-bottom: 2rem;
  }
  button {
    padding: 0.55rem 1.4rem;
    font-size: 1rem;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-family: inherit;
    transition: opacity 0.15s;
  }
  button:hover { opacity: 0.85; }
  #btn-accept  { background: #2e7d32; color: #fff; }
  #btn-edit    { background: #1565c0; color: #fff; }
  #btn-reject  { background: #6d1a1a; color: #ddd; }
  #hint {
    font-size: 0.78rem;
    color: #555;
    text-align: center;
  }
  #done-msg {
    margin-top: 4rem;
    font-size: 1.2rem;
    color: #aaa;
    text-align: center;
    line-height: 1.8;
  }
</style>
</head>
<body>
<h1>CoMMA Line Review</h1>
<div id="progress"></div>
<div id="done-msg" style="display:none"></div>
<div id="review-area">
  <div id="crop-wrap">
    <img id="crop-img" src="" alt="line crop" style="display:none">
    <span id="no-crop">no crop image</span>
  </div>
  <div id="meta"></div>
  <div id="transcript-wrap">
    <input id="transcript" type="text" autocomplete="off" spellcheck="false">
  </div>
  <div id="buttons">
    <button id="btn-accept">Accept</button>
    <button id="btn-edit">Edit+Accept</button>
    <button id="btn-reject">Reject</button>
  </div>
  <div id="hint">
    Enter&nbsp;=&nbsp;Accept &nbsp;|&nbsp;
    Shift+Enter&nbsp;=&nbsp;focus input &nbsp;|&nbsp;
    Esc&nbsp;=&nbsp;Reject
  </div>
</div>

<script>
let currentLine = null;

function loadNext() {
  fetch('/api/next')
    .then(r => r.json())
    .then(data => {
      if (data.done) {
        document.getElementById('review-area').style.display = 'none';
        document.getElementById('done-msg').style.display = 'block';
        document.getElementById('done-msg').innerHTML =
          'Done &#x2014; ' + data.summary;
        document.getElementById('progress').textContent = '';
        return;
      }
      currentLine = data.line;
      document.getElementById('progress').textContent =
        data.reviewed + ' of ' + data.total + ' reviewed';

      const img = document.getElementById('crop-img');
      const noImg = document.getElementById('no-crop');
      if (data.crop_url) {
        img.src = data.crop_url;
        img.style.display = 'block';
        noImg.style.display = 'none';
      } else {
        img.style.display = 'none';
        noImg.style.display = 'inline';
      }

      document.getElementById('meta').textContent =
        (data.line.ms_id || '') + '  page ' + data.line.page_idx +
        '  line ' + data.line.line_idx +
        '  conf ' + (data.line.confidence || 0).toFixed(3);

      document.getElementById('transcript').value = data.line.our_text || '';
    });
}

function submit(action) {
  if (!currentLine) return;
  const text = document.getElementById('transcript').value;
  fetch('/api/submit', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: action, text: text, line: currentLine})
  }).then(() => loadNext());
}

document.getElementById('btn-accept').addEventListener('click', () => submit('accept'));
document.getElementById('btn-edit').addEventListener('click', () => submit('edit'));
document.getElementById('btn-reject').addEventListener('click', () => submit('reject'));

document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey && document.activeElement.id !== 'transcript') {
    e.preventDefault();
    submit('accept');
  } else if (e.key === 'Enter' && e.shiftKey) {
    e.preventDefault();
    document.getElementById('transcript').focus();
  } else if (e.key === 'Escape') {
    e.preventDefault();
    document.getElementById('transcript').blur();
    submit('reject');
  }
});

loadNext();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class ReviewState:
    def __init__(self, queue: list[dict], out_path: Path, crops_root: Path | None) -> None:
        self.queue = queue
        self.out_path = out_path
        self.crops_root = crops_root
        self.idx = 0
        self.counts = {"accept": 0, "edit": 0, "reject": 0}
        self._lock = threading.Lock()

    @property
    def total(self) -> int:
        return len(self.queue)

    @property
    def reviewed(self) -> int:
        return self.idx

    def current(self) -> dict | None:
        with self._lock:
            if self.idx >= len(self.queue):
                return None
            return self.queue[self.idx]

    def advance(self) -> None:
        with self._lock:
            self.idx += 1

    def record(self, line: dict, action: str, text: str) -> None:
        entry = {
            "ms_id": line.get("ms_id"),
            "page_idx": line.get("page_idx"),
            "line_idx": line.get("line_idx"),
            "text": text,
            "action": action,
            "original_text": line.get("our_text"),
            "confidence": line.get("confidence"),
            "crop_path": line.get("crop_path"),
        }
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.out_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self.counts[action] = self.counts.get(action, 0) + 1


def _make_handler(state: ReviewState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # type: ignore[override]
            pass  # suppress per-request noise

        def _send(self, code: int, ctype: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            if path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", _HTML.encode("utf-8"))
                return

            if path == "/api/next":
                line = state.current()
                if line is None:
                    total_done = state.counts.get("accept", 0) + state.counts.get("edit", 0) + state.counts.get("reject", 0)
                    payload = {
                        "done": True,
                        "summary": (
                            f"{state.counts.get('accept',0)} accepted, "
                            f"{state.counts.get('edit',0)} edited, "
                            f"{state.counts.get('reject',0)} rejected."
                        ),
                    }
                else:
                    crop_url = None
                    cp = line.get("crop_path")
                    if cp and state.crops_root:
                        full = state.crops_root / cp
                        if full.is_file():
                            crop_url = "/crop/" + urllib.parse.quote(cp)
                    payload = {
                        "done": False,
                        "line": line,
                        "crop_url": crop_url,
                        "reviewed": state.reviewed,
                        "total": state.total,
                    }
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", body)
                return

            if path.startswith("/crop/"):
                rel = urllib.parse.unquote(path[len("/crop/"):])
                if state.crops_root:
                    img_path = state.crops_root / rel
                    try:
                        data = img_path.read_bytes()
                        mt = mimetypes.guess_type(str(img_path))[0] or "image/png"
                        self._send(200, mt, data)
                        return
                    except OSError:
                        pass
                self._send(404, "text/plain", b"not found")
                return

            self._send(404, "text/plain", b"not found")

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/submit":
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                action = body.get("action", "reject")
                text = body.get("text", "")
                line = body.get("line", {})
                if action not in ("accept", "edit", "reject"):
                    action = "reject"
                state.record(line, action, text)
                state.advance()
                self._send(200, "application/json", b'{"ok":true}')
            else:
                self._send(404, "text/plain", b"not found")

    return Handler


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--queue", type=Path, required=True,
                    help="review_queue.jsonl produced by comma_filter.py")
    ap.add_argument("--out", type=Path, required=True,
                    help="adjudicated.jsonl (appended to; already-adjudicated lines are skipped)")
    ap.add_argument("--port", type=int, default=8765,
                    help="Local HTTP port (default 8765)")
    ap.add_argument("--crops-root", type=Path, default=None,
                    help="Root directory from which crop_path values are relative "
                         "(usually the same --out-dir used in comma_recognition_pass.py)")
    args = ap.parse_args()

    queue_path = args.queue.expanduser().resolve()
    out_path = args.out.expanduser().resolve()
    crops_root = args.crops_root.expanduser().resolve() if args.crops_root else None

    if not queue_path.is_file():
        sys.exit(f"Queue file not found: {queue_path}")

    all_lines = []
    for row in _load_jsonl(queue_path):
        all_lines.append(row)

    # Skip already adjudicated
    done_keys = _adjudicated_keys(out_path)
    remaining: list[dict] = []
    for row in all_lines:
        key = (row.get("ms_id"), row.get("page_idx"), row.get("line_idx"))
        if key not in done_keys:
            remaining.append(row)

    skipped = len(all_lines) - len(remaining)
    if skipped:
        print(f"[review] skipping {skipped} already-adjudicated lines")
    print(f"[review] {len(remaining)} lines to review")

    if not remaining:
        print("[review] nothing left to review — all lines already adjudicated.")
        return

    state = ReviewState(remaining, out_path, crops_root)
    handler_cls = _make_handler(state)

    server = HTTPServer(("127.0.0.1", args.port), handler_cls)
    url = f"http://localhost:{args.port}"
    print(f"[review] serving at {url}  (Ctrl-C to stop)")

    def _open_browser():
        webbrowser.open(url)

    t = threading.Timer(0.5, _open_browser)
    t.daemon = True
    t.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(
            f"\n[review] stopped. "
            f"accept={state.counts.get('accept',0)}  "
            f"edit={state.counts.get('edit',0)}  "
            f"reject={state.counts.get('reject',0)}"
        )


if __name__ == "__main__":
    main()
