#!/usr/bin/env python3
"""CoMMA recognition-only pass — improve browse transcriptions, never train on them.

Re-transcribes CoMMA manuscripts with our Kraken HTR model and compares against
CoMMA's CATMuS 1.6.0 text. All outputs stay under comma-rerecognition/ and are
explicitly excluded from training manifests.

Modes:
  1. IIIF pilot (default): sample comma-jsonl → fetch page images → segment → rpred
  2. ALTO refresh (--alto-dir): keep CoMMA line geometry, swap recognition only

Usage:
    # After comma_acquire.sh and gm-htr-r7-full_best.mlmodel exist:
    python scripts/comma_recognition_pass.py \\
        --comma-jsonl /ocean/.../comma-rerecognition/raw/comma-jsonl \\
        --model /ocean/.../src/gm-htr-r7-full_best.mlmodel \\
        --seg-model /ocean/.../src/kraken-merged-seg_best.mlmodel \\
        --out-dir /ocean/.../comma-rerecognition/pilot \\
        --language-filter latin --max-manuscripts 50 --max-pages-per-ms 3

TRAINING FIREWALL: never add --out-dir or comma-jsonl paths to ketos train -t/-e.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

TRAINING_FIREWALL_PATHS = (
    "comma-rerecognition",
    "comma-jsonl",
    "comma-other-formats",
    "comma-project",
)


def _assert_not_training_path(path: Path) -> None:
    s = str(path.resolve()).lower()
    if any(tok in s for tok in ("htr-corpora", "latin-corpus-gt")):
        sys.exit(
            f"Refusing to write CoMMA output under training tree: {path}\n"
            "Use comma-rerecognition/ instead."
        )


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _find_jsonl_file(root: Path) -> Path:
    for p in sorted(root.rglob("*.jsonl")):
        return p
    for p in sorted(root.rglob("*.json")):
        if p.stat().st_size > 1_000_000:
            return p
    sys.exit(f"No comma-jsonl file found under {root}")


def _language_matches(row: dict, flt: str) -> bool:
    if not flt:
        return True
    flt = flt.lower()
    for key in ("language_fasttext", "biblissima_simplified_language", "biblissima_language"):
        val = str(row.get(key) or "").lower()
        if flt in val:
            return True
    return False


def _iiif_page_urls(manifest_url: str, max_pages: int) -> list[str]:
    """Return IIIF image service URLs for up to max_pages canvases."""
    req = urllib.request.Request(
        manifest_url,
        headers={"User-Agent": "transcription-shell/comma-rerecognition"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    urls: list[str] = []
    sequences = data.get("sequences") or []
    if not sequences and "items" in data:
        # Presentation 3
        for item in data.get("items") or []:
            for anno in item.get("items") or []:
                body = (anno.get("body") or {})
                svc = body.get("service") or []
                if isinstance(svc, list) and svc:
                    sid = svc[0].get("id") or svc[0].get("@id")
                    if sid:
                        urls.append(f"{sid.rstrip('/')}/full/max/0/default.jpg")
                if len(urls) >= max_pages:
                    return urls
        return urls

    for seq in sequences:
        for canvas in seq.get("canvases") or []:
            images = canvas.get("images") or []
            for image in images:
                resource = image.get("resource") or {}
                sid = resource.get("@id") or resource.get("id")
                if not sid:
                    continue
                if "/full/" not in sid:
                    sid = f"{sid.rstrip('/')}/full/max/0/default.jpg"
                urls.append(sid)
                if len(urls) >= max_pages:
                    return urls
    return urls


def _download(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "transcription-shell/comma-rerecognition"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            dest.write_bytes(resp.read())
        return True
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"  [warn] download failed {url}: {exc}", file=sys.stderr)
        return False


def _cer(a: str, b: str) -> float:
    """Levenshtein CER on canonicalized strings."""
    import unicodedata

    def norm(s: str) -> str:
        s = unicodedata.normalize("NFD", s)
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        return re.sub(r"\s+", " ", s.lower()).strip()

    a, b = norm(a), norm(b)
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    la, lb = len(a), len(b)
    dp = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        prev = dp[0]
        dp[0] = i
        for j, cb in enumerate(b, 1):
            cur = dp[j]
            dp[j] = min(
                dp[j] + 1,
                dp[j - 1] + 1,
                prev + (ca != cb),
            )
            prev = cur
    return dp[lb] / max(la, lb)


def _line_confidence(rec) -> float:
    """Best available per-line confidence from an rpred record."""
    confs = getattr(rec, "confidences", None)
    if confs:
        return float(min(confs))
    cuts = getattr(rec, "cuts", None)
    if cuts:
        return float(sum(cuts) / len(cuts))
    return 0.0


def _transcribe_page(
    image_path: Path,
    htr_model: Path,
    seg_model: Path | None,
    *,
    device: str,
    save_line_records: bool = False,
    ms_id: str = "",
    page_idx: int = 0,
    out_dir: Path | None = None,
    xml_rel_path: str = "",
) -> tuple[str, list[dict]]:
    """Return (full_page_text, line_records).

    line_records is populated only when save_line_records=True.
    """
    from PIL import Image
    from kraken import blla, rpred
    from kraken.lib import models
    from kraken.lib.xml import XMLPage
    from kraken import serialization

    im = Image.open(image_path).convert("RGB")
    seg_m = models.load_any(str(seg_model), device=device) if seg_model else None
    seg = blla.segment(im, model=seg_m, text_direction="horizontal-lr", device=device) if seg_m else blla.segment(im)
    htr_m = models.load_any(str(htr_model), device=device)

    # Serialize to temp PAGE for rpred container
    xml_str = serialization.serialize(seg, image_size=im.size, template="pagexml")
    tmp_xml = image_path.with_suffix(".lines.xml")
    tmp_xml.write_text(xml_str, encoding="utf-8")
    page = XMLPage(str(tmp_xml)).to_container()
    recs = list(rpred.rpred(htr_m, im, page, pad=16))
    tmp_xml.unlink(missing_ok=True)

    lines = [rec.prediction for rec in recs]
    line_records: list[dict] = []

    if save_line_records and out_dir is not None:
        crops_base = out_dir / "line_crops"
        safe_id = re.sub(r"[^\w.-]+", "_", str(ms_id))[:80]
        crops_ms_dir = crops_base / safe_id
        crops_ms_dir.mkdir(parents=True, exist_ok=True)

        for line_idx, rec in enumerate(recs):
            conf = _line_confidence(rec)
            crop_filename = f"page_{page_idx:03d}_line_{line_idx:03d}.png"
            crop_path_abs = crops_ms_dir / crop_filename
            crop_rel = str(
                (crops_base / safe_id / crop_filename).relative_to(out_dir)
            )

            # Save crop image from bounding box
            bbox = getattr(rec, "bbox", None)
            if bbox is None:
                # Attempt to derive from cuts / line geometry
                cuts = getattr(rec, "cuts", None)
                if cuts and len(cuts) >= 2:
                    xs = [c[0] for c in cuts if hasattr(c, "__iter__")]
                    ys = [c[1] for c in cuts if hasattr(c, "__iter__")]
                    bbox = (min(xs), min(ys), max(xs), max(ys)) if xs and ys else None

            if bbox is not None:
                try:
                    x0, y0, x1, y1 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
                    x0, y0 = max(0, x0), max(0, y0)
                    x1, y1 = min(im.width, x1), min(im.height, y1)
                    if x1 > x0 and y1 > y0:
                        im.crop((x0, y0, x1, y1)).save(str(crop_path_abs))
                except Exception:
                    pass  # crop save failure is non-fatal

            bbox_record = (
                [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]
                if bbox is not None else None
            )
            line_records.append(
                {
                    "ms_id": ms_id,
                    "page_idx": page_idx,
                    "line_idx": line_idx,
                    "confidence": round(conf, 6),
                    "our_text": rec.prediction,
                    "bbox": bbox_record,
                    "crop_path": crop_rel,
                    "xml_path": xml_rel_path,
                }
            )

    return "\n".join(lines), line_records


def run_iiif_pilot(args: argparse.Namespace) -> None:
    jsonl_root = args.comma_jsonl.expanduser().resolve()
    jsonl_file = _find_jsonl_file(jsonl_root)
    rows = _load_jsonl(jsonl_file)

    out_dir = args.out_dir.expanduser().resolve()
    _assert_not_training_path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = out_dir / "pages"
    results_path = out_dir / "rerecognition.jsonl"
    lines_path = out_dir / "lines.jsonl"
    stats_path = out_dir / "stats.json"

    selected = [
        r for r in rows
        if r.get("iiif_manifest") and _language_matches(r, args.language_filter)
    ][: args.max_manuscripts]

    print(f"[comma] {len(selected)} manuscripts (filter={args.language_filter!r})")
    htr_model = args.model.expanduser().resolve()
    seg_model = args.seg_model.expanduser().resolve() if args.seg_model else None

    save_lines = args.save_line_records
    processed = 0
    total_line_records = 0

    lines_fh = lines_path.open("w", encoding="utf-8") if save_lines else None
    try:
        with results_path.open("w", encoding="utf-8") as out_fh:
            for row in selected:
                ms_id = row.get("biblissima_id") or row.get("shelfmark") or f"ms_{processed}"
                manifest = row["iiif_manifest"]
                comma_text = (row.get("text") or "").strip()
                page_urls = _iiif_page_urls(manifest, args.max_pages_per_ms)
                if not page_urls:
                    print(f"  [skip] no IIIF pages: {ms_id}")
                    continue

                our_parts: list[str] = []
                for i, url in enumerate(page_urls):
                    safe = re.sub(r"[^\w.-]+", "_", str(ms_id))[:80]
                    img_path = pages_dir / safe / f"page_{i:03d}.jpg"
                    if not _download(url, img_path):
                        continue

                    # Derive a stable relative xml_path for line records
                    xml_rel = str(
                        (pages_dir / safe / f"page_{i:03d}.lines.xml").relative_to(out_dir)
                    )

                    try:
                        text, line_records = _transcribe_page(
                            img_path,
                            htr_model,
                            seg_model,
                            device=args.device,
                            save_line_records=save_lines,
                            ms_id=ms_id,
                            page_idx=i,
                            out_dir=out_dir,
                            xml_rel_path=xml_rel,
                        )
                        our_parts.append(text)
                        if save_lines and lines_fh is not None:
                            for lr in line_records:
                                lines_fh.write(json.dumps(lr, ensure_ascii=False) + "\n")
                            total_line_records += len(line_records)
                    except Exception as exc:
                        print(f"  [warn] HTR failed {ms_id} p{i}: {exc}", file=sys.stderr)

                our_text = "\n".join(our_parts).strip()
                if not our_text:
                    continue

                cer = _cer(comma_text, our_text) if comma_text else None
                record = {
                    "biblissima_id": ms_id,
                    "iiif_manifest": manifest,
                    "language_fasttext": row.get("language_fasttext"),
                    "comma_lines": row.get("lines"),
                    "comma_tokens": row.get("tokens"),
                    "comma_text_chars": len(comma_text),
                    "our_text_chars": len(our_text),
                    "cer_vs_comma": cer,
                    "comma_text_excerpt": comma_text[:500],
                    "our_text_excerpt": our_text[:500],
                    "training_use": "FORBIDDEN",
                    "model": str(htr_model),
                    "mode": "iiif_pilot",
                }
                out_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                processed += 1
                print(f"  [{processed}] {ms_id} cer={cer:.3f}" if cer is not None else f"  [{processed}] {ms_id}")
    finally:
        if lines_fh is not None:
            lines_fh.close()

    stats = {
        "manuscripts_processed": processed,
        "language_filter": args.language_filter,
        "model": str(htr_model),
        "comma_jsonl": str(jsonl_file),
        "out_dir": str(out_dir),
        "training_firewall": "Outputs must never enter ketos train manifests",
        "comma_reference": "https://comma.inria.fr/homepage",
    }
    if save_lines:
        stats["line_records_written"] = total_line_records
    stats_path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(f"[comma] wrote {results_path} ({processed} records)")
    if save_lines:
        print(f"[comma] wrote {lines_path} ({total_line_records} line records)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--comma-jsonl", type=Path, required=True, help="Path to downloaded comma-jsonl dir")
    p.add_argument("--model", type=Path, required=True, help="Kraken HTR .mlmodel (e.g. gm-htr-r7-full_best)")
    p.add_argument("--seg-model", type=Path, default=None, help="Kraken seg .mlmodel (default: blla if omitted)")
    p.add_argument("--out-dir", type=Path, required=True, help="Output under comma-rerecognition/ only")
    p.add_argument("--language-filter", default="latin", help="Substring match on language fields")
    p.add_argument("--max-manuscripts", type=int, default=50)
    p.add_argument("--max-pages-per-ms", type=int, default=3)
    p.add_argument("--device", default="cpu", help="cuda:0 on GPU nodes")
    p.add_argument(
        "--save-line-records",
        action="store_true",
        default=False,
        help=(
            "Also emit per-line confidence records to lines.jsonl and save "
            "line crop images under <out-dir>/line_crops/."
        ),
    )
    p.add_argument(
        "--alto-dir",
        type=Path,
        default=None,
        help="Future: ALTO tree from comma-project for recognition-only line refresh",
    )
    args = p.parse_args()

    if args.alto_dir:
        sys.exit(
            "ALTO recognition-only mode not wired yet — contact comma-project for bulk ALTO, "
            "or run IIIF pilot without --alto-dir."
        )

    run_iiif_pilot(args)


if __name__ == "__main__":
    main()
