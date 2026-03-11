"""Hardware detection for mesh workers."""

from __future__ import annotations

import platform
import subprocess
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class GPUInfo:
    """Information about a GPU."""

    name: str = ""
    vram_mb: int = 0
    driver: str = ""
    cuda_version: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "vram_mb": self.vram_mb,
            "driver": self.driver,
            "cuda_version": self.cuda_version,
        }


@dataclass
class HardwareInfo:
    """Hardware information for a node."""

    hostname: str = ""
    os: str = ""
    cpu_cores: int = 0
    ram_total_gb: float = 0.0
    ram_available_gb: float = 0.0
    gpus: list[GPUInfo] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "hostname": self.hostname,
            "os": self.os,
            "cpu_cores": self.cpu_cores,
            "ram_total_gb": round(self.ram_total_gb, 1),
            "ram_available_gb": round(self.ram_available_gb, 1),
            "gpus": [g.to_dict() for g in self.gpus],
        }

    @classmethod
    def from_dict(cls, data: dict) -> HardwareInfo:
        gpus = [GPUInfo(**g) for g in data.get("gpus", [])]
        return cls(
            hostname=data.get("hostname", ""),
            os=data.get("os", ""),
            cpu_cores=data.get("cpu_cores", 0),
            ram_total_gb=data.get("ram_total_gb", 0.0),
            ram_available_gb=data.get("ram_available_gb", 0.0),
            gpus=gpus,
        )

    @property
    def max_vram_mb(self) -> int:
        return max((g.vram_mb for g in self.gpus), default=0)


def detect_hardware() -> HardwareInfo:
    """Detect local hardware capabilities."""
    info = HardwareInfo(
        hostname=platform.node(),
        os=f"{platform.system()} {platform.release()}",
        cpu_cores=_get_cpu_cores(),
    )

    # RAM via psutil
    try:
        import psutil

        mem = psutil.virtual_memory()
        info.ram_total_gb = mem.total / (1024**3)
        info.ram_available_gb = mem.available / (1024**3)
    except ImportError:
        logger.warning("psutil not available, RAM detection skipped")

    # GPU via nvidia-smi
    info.gpus = _detect_gpus()

    return info


def _get_cpu_cores() -> int:
    try:
        import os

        return os.cpu_count() or 1
    except Exception:
        return 1


def _detect_gpus() -> list[GPUInfo]:
    """Detect NVIDIA GPUs via nvidia-smi."""
    gpus = []
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    gpus.append(
                        GPUInfo(
                            name=parts[0],
                            vram_mb=int(float(parts[1])),
                            driver=parts[2],
                            cuda_version=_get_cuda_version(),
                        )
                    )
    except FileNotFoundError:
        pass  # No nvidia-smi
    except Exception as e:
        logger.debug(f"GPU detection failed: {e}")

    return gpus


def _get_cuda_version() -> str:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=cuda_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip().split("\n")[0].strip()
    except Exception:
        pass
    return ""
