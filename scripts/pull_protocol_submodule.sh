#!/usr/bin/env bash
# Pull latest transcription-protocol into vendor/ (benchmark md, stress_report, etc.)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUB="$ROOT/vendor/transcription-protocol"

[[ -e "$SUB/.git" ]] || { echo "Run: git submodule update --init vendor/transcription-protocol"; exit 1; }

cd "$SUB"
git fetch origin
git pull --ff-only origin main
echo "[protocol] at $(git rev-parse --short HEAD): $(git log -1 --format=%s)"
echo "[protocol] stress report: $SUB/benchmark/test-results/stress/stress_report.md"
