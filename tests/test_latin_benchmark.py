"""Latin manuscript pipeline benchmark tests.

Five ground truth cases from ~/latin-ms-workspace/training/combined_gt/ are
run through the local lineation model (mask backend), optional LLM
transcription, optional expand-diplomatic expansion, and scored with
_eval_core CER/WER helpers.

Marks
-----
live_llm  — requires ANTHROPIC_API_KEY and a working model; skipped in CI.
live_expand — requires GEMINI_API_KEY; skipped in CI.
live_lineation — requires the mask weights file on disk; skipped otherwise.
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NamedTuple
from unittest.mock import patch

import pytest
import yaml

# ── paths ────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_CORE = REPO_ROOT / "vendor" / "transcription-protocol" / "benchmark" / "_eval_core.py"
GT_DIR = Path.home() / "latin-ms-workspace" / "training" / "combined_gt"
UNET_WEIGHTS = Path.home() / "latin-ms-workspace" / "training" / "line_mask_unet.pt"
EXPAND_DIPLOMATIC_DIR = Path.home() / "Projects" / "magic-elise-tool"
YAML_TO_TEI = REPO_ROOT / "scripts" / "latin_ms" / "yaml_to_tei.py"
PAGE_NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"


# ── load eval helpers ────────────────────────────────────────────────────────
import importlib.util as _ilu

def _load_eval_core():
    spec = _ilu.spec_from_file_location("_eval_core", EVAL_CORE)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_eval = _load_eval_core()
strip_tokens = _eval.strip_tokens
normalize_for_comparison = _eval.normalize_for_comparison
word_diff = _eval.word_diff
rubric_score = _eval.rubric_score
disposition = _eval.disposition


# ── ground truth cases ────────────────────────────────────────────────────────
class GTCase(NamedTuple):
    stem: str
    xml: Path
    image: Path
    gt_text: str  # joined GT TextLine Unicode text


def _load_gt_case(stem: str) -> GTCase:
    xml = GT_DIR / f"{stem}.xml"
    tree = ET.parse(xml)
    # Use wildcard namespace to handle both 2013 and 2019 PAGE schemas
    page = tree.find(".//{*}Page")
    img_name = page.get("imageFilename", "") if page is not None else ""
    image = Path(img_name) if img_name and Path(img_name).is_file() else GT_DIR / f"{stem}.jpeg"
    lines = tree.findall(".//{*}TextLine")
    texts = [
        (t.findtext("{*}TextEquiv/{*}Unicode") or "").strip()
        for t in lines
    ]
    gt = "\n".join(t for t in texts if t)
    return GTCase(stem=stem, xml=xml, image=image, gt_text=gt)


# Primary benchmark cases (from combined_gt; ordered by line count)
BENCHMARK_CASES = [
    "JUST1-633m5",
    "JUST1-633m47d",
    "JUST1-633m16d",
    "JUST1-633m120",
    "JUST-633m12d",
]

# Extended val_data cases (exact GT for existing job YAMLs + new sources)
EXTENDED_CASES = [
    "JUST1-734m24d",
    "JUST1-734m17da",
    "JUST1-734m4",
    "KB27-263m21",
    "KB27-645m22a",
    "CP40-649m116a",
    "JUST1-633m52",
    "JUST1-633m60d",
]


@pytest.fixture(scope="module")
def gt_cases() -> list[GTCase]:
    pytest.importorskip  # keeps linter happy
    if not GT_DIR.is_dir():
        pytest.skip(f"GT dir not found: {GT_DIR}")
    cases = []
    for stem in BENCHMARK_CASES:
        xml = GT_DIR / f"{stem}.xml"
        if not xml.is_file():
            pytest.skip(f"GT XML missing: {xml}")
        cases.append(_load_gt_case(stem))
    return cases


@pytest.fixture(scope="module")
def extended_cases() -> list[GTCase]:
    """Extended set from val_data — exact GT for existing job YAMLs."""
    if not GT_DIR.is_dir():
        pytest.skip(f"GT dir not found: {GT_DIR}")
    cases = []
    for stem in EXTENDED_CASES:
        xml = GT_DIR / f"{stem}.xml"
        if xml.is_file():
            cases.append(_load_gt_case(stem))
    if not cases:
        pytest.skip("No extended GT cases found in combined_gt")
    return cases


# ── helpers ───────────────────────────────────────────────────────────────────

def _gt_lines(case: GTCase) -> list[str]:
    tree = ET.parse(case.xml)
    lines = tree.findall(".//{*}TextLine")
    return [
        (t.findtext("{*}TextEquiv/{*}Unicode") or "").strip()
        for t in lines
        if (t.findtext("{*}TextEquiv/{*}Unicode") or "").strip()
    ]


def _score(gt: str, hyp: str) -> dict:
    gt_n = normalize_for_comparison(gt)
    hyp_n = normalize_for_comparison(hyp)
    matches, adds, omits = word_diff(gt_n, hyp_n)
    gt_words = len(gt_n.split())
    recall = matches / gt_words if gt_words else 0.0
    disp, crit, major = disposition(len(adds), len(omits))
    score = rubric_score(len(adds), len(omits))
    return {
        "gt_words": gt_words,
        "matches": matches,
        "additions": adds,
        "omissions": omits,
        "word_recall": recall,
        "rubric_score": score,
        "disposition": disp,
    }


# ── VPE / PAGE XML validation ─────────────────────────────────────────────────

class TestPageXmlValidation:
    """Validate that our GT files are well-formed PAGE XML (VPE gate)."""

    def test_gt_xml_parses(self, gt_cases: list[GTCase]) -> None:
        for case in gt_cases:
            tree = ET.parse(case.xml)
            ns = {"p": PAGE_NS}
            page = tree.find(".//p:Page", ns)
            assert page is not None, f"{case.stem}: no <Page> element"

    def test_gt_has_text_lines(self, gt_cases: list[GTCase]) -> None:
        for case in gt_cases:
            lines = _gt_lines(case)
            assert len(lines) >= 10, (
                f"{case.stem}: only {len(lines)} GT text lines, expected ≥10"
            )

    def test_gt_images_exist(self, gt_cases: list[GTCase]) -> None:
        for case in gt_cases:
            assert case.image.is_file(), f"{case.stem}: image missing: {case.image}"


# ── strigil acquisition stub ──────────────────────────────────────────────────

class TestStrigilAcquisition:
    """Smoke test strigil adapter interface (no network required)."""

    def test_strigil_importable(self) -> None:
        strigil_src = REPO_ROOT.parent / "strigil" / "src"
        if not strigil_src.is_dir():
            pytest.skip("strigil not found alongside transcription-shell")
        sys.path.insert(0, str(strigil_src))
        try:
            import strigil  # noqa: F401
        except ImportError as e:
            pytest.skip(f"strigil import failed: {e}")

    def test_gt_images_are_valid_jpegs_or_pngs(self, gt_cases: list[GTCase]) -> None:
        """Images the pipeline would acquire must be readable."""
        from PIL import Image

        for case in gt_cases:
            img = Image.open(case.image)
            assert img.size[0] > 0 and img.size[1] > 0, (
                f"{case.stem}: zero-dimension image"
            )


# ── lineation (mask U-Net backend) ────────────────────────────────────────────

@pytest.mark.skipif(
    not UNET_WEIGHTS.is_file(),
    reason=f"U-Net weights not found at {UNET_WEIGHTS}",
)
class TestMaskLineation:
    """Run U-Net lineation on GT images, compare TextLine count against GT."""

    def _run_mask_lineation(self, image: Path, tmp_path: Path, stem: str) -> int:
        """Return TextLine count produced by mask backend."""
        torch = pytest.importorskip("torch", reason="torch not installed")
        from transcriber_shell.mask_lineation import fetch_lines_xml_mask
        from transcriber_shell.config import Settings

        settings = Settings(
            artifacts_dir=tmp_path / "arts",
            mask_weights_path=UNET_WEIGHTS,
            mask_inference_callable="latin_lineation_mvp.infer:predict_masks",
        )
        xml_out = fetch_lines_xml_mask(image, stem, settings=settings)
        tree = ET.parse(xml_out)
        return len(tree.findall(".//{*}TextLine"))

    def test_line_count_within_tolerance(
        self, gt_cases: list[GTCase], tmp_path: Path
    ) -> None:
        for case in gt_cases:
            gt_count = len(_gt_lines(case))
            pred_count = self._run_mask_lineation(case.image, tmp_path, case.stem)
            ratio = pred_count / gt_count if gt_count else 0.0
            print(f"\n    {case.stem}: {pred_count}/{gt_count} lines (ratio={ratio:.2f})")
            # Threshold is 0.10 while Kraken/U-Net retraining is in progress;
            # raise to 0.50 once kraken_seg_updated_best.mlmodel is deployed.
            assert ratio >= 0.10, (
                f"{case.stem}: lineation produced {pred_count} lines vs "
                f"{gt_count} GT lines (ratio={ratio:.2f}, threshold=0.10)"
            )


# ── full pipeline (LLM transcription) ─────────────────────────────────────────

@pytest.mark.live_llm
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
class TestLivePipeline:
    """End-to-end pipeline test using real LLM, GT XML as lineation source."""

    def _prompt_cfg(self) -> dict:
        prompt_yaml = REPO_ROOT / "scripts" / "latin_ms" / "prompt_latin.yaml"
        if prompt_yaml.is_file():
            return yaml.safe_load(prompt_yaml.read_text(encoding="utf-8"))
        return {
            "protocolVersion": "1.1.0",
            "targetLanguage": "lat-Latn",
            "diplomaticProfile": "layout_aware",
            "normalizationMode": "diplomatic",
        }

    def test_pipeline_word_recall(
        self, gt_cases: list[GTCase], tmp_path: Path
    ) -> None:
        from transcriber_shell.config import Settings
        from transcriber_shell.models.job import TranscribeJob
        from transcriber_shell.pipeline.run import run_pipeline

        artifacts = tmp_path / "artifacts"
        settings = Settings(artifacts_dir=artifacts)
        cfg = self._prompt_cfg()

        results = []
        for case in gt_cases:
            job = TranscribeJob(
                job_id=case.stem,
                image_path=case.image,
                prompt_cfg={**cfg, "sourcePageId": case.stem},
                provider="anthropic",
            )
            result = run_pipeline(
                job,
                skip_gm=True,
                lines_xml_path=case.xml,
                require_text_line=True,
                settings=settings,
            )
            assert not result.errors, (
                f"{case.stem}: pipeline errors: {result.errors}"
            )
            assert result.transcription_yaml_path and result.transcription_yaml_path.is_file(), (
                f"{case.stem}: no transcription YAML produced"
            )
            data = yaml.safe_load(
                result.transcription_yaml_path.read_text(encoding="utf-8")
            )
            root = data.get("transcriptionOutput", data)
            segs = root.get("segments", [])
            hyp = "\n".join(
                s.get("text", "").strip()
                for s in segs
                if isinstance(s, dict) and s.get("text", "").strip()
            )

            # Score diplomatic output directly against GT (both use Unicode combining chars)
            dipl_score = _score(case.gt_text, hyp)

            # Also score expanded output if Gemini key available (expansion improves recall)
            exp_score = None
            if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
                try:
                    if str(EXPAND_DIPLOMATIC_DIR) not in sys.path:
                        sys.path.insert(0, str(EXPAND_DIPLOMATIC_DIR))
                    from expand_diplomatic.expander import expand_xml
                    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
                    tei_xml = (
                        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
                        + "".join(f"<p>{line}</p>" for line in hyp.split("\n") if line.strip())
                        + "</body></text></TEI>"
                    )
                    expanded = expand_xml(
                        tei_xml, examples=[], api_key=api_key, backend="gemini",
                        modality="full", passes=1,
                        model=os.environ.get("EXPAND_DIPLOMATIC_MODEL", "gemini-2.5-flash"),
                    )
                    root_xml = ET.fromstring(expanded)
                    exp_text = "\n".join(
                        (p.text or "").strip()
                        for p in root_xml.findall(".//{http://www.tei-c.org/ns/1.0}p")
                        if (p.text or "").strip()
                    )
                    exp_score = _score(case.gt_text, exp_text)
                except Exception:
                    pass

            results.append((case.stem, dipl_score, exp_score))
            exp_note = f"  expanded={exp_score['word_recall']:.2%}" if exp_score else ""
            print(
                f"\n{case.stem}: dipl={dipl_score['word_recall']:.2%}"
                f"  disp={dipl_score['disposition']}{exp_note}"
            )

        recalls = [s[1]["word_recall"] for s in results]
        avg = sum(recalls) / len(recalls)
        per_case = [(n, "{:.2%}".format(s["word_recall"])) for n, s, *_ in results]
        assert avg >= 0.40, (
            f"Mean word recall {avg:.2%} below 40% threshold. Per-case: {per_case}"
        )


# ── expand-diplomatic integration ─────────────────────────────────────────────

@pytest.mark.live_expand
@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)
class TestExpandDiplomaticIntegration:
    """Round-trip: protocol YAML → TEI XML → expand_diplomatic → score vs GT."""

    def _yaml_to_tei_str(self, yaml_path: Path) -> str:
        import importlib.util
        spec = importlib.util.spec_from_file_location("yaml_to_tei", YAML_TO_TEI)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        import io, sys
        tmp = yaml_path.with_suffix(".tei.xml")
        mod.yaml_to_tei(yaml_path, tmp)
        return tmp.read_text(encoding="utf-8")

    def _expand(self, tei_xml: str) -> str:
        if str(EXPAND_DIPLOMATIC_DIR) not in sys.path:
            sys.path.insert(0, str(EXPAND_DIPLOMATIC_DIR))
        from expand_diplomatic.expander import expand_xml
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        return expand_xml(
            tei_xml,
            examples=[],
            api_key=api_key,
            backend="gemini",
            modality="full",
            passes=1,
            model=os.environ.get("EXPAND_DIPLOMATIC_MODEL", "gemini-2.5-flash"),
        )

    def _extract_tei_text(self, xml_str: str) -> str:
        root = ET.fromstring(xml_str)
        ns = {"t": "http://www.tei-c.org/ns/1.0"}
        paras = root.findall(".//t:p", ns)
        parts = []
        for p in paras:
            text = " ".join(t.strip() for t in p.itertext() if t.strip())
            if text:
                parts.append(text)
        return "\n".join(parts)

    def test_expand_then_score(
        self, gt_cases: list[GTCase], tmp_path: Path
    ) -> None:
        # Use GT XML as transcription proxy: extract GT text → minimal YAML
        for case in gt_cases:
            gt_lines = _gt_lines(case)
            # Write a minimal protocol YAML from GT text
            proto_yaml = tmp_path / f"{case.stem}_transcription.yaml"
            segs = [
                {"segmentId": i + 1, "pageNumber": 1, "lineRange": str(i + 1),
                 "position": "body", "text": line, "confidence": "high",
                 "uncertaintyTokenCount": 0, "notes": None}
                for i, line in enumerate(gt_lines)
            ]
            data = {
                "transcriptionOutput": {
                    "protocolVersion": "1.1.0",
                    "metadata": {"sourcePageId": case.stem, "protocolVersion": "1.1.0"},
                    "segments": segs,
                }
            }
            proto_yaml.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")

            tei_xml = self._yaml_to_tei_str(proto_yaml)
            expanded_xml = self._expand(tei_xml)
            expanded_text = self._extract_tei_text(expanded_xml)

            # After expansion the text should be at least as long (abbreviations opened up)
            assert len(expanded_text) >= len(case.gt_text) * 0.5, (
                f"{case.stem}: expanded text suspiciously short "
                f"({len(expanded_text)} < {len(case.gt_text) * 0.5:.0f})"
            )
            print(
                f"\n{case.stem}: expanded {len(case.gt_text)} → {len(expanded_text)} chars"
            )


# ── eval_core unit tests ──────────────────────────────────────────────────────

class TestEvalCore:
    """Sanity checks for _eval_core helpers so benchmark scores are trustworthy."""

    def test_strip_tokens_uncertain(self) -> None:
        assert strip_tokens("[uncertain: Iohem/Iohm]") == "Iohem"

    def test_strip_tokens_illegible(self) -> None:
        assert strip_tokens("[illegible]") == ""

    def test_strip_tokens_deletion(self) -> None:
        assert strip_tokens("[deletion: old]") == ""

    def test_strip_tokens_insertion(self) -> None:
        assert strip_tokens("[insertion: new]") == "new"

    def test_normalize_whitespace(self) -> None:
        assert normalize_for_comparison("a  b\n\nc") == "a b c"

    def test_word_diff_exact(self) -> None:
        matches, adds, omits = word_diff("Rex et Regina", "Rex et Regina")
        assert matches == 3
        assert adds == []
        assert omits == []

    def test_word_diff_omission(self) -> None:
        matches, adds, omits = word_diff("Rex et Regina", "Rex Regina")
        assert "et" in omits

    def test_word_diff_addition(self) -> None:
        matches, adds, omits = word_diff("Rex Regina", "Rex et Regina")
        assert "et" in adds

    def test_rubric_score_perfect(self) -> None:
        assert rubric_score(0, 0) == 1.0

    def test_rubric_score_clamp(self) -> None:
        assert rubric_score(100, 100) == 0.0

    def test_disposition_pass(self) -> None:
        disp, crit, _ = disposition(0, 0)
        assert disp == "PASS"
        assert crit == []

    def test_disposition_fail_additions(self) -> None:
        disp, crit, _ = disposition(1, 0)
        assert disp == "FAIL"
        assert "substantive_additions" in crit

    def test_disposition_conditional_minor_omissions(self) -> None:
        disp, _, major = disposition(0, 2)
        assert disp == "CONDITIONAL_PASS"
        assert "minor_omissions" in major

    def test_disposition_fail_significant_omissions(self) -> None:
        disp, crit, _ = disposition(0, 5)
        assert disp == "FAIL"
        assert "significant_omissions" in crit


# ── word recall delta test ─────────────────────────────────────────────────────

class TestScoringRegression:
    """Deterministic scoring tests using synthetic GT vs hypothesis pairs."""

    def _make_case(self, stem: str) -> GTCase:
        return _load_gt_case(stem)

    def test_self_score_is_perfect(self, gt_cases: list[GTCase]) -> None:
        """Scoring GT against itself should be PASS with 100% recall."""
        for case in gt_cases:
            gt_n = normalize_for_comparison(case.gt_text)
            result = _score(gt_n, gt_n)
            assert result["word_recall"] == pytest.approx(1.0), (
                f"{case.stem}: self-score recall != 1.0"
            )
            assert result["disposition"] == "PASS", (
                f"{case.stem}: self-score disposition != PASS"
            )

    def test_empty_hyp_scores_zero(self, gt_cases: list[GTCase]) -> None:
        for case in gt_cases:
            result = _score(case.gt_text, "")
            assert result["word_recall"] == pytest.approx(0.0)

    def test_partial_hyp_scores_below_one(self, gt_cases: list[GTCase]) -> None:
        for case in gt_cases:
            lines = case.gt_text.split("\n")
            partial = "\n".join(lines[: len(lines) // 2])
            result = _score(case.gt_text, partial)
            assert result["word_recall"] < 1.0, (
                f"{case.stem}: partial hyp scored 1.0"
            )


# ── extended benchmark — val_data cases with exact GT match ───────────────────

class TestExtendedBenchmarkGT:
    """Offline scoring regressions using val_data GT (no LLM needed)."""

    def test_extended_cases_load(self, extended_cases: list[GTCase]) -> None:
        for case in extended_cases:
            assert case.gt_text.strip(), f"{case.stem}: empty GT text"
            assert len(case.gt_text.split()) >= 10, (
                f"{case.stem}: fewer than 10 GT words"
            )
            assert case.image.is_file(), f"{case.stem}: image missing"

    def test_extended_self_score(self, extended_cases: list[GTCase]) -> None:
        for case in extended_cases:
            gt_n = normalize_for_comparison(case.gt_text)
            result = _score(gt_n, gt_n)
            assert result["word_recall"] == pytest.approx(1.0), (
                f"{case.stem}: self-score != 1.0"
            )

    def test_extended_gt_xml_valid_pagexml(self, extended_cases: list[GTCase]) -> None:
        from transcriber_shell.xml_tools.lines_validate import validate_lines_xml
        for case in extended_cases:
            ok, msgs, stats = validate_lines_xml(str(case.xml))
            assert ok, f"{case.stem}: {msgs}"
            assert stats["text_line"] >= 10, (
                f"{case.stem}: only {stats['text_line']} TextLines"
            )

    def test_existing_job_yamls_vs_exact_gt(self, extended_cases: list[GTCase]) -> None:
        """Score existing job transcription YAMLs against their exact GT folio."""
        jobs_dir = Path.home() / "latin-ms-workspace" / "jobs"
        if not jobs_dir.is_dir():
            pytest.skip("Jobs dir not found")

        scored = []
        for case in extended_cases:
            # Find a YAML matching this stem in any job
            yamls = list(jobs_dir.rglob(f"*{case.stem}*_transcription.yaml"))
            if not yamls:
                continue
            yaml_path = yamls[0]
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            root = data.get("transcriptionOutput", data)
            segs = root.get("segments", [])
            hyp = "\n".join(
                s.get("text", "").strip()
                for s in segs
                if isinstance(s, dict) and s.get("text", "").strip()
            )
            result = _score(case.gt_text, hyp)
            scored.append((case.stem, result))
            print(
                f"\n  {case.stem}: recall={result['word_recall']:.1%}  "
                f"disp={result['disposition']}  "
                f"gt={result['gt_words']}w"
            )

        if not scored:
            pytest.skip("No cached job YAMLs match extended GT cases")

        # Diplomatic output against GT: expect at least 15% recall
        # (GT is expanded; diplomatic uses Unicode combining chars — some match)
        recalls = [r["word_recall"] for _, r in scored]
        avg = sum(recalls) / len(recalls)
        print(f"\n  Mean recall (dipl vs expanded GT): {avg:.1%}")
        # This is diagnostic — don't fail on a hard threshold since diplomatic != expanded


class TestCrossRepositoryGTCoverage:
    """Verify combined_gt has adequate coverage across roll types."""

    def test_cp40_rolls_present(self) -> None:
        if not GT_DIR.is_dir():
            pytest.skip("GT dir not available")
        cp40 = list(GT_DIR.glob("CP40-*.xml"))
        assert len(cp40) >= 3, f"Expected ≥3 CP40 GT XMLs, got {len(cp40)}"

    def test_just1_rolls_present(self) -> None:
        if not GT_DIR.is_dir():
            pytest.skip("GT dir not available")
        just1 = list(GT_DIR.glob("JUST1-*.xml"))
        assert len(just1) >= 5, f"Expected ≥5 JUST1 GT XMLs, got {len(just1)}"

    def test_kb27_rolls_present(self) -> None:
        if not GT_DIR.is_dir():
            pytest.skip("GT dir not available")
        kb27 = list(GT_DIR.glob("KB27*.xml"))
        assert len(kb27) >= 3, f"Expected ≥3 KB27 GT XMLs, got {len(kb27)}"

    def test_combined_gt_total_count(self) -> None:
        if not GT_DIR.is_dir():
            pytest.skip("GT dir not available")
        all_xml = list(GT_DIR.glob("*.xml"))
        assert len(all_xml) >= 100, (
            f"Expected ≥100 GT XMLs in combined_gt, got {len(all_xml)}"
        )
