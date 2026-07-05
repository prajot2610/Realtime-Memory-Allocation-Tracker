"""
demo_leaky.py — a process that deliberately leaks memory, so you have
something to point the monitor at and watch the leak detector trigger.

Run this in one terminal to get its PID:
    python3 demo_leaky.py

Then in gui_app.py, select this process (or type its PID) and hit Start.
Its RSS will climb steadily and, after ~10-20 seconds (20 samples at the
GUI's 0.5s sampling interval), the Status panel should flip to
"LEAK SUSPECTED".
"""
import time
import os

def main():
    print(f"demo_leaky: running, pid={os.getpid()}")
    print("point the monitor at this PID; press Ctrl+C to stop")
    leaked = []
    chunk = bytearray(256 * 1024)  # 256 KB per iteration, never released
    i = 0
    try:
        while True:
            leaked.append(bytearray(chunk))  # copy, so it's real distinct memory
            i += 1
            if i % 10 == 0:
                print(f"leaked ~{i * 256} KB so far ({len(leaked)} chunks)")
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\ndemo_leaky: stopped")


if __name__ == "__main__":
    main()
