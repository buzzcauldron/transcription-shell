"""User-facing directories for library, cache, and models."""

from __future__ import annotations

import os
from pathlib import Path


def home_dir() -> Path:
    return Path(os.path.expanduser("~"))


def default_library_dir() -> Path:
    override = os.environ.get("DENDRO_LIBRARY")
    if override:
        return Path(override).expanduser()
    return home_dir() / "DendroLibrary"


def cache_dir() -> Path:
    override = os.environ.get("DENDRO_CACHE")
    if override:
        return Path(override).expanduser()
    return home_dir() / ".cache" / "dendro-shell"


def models_dir() -> Path:
    d = cache_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def projects_dir() -> Path:
    d = cache_dir() / "projects"
    d.mkdir(parents=True, exist_ok=True)
    return d
