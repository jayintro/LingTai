"""
运行环境对话框 - 统一管理 JDK 和 Python 版本配置
"""
import re
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from app.core import ConfigManager, JdkConfig, PythonConfig


class RuntimeManagerDialog(tk.Toplevel):
    """运行环境主窗口（管理 JDK + Python）"""

    def __init__(self, parent, config: ConfigManager):
        super().__init__(parent)
        self.config = config
        self.title("运行环境（JDK / Python）")
        self.geometry("780x500")
        self.minsize(600, 400)
        self.transient(parent)
        self.grab_set()
        self._build_ui()
        self._refresh()
        self._center_on_parent(parent)

    def _center_on_parent(self, parent):
        self.update(); self.update()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        pp = parent.winfo_rootx()
        pt = parent.winfo_rooty()
        ww = self.winfo_width()
        wh = self.winfo_height()
        if ww > 0 and wh > 0:
            self.geometry(f"+{pp + (pw - ww) // 2}+{pt + (ph - wh) // 2}")

    def _build_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        self._jdk_panel = ttk.Frame(nb)
        self._py_panel = ttk.Frame(nb)
        nb.add(self._jdk_panel, text="☕ JDK 版本")
        nb.add(self._py_panel, text="🐍 Python 版本")

        self._build_jdk_tab()
        self._build_py_tab()

    # ─── JDK Tab ─────────────────────────────────────────────────

    def _build_jdk_tab(self):
        f = self._jdk_panel
        ttk.Frame(f, height=4).pack()
        tb = ttk.Frame(f)
        tb.pack(fill="x", padx=8, pady=4)
        ttk.Button(tb, text="+ 添加 JDK", command=self._add_jdk).pack(side="left", padx=4)
        ttk.Button(tb, text="✎ 编辑", command=self._edit_jdk).pack(side="left", padx=4)
        ttk.Button(tb, text="✕ 删除", command=self._delete_jdk).pack(side="left", padx=4)

        cols = ("显示名称", "版本", "java 路径", "备注")
        self._jdk_tree = ttk.Treeview(f, columns=cols, show="headings")
        for c, w in zip(cols, (140, 110, 320, 130)):
            self._jdk_tree.heading(c, text=c)
            self._jdk_tree.column(c, width=w, minwidth=60)
        sb = ttk.Scrollbar(f, orient="vertical", command=self._jdk_tree.yview)
        self._jdk_tree.configure(yscrollcommand=sb.set)
        self._jdk_tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=4)
        sb.pack(side="right", fill="y", pady=4, padx=(0, 8))

    # ─── Python Tab ─────────────────────────────────────────────

    def _build_py_tab(self):
        f = self._py_panel
        ttk.Frame(f, height=4).pack()
        tb = ttk.Frame(f)
        tb.pack(fill="x", padx=8, pady=4)
        ttk.Button(tb, text="+ 添加 Python", command=self._add_py).pack(side="left", padx=4)
        ttk.Button(tb, text="✎ 编辑", command=self._edit_py).pack(side="left", padx=4)
        ttk.Button(tb, text="✕ 删除", command=self._delete_py).pack(side="left", padx=4)

        cols = ("显示名称", "版本", "python 路径", "备注")
        self._py_tree = ttk.Treeview(f, columns=cols, show="headings")
        for c, w in zip(cols, (140, 110, 320, 130)):
            self._py_tree.heading(c, text=c)
            self._py_tree.column(c, width=w, minwidth=60)
        sb = ttk.Scrollbar(f, orient="vertical", command=self._py_tree.yview)
        self._py_tree.configure(yscrollcommand=sb.set)
        self._py_tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=4)
        sb.pack(side="right", fill="y", pady=4, padx=(0, 8))

    def _refresh(self):
        self._jdk_tree.delete(*self._jdk_tree.get_children())
        for jdk in self.config.list_jdks():
            self._jdk_tree.insert("", "end", iid=jdk.id,
                                  values=(jdk.name, jdk.version, jdk.java_path, jdk.description))

        self._py_tree.delete(*self._py_tree.get_children())
        for py in self.config.list_pythons():
            self._py_tree.insert("", "end", iid=py.id,
                                 values=(py.name, py.version, py.python_path, py.description))

    # ─── JDK 操作 ────────────────────────────────────────────────

    def _selected_jdk(self):
        sel = self._jdk_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一条记录", parent=self)
            return None
        return self.config.get_jdk(sel[0])

    def _add_jdk(self):
        _RuntimeEditDialog(self, self.config, "jdk", None, self._refresh)

    def _edit_jdk(self):
        jdk = self._selected_jdk()
        if jdk:
            _RuntimeEditDialog(self, self.config, "jdk", jdk, self._refresh)

    def _delete_jdk(self):
        jdk = self._selected_jdk()
        if not jdk:
            return
        if not messagebox.askyesno("确认删除", f"确定删除「{jdk.name}」？", parent=self):
            return
        try:
            self.config.delete_jdk(jdk.id)
            self._refresh()
        except ValueError as e:
            messagebox.showerror("无法删除", str(e), parent=self)

    # ─── Python 操作 ────────────────────────────────────────────

    def _selected_py(self):
        sel = self._py_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一条记录", parent=self)
            return None
        return self.config.get_python(sel[0])

    def _add_py(self):
        _RuntimeEditDialog(self, self.config, "python", None, self._refresh)

    def _edit_py(self):
        py = self._selected_py()
        if py:
            _RuntimeEditDialog(self, self.config, "python", py, self._refresh)

    def _delete_py(self):
        py = self._selected_py()
        if not py:
            return
        if not messagebox.askyesno("确认删除", f"确定删除「{py.name}」？", parent=self):
            return
        try:
            self.config.delete_python(py.id)
            self._refresh()
        except ValueError as e:
            messagebox.showerror("无法删除", str(e), parent=self)



# ─── JDK / Python 编辑表单 ─────────────────────────────────────────

class _RuntimeEditDialog(tk.Toplevel):
    def __init__(self, parent, config: ConfigManager,
                 rtype: str, obj, on_done):
        super().__init__(parent)
        self.config = config
        self.rtype = rtype  # "jdk" or "python"
        self.obj = obj
        self.on_done = on_done
        self.title(f"编辑 {'JDK' if rtype == 'jdk' else 'Python'}"
                   if obj else f"添加 {'JDK' if rtype == 'jdk' else 'Python'}")
        self.geometry("500x280")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self._build()
        self._center_on_parent(parent)

    def _center_on_parent(self, parent):
        self.update(); self.update()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        pp = parent.winfo_rootx()
        pt = parent.winfo_rooty()
        ww = self.winfo_width()
        wh = self.winfo_height()
        if ww > 0 and wh > 0:
            self.geometry(f"+{pp + (pw - ww) // 2}+{pt + (ph - wh) // 2}")

    def _build(self):
        f = ttk.Frame(self, padding=16)
        f.pack(fill="both", expand=True)

        exe_label = "java 可执行文件路径" if self.rtype == "jdk" else "python 可执行文件路径"
        icon = "☕" if self.rtype == "jdk" else "🐍"
        self._vars = {
            "name": tk.StringVar(),
            "version": tk.StringVar(),
            "path": tk.StringVar(),
            "desc": tk.StringVar(),
        }

        if self.obj:
            self._vars["name"].set(self.obj.name)
            self._vars["version"].set(self.obj.version)
            self._vars["path"].set(
                self.obj.java_path if self.rtype == "jdk" else self.obj.python_path)
            self._vars["desc"].set(self.obj.description)

        rows = [
            ("显示名称", self._vars["name"]),
            ("版本号", self._vars["version"]),
            (exe_label, self._vars["path"]),
            ("备注", self._vars["desc"]),
        ]

        for i, (lbl, var) in enumerate(rows):
            ttk.Label(f, text=lbl + "：").grid(row=i, column=0, sticky="e", pady=5, padx=4)
            if lbl == exe_label:
                row = ttk.Frame(f)
                row.grid(row=i, column=1, sticky="ew", pady=5)
                ttk.Entry(row, textvariable=var, width=36).pack(side="left")
                ttk.Button(row, text="浏览", command=self._browse).pack(side="left", padx=4)
            else:
                ttk.Entry(f, textvariable=var, width=40).grid(row=i, column=1, sticky="ew", pady=5)
        f.columnconfigure(1, weight=1)

        btns = ttk.Frame(f)
        btns.grid(row=len(rows), column=0, columnspan=2, pady=12)
        ttk.Button(btns, text="检测版本", command=self._detect).pack(side="left", padx=8)
        ttk.Button(btns, text="保存", command=self._save).pack(side="left", padx=8)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=8)

    def _browse(self):
        ext = "java.exe java" if self.rtype == "jdk" else "python.exe python"
        path = filedialog.askopenfilename(parent=self, title="选择可执行文件",
                                          filetypes=[(ext, "*.exe"), ("所有文件", "*.*")])
        if path:
            self._vars["path"].set(path)

    def _detect(self):
        p = Path(self._vars["path"].get().strip())
        if not p.exists():
            self._show_centered_msg("提示", "路径无效或文件不存在", "warning")
            return

        # 尝试多种版本检测参数（隐藏控制台窗口）
        ver = None
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        for arg in ["--version", "-V", "-version"]:
            try:
                r = subprocess.run([str(p), arg], capture_output=True,
                                text=True, timeout=5, creationflags=creationflags)
                if r.returncode == 0:
                    ver = (r.stdout or r.stderr or "").strip().splitlines()[0]
                    break
            except Exception:
                pass

        if ver:
            self._show_centered_msg("检测结果", ver, "info")
            m = re.search(r'"?([\d]+\.[\d.]+)', ver)
            if m:
                self._vars["version"].set(m.group(1))
        else:
            msg = "无法获取版本信息\n\n可能原因：\n"
            msg += "1. 路径指向的是快捷方式(.lnk)而非可执行文件\n"
            msg += "2. 该程序不支持 --version 参数\n"
            msg += "3. 路径不存在或被损坏"
            self._show_centered_msg("检测失败", msg, "error")

    def _show_centered_msg(self, title: str, message: str, msg_type: str = "info"):
        """显示居中对齐的自定义消息弹窗"""
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("360x160")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        # 居中计算
        win.update_idletasks()
        pw, ph = self.winfo_width(), self.winfo_height()
        px, py = self.winfo_rootx(), self.winfo_rooty()
        ww, wh = win.winfo_width(), win.winfo_height()
        win.geometry(f"+{px + (pw - ww) // 2}+{py + (ph - wh) // 2}")

        # 图标颜色
        icon_color = {"info": "#3b82f6", "warning": "#f59e0b", "error": "#ef4444"}.get(msg_type, "#3b82f6")
        icon_text = {"info": "ℹ", "warning": "⚠", "error": "✕"}.get(msg_type, "ℹ")

        # 内容
        content = ttk.Frame(win, padding=20)
        content.pack(fill="both", expand=True)

        icon_lbl = ttk.Label(content, text=icon_text, font=("", 24), foreground=icon_color)
        icon_lbl.pack()

        msg_lbl = ttk.Label(content, text=message, wraplength=300, justify="center")
        msg_lbl.pack(pady=(10, 0))

        ttk.Button(win, text="确定", command=win.destroy).pack(pady=(0, 15))

    def _save(self):
        name = self._vars["name"].get().strip()
        version = self._vars["version"].get().strip()
        path = self._vars["path"].get().strip()
        desc = self._vars["desc"].get().strip()
        if not name or not path:
            messagebox.showwarning("提示", "名称和路径不能为空", parent=self)
            return

        if self.rtype == "jdk":
            if self.obj:
                self.obj.name, self.obj.version = name, version
                self.obj.java_path, self.obj.description = path, desc
                self.config.update_jdk(self.obj)
            else:
                self.config.add_jdk(name, version, path, desc)
        else:
            if self.obj:
                self.obj.name, self.obj.version = name, version
                self.obj.python_path, self.obj.description = path, desc
                self.config.update_python(self.obj)
            else:
                self.config.add_python(name, version, path, desc)

        self.on_done()
        self.destroy()


# ─── Python 扫描结果对话框 ─────────────────────────────────────────


