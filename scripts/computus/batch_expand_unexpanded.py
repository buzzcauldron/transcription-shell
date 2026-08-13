#!/usr/bin/env python3
"""Resume-safe expand-diplomatic over latin-ms-workspace jobs.

Converts *_transcription.yaml → TEI, expands pages that lack 04_expanded/*.txt,
writes expanded XML + plain text. Unparseable YAML is marked `.expand_skip`
and counted as skip (not fail). Priority job ids first.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import types
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def _load_yaml_to_tei(tshell_src: Path) -> Callable[[Path, Path], None]:
    try:
        if str(tshell_src) not in sys.path:
            sys.path.insert(0, str(tshell_src))
        from transcriber_shell.xml_tools.tei import yaml_to_tei

        return yaml_to_tei
    except Exception:
        pass
    tables_path = tshell_src / "transcriber_shell" / "xml_tools" / "tables.py"
    tei_path = tshell_src / "transcriber_shell" / "xml_tools" / "tei.py"
    pkg = types.ModuleType("transcriber_shell")
    xml = types.ModuleType("transcriber_shell.xml_tools")
    sys.modules.setdefault("transcriber_shell", pkg)
    sys.modules["transcriber_shell.xml_tools"] = xml
    spec_t = importlib.util.spec_from_file_location(
        "transcriber_shell.xml_tools.tables", tables_path
    )
    assert spec_t and spec_t.loader
    tables = importlib.util.module_from_spec(spec_t)
    sys.modules["transcriber_shell.xml_tools.tables"] = tables
    spec_t.loader.exec_module(tables)
    spec = importlib.util.spec_from_file_location(
        "transcriber_shell.xml_tools.tei", tei_path
    )
    assert spec and spec.loader
    tei = importlib.util.module_from_spec(spec)
    sys.modules["transcriber_shell.xml_tools.tei"] = tei
    spec.loader.exec_module(tei)
    return tei.yaml_to_tei


def _load_expand(expand_root: Path) -> tuple[Any, Any, Any]:
    root_s = str(expand_root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    from dotenv import load_dotenv

    load_dotenv(expand_root / ".env")
    from expand_diplomatic.examples_io import load_examples
    from expand_diplomatic.expander import expand_xml, extract_text_lines

    return expand_xml, extract_text_lines, load_examples


def yaml_has_text(path: Path) -> bool:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(raw.strip()) and ("text:" in raw or "Unicode" in raw)


LLM_EXPAND_BACKENDS = frozenset({"anthropic", "gemini", "groq", "local"})


def yaml_ready_for_expand(path: Path, *, backend: str = "rules") -> bool:
    """Rules expand runs on diplomatic HTR before LLM cleanup.

    LLM backends still skip HTR-only drafts and ``.needs_llm`` markers.
    """
    be = (backend or "rules").strip().lower()
    if be not in LLM_EXPAND_BACKENDS:
        return True
    if (path.parent / ".needs_llm").is_file():
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return False
    return "htr_only" not in head


def expand_skip_path(yaml_path: Path) -> Path:
    return yaml_path.parent / ".expand_skip"


def mark_expand_skip(yaml_path: Path, reason: str) -> None:
    dest = expand_skip_path(yaml_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(reason.strip()[:800] + "\n", encoding="utf-8")


ARTIFACT_DIR_NAMES = ("03_artifacts_2500", "03_artifacts")


def job_artifacts_dir(job: Path) -> Path | None:
    """Prefer ``03_artifacts_2500`` (akdeniz HTR) then ``03_artifacts`` (local jobs)."""
    for name in ARTIFACT_DIR_NAMES:
        p = job / name
        if p.is_dir():
            return p
    return None


def job_ids(jobs_root: Path) -> list[str]:
    ids = []
    for p in sorted(jobs_root.iterdir()):
        if p.is_dir() and job_artifacts_dir(p) is not None:
            ids.append(p.name)
    return ids


def order_jobs(all_ids: list[str], priority: list[str]) -> list[str]:
    seen = set()
    ordered: list[str] = []
    for jid in priority:
        if jid in all_ids and jid not in seen:
            ordered.append(jid)
            seen.add(jid)
    for jid in all_ids:
        if jid not in seen:
            ordered.append(jid)
    return ordered


def expand_one(
    tei_path: Path,
    out_xml: Path,
    out_txt: Path,
    *,
    expand_xml,
    extract_text_lines,
    examples: list[dict[str, str]],
    model: str,
    api_key: str | None,
    backend: str,
    modality: str,
    whole_document: bool,
    passes: int,
) -> tuple[str, str]:
    xml_in = tei_path.read_text(encoding="utf-8")
    xml_out = expand_xml(
        xml_in,
        examples,
        model=model,
        api_key=api_key,
        backend=backend,
        modality=modality,
        passes=passes,
        whole_document=whole_document,
        dry_run=False,
    )
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    out_xml.write_text(xml_out, encoding="utf-8")
    text = extract_text_lines(xml_out)
    out_txt.write_text(text, encoding="utf-8")
    return ("ok", tei_path.name)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jobs-root", type=Path, required=True)
    ap.add_argument("--tshell-src", type=Path, required=True)
    ap.add_argument("--expand-root", type=Path, required=True)
    ap.add_argument("--priority-file", type=Path, default=None)
    ap.add_argument("--only-job", default="", help="Expand this job id only (under --jobs-root).")
    ap.add_argument("--limit-jobs", type=int, default=0)
    ap.add_argument("--limit-pages", type=int, default=0)
    ap.add_argument("--parallel-files", type=int, default=2)
    ap.add_argument(
        "--backend",
        default="rules",
        choices=("rules", "anthropic", "gemini", "groq", "local"),
    )
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--modality", default="full")
    ap.add_argument("--passes", type=int, default=1)
    ap.add_argument("--whole-doc", action="store_true", default=True)
    ap.add_argument("--no-whole-doc", action="store_false", dest="whole_doc")
    ap.add_argument("--status-json", type=Path, default=None)
    args = ap.parse_args()

    yaml_to_tei = _load_yaml_to_tei(args.tshell_src)
    expand_xml, extract_text_lines, load_examples = _load_expand(args.expand_root)
    examples_path = args.expand_root / "examples.json"
    examples = load_examples(examples_path) if examples_path.is_file() else []
    api_key: str | None = None
    if args.backend == "anthropic":
        api_key = (
            os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("TRANSCRIBER_SHELL_ANTHROPIC_API_KEY")
            or ""
        ).strip()
        if not api_key:
            print("ANTHROPIC_API_KEY missing", file=sys.stderr)
            return 2
    elif args.backend == "groq":
        api_key = (
            os.environ.get("GROQ_API_KEY")
            or os.environ.get("TRANSCRIBER_SHELL_GROQ_API_KEY")
            or ""
        ).strip()
        if not api_key:
            print("GROQ_API_KEY missing", file=sys.stderr)
            return 2
    elif args.backend in ("rules", "local"):
        api_key = None
    else:
        api_key = (
            os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        ).strip()
        if not api_key:
            print("GEMINI_API_KEY / GOOGLE_API_KEY missing", file=sys.stderr)
            return 2

    os.environ.setdefault("GEMINI_TIMEOUT", "120")
    os.environ.setdefault("GEMINI_RETRY_ATTEMPTS", "3")
    os.environ.setdefault(
        "EXPANDER_MAX_CONCURRENT",
        "8" if args.backend == "rules" else "2",
    )

    priority: list[str] = []
    if args.priority_file and args.priority_file.is_file():
        priority = [
            ln.strip()
            for ln in args.priority_file.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]

    if args.only_job.strip():
        jid = args.only_job.strip()
        jobs = [jid] if job_artifacts_dir(args.jobs_root / jid) is not None else []
        if not jobs:
            print(f"[expand] only-job {jid} not found under {args.jobs_root}", file=sys.stderr)
            return 1
    else:
        jobs = order_jobs(job_ids(args.jobs_root), priority)
        if args.limit_jobs > 0:
            jobs = jobs[: args.limit_jobs]

    status: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "jobs": jobs,
        "ok": 0,
        "skip": 0,
        "fail": 0,
        "empty": 0,
        "failures": [],
    }
    pages_done = 0
    t0 = time.time()

    def flush_status() -> None:
        if args.status_json:
            args.status_json.parent.mkdir(parents=True, exist_ok=True)
            status["elapsed_s"] = round(time.time() - t0, 1)
            args.status_json.write_text(
                json.dumps(status, indent=2) + "\n", encoding="utf-8"
            )

    print(
        f"[expand] jobs={len(jobs)} backend={args.backend} parallel={args.parallel_files} "
        f"model={args.model} whole_doc={args.whole_doc}",
        flush=True,
    )

    for jid in jobs:
        job = args.jobs_root / jid
        artifacts = job_artifacts_dir(job)
        if artifacts is None:
            print(f"[job] {jid}: no artifacts dir", flush=True)
            continue
        tei_dir = job / ".tei_stage"
        exp_dir = job / "04_expanded"
        tei_dir.mkdir(parents=True, exist_ok=True)
        exp_dir.mkdir(parents=True, exist_ok=True)

        pending: list[tuple[Path, Path, Path]] = []
        skip_tei = 0
        for yf in sorted(artifacts.rglob("*_transcription.yaml")):
            if any(part.startswith(".") for part in yf.relative_to(artifacts).parts):
                continue
            stem = yf.stem.replace("_transcription", "")
            out_txt = exp_dir / f"{stem}_expanded.txt"
            if out_txt.is_file() and out_txt.stat().st_size > 0:
                status["skip"] += 1
                continue
            if expand_skip_path(yf).is_file():
                status["skip"] += 1
                continue
            if not yaml_has_text(yf):
                status["empty"] += 1
                continue
            if not yaml_ready_for_expand(yf, backend=args.backend):
                status["skip"] += 1
                continue
            tei_path = tei_dir / f"{stem}_tei.xml"
            try:
                yaml_to_tei(yf, tei_path)
            except Exception as exc:
                mark_expand_skip(yf, f"skip_tei: {type(exc).__name__}: {exc}")
                status["skip"] += 1
                skip_tei += 1
                continue
            pending.append((tei_path, exp_dir / f"{stem}_tei_expanded.xml", out_txt))

        if not pending:
            print(
                f"[job] {jid}: nothing pending skip_tei={skip_tei}",
                flush=True,
            )
            flush_status()
            continue

        if args.limit_pages > 0:
            remain = args.limit_pages - pages_done
            if remain <= 0:
                print("[expand] page limit reached", flush=True)
                break
            pending = pending[:remain]

        print(
            f"[job] {jid}: expand {len(pending)} pages skip_tei={skip_tei}",
            flush=True,
        )
        workers = max(1, min(args.parallel_files, 16 if args.backend == "rules" else 4))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {
                pool.submit(
                    expand_one,
                    tei,
                    xml_out,
                    txt,
                    expand_xml=expand_xml,
                    extract_text_lines=extract_text_lines,
                    examples=examples,
                    model=args.model,
                    api_key=api_key,
                    backend=args.backend,
                    modality=args.modality,
                    whole_document=args.whole_doc,
                    passes=args.passes,
                ): (tei, xml_out, txt)
                for tei, xml_out, txt in pending
            }
            for fut in as_completed(futs):
                tei, xml_out, txt = futs[fut]
                try:
                    kind, name = fut.result()
                    status["ok"] += 1
                    pages_done += 1
                    print(f"[ok] {jid}/{name}", flush=True)
                except Exception as exc:
                    # Unmarked: next pass retries API/transient errors.
                    status["skip"] += 1
                    print(f"[skip expand] {jid}/{tei.name}: {type(exc).__name__}: {exc}", flush=True)
                if pages_done % 10 == 0:
                    flush_status()

        flush_status()
        if args.limit_pages > 0 and pages_done >= args.limit_pages:
            break

    status["finished_at"] = datetime.now(timezone.utc).isoformat()
    flush_status()
    print(
        json.dumps(
            {
                "ok": status["ok"],
                "skip": status["skip"],
                "fail": status["fail"],
                "empty": status["empty"],
            },
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
