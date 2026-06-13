#!/usr/bin/env python3
"""Fine-tune TrOCR on PAGE-XML line manifests (e.g. gothic_bible_train_manifest.txt).

Usage:
    python scripts/train_trocr_htr.py \\
        --train-manifest latin-corpus-gt/gothic_bible_train_manifest.txt \\
        --val-manifest latin-corpus-gt/gothic_bible_val_manifest.txt \\
        --output-dir models/trocr-gothic-bible \\
        --pretrained microsoft/trocr-base-handwritten
"""

from __future__ import annotations

import argparse
import random
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent
if str(_SCRIPT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT))

from pagexml_lines import iter_text_lines  # noqa: E402


def _page_image(xml_path: Path) -> Path | None:
    try:
        root = ET.parse(xml_path).getroot()
    except (ET.ParseError, OSError):
        return None
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"
    page = root.find(f".//{ns}Page")
    if page is None:
        return None
    raw = (page.get("imageFilename") or "").strip()
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_file() else (xml_path.parent / raw).resolve() if (xml_path.parent / raw).is_file() else None


def _collect_samples(manifest: Path, *, max_pages: int | None) -> list[tuple[Path, tuple[int, int, int, int], str]]:
    paths = [Path(line.strip()) for line in manifest.read_text().splitlines() if line.strip()]
    if max_pages is not None and len(paths) > max_pages:
        rng = random.Random(42)
        paths = rng.sample(paths, max_pages)
    samples: list[tuple[Path, tuple[int, int, int, int], str]] = []
    for xml in paths:
        if not xml.is_file():
            continue
        image = _page_image(xml)
        if image is None:
            continue
        for rec in iter_text_lines(xml):
            if not rec.text:
                continue
            samples.append((image, rec.bbox, rec.text))
    return samples


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--train-manifest", type=Path, required=True)
    p.add_argument("--val-manifest", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--pretrained", default="microsoft/trocr-base-handwritten")
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--lr", type=float, default=5e-5)
    p.add_argument("--max-train-pages", type=int, default=None, help="Cap pages for smoke tests")
    p.add_argument("--device", default="auto")
    args = p.parse_args()

    try:
        from PIL import Image
        import torch
        from torch.utils.data import Dataset
        from transformers import (
            Seq2SeqTrainer,
            Seq2SeqTrainingArguments,
            TrOCRProcessor,
            VisionEncoderDecoderModel,
        )
    except ImportError as e:
        sys.exit("Install trocr extra: pip install 'transcriber-shell[trocr]'") from e

    train_samples = _collect_samples(args.train_manifest.expanduser().resolve(), max_pages=args.max_train_pages)
    val_samples = _collect_samples(args.val_manifest.expanduser().resolve(), max_pages=args.max_train_pages)
    if not train_samples:
        sys.exit("No training line samples — check manifests and PAGE-XML Unicode fields")
    print(f"[trocr-train] train lines: {len(train_samples):,}  val lines: {len(val_samples):,}")

    processor = TrOCRProcessor.from_pretrained(args.pretrained)
    model = VisionEncoderDecoderModel.from_pretrained(args.pretrained)

    class LineDataset(Dataset):
        def __init__(self, rows: list[tuple[Path, tuple[int, int, int, int], str]], *, pad: int = 6) -> None:
            self.rows = rows
            self.pad = pad

        def __len__(self) -> int:
            return len(self.rows)

        def __getitem__(self, idx: int):
            image_path, bbox, text = self.rows[idx]
            x0, y0, x1, y1 = bbox
            page = Image.open(image_path).convert("RGB")
            w, h = page.size
            crop = page.crop(
                (
                    max(0, x0 - self.pad),
                    max(0, y0 - self.pad),
                    min(w, x1 + self.pad),
                    min(h, y1 + self.pad),
                )
            )
            pixel_values = processor(images=crop, return_tensors="pt").pixel_values.squeeze()
            labels = processor.tokenizer(
                text,
                padding="max_length",
                max_length=128,
                truncation=True,
                return_tensors="pt",
            ).input_ids.squeeze()
            labels[labels == processor.tokenizer.pad_token_id] = -100
            return {"pixel_values": pixel_values, "labels": labels}

    if args.device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = args.device

    out = args.output_dir.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    training_args = Seq2SeqTrainingArguments(
        output_dir=str(out),
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        eval_strategy="epoch" if val_samples else "no",
        save_strategy="epoch",
        logging_steps=50,
        predict_with_generate=True,
        fp16=device.startswith("cuda"),
        remove_unused_columns=False,
        report_to="none",
    )

    trainer = Seq2SeqTrainer(
        model=model,
        args=training_args,
        train_dataset=LineDataset(train_samples),
        eval_dataset=LineDataset(val_samples) if val_samples else None,
    )
    trainer.train()
    trainer.save_model(str(out))
    processor.save_pretrained(str(out))
    print(f"[trocr-train] saved {out}")


if __name__ == "__main__":
    main()
