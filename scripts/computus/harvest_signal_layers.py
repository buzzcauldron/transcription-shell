#!/usr/bin/env python3
"""Harvest-wide signal layers for the computus union (not a single-genre map).

Combines tools already in this repo and sister checkouts:

  holdings / URL     union registry + computus.lat
  origin / century   CitCA manifest
  title prior        transcriber_shell.stylometry.title_genre
  discourse mix      genre_signal (medieval-proof if present, else lexicon)
  book fingerprint   function-word + Latin char n-grams
  series crossdate   dendro-shell lag-correlation on rolling mix
  layout             DocLay YOLO (specified; run separately on image jobs)
  script family      manuscript-fingerprint L0 on PAGE XML (specified)
  keyness            antconc-engine (specified; already used on the 35)
  R stylo            run_stylo_target.R (harvest: clat_107 / clat_114 only)

Writes JSON (+ optional markdown) under web_harvest/reports/.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "references" / "computus-library" / "manifest.json"
DEFAULT_OUT = (
    REPO_ROOT / "references" / "computus-library" / "web_harvest" / "reports"
)


def origin_bucket(origin: str | None) -> str:
    t = (origin or "unknown").lower()
    if "unknown" in t:
        return "unknown"
    if any(x in t for x in ("st. gall", "reichenau", "lake constance", "einsiedeln")):
        return "Lake Constance"
    if any(x in t for x in ("verona", "italy", "montecassino", "lucana")):
        return "Italy"
    if any(
        x in t
        for x in (
            "bavaria",
            "mainz",
            "worms",
            "cologne",
            "weissenburg",
            "germany",
            "insular",
            "regensburg",
        )
    ):
        return "German lands"
    if any(x in t for x in ("loire", "fleury", "western france", "saint-maixent", "lyon")):
        return "Loire / E. France"
    if "southern france" in t:
        return "Southern France"
    if any(
        x in t
        for x in (
            "france",
            "saint-denis",
            "saint-amand",
            "amiens",
            "saint-germain",
            "burgand",
            "burgundy",
        )
    ):
        return "Northern / NE France"
    return origin or "unknown"


def century_bin(date_str: str | None) -> str:
    t = str(date_str or "").lower()
    years = [int(x) for x in re.findall(r"(?:ad\s*)?(\d{3,4})", t)]
    years = [y for y in years if 700 <= y <= 1599]
    if years:
        return f"{(min(years) // 100) * 100}s"
    for needle, label in (
        ("8th", "800s"),
        ("viii", "800s"),
        ("9th", "900s"),
        ("ix", "900s"),
        ("10th", "1000s"),
        ("11th", "1100s"),
        ("12th", "1200s"),
        ("13th", "1300s"),
        ("14th", "1400s"),
        ("15th", "1500s"),
    ):
        if needle in t:
            return label
    return "undated"


def lag_correlate(
    a: list[float],
    b: list[float],
    *,
    max_lag: int = 4,
) -> dict[str, float | int]:
    """Pearson r at integer lags. Same idea as dendro_shell.crossdate."""
    best: dict[str, float | int] = {"lag": 0, "r": 0.0, "overlap": 0}
    if len(a) < 4 or len(b) < 4:
        return best
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            x = a[lag:]
            y = b[: len(x)]
            x = x[: len(y)]
        else:
            y = b[-lag:]
            x = a[: len(y)]
            y = y[: len(x)]
        n = len(x)
        if n < 4:
            continue
        mx = sum(x) / n
        my = sum(y) / n
        num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
        den = math.sqrt(
            sum((xi - mx) ** 2 for xi in x) * sum((yi - my) ** 2 for yi in y)
        )
        if den <= 1e-12:
            continue
        r = num / den
        if abs(r) > abs(float(best["r"])) or (
            abs(r) == abs(float(best["r"])) and n > int(best["overlap"])
        ):
            best = {"lag": lag, "r": round(r, 4), "overlap": n}
    return best


def book_sample(text: str, n_words: int = 6000) -> str:
    """Head/mid/tail sample so whole-book scoring stays bounded."""
    toks = text.split()
    if len(toks) <= n_words:
        return text
    third = max(1, n_words // 3)
    mid = max(0, (len(toks) - third) // 2)
    return " ".join(toks[:third] + toks[mid : mid + third] + toks[-third:])


def even_windows(text: str, n_win: int = 12, win_words: int = 400) -> list[str]:
    """Evenly spaced windows along the book (dendro-style path samples)."""
    toks = text.split()
    if not toks:
        return []
    if len(toks) <= win_words:
        return [" ".join(toks)]
    n_win = min(n_win, max(2, len(toks) // win_words))
    step = (len(toks) - win_words) / (n_win - 1)
    return [
        " ".join(toks[int(i * step) : int(i * step) + win_words])
        for i in range(n_win)
    ]


def citca_layers(manifest_path: Path) -> dict[str, Any]:
    from transcriber_shell.stylometry.title_genre import classify_by_title

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    mss = data.get("manuscripts") or []
    origin_n: Counter[str] = Counter()
    century_n: Counter[str] = Counter()
    title_n: Counter[str] = Counter()
    title_unmatched = 0
    n_works = 0
    rows = []
    for rec in mss:
        origin = origin_bucket(rec.get("origin"))
        century = century_bin(rec.get("date_citca") or rec.get("date_computistical"))
        origin_n[origin] += 1
        century_n[century] += 1
        work_genres: list[str] = []
        for title in rec.get("texts") or []:
            n_works += 1
            g = classify_by_title(str(title))
            if g:
                title_n[g] += 1
                work_genres.append(g)
            else:
                title_unmatched += 1
        rows.append(
            {
                "id": rec.get("id"),
                "display": rec.get("display"),
                "origin": rec.get("origin"),
                "origin_bucket": origin,
                "date": rec.get("date_citca") or rec.get("date_computistical"),
                "century": century,
                "n_indexed_texts": rec.get("text_count_indexed") or len(rec.get("texts") or []),
                "title_genres": work_genres,
            }
        )
    return {
        "n_witnesses": len(mss),
        "n_indexed_works": n_works,
        "title_unmatched": title_unmatched,
        "origin": dict(origin_n.most_common()),
        "century": dict(century_n.most_common()),
        "title_genre": dict(title_n.most_common()),
        "witnesses": rows,
    }


def score_texts(
    texts_dir: Path,
    *,
    prefer_external: bool,
    limit: int,
    chunk_words: int,
) -> dict[str, Any]:
    from transcriber_shell.stylometry.fingerprint import (
        compare_fingerprints,
        compute_fingerprint,
    )
    from transcriber_shell.stylometry.genre_signal import compute_genre_signal

    files = sorted(texts_dir.glob("*.txt"))
    if limit > 0:
        files = files[:limit]
    mix_rows: list[dict[str, Any]] = []
    fps = []
    series: dict[str, list[float]] = {}
    top_n: Counter[str] = Counter()
    secondary_n: Counter[str] = Counter()
    n_near_tie = 0
    for path in files:
        raw = path.read_text(encoding="utf-8", errors="replace")
        windows = even_windows(raw, n_win=12, win_words=max(200, chunk_words // 2))
        doc_id = path.stem
        gs = compute_genre_signal(
            [book_sample(raw)],
            doc_id,
            prefer_external=prefer_external,
            granularity="page",
        )
        rolling = [
            compute_genre_signal(
                [w],
                f"{doc_id}_w{i}",
                prefer_external=prefer_external,
                granularity="page",
            )
            for i, w in enumerate(windows)
        ]
        ordered = gs.ordered_genres
        primary = ordered[0][0] if ordered else ""
        secondary = ordered[1][0] if len(ordered) > 1 else ""
        p1 = ordered[0][1] if ordered else 0.0
        p2 = ordered[1][1] if len(ordered) > 1 else 0.0
        near = abs(p1 - p2) < 0.08
        if near:
            n_near_tie += 1
        if primary:
            top_n[primary] += 1
        if secondary:
            secondary_n[secondary] += 1
        mix_series = [
            float(
                r.genre_probs.get("computus_calendar")
                or r.genre_probs.get("computus")
                or 0.0
            )
            for r in rolling
        ]
        if not mix_series:
            mix_series = [
                float(
                    gs.genre_probs.get("computus_calendar")
                    or gs.genre_probs.get("computus")
                    or 0.0
                )
            ]
        series[doc_id] = mix_series
        fps.append(
            compute_fingerprint(
                [book_sample(raw, 12000)],
                doc_id,
                source_label=str(texts_dir),
            )
        )
        mix_rows.append(
            {
                "id": doc_id,
                "words": len(raw.split()),
                "chunks": len(windows),
                "primary": primary,
                "secondary": secondary,
                "p_primary": round(p1, 4),
                "p_secondary": round(p2, 4),
                "near_tie": near,
                "n_boundaries": len(gs.boundary_indices),
                "window_primaries": [r.top_genre for r in rolling],
                "confidence": gs.confidence,
                "model": gs.model_name,
                "probs": {k: round(v, 4) for k, v in ordered[:6]},
            }
        )

    neighbors = []
    if len(fps) >= 2:
        from transcriber_shell.stylometry.fingerprint import compare_fingerprints

        pairs = []
        for i, fa in enumerate(fps):
            for fb in fps[i + 1 :]:
                c = compare_fingerprints(fa, fb)
                pairs.append(
                    {
                        "a": fa.doc_id,
                        "b": fb.doc_id,
                        "vector_cosine": round(c["vector_cosine"], 4),
                        "fw_cosine": round(c["fw_cosine"], 4),
                    }
                )
        neighbors = sorted(pairs, key=lambda r: r["vector_cosine"])[:12]

    cross = []
    ids = list(series)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            hit = lag_correlate(series[a], series[b])
            if abs(float(hit["r"])) >= 0.35 and int(hit["overlap"]) >= 6:
                cross.append({"a": a, "b": b, **hit})
    cross.sort(key=lambda r: -abs(float(r["r"])))

    return {
        "n_texts": len(files),
        "texts_dir": str(texts_dir),
        "near_tie_share": round(n_near_tie / len(files), 3) if files else 0.0,
        "primary_counts": dict(top_n.most_common()),
        "secondary_counts": dict(secondary_n.most_common()),
        "mix": mix_rows,
        "fingerprint_nearest": neighbors[:12],
        "dendro_crossdate": cross[:20],
    }


def layer_catalog(scored: dict[str, Any] | None) -> list[dict[str, Any]]:
    n_mix = (scored or {}).get("n_texts") or 0
    return [
        {
            "id": "holdings",
            "tool": "computus.lat + union registry",
            "status": "computed",
            "signal": "holding-library geography and confirmed digitization URLs",
        },
        {
            "id": "citca_origin",
            "tool": "CitCA manifest",
            "status": "computed",
            "signal": "origin region and century for 54 dated witnesses only",
        },
        {
            "id": "title_genre",
            "tool": "transcriber_shell.stylometry.title_genre",
            "status": "computed",
            "signal": "work-title prior (CitCA texts[]); not a book-level genre",
        },
        {
            "id": "discourse_mix",
            "tool": "genre_signal / medieval-proof",
            "status": "computed" if n_mix else "ready",
            "n": n_mix,
            "signal": "rolling primary+secondary discourse; near-ties kept",
        },
        {
            "id": "fingerprint",
            "tool": "stylometry.fingerprint (FW + char n-grams)",
            "status": "computed" if n_mix else "ready",
            "n": n_mix,
            "signal": "book-level style neighborhood without R stylo",
        },
        {
            "id": "dendro_series",
            "tool": "dendro-shell crossdate idea on rolling computus_calendar weight",
            "status": "computed" if n_mix else "ready",
            "signal": "lag-correlation of mix series between books; not ring detection",
        },
        {
            "id": "layout",
            "tool": "DocLay YOLO (transcriber_shell.figures.doclay)",
            "status": "specified",
            "signal": "page mix Table/Text/Picture = compilation strategy",
        },
        {
            "id": "script",
            "tool": "manuscript-fingerprint L0 on PAGE XML",
            "status": "specified",
            "signal": "script-family clustering from ink-component heights; skip typebox L1 (print)",
        },
        {
            "id": "keyness",
            "tool": "antconc-engine keyword vs locked historical core",
            "status": "specified",
            "signal": "computus-like vs not, without a whole-book genre call",
        },
        {
            "id": "r_stylo",
            "tool": "stylometry-r run_stylo_target.R",
            "status": "partial",
            "n": 2,
            "signal": "harvest jobs clat_107 / clat_114 only; mixed miscellanies",
        },
    ]


def write_markdown(payload: dict[str, Any], path: Path) -> None:
    citca = payload["citca"]
    scored = payload.get("core_texts") or {}
    lines = [
        "# Harvest signal layers",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "Books containing computus are treated as **genre-mixed miscellanies**.",
        "Layers report primary+secondary (or a distribution), never one forced label.",
        "",
        "## Layer catalog",
        "",
        "| id | tool | status | signal |",
        "|---|---|---|---|",
    ]
    for layer in payload["layers"]:
        lines.append(
            f"| `{layer['id']}` | {layer['tool']} | {layer['status']} | {layer['signal']} |"
        )
    lines += [
        "",
        "## CitCA / local (n = "
        + str(citca["n_witnesses"])
        + ")",
        "",
        f"- Indexed works: {citca['n_indexed_works']} "
        f"(unmatched titles: {citca['title_unmatched']})",
        f"- Origin buckets: {citca['origin']}",
        f"- Century bins: {citca['century']}",
        f"- Title-genre prior: {citca['title_genre']}",
        "",
    ]
    if scored:
        lines += [
            f"## Core extracts scored (`{scored.get('texts_dir')}`, n = {scored.get('n_texts')})",
            "",
            f"- Near-tie primary/secondary: {scored.get('near_tie_share')}",
            f"- Primary counts: {scored.get('primary_counts')}",
            f"- Secondary counts: {scored.get('secondary_counts')}",
            f"- Dendro-style mix crossdates (|r| ≥ 0.35, overlap ≥ 6): "
            f"{len(scored.get('dendro_crossdate') or [])}",
            "",
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--texts-dir", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--chunk-words", type=int, default=400)
    ap.add_argument("--prefer-external", action="store_true")
    ap.add_argument("--no-external", action="store_true")
    args = ap.parse_args()

    src = REPO_ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    citca = citca_layers(args.manifest)
    scored = None
    if args.texts_dir and args.texts_dir.is_dir():
        scored = score_texts(
            args.texts_dir,
            prefer_external=bool(args.prefer_external) and not args.no_external,
            limit=args.limit,
            chunk_words=args.chunk_words,
        )
    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": "genre-mixed miscellanies; primary+secondary; no single whole-book genre",
        "layers": layer_catalog(scored),
        "citca": citca,
        "core_texts": scored,
        "pipeline_snapshot": {
            "union_records": 752,
            "confirmed_urls": 334,
            "unique_jobs_with_image_dir": 285,
            "expand_dirs": 65,
            "core_extracts_expanded_words_m": 4.22,
            "harvest_stylo_jobs": ["clat_107", "clat_114"],
        },
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "signal_layers.json"
    slim = dict(payload)
    slim_citca = dict(citca)
    slim_citca["witnesses"] = [
        {k: w[k] for k in ("id", "origin_bucket", "century", "title_genres") if k in w}
        for w in citca["witnesses"]
    ]
    slim["citca"] = slim_citca
    json_path.write_text(json.dumps(slim, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_markdown(payload, args.out_dir / "SIGNAL_LAYERS.md")
    print(json.dumps(
        {
            "json": str(json_path),
            "n_citca": citca["n_witnesses"],
            "title_genre": citca["title_genre"],
            "n_scored": (scored or {}).get("n_texts"),
            "primary": (scored or {}).get("primary_counts"),
            "near_tie": (scored or {}).get("near_tie_share"),
            "n_crossdate": len((scored or {}).get("dendro_crossdate") or []),
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
