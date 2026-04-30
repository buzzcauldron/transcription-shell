"""Run one or more HTR backends in parallel alongside the LLM call."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from transcriber_shell.htr.base import HtrResult


def run_htr_parallel(
    tasks: dict[str, Callable[[], HtrResult]],
) -> dict[str, HtrResult | Exception]:
    """Execute HTR backend callables in parallel threads.

    Args:
        tasks: mapping of backend name → zero-arg callable returning HtrResult.

    Returns:
        mapping of backend name → HtrResult on success, or the Exception on failure.
    """
    if not tasks:
        return {}

    results: dict[str, HtrResult | Exception] = {}
    with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        future_to_name = {executor.submit(fn): name for name, fn in tasks.items()}
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result()
            except Exception as exc:  # noqa: BLE001
                results[name] = exc
    return results


def build_htr_tasks(
    image_path: Path,
    lines_xml_path: Path | None,
    scripts: set[str],
    settings,
) -> dict[str, Callable[[], HtrResult]]:
    """Build the tasks dict from settings, filtering by detected scripts.

    Only adds a backend when its required config is present and the detected
    script set overlaps with the backend's supported scripts.
    """
    tasks: dict[str, Callable[[], HtrResult]] = {}

    if lines_xml_path is None:
        return tasks

    # Zenodo medieval-documentary model (Latin/French)
    if (
        settings.kraken_htr_model_path
        and scripts & {"latin-french", "latin"}
    ):
        model_path = Path(settings.kraken_htr_model_path).expanduser().resolve()
        device = getattr(settings, "kraken_device", "cpu")
        _img = image_path
        _xml = lines_xml_path
        _mp = model_path

        from transcriber_shell.htr.kraken_htr import run_kraken_htr

        tasks["kraken-htr"] = lambda: run_kraken_htr(_img, _xml, _mp, device=device)

    # Glyph Machina HTR pipeline
    if settings.gm_htr_repo_path and scripts & {"latin-french", "latin", "english-medieval"}:
        repo_path = Path(settings.gm_htr_repo_path).expanduser().resolve()
        device = getattr(settings, "kraken_device", "cpu")
        _img = image_path
        _xml = lines_xml_path
        _rp = repo_path

        from transcriber_shell.htr.gm_htr import run_gm_htr

        tasks["gm-htr"] = lambda: run_gm_htr(_img, _xml, repo_path=_rp, device=device)

    return tasks
