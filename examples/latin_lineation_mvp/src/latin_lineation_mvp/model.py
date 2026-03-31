"""Lightweight U-Net: RGB → per-line masks (fixed max channel count)."""

from __future__ import annotations

import torch
import torch.nn as nn


class ConvBlock(nn.Module):
    def __init__(self, in_ch: int, out_ch: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_ch, out_ch, 3, padding=1),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class LineMaskUNet(nn.Module):
    """Encoder–decoder with skip connections; logits shape ``(B, max_lines, H, W)``."""

    def __init__(self, *, in_ch: int = 3, max_lines: int = 64, base: int = 32) -> None:
        super().__init__()
        self.max_lines = max_lines
        c1, c2, c3, c4 = base, base * 2, base * 4, base * 8
        self.down1 = ConvBlock(in_ch, c1)
        self.pool1 = nn.MaxPool2d(2)
        self.down2 = ConvBlock(c1, c2)
        self.pool2 = nn.MaxPool2d(2)
        self.down3 = ConvBlock(c2, c3)
        self.pool3 = nn.MaxPool2d(2)
        self.mid = ConvBlock(c3, c4)
        self.up3 = nn.ConvTranspose2d(c4, c3, 2, stride=2)
        self.dec3 = ConvBlock(c3 + c3, c3)
        self.up2 = nn.ConvTranspose2d(c3, c2, 2, stride=2)
        self.dec2 = ConvBlock(c2 + c2, c2)
        self.up1 = nn.ConvTranspose2d(c2, c1, 2, stride=2)
        self.dec1 = ConvBlock(c1 + c1, c1)
        self.out = nn.Conv2d(c1, max_lines, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, 3, H, W)
        d1 = self.down1(x)
        p1 = self.pool1(d1)
        d2 = self.down2(p1)
        p2 = self.pool2(d2)
        d3 = self.down3(p2)
        p3 = self.pool3(d3)
        m = self.mid(p3)
        u3 = self.up3(m)
        u3 = self._crop_cat(u3, d3)
        x3 = self.dec3(u3)
        u2 = self.up2(x3)
        u2 = self._crop_cat(u2, d2)
        x2 = self.dec2(u2)
        u1 = self.up1(x2)
        u1 = self._crop_cat(u1, d1)
        x1 = self.dec1(u1)
        return self.out(x1)

    @staticmethod
    def _crop_cat(up: torch.Tensor, skip: torch.Tensor) -> torch.Tensor:
        """Match spatial size after transpose conv."""
        _, _, hu, wu = up.shape
        _, _, hs, ws = skip.shape
        dh, dw = hs - hu, ws - wu
        if dh > 0 or dw > 0:
            skip = skip[
                :,
                :,
                dh // 2 : dh // 2 + hu,
                dw // 2 : dw // 2 + wu,
            ]
        return torch.cat([up, skip], dim=1)


def bce_dice_loss(
    logits: torch.Tensor,
    target: torch.Tensor,
    valid: torch.Tensor,
    *,
    eps: float = 1e-6,
) -> torch.Tensor:
    """Masked loss over line channels: ``valid`` (B, L) 1 for supervised channels."""
    b, l, h, w = logits.shape
    v = valid.view(b, l, 1, 1)
    prob = torch.sigmoid(logits)
    # BCE
    bce = nn.functional.binary_cross_entropy_with_logits(
        logits, target, reduction="none"
    )
    bce = (bce * v).sum() / (v.sum() * h * w + eps)
    # Dice per channel
    inter = (prob * target * v).sum(dim=(2, 3))
    denom = (prob + target).clamp_min(eps) * v
    denom = denom.sum(dim=(2, 3))
    dice = 1.0 - (2.0 * inter + eps) / (denom + eps)
    dice = (dice * valid).sum() / (valid.sum() + eps)
    return bce + dice
