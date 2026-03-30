# Packaging

This project is **install-from-source** today. The **git/project directory** is commonly named **`transcription-shell`**; the **Python distribution and CLI** remain **`transcriber-shell`**. Conventions follow [visual-page-editor](https://github.com/buzzcauldron/visual-page-editor) (install scripts + Docker + version file), without RPM/DEB artifacts unless added later.

| Method | Notes |
|--------|--------|
| **pip (editable)** | `pip install -e ".[api,gemini,xml-xsd,dev]"` after `git submodule update --init vendor/transcription-protocol` |
| **Local installer** | [`scripts/install-local.sh`](scripts/install-local.sh) — venv, submodule, Chromium |
| **Docker** | [`README-DOCKER.md`](README-DOCKER.md), [`Dockerfile`](Dockerfile), [`docker-run.sh`](docker-run.sh), [`docker-compose.yml`](docker-compose.yml) |
| **Version** | Single source: [`pyproject.toml`](pyproject.toml) `version` and repo [`VERSION`](VERSION) for Docker tags (keep in sync when releasing) |
