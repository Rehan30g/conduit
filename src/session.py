import os
import json
import time
import logging

# The MCP bridge is spawned by the AI client as a separate process, so it cannot
# inherit the token from the running daemon. The daemon publishes it here instead,
# which keeps the client-side MCP config static even though the token rotates on
# every restart.
SESSION_DIR = os.path.join(os.path.expanduser("~"), ".conduit")
SESSION_FILE = os.path.join(SESSION_DIR, "session.json")


def write_session(token, host, port):
    """Publish the live session so local bridges can find the daemon."""
    data = {
        "token": token,
        "host": host,
        "port": port,
        "pid": os.getpid(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        os.makedirs(SESSION_DIR, exist_ok=True)
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        try:
            os.chmod(SESSION_FILE, 0o600)
        except Exception:
            pass  # Best effort — POSIX modes are only partially honoured on Windows.
        return True
    except Exception as e:
        logging.error(f"[Session] Could not write session file: {e}")
        return False


def read_session():
    """Return the published session dict, or None if Conduit is not running."""
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data.get("token") or not data.get("port"):
            return None
        return data
    except Exception:
        return None


def clear_session():
    try:
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
    except Exception as e:
        logging.error(f"[Session] Could not remove session file: {e}")
