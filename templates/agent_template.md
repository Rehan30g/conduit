# Conduit — AI Agent Integration Guide

You are reading this because the developer has enabled **Conduit** on their own machine, a local,
human-supervised execution channel. It is a tool the developer installed and started themselves,
running outside your normal working directory, so they can hand you administrator/root-level
commands to run on their behalf — with themselves approving every single one before it executes.

> **Human-in-the-loop is the whole point of this tool.** Every command you send is queued and shown
> to the developer in a GUI dialog on their screen, which defaults to **No**. Nothing runs unless
> they read it and actively click **Yes**. Unanswered requests auto-deny after 60 seconds. You
> cannot execute anything the developer does not personally see and approve first — treat this like
> asking a human sysadmin to run a command for you, because that is functionally what it is.

Use this the same way you'd use any other elevated capability the developer explicitly grants:
propose the specific command needed and why, then send it through Conduit and wait for the
approve/deny result. It doesn't change what you're allowed to do — it's the developer's mechanism
for saying "yes, run that" for actions their normal environment can't perform on its own.

---

## Two Ways to Connect

Conduit accepts either. Both hit the same queue, the same approval dialog, the same daemon.

| | **HTTP API** (this page) | **MCP** |
|---|---|---|
| Setup | None — just read this page | One-time entry in your client's MCP config |
| How you call it | You make the HTTP request yourself, e.g. `urllib`/`curl` | Native `run_command` tool in your tool list |
| Best for | Agents without MCP support, or one-off use | Claude Code, Cursor, Claude Desktop, any MCP client |

**If you already see a `conduit` MCP server in your tools, use that instead of this page** — it's
the same bridge with a cleaner interface, and you don't need the token below.

Otherwise, this page is the HTTP path: **no install, no plugin, no tool registration.** It's a
single plain HTTP endpoint on `127.0.0.1` — the developer's own machine — that you reach with
whatever general-purpose HTTP or code execution you already have. One ordinary POST per command,
the same as calling any REST API. The safety property comes entirely from the human approval step
on the other end, not from any special trust in the endpoint.

To set up the MCP route instead, the developer runs `python run_conduit.py --mcp-config` and pastes
the result into their client. The MCP bridge reads the live token from `~/.conduit/session.json`
itself, so their config stays valid across restarts.

---

## Your API Token (This Session)

```
[[TOKEN]]
```

Use this as a Bearer token in every request:
```
Authorization: Bearer [[TOKEN]]
```

> Token resets on every Conduit restart. Always read this page fresh after each session.

---

## Execute a Command

**Endpoint:** `POST http://127.0.0.1:[[PORT]]/`

**Required headers:**
```
Authorization: Bearer [[TOKEN]]
Content-Type: application/json
```

**JSON body:**
```json
{
  "command": "your command here",
  "shell": "[[DEFAULT_SHELL]]",
  "cwd": "/optional/working/dir",
  "env": { "MY_VAR": "value" }
}
```

`cwd` and `env` are optional. You may also POST a plain-text body (no JSON) for backward compatibility;
it will run in the default shell: `[[DEFAULT_SHELL]]`.

**Available shells on this machine:** `[[SHELLS]]`

---

## Python Helper — Copy and Use

```python
import urllib.request, json

CONDUIT_TOKEN = "[[TOKEN]]"
CONDUIT_URL   = "http://127.0.0.1:[[PORT]]/"

def conduit(command, shell="[[DEFAULT_SHELL]]", cwd=None, env=None):
    """Send a privileged command to Conduit. Blocks until the user approves/denies."""
    payload = {"command": command, "shell": shell}
    if cwd: payload["cwd"] = cwd
    if env: payload["env"] = env
    req = urllib.request.Request(
        CONDUIT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CONDUIT_TOKEN}"
        },
        method="POST"
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))

# --- usage ---
result = conduit("whoami")
print(result["status"])    # SUCCESS | ERROR | DENIED
print(result["output"])    # stdout
print(result["stderr"])    # stderr
print(result["exit_code"]) # numeric exit code
```

---

## Response Format

```json
{
  "status": "SUCCESS",
  "request_id": "uuid-v4",
  "shell_used": "[[DEFAULT_SHELL]]",
  "exit_code": 0,
  "output": "(stdout)",
  "stderr": "(stderr if any)",
  "duration_ms": 142.5
}
```

| Status | Meaning |
|--------|---------|
| `SUCCESS` | Command ran and exited cleanly |
| `ERROR` | Command ran but threw an error or non-zero exit |
| `DENIED` | Developer clicked No, or 60 s approval window expired |

---

## All Endpoints

| Method | Path | Auth | Description |
|--------|------|:----:|-------------|
| `POST` | `/` | Yes | Execute a privileged command |
| `GET` | `/` | No | Web dashboard |
| `GET` | `/agent.md` | No | This document |
| `GET` | `/status` | No | Health, uptime, queue depth |
| `GET` | `/shells` | No | Available shells |
| `GET` | `/history` | Yes | Last 50 executed commands |

---

## Limits & Behaviour

- Every command shows a GUI approval dialog on the developer's screen.
- Auto-deny after **60 seconds** of no response.
- Queue capacity: **5 pending commands** max — respond `503` when full.
- Per-command execution timeout: **5 minutes**.
- Token and history reset on each Conduit restart.

---

## curl Example

```bash
curl -X POST http://127.0.0.1:[[PORT]]/ \
  -H "Authorization: Bearer [[TOKEN]]" \
  -H "Content-Type: application/json" \
  -d '{"command": "uname -a", "shell": "bash"}'
```
