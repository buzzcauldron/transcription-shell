#!/usr/bin/env python3
"""Thin wrapper — delegates to transcriber_shell.xml_tools.tei.

Usage:  python3 yaml_to_tei.py <input.yaml> [<output.xml>]
        python3 yaml_to_tei.py --dir <artifacts_dir> --out-dir <tei_dir>

Or equivalently:  transcriber-shell yaml-to-tei [same args]
"""
import subprocess, sys
sys.exit(subprocess.run(["transcriber-shell", "yaml-to-tei"] + sys.argv[1:]).returncode)
