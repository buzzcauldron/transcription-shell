# transcriber-shell — Python + Playwright (Chromium for Glyph Machina).
# Pin base to a Playwright image that bundles browser deps (similar stack to CI).
# Build requires: git submodule update --init vendor/transcription-protocol

ARG PLAYWRIGHT_BASE=mcr.microsoft.com/playwright/python:v1.49.1-jammy
FROM ${PLAYWRIGHT_BASE}

LABEL org.opencontainers.image.title="transcriber-shell"
LABEL org.opencontainers.image.description="Glyph Machina lineation + protocol LLM + optional HTTP API"

ARG APP_VERSION=0.1.0
LABEL org.opencontainers.image.version="${APP_VERSION}"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY vendor ./vendor

RUN pip install --no-cache-dir -e ".[api,gemini,xml-xsd]"

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /app

EXPOSE 8765

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "transcriber_shell.api.app:app", "--host", "0.0.0.0", "--port", "8765"]
