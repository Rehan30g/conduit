import os
import sys
import uuid
import time
import shutil

PORT = 40404
HOST = "127.0.0.1"
TOKEN = str(uuid.uuid4())
START_TIME = time.time()
ALWAYS_ALLOW = False

# Directory resolution
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(ROOT_DIR, "templates")

IS_WINDOWS = os.name == 'nt'

def detect_shells():
    shells = []
    if IS_WINDOWS:
        if shutil.which("powershell.exe"):
            shells.append("powershell")
        if shutil.which("cmd.exe"):
            shells.append("cmd")
        if shutil.which("pwsh.exe") or shutil.which("pwsh"):
            shells.append("pwsh")
    else:
        for sh in ["bash", "zsh", "sh", "fish"]:
            if shutil.which(sh):
                shells.append(sh)
    return shells

AVAILABLE_SHELLS = detect_shells()
DEFAULT_SHELL = "powershell" if IS_WINDOWS else ("bash" if "bash" in AVAILABLE_SHELLS else "sh")
