"""License dialogs: popups (tkinter) like eScope, console prompts, or nothing (CI).

Selection: no dialog at all in continuous integration (or EUNIT_NO_DIALOG=1); popups when a
display is available (EUNIT_NO_GUI=1 forces the console); console prompts on a terminal;
otherwise non-interactive, as if the dialogs were closed (demonstration license).
"""
import os
import sys
import webbrowser

from . import env
from .info import LicenseType
from .product import BUY_URL, PRODUCT_NAME

CHOICES = [
    (LicenseType.PERSONAL, "Personal (Free)", "For non-commercial, personal use only."),
    (LicenseType.PROFESSIONAL, "Professional (Paid)", "Required for work, business, or client use."),
    (LicenseType.DEMONSTRATION, "Demonstration (Free)", "1 month trial for work, business, or client use."),
]

PERSONAL_TEXT = ("This software is free for personal, non-commercial use only.\n\n"
                 "Personal use does NOT include\n"
                 "  - Work or business use\n"
                 "  - Client or consulting work\n"
                 "  - Revenue-generating activity")
PERSONAL_CONFIRM = "I confirm I will use this software only for personal, non-commercial purposes."


def make_ui():
    if env.is_ci() or os.environ.get("EUNIT_NO_DIALOG"):
        return SilentUI()
    if not os.environ.get("EUNIT_NO_GUI") and _has_display():
        try:
            return GuiUI()
        except Exception:
            pass
    if sys.stdin is not None and sys.stdin.isatty():
        return ConsoleUI()
    return SilentUI()


def _has_display():
    if os.name == "nt" or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


# ----------------------------------------------------------------------------
class SilentUI:
    """Never blocks: messages on stderr, dialogs answered as if closed."""

    def message(self, text, level="info"):
        print(f"{PRODUCT_NAME} license: {text}", file=sys.stderr)

    def choose_license(self):
        return LicenseType.DEMONSTRATION

    def confirm_personal(self):
        return False

    def managed_notice(self, text, ok_cancel):
        self.message(text, "warning")
        return True

    def activate_professional(self, activate_fn):
        return None

    def close(self):
        pass


# ----------------------------------------------------------------------------
class ConsoleUI(SilentUI):
    def _input(self, prompt):
        try:
            return input(prompt)
        except EOFError:
            return ""

    def message(self, text, level="info"):
        print(f"\n[{PRODUCT_NAME} license] {text}\n", file=sys.stderr)

    def choose_license(self):
        print(f"\n{PRODUCT_NAME} - How will you use this software?")
        for i, (_, title, desc) in enumerate(CHOICES, 1):
            print(f"  {i}. {title}: {desc}")
        answer = self._input("Choice [1-3, default 3]: ").strip()
        return CHOICES[int(answer) - 1][0] if answer in ("1", "2", "3") else LicenseType.DEMONSTRATION

    def confirm_personal(self):
        print(f"\n{PERSONAL_TEXT}\n")
        return self._input(f"{PERSONAL_CONFIRM}\nType 'yes' to confirm: ").strip().lower() == "yes"

    def managed_notice(self, text, ok_cancel):
        self.message(text, "warning")
        if not ok_cancel:
            return True
        return self._input("Continue with the Personal license? [y/N]: ").strip().lower() in ("y", "yes")

    def activate_professional(self, activate_fn):
        print(f"\nBuy a license: {BUY_URL}")
        while True:
            key = self._input("Enter your Professional license key (empty to cancel): ").strip()
            if not key:
                return None
            print("Activating...")
            lic, error = activate_fn(key)
            if lic is not None:
                return lic
            print(error)


# ----------------------------------------------------------------------------
class GuiUI:
    """Popups like the eScope dialogs (tkinter, standard with Python)."""

    def __init__(self):
        import tkinter as tk
        from tkinter import messagebox
        if os.name == "nt":
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)   # crisp text on scaled displays
            except Exception:
                pass
        self.tk, self.mb = tk, messagebox
        self.root = tk.Tk()
        self.root.withdraw()

    def close(self):
        if self.root is not None:
            self.root.destroy()
            self.root = None

    def _dialog(self, title):
        w = self.tk.Toplevel(self.root)
        w.title(f"{PRODUCT_NAME} - {title}")
        w.resizable(False, False)
        w.attributes("-topmost", True)
        return w

    def _run(self, w):
        w.update_idletasks()
        x = (w.winfo_screenwidth() - w.winfo_reqwidth()) // 2
        y = (w.winfo_screenheight() - w.winfo_reqheight()) // 3
        w.geometry(f"+{x}+{y}")
        w.lift()
        w.focus_force()
        w.grab_set()
        self.root.wait_window(w)

    def message(self, text, level="info"):
        fn = {"warning": self.mb.showwarning, "error": self.mb.showerror}.get(level, self.mb.showinfo)
        fn(f"{PRODUCT_NAME} - License", text, parent=self.root)

    def managed_notice(self, text, ok_cancel):
        if ok_cancel:
            return bool(self.mb.askokcancel("Notice", text, icon="warning", parent=self.root))
        self.mb.showwarning("Notice", text, parent=self.root)
        return True

    def choose_license(self):
        tk = self.tk
        w = self._dialog("License Creation")
        choice = tk.StringVar(value=LicenseType.DEMONSTRATION.value)
        result = {"type": LicenseType.DEMONSTRATION}   # closing the window = demonstration, as eScope
        frame = tk.Frame(w, padx=24, pady=18)
        frame.pack()
        tk.Label(frame, text="How will you use this software?").pack(anchor="w", pady=(0, 10))
        for t, title, desc in CHOICES:
            tk.Radiobutton(frame, text=f"{title}\n{desc}", value=t.value, variable=choice,
                           justify="left").pack(anchor="w", pady=4)

        def ok():
            result["type"] = LicenseType(choice.get())
            w.destroy()
        tk.Button(frame, text="Continue", width=12, command=ok).pack(pady=(12, 0))
        w.bind("<Return>", lambda _e: ok())
        self._run(w)
        return result["type"]

    def confirm_personal(self):
        tk = self.tk
        w = self._dialog("Personal License")
        accepted = {"ok": False}
        checked = tk.BooleanVar(value=False)
        frame = tk.Frame(w, padx=24, pady=18)
        frame.pack()
        tk.Label(frame, text=PERSONAL_TEXT, justify="left").pack(anchor="w")
        tk.Checkbutton(frame, text=PERSONAL_CONFIRM, variable=checked).pack(anchor="w", pady=14)

        def ok():
            if not checked.get():
                self.mb.showwarning("Confirmation Required", "You must confirm personal use to continue.", parent=w)
                return
            accepted["ok"] = True
            w.destroy()
        tk.Button(frame, text="Continue", width=12, command=ok).pack()
        self._run(w)
        return accepted["ok"]

    def activate_professional(self, activate_fn):
        tk = self.tk
        w = self._dialog("Professional License")
        result = {"license": None}
        frame = tk.Frame(w, padx=16, pady=14)
        frame.pack()
        tk.Label(frame, text="Enter your Professional license key:").grid(row=0, column=0, columnspan=3, sticky="w")
        key = tk.Entry(frame, width=44)
        key.grid(row=1, column=0, columnspan=3, sticky="we", pady=6)
        status = tk.Label(frame, text="", fg="firebrick", justify="left", wraplength=360)
        status.grid(row=2, column=0, columnspan=3, sticky="w")
        buy = tk.Label(frame, text="Buy a license", fg="blue", cursor="hand2")
        buy.grid(row=3, column=0, sticky="w", pady=(8, 0))
        buy.bind("<Button-1>", lambda _e: webbrowser.open(BUY_URL))

        def activate():
            activate_btn.config(state="disabled")
            key.config(state="disabled")
            status.config(text="Activating...", fg="black")
            w.config(cursor="watch")
            w.update()
            lic, error = activate_fn(key.get())
            w.config(cursor="")
            if lic is not None:
                result["license"] = lic
                w.destroy()
                return
            status.config(text=error, fg="firebrick")
            activate_btn.config(state="normal")
            key.config(state="normal")

        activate_btn = tk.Button(frame, text="Activate", width=10, command=activate)
        activate_btn.grid(row=3, column=1, padx=4, pady=(8, 0))
        tk.Button(frame, text="Cancel", width=10, command=w.destroy).grid(row=3, column=2, pady=(8, 0))
        frame.columnconfigure(0, weight=1)
        w.bind("<Return>", lambda _e: activate())
        w.bind("<Escape>", lambda _e: w.destroy())
        key.focus_set()
        self._run(w)
        return result["license"]
