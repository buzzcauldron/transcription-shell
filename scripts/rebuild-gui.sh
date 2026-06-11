#!/usr/bin/env bash
# Reinstall transcriber-shell (editable) and launch the desktop GUI.
#
# Usage:
#   ./scripts/rebuild-gui.sh              # rebuild once, run GUI
#   ./scripts/rebuild-gui.sh --watch      # rebuild + restart GUI when src/ changes
#
# Optional env:
#   TRANSCRIBER_SHELL_EXTRAS   default: api,gemini,xml-xsd,dev,tesseract
#
# historical-ocr is a sibling project (not vendored): tesstrain fine-tuning
# (train_tesseract_pre1800.sh → historical-ocr tess train-gt), print export,
# and newspaper histnews models. Runtime print OCR stays in-process tesseract_htr.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

EXTRAS="${TRANSCRIBER_SHELL_EXTRAS:-api,gemini,xml-xsd,dev,tesseract}"
WATCH=0
GUI_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --watch|-w)
      WATCH=1
      shift
      ;;
    --extras)
      EXTRAS="${2:?--extras requires a value}"
      shift 2
      ;;
    -h|--help)
      sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      GUI_ARGS+=("$1")
      shift
      ;;
  esac
done

ensure_venv() {
  if [[ -d .venv ]] && ! .venv/bin/python -c "import sys" 2>/dev/null; then
    echo "Removing stale .venv (interpreter path invalid); recreating."
    rm -rf .venv
  fi
  if [[ ! -d .venv ]]; then
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
}

init_submodule() {
  if [[ -d .git ]]; then
    git submodule update --init --recursive vendor/transcription-protocol || true
  fi
}

rebuild_package() {
  echo "==> pip install -e \".[${EXTRAS}]\""
  pip install -q -U pip
  pip install -q -e ".[${EXTRAS}]"
}

run_gui() {
  echo "==> transcriber-shell-gui ${GUI_ARGS[*]:-}"
  exec transcriber-shell-gui "${GUI_ARGS[@]}"
}

ensure_venv
init_submodule
rebuild_package

if [[ "$WATCH" -eq 0 ]]; then
  run_gui
fi

echo "==> watch mode: rebuilding when src/transcriber_shell or pyproject.toml changes"
export TRANSCRIBER_SHELL_EXTRAS="$EXTRAS"
export TRANSCRIBER_SHELL_ROOT="$ROOT"
exec .venv/bin/python - "$ROOT" "${GUI_ARGS[@]+"${GUI_ARGS[@]}"}" <<'PY'
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

root = Path(sys.argv[1])
gui_args = sys.argv[2:]
src = root / "src" / "transcriber_shell"
pyproject = root / "pyproject.toml"
extras = os.environ.get("TRANSCRIBER_SHELL_EXTRAS", "api,gemini,xml-xsd,dev,tesseract")
venv_python = root / ".venv" / "bin" / "python"
poll_s = float(os.environ.get("TRANSCRIBER_SHELL_WATCH_POLL", "1.0"))

def tree_mtime(path: Path) -> float:
    if not path.exists():
        return 0.0
    latest = path.stat().st_mtime
    if path.is_dir():
        for child in path.rglob("*.py"):
            try:
                latest = max(latest, child.stat().st_mtime)
            except OSError:
                pass
    return latest

def pip_install() -> None:
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "-q", "-e", f".[{extras}]"],
        cwd=root,
        check=True,
    )

def start_gui() -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    return subprocess.Popen(
        [str(root / ".venv" / "bin" / "transcriber-shell-gui"), *gui_args],
        cwd=root,
        env=env,
    )

def stop_gui(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

last_mtime = 0.0
gui: subprocess.Popen | None = None

while True:
    current = max(tree_mtime(src), tree_mtime(pyproject))
    gui_dead = gui is not None and gui.poll() is not None
    if current != last_mtime or gui is None or gui_dead:
        if current != last_mtime:
            print(f"==> change detected — pip install -e .[{extras}]", flush=True)
            pip_install()
            last_mtime = current
        elif gui_dead:
            print("==> GUI exited — relaunching", flush=True)
        stop_gui(gui)
        gui = start_gui()
    time.sleep(poll_s)
PY
