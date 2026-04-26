"""
日志查看窗口 - 实时滚动 + 历史运行记录
"""
import tkinter as tk
from tkinter import ttk

from app.core import LogManager


class LogViewerWindow(tk.Toplevel):
    """独立日志查看窗口，支持实时刷新"""

    def __init__(self, parent, log_mgr: LogManager,
                 tool_id: str, tool_name: str,
                 log_file: str | None = None):
        super().__init__(parent)
        self.log_mgr = log_mgr
        self.tool_id = tool_id
        self.tool_name = tool_name
        self.log_file = log_file
        self._auto_refresh = True
        self._last_size = 0

        self.title(f"日志 — {self.tool_name}")
        self.geometry("820x520")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build()
        self._refresh_log()

    def _build(self):
        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")

        ttk.Label(top, text="日志文件：").pack(side="left")
        self._file_label = ttk.Label(top, text=self.log_file or "—",
                                     foreground="gray", wraplength=500)
        self._file_label.pack(side="left", fill="x", expand=True)

        self._auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="自动刷新", variable=self._auto_var,
                        command=self._toggle_auto).pack(side="right", padx=4)
        ttk.Button(top, text="清空显示", command=self._clear).pack(side="right", padx=4)

        # 主日志文本区域
        main_f = ttk.Frame(self)
        main_f.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        self.text = tk.Text(main_f, wrap="none", font=("Consolas", 10),
                            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white",
                            state="disabled")
        sb_v = ttk.Scrollbar(main_f, orient="vertical", command=self.text.yview)
        sb_h = ttk.Scrollbar(main_f, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)

        self.text.grid(row=0, column=0, sticky="nsew")
        sb_v.grid(row=0, column=1, sticky="ns")
        sb_h.grid(row=1, column=0, sticky="ew")
        main_f.rowconfigure(0, weight=1)
        main_f.columnconfigure(0, weight=1)

        # 底部历史记录区
        hist_frame = ttk.LabelFrame(self, text="最近运行记录", padding=4)
        hist_frame.pack(fill="x", padx=8, pady=(0, 8))

        cols = ("启动时间", "状态", "退出码", "日志文件")
        self.hist_tree = ttk.Treeview(hist_frame, columns=cols,
                                      show="headings", height=4)
        for c, w in zip(cols, (150, 80, 60, 360)):
            self.hist_tree.heading(c, text=c)
            self.hist_tree.column(c, width=w, minwidth=40)
        self.hist_tree.pack(fill="x")
        self.hist_tree.bind("<Double-1>", self._open_history_log)

        self._refresh_history()

    def _refresh_log(self):
        if not self.log_file:
            return
        content = self.log_mgr.read_log_tail(self.log_file, 500)
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", content)
        self.text.configure(state="disabled")
        self.text.see("end")

        # 调度下一次刷新
        if self._auto_var.get() and self.winfo_exists():
            self.after(1500, self._refresh_log)

    def _refresh_history(self):
        self.hist_tree.delete(*self.hist_tree.get_children())
        for r in self.log_mgr.get_history(self.tool_id, limit=20):
            self.hist_tree.insert("", "end", values=(
                r.started_at[:19].replace("T", " "),
                r.status,
                r.exit_code if r.exit_code is not None else "—",
                r.log_file,
            ), tags=(r.log_file,))

    def _open_history_log(self, event):
        sel = self.hist_tree.selection()
        if not sel:
            return
        log_path = self.hist_tree.item(sel[0])["values"][3]
        if log_path and log_path != "—":
            LogViewerWindow(self, self.log_mgr, self.tool_id, self.tool_name,
                            log_file=str(log_path))

    def _toggle_auto(self):
        if self._auto_var.get():
            self._refresh_log()

    def _clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def _on_close(self):
        self._auto_var.set(False)
        self.destroy()
