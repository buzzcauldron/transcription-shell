#!/usr/bin/env bash
# Thin wrapper — use bridges_start.sh directly.
exec "$(dirname "$0")/bridges_start.sh" "$@"
