#!/usr/bin/env python3
"""Train a local line-mask U-Net for transcriber-shell using the bundled MVP trainer.

This wraps ``latin_lineation_mvp.train:main`` (same as the ``latin-lineation-train``
console script). Install the optional package first::

    pip install -e examples/latin_lineation_mvp

**Training data directory** is resolved in order:

1. ``--data-dir PATH`` (optional first pass; also accepted by the trainer itself)
2. ``LATIN_DOCUMENTS_DATA`` — path to ``latin_documents/data``
3. ``LATIN_DOCUMENTS_ROOT`` — uses ``<root>/data`` if that directory exists

All other arguments are forwarded unchanged (epochs, device, resume, etc.).

Example::

    export LATIN_DOCUMENTS_ROOT=~/src/latin_documents
    python scripts/train_local_mask_lineation.py --epochs 30 --out ./artifacts/training/line_mask_unet.pt --device cuda

After training, wire transcriber-shell (see printed hint or ``examples/latin_lineation_mvp/README.md``)::

    export TRANSCRIBER_SHELL_LINEATION_BACKEND=mask
    export TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE=latin_lineation_mvp.infer:predict_masks
    export TRANSCRIBER_SHELL_MASK_WEIGHTS_PATH=/absolute/path/to/line_mask_unet.pt
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_data_dir() -> Path:
    d = os.environ.get("LATIN_DOCUMENTS_DATA", "").strip()
    if d:
        p = Path(d).expanduser().resolve()
        if not p.is_dir():
            raise SystemExit(f"LATIN_DOCUMENTS_DATA is not a directory: {p}")
        return p
    root = os.environ.get("LATIN_DOCUMENTS_ROOT", "").strip()
    if root:
        p = Path(root).expanduser().resolve() / "data"
        if p.is_dir():
            return p
        raise SystemExit(
            f"Expected LATIN_DOCUMENTS_ROOT/data to exist: {p}\n"
            "Clone ideasrule/latin_documents or set LATIN_DOCUMENTS_DATA to the data/ folder."
        )
    raise SystemExit(
        "No training data directory. Pass --data-dir, or set LATIN_DOCUMENTS_DATA, "
        "or set LATIN_DOCUMENTS_ROOT (with a data/ subfolder).\n"
        "See docs/latin-documents-training-data.md and examples/latin_lineation_mvp/README.md."
    )


def _has_data_dir_arg(argv: list[str]) -> bool:
    for i, a in enumerate(argv):
        if a == "--data-dir" or a.startswith("--data-dir="):
            return True
        if a == "--data_dir":  # tolerate typo
            return True
    return False


def _print_wire_hint() -> None:
    out = Path("line_mask_unet.pt")
    argv = sys.argv
    for i, a in enumerate(argv):
        if a == "--out" and i + 1 < len(argv):
            out = Path(argv[i + 1]).expanduser().resolve()
            break
        if a.startswith("--out="):
            out = Path(a.split("=", 1)[1]).expanduser().resolve()
            break
    print()
    print("--- Wire transcriber-shell to this checkpoint ---")
    print(f"export TRANSCRIBER_SHELL_LINEATION_BACKEND=mask")
    print(f"export TRANSCRIBER_SHELL_MASK_INFERENCE_CALLABLE=latin_lineation_mvp.infer:predict_masks")
    print(f"export TRANSCRIBER_SHELL_MASK_WEIGHTS_PATH={out}")
    print("(absolute path recommended in .env)")


def main() -> None:
    argv = list(sys.argv[1:])
    for_help = "-h" in argv or "--help" in argv

    try:
        from latin_lineation_mvp.train import main as train_main
    except ImportError as e:
        raise SystemExit(
            "latin_lineation_mvp is not installed. From the repo root:\n"
            "  pip install -e examples/latin_lineation_mvp\n"
            f"Import error: {e}"
        ) from e

    if for_help:
        sys.argv = ["latin-lineation-train", *argv]
        train_main()
        return

    if not _has_data_dir_arg(argv):
        data_dir = _resolve_data_dir()
        sys.argv = ["latin-lineation-train", "--data-dir", str(data_dir), *argv]
    else:
        sys.argv = ["latin-lineation-train", *argv]

    train_main()
    _print_wire_hint()


if __name__ == "__main__":
    main()
