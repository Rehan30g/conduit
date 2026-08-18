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

# Bound the on-disk history log so it doesn't grow forever on long-lived
# (e.g. --headless) processes. Once the file exceeds MAX_HISTORY_FILE_BYTES
# it's trimmed down to the most recent MAX_HISTORY_FILE_LINES entries.
MAX_HISTORY_FILE_BYTES = 5 * 1024 * 1024
MAX_HISTORY_FILE_LINES = 5000

# ──────────────────────────────────────────────────────
# HISTORY LOGGER
# ──────────────────────────────────────────────────────
def _rotate_history_file(history_file):
    with open(history_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    tmp_path = history_file + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.writelines(lines[-MAX_HISTORY_FILE_LINES:])
    os.replace(tmp_path, history_file)

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
            if os.path.getsize(history_file) > MAX_HISTORY_FILE_BYTES:
                _rotate_history_file(history_file)
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

    # subprocess only controls how *we* decode the bytes we get back; the
    # child still chooses what bytes to write. PowerShell and cmd default to
    # the legacy console codepage regardless of that decode setting, so
    # UTF-8-decoding their raw output produces mojibake, not just a decode
    # failure. Force each shell to write UTF-8 itself so the two sides agree.
    utf8_preamble_ps = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "$OutputEncoding = [System.Text.Encoding]::UTF8; "
    )

    if shell == "powershell":
        args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                utf8_preamble_ps + command]
    elif shell == "cmd":
        args = ["cmd.exe", "/c", "chcp 65001>nul && " + command]
    elif shell == "pwsh":
        args = ["pwsh", "-NoProfile", "-NonInteractive", "-Command",
                utf8_preamble_ps + command]
    elif shell in AVAILABLE_SHELLS:
        args = [shell, "-c", command]
    else:
        args = (["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                 utf8_preamble_ps + command]
                if IS_WINDOWS else [DEFAULT_SHELL, "-c", command])

    t0 = time.time()
    try:
        # errors="replace" remains a safety net for the POSIX shells, which
        # depend on the ambient locale rather than anything set above.
        r = subprocess.run(args, cwd=cwd, env=merged_env,
                           capture_output=True, text=True, timeout=300,
                           encoding="utf-8", errors="replace")
        ms = (time.time() - t0) * 1000
        # A non-zero exit is a failure, as the docs have always claimed. Passing
        # it off as SUCCESS tells the agent its install/service change worked.
        status = "SUCCESS" if r.returncode == 0 else "ERROR"
        return status, r.stdout, r.stderr, ms, r.returncode
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
        # One malformed or buggy request must never take the worker down with
        # it: if any step below raises, the thread would die and every later
        # command would sit in the queue until the caller's timeout. Catch
        # broadly, surface an error to *this* request, and keep looping.
        try:
            logging.info(f"[Engine] Processing request {req.id} | shell={req.shell}")

            if src.config.ALWAYS_ALLOW:
                approved = True
                logging.info(f"[Engine] Auto-approved {req.id} via Always Allow session rule.")
            else:
                prompt_res = run_gui_prompt(req.command, req.shell,
                                            cwd=req.cwd, env=req.env)
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
        except Exception:
            # exc_info=True keeps the traceback so the real bug is still
            # diagnosable, even though we refuse to let it kill the worker.
            logging.error(f"[Engine] Unexpected error while processing {req.id}; "
                          f"worker stays alive.", exc_info=True)
            req.response = {
                "status": "ERROR",
                "request_id": req.id,
                "shell_used": req.shell,
                "exit_code": -1,
                "output": "",
                "stderr": "Internal engine error while processing this command.",
                "duration_ms": 0.0,
            }
            # Record the failure in history too. Without this, a caught engine
            # error reaches the caller but never shows up in /history or
            # conduit_history.jsonl, leaving the run invisible in the audit
            # trail. Guard the call itself so history logging can never become
            # the thing that finally kills the worker.
            try:
                log_history(req.id, req.shell, req.command, "ERROR", "",
                            req.response["stderr"], 0.0, -1)
            except Exception:
                logging.error(f"[Engine] Failed to log_history for errored "
                              f"request {req.id}; worker stays alive.",
                              exc_info=True)
        finally:
            # Always release the waiting caller and balance the get(), so a
            # failed request returns promptly instead of hanging to timeout.
            req.event.set()
            COMMAND_QUEUE.task_done()
