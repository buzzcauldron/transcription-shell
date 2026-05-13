#!/usr/bin/env python3
"""Thin wrapper — delegates to transcriber_shell.image_tools.convert.

Usage:  python3 convert_images.py <src> [<src2> ...] [options]

Or equivalently:  transcriber-shell convert-images [same args]
"""
import subprocess, sys
sys.exit(subprocess.run(["transcriber-shell", "convert-images"] + sys.argv[1:]).returncode)
