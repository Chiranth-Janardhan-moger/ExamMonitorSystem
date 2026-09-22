import socket
import time
import json
import subprocess
import sys
import unittest

class TestExamMonitorIntegration(unittest.TestCase):
    def setUp(self):
        self.admin_proc = subprocess.Popen(
            [sys.executable, "admin.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        time.sleep(1.5)

    def tearDown(self):
        try:
            self.admin_proc.stdin.write("quit\n")
            self.admin_proc.stdin.flush()
        except Exception:
            pass
        try:
            self.admin_proc.terminate()
            self.admin_proc.wait(timeout=2)
        except Exception:
            self.admin_proc.kill()

    def test_handshake_and_commands(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", 9999))
        sock.settimeout(3.0)

        # 1. Send Join message
        join_msg = {
            "type": "join",
            "student": "Candidate01",
            "hostname": "lab-pc-01",
            "os": "Windows 11",
            "mac": "AA:BB:CC:DD:EE:FF"
        }
        sock.sendall((json.dumps(join_msg) + "\n").encode("utf-8"))

        # Read initial status
        data = sock.recv(1024).decode("utf-8")
        status = json.loads(data.strip())
        self.assertEqual(status.get("type"), "status")

        # 2. Send Heartbeat
        hb_msg = {
            "type": "heartbeat",
            "student": "Candidate01",
            "window": "IDE - Exam",
            "process": "code.exe",
            "processes": ["code.exe", "explorer.exe"]
        }
        sock.sendall((json.dumps(hb_msg) + "\n").encode("utf-8"))

        # 3. Issue Warning command via admin CLI
        self.admin_proc.stdin.write("warn Candidate01 Window focus violation\n")
        self.admin_proc.stdin.flush()
        time.sleep(0.5)

        cmd_data = sock.recv(1024).decode("utf-8")
        cmd = json.loads(cmd_data.strip())
        self.assertEqual(cmd.get("type"), "warning")
        self.assertIn("Window focus violation", cmd.get("message", ""))

        sock.close()

if __name__ == "__main__":
    unittest.main()
