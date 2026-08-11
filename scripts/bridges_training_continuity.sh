#!/usr/bin/env bash
# Cron entry point for Bridges training continuity (Cursor Automations).
#
#   bash scripts/bridges_training_continuity.sh
#   bash scripts/bridges_training_continuity.sh --dry-run
#
# Requires SSH to Bridges (configure BRIDGES_SSH_KEY in automation secrets).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec bash "$SCRIPT_DIR/bridges_training_automation_remediate.sh" "$@"
