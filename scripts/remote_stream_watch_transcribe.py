#!/usr/bin/env python3
"""Watch a streaming manuscript acquisition and transcribe pages as they arrive.

Per manuscript, every time:
  lineation → highest HTR checkpoint → LLM cleanup → expand-diplomatic → stylo

Never LLM-only. Blank/endleaf/cover images are skipped before HTR (not failed).
When pages are exhausted and acquire is idle, expand any remaining YAML, extract
expanded text, run stylo for this job, then exit so the next manuscript can start.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageStat

JOB = Path(os.environ["STREAM_JOB_DIR"]).expanduser()
SRC = JOB / "00_sources_chunks"
PAGES = JOB / os.environ.get("STREAM_PAGES_DIR", "01_pages_2500")
ART = JOB / os.environ.get("STREAM_ARTIFACTS_DIR", "03_artifacts_2500")
BATCHES = Path(os.environ.get("STREAM_BATCHES_DIR", str(JOB / "transcription_batches"))).expanduser()
LOG = JOB / "logs" / "watch_transcribe.log"

IMAGE_NAME_CONTAINS = os.environ.get("STREAM_IMAGE_NAME_CONTAINS", "")
MAX_LONG_EDGE = int(os.environ.get("STREAM_MAX_LONG_EDGE", "2500"))
BATCH_SIZE = int(os.environ.get("STREAM_BATCH_SIZE", "8"))
IDLE_LIMIT = int(os.environ.get("STREAM_IDLE_LIMIT", "30"))
DOC_TYPE = os.environ.get("STREAM_DOC_TYPE", "computus_medieval_latin")
PROVIDER = os.environ.get("STREAM_PROVIDER", "anthropic")
# Minimum LLM: correct = HTR draft primary + short text-only fix (~20x cheaper than full).
LLM_MODE = os.environ.get("STREAM_LLM_MODE", "correct").strip() or "correct"
MODEL = os.environ.get("STREAM_MODEL", "").strip()
# Never LLM-only: default to Kraken HTR before LLM (override only with an HTR combo).
HTR_COMBINATION = (
    os.environ.get("STREAM_HTR_COMBINATION", "").strip()
    or os.environ.get("TRANSCRIBER_SHELL_HTR_COMBINATION", "").strip()
    or "kraken_htr"
)
SKIP_LINES_XML_VALIDATION = os.environ.get("STREAM_SKIP_LINES_XML_VALIDATION", "")
# Opt-in only: continuing without lineation enables LLM-without-HTR; default off.
CONTINUE_ON_LINEATION_FAILURE = os.environ.get(
    "STREAM_CONTINUE_ON_LINEATION_FAILURE", ""
).strip().lower() in ("1", "true", "yes", "on")
TSHELL_ROOT = Path(
    os.environ.get("STREAM_TRANSCRIPTION_SHELL_ROOT", "~/Projects/transcription-shell")
).expanduser()
TSHELL_VENV = Path(
    os.environ.get(
        "STREAM_TRANSCRIPTION_SHELL_VENV",
        str(TSHELL_ROOT / ".venv-lineation"),
    )
).expanduser()
EXPAND_ROOT = Path(
    os.environ.get("EXPAND_DIPLOMATIC_ROOT", str(Path.home() / "Projects" / "expand-diplomatic"))
).expanduser()
EXPAND_ENABLED = os.environ.get("STREAM_EXPAND", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
EXPAND_BACKEND = os.environ.get("EXPAND_DIPLOMATIC_BACKEND", "anthropic").strip() or "anthropic"
EXPAND_MODEL = os.environ.get(
    "EXPAND_DIPLOMATIC_MODEL",
    "claude-haiku-4-5-20251001" if EXPAND_BACKEND == "anthropic" else "gemini-2.5-flash",
)
STYLO_REF = Path(
    os.environ.get(
        "STREAM_STYLO_REF",
        "~/Projects/stylometry-r/output/de_luce_r_rescore/reference_set_medieval_mixed",
    )
).expanduser()
STYLO_RUNNER = Path(
    os.environ.get("STREAM_STYLO_RUNNER", "~/Projects/stylometry-r/scripts/run_stylo_target.R")
).expanduser()
STYLO_OUT = Path(
    os.environ.get("STREAM_STYLO_OUT", str(JOB / "05_stylo"))
).expanduser()
EXTRACT_PY = TSHELL_ROOT / "scripts" / "extract_ms_text.py"
EXPAND_PY = TSHELL_ROOT / "scripts" / "computus" / "batch_expand_unexpanded.py"

_HTR_RANKED = (
    "gm-htr-r7-full_best.mlmodel",
    "gm-htr-r6-core_best.mlmodel",
    "gm-htr-computus_best.mlmodel",
    "gm-htr-r5-best.mlmodel",
)
_SEG_RANKED = (
    "gm-seg.mlmodel",
    "kraken-merged-seg.mlmodel_best.mlmodel",
    "kraken-merged-seg.mlmodel",
)

# Filename heuristics: binding/endleaf/cover extras from IIIF (e-codices _eNNN, Vatlib Spiegel, …).
_SKIP_NAME_RE = re.compile(
    r"(?i)("
    r"_e\d+"  # e-codices endleaf / extra
    r"|profilsg|profile"
    r"|vorderspiegel|hinterspiegel|spiegel"
    r"|binding|cover|flyleaf|endleaf|endpaper"
    r"|_999[a-z]?"  # e-codices binding shots
    r")"
)
# Very dark, low-contrast boards/backs (not inked parchment).
BLANK_MAX_MEAN = float(os.environ.get("STREAM_BLANK_MAX_MEAN", "40"))
BLANK_MAX_STD = float(os.environ.get("STREAM_BLANK_MAX_STD", "45"))


def log(msg: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _first_existing(names: tuple[str, ...], env_key: str = "") -> str:
    if env_key:
        explicit = os.environ.get(env_key, "").strip()
        if explicit:
            p = Path(explicit).expanduser()
            if p.is_file() and "/Users/" not in str(p):
                return str(p)
    src = Path.home() / "src"
    for name in names:
        p = src / name
        if p.is_file():
            return str(p)
    return ""


def resolve_highest_htr_model() -> str:
    """Prefer an explicit path, else the highest training-round checkpoint on disk."""
    return _first_existing(_HTR_RANKED, "TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH")


def resolve_seg_model() -> str:
    """Segmentation checkpoint on this host (ignore Mac paths leaked via .env)."""
    return _first_existing(_SEG_RANKED, "TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH")


def resize(src: Path, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return False
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            w, h = im.size
            scale = min(1.0, MAX_LONG_EDGE / max(w, h))
            if scale < 1.0:
                im = im.resize((int(w * scale), int(h * scale)))
            tmp = dest.with_suffix(".tmp.jpg")
            im.save(tmp, "JPEG", quality=90)
            tmp.replace(dest)
        return True
    except Exception as e:
        log(f"WARN resize failed {src}: {e}")
        return False


def stage_new() -> int:
    PAGES.mkdir(parents=True, exist_ok=True)
    count = 0
    for src in sorted(SRC.rglob("*.jpg")):
        if IMAGE_NAME_CONTAINS and IMAGE_NAME_CONTAINS not in src.name:
            continue
        dest = PAGES / src.name
        if resize(src, dest):
            count += 1
    return count


def valid_yaml(stem: str) -> bool:
    if (ART / stem / f"{stem}_transcription.yaml").exists():
        return True
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "_", stem)
    if sanitized != stem:
        sanitized_dir = ART / sanitized
        if (sanitized_dir / f"{stem}_transcription.yaml").exists():
            return True
        if (sanitized_dir / f"{sanitized}_transcription.yaml").exists():
            return True
    return False


def _mark(stem: str, kind: str, reason: str) -> None:
    """Write ``.skipped`` / ``.failed`` marker under artifacts."""
    dest = ART / stem / f".{kind}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(reason.rstrip() + "\n", encoding="utf-8")


def is_non_text_page(img: Path) -> str | None:
    """Return skip reason if this image should never enter HTR→LLM."""
    if _SKIP_NAME_RE.search(img.stem):
        return f"skip_name: non-text/extra folio ({img.name})"
    try:
        with Image.open(img) as im:
            gray = im.convert("L")
            st = ImageStat.Stat(gray)
            mean = float(st.mean[0])
            std = float(st.stddev[0])
    except Exception as e:
        return f"skip_unreadable: {e}"
    if mean <= BLANK_MAX_MEAN and std <= BLANK_MAX_STD:
        return f"skip_blank: mean={mean:.1f} std={std:.1f} (dark/empty board)"
    return None


def pending_images() -> list[Path]:
    imgs: list[Path] = []
    for img in sorted(PAGES.glob("*.jpg")):
        if valid_yaml(img.stem):
            continue
        if (ART / img.stem / ".failed").exists():
            continue
        if (ART / img.stem / ".skipped").exists():
            continue
        reason = is_non_text_page(img)
        if reason:
            _mark(img.stem, "skipped", reason)
            log(f"SKIP {img.name}: {reason}")
            continue
        imgs.append(img)
    return imgs


def acquisition_running() -> bool:
    for pidfile in (JOB / "status").glob("acquire_*.pid"):
        try:
            os.kill(int(pidfile.read_text().strip()), 0)
            return True
        except Exception:
            pass
    return False


def run_batch(imgs: list[Path], idx: int) -> None:
    batch_dir = BATCHES / f"batch_{idx:04d}"
    if batch_dir.exists():
        shutil.rmtree(batch_dir)
    batch_dir.mkdir(parents=True)
    for img in imgs:
        os.symlink(img, batch_dir / img.name)

    report = JOB / "logs" / f"transcription_batch_{idx:04d}.json"
    log_file = JOB / "logs" / f"transcription_batch_{idx:04d}.log"
    if HTR_COMBINATION.lower() in ("shell", "off", "none", "llm_only"):
        raise SystemExit(
            f"STREAM_HTR_COMBINATION={HTR_COMBINATION!r} is LLM-only; "
            "refusing to start batch (require HTR→LLM)."
        )
    htr_export = f"export TRANSCRIBER_SHELL_HTR_COMBINATION='{HTR_COMBINATION}' && "
    htr_model = resolve_highest_htr_model()
    htr_model_export = (
        f"export TRANSCRIBER_SHELL_KRAKEN_HTR_MODEL_PATH='{htr_model}' && " if htr_model else ""
    )
    seg_model = resolve_seg_model()
    seg_export = (
        f"export TRANSCRIBER_SHELL_KRAKEN_MODEL_PATH='{seg_model}' && " if seg_model else ""
    )
    expand_export = ""
    if EXPAND_ENABLED:
        expand_export = (
            "export EXPAND_DIPLOMATIC_ENABLED=1 && "
            "export TRANSCRIBER_SHELL_EXPAND_DIPLOMATIC=1 && "
            f"export EXPAND_DIPLOMATIC_BACKEND='{EXPAND_BACKEND}' && "
            f"export EXPAND_DIPLOMATIC_MODEL='{EXPAND_MODEL}' && "
            f"export EXPAND_DIPLOMATIC_ROOT='{EXPAND_ROOT}' && "
            "export EXPAND_DIPLOMATIC_WHOLE_DOC=1 && "
        )
    skip_xml_export = (
        f"export TRANSCRIBER_SHELL_SKIP_LINES_XML_VALIDATION='{SKIP_LINES_XML_VALIDATION}' && "
        if SKIP_LINES_XML_VALIDATION
        else ""
    )
    model_flag = f" --model '{MODEL}'" if MODEL else ""
    llm_mode_flag = f" --llm-mode '{LLM_MODE}'" if LLM_MODE else ""
    continue_flag = "--continue-on-lineation-failure " if CONTINUE_ON_LINEATION_FAILURE else ""
    cmd = (
        f"cd '{TSHELL_ROOT}' && "
        f"source '{TSHELL_VENV}/bin/activate' && "
        f"set -a && [ -f '{TSHELL_ROOT}/.env' ] && . '{TSHELL_ROOT}/.env'; set +a && "
        f"export PYTHONPATH='{TSHELL_ROOT}/src' && "
        f"export TRANSCRIBER_SHELL_ARTIFACTS_DIR='{ART}' && "
        f"export TRANSCRIBER_SHELL_REQUIRE_HTR_BEFORE_LLM=1 && "
        f"export TRANSCRIBER_SHELL_HTR_PARALLEL=0 && "
        f"{htr_export}"
        f"{htr_model_export}"
        f"{seg_export}"
        f"{expand_export}"
        f"{skip_xml_export}"
        f"transcriber-shell batch '{batch_dir}' "
        f"--doc-type '{DOC_TYPE}' "
        f"--provider '{PROVIDER}' "
        f"--htr-combination '{HTR_COMBINATION}' "
        f"{llm_mode_flag}"
        f"{model_flag} "
        "--skip-successful "
        f"{continue_flag}"
        f"--batch-report '{report}'"
    )
    log(f"RUN batch {idx} images={len(imgs)}")
    with log_file.open("w", encoding="utf-8") as f:
        result = subprocess.run(["bash", "-lc", cmd], stdout=f, stderr=subprocess.STDOUT)
    log(f"DONE batch {idx} exit={result.returncode}")
    if result.returncode != 0:
        log_txt = log_file.read_text(encoding="utf-8", errors="replace") if log_file.is_file() else ""
        for img in imgs:
            if valid_yaml(img.stem):
                continue
            if "HTR→LLM required" in log_txt and img.name in log_txt:
                _mark(
                    img.stem,
                    "skipped",
                    "skip_empty_htr: HTR produced no usable draft (blank/non-text page)",
                )
                log(f"SKIP {img.name}: empty HTR draft after lineation")
                continue
            _mark(img.stem, "failed", f"batch {idx} exit {result.returncode}")


def finish_manuscript() -> None:
    """Expand leftover YAML, extract expanded text, run stylo for this job."""
    log("finish_manuscript: expand → extract → stylo")
    py = str(TSHELL_VENV / "bin" / "python") if (TSHELL_VENV / "bin" / "python").is_file() else "python3"
    if EXPAND_ENABLED and EXPAND_PY.is_file():
        cmd = [
            py,
            str(EXPAND_PY),
            "--jobs-root",
            str(JOB.parent),
            "--tshell-src",
            str(TSHELL_ROOT / "src"),
            "--expand-root",
            str(EXPAND_ROOT),
            "--only-job",
            JOB.name,
            "--backend",
            EXPAND_BACKEND,
            "--model",
            EXPAND_MODEL,
            "--parallel-files",
            "2",
            "--whole-doc",
        ]
        log("RUN expand-backfill")
        inner = " ".join(shlex.quote(c) for c in cmd)
        subprocess.run(
            [
                "bash",
                "-lc",
                f"set -a && [ -f '{TSHELL_ROOT}/.env' ] && . '{TSHELL_ROOT}/.env'; set +a && {inner}",
            ],
            cwd=str(JOB),
            check=False,
        )
    txt = JOB / "04_expanded" / f"{JOB.name}_latin.txt"
    if EXTRACT_PY.is_file() and ART.is_dir():
        txt.parent.mkdir(parents=True, exist_ok=True)
        log(f"RUN extract → {txt}")
        subprocess.run(
            [py, str(EXTRACT_PY), str(ART), str(txt), "--prefer-expanded"],
            check=False,
        )
    if STYLO_RUNNER.is_file() and txt.is_file() and txt.stat().st_size > 0 and STYLO_REF.is_dir():
        STYLO_OUT.mkdir(parents=True, exist_ok=True)
        log(f"RUN stylo → {STYLO_OUT}")
        subprocess.run(
            ["Rscript", str(STYLO_RUNNER), str(txt), str(STYLO_OUT), JOB.name, str(STYLO_REF)],
            check=False,
        )
    done = JOB / "status" / "pipeline.DONE"
    done.parent.mkdir(parents=True, exist_ok=True)
    done.write_text(time.strftime("%Y-%m-%dT%H:%M:%S%z") + "\n", encoding="utf-8")
    log("finish_manuscript done")


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    BATCHES.mkdir(parents=True, exist_ok=True)
    htr_model = resolve_highest_htr_model()
    seg_model = resolve_seg_model()
    log("watch_transcribe start")
    log(
        f"pipeline htr_model={htr_model or '(doc-type/registry)'} "
        f"seg_model={seg_model or '(doc-type/registry)'} "
        f"llm_mode={LLM_MODE} expand={EXPAND_ENABLED}/{EXPAND_BACKEND} stylo_out={STYLO_OUT}"
    )
    idle = 0
    batch_idx = 1
    while True:
        staged = stage_new()
        pending = pending_images()
        done = len(list(ART.rglob("*_transcription.yaml")))
        skipped = len(list(ART.rglob(".skipped")))
        downloaded = len(list(PAGES.glob("*.jpg")))
        log(
            f"status staged_new={staged} downloaded={downloaded} "
            f"done={done} skipped={skipped} pending={len(pending)}"
        )
        if pending:
            idle = 0
            run_batch(pending[:BATCH_SIZE], batch_idx)
            batch_idx += 1
            continue
        if not acquisition_running():
            log("watch_transcribe complete: no pending pages and acquire idle")
            finish_manuscript()
            break
        idle += 1
        if idle >= IDLE_LIMIT:
            log("watch_transcribe complete: idle limit with acquire still marked running")
            finish_manuscript()
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
