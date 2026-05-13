#!/usr/bin/env bash
# patch_kraken_segtrain.sh — apply medieval-MS training improvements to Kraken's
# segmentation dataset in the active venv.
#
# Patches applied:
#   1. SegmentationAugmenter: paper-spec params (ColorJitter ±50%, RandomAffine
#      ±0.7°/1%W/2%H/±2% scale, then nothing|sharpen×2|blur σ=1-6px)
#   2. BaselineSet.transform: fixed-height strip rasterisation (removes shapely
#      buffer + skimage.draw.polygon; bounding-box fill for region masks)
#
# Run after every `pip install kraken` or `pip install --upgrade kraken`.
# Usage: source venv/bin/activate && bash patch_kraken_segtrain.sh
set -euo pipefail

VENV_SITE=$(python3 -c "import sysconfig; print(sysconfig.get_path('purelib'))")
TARGET="${VENV_SITE}/kraken/lib/dataset/segmentation.py"

if [[ ! -f "$TARGET" ]]; then
    echo "ERROR: $TARGET not found — is Kraken installed in the active venv?" >&2
    exit 1
fi

cp "$TARGET" "${TARGET}.bak"
echo "  Backed up to ${TARGET}.bak"

cat > "$TARGET" << 'PYEOF'
#
# Copyright 2015 Benjamin Kiessling — Apache 2.0
# Patched: polygon-drawing replaced with fixed-height strips;
#          augmenter updated to paper-spec parameters.
#
import traceback
import multiprocessing as mp
from collections import defaultdict
from ctypes import c_char
from itertools import groupby
from typing import TYPE_CHECKING, Any, Callable

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import Dataset
from torchvision import tv_tensors
from torchvision.transforms import InterpolationMode
from torchvision.transforms import v2

from kraken.lib.dataset.utils import _get_type
from kraken.lib.util import is_bitonal, open_image

if TYPE_CHECKING:
    from kraken.containers import Segmentation

__all__ = ['BaselineSet']

import logging
logger = logging.getLogger(__name__)


class SegmentationAugmenter():
    """
    Paper-spec augmentation pipeline:
      - ColorJitter brightness/contrast/saturation/hue ±50%
      - RandomAffine: rotation ±0.7°, translate (1%W, 2%H), scale ±2%
      - Final: 1/4 nothing | 1/4 sharpen×2 | 1/2 Gaussian blur σ=1-6px
    """
    def __init__(self) -> None:
        self._color = v2.ColorJitter(
            brightness=0.5, contrast=0.5, saturation=0.5, hue=0.5
        )
        self._affine = v2.RandomAffine(
            degrees=0.7,
            translate=(0.01, 0.02),
            scale=(0.98, 1.02),
            interpolation=InterpolationMode.BILINEAR,
            fill=0.0,
        )
        self._sharpen = v2.RandomAdjustSharpness(sharpness_factor=2, p=1.0)
        self._blur = v2.GaussianBlur(kernel_size=7, sigma=(1.0, 6.0))

    def __call__(self, image: torch.Tensor, target: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        mask = tv_tensors.Mask(target)
        image = self._color(image)
        image, mask = self._affine(image, mask)
        r = torch.rand(1).item()
        if r < 0.25:
            pass
        elif r < 0.5:
            image = self._sharpen(image)
        else:
            image = self._blur(image)
        return image.clamp(0.0, 1.0), mask.as_subclass(torch.Tensor)


class BaselineSet(Dataset):
    """Dataset for training a baseline/region segmentation model."""

    def __init__(self,
                 class_mapping: dict[str, dict[str, int]],
                 line_width: int = 4,
                 padding: tuple[int, int, int, int] = (0, 0, 0, 0),
                 im_transforms: Callable[[Any], torch.Tensor] = v2.Identity(),
                 augmentation: bool = False) -> None:
        super().__init__()
        required_keys = {'aux', 'baselines', 'regions'}
        if set(class_mapping.keys()) != required_keys:
            raise ValueError(f'class_mapping must have exactly keys {required_keys}, got {set(class_mapping.keys())}')
        for req in ('_start_separator', '_end_separator'):
            if req not in class_mapping['aux']:
                raise ValueError(f"class_mapping['aux'] must contain '{req}'")
        for section, sub_dict in class_mapping.items():
            for key, val in sub_dict.items():
                if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                    raise ValueError(f'class_mapping[{section!r}][{key!r}] must be a non-negative integer')
        for section in ('baselines', 'regions'):
            sub_dict = class_mapping[section]
            for key, val in sub_dict.items():
                if val < 2:
                    raise ValueError(f'class_mapping[{section!r}][{key!r}] has index {val} < 2 (reserved)')
            if isinstance(sub_dict, defaultdict) and sub_dict.default_factory is not None:
                factory = sub_dict.default_factory
                next_val = factory.n if hasattr(factory, 'n') else factory()
                if next_val < 2:
                    raise ValueError(f'class_mapping[{section!r}] default factory produces index {next_val} < 2')
        baseline_indices = set(class_mapping['baselines'].values())
        region_indices = set(class_mapping['regions'].values())
        overlap = baseline_indices & region_indices
        if overlap:
            raise ValueError(f'Baseline and region class mappings overlap at indices: {overlap}')
        self.imgs = []
        self.pad = padding
        self.targets = []
        self.class_mapping = class_mapping
        self.failed_samples = set()
        self.class_stats = {'baselines': defaultdict(int), 'regions': defaultdict(int)}
        self.aug = SegmentationAugmenter() if augmentation else None
        self.line_width = line_width
        self.transforms = im_transforms
        self.seg_type = None
        self._im_mode = mp.Value(c_char, b'1')

    @property
    def num_classes(self):
        return max(v for d in self.class_mapping.values() for v in d.values()) + 1

    @property
    def canonical_class_mapping(self):
        result = {}
        for section, sub_dict in self.class_mapping.items():
            seen = set()
            result[section] = {k: v for k, v in sub_dict.items() if v not in seen and not seen.add(v)}
        return result

    @property
    def merged_classes(self):
        result = {}
        for section, sub_dict in self.class_mapping.items():
            idx_to_names = defaultdict(list)
            for k, v in sub_dict.items():
                idx_to_names[v].append(k)
            result[section] = {names[0]: names[1:] for names in idx_to_names.values() if len(names) > 1}
        return result

    def add(self, doc: 'Segmentation'):
        if doc.type != 'baselines':
            raise ValueError(f'{doc} is of type {doc.type}. Expected "baselines".')
        baselines_ = defaultdict(list)
        for line in doc.lines:
            tag = _get_type(line.tags)
            try:
                idx = self.class_mapping['baselines'][tag]
                baselines_[idx].append(line.baseline)
                self.class_stats['baselines'][tag] += 1
            except KeyError:
                continue
        regions_ = defaultdict(list)
        for k, v in doc.regions.items():
            try:
                idx = self.class_mapping['regions'][k]
                v = [x for x in v if x.boundary]
                regions_[idx].extend(v)
                self.class_stats['regions'][k] += len(v)
            except KeyError:
                continue
        self.targets.append({'baselines': baselines_, 'regions': regions_})
        self.imgs.append(doc.imagename)

    def _update_im_mode(self, im):
        im_mode = b'R' if im.shape[0] == 3 else b'L'
        if is_bitonal(im):
            im_mode = b'1'
        with self._im_mode.get_lock():
            if im_mode > self._im_mode.value:
                self._im_mode.value = im_mode

    def __getitem__(self, idx):
        if len(self.failed_samples) == len(self):
            raise ValueError(f'All {len(self)} samples invalid.')
        im = self.imgs[idx]
        target = self.targets[idx]
        if not isinstance(im, Image.Image):
            try:
                im = open_image(im)
                im, target, baselines = self.transform(im, target)
                self._update_im_mode(im)
                return {'image': im, 'target': target, 'baselines': baselines}
            except Exception:
                self.failed_samples.add(idx)
                idx = np.random.randint(0, len(self.imgs))
                logger.debug(traceback.format_exc())
                return self[idx]
        im, target, baselines = self.transform(im, target)
        self._update_im_mode(im)
        return {'image': im, 'target': target, 'baselines': baselines}

    @staticmethod
    def _rasterise_baseline_strip(pts, hw, t, cls_idx, t_h, t_w):
        """Vectorised: collect all (x,y) baseline points, then scatter-fill height band."""
        xs_list, ys_list = [], []
        for i in range(max(1, len(pts))):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1] if i + 1 < len(pts) else pts[i]
            n = max(abs(int(x1) - int(x0)), abs(int(y1) - int(y0)), 1) + 1
            xs_list.append(np.round(np.linspace(x0, x1, n)).astype(int))
            ys_list.append(np.round(np.linspace(y0, y1, n)).astype(int))
        xs = np.concatenate(xs_list)
        ys = np.concatenate(ys_list)
        valid = (xs >= 0) & (xs < t_w)
        xs, ys = xs[valid], ys[valid]
        if len(xs) == 0:
            return
        t_np = t[cls_idx].numpy()
        for dy in range(-hw, hw + 1):
            row = np.clip(ys + dy, 0, t_h - 1)
            t_np[row, xs] = 1
        t[cls_idx] = torch.from_numpy(t_np)

    def transform(self, image, target):
        orig_size = image.size
        image = self.transforms(image)
        scale = (image.shape[2] - 2 * self.pad[1]) / orig_size[0]
        t_h = image.shape[1] - 2 * self.pad[1]
        t_w = image.shape[2] - 2 * self.pad[0]
        t = torch.zeros((self.num_classes, t_h, t_w))
        start_sep_cls = self.class_mapping['aux']['_start_separator']
        end_sep_cls = self.class_mapping['aux']['_end_separator']
        hw = max(1, self.line_width // 2)

        scaled_baselines = defaultdict(list)
        for cls_idx, lines in target['baselines'].items():
            for line in lines:
                line = [k for k, g in groupby(line)]
                line = np.array(line, dtype=float) * scale
                scaled_baselines[cls_idx].append(line.tolist())
                if len(line) < 1:
                    continue
                pts = np.round(line).astype(int)
                self._rasterise_baseline_strip(pts, hw, t, cls_idx, t_h, t_w)
                xs = int(np.clip(pts[0, 0], 0, t_w - 1))
                t[start_sep_cls, :, xs] = 1
                t[start_sep_cls, :, xs] *= (1 - t[cls_idx, :, xs])
                xe = int(np.clip(pts[-1, 0], 0, t_w - 1))
                t[end_sep_cls, :, xe] = 1
                t[end_sep_cls, :, xe] *= (1 - t[cls_idx, :, xe])

        for cls_idx, regions in target['regions'].items():
            for region in regions:
                coords = np.array(region.boundary, dtype=float) * scale
                if len(coords) < 2:
                    continue
                x_min = int(np.clip(coords[:, 0].min(), 0, t_w - 1))
                x_max = int(np.clip(coords[:, 0].max(), 0, t_w))
                y_min = int(np.clip(coords[:, 1].min(), 0, t_h - 1))
                y_max = int(np.clip(coords[:, 1].max(), 0, t_h))
                t[cls_idx, y_min:y_max, x_min:x_max] = 1

        target = F.pad(t, self.pad)
        if self.aug:
            image, target = self.aug(image, target)
        return image, target, dict(scaled_baselines)

    def __len__(self):
        return len(self.imgs)

    @property
    def im_mode(self):
        return {b'1': '1', b'L': 'L', b'R': 'RGB'}[self._im_mode.value]
PYEOF

python3 -c "from kraken.lib.dataset.segmentation import BaselineSet, SegmentationAugmenter; print('  Patch verified OK')"
echo "  Applied to: $TARGET"
