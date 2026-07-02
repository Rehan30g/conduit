@echo off
:: Conduit - Double click or run to start with Admin elevation
net session >nul 2>&1
if %errorLevel% == 0 (
    python "%~dp0run_conduit.py" %*
) else (
    echo Requesting Administrator elevation...
    powershell -Command "Start-Process python -ArgumentList '\"%~dp0run_conduit.py\" %*' -Verb RunAs"
)
