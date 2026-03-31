# Packaging

<!-- transcriber-shell-sync:pyproject.version -->
**Version 0.1.0** · Python 3.11+ — canonical metadata in [`pyproject.toml`](pyproject.toml). After a pull or version bump, run `python scripts/sync_repo_docs.py`.
<!-- transcriber-shell-sync:end:pyproject.version -->

This project is **install-from-source** today. The **git/project directory** is commonly named **`transcription-shell`**; the **Python distribution and CLI** remain **`transcriber-shell`**. Conventions follow [visual-page-editor](https://github.com/buzzcauldron/visual-page-editor) (install scripts + Docker + version file), without RPM/DEB artifacts unless added later.

| Method | Notes |
|--------|--------|
| **pip (editable)** | `pip install -e ".[api,gemini,xml-xsd,dev]"` after `git submodule update --init vendor/transcription-protocol` |
| **Local installer (Unix)** | [`scripts/install-local.sh`](scripts/install-local.sh) — venv, submodule, Chromium |
| **Local installer (Windows)** | [`scripts/install-local.ps1`](scripts/install-local.ps1) — same, PowerShell |
| **Docker** | [`README-DOCKER.md`](README-DOCKER.md), [`Dockerfile`](Dockerfile), [`docker-run.sh`](docker-run.sh), [`docker-compose.yml`](docker-compose.yml) |
| **Line-mask training (optional)** | `pip install -e "examples/latin_lineation_mvp"` — separate package; requires PyTorch |
| **Version** | Canonical: [`pyproject.toml`](pyproject.toml) `[project].version`. Run **`python scripts/sync_repo_docs.py`** to update [`VERSION`](VERSION) and version blurbs in `README.md`, this file, and [`docs/claude.md`](docs/claude.md). CI runs [`scripts/sync_repo_docs.py --check`](scripts/sync_repo_docs.py) and [`scripts/check_version.py`](scripts/check_version.py). |
| **CI** | [`.github/workflows/ci.yml`](.github/workflows/ci.yml): checks out `vendor/transcription-protocol` (recursive submodules), runs [`scripts/check_version.py`](scripts/check_version.py), tests, `python -m build` + `twine check` on sdist/wheel. On **push to `main`**, a **Docker** job builds [`Dockerfile`](Dockerfile) with `APP_VERSION` from `VERSION`. |

**GUI drag-and-drop:** [`tkinterdnd2`](https://pypi.org/project/tkinterdnd2/) is a **core** dependency in [`pyproject.toml`](pyproject.toml). Sdists and wheels declare `Requires-Dist: tkinterdnd2>=0.3.0`, so any `pip install transcriber-shell` (or editable install) pulls it with the rest of the runtime stack. You still need a working **tkinter** on the host (e.g. `python3-tk` on Debian/Ubuntu). For a **frozen** binary (PyInstaller and similar), include Tcl/Tk assets for `tkinterdnd2`, for example `--collect-all tkinterdnd2` alongside your GUI entry point.

---

**Doc workflow inspiration:** [Axel Edin (@axlolo)](https://github.com/axlolo). Adapted for transcriber-shell.

