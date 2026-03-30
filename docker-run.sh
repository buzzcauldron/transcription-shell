#!/usr/bin/env bash
# Run transcription-shell (package: transcriber-shell) in Docker — API or shell; repo at /workspace.

set -euo pipefail

show_help() {
  cat <<'EOF'
Usage: ./docker-run.sh [options] [api|shell]

  Build (if needed) and run transcriber-shell. Image tag: transcriber-shell:<VERSION>
  from ./VERSION.

Commands:
  api    Run Uvicorn on 0.0.0.0:8765 (default)
  shell  Interactive bash (/workspace = repository)

Options:
  --build, --rebuild   Force docker build
  -h, --help           Show this help

Environment:
  TS_IMAGE              Override image (default: transcriber-shell:<VERSION>)
  HOST_API_PORT         Host port mapped to 8765 (default: 8765)
  DOCKER_DEFAULT_PLATFORM  Default: linux/amd64

Before first build:
  git submodule update --init vendor/transcription-protocol

See README-DOCKER.md
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(tr -d ' \t\n\r' <"$SCRIPT_DIR/VERSION" 2>/dev/null || echo 0.1.0)"
DEFAULT_IMAGE="transcriber-shell:${VERSION}"
IMAGE_NAME="${TS_IMAGE:-$DEFAULT_IMAGE}"
CONTAINER_NAME="${TS_CONTAINER_NAME:-transcriber-shell-run}"
PLATFORM="${DOCKER_DEFAULT_PLATFORM:-linux/amd64}"
HOST_PORT="${HOST_API_PORT:-8765}"

FORCE_BUILD=0
MODE="api"

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)
      show_help
      exit 0
      ;;
    --build|--rebuild)
      FORCE_BUILD=1
      shift
      ;;
    api|shell)
      MODE="$1"
      shift
      break
      ;;
    *)
      echo "Unknown option: $1" >&2
      show_help
      exit 2
      ;;
  esac
done

if [ "$FORCE_BUILD" = 1 ] || ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
  echo "Building Docker image ${IMAGE_NAME} (${PLATFORM})..."
  docker build --platform "$PLATFORM" \
    --build-arg "APP_VERSION=$VERSION" \
    -f "$SCRIPT_DIR/Dockerfile" \
    -t "$IMAGE_NAME" \
    "$SCRIPT_DIR"
  docker tag "$IMAGE_NAME" "transcriber-shell:latest" 2>/dev/null || true
fi

ENV_FILE="$SCRIPT_DIR/.env.docker"
ENV_OPTS=()
[ -f "$ENV_FILE" ] && ENV_OPTS=(--env-file "$ENV_FILE")

VOL_OPTS=(-v "${SCRIPT_DIR}:/workspace:rw")
TTY_OPTS=(-i)
[ -t 0 ] && [ -t 1 ] && TTY_OPTS=(-it)

case "$MODE" in
  api)
    echo "Starting API ${IMAGE_NAME} → http://127.0.0.1:${HOST_PORT}"
    docker run --rm "${TTY_OPTS[@]}" \
      --name "${CONTAINER_NAME}-api" \
      --platform "$PLATFORM" \
      "${ENV_OPTS[@]}" \
      -p "${HOST_PORT}:8765" \
      "${VOL_OPTS[@]}" \
      -w /workspace \
      "$IMAGE_NAME"
    ;;
  shell)
    echo "Interactive shell (${IMAGE_NAME}), /workspace = repo"
    docker run --rm "${TTY_OPTS[@]}" \
      --name "${CONTAINER_NAME}-shell" \
      --platform "$PLATFORM" \
      "${ENV_OPTS[@]}" \
      "${VOL_OPTS[@]}" \
      -w /workspace \
      "$IMAGE_NAME" bash
    ;;
esac
