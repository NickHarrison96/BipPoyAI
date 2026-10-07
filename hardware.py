"""
Hardware detection + recommendation engine.

Single source of truth for "what settings should this machine use?" — consumed
by config.py (TUI), main.py (GUI), and setup.py (installer).
"""

from dataclasses import dataclass, asdict
from typing import Optional

import psutil

import warnings

try:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=FutureWarning)
        import pynvml
    pynvml.nvmlInit()
    _HAS_NVML = True
except Exception:
    pynvml = None
    _HAS_NVML = False

try:
    import ollama
except ImportError:
    ollama = None


@dataclass
class GPUInfo:
    name: str
    total_vram_gb: float
    used_vram_gb: float


@dataclass
class Recommendations:
    context_size: int = 32768
    gpu_layers: int = 1
    cpu_threads: int = 6
    batch_size: int = 512
    temperature: float = 0.2
    engine_mode: str = "litellm_chat"  # "direct" | "litellm_standard" | "litellm_chat"

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class HardwareReport:
    cpu_cores: int
    ram_gb: float
    gpu: Optional[GPUInfo]
    ollama_running: bool
    recommendations: Recommendations


def _detect_gpu() -> Optional[GPUInfo]:
    if not _HAS_NVML:
        return None
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        raw_name = pynvml.nvmlDeviceGetName(handle)
        name = raw_name.decode("utf-8") if isinstance(raw_name, bytes) else raw_name
        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return GPUInfo(
            name=name,
            total_vram_gb=mem.total / (1024 ** 3),
            used_vram_gb=mem.used / (1024 ** 3),
        )
    except Exception:
        return None


def _detect_ollama() -> bool:
    if ollama is None:
        return False
    try:
        ollama.list()
        return True
    except Exception:
        return False


def _recommend(cpu_cores: int, ram_gb: float, gpu: Optional[GPUInfo],
               ollama_running: bool) -> Recommendations:
    r = Recommendations()

    # Dual-GPU systems (NVIDIA + AMD): Use gpu_layers=1 to force single GPU usage.
    # On Windows, Ollama may try to spread layers across both GPUs when gpu_layers=99,
    # which causes VRAM issues since AMD RX 580 has limited VRAM.
    # Set gpu_layers=1 to use only the NVIDIA GPU (device 0).
    if gpu and gpu.total_vram_gb > 0:
        vram = gpu.total_vram_gb
        if vram >= 8:
            # For dual-GPU systems, gpu_layers=1 ensures NVIDIA-only usage.
            # Change to gpu_layers=99 only if you have a single NVIDIA GPU.
            r.gpu_layers = 1
            r.context_size = max(32768, cpu_cores * 1024)
            r.cpu_threads = max(2, cpu_cores - 4)
            r.batch_size = 1024
        elif vram >= 4:
            # For dual-GPU systems, gpu_layers=1 ensures NVIDIA-only usage.
            r.gpu_layers = 1
            r.context_size = max(16384, cpu_cores * 512)
            r.cpu_threads = max(2, cpu_cores - 2)
            r.batch_size = 512
        else:
            r.gpu_layers = 32
            r.context_size = max(8192, cpu_cores * 256)
            r.cpu_threads = max(2, cpu_cores - 1)
            r.batch_size = 256
    else:
        r.gpu_layers = 0
        r.context_size = max(8192, cpu_cores * 512)
        # Allocate 3 cores / 6 threads for inference so the host OS & UI aren't starved
        r.cpu_threads = min(6, max(2, cpu_cores // 2))
        r.batch_size = 256

    # RAM-driven ceiling
    if ram_gb >= 32:
        r.context_size = max(r.context_size, 65536)
    elif ram_gb >= 16:
        r.context_size = max(r.context_size, 32768)
    elif ram_gb >= 8:
        r.context_size = max(r.context_size, 16384)

    if ollama_running:
        r.engine_mode = "litellm_chat"
    elif gpu and gpu.total_vram_gb > 0:
        r.engine_mode = "litellm_standard"
    else:
        r.engine_mode = "direct"

    return r


def detect() -> HardwareReport:
    """Probe CPU/RAM/GPU/Ollama and return a full report + recommendations."""
    logical = psutil.cpu_count(logical=True) or 1
    physical = psutil.cpu_count(logical=False) or logical
    cores = physical if physical and physical >= logical else logical

    ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    gpu = _detect_gpu()
    ollama_running = _detect_ollama()
    recs = _recommend(cores, ram_gb, gpu, ollama_running)

    return HardwareReport(
        cpu_cores=cores,
        ram_gb=ram_gb,
        gpu=gpu,
        ollama_running=ollama_running,
        recommendations=recs,
    )
