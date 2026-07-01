import os
import sys
import json
import time
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
import src.config
from src.config import HOST, PORT, TOKEN, START_TIME, TEMPLATES_DIR, AVAILABLE_SHELLS, DEFAULT_SHELL
from src.engine import COMMAND_QUEUE, HISTORY, HISTORY_LOCK, CommandRequest

# ──────────────────────────────────────────────────────
# TEMPLATE LOADER
# ──────────────────────────────────────────────────────
def load_template(filename):
    path = os.path.join(TEMPLATES_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logging.error(f"Error loading template {filename}: {e}")
        return f"Error: Failed to load {filename} template from local templates/ directory."

# ──────────────────────────────────────────────────────
# HTTP SERVER HANDLER
# ──────────────────────────────────────────────────────
class ConduitHandler(BaseHTTPRequestHandler):

    def handle(self):
        try:
            super().handle()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def log_message(self, fmt, *args):
        if args and isinstance(args[0], str) and "/status" in args[0]:
            return
        logging.info(f"[HTTP] {fmt % args}")

    def send_json(self, code, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def check_auth(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self.send_json(401, {"status": "ERROR", "message": "Missing Authorization header."})
            return False
        if auth[7:].strip() != TOKEN:
            self.send_json(401, {"status": "ERROR", "message": "Invalid API token."})
            return False
        return True

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    # ── GET ────────────────────────────────────────────
    def do_GET(self):
        path = self.path.split("?")[0]

        # Web dashboard
        if path in ("/", "/dashboard"):
            html = load_template("dashboard.html")
            copy_prompt = (
                f"Conduit is active on my machine (http://127.0.0.1:{PORT}) with session token: {TOKEN}. "
                f"Please read http://127.0.0.1:{PORT}/agent.md for integration details. "
                f"You can now use Conduit to run administrative/privileged commands on my behalf."
            )
            copy_prompt_json = json.dumps(copy_prompt)

            shells_html = "".join(f'<span class="shell-tag">{s}</span>' for s in AVAILABLE_SHELLS)

            html = html.replace("[[TOKEN]]", TOKEN)
            html = html.replace("[[PORT]]", str(PORT))
            html = html.replace("[[PLATFORM]]", sys.platform)
            html = html.replace("[[SHELLS_HTML]]", shells_html)
            html = html.replace("[[COPY_PROMPT]]", copy_prompt)
            html = html.replace("[[COPY_PROMPT_JSON]]", copy_prompt_json)

            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Static dashboard.js script
        if path == "/dashboard.js":
            content = load_template("dashboard.js")
            body = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return

        # Static conduit.png logo
        if path == "/conduit.png":
            path_img = os.path.join(TEMPLATES_DIR, "conduit.png")
            try:
                with open(path_img, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                logging.error(f"Error serving conduit.png: {e}")
                self.send_json(404, {"status": "ERROR", "message": "Image not found."})
            return

        # Static conduit_flow.png diagram
        if path == "/conduit_flow.png":
            path_img = os.path.join(TEMPLATES_DIR, "conduit_flow.png")
            try:
                with open(path_img, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                logging.error(f"Error serving conduit_flow.png: {e}")
                self.send_json(404, {"status": "ERROR", "message": "Image not found."})
            return

        # Agent integration guide
        if path == "/agent.md":
            content = load_template("agent_template.md")
            content = content.replace("[[TOKEN]]", TOKEN)
            content = content.replace("[[PORT]]", str(PORT))
            content = content.replace("[[SHELLS]]", ", ".join(AVAILABLE_SHELLS))
            content = content.replace("[[DEFAULT_SHELL]]", DEFAULT_SHELL)

            body = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return

        # Status
        if path == "/status":
            self.send_json(200, {
                "status": "ONLINE",
                "uptime_seconds": int(time.time() - START_TIME),
                "queue_depth": COMMAND_QUEUE.qsize(),
                "available_shells": AVAILABLE_SHELLS,
                "platform": sys.platform,
                "python_version": sys.version.split()[0],
                "always_allow_active": src.config.ALWAYS_ALLOW,
            })
            return

        # Shells
        if path == "/shells":
            self.send_json(200, {"available_shells": AVAILABLE_SHELLS,
                                 "default_shell": DEFAULT_SHELL})
            return

        # History
        if path == "/history":
            if not self.check_auth():
                return
            with HISTORY_LOCK:
                self.send_json(200, HISTORY)
            return

        self.send_json(404, {"status": "ERROR", "message": "Endpoint not found."})

    # ── POST ───────────────────────────────────────────
    def do_POST(self):
        if self.path != "/":
            self.send_json(404, {"status": "ERROR", "message": "Endpoint not found."})
            return

        if not self.check_auth():
            return

        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length)

        command = ""; shell = DEFAULT_SHELL; cwd = None; env = None
        try:
            body = json.loads(raw_body.decode("utf-8"))
            if isinstance(body, dict):
                command = body.get("command", "")
                shell = body.get("shell", DEFAULT_SHELL)
                cwd = body.get("cwd")
                env = body.get("env")
            else:
                command = str(body)
        except (ValueError, UnicodeDecodeError):
            command = raw_body.decode("utf-8", errors="replace")

        if not command.strip():
            self.send_json(400, {"status": "ERROR", "message": "Command is empty."})
            return

        req = CommandRequest(command, shell, cwd, env)
        try:
            COMMAND_QUEUE.put(req, block=False)
        except Exception:
            self.send_json(503, {"status": "ERROR",
                                 "message": "Queue full. Try again shortly."})
            return

        req.event.wait()
        self.send_json(200, req.response or {"status": "ERROR",
                                             "message": "Internal processing failure."})

def run_server():
    server = HTTPServer((HOST, PORT), ConduitHandler)
    logging.info(f"[HTTP] Listening on http://{HOST}:{PORT}/")
    try:
        server.serve_forever()
    except Exception as e:
        logging.error(f"[HTTP] Server error: {e}")
    finally:
        server.server_close()
