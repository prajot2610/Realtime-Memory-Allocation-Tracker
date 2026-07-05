"""
gui_app.py — Real-Time Memory Monitoring GUI

Pick a running process (or type a PID), hit Start, and watch its RSS/VMS
memory usage plotted live with Matplotlib inside a Tkinter window. Every
sample is also appended to a CSV file for later trend analysis, and a
simple leak detector flags sustained one-way memory growth.

Run:
    python3 gui_app.py

Requires a display (X11/Wayland or a virtual framebuffer like Xvfb).
"""
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import psutil
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from memory_monitor import ProcessSampler, CSVLogger, LeakDetector, list_processes

POLL_MS = 300          # how often the GUI checks for new samples
SAMPLE_INTERVAL_S = 0.5  # how often the background thread samples the target process
HISTORY_POINTS = 200     # how many points to keep on the live chart


class MemoryMonitorApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=8)
        self.master = master
        master.title("Real-Time Memory Monitor")
        master.geometry("980x640")

        self.pack(fill=tk.BOTH, expand=True)

        self._sample_queue: "queue.Queue" = queue.Queue()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._sampler: ProcessSampler | None = None
        self._csv_logger: CSVLogger | None = None
        self._leak_detector: LeakDetector | None = None

        self._t0 = None
        self._times = []
        self._rss_mb = []
        self._vms_mb = []
        self._peak_rss_mb = 0.0
        self._sample_count = 0

        self._build_controls()
        self._build_chart()
        self._build_status_bar()

        self._refresh_process_list()
        self._poll_queue()  # start the recurring GUI-thread poll loop

    # ---------------------------------------------------------------- UI --

    def _build_controls(self):
        row = ttk.Frame(self)
        row.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(row, text="Process:").pack(side=tk.LEFT)
        self.process_var = tk.StringVar()
        self.process_combo = ttk.Combobox(row, textvariable=self.process_var,
                                           width=42, state="readonly")
        self.process_combo.pack(side=tk.LEFT, padx=(4, 4))

        ttk.Button(row, text="Refresh list", command=self._refresh_process_list).pack(side=tk.LEFT)

        ttk.Label(row, text="  or PID:").pack(side=tk.LEFT, padx=(10, 2))
        self.pid_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.pid_var, width=8).pack(side=tk.LEFT)

        ttk.Label(row, text="  CSV log:").pack(side=tk.LEFT, padx=(10, 2))
        self.csv_var = tk.StringVar(value="memory_log.csv")
        ttk.Entry(row, textvariable=self.csv_var, width=22).pack(side=tk.LEFT)

        self.start_btn = ttk.Button(row, text="Start", command=self.start_monitoring)
        self.start_btn.pack(side=tk.LEFT, padx=(12, 2))
        self.stop_btn = ttk.Button(row, text="Stop", command=self.stop_monitoring, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT)

    def _build_chart(self):
        self.fig = Figure(figsize=(9, 4.6), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("Elapsed time (s)")
        self.ax.set_ylabel("Memory (MB)")
        self.ax.set_title("Live memory usage")
        (self.rss_line,) = self.ax.plot([], [], label="RSS (physical)", color="#1f77b4")
        (self.vms_line,) = self.ax.plot([], [], label="VMS (virtual)", color="#ff7f0e", alpha=0.6)
        self.ax.legend(loc="upper left")
        self.ax.grid(True, alpha=0.3)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _build_status_bar(self):
        bar = ttk.Frame(self)
        bar.pack(fill=tk.X, pady=(6, 0))

        self.status_labels = {}
        fields = ["Current RSS", "Peak RSS", "CPU %", "Threads", "Samples logged", "Status"]
        for f in fields:
            cell = ttk.Frame(bar, relief=tk.GROOVE, borderwidth=1)
            cell.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
            ttk.Label(cell, text=f, font=("TkDefaultFont", 8)).pack(anchor="w", padx=4)
            var = tk.StringVar(value="-")
            lbl = ttk.Label(cell, textvariable=var, font=("TkDefaultFont", 11, "bold"))
            lbl.pack(anchor="w", padx=4, pady=(0, 4))
            self.status_labels[f] = (var, lbl)

    # ---------------------------------------------------------- controls --

    def _refresh_process_list(self):
        procs = list_processes()
        self._proc_lookup = {f"{name} ({pid})": pid for pid, name in procs}
        self.process_combo["values"] = list(self._proc_lookup.keys())

    def _resolve_target_pid(self):
        pid_text = self.pid_var.get().strip()
        if pid_text:
            try:
                return int(pid_text)
            except ValueError:
                messagebox.showerror("Invalid PID", f"'{pid_text}' is not a valid PID.")
                return None
        sel = self.process_var.get()
        if sel in getattr(self, "_proc_lookup", {}):
            return self._proc_lookup[sel]
        messagebox.showerror("No process selected",
                              "Pick a process from the list or type a PID.")
        return None

    def start_monitoring(self):
        pid = self._resolve_target_pid()
        if pid is None:
            return
        try:
            self._sampler = ProcessSampler(pid)
        except psutil.NoSuchProcess:
            messagebox.showerror("Process not found", f"No such process: PID {pid}")
            return
        except psutil.AccessDenied:
            messagebox.showerror("Access denied", f"Cannot access PID {pid} (permissions).")
            return

        try:
            self._csv_logger = CSVLogger(self.csv_var.get().strip() or "memory_log.csv")
        except OSError as e:
            messagebox.showerror("CSV error", str(e))
            return

        self._leak_detector = LeakDetector()
        self._times.clear()
        self._rss_mb.clear()
        self._vms_mb.clear()
        self._peak_rss_mb = 0.0
        self._sample_count = 0
        self._t0 = time.time()

        self._stop_event.clear()
        self._worker = threading.Thread(target=self._sampling_loop, daemon=True)
        self._worker.start()

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self._set_status("Status", "MONITORING", ok=True)

    def stop_monitoring(self):
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=2)
        if self._csv_logger:
            self._csv_logger.close()
            self._csv_logger = None
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self._set_status("Status", "STOPPED", ok=True)

    # ------------------------------------------------------- worker thread --

    def _sampling_loop(self):
        """Runs in a background thread. Never touches Tkinter widgets
        directly — only pushes results onto a thread-safe queue that the
        GUI thread drains via _poll_queue()."""
        while not self._stop_event.is_set():
            try:
                s = self._sampler.sample()
                self._csv_logger.log(s)
                self._sample_queue.put(("sample", s))
            except psutil.NoSuchProcess:
                self._sample_queue.put(("exited", None))
                return
            except Exception as e:  # keep the thread alive and surface the error
                self._sample_queue.put(("error", str(e)))
            time.sleep(SAMPLE_INTERVAL_S)

    # ---------------------------------------------------------- GUI thread --

    def _poll_queue(self):
        updated = False
        try:
            while True:
                kind, payload = self._sample_queue.get_nowait()
                if kind == "sample":
                    self._handle_sample(payload)
                    updated = True
                elif kind == "exited":
                    self.stop_monitoring()
                    messagebox.showinfo("Process exited", "The monitored process has ended.")
                elif kind == "error":
                    self._set_status("Status", "ERROR", ok=False)
        except queue.Empty:
            pass

        if updated:
            self._redraw_chart()

        self.master.after(POLL_MS, self._poll_queue)

    def _handle_sample(self, s):
        elapsed = s.timestamp - self._t0
        rss_mb = s.rss_bytes / (1024 * 1024)
        vms_mb = s.vms_bytes / (1024 * 1024)

        self._times.append(elapsed)
        self._rss_mb.append(rss_mb)
        self._vms_mb.append(vms_mb)
        self._times = self._times[-HISTORY_POINTS:]
        self._rss_mb = self._rss_mb[-HISTORY_POINTS:]
        self._vms_mb = self._vms_mb[-HISTORY_POINTS:]

        self._peak_rss_mb = max(self._peak_rss_mb, rss_mb)
        self._sample_count += 1

        leak = self._leak_detector.update(s.rss_bytes)

        self._set_status("Current RSS", f"{rss_mb:.1f} MB")
        self._set_status("Peak RSS", f"{self._peak_rss_mb:.1f} MB")
        self._set_status("CPU %", f"{s.cpu_percent:.1f}")
        self._set_status("Threads", str(s.num_threads))
        self._set_status("Samples logged", str(self._sample_count))
        if leak:
            self._set_status("Status", "LEAK SUSPECTED", ok=False)
        elif self._worker and self._worker.is_alive():
            self._set_status("Status", "MONITORING", ok=True)

    def _set_status(self, field, text, ok=None):
        var, lbl = self.status_labels[field]
        var.set(text)
        if ok is True:
            lbl.configure(foreground="#1a7f37")
        elif ok is False:
            lbl.configure(foreground="#c0392b")
        else:
            lbl.configure(foreground="")

    def _redraw_chart(self):
        self.rss_line.set_data(self._times, self._rss_mb)
        self.vms_line.set_data(self._times, self._vms_mb)
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw_idle()


def main():
    import sys

    root = tk.Tk()
    app = MemoryMonitorApp(root)

    def on_close():
        app.stop_monitoring()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    # Optional: `python3 gui_app.py <pid> [csv_path]` pre-fills the PID
    # field and starts monitoring automatically once the window is up.
    # Handy for quickly attaching to a process you already have running,
    # and for scripted/automated testing.
    if len(sys.argv) > 1:
        app.pid_var.set(sys.argv[1])
        if len(sys.argv) > 2:
            app.csv_var.set(sys.argv[2])
        root.after(300, app.start_monitoring)

    root.mainloop()


if __name__ == "__main__":
    main()
