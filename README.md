# ExamMonitorSystem

A cross-platform, client-server exam proctoring and monitoring system engineered for computer-based assessments in academic laboratories and institutional test centers.

ExamMonitorSystem provides real-time visibility into student workstations, detects unauthorized application launches (browsers, unauthorized messaging software, developer tools), enables remote proctor intervention (warning dialogs, screen freezing, on-demand screenshots), and maintains detailed audit logs throughout the examination lifecycle.

---

## Architecture Overview

ExamMonitorSystem utilizes an inverted, single-connection TCP architecture. The student client initiates and maintains a single persistent socket connection to the admin proctor server. All heartbeats, telemetry, violation alerts, and incoming proctor commands are transmitted bi-directionally across this established channel, ensuring reliable operation across NAT gateways, subnets, and local firewalls.

```
+------------------------------------------------------------------+
|                       Admin Proctor Server                       |
|                             admin.py                             |
|          Listens on Port 9999 (Configurable)                     |
|          Maintains Registry of Connected Candidates             |
|          Broadcasts Exam Status & Delivers Proctor Commands      |
+------------------------------------------------------------------+
                                 ^
                                 | Persistent TCP Connection
                                 | Framing: JSON with \n delimiter
                                 v
+------------------------------------------------------------------+
|                      Student Monitor Client                      |
|                        student/student.py                        |
|                                                                  |
|   +---------------------+             +----------------------+   |
|   | Active Window &     |             | Fullscreen Lock      |   |
|   | Process Inspection  |             | freeze_screen.py     |   |
|   +---------------------+             +----------------------+   |
|              |                                    ^              |
|              v                                    |              |
|   +---------------------+             +----------------------+   |
|   | Violation Detection |------------>| Proctor Intervention |   |
|   | & Rate-Limited Grab |             | & UI Enforcement     |   |
|   +---------------------+             +----------------------+   |
+------------------------------------------------------------------+
```

---

## Core Capabilities

- **Active Window Telemetry**: Tracks the foreground application title and parent process name across Windows, Linux, and macOS.
- **Process Whitelist/Blacklist Monitoring**: Periodically scans the student workstation for unauthorized processes (browsers, remote desktop clients, communication software, terminal shells).
- **Proctor-Controlled Screen Freezing**: Deploys a topmost fullscreen overlay (`freeze_screen.py`) that traps keyboard inputs and mouse clicks when a policy breach occurs or upon proctor command.
- **Interactive Proctor CLI**: Command-line administrative console allows examiners to list active examinees, inspect violation counts, trigger on-demand warnings, execute screenshots, and manage exam sessions.
- **Persistent Socket Transport**: Uses newline-delimited JSON payloads over a single TCP socket with automatic reconnect loops and session state tracking.
- **Lightweight Footprint**: Written in pure Python using standard socket primitives and native OS integrations, avoiding heavyweight web runtime overhead.

---

## Project Structure

```
ExamMonitorSystem/
├── admin.py                    # Proctor server and administrative CLI interface
├── admin_config.json           # Server port, timing, and automated policy settings
├── exam_config.json            # Exam duration, metadata, and prohibited application lists
├── requirements.txt            # Python library dependencies
├── .gitignore                  # Git exclusions for logs, locks, and temporary files
├── README.md                   # System documentation
├── student/
│   ├── student.py              # Candidate monitoring daemon
│   ├── freeze_screen.py        # Fullscreen lock overlay with countdown timer
│   └── monitor_config.json     # Client connection and telemetry intervals
└── tests/
    └── test_integration.py     # Automated end-to-end socket protocol integration tests
```

---

## Protocol Specification

All communications are transmitted as newline-delimited UTF-8 JSON objects (`json.dumps(payload) + "\n"`).

### Client to Server Messages

- **Registration (`join`)**:
  ```json
  {
    "type": "join",
    "student": "candidate_username",
    "hostname": "LAB-PC-04",
    "os": "Windows 11",
    "mac": "00:1A:2B:3C:4D:5E"
  }
  ```

- **Telemetry Heartbeat (`heartbeat`)**:
  ```json
  {
    "type": "heartbeat",
    "student": "candidate_username",
    "window": "Exam Portal - Google Chrome",
    "process": "chrome.exe",
    "processes": ["chrome.exe", "explorer.exe"]
  }
  ```

- **Violation Alert (`alert`)**:
  ```json
  {
    "type": "alert",
    "student": "candidate_username",
    "alert_type": "BROWSER",
    "details": "Active: Exam Portal - Google Chrome (chrome.exe)"
  }
  ```

- **Screenshot Notification (`screenshot`)**:
  ```json
  {
    "type": "screenshot",
    "student": "candidate_username",
    "filename": "screenshots/candidate_username_1715421000.png"
  }
  ```

### Server to Client Commands

- **Exam Status (`status`)**:
  ```json
  {
    "type": "status",
    "active": true,
    "remaining_time": 54.2,
    "exam_name": "Operating Systems Midterm"
  }
  ```

- **Screen Freeze (`freeze`)**:
  ```json
  {
    "type": "freeze",
    "reason": "Unauthorized browser detected",
    "duration": 30
  }
  ```

- **Screen Unfreeze (`unfreeze`)**:
  ```json
  {
    "type": "unfreeze"
  }
  ```

- **Warning Dialog (`warning`)**:
  ```json
  {
    "type": "warning",
    "message": "Focus lost on exam window. Return immediately."
  }
  ```

- **On-Demand Screenshot (`screenshot`)**:
  ```json
  {
    "type": "screenshot"
  }
  ```

---

## Installation

### Prerequisites

- Python 3.9 or newer.
- Operating System: Windows, Linux (X11), or macOS.

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/Chiranth-Janardhan-moger/ExamMonitorSystem.git
   cd ExamMonitorSystem
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Linux/macOS:
   source venv/bin/activate
   ```

3. Install required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## Configuration

### `admin_config.json`
Specifies proctor server binding details and automated enforcement rules:
```json
{
    "host": "0.0.0.0",
    "port": 9999,
    "log_level": "INFO",
    "auto_freeze": true,
    "freeze_duration": 30,
    "freeze_message": "Unauthorized activity detected. Screen frozen by administrator.",
    "save_logs": true,
    "disconnect_timeout": 30
}
```

### `exam_config.json`
Specifies exam metadata and restricted software lists:
```json
{
    "exam_name": "Standard Examination",
    "exam_duration": 60,
    "blocked_apps": [
        "chrome",
        "firefox",
        "edge",
        "safari",
        "opera",
        "brave",
        "vivaldi",
        "tor"
    ],
    "blocked_processes": [
        "discord",
        "slack",
        "teams",
        "telegram",
        "whatsapp",
        "anydesk",
        "teamviewer",
        "cmd",
        "powershell",
        "wireshark"
    ]
}
```

### `student/monitor_config.json`
Configures the student daemon's connection endpoint and telemetry cadence:
```json
{
    "admin_host": "127.0.0.1",
    "admin_port": 9999,
    "heartbeat_interval": 3,
    "reconnect_interval": 5,
    "enable_screenshots": true,
    "log_file": "student_monitor.log",
    "screenshot_dir": "screenshots"
}
```

---

## Usage Guide

### 1. Launching the Proctor Server
Run `admin.py` on the examiner workstation:
```bash
python admin.py
```
Upon startup, the admin CLI shell will prompt for input:
```
[2026-09-22 10:00:00] Exam Admin Server running on 0.0.0.0:9999
Enter 'help' for proctor commands.
admin> 
```

### 2. Launching Candidate Workstations
On each student machine, configure `student/monitor_config.json` with the proctor workstation's LAN IP address, then launch the agent:
```bash
python student/student.py
```
The client connects, transmits device metadata, and begins background telemetry reporting.

### 3. Administrative Console Commands

| Command | Arguments | Description |
| :--- | :--- | :--- |
| `list` | None | Displays all registered students, IP addresses, connection statuses, violation counts, and active window titles. |
| `start` | `[minutes]` | Initiates the exam session and broadcasts active status with remaining duration. |
| `stop` | None | Terminates the active exam session and broadcasts conclusion notice. |
| `status` | None | Displays exam state and remaining minutes. |
| `freeze` | `<student> [duration]` | Locks target student's screen with fullscreen countdown. |
| `unfreeze` | `<student>` | Immediately terminates fullscreen lock on target machine. |
| `warn` | `<student> <message>` | Pops up an OS-level warning message box on the candidate's desktop. |
| `screenshot` | `<student>` | Commands target student machine to capture and report a desktop screenshot. |
| `reload` | None | Reloads configuration files without restarting server. |
| `exit` / `quit` | None | Shuts down admin server cleanly. |

---

## Automated Verification

The test suite runs integration checks verifying end-to-end socket handshake, heartbeat ingestion, and command transmission:

```bash
python -m unittest discover tests
```

---

## Ethical and Operational Guidelines

ExamMonitorSystem is designed exclusively for authorized academic evaluations, supervised laboratory tests, and institutional assessments. It should only be executed in controlled environments where participants are informed of monitoring parameters in compliance with institutional data governance policies.
