"""
通用输入对话框
"""
import tkinter as tk
from tkinter import ttk


class InputDialog(tk.Toplevel):
    """简单输入对话框 - 返回用户输入的字符串"""

    def __init__(self, parent, title: str, prompt: str, default: str = ""):
        super().__init__(parent)
        self.result = None
        self.title(title)
        self.geometry("320x120")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.update(); self.update()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        pp, pt = parent.winfo_rootx(), parent.winfo_rooty()
        ww, wh = self.winfo_width(), self.winfo_height()
        if ww > 0 and wh > 0:
            self.geometry(f"+{pp + (pw - ww) // 2}+{pt + (ph - wh) // 2}")

        ttk.Label(self, text=prompt).pack(padx=12, pady=10)
        self._var = tk.StringVar(value=default)
        ttk.Entry(self, textvariable=self._var, width=36).pack(padx=12)
        btns = ttk.Frame(self)
        btns.pack(pady=8)
        ttk.Button(btns, text="确定", command=self._ok).pack(side="left", padx=8)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=8)
        self.bind("<Return>", lambda e: self._ok())
        self.wait_window()

    def _ok(self):
        v = self._var.get().strip()
        if v:
            self.result = v
        self.destroy()
