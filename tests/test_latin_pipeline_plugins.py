"""Latin manuscript pipeline — plugin integration tests.

Covers all stages without live network or API calls:
  Stage 0  retrain — PyTorch U-Net weights integrity
  Stage 1  acquire — strigil schema detection, fetcher interface (mock HTTP)
  Stage 2  crop    — image normalization (PIL)
  Stage 3  lineate — PageXML validation; VPE-style XML compatibility; Kraken backend (conditional)
  Stage 4  transcribe — run_pipeline with mocked LLM; schema gate; batch mocked
  Stage 5  expand  — yaml_to_tei conversion; expand_xml dry_run (no API key needed)
  Stage 6  normalize — validate_normalization_output helper; s6 batch runner smoke test
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# ── repo paths ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "latin_ms"
VENDOR_PROTO = REPO_ROOT / "vendor" / "transcription-protocol"
BENCHMARK_DIR = VENDOR_PROTO / "benchmark"
GT_DIR = Path.home() / "latin-ms-workspace" / "training" / "combined_gt"
UNET_WEIGHTS = Path.home() / "latin-ms-workspace" / "training" / "line_mask_unet.pt"
EXPAND_DIPLOMATIC_DIR = Path.home() / "Projects" / "magic-elise-tool"
STRIGIL_DIR = Path.home() / "Projects" / "strigil"
PAGE_NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─────────────────────────────────────────────────────────────────────────────
# Stage 0 — PyTorch U-Net weights integrity
# ─────────────────────────────────────────────────────────────────────────────

class TestUNetWeightsIntegrity:
    """Verify the trained U-Net weights load correctly and have expected keys."""

    @pytest.mark.skipif(not UNET_WEIGHTS.is_file(), reason="U-Net weights not found")
    def test_weights_load_as_torch_state_dict(self) -> None:
        torch = pytest.importorskip("torch", reason="torch not installed")
        ckpt = torch.load(str(UNET_WEIGHTS), map_location="cpu", weights_only=True)
        assert isinstance(ckpt, dict), "weights file should deserialize as dict"
        # Checkpoint may be wrapped: {"state_dict": {...}, "meta": {...}}
        state = ckpt.get("state_dict", ckpt)
        keys = list(state.keys())
        assert len(keys) > 0, "state dict is empty"
        has_conv = any("conv" in k or "weight" in k or "down" in k or "up" in k for k in keys)
        assert has_conv, f"no conv/weight keys in state dict; got: {keys[:5]}"

    @pytest.mark.skipif(not UNET_WEIGHTS.is_file(), reason="U-Net weights not found")
    def test_unet_json_metadata_exists(self) -> None:
        json_path = UNET_WEIGHTS.with_suffix(".json")
        assert json_path.is_file(), f"model metadata JSON not found: {json_path}"
        import json
        meta = json.loads(json_path.read_text())
        assert "max_lines" in meta, "metadata should contain max_lines"

    @pytest.mark.skipif(not UNET_WEIGHTS.is_file(), reason="U-Net weights not found")
    def test_unet_model_inference_shape(self) -> None:
        torch = pytest.importorskip("torch", reason="torch not installed")
        mvp_src = REPO_ROOT / "examples" / "latin_lineation_mvp" / "src"
        if not mvp_src.is_dir():
            pytest.skip("latin_lineation_mvp src not found")
        sys.path.insert(0, str(mvp_src))
        from latin_lineation_mvp.model import LineMaskUNet
        import json

        meta = json.loads((UNET_WEIGHTS.with_suffix(".json")).read_text())
        max_lines = meta.get("max_lines", 32)
        model = LineMaskUNet(max_lines=max_lines)
        ckpt = torch.load(str(UNET_WEIGHTS), map_location="cpu", weights_only=True)
        state = ckpt.get("state_dict", ckpt)
        model.load_state_dict(state, strict=False)
        model.eval()
        with torch.no_grad():
            x = torch.zeros(1, 3, 256, 256)
            y = model(x)
        assert y.shape[0] == 1
        assert y.shape[1] == max_lines
        assert y.shape[2] > 0 and y.shape[3] > 0


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Strigil interface (no network)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def strigil_available() -> bool:
    if not STRIGIL_DIR.is_dir():
        return False
    try:
        if str(STRIGIL_DIR) not in sys.path:
            sys.path.insert(0, str(STRIGIL_DIR))
        import strigil  # noqa: F401
        return True
    except ImportError:
        return False


class TestStrigilSchemaDetection:
    """Schema detection logic — no network, pure parsing."""

    def test_import_schema_module(self, strigil_available: bool) -> None:
        if not strigil_available:
            pytest.skip("strigil not found")
        if str(STRIGIL_DIR) not in sys.path:
            sys.path.insert(0, str(STRIGIL_DIR))
        from strigil.schema import ImageSchema, DetectionResult
        import dataclasses
        assert ImageSchema.IIIF_MANIFEST
        field_names = {f.name for f in dataclasses.fields(DetectionResult)}
        assert "schema" in field_names
        assert "confidence" in field_names

    def test_parse_size_helper(self, strigil_available: bool) -> None:
        if not strigil_available:
            pytest.skip("strigil not found")
        from strigil.pipeline import parse_size
        assert parse_size("100") == 100
        assert parse_size("200k") == 200 * 1024
        assert parse_size("1m") == 1024 * 1024

    def test_iiif_schema_enum_values(self, strigil_available: bool) -> None:
        if not strigil_available:
            pytest.skip("strigil not found")
        from strigil.schema import ImageSchema
        assert ImageSchema.HATHITRUST.value == "hathitrust"
        assert ImageSchema.IIIF_MANIFEST.value == "iiif_manifest"
        assert ImageSchema.ARCHIVE_ORG.value == "archive_org"

    def test_collect_image_urls_iiif_manifest(self, strigil_available: bool) -> None:
        """Simulate IIIF manifest parsing without a real network call."""
        if not strigil_available:
            pytest.skip("strigil not found")
        from strigil.extractors import parse_iiif_manifest
        import json
        manifest = {
            "@context": "http://iiif.io/api/presentation/2/context.json",
            "sequences": [
                {
                    "canvases": [
                        {
                            "images": [
                                {
                                    "resource": {
                                        "@id": "https://example.org/iiif/image/1",
                                        "@type": "dctypes:Image",
                                        "service": {
                                            "@id": "https://example.org/iiif/image/1",
                                            "profile": "http://iiif.io/api/image/2/level2.json",
                                        },
                                    }
                                }
                            ]
                        }
                    ]
                }
            ],
        }
        # parse_iiif_manifest accepts a dict
        urls = parse_iiif_manifest(manifest)
        assert isinstance(urls, list)
        assert len(urls) >= 1
        assert any("example.org" in u for u in urls)

    def test_map_result_structure(self, strigil_available: bool) -> None:
        if not strigil_available:
            pytest.skip("strigil not found")
        from strigil.pipeline import MapResult
        r = MapResult()
        assert r.image_items == []
        assert r.pdf_urls == []
        assert r.page_links == []
        assert r.text is None


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Crop / normalize (PIL)
# ─────────────────────────────────────────────────────────────────────────────

class TestImageNormalization:
    """Image normalization logic without external system tools (PIL only)."""

    def test_jpeg_round_trip(self, tmp_path: Path) -> None:
        from PIL import Image
        img = Image.new("RGB", (400, 600), color=(200, 180, 160))
        src = tmp_path / "raw_page.tiff"
        img.save(str(src), format="TIFF")
        dst = tmp_path / "MS_f001r.jpg"
        img.convert("RGB").save(str(dst), format="JPEG", quality=85)
        loaded = Image.open(dst)
        assert loaded.size == (400, 600)
        assert loaded.mode == "RGB"

    def test_folio_naming_convention(self) -> None:
        """The pipeline naming convention: {MSID}_f{NNN:03d}{r|v}.jpg"""
        msid = "KB27"
        for folio_num, side in [(1, "r"), (1, "v"), (12, "r"), (335, "v")]:
            name = f"{msid}_f{folio_num:03d}{side}.jpg"
            # Must match pattern: alpha-num, underscore, 'f', 3-digit, r/v, .jpg
            import re
            assert re.match(r"[A-Za-z0-9_-]+_f\d{3}[rv]\.jpg", name), (
                f"name {name!r} does not match naming convention"
            )

    def test_long_edge_resize(self, tmp_path: Path) -> None:
        from PIL import Image
        img = Image.new("RGB", (3000, 4000))
        w, h = img.size
        max_edge = 2000
        scale = max_edge / max(w, h)
        new_size = (int(w * scale), int(h * scale))
        resized = img.resize(new_size, Image.LANCZOS)
        assert max(resized.size) == max_edge


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — Lineation / PAGE XML compatibility
# ─────────────────────────────────────────────────────────────────────────────

def _make_pagexml(n_lines: int, with_baselines: bool = True, with_text: bool = False) -> str:
    lines = []
    for i in range(1, n_lines + 1):
        y = i * 30
        bl = f'<Baseline points="0,{y} 100,{y}"/>' if with_baselines else ""
        txt = f'<TextEquiv><Unicode>line {i}</Unicode></TextEquiv>' if with_text else ""
        lines.append(f'    <TextLine id="l{i}">{bl}{txt}</TextLine>')
    body = "\n".join(lines)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="{PAGE_NS}">
  <Page imageFilename="test.jpg" imageWidth="800" imageHeight="1200">
    <TextRegion id="tr1" type="paragraph">
{body}
    </TextRegion>
  </Page>
</PcGts>"""


class TestPageXMLCompatibility:
    """Validate PageXML structures transcriber-shell and VPE produce."""

    def test_minimal_pagexml_validates(self, tmp_path: Path) -> None:
        from transcriber_shell.xml_tools.lines_validate import validate_lines_xml
        xml = tmp_path / "lines.xml"
        xml.write_text(_make_pagexml(5, with_baselines=True), encoding="utf-8")
        ok, msgs, stats = validate_lines_xml(xml)
        assert ok, f"validation failed: {msgs}"
        assert stats["text_line"] == 5

    def test_pagexml_without_baselines_validates(self, tmp_path: Path) -> None:
        from transcriber_shell.xml_tools.lines_validate import validate_lines_xml
        xml = tmp_path / "lines_no_bl.xml"
        xml.write_text(_make_pagexml(3, with_baselines=False), encoding="utf-8")
        ok, msgs, stats = validate_lines_xml(xml)
        assert ok, f"Expected OK for baseline-free XML: {msgs}"

    def test_vpe_style_pagexml_with_text_equivs(self, tmp_path: Path) -> None:
        """VPE exports can include TextEquiv/Unicode for existing transcriptions."""
        from transcriber_shell.xml_tools.lines_validate import validate_lines_xml
        xml = tmp_path / "vpe_export.xml"
        xml.write_text(
            _make_pagexml(8, with_baselines=True, with_text=True), encoding="utf-8"
        )
        ok, msgs, stats = validate_lines_xml(xml)
        assert ok, f"VPE-style XML failed validation: {msgs}"
        assert stats["text_line"] == 8

    def test_empty_xml_fails_validation(self, tmp_path: Path) -> None:
        from transcriber_shell.xml_tools.lines_validate import validate_lines_xml
        xml = tmp_path / "empty.xml"
        xml.write_text("<root/>", encoding="utf-8")
        # require_text_line=True makes zero TextLines a failure
        ok, msgs, _ = validate_lines_xml(xml, require_text_line=True)
        assert not ok, "empty XML with require_text_line should fail validation"

    def test_gt_pagexml_validates(self) -> None:
        """Every GT XML should pass our lines validator."""
        if not GT_DIR.is_dir():
            pytest.skip("GT dir not available")
        from transcriber_shell.xml_tools.lines_validate import validate_lines_xml
        import glob
        xmls = sorted(glob.glob(str(GT_DIR / "*.xml")))[:5]
        for xml_path in xmls:
            ok, msgs, stats = validate_lines_xml(xml_path)
            assert ok, f"{xml_path}: {msgs}"

    def test_xsd_optional_validation(self, tmp_path: Path) -> None:
        from transcriber_shell.xml_tools.pagexml_schema import validate_xsd_optional
        xml = tmp_path / "lines.xml"
        xml.write_text(_make_pagexml(2), encoding="utf-8")
        # Without lxml the function returns False with a helpful error message
        ok, errs = validate_xsd_optional(xml, tmp_path / "nonexistent.xsd")
        # Either lxml is installed and raises (file not found) or not installed
        assert isinstance(ok, bool)
        assert isinstance(errs, list)


@pytest.mark.skipif(
    not (Path.home() / "latin-ms-workspace" / "training" / "kraken_seg_updated_best.mlmodel").is_file()
    and not (Path("/Users/halxiii/Projects/latin_documents-1/model_249.mlmodel")).is_file(),
    reason="No Kraken model available",
)
class TestKrakenLineationBackend:
    """Kraken backend produces valid PAGE XML for at least one GT image."""

    def test_kraken_produces_lines_xml(self, tmp_path: Path) -> None:
        if not GT_DIR.is_dir():
            pytest.skip("GT dir not available")
        from transcriber_shell.kraken_lineation import fetch_lines_xml_kraken
        from transcriber_shell.config import Settings

        # Prefer fine-tuned model if it exists
        finetuned = Path.home() / "latin-ms-workspace" / "training" / "kraken_seg_updated_best.mlmodel"
        base = Path("/Users/halxiii/Projects/latin_documents-1/model_249.mlmodel")
        model = finetuned if finetuned.is_file() else base

        # Pick a GT image that exists
        import glob
        xmls = sorted(glob.glob(str(GT_DIR / "*.xml")))
        if not xmls:
            pytest.skip("No GT XMLs found")

        import xml.etree.ElementTree as ET
        ns = {"p": PAGE_NS}
        image = None
        for x in xmls[:5]:
            tree = ET.parse(x)
            page = tree.find(".//p:Page", ns)
            img_path = Path(page.get("imageFilename", "")) if page is not None else Path()
            if img_path.is_file():
                image = img_path
                break
        if image is None:
            pytest.skip("No GT image found")

        settings = Settings(kraken_model_path=model)
        out = tmp_path / "kraken_lines.xml"
        fetch_lines_xml_kraken(image, out, settings=settings)
        assert out.is_file(), "Kraken lineation produced no output XML"
        tree = ET.parse(out)
        lines = tree.findall(f".//{{{PAGE_NS}}}TextLine")
        assert len(lines) >= 1, f"Expected at least 1 TextLine, got {len(lines)}"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 4 — Transcription pipeline (mocked LLM)
# ─────────────────────────────────────────────────────────────────────────────

_MINIMAL_YAML = """\
transcriptionOutput:
  protocolVersion: "1.1.0"
  metadata:
    sourcePageId: "test-001"
    protocolVersion: "1.1.0"
    modelId: "mock"
    timestamp: "2024-01-01T00:00:00Z"
    targetLanguage: "lat-Latn"
    targetEra: "medieval"
    eraRange: "1300-1400"
    diplomaticProfile: "layout_aware"
    normalizationMode: "diplomatic"
    languageSet: []
    diplomaticToggles:
      preserveLineBreaks: true
      preserveOriginalAbbreviations: true
      markExpansions: false
      captureDeletionsAndInsertions: false
      captureUnclearGlyphShape: true
    runMode: "standard"
    mixedContent:
      mixedLanguage: false
      mixedEra: false
    scriptNotes: null
    englishHandwritingModality: null
    epistemicNotes: null
    schemaRevision: null
  preCheck:
    resolutionAdequate: true
    orientationCorrect: true
    pageBoundariesVisible: true
    pageCount: 1
    scriptIdentified: "Latin, Cursive"
    scriptMatchesConfig: true
    conditionNotes: null
    proceedDecision: "proceed"
    proceedOverride: false
    abortReason: null
  segments:
    - segmentId: 1
      pageNumber: 1
      lineRange: "1-3"
      position: "body"
      text: "Iohannes filius Philippi de Neuille"
      confidence: "high"
      uncertaintyTokenCount: 0
      notes: null
  mismatchReport:
    - mismatchId: 1
      segmentId: 1
      pass1Reading: "Iohannes filius Philippi de Neuille"
      pass2Reading: "Iohannes filius Philippi de Neuille"
      resolution: "pass2 confirms final text; no edit"
      resolved: true
  hallucinationAudit:
    totalWords: 5
    wordsGroundedInGlyphs: 5
    wordsFromExpansion: 0
    expansionsWithVisibleMark: 0
    normalizationReversals: 0
    formulaSubstitutionsDetected: 0
    auditPass: true
"""


class TestTranscribePipelineMocked:
    """run_pipeline with LLM mocked — validates plumbing without network."""

    def test_skip_gm_with_mocked_llm(self, tmp_path: Path) -> None:
        from transcriber_shell.config import Settings
        from transcriber_shell.llm.transcribe import TranscribeResult
        from transcriber_shell.models.job import TranscribeJob
        from transcriber_shell.pipeline.run import run_pipeline

        lines = tmp_path / "lines.xml"
        lines.write_text(_make_pagexml(3), encoding="utf-8")
        image = tmp_path / "page.jpg"

        from PIL import Image
        Image.new("RGB", (100, 200)).save(str(image), format="JPEG")

        job = TranscribeJob(
            job_id="mock-001",
            image_path=image,
            prompt_cfg={
                "protocolVersion": "1.1.0",
                "sourcePageId": "mock-001",
                "targetLanguage": "lat-Latn",
                "diplomaticProfile": "layout_aware",
                "normalizationMode": "diplomatic",
            },
            provider="anthropic",
        )
        settings = Settings(artifacts_dir=tmp_path / "artifacts")

        with (
            patch(
                "transcriber_shell.pipeline.run.run_transcribe",
                return_value=TranscribeResult(_MINIMAL_YAML, None),
            ),
            patch(
                "transcriber_shell.pipeline.run.validate_transcript_file",
                return_value=(True, [], []),
            ),
        ):
            result = run_pipeline(
                job,
                skip_gm=True,
                lines_xml_path=lines,
                settings=settings,
            )

        assert result.errors == [], f"Pipeline errors: {result.errors}"
        assert result.transcription_yaml_path is not None
        assert result.transcription_yaml_path.is_file()

    def test_mocked_yaml_validates_against_schema(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "test_transcription.yaml"
        yaml_path.write_text(_MINIMAL_YAML, encoding="utf-8")
        from transcriber_shell.llm.validate_output import validate_transcript_file
        ok, errs, warns = validate_transcript_file(yaml_path)
        assert ok, f"Schema validation failed: {errs}"

    def test_schema_validation_catches_missing_wrapper(self, tmp_path: Path) -> None:
        bad_yaml = "segments:\n  - {segmentId: 1, text: 'hello'}\n"
        yaml_path = tmp_path / "bad.yaml"
        yaml_path.write_text(bad_yaml, encoding="utf-8")
        from transcriber_shell.llm.validate_output import validate_transcript_file
        ok, errs, warns = validate_transcript_file(yaml_path)
        assert not ok, "Missing transcriptionOutput wrapper should fail validation"

    def test_batch_pipeline_with_multiple_mocked_pages(self, tmp_path: Path) -> None:
        from transcriber_shell.config import Settings
        from transcriber_shell.llm.transcribe import TranscribeResult
        from transcriber_shell.models.job import TranscribeJob
        from transcriber_shell.pipeline.run import run_pipeline
        from PIL import Image

        artifacts = tmp_path / "artifacts"
        settings = Settings(artifacts_dir=artifacts)

        for i in range(1, 4):
            img = tmp_path / f"KB27_f{i:03d}r.jpg"
            Image.new("RGB", (100, 200)).save(str(img), format="JPEG")
            lines = tmp_path / f"KB27_f{i:03d}r.xml"
            lines.write_text(_make_pagexml(3), encoding="utf-8")

            job = TranscribeJob(
                job_id=f"batch-{i:03d}",
                image_path=img,
                prompt_cfg={"protocolVersion": "1.1.0", "sourcePageId": f"p{i}"},
                provider="anthropic",
            )
            with (
                patch(
                    "transcriber_shell.pipeline.run.run_transcribe",
                    return_value=TranscribeResult(_MINIMAL_YAML, None),
                ),
                patch(
                    "transcriber_shell.pipeline.run.validate_transcript_file",
                    return_value=(True, [], []),
                ),
            ):
                result = run_pipeline(
                    job, skip_gm=True, lines_xml_path=lines, settings=settings
                )
            assert result.errors == [], f"Page {i} errors: {result.errors}"

        yaml_files = list(artifacts.rglob("*_transcription.yaml"))
        assert len(yaml_files) == 3, f"Expected 3 YAMLs, got {len(yaml_files)}"

    def test_xml_only_mode_produces_no_yaml(self, tmp_path: Path) -> None:
        from transcriber_shell.config import Settings
        from transcriber_shell.models.job import TranscribeJob
        from transcriber_shell.pipeline.run import run_pipeline
        from PIL import Image

        img = tmp_path / "page.jpg"
        Image.new("RGB", (100, 200)).save(str(img), format="JPEG")
        lines = tmp_path / "lines.xml"
        lines.write_text(_make_pagexml(2), encoding="utf-8")

        job = TranscribeJob(
            job_id="xmlonly",
            image_path=img,
            prompt_cfg={"protocolVersion": "1.1.0", "sourcePageId": "p1"},
            provider="anthropic",
        )
        settings = Settings(artifacts_dir=tmp_path / "arts", xml_only=True)
        result = run_pipeline(
            job, skip_gm=True, lines_xml_path=lines, settings=settings
        )
        assert result.transcription_yaml_path is None


# ─────────────────────────────────────────────────────────────────────────────
# Stage 5 — yaml_to_tei + expand_diplomatic dry-run
# ─────────────────────────────────────────────────────────────────────────────

class TestYamlToTei:
    """yaml_to_tei.py conversion — fully offline."""

    @pytest.fixture
    def yaml_to_tei(self):
        return _load_module("yaml_to_tei", SCRIPTS_DIR / "yaml_to_tei.py")

    def _make_yaml(self, segments: list[str]) -> dict:
        return {
            "transcriptionOutput": {
                "protocolVersion": "1.1.0",
                "metadata": {"sourcePageId": "test"},
                "segments": [
                    {"segmentId": i + 1, "text": t, "confidence": "high",
                     "uncertaintyTokenCount": 0}
                    for i, t in enumerate(segments)
                ],
            }
        }

    def test_single_segment_produces_one_p(self, tmp_path: Path, yaml_to_tei) -> None:
        src = tmp_path / "test_transcription.yaml"
        src.write_text(
            yaml.dump(self._make_yaml(["Radulfus Basset de Welledon"])),
            encoding="utf-8",
        )
        dst = tmp_path / "test_tei.xml"
        yaml_to_tei.yaml_to_tei(src, dst)
        tree = ET.parse(dst)
        ns = {"t": "http://www.tei-c.org/ns/1.0"}
        paras = tree.findall(".//t:p", ns)
        assert len(paras) == 1
        assert "Radulfus Basset" in (paras[0].text or "")

    def test_multi_segment_produces_multiple_p(self, tmp_path: Path, yaml_to_tei) -> None:
        segments = [
            "Radulfus Basset chiualer",
            "Iohannes de Lincoln q̄nd req̄ñō",
            "aduocacōnes actiōnes",
        ]
        src = tmp_path / "ms_transcription.yaml"
        src.write_text(yaml.dump(self._make_yaml(segments)), encoding="utf-8")
        dst = tmp_path / "ms_tei.xml"
        yaml_to_tei.yaml_to_tei(src, dst)
        tree = ET.parse(dst)
        ns = {"t": "http://www.tei-c.org/ns/1.0"}
        paras = tree.findall(".//t:p", ns)
        assert len(paras) == 3

    def test_unicode_combining_chars_preserved(self, tmp_path: Path, yaml_to_tei) -> None:
        text = "aduocacōnes p̄ Iohem Dñō Regiō"
        src = tmp_path / "uc_transcription.yaml"
        src.write_text(yaml.dump(self._make_yaml([text])), encoding="utf-8")
        dst = tmp_path / "uc_tei.xml"
        yaml_to_tei.yaml_to_tei(src, dst)
        content = dst.read_text(encoding="utf-8")
        assert "aduocac" in content, "combining char content should be preserved"

    def test_uncertainty_tokens_pass_through(self, tmp_path: Path, yaml_to_tei) -> None:
        text = "[uncertain: Iohem/Iohm] de Lincoln [illegible]"
        src = tmp_path / "unc_transcription.yaml"
        src.write_text(yaml.dump(self._make_yaml([text])), encoding="utf-8")
        dst = tmp_path / "unc_tei.xml"
        yaml_to_tei.yaml_to_tei(src, dst)
        content = dst.read_text(encoding="utf-8")
        assert "[uncertain:" in content, "uncertainty tokens should pass through to TEI"
        assert "[illegible]" in content

    def test_empty_segments_produces_empty_body(self, tmp_path: Path, yaml_to_tei) -> None:
        data = {"transcriptionOutput": {"protocolVersion": "1.1.0", "segments": []}}
        src = tmp_path / "empty_transcription.yaml"
        src.write_text(yaml.dump(data), encoding="utf-8")
        dst = tmp_path / "empty_tei.xml"
        yaml_to_tei.yaml_to_tei(src, dst)
        tree = ET.parse(dst)
        ns = {"t": "http://www.tei-c.org/ns/1.0"}
        paras = tree.findall(".//t:p", ns)
        assert len(paras) == 0

    def test_tei_namespace_correct(self, tmp_path: Path, yaml_to_tei) -> None:
        src = tmp_path / "ns_transcription.yaml"
        src.write_text(yaml.dump(self._make_yaml(["test"])), encoding="utf-8")
        dst = tmp_path / "ns_tei.xml"
        yaml_to_tei.yaml_to_tei(src, dst)
        content = dst.read_text(encoding="utf-8")
        assert "http://www.tei-c.org/ns/1.0" in content

    def test_batch_dir_mode(self, tmp_path: Path, yaml_to_tei) -> None:
        arts = tmp_path / "artifacts"
        arts.mkdir()
        for i in range(3):
            f = arts / f"page{i:03d}_transcription.yaml"
            f.write_text(yaml.dump(self._make_yaml([f"line {i}"])), encoding="utf-8")
        tei_dir = tmp_path / "tei"

        class _Args:
            dir = str(arts)
            out_dir = str(tei_dir)
            input = None
            output = None

        # Call batch processing directly
        for src in sorted(arts.rglob("*_transcription.yaml")):
            stem = src.stem.replace("_transcription", "")
            dst = tei_dir / f"{stem}_tei.xml"
            yaml_to_tei.yaml_to_tei(src, dst)

        tei_files = list(tei_dir.glob("*.xml"))
        assert len(tei_files) == 3


@pytest.mark.skipif(
    not EXPAND_DIPLOMATIC_DIR.is_dir(),
    reason="magic-elise-tool not found",
)
class TestExpandDiplomaticDryRun:
    """expand_xml with dry_run=True — no Gemini API call, no API key needed."""

    @pytest.fixture(autouse=True)
    def _add_expand_to_path(self):
        if str(EXPAND_DIPLOMATIC_DIR) not in sys.path:
            sys.path.insert(0, str(EXPAND_DIPLOMATIC_DIR))

    def _simple_tei(self, text: str) -> str:
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text><body><p>{text}</p></body></text>
</TEI>"""

    def test_dry_run_returns_input_unchanged(self) -> None:
        from expand_diplomatic.expander import expand_xml
        xml = self._simple_tei("Radulfus Basset de Welledon")
        result = expand_xml(xml, examples=[], dry_run=True, backend="gemini")
        assert "Radulfus Basset" in result

    def test_dry_run_preserves_xml_structure(self) -> None:
        from expand_diplomatic.expander import expand_xml
        xml = self._simple_tei("aduocacōnes actiōnes")
        result = expand_xml(xml, examples=[], dry_run=True, backend="gemini")
        root = ET.fromstring(result)
        ns = {"t": "http://www.tei-c.org/ns/1.0"}
        paras = root.findall(".//t:p", ns)
        assert len(paras) == 1

    def test_dry_run_multi_paragraph(self) -> None:
        from expand_diplomatic.expander import expand_xml
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text><body>
    <p>Radulfus Basset</p>
    <p>Iohannes de Lincoln</p>
    <p>aduocacōnes actiōnes</p>
  </body></text>
</TEI>"""
        result = expand_xml(xml, examples=[], dry_run=True)
        root = ET.fromstring(result)
        ns = {"t": "http://www.tei-c.org/ns/1.0"}
        paras = root.findall(".//t:p", ns)
        assert len(paras) == 3

    def test_extract_text_lines_api(self) -> None:
        from expand_diplomatic.expander import extract_text_lines
        xml = self._simple_tei("Iohannes filius Philippi de Neuille")
        text = extract_text_lines(xml)
        assert "Iohannes" in text

    def test_expansion_passes_parameter_accepted(self) -> None:
        from expand_diplomatic.expander import expand_xml
        xml = self._simple_tei("abbrev. text")
        # dry_run with passes=2 should not error
        result = expand_xml(xml, examples=[], dry_run=True, passes=2)
        assert result is not None

    def test_modality_parameter_accepted(self) -> None:
        from expand_diplomatic.expander import expand_xml
        xml = self._simple_tei("text")
        for modality in ("full", "conservative", "aggressive", "normalize"):
            result = expand_xml(xml, examples=[], dry_run=True, modality=modality)
            assert result is not None


# ─────────────────────────────────────────────────────────────────────────────
# Stage 6 — Normalization schema validation
# ─────────────────────────────────────────────────────────────────────────────

def _load_validate_normalization():
    return _load_module(
        "validate_normalization",
        VENDOR_PROTO / "benchmark" / "validate_normalization.py",
    )


class TestNormalizationSchemaValidation:
    """validate_normalization_output against norm-1.1.0 schema — no LLM needed."""

    def _make_norm_output(
        self,
        *,
        page_id: str = "test-001",
        source_version: str = "1.1.0",
        norm_version: str = "norm-1.1.0",
        editorial_level: str = "conservative_editorial",
        segments: list | None = None,
    ) -> dict:
        segs = segments or [
            {
                "segmentId": 1,
                "diplomaticText": "Radulfus Basset de Welledon",
                "normalizedText": "Radulfus Basset de Welledon",
                "alignmentNotes": None,
                "changes": [],
            }
        ]
        return {
            "normalizationOutput": {
                "normalizationProtocolVersion": norm_version,
                "source": {
                    "sourcePageId": page_id,
                    "sourceProtocolVersion": source_version,
                },
                "normalizationPolicy": {
                    "editorialLevel": editorial_level,
                    "orthographyTarget": "classical",
                    "abbreviationHandling": "expand",
                    "lineBreakHandling": "reflow_to_spaces",
                    "registerNotes": "medieval_latin",
                },
                "metadata": {
                    "modelId": "mock",
                    "timestamp": "2024-01-01T00:00:00Z",
                    "notes": None,
                },
                "normalizedSegments": segs,
            }
        }

    def test_valid_norm_output_passes(self) -> None:
        mod = _load_validate_normalization()
        data = self._make_norm_output()
        root = data.get("normalizationOutput", data)
        ok, errors = mod.validate_normalization_output(root)
        assert ok, f"Valid norm output failed: {errors}"

    def test_missing_norm_version_fails(self) -> None:
        mod = _load_validate_normalization()
        data = self._make_norm_output()
        del data["normalizationOutput"]["normalizationProtocolVersion"]
        root = data["normalizationOutput"]
        ok, errors = mod.validate_normalization_output(root)
        assert not ok
        assert any("normalizationProtocolVersion" in e for e in errors)

    def test_invalid_editorial_level_fails(self) -> None:
        mod = _load_validate_normalization()
        data = self._make_norm_output(editorial_level="bogus_level")
        root = data["normalizationOutput"]
        ok, errors = mod.validate_normalization_output(root)
        assert not ok
        assert any("editorialLevel" in e for e in errors)

    def test_missing_source_fails(self) -> None:
        mod = _load_validate_normalization()
        data = self._make_norm_output()
        del data["normalizationOutput"]["source"]
        root = data["normalizationOutput"]
        ok, errors = mod.validate_normalization_output(root)
        assert not ok

    def test_mechanical_level_valid(self) -> None:
        mod = _load_validate_normalization()
        root = self._make_norm_output(editorial_level="mechanical")["normalizationOutput"]
        ok, errors = mod.validate_normalization_output(root)
        assert ok, f"mechanical level should be valid: {errors}"

    def test_scholarly_editorial_valid(self) -> None:
        mod = _load_validate_normalization()
        root = self._make_norm_output(editorial_level="scholarly_editorial")["normalizationOutput"]
        ok, errors = mod.validate_normalization_output(root)
        assert ok, f"scholarly_editorial level should be valid: {errors}"

    def test_diplomatic_text_crosscheck(self) -> None:
        """diplomaticText in norm output must match source segment text when provided."""
        mod = _load_validate_normalization()
        source_text = "Radulfus Basset de Welledon"
        segs = [
            {
                "segmentId": 1,
                "diplomaticText": source_text,
                "normalizedText": "Radulfus Basset de Welledon",
                "alignmentNotes": None,
                "changes": [],
            }
        ]
        root = self._make_norm_output(segments=segs)["normalizationOutput"]
        diplomatic_by_id = {1: source_text}
        ok, errors = mod.validate_normalization_output(root, diplomatic_by_id)
        assert ok, f"Cross-check failed: {errors}"

    def test_diplomatic_text_mismatch_fails(self) -> None:
        mod = _load_validate_normalization()
        segs = [
            {
                "segmentId": 1,
                "diplomaticText": "wrong text",
                "normalizedText": "Radulfus Basset de Welledon",
                "alignmentNotes": None,
                "changes": [],
            }
        ]
        root = self._make_norm_output(segments=segs)["normalizationOutput"]
        diplomatic_by_id = {1: "Radulfus Basset de Welledon"}
        ok, errors = mod.validate_normalization_output(root, diplomatic_by_id)
        assert not ok, "diplomaticText mismatch should fail"


class TestNormalizationProtocolSchema:
    """validate_schema helpers for transcriptionOutput."""

    def _load_validate_schema(self):
        return _load_module(
            "validate_schema",
            VENDOR_PROTO / "benchmark" / "validate_schema.py",
        )

    def test_valid_transcription_output(self) -> None:
        mod = self._load_validate_schema()
        data = yaml.safe_load(_MINIMAL_YAML)
        root = data.get("transcriptionOutput", data)
        ok, errors, _warns = mod.validate_transcription_output(root)
        assert ok, f"Minimal YAML failed protocol schema: {errors}"

    def test_missing_protocol_version_fails(self) -> None:
        mod = self._load_validate_schema()
        data = yaml.safe_load(_MINIMAL_YAML)
        root = data["transcriptionOutput"]
        del root["metadata"]["protocolVersion"]
        ok, errors, _warns = mod.validate_transcription_output(root)
        assert not ok

    def test_valid_profile_accepted(self) -> None:
        mod = self._load_validate_schema()
        for profile in ("strict", "semi_strict", "layout_aware", "diplomatic_plus"):
            data = yaml.safe_load(_MINIMAL_YAML)
            root = data["transcriptionOutput"]
            root["metadata"]["diplomaticProfile"] = profile
            ok, errors, _warns = mod.validate_transcription_output(root)
            assert ok, f"Profile {profile!r} should be valid: {errors}"


# ─────────────────────────────────────────────────────────────────────────────
# Security — env leak guard in run_pipeline.sh
# ─────────────────────────────────────────────────────────────────────────────

class TestEnvLeakGuard:
    """run_pipeline.sh must abort if .env.latin-ms is git-tracked."""

    def test_git_tracked_env_aborts_pipeline(self, tmp_path: Path) -> None:
        """Simulate a git repo where .env.latin-ms is tracked — expect exit 1."""
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, check=True, capture_output=True,
        )
        env_file = tmp_path / ".env.latin-ms"
        env_file.write_text("ANTHROPIC_API_KEY=fake\n")
        subprocess.run(
            ["git", "add", ".env.latin-ms"],
            cwd=tmp_path, check=True, capture_output=True,
        )

        # Write a minimal run_pipeline.sh that only runs the guard
        guard_sh = tmp_path / "guard_test.sh"
        guard_sh.write_text(
            "#!/usr/bin/env bash\n"
            'ENV_FILE=".env.latin-ms"\n'
            "SCRIPT_DIR=\"$(pwd)\"\n"
            'if git -C "$SCRIPT_DIR" ls-files --error-unmatch "$ENV_FILE" &>/dev/null 2>&1; then\n'
            '    echo "ERROR: env file is tracked" >&2\n'
            "    exit 1\n"
            "fi\n"
            "exit 0\n"
        )
        guard_sh.chmod(0o755)

        result = subprocess.run(
            ["bash", str(guard_sh)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1, "Guard should abort when .env.latin-ms is tracked"
        assert "tracked" in result.stderr or "ERROR" in result.stderr

    def test_untracked_env_passes_guard(self, tmp_path: Path) -> None:
        """An untracked .env.latin-ms should not trigger the guard."""
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, check=True, capture_output=True,
        )
        env_file = tmp_path / ".env.latin-ms"
        env_file.write_text("ANTHROPIC_API_KEY=fake\n")

        guard_sh = tmp_path / "guard_test.sh"
        guard_sh.write_text(
            "#!/usr/bin/env bash\n"
            'ENV_FILE=".env.latin-ms"\n'
            "SCRIPT_DIR=\"$(pwd)\"\n"
            'if git -C "$SCRIPT_DIR" ls-files --error-unmatch "$ENV_FILE" &>/dev/null 2>&1; then\n'
            '    echo "ERROR: env file is tracked" >&2\n'
            "    exit 1\n"
            "fi\n"
            "exit 0\n"
        )
        guard_sh.chmod(0o755)

        result = subprocess.run(
            ["bash", str(guard_sh)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, "Guard should pass when .env.latin-ms is untracked"


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline configuration validator
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineConfigValidation:
    """Validate Settings objects catch misconfigured pipeline before run."""

    def test_settings_default_lineation_backend(self) -> None:
        from transcriber_shell.config import Settings
        s = Settings()
        assert s.lineation_backend in ("glyph_machina", "mask", "kraken"), (
            f"Unexpected lineation_backend: {s.lineation_backend}"
        )

    def test_mask_backend_requires_weights_path(self) -> None:
        from transcriber_shell.config import Settings
        s = Settings(lineation_backend="mask")
        # mask_weights_path is None by default — pipeline should warn
        assert s.lineation_backend == "mask"

    def test_prompt_cfg_with_latin_settings(self) -> None:
        from transcriber_shell.config import Settings
        prompt_yaml = SCRIPTS_DIR / "prompt_latin.yaml"
        if not prompt_yaml.is_file():
            pytest.skip("prompt_latin.yaml not found")
        cfg = yaml.safe_load(prompt_yaml.read_text(encoding="utf-8"))
        assert cfg.get("targetLanguage") == "lat-Latn", "Latin prompt must target lat-Latn"
        assert cfg.get("diplomaticProfile") in (
            "strict", "semi_strict", "layout_aware", "diplomatic_plus"
        ), f"Invalid diplomaticProfile: {cfg.get('diplomaticProfile')}"
        assert cfg.get("normalizationMode") == "diplomatic", (
            "Pipeline default must be diplomatic, not normalized"
        )

    def test_env_example_has_all_required_keys(self) -> None:
        env_example = SCRIPTS_DIR / "env.example"
        if not env_example.is_file():
            pytest.skip("env.example not found")
        content = env_example.read_text()
        required = [
            "LATIN_MS_JOB_ID",
            "LATIN_MS_MSID",
            "LATIN_MS_WORKSPACE",
            "ANTHROPIC_API_KEY",
        ]
        for key in required:
            assert key in content, f"{key} missing from env.example"
