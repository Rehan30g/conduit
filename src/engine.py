import os
import sys
import time
import json
import subprocess
import logging
import threading
from queue import Queue
import src.config
from src.config import ROOT_DIR, AVAILABLE_SHELLS, DEFAULT_SHELL, IS_WINDOWS
from src.dialogs import run_gui_prompt

COMMAND_QUEUE = Queue(maxsize=5)
HISTORY = []
HISTORY_LOCK = threading.Lock()

# ──────────────────────────────────────────────────────
# HISTORY LOGGER
# ──────────────────────────────────────────────────────
def log_history(request_id, shell, command, status, output, error, duration_ms, exit_code):
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "request_id": request_id,
        "shell": shell,
        "command": command,
        "status": status,
        "exit_code": exit_code,
        "duration_ms": int(duration_ms),
        "output_length": len(output) if output else 0,
        "error": error
    }
    with HISTORY_LOCK:
        HISTORY.insert(0, entry)
        if len(HISTORY) > 50:
            HISTORY.pop()
    try:
        history_file = os.path.join(ROOT_DIR, "conduit_history.jsonl")
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logging.error(f"Failed to write history log: {e}")

# ──────────────────────────────────────────────────────
# COMMAND REQUEST OBJECT
# ──────────────────────────────────────────────────────
class CommandRequest:
    def __init__(self, command, shell, cwd=None, env=None):
        self.id = str(uuid_v4())
        self.command = command
        self.shell = shell
        self.cwd = cwd
        self.env = env
        self.event = threading.Event()
        self.response = None

def uuid_v4():
    import uuid
    return str(uuid.uuid4())

# ──────────────────────────────────────────────────────
# EXECUTION ENGINE
# ──────────────────────────────────────────────────────
def execute_command(command, shell, cwd=None, env=None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    if shell == "powershell":
        args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
    elif shell == "cmd":
        args = ["cmd.exe", "/c", command]
    elif shell == "pwsh":
        args = ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command]
    elif shell in AVAILABLE_SHELLS:
        args = [shell, "-c", command]
    else:
        args = (["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
                if IS_WINDOWS else [DEFAULT_SHELL, "-c", command])

    t0 = time.time()
    try:
        r = subprocess.run(args, cwd=cwd, env=merged_env,
                           capture_output=True, text=True, timeout=300)
        ms = (time.time() - t0) * 1000
        return "SUCCESS", r.stdout, r.stderr, ms, r.returncode
    except subprocess.TimeoutExpired as e:
        ms = (time.time() - t0) * 1000
        return "ERROR", e.stdout or "", (e.stderr or "") + "\n[Process timed out — 5m limit]", ms, -1
    except Exception as e:
        ms = (time.time() - t0) * 1000
        return "ERROR", "", str(e), ms, -1

# ──────────────────────────────────────────────────────
# QUEUE WORKER
# ──────────────────────────────────────────────────────
def queue_worker():
    logging.info("[Engine] Command queue worker started.")
    while True:
        req = COMMAND_QUEUE.get()
        if req is None:
            break
        logging.info(f"[Engine] Processing request {req.id} | shell={req.shell}")

        if src.config.ALWAYS_ALLOW:
            approved = True
            logging.info(f"[Engine] Auto-approved {req.id} via Always Allow session rule.")
        else:
            prompt_res = run_gui_prompt(req.command, req.shell, req.cwd, req.env)
            if prompt_res == "ALWAYS":
                src.config.ALWAYS_ALLOW = True
                approved = True
                logging.info(f"[Engine] Always Allow activated by user for this session.")
            else:
                approved = bool(prompt_res)

        if approved:
            logging.info(f"[Engine] APPROVED {req.id}. Executing...")
            status, stdout, stderr, ms, code = execute_command(
                req.command, req.shell, req.cwd, req.env)
            req.response = {
                "status": status,
                "request_id": req.id,
                "shell_used": req.shell,
                "exit_code": code,
                "output": stdout,
                "stderr": stderr,
                "duration_ms": ms,
            }
            logging.info(f"[Engine] Done {req.id} in {ms:.1f}ms (exit={code})")
        else:
            logging.info(f"[Engine] DENIED {req.id}")
            req.response = {
                "status": "DENIED",
                "request_id": req.id,
                "shell_used": req.shell,
                "exit_code": -1,
                "output": "",
                "stderr": "Command denied by user.",
                "duration_ms": 0.0,
            }

        log_history(req.id, req.shell, req.command, req.response["status"],
                    req.response["output"],
                    req.response["stderr"] if req.response["status"] != "SUCCESS" else None,
                    req.response["duration_ms"], req.response["exit_code"])

        req.event.set()
        COMMAND_QUEUE.task_done()
