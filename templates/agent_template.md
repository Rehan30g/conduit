# Conduit — AI Agent Integration Guide

You are reading this because the developer has enabled **Conduit**, a local admin execution bridge.
This allows you to run commands with **full Administrator/root privileges**, bypassing the sandbox
restrictions imposed by your AI coding environment.

> **Human-in-the-loop**: Every command you send must be approved by the developer via a GUI dialog
> before it executes. You will not be able to run anything without their explicit click.

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
