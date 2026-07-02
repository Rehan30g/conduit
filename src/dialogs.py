import os
import sys
import time
import subprocess
import shutil
import logging
from src.config import IS_WINDOWS

def _truncate(text, limit):
    return text if len(text) <= limit else text[:limit - 1] + "…"

# Enable High-DPI awareness on Windows to prevent blurriness (ensures sharp rendering)
if IS_WINDOWS:
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

class ApprovalDialog:
    def __init__(self, command, shell, cwd=None, env=None, timeout=60):
        self.command = command
        self.shell = shell
        self.cwd = cwd
        self.env = env
        self.timeout = timeout
        self.result = False

        import tkinter as tk
        from tkinter import font as tkfont

        self.root = tk.Tk()
        self.root.title("Conduit - Authorization Request")
        self.root.configure(bg="#ffffff")
        
        # Hide the window while calculating layout to prevent top-left flash and ensure centering
        self.root.withdraw()
        
        # Use compact default dimensions suitable for standard commands
        w = 620
        h = 320
        self.root.minsize(500, 260)
        self.root.update_idletasks()
        
        # Center the window on the active screen
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f'{w}x{h}+{x}+{y}')
        
        # Disable minimize/maximize buttons
        self.root.resizable(False, False)
        if IS_WINDOWS:
            try:
                import ctypes
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, -16)  # GWL_STYLE
                style &= ~0x00020000  # WS_MINIMIZEBOX
                style &= ~0x00010000  # WS_MAXIMIZEBOX
                ctypes.windll.user32.SetWindowLongW(hwnd, -16, style)
                ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)  # SWP_FRAMECHANGED
            except Exception:
                pass

        # Show window now that geometry is applied
        self.root.deiconify()
        
        self.root.attributes("-topmost", True)
        self.root.focus_force()

        tf = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        bf = tkfont.Font(family="Segoe UI", size=10)
        cf = tkfont.Font(family="Consolas", size=10)

        # Load the icon image
        from src.config import TEMPLATES_DIR
        icon_path = os.path.join(TEMPLATES_DIR, "conduit.png")
        self.icon_image = None
        if os.path.exists(icon_path):
            try:
                # Tkinter PhotoImage can load PNG files natively in Python 3
                full_img = tk.PhotoImage(file=icon_path)
                # Subsample 512x512 to ~51x51 (512 / 10 = 51)
                self.icon_image = full_img.subsample(10, 10)
            except Exception as e:
                logging.warning(f"Could not load dialog icon: {e}")

        # 1. Header Frame (left-aligned container for Icon and stacked Text)
        header_frame = tk.Frame(self.root, bg="#ffffff")
        header_frame.pack(fill=tk.X, padx=25, pady=(20, 5))

        if self.icon_image:
            icon_label = tk.Label(header_frame, image=self.icon_image, bg="#ffffff", bd=0)
            icon_label.pack(side=tk.LEFT, padx=(0, 15), anchor="nw")

        # Text container for vertical stacking next to the icon
        text_container = tk.Frame(header_frame, bg="#ffffff")
        text_container.pack(side=tk.LEFT, fill=tk.Y, expand=True, anchor="nw")

        title_label = tk.Label(text_container,
                               text="AI Agent Command Authorization Request",
                               fg="#1f2937", bg="#ffffff", font=tf, bd=0, anchor="w")
        title_label.pack(fill=tk.X, anchor="w", pady=(2, 4))

        # 2. Info Label (now stacked vertically next to the icon)
        self.info = tk.Label(text_container,
                             text=f"Shell: {self.shell} | Auto-denying in {self.timeout}s...",
                             fg="#4b5563", bg="#ffffff", font=bf, bd=0, anchor="w")
        self.info.pack(fill=tk.X, anchor="w")

        # 2b. Surface cwd/env overrides so the user can spot a request that
        # is trying to run a plain-looking command under a tampered
        # environment (e.g. a hijacked PATH or LD_PRELOAD). Truncated to a
        # fixed length: the window is non-resizable, and a request with many
        # (or long) env keys must not be able to grow this label enough to
        # push the command text out of view.
        details = []
        if self.cwd:
            details.append(f"cwd: {_truncate(self.cwd, 80)}")
        if self.env:
            details.append(f"env overrides: {_truncate(', '.join(sorted(self.env.keys())), 120)}")
        if details:
            tk.Label(text_container, text=" | ".join(details),
                     fg="#b45309", bg="#ffffff", font=bf, bd=0, anchor="w",
                     wraplength=520, justify=tk.LEFT
            ).pack(fill=tk.X, anchor="w", pady=(2, 0))

        # 3. Action Buttons Frame (packed from BOTTOM first to prevent command frame overlap)
        bf2 = tk.Frame(self.root, bg="#ffffff")
        bf2.pack(fill=tk.X, pady=15, side=tk.BOTTOM)

        # Left: Approve (Deep Corporate Blue)
        tk.Button(bf2, text="Approve (Yes)", bg="#1e3a8a", fg="#ffffff",
                  font=bf, activebackground="#2563eb", activeforeground="#ffffff",
                  width=14, command=self.approve, cursor="hand2", bd=0, padx=5, pady=5
        ).pack(side=tk.LEFT, padx=30)

        # Center: Always Allow (Muted Burgundy/Red)
        tk.Button(bf2, text="⚠️ Always Allow", bg="#991b1b", fg="#ffffff",
                  font=bf, activebackground="#be123c", activeforeground="#ffffff",
                  width=14, command=self.always_allow, cursor="hand2", bd=0, padx=5, pady=5
        ).pack(side=tk.LEFT, padx=30)

        # Right: Deny (Default Focused Clean Slate Gray)
        nb = tk.Button(bf2, text="Deny (No)", bg="#e5e7eb", fg="#374151",
                       font=bf, activebackground="#d1d5db", activeforeground="#374151",
                       width=14, command=self.deny, cursor="hand2", bd=0, padx=5, pady=5)
        nb.pack(side=tk.RIGHT, padx=30)
        nb.focus_set()

        # 4. Command Area Frame (occupies all remaining space in the middle, height limited to 6 lines by default)
        frame = tk.Frame(self.root, bg="#e5e7eb", bd=1)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        sb = tk.Scrollbar(frame)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        
        ta = tk.Text(frame, wrap=tk.WORD, yscrollcommand=sb.set,
                     bg="#f9fafb", fg="#111827", font=cf,
                     bd=0, padx=12, pady=12, height=6)
        ta.insert(tk.END, self.command)
        ta.config(state=tk.DISABLED)
        ta.pack(fill=tk.BOTH, expand=True)
        sb.config(command=ta.yview)

        self.remaining = self.timeout
        self.countdown()
        self.root.protocol("WM_DELETE_WINDOW", self.deny)
        self.root.mainloop()

    def countdown(self):
        if self.remaining <= 0:
            self.deny()
        else:
            self.info.config(text=f"Shell: {self.shell} | Auto-denying in {self.remaining}s...")
            self.remaining -= 1
            self.root.after(1000, self.countdown)

    def approve(self):
        self.result = True; self.root.destroy()

    def deny(self):
        self.result = False; self.root.destroy()

    def always_allow(self):
        from tkinter import messagebox
        # Peringatan Merah (Dangerous alert confirmation dialog)
        confirm = messagebox.askyesno(
            "⚠️ CRITICAL SECURITY WARNING",
            "You are about to enable ALWAYS ALLOW for this session.\n\n"
            "This will allow the AI agent to execute administrative/root commands "
            "WITHOUT showing this authorization popup again.\n\n"
            "An AI agent could run destructive commands (like formatting disks or deleting system files) "
            "silently in the background.\n\n"
            "Are you absolutely sure you want to proceed?",
            icon="warning"
        )
        if confirm:
            self.result = "ALWAYS"
            self.root.destroy()


def run_gui_prompt(command, shell, cwd=None, env=None, timeout=60):
    try:
        import tkinter
        return ApprovalDialog(command, shell, cwd, env, timeout).result
    except Exception as e:
        logging.warning(f"Tkinter unavailable ({e}). Trying platform fallback...")
        return run_fallback_prompt(command, shell, cwd, env, timeout)


def run_fallback_prompt(command, shell, cwd=None, env=None, timeout=60):
    details = f"Shell: {shell}"
    if cwd:
        details += f"\ncwd: {cwd}"
    if env:
        details += f"\nenv overrides: {', '.join(sorted(env.keys()))}"

    if sys.platform == "darwin":
        try:
            esc = command.replace('"', '\\"').replace('\n', '\\r')
            details_esc = details.replace('"', '\\"').replace('\n', '\\r')
            script = (
                f'display dialog "Conduit Authorization\\r\\r{details_esc}\\rCommand:\\r{esc}" '
                f'with title "Conduit" buttons {{"No","Yes"}} default button "No" giving up after {timeout}'
            )
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            return "returned:Yes" in r.stdout
        except Exception:
            pass

    if sys.platform.startswith("linux") and shutil.which("zenity"):
        try:
            r = subprocess.run([
                "zenity", "--question",
                "--title=Conduit Authorization",
                f"--text=Authorize command?\n\n{details}\n\n{command}",
                f"--timeout={timeout}"
            ])
            return r.returncode == 0
        except Exception:
            pass

    return run_terminal_fallback(command, shell, cwd, env, timeout)


def run_terminal_fallback(command, shell, cwd, env, timeout):
    print("\n" + "="*70)
    print("[!] CONDUIT AUTHORIZATION REQUEST (Terminal Fallback)")
    print(f"Shell: {shell}")
    if cwd:
        print(f"cwd: {cwd}")
    if env:
        print(f"env overrides: {', '.join(sorted(env.keys()))}")
    print("-" * 70)
    print(command)
    print("-" * 70)
    print("WARNING: Selecting 'a' (Always Allow) will bypass all prompts!")
    print(f"Authorize execution? [y/N/a] (a = Always Allow): ", end="", flush=True)

    choice = "n"
    if IS_WINDOWS:
        import msvcrt
        t0 = time.time(); chars = []
        while time.time() - t0 < timeout:
            if msvcrt.kbhit():
                c = msvcrt.getwche()
                if c in ('\r', '\n'):
                    print(); break
                chars.append(c)
            time.sleep(0.1)
        choice = "".join(chars).strip().lower()
    else:
        import select
        rlist, _, _ = select.select([sys.stdin], [], [], timeout)
        if rlist:
            choice = sys.stdin.readline().strip().lower()
        else:
            print("\n[Timeout] Auto-denied.")
            choice = "n"

    if choice in ('y', 'yes'):
        return True
    elif choice == 'a':
        print("\n" + "!"*70)
        print("⚠️  CRITICAL SECURITY WARNING (ALWAYS ALLOW)")
        print("This allows the AI agent to run ANY command as Administrator without asking!")
        print("Are you sure? [y/N]: ", end="", flush=True)
        confirm_choice = "n"
        if IS_WINDOWS:
            chars = []
            while True:
                if msvcrt.kbhit():
                    c = msvcrt.getwche()
                    if c in ('\r', '\n'):
                        print(); break
                    chars.append(c)
                time.sleep(0.1)
            confirm_choice = "".join(chars).strip().lower()
        else:
            rlist, _, _ = select.select([sys.stdin], [], [], 30)
            if rlist:
                confirm_choice = sys.stdin.readline().strip().lower()
        if confirm_choice in ('y', 'yes'):
            return "ALWAYS"
    return False
