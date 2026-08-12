# Conduit

<p align="center">
  <img src="templates/conduit.png" width="128" alt="Conduit Logo">
</p>

**A human-approved admin channel for AI coding agents.**

Every AI coding assistant (Cursor, Codex, Claude Code, Antigravity, and others) runs inside a sandboxed terminal. That sandbox is intentional: it exists to prevent accidental damage. But it also means that when *you* want your AI to do real system-level work, there's no way to say "yes, go ahead" — even for a command you'd happily run yourself.

Inside the sandbox, your AI **cannot**:

- Install system-wide packages or software (`apt`, `brew`, `winget`, `msi`)
- Start, stop, or configure system services
- Write to protected system directories (`/etc`, `/usr/local`, `C:\Windows`, `C:\Program Files`)
- Run any command that requires `sudo` on Linux/macOS or UAC elevation on Windows
- Modify firewall rules, network interfaces, or DNS settings
- Manage user accounts or file permissions at the OS level

**Conduit gives you a way to say yes.**

It's a tiny Python process *you* start, with the privileges *you* grant it. The AI proposes a command; you see a GUI approval dialog for every single one, defaulting to No; you click Yes or No; the output goes back to the AI. Nothing runs that you didn't personally read and approve. Just:

```bash
python run_conduit.py
```

Your AI connects either over plain HTTP or as an **MCP server** — see [Connecting Your AI](#connecting-your-ai).

## How It Works

<p align="center">
  <img src="templates/conduit_flow.svg" width="860" alt="Conduit Architecture Diagram">
</p>

1. Start Conduit in an elevated terminal (or double-click `conduit.bat` on Windows).
2. Conduit prints a session token and opens the web dashboard in your browser.
3. Connect your agent, either way — paste the dashboard's prompt into the chat so the agent reads `http://127.0.0.1:40404/agent.md` and talks HTTP, or set it up once as an [MCP server](#option-1--mcp-recommended-for-claude-code-cursor-claude-desktop) and let it use the `run_command` tool directly.
4. The agent proposes a privileged command. It lands in Conduit's queue.
5. A dialog appears on your screen showing the exact command. It defaults to No.
6. You approve or deny. Output returns to the agent in structured JSON — or `DENIED`, and nothing ran.

<p align="center">
  <img src="templates/screenshot_approval_v2.png" width="560" alt="Conduit Approval Dialog">
</p>

## Quick Start

### Windows
Double-click `conduit.bat` (auto-elevates to Administrator) or:
```powershell
python run_conduit.py
```

### macOS / Linux
```bash
chmod +x conduit.sh
./conduit.sh
```

After launch, your browser opens at `http://127.0.0.1:40404/`. Copy the prompt and send it to your AI.

### Command-line Options

Conduit supports configuration flags to customize how the server runs:

* `--always-allow`: Auto-approves execution requests without prompt popups.
* `--headless`: Skips opening the dashboard browser tab and implies `--always-allow`. Use this for headless environments (like VPS or remote servers).
* `--mcp`: Runs as an MCP stdio bridge to the daemon. Your AI client spawns this; you don't run it by hand.
* `--mcp-config`: Prints the MCP config to paste into your AI client, then exits.

Example:
```bash
python run_conduit.py --headless
```

## Web Dashboard

Conduit hosts a local web dashboard at `http://127.0.0.1:40404/`. It shows:

- Live status (uptime, queue depth, platform)
- Current session token with one-click copy
- A "Copy Prompt" button you paste directly into your AI agent to activate Conduit

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|:----:|-------------|
| `GET` | `/` | No | Web dashboard |
| `GET` | `/agent.md` | No | AI agent integration guide (with live token) |
| `POST` | `/` | Yes | Execute a privileged command |
| `GET` | `/status` | No | Health check, uptime, queue depth |
| `GET` | `/shells` | No | Available shells on this machine |
| `GET` | `/mcp.json` | No | Ready-to-paste MCP client config |
| `GET` | `/history` | Yes | Last 50 executed commands |

### Executing a Command (`POST /`)

```json
{
  "command": "Get-Disk | Format-Table -AutoSize",
  "shell": "powershell",
  "cwd": "C:\\optional\\path",
  "env": { "MY_VAR": "value" }
}
```

Plain-text body (no JSON) also works and runs in the default shell.

### Response

```json
{
  "status": "SUCCESS",
  "request_id": "uuid-v4",
  "shell_used": "powershell",
  "exit_code": 0,
  "output": "(stdout)",
  "stderr": "(stderr if any)",
  "duration_ms": 142.5
}
```

Status values: `SUCCESS`, `ERROR`, `DENIED`

## Connecting Your AI

Conduit speaks two protocols at once. Both funnel into the same queue and the same approval dialog, so you can use whichever your agent supports — or both, from different agents, simultaneously.

### Option 1 — MCP (recommended for Claude Code, Cursor, Claude Desktop)

Conduit ships its own MCP server, so the agent gets a native `run_command` tool instead of having to hand-roll HTTP calls. Print the config:

```bash
python run_conduit.py --mcp-config
```

Paste the output into your client's MCP config, or for Claude Code:

```bash
claude mcp add conduit -- python /full/path/to/run_conduit.py --mcp
```

Then start Conduit normally (`python run_conduit.py`, elevated) whenever you want the channel live.

**How it fits together:** your AI client spawns `run_conduit.py --mcp` as a subprocess *inside its own unprivileged sandbox*. That bridge executes nothing itself — it forwards each call over localhost to the elevated Conduit daemon you started, which owns the approval dialog and the privileges. The bridge finds the current session token from `~/.conduit/session.json` automatically, so your MCP config keeps working across restarts even though the token rotates.

Tools exposed: `run_command` (approval-gated), `list_shells` and `get_status` (read-only, no dialog).

If Conduit isn't running, the bridge still loads and simply reports that fact when called — it won't break your client's startup.

### Option 2 — HTTP API

The simplest integration uses only Python stdlib:

```python
import urllib.request, json

CONDUIT_TOKEN = "paste-your-session-token-here"

def conduit(command, shell="powershell", cwd=None, env=None):
    payload = {"command": command, "shell": shell}
    if cwd: payload["cwd"] = cwd
    if env: payload["env"] = env
    req = urllib.request.Request(
        "http://127.0.0.1:40404/",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CONDUIT_TOKEN}"
        },
        method="POST"
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))
```

Or have the AI visit `http://127.0.0.1:40404/agent.md`, which serves a fully self-contained guide with the live token already embedded.

## Security Design

| Property | Detail |
|----------|--------|
| **Network scope** | Binds to `127.0.0.1` only, never exposed to external networks |
| **Human approval** | Every command requires an explicit GUI click before it runs |
| **Default deny** | The dialog defaults to No, approval is always an active choice |
| **60-second timeout** | Unanswered prompts are automatically denied |
| **Token auth** | Each session generates a fresh UUID token, only scripts that know it can submit commands |
| **No persistence** | Token and history vanish when Conduit is closed |
| **Thin MCP bridge** | The MCP subprocess executes nothing itself — it only forwards to the daemon, so it cannot skip the approval dialog |
| **Session file** | Token is published to `~/.conduit/session.json` (owner-only, `0600`) and deleted on shutdown |

## Requirements

- **Python 3.8+** (standard library only, no `pip install` needed)
- On Windows: `tkinter` is included with the official Python installer
- On Linux: `tkinter` via `sudo apt install python3-tk` (or `zenity` as fallback)
- On macOS: `tkinter` is included; `osascript` used as fallback dialog

