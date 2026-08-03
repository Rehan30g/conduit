# Contributing to Conduit

Thank you for your interest in contributing to **Conduit**! 

Conduit provides a human-approved admin execution bridge for AI coding agents (Claude Code, Cursor, Antigravity, and others). We welcome contributions from the community—whether that's reporting bugs, improving documentation, submitting feature requests, or opening pull requests.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Design Principles](#design-principles)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Repository Structure](#repository-structure)
- [Development Workflow](#development-workflow)
  - [Branch Naming](#branch-naming)
  - [Running Locally](#running-locally)
- [Architecture & Core Concepts](#architecture--core-concepts)
  - [Dual Protocol Support](#dual-protocol-support)
  - [Security Model](#security-model)
- [Coding Guidelines](#coding-guidelines)
- [Testing Changes](#testing-changes)
- [Submitting Pull Requests](#submitting-pull-requests)

---

## Code of Conduct

We aim to foster an open, welcoming, and inclusive community. Please ensure all interactions are respectful, constructive, and free of harassment or toxicity.

---

## Design Principles

When contributing to Conduit, keep the following core design principles in mind:

1. **Zero External Dependencies**: Conduit runs strictly on **Python 3.8+ standard library**. Do **NOT** add third-party Python package dependencies (e.g. `pip install ...`). This guarantees instant, zero-setup execution on any system.
2. **Security & Human-in-the-Loop First**: Every command execution must default to requiring human approval. Never weaken authorization dialogs, token checks, or network scoping (`127.0.0.1` binding).
3. **Cross-Platform Compatibility**: Conduit runs on Windows, macOS, and Linux. Always test changes across platform boundaries (especially GUI fallbacks like `tkinter`, `zenity`, and `osascript`).
4. **Lightweight & Fast**: Keep startup fast, RAM footprint minimal, and code clean and maintainable.

---

## Getting Started

### Prerequisites

- **Python 3.8** or higher.
- **GUI Toolkit**:
  - **Windows**: Included with standard Python installer (`tkinter`).
  - **macOS**: Included with system/Homebrew Python; fallback via `osascript`.
  - **Linux**: `python3-tk` (e.g., `sudo apt install python3-tk`) or `zenity`.

### Repository Structure

```
├── run_conduit.py         # Main CLI entry point & launcher flags
├── conduit.bat            # Windows auto-elevated helper script
├── conduit.sh             # Linux/macOS launcher script
├── CHANGELOG.md           # Release history
├── LICENSE                # MIT License
├── README.md              # Main project documentation
└── src/
    ├── config.py          # Host, port (40404), platform flags, and global configs
    ├── dialogs.py         # GUI authorization popups (Tkinter, Zenity, AppleScript)
    ├── engine.py          # Command queue worker and execution subprocess handler
    ├── mcp_server.py      # MCP (Model Context Protocol) stdio bridge implementation
    ├── server.py          # HTTP server implementation & web dashboard endpoints
    ├── session.py         # Token management and ~/.conduit/session.json persistence
    └── settings_panel.py  # Embedded dashboard & settings GUI panel
```

---

## Development Workflow

### Branch Naming

Use clear, descriptive prefix conventions for feature branches:

- `feat/<feature-name>` (e.g., `feat/mcp-transport`)
- `fix/<bug-description>` (e.g., `fix/token-cleanup`)
- `docs/<doc-update>` (e.g., `docs/contributing-guide`)
- `refactor/<component>` (e.g., `refactor/server-handler`)

### Running Locally

To run Conduit in standard mode:

```bash
python run_conduit.py
```

To test CLI options during development:

```bash
# Test headless mode (auto-approves, no GUI)
python run_conduit.py --headless

# Test always-allow mode (GUI popups bypassed)
python run_conduit.py --always-allow

# Print MCP configuration JSON
python run_conduit.py --mcp-config

# Test MCP stdio bridge server mode
python run_conduit.py --mcp
```

---

## Architecture & Core Concepts

### Dual Protocol Support

Conduit serves two integration pathways simultaneously:

1. **HTTP REST API** (`http://127.0.0.1:40404/`):
   - `GET /` — Interactive web dashboard.
   - `POST /` — Execute command (requires Bearer token authentication).
   - `GET /agent.md` — AI integration instruction prompt.
   - `GET /status`, `GET /shells`, `GET /history`, `GET /mcp.json`.

2. **MCP (Model Context Protocol)**:
   - Launched via `run_conduit.py --mcp` as a stdio process.
   - Proxy bridge reading token from `~/.conduit/session.json` and delegating execution requests to the running HTTP daemon.

### Security Model

- **Localhost Only**: Server strictly binds to `127.0.0.1`.
- **Ephemeral Session Tokens**: Fresh UUID generated on launch; token is published to `~/.conduit/session.json` (`0600` permissions) and cleaned up on exit.
- **Default Deny**: Authorization dialogs default to "No". Unanswered popups time out after 60 seconds.

---

## Coding Guidelines

- **PEP 8**: Follow standard Python formatting conventions (4 spaces indentation, clean naming conventions).
- **Type Annotations**: Use type hints where appropriate to improve code clarity.
- **Error Handling**: Handle OS-level exceptions gracefully (e.g., missing GUI, permission denied, process timeouts).
- **No Heavy Dependencies**: Rely on `sys`, `os`, `json`, `http.server`, `urllib`, `threading`, `subprocess`, `ctypes`, and `tkinter`.

---

## Testing Changes

Before opening a pull request, ensure you have tested your changes:

1. **CLI Flag Verification**:
   - Verify `--headless`, `--always-allow`, and `--mcp-config` behave as expected.
2. **GUI / Popup Verification**:
   - Verify approval popups render correctly on your operating system.
   - Verify timeout and "Deny" paths work without crashing.
3. **API & MCP Verification**:
   - Test command execution through `POST /` with token authentication.
   - Verify MCP tool calls (`run_command`, `list_shells`, `get_status`).
4. **Clean Exit Verification**:
   - Stop Conduit (Ctrl+C or window close) and ensure `~/.conduit/session.json` is deleted properly.

---

## Submitting Pull Requests

1. **Fork the Repository**: Create your fork on GitHub.
2. **Create a Topic Branch**: `git checkout -b feat/my-new-feature`
3. **Commit Your Changes**: Make clear, atomic commits with concise commit messages.
4. **Push to Your Fork**: `git push origin feat/my-new-feature`
5. **Open a Pull Request**:
   - Provide a clear title and description explaining what changed and why.
   - Reference any related issues (e.g., `Fixes #12`).
   - Mention the platforms tested (Windows, macOS, Linux).

---

Thank you for helping make Conduit better for everyone!
