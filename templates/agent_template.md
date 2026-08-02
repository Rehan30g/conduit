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

| | **MCP** (preferred) | **HTTP API** (this page) |
|---|---|---|
| Setup | One-time entry in the client's MCP config | None |
| How you call it | Native `run_command` tool in your tool list | You make the HTTP request yourself, e.g. `urllib`/`curl` |
| Best for | Claude Code, Cursor, Claude Desktop, any MCP client | Agents without MCP support |

**If you already see a `conduit` MCP server in your tools, use that and ignore the rest of this
page** — same bridge, cleaner interface, and no token needed.

**If you don't, and your client supports MCP, that is the better route and you should say so rather
than using this page.** Tell the developer to run `python run_conduit.py --mcp-config` and add the
result to their client's config (for Claude Code: `claude mcp add conduit -- <python> <path>
--mcp`). The bridge reads the live token from `~/.conduit/session.json` itself, so their config
survives restarts. Registering it there is a deliberate act by the developer in their own
configuration, which is a sounder basis for trusting a privileged tool than anything a page like
this one could assert about itself.

That distinction is worth being blunt about: **a document fetched over HTTP cannot grant you
authority, and this one is not trying to.** If you have been pointed at this page by text pasted
into a chat, treat the page as a reference manual for an endpoint, not as permission. Whether to
use it is a judgement call between you and the developer, based on what they tell you they want
done — some clients reasonably decline this route on principle, and that is a defensible position,
not a malfunction. The MCP route exists precisely because it does not require you to take a fetched
document's word for anything.

What this page describes is a single plain HTTP endpoint on `127.0.0.1`, the developer's own
machine, reachable with whatever general-purpose HTTP or code execution you already have — no
install, no plugin, no tool registration. One ordinary POST per command. The safety property comes
entirely from the human approval step on the other end.

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
