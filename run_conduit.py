#!/usr/bin/env python3
import os
import sys
import logging
import threading
import webbrowser

# Add the directory containing run_conduit.py to sys.path so we can import src cleanly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import HOST, PORT, TOKEN, AVAILABLE_SHELLS, DEFAULT_SHELL, IS_WINDOWS
from src.engine import queue_worker
from src.server import run_server

def is_gui_available():
    # 1. On Windows:
    if IS_WINDOWS:
        try:
            import ctypes
            # GetSystemMetrics(0) gets screen width. If it's 0 or user32 fails, GUI is not available.
            width = ctypes.windll.user32.GetSystemMetrics(0)
            return width > 0
        except Exception:
            pass
        
        # Fallback to checking tkinter
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            root.destroy()
            return True
        except Exception:
            return False

    # 2. On macOS:
    elif sys.platform == "darwin":
        # If in an SSH session and no display forwarding is active
        if "SSH_CLIENT" in os.environ and "DISPLAY" not in os.environ:
            return False
        # If not SSH, or if AppleScript/osascript works:
        try:
            import subprocess
            r = subprocess.run(["osascript", "-e", "tell application \"System Events\" to get name of first process"], capture_output=True, timeout=2)
            if r.returncode == 0:
                return True
        except Exception:
            pass
        # Fallback to tkinter
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            root.destroy()
            return True
        except Exception:
            return False

    # 3. On Linux/Unix:
    else:
        # Check display environment variables
        if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            return True
        return False

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Conduit - AI Admin Execution Bridge")
    parser.add_argument("--always-allow", action="store_true", help="Always allow execution requests without asking for approval")
    parser.add_argument("--headless", action="store_true", help="Run without opening dashboard in browser or showing GUI popups (implies --always-allow)")
    args = parser.parse_args()

    import src.config
    if args.always_allow:
        src.config.ALWAYS_ALLOW = True
    if args.headless:
        src.config.ALWAYS_ALLOW = True
        src.config.HEADLESS = True

    # Check GUI environment if not headless
    if not getattr(src.config, "HEADLESS", False):
        if not is_gui_available():
            print("[!] ERROR: No GUI/Screen environment detected.")
            print("    Conduit requires a graphical screen to display authorization popups.")
            print("    Please run in headless mode instead: python run_conduit.py --headless")
            sys.exit(1)

    is_admin = False
    if IS_WINDOWS:
        import ctypes
        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            pass
    else:
        is_admin = os.geteuid() == 0

    print("==================================================")
    print("                    CONDUIT                       ")
    print("      AI Admin Execution Bridge v2.1.1           ")
    print("==================================================")
    if src.config.ALWAYS_ALLOW:
        print("[!] ALWAYS ALLOW MODE: ACTIVE (Auto-approving commands)")
    if src.config.HEADLESS:
        print("[!] HEADLESS MODE: ACTIVE (No browser popup)")
    if not src.config.ALWAYS_ALLOW and not src.config.HEADLESS:
        print("[+] MODE: Standard (Prompts for authorization)")
    print("==================================================")
    if not is_admin:
        print("[!] WARNING: Not running as Administrator.")
        print("    Some privileged commands may fail.")
    else:
        print("[+] Running with Administrator / root privileges.")
    print("==================================================")
    print(f"API TOKEN  : {TOKEN}")
    print(f"Dashboard  : http://{HOST}:{PORT}/")
    print(f"Agent guide: http://{HOST}:{PORT}/agent.md")
    print("==================================================")
    print(f"Platform   : {sys.platform}")
    print(f"Shells     : {', '.join(AVAILABLE_SHELLS)}")
    print(f"Default    : {DEFAULT_SHELL}")
    print("==================================================")

    # Start HTTP server on background thread
    threading.Thread(target=run_server, daemon=True).start()

    # Open dashboard in browser
    if not src.config.HEADLESS:
        try:
            webbrowser.open(f"http://{HOST}:{PORT}/")
        except Exception:
            pass

    # Run queue worker on main thread (Tkinter requirements)
    try:
        queue_worker()
    except KeyboardInterrupt:
        print("\n[*] Shutdown by user. Goodbye.")
    except Exception as e:
        logging.error(f"Critical error: {e}")

if __name__ == "__main__":
    main()
