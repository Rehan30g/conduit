import tkinter as tk
from tkinter import messagebox
import sys


class ApprovalDialog:
    def __init__(self, command, timeout=60):
        self.command = command
        self.timeout = timeout
        self.remaining = timeout
        self.result = None
        self.root = None
        self.timer_id = None
        self.timer_paused = False

    def _tick(self):
        if self.timer_paused:
            # Reschedule without decrementing
            self.timer_id = self.root.after(100, self._tick)
            return

        self.remaining -= 0.1
        if self.remaining <= 0:
            self.result = "deny"
            self.root.quit()
            return
        self.label.config(
            text=f"Allow '{self.command}'?\n\nAuto-deny in {self.remaining:.1f}s"
        )
        self.timer_id = self.root.after(100, self._tick)

    def _allow_once(self):
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
        self.result = "once"
        self.root.quit()

    def _deny(self):
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
        self.result = "deny"
        self.root.quit()

    def _confirm_always(self):
        # Pause the countdown timer
        self.timer_paused = True

        top = tk.Toplevel(self.root)
        top.title("Confirm Always Allow")
        tk.Label(
            top,
            text=f"Are you sure you want to always allow:\n{self.command}?",
            padx=20,
            pady=20,
        ).pack()
        result = [None]

        def yes():
            result[0] = True
            top.destroy()

        def no():
            result[0] = False
            top.destroy()

        btn_frame = tk.Frame(top)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Yes", command=yes, width=10).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="No", command=no, width=10).pack(side=tk.LEFT, padx=5)

        top.transient(self.root)
        top.grab_set()
        self.root.wait_window(top)

        # Resume the countdown timer
        self.timer_paused = False

        if result[0]:
            if self.timer_id:
                self.root.after_cancel(self.timer_id)
            self.result = "always"
            self.root.quit()

    def show(self):
        self.root = tk.Tk()
        self.root.title("Approval Required")
        self.label = tk.Label(
            self.root,
            text=f"Allow '{self.command}'?\n\nAuto-deny in {self.remaining:.1f}s",
            padx=20,
            pady=20,
        )
        self.label.pack()

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="Allow Once", command=self._allow_once, width=12).pack(
            side=tk.LEFT, padx=5
        )
        tk.Button(btn_frame, text="Always Allow", command=self._confirm_always, width=12).pack(
            side=tk.LEFT, padx=5
        )
        tk.Button(btn_frame, text="Deny", command=self._deny, width=12).pack(
            side=tk.LEFT, padx=5
        )

        self.root.protocol("WM_DELETE_WINDOW", self._deny)
        self.timer_id = self.root.after(100, self._tick)
        self.root.mainloop()

        try:
            self.root.destroy()
        except:
            pass

        return self.result
