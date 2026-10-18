"""Live CPU/RAM/GPU/VRAM sampling (Windows performance counters + psutil)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import time
from collections import defaultdict

import psutil
from pydantic import BaseModel


class GpuSample(BaseModel):
    name: str
    utilization_pct: float
    dedicated_used_mb: float | None = None
    dedicated_total_mb: float | None = None
    shared_used_mb: float | None = None


class HardwareSample(BaseModel):
    timestamp: float
    cpu_pct: float
    cpu_count: int
    ram_used_mb: float
    ram_total_mb: float
    process_rss_mb: float
    gpus: list[GpuSample]


class _PdhGpuReader:
    """Reads the 'GPU Engine' and 'GPU Adapter Memory' counters, which cover Intel, AMD and NVIDIA."""

    def __init__(self) -> None:
        import win32pdh  # noqa: PLC0415 - Windows only

        self.pdh = win32pdh
        self.query = win32pdh.OpenQuery()
        self.engine = self._add(r"\GPU Engine(*)\Utilization Percentage")
        self.dedicated = self._add(r"\GPU Adapter Memory(*)\Dedicated Usage")
        self.shared = self._add(r"\GPU Adapter Memory(*)\Shared Usage")
        win32pdh.CollectQueryData(self.query)

    def _add(self, path: str):
        try:
            return self.pdh.AddEnglishCounter(self.query, path)
        except Exception:  # noqa: BLE001 - counter set missing on this machine
            return None

    def _values(self, counter) -> dict[str, float]:
        if counter is None:
            return {}
        try:
            return self.pdh.GetFormattedCounterArray(counter, self.pdh.PDH_FMT_DOUBLE)
        except Exception:  # noqa: BLE001 - no instances yet
            return {}

    def read(self) -> dict[str, dict[str, float]]:
        self.pdh.CollectQueryData(self.query)
        per_adapter: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        # Instance names look like "pid_123_luid_0x0_0x1234_phys_0_eng_0_engtype_3D".
        engine_totals: dict[tuple[str, str], float] = defaultdict(float)
        for instance, value in self._values(self.engine).items():
            luid = _luid(instance)
            engtype = instance.rsplit("engtype_", 1)[-1] if "engtype_" in instance else "other"
            engine_totals[(luid, engtype)] += value
        for (luid, _), total in engine_totals.items():
            per_adapter[luid]["util"] = max(per_adapter[luid]["util"], min(total, 100.0))
        for instance, value in self._values(self.dedicated).items():
            per_adapter[_luid(instance)]["dedicated"] += value
        for instance, value in self._values(self.shared).items():
            per_adapter[_luid(instance)]["shared"] += value
        return per_adapter


def _luid(instance: str) -> str:
    if "luid_" not in instance:
        return instance
    parts = instance.split("luid_", 1)[1].split("_")
    return "_".join(parts[:2])


def _nvidia_smi() -> list[GpuSample]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    samples = []
    for line in out.strip().splitlines():
        name, util, used, total = (part.strip() for part in line.split(","))
        samples.append(
            GpuSample(
                name=name,
                utilization_pct=float(util),
                dedicated_used_mb=float(used),
                dedicated_total_mb=float(total),
            )
        )
    return samples


def _adapter_names() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        import win32com.client  # noqa: PLC0415

        wmi = win32com.client.GetObject("winmgmts:")
        return [gpu.Name for gpu in wmi.InstancesOf("Win32_VideoController")]
    except Exception:  # noqa: BLE001 - WMI unavailable
        return []


class HardwareMonitor:
    """Samples in a background thread so API calls return instantly."""

    def __init__(self, interval: float = 1.0) -> None:
        self.interval = interval
        self._latest: HardwareSample | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="hardware-monitor", daemon=True)
        self._proc = psutil.Process()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def latest(self) -> HardwareSample:
        with self._lock:
            if self._latest is not None:
                return self._latest
        return self._sample(None, [])

    def _run(self) -> None:
        if sys.platform == "win32":
            import pythoncom  # noqa: PLC0415 - WMI needs COM initialised per thread

            pythoncom.CoInitialize()
        names = _adapter_names()
        reader = None
        if sys.platform == "win32":
            try:
                reader = _PdhGpuReader()
            except Exception:  # noqa: BLE001 - counters disabled
                reader = None
        psutil.cpu_percent(None)
        while not self._stop.wait(self.interval):
            sample = self._sample(reader, names)
            with self._lock:
                self._latest = sample

    def _sample(self, reader: _PdhGpuReader | None, names: list[str]) -> HardwareSample:
        vm = psutil.virtual_memory()
        gpus = _nvidia_smi()
        if not gpus and reader is not None:
            try:
                adapters = reader.read()
            except Exception:  # noqa: BLE001 - transient PDH errors
                adapters = {}
            # Adapters without engine activity or memory are virtual (e.g. Basic Render).
            real = [
                (luid, v)
                for luid, v in adapters.items()
                if v.get("dedicated", 0) > 2**20 or v.get("shared", 0) > 2**20 or v.get("util", 0) >= 0.5
            ]
            for i, (luid, values) in enumerate(real):
                gpus.append(
                    GpuSample(
                        name=names[i] if i < len(names) else f"GPU {luid}",
                        utilization_pct=round(values.get("util", 0.0), 1),
                        dedicated_used_mb=round(values.get("dedicated", 0.0) / 2**20, 1),
                        shared_used_mb=round(values.get("shared", 0.0) / 2**20, 1),
                    )
                )
        return HardwareSample(
            timestamp=time.time(),
            cpu_pct=psutil.cpu_percent(None),
            cpu_count=psutil.cpu_count() or 1,
            ram_used_mb=round((vm.total - vm.available) / 2**20, 1),
            ram_total_mb=round(vm.total / 2**20, 1),
            process_rss_mb=round(self._proc.memory_info().rss / 2**20, 1),
            gpus=gpus,
        )
