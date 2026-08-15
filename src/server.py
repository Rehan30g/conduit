import os
import sys
import json
import time
import hmac
import logging
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import src.config
from src.config import HOST, PORT, TOKEN, START_TIME, TEMPLATES_DIR, AVAILABLE_SHELLS, DEFAULT_SHELL
from src.engine import COMMAND_QUEUE, HISTORY, HISTORY_LOCK, CommandRequest

# Only these may appear in the Host header. Anything else is a rebinding attempt.
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"[::1]:{PORT}"}
ALLOWED_ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}", f"http://[::1]:{PORT}"}

# 60 s approval window + 300 s execution ceiling + slack.
REQUEST_TIMEOUT = 400

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
        self.end_headers()
        self.wfile.write(body)

    def check_auth(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self.send_json(401, {"status": "ERROR", "message": "Missing Authorization header."})
            return False
        if not hmac.compare_digest(auth[7:].strip(), TOKEN):
            self.send_json(401, {"status": "ERROR", "message": "Invalid API token."})
            return False
        return True

    def check_local(self):
        # Two browser-borne attacks have to be shut out here, because the only
        # thing guarding root on this machine is a token sitting in a page the
        # browser can otherwise be talked into fetching.
        #
        # 1. DNS rebinding. A page on evil.test whose record flips to 127.0.0.1
        #    becomes *same-origin* with us, so CORS stops applying entirely. The
        #    Host header still carries the attacker's hostname, so reject on it.
        # 2. Plain cross-origin reads. Any page the developer happens to have
        #    open could otherwise fetch /agent.md or / and scrape the token.
        host = self.headers.get("Host", "")
        if host not in ALLOWED_HOSTS:
            logging.warning(f"[HTTP] Rejected request with foreign Host header: {host!r}")
            self.send_json(403, {"status": "ERROR",
                                 "message": "Conduit only serves 127.0.0.1."})
            return False

        origin = self.headers.get("Origin")
        if origin and origin not in ALLOWED_ORIGINS:
            logging.warning(f"[HTTP] Rejected cross-origin request from: {origin!r}")
            self.send_json(403, {"status": "ERROR",
                                 "message": "Cross-origin requests are not allowed."})
            return False
        return True

    def do_OPTIONS(self):
        # Deliberately no Access-Control-Allow-* headers: nothing legitimate talks
        # to Conduit cross-origin, and granting the preflight is what would let a
        # web page send the Authorization header at all.
        self.send_json(403, {"status": "ERROR",
                             "message": "Cross-origin requests are not allowed."})

    # ── GET ────────────────────────────────────────────
    def do_GET(self):
        if not self.check_local():
            return
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

        # Ready-to-paste MCP client config
        if path == "/mcp.json":
            script = os.path.join(os.path.dirname(TEMPLATES_DIR), "run_conduit.py")
            self.send_json(200, {
                "mcpServers": {
                    "conduit": {
                        "command": sys.executable,
                        "args": [script, "--mcp"],
                    }
                }
            })
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
        if not self.check_local():
            return

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

        # A JSON body can put any type in these fields, but the engine assumes
        # specific ones: command/shell get .strip()'d and handed to the shell as
        # strings, cwd is passed to subprocess as a path, and env is fed straight
        # into dict.update(). Two of those turn a malformed request into an
        # uncaught exception:
        #   - a non-string command hits AttributeError in command.strip() below;
        #   - a non-dict env (e.g. {"env": "x"}) makes dict.update() raise
        #     ValueError inside execute_command, *before* its try block, so the
        #     exception unwinds the queue worker thread and kills it. Every later
        #     command then just sits in the queue until the caller's 400 s wait
        #     times out — the daemon is effectively dead with no error surfaced.
        # Validate the shapes here and answer 400 instead of letting them through.
        if not isinstance(command, str):
            self.send_json(400, {"status": "ERROR", "message": "'command' must be a string."})
            return
        if not isinstance(shell, str):
            self.send_json(400, {"status": "ERROR", "message": "'shell' must be a string."})
            return
        if cwd is not None and not isinstance(cwd, str):
            self.send_json(400, {"status": "ERROR", "message": "'cwd' must be a string or null."})
            return
        if env is not None and not (isinstance(env, dict) and all(
                isinstance(k, str) and isinstance(v, str) for k, v in env.items())):
            self.send_json(400, {"status": "ERROR",
                                 "message": "'env' must be an object mapping string keys to string values."})
            return

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

        # Bounded: 60 s approval window plus the 5 minute execution ceiling, with
        # slack. Waiting forever means one wedged command holds the caller open
        # with no way to recover.
        if not req.event.wait(timeout=REQUEST_TIMEOUT):
            self.send_json(504, {
                "status": "ERROR",
                "request_id": req.id,
                "message": "Timed out waiting for approval and execution. The command may "
                           "still be running — do not retry it blindly.",
            })
            return

        self.send_json(200, req.response or {"status": "ERROR",
                                             "message": "Internal processing failure."})


class ConduitTCPServer(ThreadingHTTPServer):
    # HTTPServer defaults this to True. On POSIX that only lets a restarted
    # server rebind a socket stuck in TIME_WAIT; on Windows, SO_REUSEADDR also
    # lets an unrelated process bind an address that is already LISTENING,
    # silently splitting traffic between two daemons with two different
    # tokens instead of the second bind failing. Disabling it restores "port
    # already in use" as an actual error on every platform, which is what the
    # already-running check below depends on.
    allow_reuse_address = False


def bind_server():
    """Bind the listening socket, or return None if the port is already taken."""
    try:
        return ConduitTCPServer((HOST, PORT), ConduitHandler)
    except OSError as e:
        logging.error(f"[HTTP] Could not bind {HOST}:{PORT} — {e}")
        return None


def run_server(server=None):
    # Threaded: a single approval dialog blocks its request for up to 60 s, and
    # on a single-threaded server that stalled *everything* — the dashboard's
    # status poll, a second agent, the MCP bridge — and left the documented
    # 5-slot queue permanently empty.
    if server is None:
        server = bind_server()
    if server is None:
        print(f"\n[!] ERROR: port {PORT} is already in use. Conduit may already be running.")
        print("    Close the other instance, then start this one again.")
        os._exit(1)

    logging.info(f"[HTTP] Listening on http://{HOST}:{PORT}/")
    try:
        server.serve_forever()
    except Exception as e:
        logging.error(f"[HTTP] Server error: {e}")
    finally:
        server.server_close()
