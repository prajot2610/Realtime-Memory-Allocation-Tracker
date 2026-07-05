# Real-Time Memory Monitoring GUI

A desktop GUI that watches a chosen process's memory usage live, plots it
with Matplotlib, logs every sample to CSV for later trend analysis, and
flags sustained memory growth as a suspected leak.

**Tech:** Python · Tkinter (GUI) · Matplotlib (live charts) · psutil (process metrics) · CSV (historical logging)

## What it does

- **Pick any running process** from a dropdown (or type a PID) and monitor
  its RSS (physical memory) and VMS (virtual memory) in real time.
- **Live chart**, updating twice a second, embedded directly in the window.
- **CSV logging** of every sample (timestamp, PID, name, RSS, VMS, CPU%,
  thread count) so you can analyze usage trends afterward in Excel,
  pandas, etc.
- **Leak detection**: a sliding-window rule flags "LEAK SUSPECTED" when
  memory has grown by more than a threshold with no meaningful drops over
  the last N samples — the signature of a classic unbounded-growth leak.

## Files

| File               | Purpose                                                          |
|--------------------|--------------------------------------------------------------------|
| `memory_monitor.py`| Core logic — process sampling, CSV logging, leak detection. No GUI dependency, so it's independently testable. |
| `gui_app.py`       | The Tkinter + Matplotlib GUI application (the actual monitor).   |
| `demo_leaky.py`    | A process that deliberately leaks memory — use it to see the leak detector trigger. |
| `demo_stable.py`   | A process with steady, bounded memory churn — confirms the detector stays quiet on normal usage. |
| `requirements.txt` | Python dependencies.                                             |

## Setup

```bash
pip install -r requirements.txt
# Tkinter ships with most Python installs; on minimal Linux images:
#   sudo apt-get install python3-tk
```

## Run it

**Terminal 1 — start something to watch (or skip this and monitor any app you already have running):**
```bash
python3 demo_leaky.py
# demo_leaky: running, pid=12345
```

**Terminal 2 — launch the monitor:**
```bash
python3 gui_app.py
```
Then either:
- pick the process from the **Process** dropdown (click "Refresh list" if it just started), or
- type its PID directly into the **PID** box,

set a CSV path if you want something other than the default `memory_log.csv`,
and click **Start**.

**Shortcut:** you can also launch pre-attached to a PID from the command line:
```bash
python3 gui_app.py 12345 my_log.csv
```

## How the leak detector works

`LeakDetector` (in `memory_monitor.py`) keeps the last 20 RSS readings.
It flags a suspected leak when, over that window:
1. memory never drops by more than a small noise-tolerance amount between
   consecutive samples (i.e. it's essentially one-way), **and**
2. the net growth across the window exceeds a threshold (default 5 MB).

This is deliberately simple and explainable rather than statistical —
it's tuned to catch "memory that only ever goes up," which is the
hallmark of an unbounded-growth leak, while tolerating the small dips
that normal allocators and garbage collectors produce. Tune `window`,
`min_growth_bytes`, and `noise_tolerance_bytes` in `LeakDetector(...)` in
`gui_app.py` to fit your target application's normal behavior.

## Verifying it without the GUI

`memory_monitor.py` has no Tkinter/Matplotlib dependency, so its logic
(process sampling, CSV writing, leak flagging) can be exercised directly
in a script or test file — useful for CI or headless environments:

```python
from memory_monitor import ProcessSampler, CSVLogger, LeakDetector
import os

sampler = ProcessSampler(os.getpid())
print(sampler.sample())
```

## Notes and limitations

- Monitoring another user's process may require elevated permissions
  (psutil will raise `AccessDenied`, which the GUI reports).
- The leak heuristic is a heuristic: a process that legitimately builds up
  a large cache will also trigger it. Cross-check flagged processes
  against what they're actually supposed to be doing.
- CSV logging appends indefinitely while monitoring is active — rotate or
  clear the log file between long-running sessions if disk space matters.
