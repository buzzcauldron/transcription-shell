"""Shared training job runner for UI and CLI."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from dendro_shell.paths import models_dir
from dendro_shell.train.registry import (
    get_active_checkpoint,
    register_checkpoint,
    resolve_device,
)


@dataclass
class TrainConfig:
    library_dir: str | None = None
    name: str = "boundary_unet"
    epochs: int = 30
    imgsz: int = 512
    batch_size: int = 2
    lr: float = 1e-3
    augment: bool = True
    device: str = "auto"
    val_fraction: float = 0.2
    species: str | None = None
    tag: str | None = None
    fine_tune: bool = True
    activate: bool = True
    overwrite: bool = False
    min_samples_warn: int = 5


@dataclass
class TrainStatus:
    state: str = "idle"  # idle|running|stopping|finished|error
    epoch: int = 0
    epochs: int = 0
    loss: float = 0.0
    val_dice: float = 0.0
    val_f1: float = 0.0
    message: str = ""
    checkpoint: str | None = None
    history: list[dict[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_lock = threading.Lock()
_status = TrainStatus()
_stop = threading.Event()
_thread: threading.Thread | None = None


def get_train_status() -> TrainStatus:
    with _lock:
        return TrainStatus(**_status.to_dict())


def request_stop() -> None:
    _stop.set()
    with _lock:
        if _status.state == "running":
            _status.state = "stopping"
            _status.message = "Stop requested…"


def _set(**kwargs: Any) -> None:
    with _lock:
        for k, v in kwargs.items():
            setattr(_status, k, v)


def _dice(pred, target, eps: float = 1e-6) -> float:
    import torch

    pred = (pred > 0.5).float()
    inter = (pred * target).sum()
    return float((2 * inter + eps) / (pred.sum() + target.sum() + eps))


def _f1(pred, target, eps: float = 1e-6) -> float:
    import torch

    pred = (pred > 0.5).float()
    tp = (pred * target).sum()
    fp = (pred * (1 - target)).sum()
    fn = ((1 - pred) * target).sum()
    return float((2 * tp + eps) / (2 * tp + fp + fn + eps))


def run_training(
    config: TrainConfig,
    *,
    progress_cb: Callable[[TrainStatus], None] | None = None,
    background: bool = False,
) -> TrainStatus:
    """Run U-Net training. If background=True, start a daemon thread and return immediately."""
    global _thread

    def _notify():
        st = get_train_status()
        if progress_cb:
            progress_cb(st)

    def _worker():
        try:
            _run_impl(config, _notify)
        except Exception as e:
            _set(state="error", message=str(e))
            _notify()

    with _lock:
        if _status.state == "running":
            raise RuntimeError("Training already running")
        _stop.clear()
        _status.state = "running"
        _status.epoch = 0
        _status.epochs = config.epochs
        _status.loss = 0.0
        _status.val_dice = 0.0
        _status.val_f1 = 0.0
        _status.message = "Starting…"
        _status.checkpoint = None
        _status.history = []

    if background:
        _thread = threading.Thread(target=_worker, daemon=True)
        _thread.start()
        return get_train_status()

    _worker()
    return get_train_status()


def _run_impl(config: TrainConfig, notify: Callable[[], None]) -> None:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, random_split

    from dendro_shell.train.dataset import RingCropDataset, load_sample_arrays
    from dendro_shell.train.model import TinyUNet

    samples = load_sample_arrays(
        config.library_dir, species=config.species, tag=config.tag
    )
    if not samples:
        raise RuntimeError(
            "Training library is empty. Add corrected projects via 'Add to training set'."
        )
    if len(samples) < config.min_samples_warn:
        _set(
            message=f"Warning: only {len(samples)} sample(s); results may be poor"
        )
        notify()

    device = resolve_device(config.device)
    ds = RingCropDataset(samples, imgsz=config.imgsz, augment=config.augment)
    n_val = max(1, int(len(ds) * config.val_fraction))
    n_train = max(1, len(ds) - n_val)
    train_ds, val_ds = random_split(
        ds, [n_train, n_val], generator=torch.Generator().manual_seed(0)
    )
    train_loader = DataLoader(train_ds, batch_size=config.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=1, shuffle=False)

    model = TinyUNet(in_ch=1, out_ch=1, base=16)
    base_name = None
    if config.fine_tune:
        active = get_active_checkpoint()
        if active and active.is_file():
            ckpt = torch.load(str(active), map_location="cpu", weights_only=False)
            model.load_state_dict(ckpt["state_dict"])
            base_name = active.stem
            _set(message=f"Fine-tuning from {active.name}")
            notify()

    model.to(device)
    opt = torch.optim.Adam(model.parameters(), lr=config.lr)
    bce = nn.BCEWithLogitsLoss()

    history: list[dict[str, float]] = []
    best_dice = -1.0
    out_path = models_dir() / f"{config.name}.pt"

    for epoch in range(1, config.epochs + 1):
        if _stop.is_set():
            _set(state="finished", message="Stopped by user", epoch=epoch - 1)
            notify()
            return
        model.train()
        losses = []
        for xb, yb in train_loader:
            if _stop.is_set():
                break
            xb = xb.to(device)
            yb = yb.to(device)
            opt.zero_grad()
            logits = model(xb)
            loss = bce(logits, yb)
            loss.backward()
            opt.step()
            losses.append(float(loss.item()))
        if _stop.is_set():
            _set(state="finished", message="Stopped by user", epoch=epoch)
            notify()
            return

        model.eval()
        dices, f1s = [], []
        with torch.no_grad():
            for xb, yb in val_loader:
                xb = xb.to(device)
                yb = yb.to(device)
                prob = torch.sigmoid(model(xb))
                dices.append(_dice(prob, yb))
                f1s.append(_f1(prob, yb))
        mean_loss = float(sum(losses) / max(len(losses), 1))
        mean_dice = float(sum(dices) / max(len(dices), 1))
        mean_f1 = float(sum(f1s) / max(len(f1s), 1))
        history.append(
            {"epoch": epoch, "loss": mean_loss, "dice": mean_dice, "f1": mean_f1}
        )
        _set(
            epoch=epoch,
            epochs=config.epochs,
            loss=mean_loss,
            val_dice=mean_dice,
            val_f1=mean_f1,
            history=list(history),
            message=f"Epoch {epoch}/{config.epochs}",
        )
        notify()

        if mean_dice >= best_dice:
            best_dice = mean_dice
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "base_channels": 16,
                    "imgsz": config.imgsz,
                    "metrics": {"dice": mean_dice, "f1": mean_f1, "loss": mean_loss},
                    "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
                out_path,
            )

    metrics = {"dice": best_dice, "f1": history[-1]["f1"] if history else 0.0}
    from dendro_shell.train.registry import load_manifest

    exists = any(e.get("name") == config.name for e in load_manifest().get("models", []))
    save_name = config.name
    save_path = out_path
    if exists and not config.overwrite:
        import shutil

        stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
        save_name = f"{config.name}_{stamp}"
        save_path = models_dir() / f"{save_name}.pt"
        shutil.copy2(out_path, save_path)
        msg = f"Done. Saved as {save_name} (refused overwrite of {config.name})"
    else:
        msg = f"Done. Active model: {save_name}"

    register_checkpoint(
        save_name,
        save_path,
        metrics=metrics,
        base_checkpoint=base_name,
        activate=config.activate,
        overwrite=True,
    )
    _set(
        state="finished",
        message=msg,
        checkpoint=str(save_path),
        val_dice=best_dice,
    )
    notify()
