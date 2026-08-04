"""Detect host capabilities and tune Settings — same pipeline, different knobs.

The transcription pipeline shape is identical on every machine
(lineation → HTR → LLM → post → optional stylo). Auto-efficiency only
adjusts performance-related Settings (parallelism, reuse, preferred
backends/modes). It does **not** drop stages (no forcing ``shell`` /
``llm_mode=off`` by host).

Fleet inventory: scripts/latin_ms/machine_fleet.yaml
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from transcriber_shell.config import Settings

# Knobs auto-efficiency is allowed to touch (pipeline stages stay the same).
_EFFICIENCY_KEYS = frozenset(
    {
        "batch_parallel_pages",
        "reuse_lines_xml",
        "lineation_backend",
        "htr_combination",
        "llm_mode",
    }
)


@dataclass
class MachineProfile:
    hostname: str
    alias: str
    host_class: str
    cpus: int
    mem_gb: float | None
    load1: float | None
    gpu_name: str | None = None
    gpu_vram_mb: int | None = None
    gpu_util_pct: float | None = None
    has_nvidia: bool = False
    has_cuda_torch: bool = False
    has_kraken: bool = False
    slurm_partition: str | None = None
    slurm_job_id: str | None = None
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _cpu_count() -> int:
    return os.cpu_count() or 1


def _mem_gb() -> float | None:
    try:
        if platform.system() == "Darwin":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            return int(out) / (1024**3)
        if Path("/proc/meminfo").is_file():
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb / (1024**2)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None
    return None


def _load1() -> float | None:
    try:
        return os.getloadavg()[0]
    except (AttributeError, OSError):
        return None


def _nvidia_query() -> tuple[str | None, int | None, float | None]:
    if not shutil.which("nvidia-smi"):
        return None, None, None
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=8,
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None, None, None
    if not out:
        return None, None, None
    first = out.splitlines()[0]
    parts = [p.strip() for p in first.split(",")]
    name = parts[0] if parts else None
    vram = None
    util = None
    if len(parts) >= 2:
        try:
            vram = int(float(parts[1]))
        except ValueError:
            vram = None
    if len(parts) >= 3:
        try:
            util = float(parts[2])
        except ValueError:
            util = None
    return name, vram, util


def _has_module(name: str) -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _infer_alias(hostname: str) -> str:
    h = hostname.lower()
    if "akdeniz" in h:
        return "akdeniz"
    if "halxvi" in h or h.startswith("hal"):
        return "halxvi"
    if re.search(r"\bbr\d+\b", h) or "bridges" in h or h.endswith(".psc.edu"):
        if os.environ.get("SLURM_JOB_ID"):
            return "bridges_gpu"
        return "bridges_login"
    if platform.system() == "Darwin":
        return "local"
    return hostname.split(".")[0] or "unknown"


def _infer_host_class(alias: str, has_nvidia: bool) -> str:
    if os.environ.get("SLURM_JOB_ID") and (
        os.environ.get("SLURM_JOB_PARTITION", "").upper().startswith("GPU")
        or os.environ.get("CUDA_VISIBLE_DEVICES") not in (None, "")
        or has_nvidia
    ):
        return "bridges_gpu_compute"
    if alias == "bridges_login" or (
        alias.startswith("bridges") and not has_nvidia and not os.environ.get("SLURM_JOB_ID")
    ):
        return "bridges_login"
    if has_nvidia:
        return "cuda_interactive"
    if platform.system() == "Darwin":
        return "local_metal"
    return "cpu_generic"


def detect_machine_profile() -> MachineProfile:
    hostname = platform.node() or "unknown"
    alias = _infer_alias(hostname)
    gpu_name, vram, util = _nvidia_query()
    has_nvidia = bool(gpu_name)
    host_class = _infer_host_class(alias, has_nvidia)
    if host_class == "bridges_gpu_compute":
        alias = "bridges_gpu"

    warnings: list[str] = []
    notes: list[str] = []
    load1 = _load1()
    cpus = _cpu_count()
    if load1 is not None and load1 > cpus:
        warnings.append(f"load1={load1:.1f} > cpus={cpus}; batch_parallel_pages=1")
    if host_class == "bridges_login":
        notes.append(
            "Same pipeline as other hosts; login has no GPU so HTR will be slow/CPU — "
            "prefer submitting the same job to GPU-shared or running on akdeniz"
        )
    if host_class == "local_metal":
        notes.append(
            "Same pipeline; Metal/CPU HTR is slower — prefer akdeniz for throughput, "
            "or --skip-gm with existing lines XML"
        )
    if host_class == "cuda_interactive" and vram is not None and vram < 12000:
        notes.append("Mid VRAM — batch_parallel_pages=1 to avoid OOM")

    return MachineProfile(
        hostname=hostname,
        alias=alias,
        host_class=host_class,
        cpus=cpus,
        mem_gb=_mem_gb(),
        load1=load1,
        gpu_name=gpu_name,
        gpu_vram_mb=vram,
        gpu_util_pct=util,
        has_nvidia=has_nvidia,
        has_cuda_torch=_has_module("torch") and has_nvidia,
        has_kraken=_has_module("kraken"),
        slurm_partition=os.environ.get("SLURM_JOB_PARTITION"),
        slurm_job_id=os.environ.get("SLURM_JOB_ID"),
        warnings=warnings,
        notes=notes,
    )


def _batch_parallel_for(p: MachineProfile) -> int:
    """Parallel page count only — does not change which stages run."""
    if p.load1 is not None and p.load1 > p.cpus:
        return 1
    if p.host_class in ("bridges_login", "local_metal", "cpu_generic"):
        return 1
    if p.host_class == "bridges_gpu_compute":
        return 1  # typical single V100 gres
    vram = p.gpu_vram_mb or 0
    load_ok = p.load1 is None or p.load1 < p.cpus * 0.7
    if vram >= 20000 and load_ok:
        return 3
    return 1


def recommend_settings(profile: MachineProfile | None = None) -> dict[str, Any]:
    """Return Settings updates. Pipeline stages stay the same on every host."""
    p = profile or detect_machine_profile()
    advice: list[str] = list(p.notes)

    # Shared shape: kraken lineation + kraken HTR + correct-mode LLM + reuse lines.
    # Hosts only differ in parallelism (and advice about *where* to run).
    updates: dict[str, Any] = {
        "reuse_lines_xml": True,
        "lineation_backend": "kraken",
        "htr_combination": "kraken_htr",
        "llm_mode": "correct",
        "batch_parallel_pages": _batch_parallel_for(p),
    }

    if p.host_class == "bridges_login":
        advice.append(
            "Pipeline unchanged; for GPU speed submit identical settings via "
            "GPU-shared sbatch or run on akdeniz"
        )
    elif p.host_class == "bridges_gpu_compute":
        advice.append("GPU-shared compute: same pipeline, batch_parallel_pages=1 (single GPU)")
    elif p.host_class == "cuda_interactive":
        advice.append(
            f"CUDA host: same pipeline, batch_parallel_pages={updates['batch_parallel_pages']}"
        )
    else:
        advice.append(
            "CPU/Metal host: same pipeline knobs; expect slower HTR than akdeniz/Bridges GPU"
        )

    # Safety: never recommend keys outside the efficiency set
    updates = {k: v for k, v in updates.items() if k in _EFFICIENCY_KEYS}
    return {"updates": updates, "advice": advice}


def apply_machine_efficiency(
    settings: Settings,
    *,
    profile: MachineProfile | None = None,
    force: bool = False,  # kept for CLI compat; no longer drops stages
) -> tuple[Settings, MachineProfile, list[str]]:
    """Apply host knobs only. Never removes HTR/LLM stages."""
    del force  # identical pipeline — no stage-dropping override
    p = profile or detect_machine_profile()
    rec = recommend_settings(p)
    messages = list(p.warnings) + list(rec.get("advice") or [])
    messages.append(
        "auto-efficiency: identical pipeline (lineation→HTR→LLM); "
        f"tuned {sorted((rec.get('updates') or {}).keys())}"
    )
    updates = {k: v for k, v in (rec.get("updates") or {}).items() if k in _EFFICIENCY_KEYS}
    return settings.model_copy(update=updates), p, messages


def stage_routing_advice(profile: MachineProfile | None = None) -> list[dict[str, str]]:
    """Where to *run the same pipeline* for best throughput (settings still apply)."""
    p = profile or detect_machine_profile()
    rows = [
        {
            "stage": "full pipeline (interactive)",
            "preferred": "akdeniz (4090) — same stages, faster HTR",
            "fallback": "halxvi if load low",
        },
        {
            "stage": "full pipeline (batch / train host)",
            "preferred": "bridges_gpu GPU-shared v100-32 sbatch",
            "fallback": "akdeniz",
        },
        {
            "stage": "full pipeline (orchestrate + API LLM)",
            "preferred": "local Mac with --auto-efficiency",
            "fallback": "any host + Gemini",
        },
        {
            "stage": "bridges_login",
            "preferred": "submit the same job to GPU-shared (do not change stages)",
            "fallback": "akdeniz interactive",
        },
    ]
    for r in rows:
        r["current_host"] = p.alias
        r["current_class"] = p.host_class
    return rows


def load_fleet_yaml(path: Path | None = None) -> dict[str, Any]:
    import yaml

    if path is not None:
        candidates = [path]
    else:
        here = Path(__file__).resolve()
        candidates = [
            here.parents[3] / "scripts/latin_ms/machine_fleet.yaml",
            Path.cwd() / "scripts/latin_ms/machine_fleet.yaml",
        ]
    for p in candidates:
        if p.is_file():
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {}
