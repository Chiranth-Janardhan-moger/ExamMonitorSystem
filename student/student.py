import os
import sys
import time
import json
import socket
import threading
import getpass
import platform
import subprocess
import tempfile
import atexit
import uuid
import datetime
from typing import Optional, Tuple, List
import psutil

IS_WINDOWS = platform.system().lower() == "windows"
IS_LINUX = platform.system().lower() == "linux"
IS_MAC = platform.system().lower() == "darwin"

LOCK_FILE = os.path.join(tempfile.gettempdir(), "exam_monitor.lock")

class StudentMonitorClient:
    def __init__(self):
        self.student_name = getpass.getuser()
        self.admin_host = "127.0.0.1"
        self.admin_port = 9999
        self.heartbeat_interval = 3
        self.reconnect_interval = 5
        self.enable_screenshots = True
        self.log_file = "student_monitor.log"
        self.screenshot_dir = "screenshots"

        self.exam_active = False
        self.exam_name = "None"
        self.exam_remaining_time = 0.0

        self.sock: Optional[socket.socket] = None
        self.sock_lock = threading.Lock()
        self.running = True
        self.freeze_proc: Optional[subprocess.Popen] = None
        self.last_screenshot_time = 0.0

        self.load_config()

    def log(self, message: str):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        print(log_entry)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_entry + "\n")
        except Exception:
            pass

    def load_config(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidate_paths = [
            os.path.join(script_dir, "monitor_config.json"),
            os.path.join(os.getcwd(), "monitor_config.json"),
            os.path.join(os.getcwd(), "student", "monitor_config.json")
        ]

        config_loaded = False
        for path in candidate_paths:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                        self.admin_host = cfg.get("admin_host", self.admin_host)
                        self.admin_port = cfg.get("admin_port", self.admin_port)
                        self.heartbeat_interval = cfg.get("heartbeat_interval", self.heartbeat_interval)
                        self.reconnect_interval = cfg.get("reconnect_interval", self.reconnect_interval)
                        self.enable_screenshots = cfg.get("enable_screenshots", self.enable_screenshots)
                        self.log_file = cfg.get("log_file", self.log_file)
                        self.screenshot_dir = cfg.get("screenshot_dir", self.screenshot_dir)
                    self.log(f"Loaded config from {path}")
                    config_loaded = True
                    break
                except Exception as e:
                    self.log(f"Error reading config {path}: {e}")

        if not config_loaded:
            self.log("Using default student client configuration.")

    def prevent_multiple_instances(self):
        if os.path.exists(LOCK_FILE):
            try:
                with open(LOCK_FILE, "r") as f:
                    old_pid = int(f.read().strip())
                if psutil.pid_exists(old_pid):
                    try:
                        p = psutil.Process(old_pid)
                        if "python" in p.name().lower():
                            print("Another instance is already active. Exiting.")
                            sys.exit(1)
                    except Exception:
                        pass
            except Exception:
                pass

        try:
            with open(LOCK_FILE, "w") as f:
                f.write(str(os.getpid()))
            atexit.register(self.cleanup_lock)
        except Exception as e:
            self.log(f"Failed to create lock file: {e}")

    def cleanup_lock(self):
        try:
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
        except Exception:
            pass

    def get_mac_address(self) -> str:
        try:
            mac = uuid.getnode()
            return ':'.join(("%012X" % mac)[i:i+2] for i in range(0, 12, 2))
        except Exception:
            return "00:00:00:00:00:00"

    def send_json(self, payload: dict) -> bool:
        with self.sock_lock:
            if not self.sock:
                return False
            try:
                data = (json.dumps(payload) + "\n").encode("utf-8")
                self.sock.sendall(data)
                return True
            except Exception as e:
                self.log(f"Socket send failed: {e}")
                self.close_socket()
                return False

    def close_socket(self):
        with self.sock_lock:
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None

    def connect(self) -> bool:
        self.close_socket()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(8.0)
            s.connect((self.admin_host, self.admin_port))
            s.settimeout(None)
            with self.sock_lock:
                self.sock = s

            # Send join registration
            join_payload = {
                "type": "join",
                "student": self.student_name,
                "hostname": socket.gethostname(),
                "os": f"{platform.system()} {platform.release()}",
                "mac": self.get_mac_address()
            }
            self.send_json(join_payload)
            self.log(f"Connected to Exam Admin at {self.admin_host}:{self.admin_port}")
            return True
        except Exception as e:
            self.log(f"Connection to admin failed ({self.admin_host}:{self.admin_port}): {e}")
            self.close_socket()
            return False

    def get_active_window_info(self) -> Tuple[str, str]:
        try:
            if IS_WINDOWS:
                import win32gui
                import win32process
                hwnd = win32gui.GetForegroundWindow()
                title = win32gui.GetWindowText(hwnd) or "Unknown Window"
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    process = psutil.Process(pid).name()
                except Exception:
                    process = "unknown.exe"
                return title, process
            elif IS_LINUX:
                try:
                    active_win = subprocess.check_output(['xprop', '-root', '_NET_ACTIVE_WINDOW'], text=True)
                    win_id = active_win.strip().split()[-1]
                    if win_id == "0x0":
                        return "Desktop", "desktop"
                    win_title = subprocess.check_output(['xprop', '-id', win_id, 'WM_NAME'], text=True)
                    title = win_title.strip().split('"', 1)[-1].rstrip('"')
                    pid_info = subprocess.check_output(['xprop', '-id', win_id, '_NET_WM_PID'], text=True)
                    pid = int(pid_info.strip().split()[-1])
                    process = psutil.Process(pid).name()
                    return title, process
                except Exception:
                    return "Desktop", "desktop"
            elif IS_MAC:
                script = '''
                tell application "System Events"
                    set frontApp to name of first application process whose frontmost is true
                    set frontWindow to ""
                    try
                        tell process frontApp
                            set frontWindow to name of front window
                        end tell
                    end try
                    return {frontApp, frontWindow}
                end tell
                '''
                output = subprocess.check_output(['osascript', '-e', script], text=True)
                parts = output.strip().split(',', 1)
                process = parts[0].strip() if len(parts) > 0 else "unknown"
                title = parts[1].strip() if len(parts) > 1 else "unknown"
                return title, process
        except Exception as e:
            self.log(f"Error resolving active window: {e}")
        return "Unknown", "unknown"

    def get_monitored_processes(self) -> List[str]:
        target_signatures = [
            "chrome", "firefox", "edge", "safari", "opera", "brave", "vivaldi", "tor",
            "discord", "slack", "teams", "telegram", "whatsapp", "anydesk", "teamviewer",
            "cmd", "powershell", "wireshark", "procmon"
        ]
        active_processes = []
        try:
            for proc in psutil.process_iter(['name']):
                try:
                    pname = proc.info['name'].lower()
                    for sig in target_signatures:
                        if sig in pname and pname not in active_processes:
                            active_processes.append(pname)
                            break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            self.log(f"Error listing processes: {e}")
        return active_processes

    def freeze_screen(self, reason: str = "Proctor initiated freeze", duration: int = 30):
        # Terminate any existing freeze process first
        self.unfreeze_screen()

        script_dir = os.path.dirname(os.path.abspath(__file__))
        freeze_script = os.path.join(script_dir, "freeze_screen.py")
        if not os.path.exists(freeze_script):
            freeze_script = "freeze_screen.py"

        self.log(f"Triggering screen lock: '{reason}' for {duration}s")
        try:
            if IS_WINDOWS:
                self.freeze_proc = subprocess.Popen(
                    [sys.executable, freeze_script, reason, str(duration)],
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                self.freeze_proc = subprocess.Popen(
                    [sys.executable, freeze_script, reason, str(duration)]
                )
        except Exception as e:
            self.log(f"Failed to launch freeze screen: {e}")

    def unfreeze_screen(self):
        if self.freeze_proc:
            try:
                self.freeze_proc.terminate()
                self.freeze_proc.wait(timeout=2)
            except Exception:
                try:
                    self.freeze_proc.kill()
                except Exception:
                    pass
            self.freeze_proc = None
            self.log("Screen unlocked.")

    def show_warning(self, message: str):
        self.log(f"Proctor Warning Received: {message}")
        try:
            if IS_WINDOWS:
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, message, "Exam Monitor Warning", 0x30)
            elif IS_LINUX:
                subprocess.Popen(['notify-send', '-u', 'critical', 'Exam Monitor Warning', message])
            elif IS_MAC:
                applescript = f'display dialog "{message}" with title "Exam Monitor Warning" buttons {{"OK"}} default button "OK" with icon caution'
                subprocess.Popen(['osascript', '-e', applescript])
        except Exception as e:
            self.log(f"Failed to render warning dialog: {e}")

    def capture_screenshot(self) -> Optional[str]:
        if not self.enable_screenshots:
            return None

        now = time.time()
        if now - self.last_screenshot_time < 10:  # Rate limit 10 seconds
            return None

        self.last_screenshot_time = now
        try:
            os.makedirs(self.screenshot_dir, exist_ok=True)
            filename = os.path.join(
                self.screenshot_dir,
                f"{self.student_name}_{int(now)}.png"
            )

            if IS_WINDOWS:
                import pyautogui
                img = pyautogui.screenshot()
                img.save(filename)
            elif IS_LINUX:
                subprocess.call(['scrot', filename])
            elif IS_MAC:
                subprocess.call(['screencapture', '-x', filename])
            else:
                return None

            self.log(f"Captured screenshot: {filename}")
            return filename
        except Exception as e:
            self.log(f"Screenshot error: {e}")
            return None

    def listen_server_commands(self):
        buffer = ""
        while self.running:
            with self.sock_lock:
                current_sock = self.sock

            if not current_sock:
                time.sleep(1)
                continue

            try:
                data = current_sock.recv(4096)
                if not data:
                    self.log("Connection closed by server.")
                    self.close_socket()
                    continue

                buffer += data.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        cmd = json.loads(line)
                        self.process_command(cmd)
                    except json.JSONDecodeError:
                        self.log(f"Received invalid command: {line}")
            except Exception as e:
                self.log(f"Command listener encountered error: {e}")
                self.close_socket()

    def process_command(self, cmd: dict):
        cmd_type = cmd.get("type")
        if cmd_type == "status":
            self.exam_active = cmd.get("active", False)
            self.exam_remaining_time = cmd.get("remaining_time", 0.0)
            self.exam_name = cmd.get("exam_name", self.exam_name)
            self.log(f"Exam status updated: active={self.exam_active}, remaining={self.exam_remaining_time:.1f}m")
        elif cmd_type == "freeze":
            reason = cmd.get("reason", "Proctor initiated lock")
            duration = cmd.get("duration", 30)
            self.freeze_screen(reason, duration)
        elif cmd_type == "unfreeze":
            self.unfreeze_screen()
        elif cmd_type == "warning":
            msg = cmd.get("message", "Attention required.")
            self.show_warning(msg)
        elif cmd_type == "screenshot":
            path = self.capture_screenshot()
            if path:
                self.send_json({"type": "screenshot", "student": self.student_name, "filename": path})

    def run(self):
        self.prevent_multiple_instances()
        self.log(f"Student proctor agent starting for user '{self.student_name}'...")

        # Background thread to receive proctor instructions
        threading.Thread(target=self.listen_server_commands, daemon=True).start()

        prev_window = ""
        prev_process = ""

        while self.running:
            # Check connection health
            with self.sock_lock:
                is_connected = self.sock is not None

            if not is_connected:
                self.log("Attempting reconnection to admin server...")
                if not self.connect():
                    time.sleep(self.reconnect_interval)
                    continue

            # Telemetry collection
            window_title, active_process = self.get_active_window_info()
            running_procs = self.get_monitored_processes()

            # Detect browser or prohibited software while exam is active
            if self.exam_active:
                for b in ["chrome", "firefox", "edge", "safari", "opera", "brave", "vivaldi", "tor"]:
                    if b in window_title.lower() or b in active_process.lower():
                        if window_title != prev_window or active_process != prev_process:
                            self.send_json({
                                "type": "alert",
                                "student": self.student_name,
                                "alert_type": "BROWSER",
                                "details": f"Active: {window_title} ({active_process})"
                            })
                            self.capture_screenshot()
                        break

            prev_window = window_title
            prev_process = active_process

            # Transmit periodic heartbeat
            hb = {
                "type": "heartbeat",
                "student": self.student_name,
                "window": window_title,
                "process": active_process,
                "processes": running_procs
            }
            self.send_json(hb)

            time.sleep(self.heartbeat_interval)

if __name__ == "__main__":
    client = StudentMonitorClient()
    try:
        client.run()
    except KeyboardInterrupt:
        client.log("Client terminated by user.")
        client.unfreeze_screen()
        sys.exit(0)