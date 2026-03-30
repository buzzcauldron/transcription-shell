#!/usr/bin/env bash
# Build the transcriber-shell Docker image (same tag logic as docker-run.sh).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(tr -d ' \t\n\r' <"$SCRIPT_DIR/VERSION" 2>/dev/null || echo 0.1.0)"
IMAGE_NAME="${TS_IMAGE:-transcriber-shell:${VERSION}}"
PLATFORM="${DOCKER_DEFAULT_PLATFORM:-linux/amd64}"

echo "Building ${IMAGE_NAME} (${PLATFORM})..."
docker build --platform "$PLATFORM" \
  --build-arg "APP_VERSION=$VERSION" \
  -f "$SCRIPT_DIR/Dockerfile" \
  -t "$IMAGE_NAME" \
  "$SCRIPT_DIR"

docker tag "$IMAGE_NAME" "transcriber-shell:latest" 2>/dev/null || true
echo "Done: $IMAGE_NAME (and :latest)"
