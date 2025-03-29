import sys
import time
import psutil
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, 
                            QLabel, QTabWidget, QHBoxLayout, QScrollArea, QGroupBox,
                            QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, 
                            QMessageBox, QComboBox, QSpinBox)
from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime
import logging
from collections import deque
import platform
import os
import gc
import numpy as np
from PyQt5.QtGui import QIcon, QColor

# Configure logging
logging.basicConfig(
    filename='memory_tracker.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class MemoryTracker(QThread):
    update_signal = pyqtSignal(dict)
    leak_alert = pyqtSignal(str)
    
    def __init__(self, max_history=1000):
        super().__init__()
        self.max_history = max_history
        self.memory_history = deque(maxlen=max_history)
        self.process_memory_history = deque(maxlen=max_history)
        self.timestamps = deque(maxlen=max_history)
        self.leak_threshold = 10  # MB increase considered as potential leak
        self.leak_detected = False
        self.start_time = time.time()
        self.system_info = self.get_system_info()
        self.running = True
        self.tracked_processes = {}
        self.process_history = {}
        
    def get_system_info(self):
        """Collect system information"""
        return {
            'system': platform.system(),
            'node': platform.node(),
            'release': platform.release(),
            'version': platform.version(),
            'machine': platform.machine(),
            'processor': platform.processor(),
            'physical_cores': psutil.cpu_count(logical=False),
            'total_cores': psutil.cpu_count(logical=True),
            'total_memory': round(psutil.virtual_memory().total / (1024 ** 3), 2),  # GB
            'swap_memory': round(psutil.swap_memory().total / (1024 ** 3), 2)  # GB
        }
    
    def add_process_to_track(self, pid):
        """Add a process to track by PID"""
        try:
            process = psutil.Process(pid)
            self.tracked_processes[pid] = process
            self.process_history[pid] = deque(maxlen=self.max_history)
            return True, f"Process {pid} added successfully"
        except psutil.NoSuchProcess:
            return False, f"No process found with PID {pid}"
        except Exception as e:
            return False, f"Error adding process: {str(e)}"
    
    def remove_tracked_process(self, pid):
        """Remove a tracked process"""
        if pid in self.tracked_processes:
            del self.tracked_processes[pid]
            del self.process_history[pid]
            return True, f"Process {pid} removed successfully"
        return False, f"Process {pid} not being tracked"
    
    def run(self):
        """Main tracking loop"""
        while self.running:
            try:
                timestamp = datetime.now()
                virtual_mem = psutil.virtual_memory()
                swap_mem = psutil.swap_memory()
                process = psutil.Process(os.getpid())
                
                # Get memory info in MB
                total_mem = round(virtual_mem.total / (1024 ** 2), 2)
                used_mem = round(virtual_mem.used / (1024 ** 2), 2)
                free_mem = round(virtual_mem.free / (1024 ** 2), 2)
                used_swap = round(swap_mem.used / (1024 ** 2), 2)
                process_mem = round(process.memory_info().rss / (1024 ** 2), 2)
                
                # Store data
                self.timestamps.append(timestamp)
                self.memory_history.append({
                    'total': total_mem,
                    'used': used_mem,
                    'free': free_mem,
                    'swap': used_swap,
                    'percent': virtual_mem.percent
                })
                self.process_memory_history.append(process_mem)
                
                # Update tracked processes
                process_data = {}
                for pid, proc in self.tracked_processes.items():
                    try:
                        mem = round(proc.memory_info().rss / (1024 ** 2), 2)
                        self.process_history[pid].append(mem)
                        process_data[pid] = mem
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        self.remove_tracked_process(pid)
                
                # Check for memory leaks (improved heuristic)
                if len(self.process_memory_history) > 30:
                    recent = list(self.process_memory_history)[-30:]
                    x = np.arange(len(recent))
                    coeffs = np.polyfit(x, recent, 1)
                    slope = coeffs[0] * 60  # Projected MB increase per minute
                    
                    if slope > self.leak_threshold and not self.leak_detected:
                        self.leak_detected = True
                        alert_msg = f"Potential memory leak detected! Projected increase: {slope:.2f}MB/min"
                        logging.warning(alert_msg)
                        self.leak_alert.emit(alert_msg)
                    elif slope <= self.leak_threshold and self.leak_detected:
                        self.leak_detected = False
                        logging.info("Memory leak condition cleared")
                
                # Prepare data for emission
                current_stats = {
                    'timestamp': timestamp,
                    'total_memory': total_mem,
                    'used_memory': used_mem,
                    'free_memory': free_mem,
                    'used_swap': used_swap,
                    'memory_percent': virtual_mem.percent,
                    'process_memory': process_mem,
                    'leak_detected': self.leak_detected,
                    'process_data': process_data
                }
                
                self.update_signal.emit(current_stats)
                
            except Exception as e:
                logging.error(f"Error in tracking loop: {str(e)}")
            
            time.sleep(1)
    
    def stop(self):
        """Stop the tracking thread"""
        self.running = False
        self.wait()
    
    def get_history_df(self):
        """Return history as pandas DataFrame"""
        if not self.timestamps:
            return pd.DataFrame()
            
        data = {
            'timestamp': list(self.timestamps),
            'total_memory': [x['total'] for x in self.memory_history],
            'used_memory': [x['used'] for x in self.memory_history],
            'free_memory': [x['free'] for x in self.memory_history],
            'used_swap': [x['swap'] for x in self.memory_history],
            'memory_percent': [x['percent'] for x in self.memory_history],
            'process_memory': list(self.process_memory_history)
        }
        
        # Add tracked processes to dataframe
        for pid, history in self.process_history.items():
            data[f'process_{pid}_memory'] = list(history)
        
        return pd.DataFrame(data)
    
    def get_summary_stats(self):
        """Calculate summary statistics"""
        if not self.memory_history:
            return {}
            
        df = self.get_history_df()
        stats = {
            'uptime': round(time.time() - self.start_time, 2),
            'avg_memory_usage': round(df['used_memory'].mean(), 2),
            'max_memory_usage': round(df['used_memory'].max(), 2),
            'avg_process_memory': round(df['process_memory'].mean(), 2),
            'max_process_memory': round(df['process_memory'].max(), 2),
            'leak_detected': self.leak_detected
        }
        
        # Add process-specific stats
        for pid in self.tracked_processes.keys():
            col = f'process_{pid}_memory'
            if col in df.columns:
                stats[f'avg_{col}'] = round(df[col].mean(), 2)
                stats[f'max_{col}'] = round(df[col].max(), 2)
        
        return stats

class MemoryCanvas(FigureCanvas):
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        super().__init__(self.fig)
        self.setParent(parent)
        self.ax1 = self.fig.add_subplot(311)
        self.ax2 = self.fig.add_subplot(312)
        self.ax3 = self.fig.add_subplot(313)
        self.fig.tight_layout(pad=3.0)
        
    def plot_data(self, timestamps, memory_data, process_data, tracked_processes=None):
        """Update the plot with new data"""
        self.ax1.clear()
        self.ax2.clear()
        self.ax3.clear()
        
        # Plot system memory
        self.ax1.plot(timestamps, [m['used'] for m in memory_data], label='Used Memory')
        self.ax1.plot(timestamps, [m['free'] for m in memory_data], label='Free Memory')
        self.ax1.plot(timestamps, [m['swap'] for m in memory_data], label='Used Swap')
        self.ax1.set_title('System Memory Usage (MB)')
        self.ax1.legend()
        self.ax1.grid(True)
        
        # Plot main process memory
        self.ax2.plot(timestamps, process_data, 'r-', label='Main Process Memory')
        self.ax2.set_title('Application Memory Usage (MB)')
        self.ax2.legend()
        self.ax2.grid(True)
        
        # Plot tracked processes if available
        if tracked_processes:
            for pid, data in tracked_processes.items():
                if len(data) == len(timestamps):
                    self.ax3.plot(timestamps, data, label=f'Process {pid}')
            self.ax3.set_title('Tracked Processes Memory Usage (MB)')
            self.ax3.legend()
            self.ax3.grid(True)
        
        # Rotate x-axis labels
        for ax in [self.ax1, self.ax2, self.ax3]:
            for label in ax.get_xticklabels():
                label.set_rotation(45)
                label.set_horizontalalignment('right')
        
        self.draw()

class ProcessTable(QTableWidget):
    def __init__(self):
        super().__init__()
        self.setColumnCount(3)
        self.setHorizontalHeaderLabels(['PID', 'Memory (MB)', 'Actions'])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        
    def update_processes(self, processes, process_data):
        """Update the table with current process information"""
        self.setRowCount(len(processes))
        
        for row, (pid, process) in enumerate(processes.items()):
            # PID column
            pid_item = QTableWidgetItem(str(pid))
            self.setItem(row, 0, pid_item)
            
            # Memory column
            mem = process_data.get(pid, 0)
            mem_item = QTableWidgetItem(f"{mem:.2f}")
            self.setItem(row, 1, mem_item)
            
            # Actions column
            widget = QWidget()
            layout = QHBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            
            remove_btn = QPushButton("Remove")
            remove_btn.clicked.connect(lambda _, p=pid: self.remove_process(p))
            remove_btn.setStyleSheet("background-color: #ff6b6b; color: white;")
            
            details_btn = QPushButton("Details")
            details_btn.clicked.connect(lambda _, p=pid: self.show_process_details(p))
            
            layout.addWidget(remove_btn)
            layout.addWidget(details_btn)
            widget.setLayout(layout)
            
            self.setCellWidget(row, 2, widget)
    
    def remove_process(self, pid):
        """Signal that a process should be removed"""
        self.cellChanged.emit(pid, "remove")
    
    def show_process_details(self, pid):
        """Signal that process details should be shown"""
        self.cellChanged.emit(pid, "details")

class SystemInfoWidget(QWidget):
    def __init__(self, system_info):
        super().__init__()
        self.system_info = system_info
        self.initUI()
        
    def initUI(self):
        layout = QVBoxLayout()
        
        group = QGroupBox("System Information")
        info_layout = QVBoxLayout()
        
        info_layout.addWidget(QLabel(f"System: {self.system_info['system']} {self.system_info['release']}"))
        info_layout.addWidget(QLabel(f"Machine: {self.system_info['machine']}"))
        info_layout.addWidget(QLabel(f"Processor: {self.system_info['processor']}"))
        info_layout.addWidget(QLabel(f"Physical Cores: {self.system_info['physical_cores']}"))
        info_layout.addWidget(QLabel(f"Logical Cores: {self.system_info['total_cores']}"))
        info_layout.addWidget(QLabel(f"Total Memory: {self.system_info['total_memory']} GB"))
        info_layout.addWidget(QLabel(f"Swap Memory: {self.system_info['swap_memory']} GB"))
        
        group.setLayout(info_layout)
        layout.addWidget(group)
        
        # Add memory optimization tips
        tips_group = QGroupBox("Memory Optimization Tips")
        tips_layout = QVBoxLayout()
        
        tips = [
            "Close unused applications to free up memory",
            "Increase swap space if you frequently use swap memory",
            "Use generators instead of lists for large datasets",
            "Delete large variables when no longer needed",
            "Use 'del' statement to remove references to objects",
            "Avoid global variables which stay in memory longer",
            "Use __slots__ in classes to reduce memory usage",
            "Consider using more memory-efficient data structures"
        ]
        
        for tip in tips:
            tips_layout.addWidget(QLabel(f"• {tip}"))
        
        tips_group.setLayout(tips_layout)
        layout.addWidget(tips_group)
        
        self.setLayout(layout)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.tracker = MemoryTracker()
        self.tracker.update_signal.connect(self.update_data)
        self.tracker.leak_alert.connect(self.show_leak_alert)
        self.tracker.start()
        
        self.initUI()
        
        # Start with an initial update
        QTimer.singleShot(100, self.initial_update)
        
    def initial_update(self):
        """Initial update after UI is loaded"""
        self.update_data({
            'timestamp': datetime.now(),
            'total_memory': 0,
            'used_memory': 0,
            'free_memory': 0,
            'used_swap': 0,
            'memory_percent': 0,
            'process_memory': 0,
            'leak_detected': False,
            'process_data': {}
        })
    
    def initUI(self):
        self.setWindowTitle('Enhanced Real-time Memory Allocation Tracker')
        self.setGeometry(100, 100, 1200, 900)
        
        try:
            self.setWindowIcon(QIcon('memory_icon.png'))
        except:
            pass
        
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        
        # Create tab widget
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # Create tabs
        self.create_dashboard_tab()
        self.create_visualization_tab()
        self.create_process_tab()
        self.create_history_tab()
        self.create_system_info_tab()
        self.create_settings_tab()
        
        # Status bar
        self.statusBar().showMessage('Ready')
        
        # Alert label
        self.alert_label = QLabel()
        self.alert_label.setStyleSheet("color: red; font-weight: bold;")
        self.alert_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.alert_label)
        
    def create_dashboard_tab(self):
        """Create the dashboard tab with current memory stats"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Current stats group
        stats_group = QGroupBox("Current Memory Statistics")
        stats_layout = QVBoxLayout()
        
        self.total_mem_label = QLabel("Total Memory: -- MB")
        self.used_mem_label = QLabel("Used Memory: -- MB")
        self.free_mem_label = QLabel("Free Memory: -- MB")
        self.swap_mem_label = QLabel("Used Swap: -- MB")
        self.mem_percent_label = QLabel("Memory Percent: --%")
        self.process_mem_label = QLabel("Process Memory: -- MB")
        self.leak_status_label = QLabel("Memory Leak: Not detected")
        
        stats_layout.addWidget(self.total_mem_label)
        stats_layout.addWidget(self.used_mem_label)
        stats_layout.addWidget(self.free_mem_label)
        stats_layout.addWidget(self.swap_mem_label)
        stats_layout.addWidget(self.mem_percent_label)
        stats_layout.addWidget(self.process_mem_label)
        stats_layout.addWidget(self.leak_status_label)
        
        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)
        
        # Summary stats group
        summary_group = QGroupBox("Summary Statistics")
        summary_layout = QVBoxLayout()
        
        self.uptime_label = QLabel("Uptime: -- seconds")
        self.avg_mem_label = QLabel("Avg Memory Usage: -- MB")
        self.max_mem_label = QLabel("Max Memory Usage: -- MB")
        self.avg_process_label = QLabel("Avg Process Memory: -- MB")
        self.max_process_label = QLabel("Max Process Memory: -- MB")
        
        summary_layout.addWidget(self.uptime_label)
        summary_layout.addWidget(self.avg_mem_label)
        summary_layout.addWidget(self.max_mem_label)
        summary_layout.addWidget(self.avg_process_label)
        summary_layout.addWidget(self.max_process_label)
        
        summary_group.setLayout(summary_layout)
        layout.addWidget(summary_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.gc_button = QPushButton("Run Garbage Collector")
        self.gc_button.clicked.connect(self.run_garbage_collector)
        self.export_button = QPushButton("Export Data")
        self.export_button.clicked.connect(self.export_data)
        self.optimize_button = QPushButton("Memory Tips")
        self.optimize_button.clicked.connect(self.show_memory_tips)
        
        button_layout.addWidget(self.gc_button)
        button_layout.addWidget(self.export_button)
        button_layout.addWidget(self.optimize_button)
        layout.addLayout(button_layout)
        
        self.tabs.addTab(tab, "Dashboard")
    
    def create_visualization_tab(self):
        """Create the visualization tab with memory plots"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Create matplotlib canvas
        self.canvas = MemoryCanvas(tab, width=10, height=10, dpi=100)
        layout.addWidget(self.canvas)
        
        self.tabs.addTab(tab, "Visualization")
    
    def create_process_tab(self):
        """Create the process tracking tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Process tracking controls
        control_group = QGroupBox("Process Tracking")
        control_layout = QHBoxLayout()
        
        self.pid_input = QLineEdit()
        self.pid_input.setPlaceholderText("Enter PID to track")
        self.add_pid_button = QPushButton("Add Process")
        self.add_pid_button.clicked.connect(self.add_process_to_track)
        
        control_layout.addWidget(QLabel("Process PID:"))
        control_layout.addWidget(self.pid_input)
        control_layout.addWidget(self.add_pid_button)
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        # Process table
        self.process_table = ProcessTable()
        self.process_table.cellChanged.connect(self.handle_process_action)
        layout.addWidget(self.process_table)
        
        self.tabs.addTab(tab, "Process Tracking")
    
    def create_history_tab(self):
        """Create the history tab with logged data"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        self.history_label = QLabel("No data collected yet")
        self.history_label.setWordWrap(True)
        scroll_layout.addWidget(self.history_label)
        
        # Add history controls
        history_controls = QHBoxLayout()
        self.history_limit = QSpinBox()
        self.history_limit.setRange(5, 100)
        self.history_limit.setValue(10)
        self.history_limit.setPrefix("Show last ")
        self.history_limit.setSuffix(" entries")
        self.history_limit.valueChanged.connect(self.update_history_log)
        
        history_controls.addWidget(self.history_limit)
        history_controls.addStretch()
        scroll_layout.addLayout(history_controls)
        
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        
        self.tabs.addTab(tab, "History Log")
    
    def create_system_info_tab(self):
        """Create the system information tab"""
        tab = SystemInfoWidget(self.tracker.system_info)
        self.tabs.addTab(tab, "System Info")
    
    def create_settings_tab(self):
        """Create the settings tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Tracking settings
        tracking_group = QGroupBox("Tracking Settings")
        tracking_layout = QVBoxLayout()
        
        self.leak_threshold = QSpinBox()
        self.leak_threshold.setRange(1, 1000)
        self.leak_threshold.setValue(self.tracker.leak_threshold)
        self.leak_threshold.setPrefix("Leak Threshold: ")
        self.leak_threshold.setSuffix(" MB/min")
        self.leak_threshold.valueChanged.connect(self.update_leak_threshold)
        
        tracking_layout.addWidget(self.leak_threshold)
        tracking_group.setLayout(tracking_layout)
        layout.addWidget(tracking_group)
        
        # UI settings
        ui_group = QGroupBox("UI Settings")
        ui_layout = QVBoxLayout()
        
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Light", "Dark", "System"])
        self.theme_combo.currentTextChanged.connect(self.change_theme)
        
        ui_layout.addWidget(QLabel("Theme:"))
        ui_layout.addWidget(self.theme_combo)
        ui_group.setLayout(ui_layout)
        layout.addWidget(ui_group)
        
        layout.addStretch()
        self.tabs.addTab(tab, "Settings")
    
    def update_data(self, current_stats):
        """Update all data and UI elements"""
        try:
            # Update dashboard
            self.total_mem_label.setText(f"Total Memory: {current_stats['total_memory']} MB")
            self.used_mem_label.setText(f"Used Memory: {current_stats['used_memory']} MB")
            self.free_mem_label.setText(f"Free Memory: {current_stats['free_memory']} MB")
            self.swap_mem_label.setText(f"Used Swap: {current_stats['used_swap']} MB")
            self.mem_percent_label.setText(f"Memory Percent: {current_stats['memory_percent']}%")
            self.process_mem_label.setText(f"Process Memory: {current_stats['process_memory']} MB")
            
            if current_stats['leak_detected']:
                self.leak_status_label.setText("Memory Leak: DETECTED!")
                self.leak_status_label.setStyleSheet("color: red; font-weight: bold;")
                self.alert_label.setText("WARNING: Potential memory leak detected!")
            else:
                self.leak_status_label.setText("Memory Leak: Not detected")
                self.leak_status_label.setStyleSheet("")
                self.alert_label.setText("")
            
            # Update summary stats
            summary = self.tracker.get_summary_stats()
            self.uptime_label.setText(f"Uptime: {summary['uptime']} seconds")
            self.avg_mem_label.setText(f"Avg Memory Usage: {summary['avg_memory_usage']} MB")
            self.max_mem_label.setText(f"Max Memory Usage: {summary['max_memory_usage']} MB")
            self.avg_process_label.setText(f"Avg Process Memory: {summary['avg_process_memory']} MB")
            self.max_process_label.setText(f"Max Process Memory: {summary['max_process_memory']} MB")
            
            # Update visualization
            if len(self.tracker.timestamps) > 0:
                self.canvas.plot_data(
                    self.tracker.timestamps,
                    self.tracker.memory_history,
                    self.tracker.process_memory_history,
                    self.tracker.process_history
                )
            
            # Update process table
            self.process_table.update_processes(self.tracker.tracked_processes, current_stats['process_data'])
            
            # Update history log
            self.update_history_log()
            
            # Status bar update
            self.statusBar().showMessage(f"Last updated: {current_stats['timestamp'].strftime('%H:%M:%S')}")
            
        except Exception as e:
            logging.error(f"Error updating data: {str(e)}")
            self.statusBar().showMessage(f"Error: {str(e)}")
    
    def update_history_log(self):
        """Update the history log tab"""
        try:
            df = self.tracker.get_history_df()
            if not df.empty:
                limit = self.history_limit.value()
                last_entries = df.tail(limit).to_string(index=False)
                self.history_label.setText(f"Last {limit} entries:\n{last_entries}")
        except Exception as e:
            logging.error(f"Error updating history log: {str(e)}")
    
    def add_process_to_track(self):
        """Add a process to track by PID"""
        pid_text = self.pid_input.text()
        if not pid_text.isdigit():
            QMessageBox.warning(self, "Invalid PID", "Please enter a valid numeric PID")
            return
        
        pid = int(pid_text)
        success, message = self.tracker.add_process_to_track(pid)
        
        if success:
            self.statusBar().showMessage(message)
            self.pid_input.clear()
        else:
            QMessageBox.warning(self, "Error", message)
    
    def handle_process_action(self, pid, action):
        """Handle actions from the process table"""
        if action == "remove":
            success, message = self.tracker.remove_tracked_process(pid)
            if success:
                self.statusBar().showMessage(message)
            else:
                QMessageBox.warning(self, "Error", message)
        elif action == "details":
            self.show_process_details(pid)
    
    def show_process_details(self, pid):
        """Show details for a specific process"""
        try:
            process = psutil.Process(pid)
            info = {
                'PID': pid,
                'Name': process.name(),
                'Status': process.status(),
                'CPU %': process.cpu_percent(),
                'Memory %': process.memory_percent(),
                'Threads': process.num_threads(),
                'Create Time': datetime.fromtimestamp(process.create_time()).strftime('%Y-%m-%d %H:%M:%S')
            }
            
            msg = "\n".join(f"{k}: {v}" for k, v in info.items())
            QMessageBox.information(self, f"Process {pid} Details", msg)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not get process details: {str(e)}")
    
    def show_leak_alert(self, message):
        """Show a memory leak alert"""
        QMessageBox.warning(self, "Memory Leak Detected", message)
    
    def run_garbage_collector(self):
        """Run Python's garbage collector"""
        try:
            gc.collect()
            self.statusBar().showMessage("Garbage collector run completed")
            logging.info("Manual garbage collection performed")
        except Exception as e:
            logging.error(f"Error running garbage collector: {str(e)}")
            self.statusBar().showMessage(f"Error: {str(e)}")
    
    def export_data(self):
        """Export collected data to CSV"""
        try:
            df = self.tracker.get_history_df()
            if not df.empty:
                filename = f"memory_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                df.to_csv(filename, index=False)
                self.statusBar().showMessage(f"Data exported to {filename}")
                logging.info(f"Data exported to {filename}")
                
                # Open the directory where the file was saved
                if platform.system() == "Windows":
                    os.startfile(os.path.dirname(os.path.abspath(filename)))
                elif platform.system() == "Darwin":
                    os.system(f"open {os.path.dirname(os.path.abspath(filename))}")
                else:
                    os.system(f"xdg-open {os.path.dirname(os.path.abspath(filename))}")
            else:
                self.statusBar().showMessage("No data to export")
        except Exception as e:
            logging.error(f"Error exporting data: {str(e)}")
            self.statusBar().showMessage(f"Error: {str(e)}")
    
    def show_memory_tips(self):
        """Show memory optimization tips"""
        self.tabs.setCurrentIndex(4)  # Switch to System Info tab which contains tips
    
    def update_leak_threshold(self, value):
        """Update the memory leak detection threshold"""
        self.tracker.leak_threshold = value
        logging.info(f"Leak detection threshold updated to {value} MB/min")
    
    def change_theme(self, theme):
        """Change the application theme"""
        # This is a simplified theme changer - in a real app you'd use QSS
        palette = self.palette()
        
        if theme == "Dark":
            palette.setColor(palette.Window, QColor(53, 53, 53))
            palette.setColor(palette.WindowText, Qt.white)
            palette.setColor(palette.Base, QColor(25, 25, 25))
            palette.setColor(palette.AlternateBase, QColor(53, 53, 53))
            palette.setColor(palette.ToolTipBase, Qt.white)
            palette.setColor(palette.ToolTipText, Qt.white)
            palette.setColor(palette.Text, Qt.white)
            palette.setColor(palette.Button, QColor(53, 53, 53))
            palette.setColor(palette.ButtonText, Qt.white)
            palette.setColor(palette.BrightText, Qt.red)
            palette.setColor(palette.Link, QColor(42, 130, 218))
            palette.setColor(palette.Highlight, QColor(42, 130, 218))
            palette.setColor(palette.HighlightedText, Qt.black)
        else:  # Light or System
            palette.setColor(palette.Window, Qt.white)
            palette.setColor(palette.WindowText, Qt.black)
            palette.setColor(palette.Base, Qt.white)
            palette.setColor(palette.AlternateBase, QColor(240, 240, 240))
            palette.setColor(palette.ToolTipBase, Qt.white)
            palette.setColor(palette.ToolTipText, Qt.black)
            palette.setColor(palette.Text, Qt.black)
            palette.setColor(palette.Button, QColor(240, 240, 240))
            palette.setColor(palette.ButtonText, Qt.black)
            palette.setColor(palette.BrightText, Qt.red)
            palette.setColor(palette.Link, QColor(0, 0, 255))
            palette.setColor(palette.Highlight, QColor(0, 120, 215))
            palette.setColor(palette.HighlightedText, Qt.white)
        
        self.setPalette(palette)
        logging.info(f"Theme changed to {theme}")
    
    def closeEvent(self, event):
        """Handle window close event"""
        self.tracker.stop()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # Set style
    app.setStyle('Fusion')
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    # Start the application
    sys.exit(app.exec_())