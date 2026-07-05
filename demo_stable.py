"""
demo_stable.py — a process that allocates and frees memory in a steady
churn pattern (peaks and returns to baseline) so you can confirm the leak
detector correctly stays quiet for normal, bounded memory usage.

Run:
    python3 demo_stable.py
"""
import time
import os
import gc


def main():
    print(f"demo_stable: running, pid={os.getpid()}")
    buf = None
    i = 0
    try:
        while True:
            # allocate a temporary buffer, use it, then release it
            buf = bytearray(2 * 1024 * 1024)  # 2 MB
            for j in range(0, len(buf), 4096):
                buf[j] = 1
            buf = None
            gc.collect()
            i += 1
            if i % 10 == 0:
                print(f"churned {i} cycles, memory should stay flat")
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\ndemo_stable: stopped")


if __name__ == "__main__":
    main()
