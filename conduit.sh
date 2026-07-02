#!/bin/bash
# Conduit - Launch script for Unix systems (Linux/macOS)

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Check if python3 is available
if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
else
    echo "Error: Python is not installed or not in PATH."
    exit 1
fi

# Check for root privileges
if [ "$EUID" -ne 0 ]; then
    echo "🔒 Requesting root privileges via sudo..."
    sudo "$PYTHON_CMD" "$SCRIPT_DIR/run_conduit.py" "$@"
else
    "$PYTHON_CMD" "$SCRIPT_DIR/run_conduit.py" "$@"
fi
