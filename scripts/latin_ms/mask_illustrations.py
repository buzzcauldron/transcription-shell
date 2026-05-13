#!/usr/bin/env python3
"""
mask_illustrations.py — White-out illustrated regions using the eynollah
SBB/eynollah-image-extraction model before lineation.

The model is a TF SavedModel that segments pages into 5 classes:
  0 = background  1 = text  2 = illustration  3 = separator  4 = marginalia

Class 2 pixels are upsampled to the original image resolution and filled
white so that Kraken/U-Net lineation ignores decorated initials and miniatures.

Usage:
    python3 mask_illustrations.py <image> [<image2> ...] [options]

    python3 mask_illustrations.py 01_pages/*.jpg
    python3 mask_illustrations.py page.jpg --out-dir 01_pages_masked/ --model ~/eynollah_models/extract_images
    python3 mask_illustrations.py 01_pages/ --recurse --in-place

Options:
    --model PATH        path to TF SavedModel directory
                        (default: ~/eynollah_models/extract_images)
    --out-dir DIR       write masked images here (default: alongside source)
    --suffix STR        filename suffix for masked output (default: _masked)
    --in-place          overwrite source files (ignores --suffix / --out-dir)
    --classes N[,N...]  class indices to white-out (default: 2)
    --dilate PX         dilate mask by PX pixels before applying (default: 8)
    --recurse           recurse into subdirectories
    --dry-run           print what would happen, do nothing
"""

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

try:
    import numpy as np
except ImportError:
    print("ERROR: numpy not installed", file=sys.stderr)
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow not installed — pip install Pillow", file=sys.stderr)
    sys.exit(1)

MODEL_INPUT_SIZE = 672
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def load_model(model_path: Path):
    try:
        import tensorflow as tf
    except ImportError:
        print("ERROR: TensorFlow not installed — pip install tensorflow", file=sys.stderr)
        sys.exit(1)
    tf.config.set_visible_devices([], "GPU")
    model = tf.saved_model.load(str(model_path))
    infer = model.signatures["serving_default"]
    return infer


def segment_image(infer, img: Image.Image) -> np.ndarray:
    """Return (H_orig, W_orig) integer class map."""
    import tensorflow as tf

    orig_w, orig_h = img.size
    img_r = img.resize((MODEL_INPUT_SIZE, MODEL_INPUT_SIZE), Image.BILINEAR)
    arr = np.array(img_r.convert("RGB"), dtype=np.float32) / 255.0
    inp = arr[np.newaxis]
    out = infer(input_1=tf.constant(inp))
    pred = list(out.values())[0].numpy()[0]  # (672, 672, 5)
    seg_small = np.argmax(pred, axis=-1).astype(np.uint8)  # (672, 672)

    seg_img = Image.fromarray(seg_small, mode="L")
    seg_orig = seg_img.resize((orig_w, orig_h), Image.NEAREST)
    return np.array(seg_orig, dtype=np.uint8)


def dilate_mask(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0:
        return mask
    try:
        from scipy.ndimage import binary_dilation
        struct = np.ones((px * 2 + 1, px * 2 + 1), dtype=bool)
        return binary_dilation(mask, structure=struct).astype(np.uint8)
    except ImportError:
        # Fallback: simple max-pooling approximation via stride tricks
        from numpy.lib.stride_tricks import sliding_window_view
        padded = np.pad(mask, px, mode="edge")
        windows = sliding_window_view(padded, (px * 2 + 1, px * 2 + 1))
        return (windows.max(axis=(-2, -1)) > 0).astype(np.uint8)


def apply_mask(img: Image.Image, seg: np.ndarray, classes: list[int], dilate_px: int) -> Image.Image:
    combined = np.zeros(seg.shape, dtype=np.uint8)
    for c in classes:
        combined |= (seg == c).astype(np.uint8)
    if dilate_px > 0:
        combined = dilate_mask(combined, dilate_px)
    arr = np.array(img.convert("RGB"))
    arr[combined == 1] = 255
    return Image.fromarray(arr)


def find_images(sources: list[Path], recurse: bool) -> list[Path]:
    images = []
    for src in sources:
        if src.is_dir():
            pat = "**/*" if recurse else "*"
            for p in sorted(src.glob(pat)):
                if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                    images.append(p)
        elif src.is_file():
            images.append(src)
        else:
            print(f"  WARNING: {src} not found", file=sys.stderr)
    return images


def dst_path(src: Path, out_dir: Path | None, suffix: str, in_place: bool) -> Path:
    if in_place:
        return src
    name = src.stem + suffix + src.suffix
    base = out_dir if out_dir else src.parent
    return base / name


def main() -> int:
    parser = argparse.ArgumentParser(
        description="White-out illustrated regions using eynollah SBB model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--model", type=Path,
                        default=Path.home() / "eynollah_models" / "extract_images")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--suffix", default="_masked")
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--classes", default="2",
                        help="comma-separated class indices to mask out (default: 2)")
    parser.add_argument("--dilate", type=int, default=8,
                        help="dilate mask by N pixels (default: 8)")
    parser.add_argument("--recurse", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    mask_classes = [int(c.strip()) for c in args.classes.split(",")]

    if not args.model.exists():
        print(f"ERROR: model not found at {args.model}", file=sys.stderr)
        print("  Set --model or place the SavedModel at ~/eynollah_models/extract_images", file=sys.stderr)
        sys.exit(1)

    images = find_images(args.sources, args.recurse)
    if not images:
        print("No images found.", file=sys.stderr)
        return 1

    print(f"==> mask_illustrations: {len(images)} image(s)  "
          f"model={args.model.name}  classes={mask_classes}  dilate={args.dilate}px"
          + ("  [DRY RUN]" if args.dry_run else ""))

    if not args.dry_run:
        print("  Loading TF model...", flush=True)
        infer = load_model(args.model)
        print("  Model loaded.")

    if args.out_dir and not args.dry_run:
        args.out_dir.mkdir(parents=True, exist_ok=True)

    ok = err = 0
    for src in images:
        dst = dst_path(src, args.out_dir, args.suffix, args.in_place)
        if args.dry_run:
            print(f"  ? {src.name} → {dst}")
            ok += 1
            continue
        try:
            img = Image.open(src)
            seg = segment_image(infer, img)
            class_counts = {c: int((seg == c).sum()) for c in mask_classes}
            masked = apply_mask(img, seg, mask_classes, args.dilate)
            masked.save(dst, quality=92 if dst.suffix.lower() in (".jpg", ".jpeg") else None,
                        optimize=True)
            total_px = seg.size
            pct = sum(class_counts.values()) / total_px * 100
            print(f"  ✓ {src.name} → {dst.name}  "
                  f"masked {sum(class_counts.values())} px ({pct:.1f}%)")
            ok += 1
        except Exception as exc:
            print(f"  ✗ {src.name}: {exc}", file=sys.stderr)
            err += 1

    verb = "Would process" if args.dry_run else "Processed"
    print(f"\n  {verb} {ok}, errors {err}")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
