🧠 Realtime Memory Allocation Tracker

A Python-based real-time system monitoring tool that tracks process-wise memory usage, logs activity, and exports data for analysis.
This project is designed for Operating System concepts, performance analysis, system monitoring, and practical learning of psutil & Python automation.

📌 Overview

The Realtime Memory Allocation Tracker monitors system processes in real-time and logs:

Memory usage of running processes

Process IDs (PID) and names

Timestamped memory snapshots

Continuous tracking & CSV export

Detailed log file for debugging and review

This tool is ideal for students, developers, and researchers who want to analyze system memory behavior.

✨ Features
✔ Real-Time Memory Tracking

Captures memory usage of all active processes using Python’s psutil.

✔ CSV Data Export

Automatically generates CSV files like:

memory_data_YYYYMMDD_HHMMSS.csv


These files include process name, PID, memory usage, timestamps, and more.

✔ Logging System

Creates a memory_tracker.log file containing event logs, errors, and tracking info.

✔ Lightweight & Fast

Runs continuously with minimal system overhead.

✔ Highly Extensible

You can add:

GUI (Tkinter)

Real-time graphs (matplotlib)

Alerts for high memory usage

Custom intervals for sampling

📁 Project Structure
/Realtime-Memory-Allocation-Tracker
│
├── memory_tracker.py          # Main script that tracks memory usage
├── memory_tracker.log         # Log file for tracking events/errors
├── memory_data_*.csv          # Auto-generated memory snapshots
└── README.md                  # Project documentation

🛠 Technologies Used

Python 3.x

psutil (for system monitoring)

CSV + Logging modules

▶️ How to Run the Tracker
1️⃣ Install psutil
pip install psutil

2️⃣ Run the script
python memory_tracker.py

3️⃣ View output

CSV files → memory_data_yyyymmdd_timestamp.csv

Log file → memory_tracker.log

📊 Sample CSV Output Columns

Timestamp

Process Name

PID

Memory Usage (in MB)

Percentage of RAM

🔮 Future Enhancements (Optional Ideas)

You may add these later:

GUI Dashboard (Tkinter or PyQt)

Live memory usage graph

Monitoring specific PIDs

High-memory alerts

System-wide historical charts

Export to Excel or JSON

🎓 Academic Use

This project is suitable for:

Operating System course labs

Real-time systems study

Python automation projects

Performance monitoring experiments

📫 Contact

Developer: Prajot Nikam
Email: prajotnikam7777@gmail.com
GitHub: https://github.com/prajot2610
