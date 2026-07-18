"""Checkpoint registry under ~/.cache/dendro-shell/models."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from dendro_shell.paths import models_dir


MANIFEST = "manifest.json"


def resolve_device(device: str | None = None) -> str:
    if device and device != "auto":
        return device
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def _manifest_path() -> Path:
    return models_dir() / MANIFEST


def load_manifest() -> dict[str, Any]:
    p = _manifest_path()
    if not p.is_file():
        return {"active": None, "models": []}
    return json.loads(p.read_text(encoding="utf-8"))


def save_manifest(data: dict[str, Any]) -> None:
    _manifest_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_models() -> list[dict[str, Any]]:
    return list(load_manifest().get("models", []))


def get_active_checkpoint() -> Path | None:
    m = load_manifest()
    name = m.get("active")
    if not name:
        return None
    for entry in m.get("models", []):
        if entry.get("name") == name:
            p = Path(entry["path"])
            return p if p.is_file() else None
    # fallback path
    p = models_dir() / f"{name}.pt"
    return p if p.is_file() else None


def set_active(name: str) -> None:
    m = load_manifest()
    names = {e["name"] for e in m.get("models", [])}
    if name not in names:
        raise KeyError(f"Unknown model: {name}")
    m["active"] = name
    save_manifest(m)


def register_checkpoint(
    name: str,
    path: Path,
    *,
    metrics: dict[str, float] | None = None,
    base_checkpoint: str | None = None,
    activate: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    m = load_manifest()
    models = m.setdefault("models", [])
    existing = next((e for e in models if e["name"] == name), None)
    if existing and not overwrite:
        raise FileExistsError(
            f"Model {name!r} already exists; pass overwrite=True or choose another name"
        )
    entry = {
        "name": name,
        "path": str(path),
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "metrics": metrics or {},
        "base_checkpoint": base_checkpoint,
    }
    if existing:
        models[models.index(existing)] = entry
    else:
        models.append(entry)
    if activate:
        m["active"] = name
    save_manifest(m)
    return entry
