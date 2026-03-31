# Docker — transcription-shell

Stable way to run the **HTTP API** or an **interactive shell** with **Playwright/Chromium** (Glyph Machina) and Python deps preinstalled. Clone/live in **`transcription-shell/`**; container images stay tagged **`transcriber-shell:<version>`** (matches the PyPI package name). Pattern mirrors [visual-page-editor](https://github.com/buzzcauldron/visual-page-editor) (`docker-run.sh`, `docker-compose`, `.env.docker.example`, `VERSION`).

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (desktop or engine)
- Before **first image build**, vendor the protocol submodule:

```bash
git submodule update --init vendor/transcription-protocol
```

Without `vendor/transcription-protocol`, `docker build` fails at `COPY vendor`.

## One command (recommended)

From the repository root:

```bash
./docker-run.sh
```

Starts the API at **http://127.0.0.1:8765** (override host port with `HOST_API_PORT=8080 ./docker-run.sh`).

- **Rebuild** after git pull or Dockerfile changes: `./docker-run.sh --build`
- **Interactive shell** (repo mounted at `/workspace`): `./docker-run.sh shell`
- **Help:** `./docker-run.sh --help`

The image tag is **`transcriber-shell:<VERSION>`** where `<VERSION>` comes from the [`VERSION`](VERSION) file (also `transcriber-shell:latest` is tagged for convenience).

### API keys

```bash
cp .env.docker.example .env.docker
# edit keys; compose and docker-run.sh load .env.docker when present
```

## Docker Compose

```bash
cp .env.docker.example .env.docker
# Optional: set HOST_API_PORT in .env.docker or shell to map host port
export HOST_API_PORT=8765
docker compose --env-file .env.docker up --build api
```

**Shell profile** (interactive bash):

```bash
docker compose --env-file .env.docker --profile shell run --rm shell
```

`network_mode: host` is **not** used so **Docker Desktop** on macOS/Windows works.

## Build only

```bash
./build-docker.sh
# or
docker build --platform linux/amd64 --build-arg APP_VERSION="$(tr -d '\n' < VERSION)" -t "transcriber-shell:$(tr -d '\n' < VERSION)" .
```

## Image details

- **Base:** `mcr.microsoft.com/playwright/python` (Jammy) — Chromium + system libs for Playwright.
- **Platform:** default **`linux/amd64`** (same as visual-page-editor; Apple Silicon uses emulation).
- **Entrypoint:** if the repo is mounted at `/workspace`, `pip install -e "/workspace[api,gemini,xml-xsd]"` runs so local edits apply.

## What does not run in Docker alone

- **Glyph Machina** is a **remote site**; automation needs **network** access from the container (allowed by default in `docker run` / compose).

## Reverse proxy and upload limits

If you terminate TLS or expose the API behind **nginx** (or similar), set a **maximum request body** size that matches your largest expected batch. The application caps each image part, but **N images × per-part limit** still produces a large total body — configure **`client_max_body_size`** (or equivalent) at the proxy. See also [docs/red_team_review.md](docs/red_team_review.md).

## Troubleshooting

| Issue | What to try |
|--------|-------------|
| Build fails at `COPY vendor` | `git submodule update --init vendor/transcription-protocol` |
| `ModuleNotFoundError` inside shell | Run `pip install -e ".[api]"` from `/workspace` or rely on `entrypoint.sh` |
| Rebuild after dependency change | `./docker-run.sh --build` or `docker compose build --no-cache` |

---

**Doc workflow inspiration:** [Axel Edin (@axlolo)](https://github.com/axlolo). Adapted for transcriber-shell.

