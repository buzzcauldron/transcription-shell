# shellcheck shell=bash
# Choose a virtualenv that actually has a working kraken.
#
# WHY THIS EXISTS: the previous inline probe accepted any candidate with an
# executable bin/python:
#
#     for cand in "$TSHELL/.venv-lineation" "$HOME/.venv-kraken"; do
#       if [[ -x "$cand/bin/python" ]]; then VENV="$cand"; break; fi
#     done
#
# Two ways that picks the wrong thing, both observed on real machines:
#
#   1. halxvi's .venv-lineation is a Python 3.14 environment with NO torch and
#      NO kraken (3.14 has no torch wheels). bin/python exists, so the probe
#      selected it and the run died at `import kraken` -- after the caller had
#      already committed to that interpreter.
#
#   2. akdeniz carries a stale .venv-kraken with kraken 6.0.3 alongside
#      .venv-lineation with 7.0.2. If the preferred venv is absent the old probe
#      silently fell back two major versions, and segmentation output changes
#      between kraken 6 and 7. Nothing in the logs said which one ran.
#
# So: require kraken to be IMPORTABLE, and say which version was chosen. A
# version difference between machines is a reproducibility bug, not a detail.
pick_kraken_venv() {
  local want="${KRAKEN_VERSION_EXPECTED:-}"
  local chosen="" chosen_ver="" cand ver
  for cand in "$@"; do
    [[ -x "$cand/bin/python" ]] || continue
    ver="$("$cand/bin/python" -c \
      'import importlib.metadata as m; print(m.version("kraken"))' 2>/dev/null)"
    if [[ -z "$ver" ]]; then
      echo "[venv] skip $cand -- python present but kraken not importable" >&2
      continue
    fi
    if [[ -n "$want" && "$ver" != "$want" ]]; then
      # Keep it as a fallback, but prefer an exact version match if one exists.
      if [[ -z "$chosen" ]]; then chosen="$cand"; chosen_ver="$ver"; fi
      echo "[venv] note $cand has kraken $ver (wanted $want)" >&2
      continue
    fi
    chosen="$cand"; chosen_ver="$ver"
    break
  done
  if [[ -z "$chosen" ]]; then
    echo "[venv] FATAL: no candidate venv has an importable kraken." >&2
    echo "[venv] tried: $*" >&2
    return 1
  fi
  if [[ -n "$want" && "$chosen_ver" != "$want" ]]; then
    echo "[venv] WARNING: using kraken $chosen_ver but expected $want." >&2
    echo "[venv] WARNING: segmentation output differs across kraken majors --" >&2
    echo "[venv] WARNING: this run is NOT comparable to $want runs." >&2
  fi
  echo "[venv] using $chosen (kraken $chosen_ver)" >&2
  KRAKEN_VENV="$chosen"
  KRAKEN_VENV_VERSION="$chosen_ver"
  printf '%s\n' "$chosen"
}
