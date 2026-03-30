from __future__ import annotations

import tempfile
from pathlib import Path

from transcriber_shell.pipeline.batch import discover_images, sanitize_job_id


def test_sanitize_job_id():
    assert sanitize_job_id("foo bar") == "foo_bar"
    assert sanitize_job_id("a" * 200) == "a" * 120


def test_discover_images_empty_dir():
    with tempfile.TemporaryDirectory() as d:
        assert discover_images(d) == []


def test_discover_images_two_files():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        (base / "a.jpg").write_bytes(b"")
        (base / "b.png").write_bytes(b"")
        (base / "skip.txt").write_text("x")
        found = discover_images(d)
        assert len(found) == 2
        assert {p.name for p in found} == {"a.jpg", "b.png"}
