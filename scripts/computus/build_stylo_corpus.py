#!/usr/bin/env python3
"""Extract Latin texts and run stylo for harvested/HTR jobs → new corpus tree.

Writes:
  <corpus-out>/texts/<job>_latin.txt
  <corpus-out>/per_target/<job>/  (R stylo outputs when REF exists)
  <corpus-out>/targets.csv
  <corpus-out>/CORPUS_MANIFEST.json
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def word_count(path: Path) -> int:
    if not path.is_file():
        return 0
    return len(path.read_text(encoding="utf-8", errors="replace").split())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--htr-queue", type=Path, required=True)
    ap.add_argument("--corpus-out", type=Path, required=True)
    ap.add_argument("--extract-py", type=Path, required=True)
    ap.add_argument("--stylo-runner", type=Path, default=None)
    ap.add_argument("--stylo-ref", type=Path, default=None)
    ap.add_argument("--min-words", type=int, default=100)
    ap.add_argument("--min-yaml", type=int, default=5)
    ap.add_argument("--skip-stylo", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = load_jsonl(args.htr_queue)
    if args.limit > 0:
        rows = rows[: args.limit]

    texts_dir = args.corpus_out / "texts"
    per_target = args.corpus_out / "per_target"
    logs = args.corpus_out / "logs"
    for d in (texts_dir, per_target, logs):
        d.mkdir(parents=True, exist_ok=True)

    targets: list[dict[str, Any]] = []
    for row in rows:
        jid = row["job_id"]
        job = Path(row.get("job_dir") or "")
        art = job / "03_artifacts_2500"
        if not art.is_dir():
            print(f"[skip] {jid}: no artifacts", file=sys.stderr)
            continue
        n_yaml = sum(1 for _ in art.rglob("*_transcription.yaml"))
        if n_yaml < args.min_yaml:
            print(f"[skip] {jid}: yaml={n_yaml} < {args.min_yaml}", file=sys.stderr)
            continue
        txt = texts_dir / f"{jid}_latin.txt"
        print(f"[extract] {jid} yaml={n_yaml} → {txt}", file=sys.stderr)
        proc = subprocess.run(
            [
                sys.executable,
                str(args.extract_py),
                str(art),
                str(txt),
                "--prefer-expanded",
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"[fail extract] {jid}: {proc.stderr[:300]}", file=sys.stderr)
            continue
        wc = word_count(txt)
        if wc < args.min_words:
            print(f"[skip] {jid}: words={wc} < {args.min_words}", file=sys.stderr)
            continue
        entry = {
            "slug": jid,
            "path": str(txt),
            "label": f"{jid} (web harvest HTR)",
            "words": wc,
            "yaml_pages": n_yaml,
            "material_role": row.get("material_role") or "direct_computus",
            "host": row.get("host"),
            "record_id": row.get("record_id"),
        }
        targets.append(entry)

        if (
            not args.skip_stylo
            and args.stylo_runner
            and args.stylo_runner.is_file()
            and args.stylo_ref
            and args.stylo_ref.is_dir()
        ):
            ms_out = per_target / jid
            ms_out.mkdir(parents=True, exist_ok=True)
            slog = logs / f"stylo_{jid}.log"
            print(f"[stylo] {jid} → {ms_out}", file=sys.stderr)
            with slog.open("w", encoding="utf-8") as lf:
                subprocess.run(
                    [
                        "Rscript",
                        str(args.stylo_runner),
                        str(txt),
                        str(ms_out),
                        jid,
                        str(args.stylo_ref),
                    ],
                    stdout=lf,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            entry["stylo_out"] = str(ms_out)

    # targets.csv for develop_historical_core-style tools
    csv_path = args.corpus_out / "targets.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "slug",
                "path",
                "label",
                "words",
                "yaml_pages",
                "material_role",
                "host",
                "record_id",
            ],
        )
        w.writeheader()
        for t in targets:
            w.writerow({k: t.get(k, "") for k in w.fieldnames})

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_targets": len(targets),
        "min_words": args.min_words,
        "min_yaml": args.min_yaml,
        "corpus_out": str(args.corpus_out),
        "roles": {
            "direct_computus": sum(
                1 for t in targets if t.get("material_role") != "counterpoint"
            ),
            "counterpoint": sum(
                1 for t in targets if t.get("material_role") == "counterpoint"
            ),
        },
        "targets": targets,
    }
    (args.corpus_out / "CORPUS_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    # human note
    md = [
        "# Computus web-harvest HTR corpus",
        "",
        f"Generated: {manifest['generated_at']}",
        f"Targets with extractable text: **{len(targets)}**",
        f"Direct-computus: {manifest['roles']['direct_computus']}",
        f"Counterpoint: {manifest['roles']['counterpoint']}",
        "",
        "Counterpoints must not enter the direct-computus stylometry denominator.",
        "Genre of full-book targets remains mixed; prefer chunk-level genre when scoring.",
        "",
        "## Files",
        "",
        "- `texts/*_latin.txt`",
        "- `targets.csv`",
        "- `per_target/<slug>/` (stylo, when REF available)",
        "- `CORPUS_MANIFEST.json`",
        "",
    ]
    (args.corpus_out / "README.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"n_targets": len(targets), "out": str(args.corpus_out)}, indent=2))
    return 0 if targets else 1


if __name__ == "__main__":
    raise SystemExit(main())
