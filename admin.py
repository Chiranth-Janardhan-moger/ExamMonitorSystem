import socket
import threading
import time
import json
import os
import sys
import datetime
from typing import Dict, Any, Optional

ADMIN_CONFIG_FILE = "admin_config.json"
EXAM_CONFIG_FILE = "exam_config.json"

class ExamAdminServer:
    def __init__(self):
        self.host = "0.0.0.0"
        self.port = 9999
        self.log_level = "INFO"
        self.auto_freeze = True
        self.freeze_duration = 30
        self.freeze_message = "Unauthorized activity detected."
        self.save_logs = True
        self.disconnect_timeout = 30
        self.log_file = "exam_monitor.log"

        # Exam parameters
        self.exam_name = "Proctored Examination"
        self.exam_duration = 60  # minutes
        self.blocked_apps = []
        self.blocked_processes = []
        self.exam_active = False
        self.exam_start_time: Optional[float] = None

        # Connected students registry
        # student_name -> dict(socket=..., addr=..., last_seen=..., violations=..., info=...)
        self.students: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.running = False
        self.server_socket: Optional[socket.socket] = None

        self.load_configs()

    def log(self, message: str):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        print(log_entry)
        if self.save_logs:
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(log_entry + "\n")
            except Exception as e:
                print(f"Failed to write log: {e}")

    def load_configs(self):
        if os.path.exists(ADMIN_CONFIG_FILE):
            try:
                with open(ADMIN_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    self.host = cfg.get("host", self.host)
                    self.port = cfg.get("port", self.port)
                    self.log_level = cfg.get("log_level", self.log_level)
                    self.auto_freeze = cfg.get("auto_freeze", self.auto_freeze)
                    self.freeze_duration = cfg.get("freeze_duration", self.freeze_duration)
                    self.freeze_message = cfg.get("freeze_message", self.freeze_message)
                    self.save_logs = cfg.get("save_logs", self.save_logs)
                    self.disconnect_timeout = cfg.get("disconnect_timeout", self.disconnect_timeout)
            except Exception as e:
                self.log(f"Error reading {ADMIN_CONFIG_FILE}: {e}")

        if os.path.exists(EXAM_CONFIG_FILE):
            try:
                with open(EXAM_CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    self.exam_name = cfg.get("exam_name", self.exam_name)
                    self.exam_duration = cfg.get("exam_duration", self.exam_duration)
                    self.blocked_apps = [a.lower() for a in cfg.get("blocked_apps", [])]
                    self.blocked_processes = [p.lower() for p in cfg.get("blocked_processes", [])]
            except Exception as e:
                self.log(f"Error reading {EXAM_CONFIG_FILE}: {e}")

        self.log(f"Config loaded: {len(self.blocked_apps)} blocked apps, {len(self.blocked_processes)} blocked procs. Port: {self.port}")

    def get_remaining_minutes(self) -> float:
        if not self.exam_active or not self.exam_start_time:
            return 0.0
        elapsed_minutes = (time.time() - self.exam_start_time) / 60.0
        return max(0.0, float(self.exam_duration) - elapsed_minutes)

    def send_to_student(self, student_name: str, payload: dict) -> bool:
        with self.lock:
            student = self.students.get(student_name)
            if not student or not student.get("socket"):
                return False
            sock = student["socket"]

        try:
            data = (json.dumps(payload) + "\n").encode("utf-8")
            sock.sendall(data)
            return True
        except Exception as e:
            self.log(f"Failed to send to {student_name}: {e}")
            return False

    def broadcast(self, payload: dict):
        with self.lock:
            names = list(self.students.keys())
        for name in names:
            self.send_to_student(name, payload)

    def handle_client(self, conn: socket.socket, addr):
        student_name: Optional[str] = None
        buffer = ""

        try:
            conn.settimeout(None)
            while self.running:
                data = conn.recv(4096)
                if not data:
                    break

                buffer += data.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        student_name = self.process_message(msg, conn, addr, student_name)
                    except json.JSONDecodeError:
                        self.log(f"Malformed JSON from {addr}: {line}")
        except Exception as e:
            self.log(f"Connection error with {student_name or addr}: {e}")
        finally:
            conn.close()
            if student_name:
                with self.lock:
                    if student_name in self.students and self.students[student_name].get("socket") == conn:
                        self.students[student_name]["status"] = "disconnected"
                        self.students[student_name]["socket"] = None
                self.log(f"Student disconnected: {student_name} ({addr[0]})")

    def process_message(self, msg: dict, conn: socket.socket, addr, current_name: Optional[str]) -> Optional[str]:
        msg_type = msg.get("type")
        name = msg.get("student") or current_name

        if msg_type == "join":
            name = msg.get("student", f"Student-{addr[0]}")
            with self.lock:
                self.students[name] = {
                    "socket": conn,
                    "ip": addr[0],
                    "port": addr[1],
                    "os": msg.get("os", "Unknown"),
                    "hostname": msg.get("hostname", "Unknown"),
                    "mac": msg.get("mac", "Unknown"),
                    "last_seen": time.time(),
                    "violations": 0,
                    "window": "Unknown",
                    "process": "Unknown",
                    "status": "connected"
                }

            self.log(f"Student registered: {name} from {addr[0]} ({msg.get('os')}, {msg.get('hostname')})")
            
            # Send current exam status to newly joined student
            remaining = self.get_remaining_minutes()
            self.send_to_student(name, {
                "type": "status",
                "active": self.exam_active,
                "remaining_time": remaining,
                "exam_name": self.exam_name,
                "blocked_apps": self.blocked_apps,
                "blocked_processes": self.blocked_processes
            })
            return name

        if not name:
            return None

        with self.lock:
            if name in self.students:
                self.students[name]["last_seen"] = time.time()
                self.students[name]["status"] = "connected"

        if msg_type == "heartbeat":
            window = msg.get("window", "Unknown")
            process = msg.get("process", "Unknown")
            processes = msg.get("processes", [])

            with self.lock:
                if name in self.students:
                    self.students[name]["window"] = window
                    self.students[name]["process"] = process

            if self.exam_active:
                self.check_violations(name, window, processes)

        elif msg_type == "alert":
            alert_type = msg.get("alert_type", "GENERIC")
            details = msg.get("details", "")
            with self.lock:
                if name in self.students:
                    self.students[name]["violations"] += 1

            self.log(f"VIOLATION ALERT: [{alert_type}] {name} - {details}")
            if self.auto_freeze:
                self.send_to_student(name, {
                    "type": "freeze",
                    "reason": f"{alert_type}: {details}",
                    "duration": self.freeze_duration
                })

        elif msg_type == "screenshot":
            filename = msg.get("filename", "unknown")
            self.log(f"Screenshot recorded from {name}: {filename}")

        return name

    def check_violations(self, name: str, window: str, processes: list):
        window_lower = window.lower()
        violations = []

        # Check window title for blocked applications
        for app in self.blocked_apps:
            if app in window_lower:
                violations.append(f"Blocked app detected in active window: '{window}'")
                break

        # Check running processes
        for proc in processes:
            proc_lower = str(proc).lower()
            for blocked in self.blocked_apps + self.blocked_processes:
                if blocked in proc_lower:
                    violations.append(f"Blocked process running: '{proc}'")
                    break

        if violations:
            with self.lock:
                if name in self.students:
                    self.students[name]["violations"] += len(violations)

            for v in violations:
                self.log(f"VIOLATION: {name} - {v}")

            if self.auto_freeze:
                reason = violations[0]
                self.send_to_student(name, {
                    "type": "freeze",
                    "reason": reason,
                    "duration": self.freeze_duration
                })

    def connection_monitor_loop(self):
        while self.running:
            now = time.time()
            with self.lock:
                for name, data in self.students.items():
                    if data["status"] == "connected" and (now - data["last_seen"]) > self.disconnect_timeout:
                        data["status"] = "disconnected"
                        self.log(f"Student {name} missed heartbeats. Marked as disconnected.")
            
            # Check exam expiration
            if self.exam_active and self.exam_start_time:
                remaining = self.get_remaining_minutes()
                if remaining <= 0:
                    self.log(f"Exam duration expired. Concluding exam '{self.exam_name}'.")
                    self.stop_exam()

            time.sleep(5)

    def start_exam(self, duration: Optional[int] = None):
        if duration:
            self.exam_duration = duration
        self.exam_active = True
        self.exam_start_time = time.time()
        self.log(f"Exam '{self.exam_name}' STARTED. Duration: {self.exam_duration} minutes.")
        self.broadcast({
            "type": "status",
            "active": True,
            "remaining_time": float(self.exam_duration),
            "exam_name": self.exam_name,
            "blocked_apps": self.blocked_apps,
            "blocked_processes": self.blocked_processes
        })

    def stop_exam(self):
        self.exam_active = False
        self.exam_start_time = None
        self.log(f"Exam '{self.exam_name}' STOPPED.")
        self.broadcast({
            "type": "status",
            "active": False,
            "remaining_time": 0.0,
            "exam_name": self.exam_name,
            "blocked_apps": self.blocked_apps,
            "blocked_processes": self.blocked_processes
        })

    def start(self):
        self.running = True
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(100)

        self.log(f"Exam Admin Server running on {self.host}:{self.port}")

        # Start health check thread
        threading.Thread(target=self.connection_monitor_loop, daemon=True).start()

        # Start listener thread
        listener_thread = threading.Thread(target=self.accept_loop, daemon=True)
        listener_thread.start()

        # Run admin CLI
        self.cli_loop()

    def accept_loop(self):
        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                t = threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True)
                t.start()
            except Exception:
                break

    def cli_loop(self):
        print("\nEnter 'help' for proctor commands.")
        while self.running:
            try:
                cmd_line = input("admin> ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not cmd_line:
                continue

            parts = cmd_line.split()
            cmd = parts[0].lower()

            if cmd in ["quit", "exit"]:
                break
            elif cmd == "help":
                print("Available Commands:")
                print("  list                             - List connected students and statuses")
                print("  start [minutes]                  - Start the exam session")
                print("  stop                             - Stop the exam session")
                print("  status                           - View exam status and remaining time")
                print("  freeze <student> [duration]      - Lock student's screen")
                print("  unfreeze <student>               - Unlock student's screen")
                print("  warn <student> <message>         - Send a warning pop-up")
                print("  screenshot <student>             - Request screenshot from student")
                print("  reload                           - Reload config files")
                print("  exit / quit                      - Stop server and quit")
            elif cmd == "list":
                with self.lock:
                    if not self.students:
                        print("No students registered.")
                    else:
                        print(f"{'STUDENT':<16} {'IP':<16} {'STATUS':<14} {'VIOLATIONS':<12} {'ACTIVE WINDOW'}")
                        print("-" * 75)
                        for name, data in self.students.items():
                            print(f"{name:<16} {data['ip']:<16} {data['status']:<14} {data['violations']:<12} {data['window'][:30]}")
            elif cmd == "start":
                dur = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else self.exam_duration
                self.start_exam(dur)
            elif cmd == "stop":
                self.stop_exam()
            elif cmd == "status":
                if self.exam_active:
                    print(f"Exam '{self.exam_name}' is ACTIVE. Remaining time: {self.get_remaining_minutes():.1f} min.")
                else:
                    print(f"Exam '{self.exam_name}' is INACTIVE.")
            elif cmd == "freeze":
                if len(parts) < 2:
                    print("Usage: freeze <student_name> [duration]")
                    continue
                target = parts[1]
                dur = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else self.freeze_duration
                if self.send_to_student(target, {"type": "freeze", "reason": "Proctor initiated lock", "duration": dur}):
                    print(f"Freeze command delivered to {target}.")
                else:
                    print(f"Failed to deliver freeze command to {target}.")
            elif cmd == "unfreeze":
                if len(parts) < 2:
                    print("Usage: unfreeze <student_name>")
                    continue
                target = parts[1]
                if self.send_to_student(target, {"type": "unfreeze"}):
                    print(f"Unfreeze command delivered to {target}.")
                else:
                    print(f"Failed to deliver unfreeze command to {target}.")
            elif cmd == "warn":
                if len(parts) < 3:
                    print("Usage: warn <student_name> <message>")
                    continue
                target = parts[1]
                msg = " ".join(parts[2:])
                if self.send_to_student(target, {"type": "warning", "message": msg}):
                    print(f"Warning delivered to {target}.")
                else:
                    print(f"Failed to deliver warning to {target}.")
            elif cmd == "screenshot":
                if len(parts) < 2:
                    print("Usage: screenshot <student_name>")
                    continue
                target = parts[1]
                if self.send_to_student(target, {"type": "screenshot"}):
                    print(f"Screenshot request delivered to {target}.")
                else:
                    print(f"Failed to deliver screenshot request to {target}.")
            elif cmd == "reload":
                self.load_configs()
                print("Configuration files reloaded.")
            else:
                print(f"Unknown command '{cmd}'. Type 'help' for options.")

        self.stop()

    def stop(self):
        self.log("Shutting down admin server...")
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
        sys.exit(0)

if __name__ == "__main__":
    server = ExamAdminServer()
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()