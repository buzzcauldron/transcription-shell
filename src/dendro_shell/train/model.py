"""Small U-Net for ring-boundary segmentation."""

from __future__ import annotations


def TinyUNet(in_ch: int = 1, out_ch: int = 1, base: int = 16):
    import torch
    import torch.nn as nn

    class ConvBlock(nn.Module):
        def __init__(self, a, b):
            super().__init__()
            self.net = nn.Sequential(
                nn.Conv2d(a, b, 3, padding=1),
                nn.BatchNorm2d(b),
                nn.ReLU(inplace=True),
                nn.Conv2d(b, b, 3, padding=1),
                nn.BatchNorm2d(b),
                nn.ReLU(inplace=True),
            )

        def forward(self, x):
            return self.net(x)

    class UNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.d1 = ConvBlock(in_ch, base)
            self.d2 = ConvBlock(base, base * 2)
            self.d3 = ConvBlock(base * 2, base * 4)
            self.pool = nn.MaxPool2d(2)
            self.b = ConvBlock(base * 4, base * 8)
            self.u3 = nn.ConvTranspose2d(base * 8, base * 4, 2, stride=2)
            self.c3 = ConvBlock(base * 8, base * 4)
            self.u2 = nn.ConvTranspose2d(base * 4, base * 2, 2, stride=2)
            self.c2 = ConvBlock(base * 4, base * 2)
            self.u1 = nn.ConvTranspose2d(base * 2, base, 2, stride=2)
            self.c1 = ConvBlock(base * 2, base)
            self.out = nn.Conv2d(base, out_ch, 1)

        def forward(self, x):
            e1 = self.d1(x)
            e2 = self.d2(self.pool(e1))
            e3 = self.d3(self.pool(e2))
            b = self.b(self.pool(e3))
            x = self.u3(b)
            x = self.c3(torch.cat([x, e3], dim=1))
            x = self.u2(x)
            x = self.c2(torch.cat([x, e2], dim=1))
            x = self.u1(x)
            x = self.c1(torch.cat([x, e1], dim=1))
            return self.out(x)

    return UNet()
