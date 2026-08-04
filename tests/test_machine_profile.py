"""Host efficiency: same pipeline shape, host-tuned Settings only."""

from __future__ import annotations

from unittest.mock import patch

from transcriber_shell.config import Settings
from transcriber_shell.runtime.machine_profile import (
    MachineProfile,
    apply_machine_efficiency,
    recommend_settings,
    stage_routing_advice,
)


def _prof(**kwargs) -> MachineProfile:
    base = dict(
        hostname="test",
        alias="test",
        host_class="local_metal",
        cpus=8,
        mem_gb=16.0,
        load1=1.0,
    )
    base.update(kwargs)
    return MachineProfile(**base)


def _assert_same_pipeline_shape(updates: dict) -> None:
    """Every host keeps HTR + correct LLM — no stage dropping."""
    assert updates["htr_combination"] == "kraken_htr"
    assert updates["llm_mode"] == "correct"
    assert updates["lineation_backend"] == "kraken"
    assert updates["reuse_lines_xml"] is True


def test_recommend_cuda_4090_parallel():
    p = _prof(
        alias="akdeniz",
        host_class="cuda_interactive",
        cpus=32,
        load1=4.0,
        has_nvidia=True,
        gpu_name="RTX 4090",
        gpu_vram_mb=24564,
    )
    rec = recommend_settings(p)
    _assert_same_pipeline_shape(rec["updates"])
    assert rec["updates"]["batch_parallel_pages"] == 3


def test_recommend_3080_serial():
    p = _prof(
        alias="halxvi",
        host_class="cuda_interactive",
        cpus=12,
        load1=2.0,
        has_nvidia=True,
        gpu_vram_mb=10240,
    )
    rec = recommend_settings(p)
    _assert_same_pipeline_shape(rec["updates"])
    assert rec["updates"]["batch_parallel_pages"] == 1


def test_bridges_login_same_pipeline_not_shell():
    p = _prof(alias="bridges_login", host_class="bridges_login", has_nvidia=False)
    s0 = Settings(htr_combination="kraken_htr", llm_mode="full")
    s, _, msgs = apply_machine_efficiency(s0, profile=p)
    assert s.htr_combination == "kraken_htr"
    assert s.llm_mode == "correct"
    assert s.batch_parallel_pages == 1
    assert not any("→ shell" in m for m in msgs)


def test_bridges_gpu_keeps_llm_correct():
    p = _prof(
        alias="bridges_gpu",
        host_class="bridges_gpu_compute",
        has_nvidia=True,
        gpu_vram_mb=32000,
        slurm_partition="GPU-shared",
        slurm_job_id="123",
    )
    rec = recommend_settings(p)
    _assert_same_pipeline_shape(rec["updates"])
    assert rec["updates"]["batch_parallel_pages"] == 1


def test_all_host_classes_same_stage_settings():
    classes = (
        "local_metal",
        "cuda_interactive",
        "bridges_login",
        "bridges_gpu_compute",
        "cpu_generic",
    )
    shapes = []
    for hc in classes:
        rec = recommend_settings(_prof(host_class=hc, has_nvidia=(hc.startswith("cuda") or "gpu" in hc)))
        u = rec["updates"]
        shapes.append((u["htr_combination"], u["llm_mode"], u["lineation_backend"]))
    assert len(set(shapes)) == 1


def test_stage_routing_nonempty():
    rows = stage_routing_advice(_prof())
    assert len(rows) >= 3
    assert any("pipeline" in r["stage"] for r in rows)


def test_detect_alias_akdeniz():
    from transcriber_shell.runtime import machine_profile as mp

    with patch.object(mp.platform, "node", return_value="akdeniz"):
        with patch.object(mp, "_nvidia_query", return_value=("RTX 4090", 24564, 0.0)):
            with patch.object(mp, "_has_module", return_value=True):
                p = mp.detect_machine_profile()
    assert p.alias == "akdeniz"
    assert p.host_class == "cuda_interactive"
