import os
import sys
import time
import subprocess
import shutil
import logging
from src.config import IS_WINDOWS

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

# ---------------------------------------------------------------------------
# Design tokens — light "security console" theme
# ---------------------------------------------------------------------------
UI = {
    "bg":           "#ffffff",  # window background
    "surface":      "#eef2f7",  # secondary button / chips
    "surface_hi":   "#e2e8f0",  # secondary button hover
    "surface_dn":   "#cbd5e1",  # secondary button pressed
    "code_bg":      "#f8fafc",  # command block background
    "border":       "#dbe3ec",  # card borders
    "text":         "#0f172a",  # primary text
    "text_dim":     "#475569",  # secondary text
    "text_faint":   "#94a3b8",  # captions / hints
    "code_fg":      "#1e293b",  # command text
    "accent":       "#2563eb",  # primary button
    "accent_hi":    "#3b82f6",  # primary button hover
    "accent_dn":    "#1d4ed8",  # primary button pressed
    "danger":       "#dc2626",
    "danger_hi":    "#ef4444",
    "danger_btn":   "#dc2626",
    "danger_btn_hi": "#ef4444",
    "warn":         "#d97706",
    "grad_a":       "#6366f1",  # timer stripe gradient start (indigo)
    "grad_b":       "#06b6d4",  # timer stripe gradient end (cyan)
    "pill_bg":      "#dbeafe",
    "pill_fg":      "#1d4ed8",
    "focus":        "#2563eb",
}


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _blend(c1, c2, t):
    a, b = _hex_to_rgb(c1), _hex_to_rgb(c2)
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    """Draw a rounded rectangle as a smoothed polygon on a Canvas."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
           x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


def _pick_font(families, candidates, fallback):
    for c in candidates:
        if c in families:
            return c
    return fallback


class ApprovalDialog:
    def __init__(self, command, shell, timeout=60):
        self.command = command
        self.shell = shell
        self.timeout = timeout
        self.result = False
        self._closed = False

        import tkinter as tk
        from tkinter import font as tkfont
        self._tk = tk

        self.root = tk.Tk()
        self.root.title("Conduit — Authorization Request")
        self.root.configure(bg=UI["bg"])

        # Hide the window while calculating layout to prevent top-left flash and ensure centering
        self.root.withdraw()

        w, h = 680, 430
        self.root.minsize(560, 360)
        self.root.update_idletasks()

        # Center the window on the active screen
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f'{w}x{h}+{x}+{y}')
        self.root.resizable(False, False)

        # Windows chrome: dark title bar + remove minimize/maximize buttons
        if IS_WINDOWS:
            try:
                import ctypes
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, -16)  # GWL_STYLE
                style &= ~0x00020000  # WS_MINIMIZEBOX
                style &= ~0x00010000  # WS_MAXIMIZEBOX
                ctypes.windll.user32.SetWindowLongW(hwnd, -16, style)
                light = ctypes.c_int(0)
                for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (20; 19 on older Win10)
                    if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                            hwnd, attr, ctypes.byref(light), 4) == 0:
                        break
                # Windows 11: force a light caption bar with dark title text
                # (COLORREF is 0x00BBGGRR)
                caption = ctypes.c_int(0x00FFFFFF)   # white bar
                text_col = ctypes.c_int(0x001A170F)  # near-slate text
                ctypes.windll.dwmapi.DwmSetWindowAttribute(  # DWMWA_CAPTION_COLOR
                    hwnd, 35, ctypes.byref(caption), 4)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(  # DWMWA_TEXT_COLOR
                    hwnd, 36, ctypes.byref(text_col), 4)
                ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)  # SWP_FRAMECHANGED
            except Exception:
                pass

        # Fonts (with graceful fallbacks per platform)
        families = set(tkfont.families())
        sans = _pick_font(families, ["Segoe UI Variable Text", "Segoe UI", "SF Pro Text",
                                     "Helvetica Neue", "DejaVu Sans"], "TkDefaultFont")
        mono = _pick_font(families, ["Cascadia Mono", "Consolas", "SF Mono",
                                     "JetBrains Mono", "DejaVu Sans Mono"], "TkFixedFont")
        f_title = tkfont.Font(family=sans, size=14, weight="bold")
        f_sub = tkfont.Font(family=sans, size=10)
        f_caption = tkfont.Font(family=sans, size=8, weight="bold")
        f_timer = tkfont.Font(family=sans, size=16, weight="bold")
        f_btn = tkfont.Font(family=sans, size=10, weight="bold")
        f_link = tkfont.Font(family=sans, size=9)
        self._f_link = f_link
        f_code = tkfont.Font(family=mono, size=10)
        self._f_btn = f_btn

        # Load the icon image (window icon + header badge)
        from src.config import TEMPLATES_DIR
        icon_path = os.path.join(TEMPLATES_DIR, "conduit.png")
        self.icon_image = None
        if os.path.exists(icon_path):
            try:
                full_img = tk.PhotoImage(file=icon_path)
                self._app_icon = full_img
                self.root.iconphoto(False, full_img)
                # Subsample 512x512 down to ~43x43 for the header badge
                self.icon_image = full_img.subsample(12, 12)
            except Exception as e:
                logging.warning(f"Could not load dialog icon: {e}")

        # -------------------------------------------------------------------
        # 1. Timer stripe — a gradient bar across the top that drains as the
        #    auto-deny countdown elapses (turns amber, then red, when low)
        # -------------------------------------------------------------------
        self._stripe_w = w
        self.stripe = tk.Canvas(self.root, height=5, bg=UI["bg"],
                                highlightthickness=0, bd=0)
        self.stripe.pack(fill=tk.X, side=tk.TOP)
        for px in range(0, w, 2):
            c = _blend(UI["grad_a"], UI["grad_b"], px / max(w - 1, 1))
            self.stripe.create_line(px, 0, px, 5, fill=c, width=2)
        self._stripe_tint = self.stripe.create_rectangle(
            0, 0, w, 5, fill=UI["warn"], outline="", state="hidden")
        self._stripe_cover = self.stripe.create_rectangle(
            w, 0, w, 5, fill=UI["bg"], outline="")

        # -------------------------------------------------------------------
        # 2. Header — icon badge, title/subtitle, countdown readout at right
        # -------------------------------------------------------------------
        header = tk.Frame(self.root, bg=UI["bg"])
        header.pack(fill=tk.X, padx=26, pady=(20, 14))

        if self.icon_image:
            tk.Label(header, image=self.icon_image, bg=UI["bg"], bd=0
                     ).pack(side=tk.LEFT, padx=(0, 14), anchor="n")

        titles = tk.Frame(header, bg=UI["bg"])
        titles.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, anchor="n")
        tk.Label(titles, text="Authorization Request",
                 fg=UI["text"], bg=UI["bg"], font=f_title, bd=0, anchor="w"
                 ).pack(fill=tk.X, anchor="w")
        tk.Label(titles,
                 text="An AI agent is requesting permission to execute a command.",
                 fg=UI["text_dim"], bg=UI["bg"], font=f_sub, bd=0, anchor="w"
                 ).pack(fill=tk.X, anchor="w", pady=(3, 0))

        timer_box = tk.Frame(header, bg=UI["bg"])
        timer_box.pack(side=tk.RIGHT, anchor="n", padx=(14, 0))
        self.timer_value = tk.Label(timer_box, text=f"{self.timeout}s",
                                    fg=UI["text_dim"], bg=UI["bg"],
                                    font=f_timer, bd=0)
        self.timer_value.pack(anchor="e")
        tk.Label(timer_box, text="AUTO-DENY", fg=UI["text_faint"],
                 bg=UI["bg"], font=f_caption, bd=0).pack(anchor="e")

        # -------------------------------------------------------------------
        # 3. Footer — de-emphasized "always allow" link + Deny / Approve
        #    (packed before the command card so the card absorbs extra space)
        # -------------------------------------------------------------------
        footer = tk.Frame(self.root, bg=UI["bg"])
        footer.pack(fill=tk.X, side=tk.BOTTOM, padx=26, pady=(6, 18))

        self._always_link = tk.Label(footer, text="⚠  Always allow this session",
                                     fg=UI["text_faint"], bg=UI["bg"],
                                     font=f_link, cursor="hand2", bd=0)
        self._always_link.pack(side=tk.LEFT)
        self._always_link.bind("<Button-1>", lambda e: self.always_allow())
        self._always_link.bind("<Enter>", lambda e: self._always_link.config(
            fg=UI["danger_hi"], font=(sans, 9, "underline")))
        self._always_link.bind("<Leave>", lambda e: self._always_link.config(
            fg=UI["text_faint"], font=f_link))

        approve_btn = _FlatButton(footer, "Approve", self.approve, f_btn, kind="primary")
        approve_btn.pack(side=tk.RIGHT)
        deny_btn = _FlatButton(footer, "Deny", self.deny, f_btn, kind="secondary")
        deny_btn.pack(side=tk.RIGHT, padx=(0, 10))
        deny_btn.focus_set()  # safe default

        # -------------------------------------------------------------------
        # 4. Command card — bordered code block with caption and shell pill
        # -------------------------------------------------------------------
        card_border = tk.Frame(self.root, bg=UI["border"])
        card_border.pack(fill=tk.BOTH, expand=True, padx=26, pady=(0, 8))
        card = tk.Frame(card_border, bg=UI["code_bg"])
        card.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        card_head = tk.Frame(card, bg=UI["code_bg"])
        card_head.pack(fill=tk.X, padx=14, pady=(12, 6))
        tk.Label(card_head, text="REQUESTED COMMAND", fg=UI["text_faint"],
                 bg=UI["code_bg"], font=f_caption, bd=0).pack(side=tk.LEFT)
        self._make_pill(card_head, self.shell.upper(), f_caption).pack(side=tk.RIGHT)

        ta = tk.Text(card, wrap=tk.WORD, bg=UI["code_bg"], fg=UI["code_fg"],
                     font=f_code, bd=0, padx=14, pady=6, height=6,
                     selectbackground="#bfdbfe", selectforeground=UI["text"],
                     highlightthickness=0)
        ta.insert(tk.END, self.command)
        ta.config(state=tk.DISABLED)
        ta.pack(fill=tk.BOTH, expand=True)  # mouse wheel still scrolls long commands

        # Keyboard shortcuts
        self.root.bind("<Escape>", lambda e: self.deny())
        self.root.bind("y", lambda e: self.approve())
        self.root.bind("Y", lambda e: self.approve())
        self.root.bind("n", lambda e: self.deny())
        self.root.bind("N", lambda e: self.deny())

        # Show window now that geometry is applied
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.focus_force()

        self._deadline = time.monotonic() + self.timeout
        self._stripe_mode = "ok"
        self._tick()
        self.root.protocol("WM_DELETE_WINDOW", self.deny)
        self.root.mainloop()

    # -- widgets ------------------------------------------------------------
    def _make_pill(self, parent, text, font):
        tk = self._tk
        pw = font.measure(text) + 22
        ph = font.metrics("linespace") + 8
        c = tk.Canvas(parent, width=pw, height=ph, bg=UI["code_bg"],
                      highlightthickness=0, bd=0)
        _rounded_rect(c, 1, 1, pw - 1, ph - 1, ph // 2 - 1,
                      fill=UI["pill_bg"], outline=UI["pill_bg"])
        c.create_text(pw // 2, ph // 2, text=text, font=font, fill=UI["pill_fg"])
        return c

    # -- countdown ----------------------------------------------------------
    def _tick(self):
        if self._closed:
            return
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            self.deny()
            return
        secs = int(remaining + 0.999)
        frac = remaining / self.timeout

        # Drain the stripe from the right; tint it when time runs low
        self.stripe.coords(self._stripe_cover,
                           self._stripe_w * frac, 0, self._stripe_w, 5)
        mode = "ok" if secs > 20 else ("warn" if secs > 10 else "danger")
        if mode != self._stripe_mode:
            self._stripe_mode = mode
            if mode == "ok":
                self.stripe.itemconfig(self._stripe_tint, state="hidden")
                self.timer_value.config(fg=UI["text_dim"])
            else:
                color = UI["warn"] if mode == "warn" else UI["danger"]
                self.stripe.itemconfig(self._stripe_tint, fill=color, state="normal")
                self.stripe.tag_raise(self._stripe_cover)
                self.timer_value.config(fg=color)
        self.timer_value.config(text=f"{secs}s")
        self.root.after(100, self._tick)

    # -- actions ------------------------------------------------------------
    def _finish(self, result):
        if self._closed:
            return
        self._closed = True
        self.result = result
        try:
            self.root.destroy()
        except Exception:
            pass

    def approve(self):
        self._finish(True)

    def deny(self):
        self._finish(False)

    def always_allow(self):
        if self._confirm_always():
            self._finish("ALWAYS")

    def _confirm_always(self):
        """Themed modal confirmation for the dangerous 'Always Allow' option."""
        tk = self._tk
        from tkinter import font as tkfont

        top = tk.Toplevel(self.root)
        top.title("Security Warning")
        top.configure(bg=UI["bg"])
        top.withdraw()
        top.transient(self.root)
        top.resizable(False, False)
        top.attributes("-topmost", True)

        cw, ch = 480, 300
        px = self.root.winfo_rootx() + (self.root.winfo_width() - cw) // 2
        py = self.root.winfo_rooty() + (self.root.winfo_height() - ch) // 2
        top.geometry(f"{cw}x{ch}+{max(px, 0)}+{max(py, 0)}")

        families = set(tkfont.families())
        sans = _pick_font(families, ["Segoe UI", "Helvetica Neue", "DejaVu Sans"],
                          "TkDefaultFont")
        f_head = tkfont.Font(family=sans, size=13, weight="bold")
        f_body = tkfont.Font(family=sans, size=10)

        body = tk.Frame(top, bg=UI["bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=24, pady=20)

        head_row = tk.Frame(body, bg=UI["bg"])
        head_row.pack(fill=tk.X)
        tk.Label(head_row, text="⚠", fg=UI["danger"], bg=UI["bg"],
                 font=(sans, 20)).pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(head_row, text="Enable Always Allow?", fg=UI["text"],
                 bg=UI["bg"], font=f_head, anchor="w").pack(side=tk.LEFT)

        tk.Label(body, justify=tk.LEFT, anchor="w", wraplength=cw - 60,
                 fg=UI["text_dim"], bg=UI["bg"], font=f_body,
                 text=("Every command from the AI agent will run this session "
                       "WITHOUT showing this authorization prompt again.\n\n"
                       "A misbehaving agent could silently execute destructive "
                       "administrative commands — deleting files, changing system "
                       "settings, or worse.\n\n"
                       "Only proceed if you fully trust the current agent and task.")
                 ).pack(fill=tk.X, pady=(14, 0))

        result = {"ok": False}

        def _ok():
            result["ok"] = True
            top.destroy()

        btns = tk.Frame(body, bg=UI["bg"])
        btns.pack(fill=tk.X, side=tk.BOTTOM, pady=(16, 0))
        _FlatButton(btns, "Always Allow", _ok, self._f_btn,
                    kind="danger").pack(side=tk.RIGHT)
        cancel = _FlatButton(btns, "Cancel", top.destroy, self._f_btn,
                             kind="secondary")
        cancel.pack(side=tk.RIGHT, padx=(0, 10))

        top.protocol("WM_DELETE_WINDOW", top.destroy)
        top.bind("<Escape>", lambda e: top.destroy())
        top.deiconify()
        top.grab_set()
        cancel.focus_set()
        self.root.wait_window(top)
        return result["ok"]


class _FlatButton:
    """Rounded, flat button with hover/pressed/focus states, drawn on a Canvas."""

    KINDS = {
        "primary":   (UI["accent"], UI["accent_hi"], UI["accent_dn"], "#ffffff"),
        "secondary": (UI["surface"], UI["surface_hi"], UI["surface_dn"], UI["text"]),
        "danger":    (UI["danger_btn"], UI["danger_btn_hi"], "#991b1b", "#ffffff"),
    }

    def __init__(self, parent, text, command, font, kind="secondary"):
        import tkinter as tk
        self.command = command
        self.fill, self.hover, self.pressed, fg = self.KINDS[kind]
        w = font.measure(text) + 44
        h = font.metrics("linespace") + 18
        self._w, self._h = w, h
        self.c = tk.Canvas(parent, width=w, height=h, bg=parent["bg"],
                           highlightthickness=0, bd=0, cursor="hand2",
                           takefocus=1)
        self.shape = _rounded_rect(self.c, 1, 1, w - 1, h - 1, 10,
                                   fill=self.fill, outline=self.fill)
        self.c.create_text(w // 2, h // 2, text=text, font=font, fill=fg)
        self.c.bind("<Enter>", lambda e: self._paint(self.hover))
        self.c.bind("<Leave>", lambda e: self._paint(self.fill))
        self.c.bind("<Button-1>", lambda e: self._paint(self.pressed))
        self.c.bind("<ButtonRelease-1>", self._release)
        self.c.bind("<Return>", lambda e: self.command())
        self.c.bind("<space>", lambda e: self.command())
        self.c.bind("<FocusIn>", lambda e: self.c.itemconfig(
            self.shape, outline=UI["focus"], width=2))
        self.c.bind("<FocusOut>", lambda e: self.c.itemconfig(
            self.shape, outline=self.fill, width=1))

    def _paint(self, color):
        self.c.itemconfig(self.shape, fill=color)

    def _release(self, event):
        inside = 0 <= event.x <= self._w and 0 <= event.y <= self._h
        self._paint(self.hover if inside else self.fill)
        if inside:
            self.command()

    def pack(self, **kw):
        self.c.pack(**kw)

    def focus_set(self):
        self.c.focus_set()


def run_gui_prompt(command, shell, timeout=60):
    try:
        import tkinter
        return ApprovalDialog(command, shell, timeout).result
    except Exception as e:
        logging.warning(f"Tkinter unavailable ({e}). Trying platform fallback...")
        return run_fallback_prompt(command, shell, timeout)


def run_fallback_prompt(command, shell, timeout=60):
    if sys.platform == "darwin":
        try:
            esc = command.replace('"', '\\"').replace('\n', '\\r')
            script = (
                f'display dialog "Conduit Authorization\\r\\rShell: {shell}\\rCommand:\\r{esc}" '
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
                f"--text=Authorize command in {shell}?\n\n{command}",
                f"--timeout={timeout}"
            ])
            return r.returncode == 0
        except Exception:
            pass

    return run_terminal_fallback(command, shell, timeout)


def run_terminal_fallback(command, shell, timeout):
    print("\n" + "="*70)
    print("[!] CONDUIT AUTHORIZATION REQUEST (Terminal Fallback)")
    print(f"Shell: {shell}")
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
