"""Conduit MCP bridge — a stdio JSON-RPC proxy to the running Conduit daemon.

The AI client spawns this process itself, inside its own unprivileged context, so
this file deliberately executes nothing. Every tool call is forwarded over
localhost HTTP to the daemon the developer started, which owns the approval
dialog and the elevated privileges. Keeping execution on the daemon side is what
preserves the human-in-the-loop guarantee: the bridge cannot bypass it, because
it has no way to run a command on its own.

Protocol note: stdout is reserved exclusively for JSON-RPC frames. All logging
goes to stderr, otherwise the client's parser breaks.
"""

import os
import sys
import json
import logging
import urllib.request
import urllib.error

from src.session import read_session

SERVER_NAME = "conduit"
SERVER_VERSION = "2.1.0"

DEFAULT_PROTOCOL = "2025-06-18"
SUPPORTED_PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")

# Generous: a call can wait through a 60 s approval window plus the daemon's
# 5 minute execution ceiling before it is allowed to give up.
HTTP_TIMEOUT = 420

NOT_RUNNING_HINT = (
    "Conduit is not running. The developer needs to start it in an elevated terminal "
    "(`python run_conduit.py`, or double-click conduit.bat on Windows) before commands "
    "can be approved and executed. Ask them to start it, then retry."
)


# ──────────────────────────────────────────────────────
# DAEMON CLIENT
# ──────────────────────────────────────────────────────
def _endpoint(session, path="/"):
    return f"http://{session.get('host', '127.0.0.1')}:{session['port']}{path}"


def _resolve_session():
    """Locate the daemon. Explicit env vars win over the published session file."""
    env_token = os.environ.get("CONDUIT_TOKEN")
    env_port = os.environ.get("CONDUIT_PORT")
    session = read_session()

    if env_token:
        return {
            "token": env_token,
            "host": os.environ.get("CONDUIT_HOST", "127.0.0.1"),
            "port": int(env_port) if env_port else (session or {}).get("port", 40404),
        }
    return session


def daemon_get(path, session=None, auth=False, timeout=10):
    session = session or _resolve_session()
    if not session:
        raise ConduitOffline(NOT_RUNNING_HINT)

    headers = {}
    if auth:
        headers["Authorization"] = f"Bearer {session['token']}"
    req = urllib.request.Request(_endpoint(session, path), headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise ConduitOffline(f"{NOT_RUNNING_HINT}\n\n(connection error: {e})")


def daemon_execute(command, shell=None, cwd=None, env=None):
    session = _resolve_session()
    if not session:
        raise ConduitOffline(NOT_RUNNING_HINT)

    payload = {"command": command}
    if shell:
        payload["shell"] = shell
    if cwd:
        payload["cwd"] = cwd
    if env:
        payload["env"] = env

    req = urllib.request.Request(
        _endpoint(session, "/"),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {session['token']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        if e.code == 401:
            raise ConduitOffline(
                "Conduit rejected the session token. It was most likely restarted, which "
                "issues a fresh token. Ask the developer to restart Conduit (or reload this "
                "MCP server) so the bridge picks up the current session."
            )
        if e.code == 503:
            raise ConduitOffline(
                "Conduit's approval queue is full (5 pending commands). Wait for the "
                "developer to work through the pending dialogs, then retry."
            )
        raise ConduitOffline(f"Conduit returned HTTP {e.code}: {body or e.reason}")
    except urllib.error.URLError as e:
        raise ConduitOffline(f"{NOT_RUNNING_HINT}\n\n(connection error: {e})")


class ConduitOffline(Exception):
    """The daemon could not be reached, or refused the request outright."""


# ──────────────────────────────────────────────────────
# TOOL DEFINITIONS
# ──────────────────────────────────────────────────────
RUN_COMMAND_DESCRIPTION = (
    "Run a shell command on the developer's machine with the administrator/root "
    "privileges they granted Conduit when they started it.\n\n"
    "The developer approves every call: the command is shown to them in a dialog that "
    "defaults to No, and nothing runs until they actively click Yes. Unanswered "
    "requests auto-deny after 60 seconds, and a denial comes back as status DENIED. "
    "Treat this like asking a human sysadmin to run something for you — say what you "
    "intend to run and why before you call it, and send one specific, reviewable "
    "command rather than a long opaque script.\n\n"
    "Use it for work the developer's normal environment cannot do on its own: "
    "installing system packages, managing services, writing to protected paths, "
    "changing firewall or network settings."
)


def build_tools(shells=None, default_shell=None):
    shell_schema = {
        "type": "string",
        "description": "Shell to run the command in. Defaults to the machine's default shell.",
    }
    if shells:
        shell_schema["enum"] = shells
        shell_schema["description"] = (
            f"Shell to run the command in. Available on this machine: {', '.join(shells)}. "
            f"Defaults to {default_shell}."
        )

    return [
        {
            "name": "run_command",
            "title": "Run privileged command",
            "description": RUN_COMMAND_DESCRIPTION,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The exact command to run. Keep it specific and reviewable — the developer reads this text in the approval dialog.",
                    },
                    "shell": shell_schema,
                    "cwd": {
                        "type": "string",
                        "description": "Optional working directory for the command.",
                    },
                    "env": {
                        "type": "object",
                        "description": "Optional extra environment variables, merged over the daemon's environment.",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["command"],
            },
            "annotations": {
                "title": "Run privileged command",
                "destructiveHint": True,
                "openWorldHint": True,
            },
        },
        {
            "name": "list_shells",
            "title": "List available shells",
            "description": "List the shells Conduit can run commands in on this machine, and which one is the default. Read-only; no approval dialog.",
            "inputSchema": {"type": "object", "properties": {}},
            "annotations": {"title": "List available shells", "readOnlyHint": True},
        },
        {
            "name": "get_status",
            "title": "Check Conduit status",
            "description": "Check whether Conduit is running, plus uptime, pending approval queue depth, and platform. Read-only; no approval dialog. Useful to confirm the bridge is live before proposing privileged work.",
            "inputSchema": {"type": "object", "properties": {}},
            "annotations": {"title": "Check Conduit status", "readOnlyHint": True},
        },
    ]


def list_tools():
    """Advertise the real shell list when the daemon is up, generic schema when not."""
    try:
        info = daemon_get("/shells", timeout=5)
        return build_tools(info.get("available_shells"), info.get("default_shell"))
    except Exception:
        return build_tools()


# ──────────────────────────────────────────────────────
# TOOL DISPATCH
# ──────────────────────────────────────────────────────
def text_result(text, is_error=False):
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def format_execution(result):
    status = result.get("status", "UNKNOWN")

    if status == "DENIED":
        return text_result(
            "DENIED — the developer declined this command (or the 60 second approval "
            "window expired). It did not run. Do not retry the same command; ask them "
            "what they would prefer instead."
        )

    lines = [
        f"status: {status}",
        f"exit_code: {result.get('exit_code')}",
        f"shell: {result.get('shell_used')}",
        f"duration_ms: {result.get('duration_ms')}",
    ]
    stdout = (result.get("output") or "").rstrip()
    stderr = (result.get("stderr") or "").rstrip()
    if stdout:
        lines.append(f"\n--- stdout ---\n{stdout}")
    if stderr:
        lines.append(f"\n--- stderr ---\n{stderr}")
    if not stdout and not stderr:
        lines.append("\n(no output)")

    return text_result("\n".join(lines), is_error=(status == "ERROR"))


def call_tool(name, arguments):
    arguments = arguments or {}

    if name == "run_command":
        command = (arguments.get("command") or "").strip()
        if not command:
            return text_result("No command provided.", is_error=True)
        result = daemon_execute(
            command,
            shell=arguments.get("shell"),
            cwd=arguments.get("cwd"),
            env=arguments.get("env"),
        )
        return format_execution(result)

    if name == "list_shells":
        info = daemon_get("/shells")
        return text_result(
            f"available_shells: {', '.join(info.get('available_shells', []))}\n"
            f"default_shell: {info.get('default_shell')}"
        )

    if name == "get_status":
        info = daemon_get("/status")
        return text_result(
            f"status: {info.get('status')}\n"
            f"uptime_seconds: {info.get('uptime_seconds')}\n"
            f"queue_depth: {info.get('queue_depth')}\n"
            f"platform: {info.get('platform')}\n"
            f"available_shells: {', '.join(info.get('available_shells', []))}\n"
            f"always_allow_active: {info.get('always_allow_active')}"
        )

    raise KeyError(name)


# ──────────────────────────────────────────────────────
# JSON-RPC PLUMBING
# ──────────────────────────────────────────────────────
def write_message(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def respond(request_id, result):
    write_message({"jsonrpc": "2.0", "id": request_id, "result": result})


def respond_error(request_id, code, message):
    write_message({"jsonrpc": "2.0", "id": request_id,
                   "error": {"code": code, "message": message}})


def handle_message(msg):
    method = msg.get("method")
    request_id = msg.get("id")
    params = msg.get("params") or {}
    is_notification = request_id is None

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOLS else DEFAULT_PROTOCOL
        respond(request_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "Conduit runs shell commands on the developer's machine with the elevated "
                "privileges they granted it. Every call is gated by an approval dialog on "
                "their screen that defaults to No — nothing executes unless they click Yes, "
                "and unanswered requests auto-deny after 60 seconds. Propose the specific "
                "command and the reason for it before calling run_command."
            ),
        })
        return

    if is_notification:
        return  # initialized, cancelled, progress — nothing to reply to.

    if method == "ping":
        respond(request_id, {})
        return

    if method == "tools/list":
        respond(request_id, {"tools": list_tools()})
        return

    if method == "tools/call":
        name = params.get("name")
        try:
            respond(request_id, call_tool(name, params.get("arguments")))
        except ConduitOffline as e:
            # A tool-level error, not a protocol error: the model should read the
            # hint and relay it to the developer rather than treat the call as broken.
            respond(request_id, text_result(str(e), is_error=True))
        except KeyError:
            respond_error(request_id, -32602, f"Unknown tool: {name}")
        except Exception as e:
            logging.exception("[MCP] Tool call failed")
            respond(request_id, text_result(f"Conduit bridge error: {e}", is_error=True))
        return

    # Clients commonly probe these even when unadvertised; empty beats an error.
    if method in ("resources/list", "resources/templates/list"):
        respond(request_id, {"resources": [], "resourceTemplates": []}
                if method == "resources/templates/list" else {"resources": []})
        return
    if method == "prompts/list":
        respond(request_id, {"prompts": []})
        return

    respond_error(request_id, -32601, f"Method not found: {method}")


def run_mcp_server():
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="[Conduit MCP] %(levelname)s: %(message)s",
    )
    logging.info(f"Bridge started (v{SERVER_VERSION}). Proxying to the Conduit daemon.")

    stdin = getattr(sys.stdin, "buffer", sys.stdin)
    while True:
        line = stdin.readline()
        if not line:
            break  # Client closed the pipe — normal shutdown.
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except ValueError:
            respond_error(None, -32700, "Parse error: invalid JSON.")
            continue

        try:
            handle_message(msg)
        except Exception as e:
            logging.exception("[MCP] Unhandled error")
            if msg.get("id") is not None:
                respond_error(msg.get("id"), -32603, f"Internal error: {e}")

    logging.info("Bridge stopped.")
