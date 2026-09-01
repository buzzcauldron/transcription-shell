from __future__ import annotations

import importlib.util
from pathlib import Path

from transcriber_shell.stylometry.title_genre import classify_by_title

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "computus" / "harvest_signal_layers.py"
SPEC = importlib.util.spec_from_file_location("harvest_signal_layers", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_origin_and_century_buckets() -> None:
    assert MODULE.origin_bucket("Reichenau (Bischoff/Borst)") == "Lake Constance"
    assert MODULE.origin_bucket("Northern France") == "Northern / NE France"
    assert MODULE.origin_bucket(None) == "unknown"
    assert MODULE.century_bin("AD 876 x 900") == "800s"
    assert MODULE.century_bin("1056") == "1000s"
    assert MODULE.century_bin("") == "undated"


def test_title_prior_tags_computus_and_leaves_misc_unmatched() -> None:
    assert classify_by_title("Bede, De temporum ratione (ch. 23)") == "computus"
    assert classify_by_title("anon., Dionysiac Easter Table") is None


def test_even_windows_and_book_sample_are_bounded() -> None:
    text = " ".join(f"w{i}" for i in range(1000))
    wins = MODULE.even_windows(text, n_win=5, win_words=50)
    assert len(wins) == 5
    sampled = MODULE.book_sample(text, n_words=90)
    assert len(sampled.split()) <= 90


def test_dendro_lag_correlation_finds_shifted_series() -> None:
    a = [0.1, 0.2, 0.8, 0.9, 0.7, 0.2, 0.1, 0.15]
    b = [0.8, 0.9, 0.7, 0.2, 0.1, 0.15, 0.1, 0.05]
    hit = MODULE.lag_correlate(a, b, max_lag=3)
    assert hit["overlap"] >= 4
    assert abs(float(hit["r"])) > 0.5
