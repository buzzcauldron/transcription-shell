#!/usr/bin/env python3
"""Thin wrapper — delegates to transcriber_shell.image_tools.mask.

Usage:  python3 mask_illustrations.py <image> [<image2> ...] [options]

Or equivalently:  transcriber-shell mask-illustrations [same args]
"""
import subprocess, sys
sys.exit(subprocess.run(["transcriber-shell", "mask-illustrations"] + sys.argv[1:]).returncode)
