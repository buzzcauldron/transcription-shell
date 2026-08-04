#!/usr/bin/env bash
# Start watch_transcribe + watch_partial_stylo detached (safe under ssh).
# Required env: STREAM_JOB_DIR (and any STREAM_* the watchers need).

set -euo pipefail

JOB="${STREAM_JOB_DIR:?set STREAM_JOB_DIR}"
SCRIPTS="${STREAM_SCRIPTS_DIR:-$JOB/scripts}"
mkdir -p "$JOB/logs" "$JOB/status"

python3 - <<'PY'
import os, subprocess, sys
from pathlib import Path

job = Path(os.environ["STREAM_JOB_DIR"])
scripts = Path(os.environ.get("STREAM_SCRIPTS_DIR", job / "scripts"))
env = os.environ.copy()

def spawn(name: str, script: Path) -> int:
    log = job / "logs" / f"{name}.nohup.log"
    pid_path = job / "status" / f"{name}.pid"
    with log.open("ab") as lf:
        p = subprocess.Popen(
            [sys.executable, str(script)],
            stdin=subprocess.DEVNULL,
            stdout=lf,
            stderr=subprocess.STDOUT,
            cwd=str(job),
            env=env,
            start_new_session=True,
            close_fds=True,
        )
    pid_path.write_text(f"{p.pid}\n", encoding="utf-8")
    print(f"started {name} pid={p.pid}")
    return p.pid

spawn("watch_transcribe", scripts / "remote_stream_watch_transcribe.py")
spawn("watch_partial_stylo", scripts / "remote_stream_watch_partial_stylo.py")
PY
