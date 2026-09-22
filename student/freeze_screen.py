import sys
import time
import threading
import signal
import platform
import tkinter as tk

# Configuration and Arguments
DEFAULT_MESSAGE = "UNAUTHORIZED ACTIVITY DETECTED"
WARNING_MESSAGE = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else DEFAULT_MESSAGE

try:
    FREEZE_DURATION = int(sys.argv[2]) if len(sys.argv) > 2 else 30
except ValueError:
    FREEZE_DURATION = 30

BLINK_INTERVAL = 0.5  # seconds
WARNING_COLORS = ["#FF2222", "#990000"]
BG_COLOR = "#0A0A0A"

is_running = True

def handle_exit_signal(sig, frame):
    global is_running
    is_running = False
    try:
        root.destroy()
    except Exception:
        pass
    sys.exit(0)

# Register clean termination signals
signal.signal(signal.SIGINT, handle_exit_signal)
signal.signal(signal.SIGTERM, handle_exit_signal)

root = tk.Tk()
root.title("EXAM MONITOR - SCREEN FROZEN")
root.attributes("-fullscreen", True)
root.attributes("-topmost", True)
root.configure(bg=BG_COLOR)
root.resizable(False, False)
root.config(cursor="none")

# Intercept close requests and common shortcut events
root.protocol("WM_DELETE_WINDOW", lambda: None)

def block_event(event):
    return "break"

# Block standard hotkeys and navigation
keys_to_block = [
    "<Key>", "<Alt-Tab>", "<Alt-F4>", "<Control-Escape>",
    "<Alt-Escape>", "<Control-Alt-Delete>", "<Control-Shift-Escape>",
    "<Windows-d>", "<Windows-e>", "<Windows-r>", "<Windows-m>",
    "<Command-Tab>", "<Command-Space>"
]

for key in keys_to_block:
    try:
        root.bind(key, block_event)
    except Exception:
        pass

# Block mouse interactions
mouse_events = [
    "<Button-1>", "<Button-2>", "<Button-3>",
    "<ButtonRelease-1>", "<ButtonRelease-2>", "<ButtonRelease-3>",
    "<Double-Button-1>", "<Double-Button-2>", "<Double-Button-3>"
]

for mouse_event in mouse_events:
    try:
        root.bind(mouse_event, block_event)
    except Exception:
        pass

# Content Layout
content_frame = tk.Frame(root, bg=BG_COLOR)
content_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

icon_label = tk.Label(
    content_frame,
    text="!",
    fg=WARNING_COLORS[0],
    bg=BG_COLOR,
    font=("Arial", 90, "bold")
)
icon_label.pack(pady=10)

warning_label = tk.Label(
    content_frame,
    text="EXAM VIOLATION ALERT",
    fg=WARNING_COLORS[0],
    bg=BG_COLOR,
    font=("Arial", 32, "bold")
)
warning_label.pack(pady=10)

details_label = tk.Label(
    content_frame,
    text=WARNING_MESSAGE,
    fg="#FFFFFF",
    bg=BG_COLOR,
    font=("Arial", 20),
    wraplength=800,
    justify="center"
)
details_label.pack(pady=15)

info_label = tk.Label(
    content_frame,
    text="Your screen has been temporarily locked by the exam proctor.\nAll background activities and open windows have been reported.",
    fg="#CCCCCC",
    bg=BG_COLOR,
    font=("Arial", 16),
    justify="center"
)
info_label.pack(pady=10)

countdown_var = tk.StringVar()
countdown_var.set(f"Screen will automatically unlock in {FREEZE_DURATION} seconds")
countdown_label = tk.Label(
    content_frame,
    textvariable=countdown_var,
    fg="#EEEEEE",
    bg=BG_COLOR,
    font=("Arial", 16, "italic")
)
countdown_label.pack(pady=15)

def blink_warning():
    color_index = 0
    while is_running:
        try:
            icon_label.config(fg=WARNING_COLORS[color_index])
            warning_label.config(fg=WARNING_COLORS[color_index])
            color_index = (color_index + 1) % len(WARNING_COLORS)
            time.sleep(BLINK_INTERVAL)
        except Exception:
            break

def update_countdown():
    remaining = FREEZE_DURATION
    while remaining > 0 and is_running:
        time.sleep(1)
        remaining -= 1
        try:
            countdown_var.set(f"Screen will automatically unlock in {remaining} seconds")
        except Exception:
            break
    if is_running:
        try:
            root.after(0, root.destroy)
        except Exception:
            pass

threading.Thread(target=blink_warning, daemon=True).start()
threading.Thread(target=update_countdown, daemon=True).start()

# Automatic close fallback
root.after(FREEZE_DURATION * 1000, root.destroy)

try:
    root.mainloop()
except Exception:
    pass
finally:
    is_running = False