# Changelog

All notable changes to this project will be documented in this file.

## [2.1.0] - 2026-07-02

### Added
- **Command-line Arguments**: Added support for `--always-allow` and `--headless` flags to customize starting behaviour.
- **Headless Mode**: `--headless` flag starts Conduit without opening the web browser at launch, allowing it to run smoothly on remote server configurations (e.g., VPS). Implies `--always-allow`.
- **CLI Parameter Forwarding**: Updated launch scripts (`conduit.bat` and `conduit.sh`) to forward all trailing command line parameters directly to python execution.
- **GUI Icon Integration**: Integrated a custom logo (`conduit.png`) directly into the main Tkinter GUI approval dialogue header with a clean side-by-side layout (icon on left, text stacked on right).
- **GUI Window Decoration**: Completely hid the minimize and maximize window buttons on Windows using Win32 API window style flags to display a cleaner titlebar with only the close (X) button.
- **GUI Detection & Enforcement**: Added automated display environment detection at boot. If no GUI/screen is available (e.g., VPS over raw SSH), the script terminates cleanly with an instruction to use the `--headless` flag.

### Changed
- **Dashboard Disconnected Behavior**: Removed the automatic tab close attempt (`window.close()`) and the "Close Tab" button from the disconnected overlay as modern browsers block programmatic closing of tabs not opened via scripts.

## [2.0.0] - 2026-07-01

This release marks a complete rewrite and modularization of Conduit, evolving it from a single-file script to a robust, clean package architecture with major developer workflow enhancements.

### Added
- **Always Allow Mode**: Option to auto-approve subsequent commands in the active session. Features a red warning banner on the dashboard and double-confirmation safety prompts.
- **High-DPI GUI Support**: Enabled Windows DPI awareness via `ctypes`. Text, buttons, and borders now render at razor-sharp native resolution.
- **Clean JavaScript Separation**: Extracted all dashboard scripting logic into a separate `templates/dashboard.js` file, leaving `dashboard.html` purely layout-focused.
- **Auto-Close Web Tab**: The web dashboard automatically attempts to close the browser tab (`window.close()`) if the local Python server is shut down.
- **Disconnected Fallback Overlay**: Full-screen overlay alerting the user if the connection is lost and the tab cannot be automatically closed.
- **Custom Logo Integration**: Native support for custom pixel-art logos (`conduit.png`) with pixelated rendering properties to preserve sharp retro edges.
- **Silent Connection Closures**: Intercepted `ConnectionAbortedError` and socket reset exceptions to keep the terminal logs clean and free of backtrace spam.

### Changed
- **Modular Codebase**: Split the monolith python script into clean, domain-specific modules:
  - `run_conduit.py` (Main entry point)
  - `src/config.py` (Shell detection & configuration)
  - `src/dialogs.py` (Tkinter UI & fallbacks)
  - `src/engine.py` (Execution engine & queues)
  - `src/server.py` (HTTP Routing & APIs)
- **GUI Aesthetic Polish**: Refined colors to a clean enterprise palette (Deep Blue, Slate Gray, Burgundy Red) with regular font weights for a shifted native-like OS dialog feel.
- **Window Centering & Resizing**: Disabled window resize controls (Close-only title bar) and centered the window on the active monitor before drawing to prevent layout flicker.

### Removed
- Single-file monolithic python script structure.
- In-line scripting from the dashboard HTML layout.
