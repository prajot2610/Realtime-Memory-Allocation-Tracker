"""
memory_monitor.py — GUI-independent core for the real-time process memory
monitor. Kept separate from the Tkinter/Matplotlib layer so it can be
imported and unit-tested without a display.

Provides:
    list_processes()        -> list of (pid, name) for all running processes
    ProcessSampler           -> takes one memory/CPU sample of a given PID
    CSVLogger                -> appends samples to a CSV file with a header
    LeakDetector              -> flags sustained upward memory trends
"""
from __future__ import annotations

import csv
import os
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Optional

import psutil


@dataclass
class Sample:
    timestamp: float   # unix epoch seconds
    pid: int
    name: str
    rss_bytes: int      # resident set size — physical memory actually used
    vms_bytes: int      # virtual memory size
    cpu_percent: float
    num_threads: int


def list_processes():
    """Return [(pid, 'name (pid)')] for all currently running processes,
    sorted by name, for populating a process picker in the GUI."""
    procs = []
    for p in psutil.process_iter(attrs=["pid", "name"]):
        try:
            procs.append((p.info["pid"], p.info["name"] or "?"))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda t: (t[1].lower(), t[0]))
    return procs


class ProcessSampler:
    """Wraps a psutil.Process and takes point-in-time samples.

    Raises psutil.NoSuchProcess if the target process has exited — callers
    should catch this to know when to stop monitoring.
    """

    def __init__(self, pid: int):
        self.pid = pid
        self._proc = psutil.Process(pid)
        self._name = self._proc.name()
        # prime cpu_percent(); first call always returns 0.0
        self._proc.cpu_percent(interval=None)

    @property
    def name(self) -> str:
        return self._name

    def sample(self) -> Sample:
        with self._proc.oneshot():
            mem = self._proc.memory_info()
            cpu = self._proc.cpu_percent(interval=None)
            threads = self._proc.num_threads()
        return Sample(
            timestamp=time.time(),
            pid=self.pid,
            name=self._name,
            rss_bytes=mem.rss,
            vms_bytes=mem.vms,
            cpu_percent=cpu,
            num_threads=threads,
        )


class CSVLogger:
    """Appends Sample rows to a CSV file, writing a header once."""

    FIELDS = ["timestamp", "iso_time", "pid", "name", "rss_bytes", "rss_mb",
              "vms_bytes", "vms_mb", "cpu_percent", "num_threads"]

    def __init__(self, path: str):
        self.path = path
        self._new_file = not os.path.exists(path) or os.path.getsize(path) == 0
        self._fh = open(path, "a", newline="")
        self._writer = csv.DictWriter(self._fh, fieldnames=self.FIELDS)
        if self._new_file:
            self._writer.writeheader()
            self._fh.flush()

    def log(self, s: Sample):
        row = {
            "timestamp": s.timestamp,
            "iso_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(s.timestamp)),
            "pid": s.pid,
            "name": s.name,
            "rss_bytes": s.rss_bytes,
            "rss_mb": round(s.rss_bytes / (1024 * 1024), 3),
            "vms_bytes": s.vms_bytes,
            "vms_mb": round(s.vms_bytes / (1024 * 1024), 3),
            "cpu_percent": s.cpu_percent,
            "num_threads": s.num_threads,
        }
        self._writer.writerow(row)
        self._fh.flush()

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass


class LeakDetector:
    """Flags a suspected memory leak using a simple, explainable rule:

    Over a sliding window of the last `window` samples, if RSS never drops
    by more than `noise_tolerance_bytes` between consecutive samples (i.e.
    it's essentially monotonically non-decreasing) AND the net increase
    across the whole window exceeds `min_growth_bytes`, the window is
    flagged as a suspected leak.

    This deliberately favors a transparent, easy-to-reason-about rule over
    a statistical model — it's tuned to catch "memory that only ever goes
    up," which is the hallmark of a classic unbounded-growth leak, while
    tolerating small dips from GC/allocator noise.
    """

    def __init__(self, window: int = 20, min_growth_bytes: int = 5 * 1024 * 1024,
                 noise_tolerance_bytes: int = 64 * 1024):
        self.window = window
        self.min_growth_bytes = min_growth_bytes
        self.noise_tolerance_bytes = noise_tolerance_bytes
        self._rss_history = deque(maxlen=window)

    def update(self, rss_bytes: int) -> bool:
        """Feed one new RSS reading; returns True if a leak is suspected."""
        self._rss_history.append(rss_bytes)
        return self.is_leak_suspected()

    def is_leak_suspected(self) -> bool:
        if len(self._rss_history) < self.window:
            return False
        hist = list(self._rss_history)
        for prev, cur in zip(hist, hist[1:]):
            if cur < prev - self.noise_tolerance_bytes:
                return False  # a real drop happened -> not a one-way leak
        net_growth = hist[-1] - hist[0]
        return net_growth >= self.min_growth_bytes

    def growth_rate_bytes_per_sec(self, elapsed_seconds: float) -> Optional[float]:
        if len(self._rss_history) < 2 or elapsed_seconds <= 0:
            return None
        hist = list(self._rss_history)
        return (hist[-1] - hist[0]) / elapsed_seconds
