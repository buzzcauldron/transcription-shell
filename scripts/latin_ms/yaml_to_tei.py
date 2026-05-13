#!/usr/bin/env python3
"""Thin wrapper — delegates to transcriber_shell.xml_tools.tei.

Usage:  python3 yaml_to_tei.py <input.yaml> [<output.xml>]
        python3 yaml_to_tei.py --dir <artifacts_dir> --out-dir <tei_dir>

Or equivalently:  transcriber-shell yaml-to-tei [same args]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from transcriber_shell.xml_tools.tei import convert_dir, yaml_to_tei

__all__ = ["convert_dir", "yaml_to_tei"]


def main() -> int:
    """CLI when run as a script (keeps ``transcriber-shell`` on PATH in sync)."""
    proc = subprocess.run(["transcriber-shell", "yaml-to-tei", *sys.argv[1:]])
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
