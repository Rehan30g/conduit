# Changelog

All notable changes to this project will be documented in this file.

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
