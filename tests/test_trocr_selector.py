"""TrOCR wiring in HTR selector and task builder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from transcriber_shell.config import Settings
from transcriber_shell.htr.parallel import build_htr_tasks
from transcriber_shell.htr.selector import plan_htr_execution


def test_trocr_task_when_enabled(tmp_path: Path) -> None:
    img = tmp_path / "p.png"
    xml = tmp_path / "p.xml"
    img.write_bytes(b"x")
    xml.write_text("<PcGts/>", encoding="utf-8")
    s = Settings(trocr_enabled=True, trocr_model="microsoft/trocr-base-handwritten")
    tasks = build_htr_tasks(img, xml, {"latin-french"}, s)
    assert "trocr-htr" in tasks


def test_trocr_htr_only_plan(tmp_path: Path) -> None:
    img = tmp_path / "p.png"
    xml = tmp_path / "p.xml"
    img.write_bytes(b"x")
    xml.write_text("<PcGts/>", encoding="utf-8")
    s = Settings(trocr_enabled=True, htr_combination="trocr_htr_only")
    tasks = build_htr_tasks(img, xml, {"latin-french"}, s)
    plan = plan_htr_execution(s, tasks)
    assert plan.kind.value == "htr_only"
    assert plan.tasks and "trocr-htr" in plan.tasks


def test_run_trocr_htr_mock(tmp_path: Path) -> None:
    from transcriber_shell.htr.trocr_htr import run_trocr_htr

    img = tmp_path / "p.png"
    xml = tmp_path / "p.xml"
    xml.write_text(
        """<?xml version="1.0"?>
<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15">
  <Page imageFilename="p.png" imageWidth="20" imageHeight="20">
    <TextLine id="l1"><Coords points="1,1 18,1 18,18 1,18"/></TextLine>
  </Page>
</PcGts>""",
        encoding="utf-8",
    )
    try:
        from PIL import Image
    except ImportError:
        return
    Image.new("RGB", (20, 20)).save(img)

    mock_processor = MagicMock()
    mock_processor.batch_decode.return_value = ["hello"]
    mock_model = MagicMock()
    mock_model.generate.return_value = MagicMock(sequences=MagicMock(), scores=None)

    with patch("transcriber_shell.htr.trocr_htr._load_trocr", return_value=(mock_processor, mock_model, "cpu")):
        mock_processor.return_value = MagicMock()
        mock_processor.side_effect = lambda **kw: MagicMock(pixel_values=MagicMock())
        # Fix processor call
        pixel = MagicMock()
        mock_processor.return_value = pixel
        import torch

        pixel.pixel_values = torch.zeros(1, 3, 20, 20)
        with patch("transcriber_shell.htr.trocr_htr._load_trocr") as load:
            proc = MagicMock()
            proc.return_value.pixel_values = torch.zeros(1, 3, 20, 20)
            proc.batch_decode.return_value = ["line one"]
            model = MagicMock()
            model.generate.return_value = MagicMock(sequences=torch.tensor([[1, 2]]), scores=None)
            load.return_value = (proc, model, "cpu")
            result = run_trocr_htr(img, xml, device="cpu")
    assert result.backend == "trocr-htr"
    assert result.line_count == 1
