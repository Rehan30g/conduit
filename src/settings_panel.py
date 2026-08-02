"""Conduit terminal settings panel — a line-oriented control prompt for the daemon.

Interaction model: a plain line reader on a daemon thread, not a full-screen TUI.
The main thread belongs to queue_worker() and its Tkinter dialogs, and log lines
land in the same terminal at arbitrary moments. A redraw-based UI would fight the
logger for the cursor and would need curses (unavailable on Windows). A prompt
that only prints when it has something to say survives interleaved output: the
worst that happens is a stale prompt line, and the developer can press Enter
again. Everything the panel does is a short printed block, so scrollback stays
readable.

The panel never runs in --mcp mode (stdin is the JSON-RPC transport there) and
never runs without a TTY on stdin. It mutates src.config.ALWAYS_ALLOW as a module
attribute, which is the single source of truth every reader consults at call time.
"""

import os
import sys
import json
import time
import socket
import shutil
import logging
import threading
import webbrowser
from queue import Full

import src.config
from src.config import (HOST, PORT, TOKEN, START_TIME, AVAILABLE_SHELLS,
                        DEFAULT_SHELL, IS_WINDOWS)
from src.engine import COMMAND_QUEUE, HISTORY, HISTORY_LOCK
from src.session import clear_session

DEFAULT_HISTORY_ROWS = 10

# ──────────────────────────────────────────────────────
# TERMINAL CAPABILITIES
# ──────────────────────────────────────────────────────
_STYLE = {"ansi": False, "rule": "-"}

BOLD = "1"; DIM = "2"; RED = "31"; GREEN = "32"; YELLOW = "33"; CYAN = "36"


def _enable_ansi():
    """Turn on VT processing on Windows; degrade to plain text if we cannot."""
    if os.environ.get("NO_COLOR"):
        return False
    if not (hasattr(sys.stdout, "isatty") and sys.stdout.isatty()):
        return False
    if not IS_WINDOWS:
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.GetStdHandle.restype = ctypes.c_void_p
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        if not handle or handle == ctypes.c_void_p(-1).value:
            return False
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode)):
            return False
        vt = 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        if mode.value & vt:
            return True
        return bool(kernel32.SetConsoleMode(ctypes.c_void_p(handle), mode.value | vt))
    except Exception as e:
        logging.debug(f"[Panel] VT processing unavailable: {e}")
        return False


def _unicode_ok():
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    if "utf" in enc:
        return True
    try:
        "─".encode(enc or "ascii")
        return True
    except Exception:
        return False


def _s(code, text):
    if not _STYLE["ansi"]:
        return text
    return "\033[%sm%s\033[0m" % (code, text)


def _width():
    try:
        cols = shutil.get_terminal_size((80, 24)).columns
    except Exception:
        cols = 80
    return max(46, min(int(cols), 118))


def _rule():
    return _s(DIM, _STYLE["rule"] * _width())


# ──────────────────────────────────────────────────────
# OUTPUT
# ──────────────────────────────────────────────────────
_OUT_LOCK = threading.Lock()


def _block(lines):
    """Emit a whole panel block in one write so the logger interleaves between
    blocks rather than through the middle of one."""
    text = "\n".join(lines) + "\n"
    with _OUT_LOCK:
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except Exception:
            pass


def _prompt():
    with _OUT_LOCK:
        try:
            sys.stdout.write(_s(CYAN, "conduit> "))
            sys.stdout.flush()
        except Exception:
            pass


def _head(title):
    return [_rule(), _s(BOLD, "  " + title), _rule()]


# ──────────────────────────────────────────────────────
# FORMATTING HELPERS
# ──────────────────────────────────────────────────────
def _uptime_text():
    total = int(max(0, time.time() - START_TIME))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%dh %02dm %02ds" % (h, m, s)
    if m:
        return "%dm %02ds" % (m, s)
    return "%ds" % s


def _masked_token():
    if len(TOKEN) <= 4:
        return "*" * len(TOKEN)
    return "*" * 8 + TOKEN[-4:]


def _one_line(text, limit):
    text = " ".join(str(text or "").split())
    if limit > 3 and len(text) > limit:
        return text[:limit - 3] + "..."
    return text


def _status_colour(status):
    if status == "SUCCESS":
        return _s(GREEN, "SUCCESS")
    if status == "DENIED":
        return _s(YELLOW, "DENIED ")
    return _s(RED, _one_line(status, 7).ljust(7))


def _allow_text():
    if src.config.ALWAYS_ALLOW:
        return _s(RED, "ON  - commands auto-approve, no human in the loop")
    return _s(GREEN, "OFF - every command needs an approval dialog")


def _http_up():
    try:
        sock = socket.create_connection((HOST, PORT), 0.6)
        sock.close()
        return True
    except Exception:
        return False


# ──────────────────────────────────────────────────────
# PANEL CONTEXT
# ──────────────────────────────────────────────────────
def make_context(is_admin=False, mcp_config=None, gui_check=None, read=None):
    return {
        "is_admin": bool(is_admin),
        "mcp_config": mcp_config,
        "gui_check": gui_check,
        "gui_cached": None,
        "read": read or _stdin_read,
        "open": False,
        "reveal_token": False,
    }


def _gui_available(ctx):
    if ctx["gui_cached"] is None:
        check = ctx.get("gui_check")
        if not callable(check):
            ctx["gui_cached"] = True
        else:
            try:
                ctx["gui_cached"] = bool(check())
            except Exception as e:
                logging.warning(f"[Panel] GUI probe failed: {e}")
                ctx["gui_cached"] = True
    return ctx["gui_cached"]


# ──────────────────────────────────────────────────────
# VIEWS
# ──────────────────────────────────────────────────────
def menu_lines(ctx):
    state = "ON" if src.config.ALWAYS_ALLOW else "OFF"
    tok = "shown" if ctx["reveal_token"] else "hidden"
    return _head("CONDUIT SETTINGS PANEL") + [
        "  s   status       session info, endpoints, live daemon state",
        "  a   allow        toggle Always-Allow          (now: %s)" % state,
        "  t   token        reveal / hide the API token  (now: %s)" % tok,
        "  r   recent [n]   last n executed commands     (default %d)" % DEFAULT_HISTORY_ROWS,
        "  m   mcp          MCP client config to paste into your AI client",
        "  o   open         open the dashboard in a browser",
        "  k   clear        clear the screen",
        "  c   close        close the panel, back to the plain log view",
        "  q   quit         shut Conduit down cleanly  (q! = force)",
        "  ?   help         this menu",
        _rule(),
        _s(DIM, "  Enter on its own reprints this menu."),
        "",
    ]


def status_lines(ctx):
    token = TOKEN if ctx["reveal_token"] else _masked_token() + "   (t to reveal)"
    priv = (_s(GREEN, "Administrator / root")
            if ctx["is_admin"] else _s(YELLOW, "NOT elevated - privileged commands may fail"))
    up = _s(GREEN, "UP") if _http_up() else _s(RED, "DOWN")
    with HISTORY_LOCK:
        hist_n = len(HISTORY)
    return _head("SESSION") + [
        "  Token       : %s" % token,
        "  Dashboard   : http://%s:%d/" % (HOST, PORT),
        "  Agent guide : http://%s:%d/agent.md" % (HOST, PORT),
        "  Uptime      : %s" % _uptime_text(),
        "  Privileges  : %s" % priv,
        "  Platform    : %s   (Python %s, pid %d)" % (
            sys.platform, sys.version.split()[0], os.getpid()),
        "  Shells      : %s   (default: %s)" % (
            ", ".join(AVAILABLE_SHELLS) or "none detected", DEFAULT_SHELL),
    ] + _head("LIVE") + [
        "  Always-Allow: %s" % _allow_text(),
        "  Headless    : %s" % ("yes" if src.config.HEADLESS else "no"),
        "  HTTP server : %s   (%s:%d)" % (up, HOST, PORT),
        "  Queue depth : %d pending" % COMMAND_QUEUE.qsize(),
        "  History     : %d entries this session" % hist_n,
        _rule(),
        "",
    ]


def history_lines(count):
    with HISTORY_LOCK:
        rows = list(HISTORY[:count])
    if not rows:
        return _head("RECENT COMMANDS") + [
            _s(DIM, "  Nothing has been executed yet this session."), _rule(), ""]

    fixed = len("  HH:MM:SS  SUCCESS  ####  ########  ")
    cmd_w = max(16, _width() - fixed)
    out = _head("RECENT COMMANDS (newest first, times UTC)") + [
        _s(DIM, "  TIME      STATUS   EXIT  DURATION  COMMAND")]
    for e in rows:
        stamp = str(e.get("timestamp") or "")
        clock = stamp[11:19] if len(stamp) >= 19 else (stamp[:8] or "--:--:--")
        code = e.get("exit_code")
        code = "-" if code is None else str(code)
        ms = e.get("duration_ms") or 0
        dur = "%.1fs" % (ms / 1000.0) if ms >= 1000 else "%dms" % int(ms)
        out.append("  %-8s  %s  %4s  %8s  %s" % (
            clock, _status_colour(e.get("status", "?")), code[:4], dur[:8],
            _one_line(e.get("command"), cmd_w)))
    out.append(_rule())
    out.append("")
    return out


def mcp_lines(ctx):
    provider = ctx.get("mcp_config")
    if not callable(provider):
        return ["", _s(YELLOW, "[panel] MCP config is unavailable in this process."), ""]
    try:
        cfg = provider()
        body = json.dumps(cfg, indent=2)
    except Exception as e:
        logging.error(f"[Panel] Could not build MCP config: {e}")
        return ["", _s(RED, "[panel] Could not build the MCP config: %s" % e), ""]

    out = _head("MCP CLIENT CONFIG") + [
        _s(DIM, "  Paste into your AI client's MCP config, then restart the client."),
        "",
    ]
    out.extend("  " + line for line in body.splitlines())

    # Derive the one-liner from the same dict so there is no second source of truth.
    try:
        entry = cfg["mcpServers"]["conduit"]
        argv = " ".join([entry["command"]] + list(entry.get("args") or []))
        out += ["", "  Claude Code   : claude mcp add conduit -- %s" % argv]
    except Exception:
        pass
    out += [
        "  Cursor        : ~/.cursor/mcp.json",
        "  Claude Desktop: claude_desktop_config.json",
        "",
        _s(DIM, "  The bridge reads the live token from ~/.conduit/session.json, so this"),
        _s(DIM, "  config stays valid across restarts. Conduit must be running."),
        _rule(),
        "",
    ]
    return out


# ──────────────────────────────────────────────────────
# ACTIONS
# ──────────────────────────────────────────────────────
def _toggle_token(ctx):
    ctx["reveal_token"] = not ctx["reveal_token"]
    if ctx["reveal_token"]:
        _block(["", "  API TOKEN : " + _s(BOLD, TOKEN),
                _s(DIM, "  Anything holding this token can run privileged commands. "
                        "Press 't' again to hide it."), ""])
    else:
        _block(["", "  API TOKEN : " + _masked_token() + _s(DIM, "   (hidden)"), ""])


def _toggle_always_allow(ctx):
    """The one genuinely dangerous control. src.config.ALWAYS_ALLOW is the single
    source of truth — engine.queue_worker() and the /status endpoint both read the
    module attribute at call time, so assigning it here is immediately visible."""
    if src.config.ALWAYS_ALLOW:
        if not _gui_available(ctx):
            _block([
                "",
                _s(YELLOW, "  [!] No GUI/screen detected on this machine."),
                "      Turning Always-Allow off means every command needs approval, but",
                "      without a GUI the approval falls back to a prompt on the MAIN thread",
                "      that reads this same terminal - it will compete with this panel.",
                "      Close the panel with 'c' afterwards if approvals stop responding.",
                "",
            ])
        src.config.ALWAYS_ALLOW = False
        logging.warning("[Panel] Always-Allow DISABLED from the settings panel.")
        _block(["", _s(GREEN, "  [+] Always-Allow is now OFF."),
                "      Every subsequent command will wait for your approval again.", ""])
        return ""

    _block([
        "",
        _s(RED, "  " + _STYLE["rule"] * (_width() - 2)),
        _s(RED, "  [!] ENABLE ALWAYS-ALLOW?"),
        "",
        "      Every command the AI agent sends will execute immediately with",
        "      administrator privileges. No dialog. No human in the loop.",
        "      A misbehaving or hijacked agent could delete files, change system",
        "      settings, or install software without you seeing it.",
        "",
        "      This lasts for the rest of this session (or until you press 'a' again).",
        _s(RED, "  " + _STYLE["rule"] * (_width() - 2)),
        "",
    ])
    with _OUT_LOCK:
        try:
            sys.stdout.write("  Type " + _s(BOLD, "yes") + " to confirm, anything else cancels: ")
            sys.stdout.flush()
        except Exception:
            pass

    answer = ctx["read"]()
    if answer is None:
        return "eof"
    if answer.strip().lower() in ("y", "yes"):
        src.config.ALWAYS_ALLOW = True
        logging.warning("[Panel] Always-Allow ENABLED from the settings panel.")
        _block(["", _s(RED, "  [!] Always-Allow is now ON - commands run without approval."),
                "      Press 'a' again at any time to turn it back off.", ""])
    else:
        _block(["", _s(GREEN, "  [+] Cancelled. Always-Allow stays OFF."), ""])
    return ""


def _clear_screen():
    if _STYLE["ansi"]:
        with _OUT_LOCK:
            try:
                sys.stdout.write("\033[2J\033[H")
                sys.stdout.flush()
            except Exception:
                pass
        return
    try:
        os.system("cls" if IS_WINDOWS else "clear")
    except Exception:
        _block([""] * 5)


def _open_dashboard():
    url = "http://%s:%d/" % (HOST, PORT)
    try:
        webbrowser.open(url)
        _block(["", "  [+] Opened %s" % url, ""])
    except Exception as e:
        logging.warning(f"[Panel] Could not open browser: {e}")
        _block(["", _s(YELLOW, "  [!] Could not open a browser. Visit %s" % url), ""])


def _quit(force=False):
    """Shut down through queue_worker's own sentinel so run_conduit's
    finally: clear_session() still runs."""
    if force:
        _block(["", _s(YELLOW, "  [!] Force shutdown - clearing the session and exiting now."), ""])
        try:
            clear_session()
        except Exception:
            pass
        os._exit(0)

    pending = COMMAND_QUEUE.qsize()
    try:
        COMMAND_QUEUE.put_nowait(None)
    except Full:
        _block([
            "",
            _s(YELLOW, "  [!] The approval queue is full (%d pending)." % pending),
            "      Answer or let the open dialogs time out, then press 'q' again.",
            "      Use 'q!' to force an immediate shutdown instead.",
            "",
        ])
        return ""

    if pending:
        _block(["", "  [*] Shutdown queued behind %d pending command(s)." % pending,
                "      Conduit exits once they are answered.", ""])
    else:
        _block(["", "  [*] Shutting down. Goodbye.", ""])
    return "quit"


# ──────────────────────────────────────────────────────
# COMMAND DISPATCH
# ──────────────────────────────────────────────────────
def handle_command(raw, ctx):
    """Return "" to stay open, "close", "quit" or "eof". Pure enough to drive
    directly from a test with a fake ctx["read"]."""
    parts = (raw or "").strip().split()
    if not parts:
        _block(menu_lines(ctx))
        return ""
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else None

    if cmd in ("?", "h", "help", "menu"):
        _block(menu_lines(ctx))
    elif cmd in ("s", "status", "info"):
        _block(status_lines(ctx))
    elif cmd in ("a", "allow", "always"):
        return _toggle_always_allow(ctx)
    elif cmd in ("t", "token"):
        _toggle_token(ctx)
    elif cmd in ("r", "recent", "history", "hist"):
        count = DEFAULT_HISTORY_ROWS
        if arg:
            try:
                count = max(1, min(int(arg), 50))
            except ValueError:
                _block(["", _s(YELLOW, "  [!] '%s' is not a number - showing %d."
                               % (_one_line(arg, 20), count)), ""])
        _block(history_lines(count))
    elif cmd in ("m", "mcp", "mcp-config"):
        _block(mcp_lines(ctx))
    elif cmd in ("o", "open", "dash", "dashboard"):
        _open_dashboard()
    elif cmd in ("k", "cls", "clear"):
        _clear_screen()
    elif cmd in ("c", "close", "hide", "back"):
        return "close"
    elif cmd in ("q", "quit", "exit", "stop"):
        return _quit()
    elif cmd in ("q!", "quit!"):
        return _quit(force=True)
    else:
        _block(["", _s(YELLOW, "  [!] Unknown command: %s" % _one_line(cmd, 30)),
                _s(DIM, "      Press ? for the menu."), ""])
    return ""


def _stdin_read():
    """Blocking line read. Returns None on EOF or a dead stdin — never spins."""
    try:
        line = sys.stdin.readline()
    except (EOFError, KeyboardInterrupt):
        return None
    except Exception as e:
        logging.warning(f"[Panel] stdin read failed: {e}")
        return None
    if line == "":
        return None  # Ctrl+Z (Windows) / Ctrl+D (POSIX) / closed pipe
    return line


def panel_loop(ctx):
    _block([
        "",
        _s(DIM, "  [panel] Settings panel ready. Press Enter for the menu "
                "(? help, s status, q quit)."),
        "",
    ])
    while True:
        if ctx["open"]:
            _prompt()
        line = ctx["read"]()
        if line is None:
            _block(["", _s(DIM, "  [panel] stdin closed - settings panel off. "
                                "Conduit keeps running; Ctrl+C to stop it."), ""])
            return "eof"

        line = line.strip()
        if not ctx["open"]:
            ctx["open"] = True
            if not line:
                _block(menu_lines(ctx))
                continue

        action = handle_command(line, ctx)
        if action == "close":
            ctx["open"] = False
            _block(["", _s(DIM, "  [panel] Closed. Press Enter to reopen."), ""])
        elif action in ("quit", "eof"):
            return action


# ──────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────
def _stdin_is_console():
    """isatty() is not enough on Windows: the CRT reports every character device
    as a tty, so `< NUL` looks interactive. GetConsoleMode only succeeds on a real
    console input buffer, so it separates a console from NUL, a pipe or a file."""
    if not IS_WINDOWS:
        return True
    try:
        import ctypes
        import msvcrt
        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        mode = ctypes.c_uint32()
        return bool(ctypes.windll.kernel32.GetConsoleMode(
            ctypes.c_void_p(handle), ctypes.byref(mode)))
    except Exception as e:
        logging.debug(f"[Panel] Console probe failed, trusting isatty: {e}")
        return True


def panel_available():
    """Never in --mcp mode (stdin is the JSON-RPC transport) and never without a
    console. run_conduit only reaches this after the --mcp branch has returned."""
    if os.environ.get("CONDUIT_NO_PANEL"):
        return False
    stdin = getattr(sys, "stdin", None)
    if stdin is None or not hasattr(stdin, "isatty"):
        return False
    try:
        if not stdin.isatty():
            return False
    except Exception:
        return False
    return _stdin_is_console()


def start_panel(is_admin=False, mcp_config=None, gui_check=None):
    """Start the panel on a daemon thread. Returns the thread, or None if the
    terminal cannot support it. Never raises into the caller."""
    try:
        if not panel_available():
            logging.info("[Panel] No interactive TTY on stdin - settings panel disabled.")
            return None

        _STYLE["ansi"] = _enable_ansi()
        _STYLE["rule"] = "─" if _unicode_ok() else "-"

        ctx = make_context(is_admin=is_admin, mcp_config=mcp_config, gui_check=gui_check)

        def _run():
            try:
                panel_loop(ctx)
            except Exception as e:
                logging.error(f"[Panel] Settings panel stopped: {e}")

        thread = threading.Thread(target=_run, name="conduit-settings-panel", daemon=True)
        thread.start()
        return thread
    except Exception as e:
        logging.error(f"[Panel] Could not start settings panel: {e}")
        return None
