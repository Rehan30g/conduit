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

def main():
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
    print("      AI Admin Execution Bridge v2.0.0           ")
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
