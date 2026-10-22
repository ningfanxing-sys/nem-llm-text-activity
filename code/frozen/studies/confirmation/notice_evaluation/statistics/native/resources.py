'Limit memory use during notice-data reading and synthetic tests.'
from __future__ import annotations

import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import time


class ResourceRefusal(RuntimeError):
    'Input metadata.'


def free_memory_percent() -> float:

    if sys.platform == "darwin":
        result = subprocess.run(
            ["/usr/bin/memory_pressure", "-Q"], check=True, capture_output=True,
            text=True, timeout=20,
        )
        match = re.search(r"System-wide memory free percentage:\s*(\d+(?:\.\d+)?)%", result.stdout)
        if match is None:
            raise ResourceRefusal("memory_pressure -Q did not return the free-memory percentage")
        return float(match.group(1))
    if sys.platform.startswith("linux"):
        try:
            import psutil
        except ImportError as exc:
            raise ResourceRefusal("Linux resource verification requires psutil") from exc
        memory = psutil.virtual_memory()
        return 100.0 * memory.available / memory.total
    raise ResourceRefusal("No verified free-memory probe for this platform")


def peak_resident_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def scratch_bytes(root: Path) -> int:

    total = 0
    if root.is_symlink() or not root.is_dir():
        raise ResourceRefusal("Scratch must be an existing real directory")
    for directory, subdirectories, files in os.walk(root, followlinks=False):
        for name in subdirectories + files:
            path = Path(directory) / name
            if path.is_symlink():
                raise ResourceRefusal("Scratch cannot contain symlinks")
        for name in files:
            path = Path(directory) / name
            if not path.is_file():
                raise ResourceRefusal("Scratch contains a non-regular file")
            total += path.stat().st_size
    return total


class ResourceGuard:


    def __init__(self, scratch: Path):
        self.scratch = Path(scratch).resolve()
        self.pid = os.getpid()
        self.checkpoints: list[dict] = []

    def checkpoint(self, label: str) -> dict:
        if os.getpid() != self.pid:
            raise ResourceRefusal("Only one numerical/test process is allowed")
        nice = os.getpriority(os.PRIO_PROCESS, 0)
        free = free_memory_percent()
        peak = peak_resident_bytes()
        used = scratch_bytes(self.scratch)
        snapshot = {
            "label": str(label), "monotonic_seconds": time.monotonic(),
            "pid": self.pid, "nice": nice, "memory_free_percent": free,
            "peak_resident_bytes": peak, "scratch_bytes": used,
        }
        self.checkpoints.append(snapshot)
        if nice != 20:
            raise ResourceRefusal(f"Actual process nice must equal 20; got {nice}")
        if free < 25.0:
            raise ResourceRefusal(f"At least 25% memory must be free; got {free}%")
        if peak >= 1_500_000_000:
            raise ResourceRefusal(f"Peak resident memory must remain below 1.5 GB; got {peak}")
        if used >= 1_000_000_000:
            raise ResourceRefusal(f"Scratch must remain below 1 GB; got {used}")
        return snapshot

    def evidence(self) -> dict:
        return {
            "numerical_processes": 1,
            "pid": self.pid,
            "required_nice": 20,
            "minimum_required_memory_free_percent": 25.0,
            "peak_resident_limit_bytes": 1_500_000_000,
            "scratch_limit_bytes": 1_000_000_000,
            "minimum_observed_memory_free_percent": min(
                (row["memory_free_percent"] for row in self.checkpoints), default=None
            ),
            "peak_observed_resident_bytes": max(
                (row["peak_resident_bytes"] for row in self.checkpoints), default=0
            ),
            "maximum_observed_scratch_bytes": max(
                (row["scratch_bytes"] for row in self.checkpoints), default=0
            ),
            "checkpoints": list(self.checkpoints),
        }
