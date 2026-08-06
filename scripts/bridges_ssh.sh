#!/usr/bin/env bash
# Shared SSH setup for Bridges automation. Source from other scripts:
#   source "$(dirname "$0")/bridges_ssh.sh"
#
# Optional secrets (Cursor Automation / CI):
#   BRIDGES_SSH_KEY       PEM private key contents
#   BRIDGES_SSH_KEY_FILE  Path to an existing private key
#   BRIDGES_LOGIN         default: bridges2
#   BRIDGES_DTN           default: bridges2-dtn

BRIDGES_LOGIN="${BRIDGES_LOGIN:-bridges2}"
BRIDGES_DTN="${BRIDGES_DTN:-bridges2-dtn}"

_bridges_ssh_key_path=""
if [[ -n "${BRIDGES_SSH_KEY_FILE:-}" && -f "$BRIDGES_SSH_KEY_FILE" ]]; then
  _bridges_ssh_key_path="$BRIDGES_SSH_KEY_FILE"
elif [[ -n "${BRIDGES_SSH_KEY:-}" ]]; then
  _bridges_ssh_key_path="${HOME}/.ssh/bridges_automation_key"
  mkdir -p "${HOME}/.ssh"
  chmod 700 "${HOME}/.ssh"
  printf '%s\n' "$BRIDGES_SSH_KEY" > "$_bridges_ssh_key_path"
  chmod 600 "$_bridges_ssh_key_path"
fi

BRIDGES_SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new)
[[ -n "$_bridges_ssh_key_path" ]] && BRIDGES_SSH_OPTS+=(-i "$_bridges_ssh_key_path")

bridges_ssh() {
  ssh "${BRIDGES_SSH_OPTS[@]}" "$BRIDGES_LOGIN" "$@"
}

bridges_rsync_ssh_e() {
  printf 'ssh'
  local opt
  for opt in "${BRIDGES_SSH_OPTS[@]}"; do
    printf ' %q' "$opt"
  done
}
