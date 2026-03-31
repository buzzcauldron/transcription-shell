"""Train LineMaskUNet on latin_documents ``data/`` pairs."""

from __future__ import annotations

import argparse
import json
import random
import warnings
from pathlib import Path

import torch
from torch.utils.data import DataLoader, Dataset

from latin_lineation_mvp.dataset import (
    build_page_sample,
    filter_pairs_with_lines,
    find_page_pairs,
    max_lines_in_pairs,
    split_train_val,
)
from latin_lineation_mvp.model import LineMaskUNet, bce_dice_loss


class PageDataset(Dataset):
    def __init__(
        self,
        pairs: list[tuple[Path, Path]],
        *,
        mask_h: int,
        mask_w: int,
        max_lines: int,
        line_width: int,
    ) -> None:
        self.pairs = pairs
        self.mask_h = mask_h
        self.mask_w = mask_w
        self.max_lines = max_lines
        self.line_width = line_width

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        img_p, xml_p = self.pairs[idx]
        s = build_page_sample(
            img_p,
            xml_p,
            mask_h=self.mask_h,
            mask_w=self.mask_w,
            max_lines=self.max_lines,
            line_width=self.line_width,
        )
        return {
            "image": torch.from_numpy(s.image),
            "masks": torch.from_numpy(s.masks),
            "valid": torch.from_numpy(s.valid),
        }


def train_epoch(
    model: torch.nn.Module,
    loader: DataLoader,
    opt: torch.optim.Optimizer,
    device: torch.device,
) -> float:
    model.train()
    total = 0.0
    n = 0
    for batch in loader:
        x = batch["image"].to(device)
        y = batch["masks"].to(device)
        v = batch["valid"].to(device)
        opt.zero_grad(set_to_none=True)
        logits = model(x)
        loss = bce_dice_loss(logits, y, v)
        loss.backward()
        opt.step()
        total += float(loss.item())
        n += 1
    return total / max(n, 1)


@torch.no_grad()
def eval_epoch(
    model: torch.nn.Module,
    loader: DataLoader,
    device: torch.device,
) -> float:
    model.eval()
    total = 0.0
    n = 0
    for batch in loader:
        x = batch["image"].to(device)
        y = batch["masks"].to(device)
        v = batch["valid"].to(device)
        logits = model(x)
        loss = bce_dice_loss(logits, y, v)
        total += float(loss.item())
        n += 1
    return total / max(n, 1)


def _train_state_path(out: Path) -> Path:
    return out.parent / f"{out.stem}.train.pt"


def _load_train_checkpoint(
    path: Path, device: torch.device
) -> dict:
    try:
        ckpt = torch.load(path, map_location=device, weights_only=False)
    except TypeError:
        ckpt = torch.load(path, map_location=device)
    if not isinstance(ckpt, dict) or "model_state_dict" not in ckpt:
        raise ValueError(f"not a training checkpoint: {path}")
    return ckpt


def main() -> None:
    p = argparse.ArgumentParser(description="Train line mask U-Net on latin_documents data/")
    p.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="Path to latin_documents data/ (paired jpg+xml)",
    )
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--batch-size", type=int, default=1)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--val-ratio", type=float, default=0.2)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--mask-h", type=int, default=256)
    p.add_argument("--mask-w", type=int, default=256)
    p.add_argument("--max-lines", type=int, default=0, help="0 = auto from data")
    p.add_argument("--line-width", type=int, default=4)
    p.add_argument("--out", type=Path, default=Path("line_mask_unet.pt"))
    p.add_argument("--device", default="cpu")
    p.add_argument(
        "--min-lr",
        type=float,
        default=1e-6,
        help="Floor for cosine LR schedule (long runs)",
    )
    p.add_argument(
        "--resume",
        type=str,
        default="",
        metavar="PATH|auto",
        help="Resume from a .train.pt checkpoint (use 'auto' = <out_stem>.train.pt next to --out)",
    )
    args = p.parse_args()

    pairs = filter_pairs_with_lines(find_page_pairs(args.data_dir))
    if len(pairs) < 1:
        raise SystemExit(
            f"no jpg+xml pairs with baselines under {args.data_dir}"
        )
    train_pairs, val_pairs = split_train_val(
        pairs, val_ratio=args.val_ratio, seed=args.seed
    )
    max_lines = args.max_lines or max_lines_in_pairs(pairs)
    max_lines = min(max(max_lines, 8), 128)

    meta = {
        "max_lines": max_lines,
        "mask_h": args.mask_h,
        "mask_w": args.mask_w,
        "line_width": args.line_width,
        "train_pages": len(train_pairs),
        "val_pages": len(val_pairs),
    }
    device = torch.device(args.device)
    if device.type == "cuda":
        torch.backends.cudnn.benchmark = True

    out_path = args.out.expanduser().resolve()
    state_path = _train_state_path(out_path)

    resume_file: Path | None = None
    if args.resume.strip().lower() == "auto":
        if state_path.is_file():
            resume_file = state_path
    elif args.resume.strip():
        resume_file = Path(args.resume).expanduser().resolve()
        if not resume_file.is_file():
            raise SystemExit(f"--resume file not found: {resume_file}")

    start_epoch = 1
    best = float("inf")
    model = LineMaskUNet(in_ch=3, max_lines=max_lines).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        opt, T_max=args.epochs, eta_min=args.min_lr
    )

    if resume_file is not None:
        ckpt = _load_train_checkpoint(resume_file, device)
        sm = ckpt.get("meta", {})
        for k in ("max_lines", "mask_h", "mask_w", "line_width"):
            if sm.get(k) != meta.get(k):
                raise SystemExit(
                    f"resume meta mismatch for {k!r}: checkpoint {sm.get(k)} vs current {meta.get(k)}. "
                    "Use the same --data-dir split (same --seed, --val-ratio, --mask-*, --line-width, --max-lines)."
                )
        model.load_state_dict(ckpt["model_state_dict"])
        opt.load_state_dict(ckpt["optimizer_state_dict"])
        done = int(ckpt["epoch"])
        saved_total = int(ckpt.get("total_epochs", args.epochs))
        if saved_total == int(args.epochs):
            scheduler.load_state_dict(ckpt["scheduler_state_dict"])
        else:
            # Extended or shortened run: rebuild cosine schedule, fast-forward LR steps
            scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
                opt, T_max=args.epochs, eta_min=args.min_lr
            )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                for _ in range(done):
                    scheduler.step()
            print(
                f"Note: --epochs={args.epochs} != checkpoint total_epochs={saved_total}; "
                f"rebuilt LR schedule and stepped {done} times."
            )
        start_epoch = done + 1
        best = float(ckpt.get("best_val_loss", float("inf")))
        if ckpt.get("torch_rng_state") is not None:
            torch.set_rng_state(ckpt["torch_rng_state"].cpu())
        if ckpt.get("python_rng_state") is not None:
            random.setstate(ckpt["python_rng_state"])
        print(
            f"Resumed from {resume_file}  completed_epoch={done}  "
            f"next_epoch={start_epoch}  best_val_loss={best:.4f}"
        )
        if start_epoch > args.epochs:
            print(f"Training already finished ({args.epochs} epochs). Nothing to do.")
            return

    train_ds = PageDataset(
        train_pairs,
        mask_h=args.mask_h,
        mask_w=args.mask_w,
        max_lines=max_lines,
        line_width=args.line_width,
    )
    val_ds = PageDataset(
        val_pairs if val_pairs else train_pairs[:1],
        mask_h=args.mask_h,
        mask_w=args.mask_w,
        max_lines=max_lines,
        line_width=args.line_width,
    )
    pin = device.type == "cuda"
    train_loader = DataLoader(
        train_ds,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=2,
        pin_memory=pin,
    )
    val_loader = DataLoader(
        val_ds, batch_size=1, shuffle=False, num_workers=0, pin_memory=pin
    )

    for epoch in range(start_epoch, args.epochs + 1):
        tr = train_epoch(model, train_loader, opt, device)
        va = eval_epoch(model, val_loader, device)
        scheduler.step()
        lr = opt.param_groups[0]["lr"]
        print(
            f"epoch {epoch:3d}  train_loss={tr:.4f}  val_loss={va:.4f}  lr={lr:.2e}"
        )
        if va < best:
            best = va
            payload = {
                "state_dict": model.state_dict(),
                "meta": meta,
            }
            torch.save(payload, out_path)
            print(f"  saved {out_path}  (best val_loss={best:.4f})")

        train_payload = {
            "epoch": epoch,
            "total_epochs": args.epochs,
            "best_val_loss": best,
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": opt.state_dict(),
            "scheduler_state_dict": scheduler.state_dict(),
            "meta": meta,
            "torch_rng_state": torch.get_rng_state(),
            "python_rng_state": random.getstate(),
        }
        torch.save(train_payload, state_path)
        print(f"  state {state_path}  (resume with --resume auto)")

    meta["epochs_trained"] = args.epochs
    meta["best_val_loss"] = best
    meta_path = out_path.with_suffix(".json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"wrote {meta_path}")


if __name__ == "__main__":
    main()
