"""
工具箱模块 - LingTai 核心功能

整合 JAR / EXE / PY / Ftools 工具的管理、启动、停止等全部功能。
"""
import os
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

from app.core import ConfigManager, LaunchEngine, LogManager, ProcessStatus, ToolType, RuntimeManager
from app.core.utils import safe_filename
from app.ui.dialogs.tool_dialog import ToolEditDialog
from app.ui.log_viewer import LogViewerWindow
from app.ui.modules.base import BaseModule
from app.ui.dialogs import InputDialog


# 状态颜色
STATUS_COLOR = {
    ProcessStatus.RUNNING.value: "#22c55e",
    ProcessStatus.ERROR.value: "#ef4444",
    ProcessStatus.STOPPED.value: "#94a3b8",
    ProcessStatus.STARTING.value: "#f59e0b",
}

# 类型颜色
TYPE_COLOR = {
    ToolType.JAR.value: "#f59e0b",
    ToolType.EXE.value: "#3b82f6",
    ToolType.PY.value: "#22c55e",
    ToolType.FTOOLS.value: "#8b5cf6",
}
TYPE_ICON = {
    ToolType.JAR.value: "☕",
    ToolType.EXE.value: "⚙️",
    ToolType.PY.value: "🐍",
    ToolType.FTOOLS.value: "📂",
}


class ToolboxModule(BaseModule):
    """工具箱模块 - 管理 JAR / EXE / PY / Ftools 工具"""

    title = "工具箱"
    icon = "🧰"

    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, app, **kwargs)
        self._current_category = None
        self._init_log_buffer = {}
        self._search_text = ""          # 当前搜索关键词
        self._search_after_id = None    # 防抖定时器 ID
        self._build_ui()
        # 注册引擎状态回调
        self.app.engine.on_status_change(self._on_status_change_async)

    # ─── 构建 UI ──────────────────────────────────────────────────────

    def _build_ui(self):
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=6, pady=6)

        left = ttk.Frame(paned, width=160)
        paned.add(left, weight=0)
        self._build_left_panel(left)

        right = ttk.Frame(paned)
        paned.add(right, weight=1)
        self._build_right_panel(right)

    def _build_left_panel(self, parent):
        ttk.Label(parent, text="分类", font=("", 10, "bold")).pack(
            fill="x", padx=6, pady=(6, 2))
        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=6)

        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x", padx=4, pady=4)
        ttk.Button(btn_frame, text="+ 新分类", width=8,
                   command=self._new_category).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="重命名", width=7,
                   command=self._rename_category).pack(side="left", padx=2)

        self.cat_listbox = tk.Listbox(parent, selectmode="single",
                                      font=("", 10), bd=0, highlightthickness=0,
                                      activestyle="none")
        sb = ttk.Scrollbar(parent, orient="vertical", command=self.cat_listbox.yview)
        self.cat_listbox.configure(yscrollcommand=sb.set)
        self.cat_listbox.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=4)
        sb.pack(side="right", fill="y", pady=4)
        self.cat_listbox.bind("<<ListboxSelect>>", self._on_category_select)

    def _build_right_panel(self, parent):
        # ── 顶部栏：添加工具 + 日志 + 搜索 ──
        top_bar = ttk.Frame(parent)
        top_bar.pack(fill="x", pady=(0, 4))

        ttk.Button(top_bar, text="+ 添加工具", command=self._add_tool).pack(side="left", padx=4)
        ttk.Button(top_bar, text="📋 日志", command=self._view_log).pack(side="left", padx=4)

        # 搜索栏（靠右对齐，pack 顺序决定视觉顺序：先 pack 的在最右）
        self._search_count_label = ttk.Label(top_bar, text="", font=("", 9),
                                              foreground="#94a3b8")
        self._search_count_label.pack(side="right", padx=(0, 6))
        self._search_clear_btn = ttk.Button(top_bar, text="✕", width=3,
                                             command=self._clear_search)
        self._search_clear_btn.pack(side="right", padx=(0, 2))
        self._search_var = tk.StringVar()
        self._search_entry = ttk.Entry(top_bar, textvariable=self._search_var, width=24)
        self._search_entry.pack(side="right", padx=(0, 2))
        ttk.Label(top_bar, text="🔍", font=("", 10)).pack(side="right", padx=(4, 0))
        # 绑定事件
        self._search_var.trace_add("write", self._on_search_changed)
        self._search_entry.bind("<Escape>", self._clear_search)
        self._search_entry.bind("<Return>", self._search_launch_first)

        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill="both", expand=True)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        cols = ("类型", "名称", "状态", "运行时", "分类", "备注")
        self.tool_tree = ttk.Treeview(tree_frame, columns=cols, show="headings")
        for c, w in zip(cols, (50, 180, 70, 120, 80, 420)):
            self.tool_tree.heading(c, text=c)
            self.tool_tree.column(c, width=w, minwidth=40, stretch=True)

        sb_v = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tool_tree.yview)
        sb_h = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tool_tree.xview)
        self.tool_tree.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)

        self.tool_tree.grid(row=0, column=0, sticky="nsew")
        sb_v.grid(row=0, column=1, sticky="ns")
        sb_h.grid(row=1, column=0, sticky="ew")

        self._ctx_menu = tk.Menu(self, tearoff=0)
        self._ctx_menu.add_command(label="▶ 启动", command=self._launch)
        self._ctx_menu.add_command(label="■ 停止", command=self._stop)
        self._ctx_menu.add_command(label="⚡ 强制终止", command=self._force_kill)
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(label="📋 查看日志", command=self._view_log)
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(label="✎ 编辑", command=self._edit_tool)
        self._ctx_menu.add_command(label="✕ 删除", command=self._delete_tool)
        self.tool_tree.bind("<Button-3>", self._show_context_menu)
        self.tool_tree.bind("<Double-1>", lambda e: self._launch())
        self.tool_tree.bind("<Control-f>", self._focus_search)
        self.tool_tree.bind("<Control-F>", self._focus_search)
        # 搜索栏也支持 Ctrl+F
        self._search_entry.bind("<Control-f>", self._focus_search)
        self._search_entry.bind("<Control-F>", self._focus_search)

    # ─── 模块生命周期 ─────────────────────────────────────────────────

    def activate(self):
        """切换到工具箱时刷新数据"""
        self._refresh_categories()

    # ─── 分类操作 ──────────────────────────────────────────────────────

    def _refresh_categories(self):
        cats = ["全部"] + self.app.config.list_categories()
        self.cat_listbox.delete(0, "end")
        for c in cats:
            self.cat_listbox.insert("end", c)
        target = self._current_category or "全部"
        if target in cats:
            idx = cats.index(target)
            self.cat_listbox.selection_set(idx)
            self.cat_listbox.activate(idx)
        self._refresh_tool_list()

    def _on_category_select(self, event=None):
        sel = self.cat_listbox.curselection()
        if not sel:
            return
        cat = self.cat_listbox.get(sel[0])
        self._current_category = None if cat == "全部" else cat
        self._refresh_tool_list()

    def _new_category(self):
        d = InputDialog(self, "新建分类", "请输入分类名称：")
        if d.result:
            self.app.config.add_category(d.result)
            self._refresh_categories()

    def _rename_category(self):
        sel = self.cat_listbox.curselection()
        if not sel:
            return
        old = self.cat_listbox.get(sel[0])
        if old == "全部":
            return
        d = InputDialog(self, "重命名分类", f"将「{old}」重命名为：", default=old)
        if d.result and d.result != old:
            self.app.config.rename_category(old, d.result)
            self._current_category = d.result
            self._refresh_categories()

    # ─── 工具列表 ──────────────────────────────────────────────────────

    def _refresh_tool_list(self):
        self.tool_tree.delete(*self.tool_tree.get_children())
        tools = self.app.config.list_tools(self._current_category)
        tools = [t for t in tools
                 if t.name != "__placeholder__"
                 and (t.tool_path or t.tool_type == ToolType.FTOOLS.value)]

        # 搜索过滤：按名称、备注、分类、类型、运行时匹配
        if self._search_text:
            filtered = []
            for tool in tools:
                ttype = ToolType(tool.tool_type)
                # 构建可搜索文本
                search_parts = [tool.name, tool.description or "",
                                tool.category or "", ttype.name]
                # 运行时名称
                if ttype == ToolType.JAR:
                    jdk = self.app.config.get_jdk(tool.jdk_id)
                    if jdk:
                        search_parts.append(jdk.name)
                elif ttype in (ToolType.EXE, ToolType.PY):
                    py = self.app.config.get_python(tool.runtime_id)
                    if py:
                        search_parts.append(py.name)
                searchable = " ".join(search_parts).lower()
                if self._search_text in searchable:
                    filtered.append(tool)
            tools = filtered

        for tool in tools:
            ttype = ToolType(tool.tool_type)
            icon = TYPE_ICON.get(ttype.value, "?")
            status = self.app.engine.get_status(tool.id).value

            if ttype == ToolType.FTOOLS:
                runtime = "仅打开目录"
            elif ttype == ToolType.JAR:
                runtime = (self.app.config.get_jdk(tool.jdk_id).name
                           if self.app.config.get_jdk(tool.jdk_id) else "未配置")
            else:
                runtime = (self.app.config.get_python(tool.runtime_id).name
                           if self.app.config.get_python(tool.runtime_id) else "未配置")

            desc = tool.description or "—"
            self.tool_tree.insert("", "end", iid=tool.id,
                                 values=(icon, tool.name, status, runtime,
                                         tool.category, desc),
                                 tags=(ttype.value,))

        for ttype, color in TYPE_COLOR.items():
            self.tool_tree.tag_configure(ttype, foreground=color)

        # 更新搜索匹配计数
        self._update_search_count(len(tools))

    # ─── 搜索 ──────────────────────────────────────────────────────────

    def _on_search_changed(self, *args):
        """搜索框内容变化时触发（带 200ms 防抖）"""
        if self._search_after_id:
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(200, self._apply_search)

    def _apply_search(self):
        """应用搜索过滤"""
        self._search_text = self._search_var.get().strip().lower()
        self._refresh_tool_list()

    def _clear_search(self, event=None):
        """清除搜索条件"""
        self._search_var.set("")
        self._search_text = ""
        self._update_search_count(0)
        self._refresh_tool_list()
        # 让 Treeview 重新获得焦点
        self.tool_tree.focus_set()

    def _focus_search(self, event=None):
        """Ctrl+F：聚焦搜索栏并选中已有内容"""
        self._search_entry.focus_set()
        self._search_entry.select_range(0, "end")
        self._search_entry.icursor("end")
        return "break"  # 阻止事件继续传播

    def _search_launch_first(self, event=None):
        """回车：启动搜索结果中的第一个工具"""
        children = self.tool_tree.get_children()
        if children:
            self.tool_tree.selection_set(children[0])
            self.tool_tree.focus(children[0])
            self.tool_tree.see(children[0])
            self._launch()

    def _update_search_count(self, visible_count: int):
        """更新搜索匹配计数标签"""
        if self._search_text:
            total = len([t for t in self.app.config.list_tools()
                        if t.name != "__placeholder__"
                        and (t.tool_path or t.tool_type == ToolType.FTOOLS.value)])
            self._search_count_label.configure(
                text=f"匹配 {visible_count}/{total}",
                foreground="#22c55e" if visible_count > 0 else "#ef4444"
            )
        else:
            self._search_count_label.configure(text="")

    def _selected_tool(self):
        sel = self.tool_tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个工具", parent=self)
            return None
        return self.app.config.get_tool(sel[0])

    # ─── 工具 CRUD ────────────────────────────────────────────────────

    def _add_tool(self):
        if not self.app.config.list_jdks() and not self.app.config.list_pythons():
            if not messagebox.askyesno("提示",
                    "还没有配置任何运行时（JDK / Python）。\n"
                    "仅 Ftools 类型可在无运行时下添加，是否继续？", parent=self):
                return
        cat = self._current_category or "默认"
        ToolEditDialog(self, self.app.config, None, self._refresh_tool_list,
                      default_category=cat)

    def _edit_tool(self):
        tool = self._selected_tool()
        if tool:
            ToolEditDialog(self, self.app.config, tool, self._refresh_tool_list)

    def _delete_tool(self):
        tool = self._selected_tool()
        if not tool:
            return
        if self.app.engine.is_running(tool.id):
            messagebox.showwarning("提示", "请先停止该工具再删除", parent=self)
            return
        if messagebox.askyesno("确认删除", f"确定删除「{tool.name}」？", parent=self):
            self.app.config.delete_tool(tool.id)
            self._refresh_categories()

    # ─── 启动 / 停止 ──────────────────────────────────────────────────

    def _launch(self):
        tool = self._selected_tool()
        if not tool:
            return
        if self.app.engine.is_running(tool.id):
            messagebox.showinfo("提示", f"「{tool.name}」已经在运行中", parent=self)
            return

        if tool.tool_type == ToolType.PY.value and tool.use_venv:
            python_cfg = self.app.config.get_python(tool.runtime_id)
            if python_cfg:
                tool_dir = tool.working_dir.strip() or os.path.dirname(tool.tool_path)
                rt_mgr = RuntimeManager(log_callback=lambda msg: self._init_log_buffer.setdefault(tool.id, []).append(msg))
                venv_ok = rt_mgr.venv_ready(tool_dir)
                deps_ok = rt_mgr._deps_marker_path(tool_dir).exists()

                # 兜底：如果上次启动留下了 error.log（说明运行时仍有依赖缺失），
                # 删除标记文件，强制走初始化流程（会执行 import 预检 + 自动补装）
                if venv_ok and deps_ok:
                    missing_module = self._detect_missing_module(tool, rt_mgr)
                    if missing_module:
                        marker = rt_mgr._deps_marker_path(tool_dir)
                        if marker.exists():
                            marker.unlink()
                        deps_ok = False

                if venv_ok and deps_ok:
                    self._do_launch(tool)
                    return
            self._show_init_log_popup(tool)
            return

        self._do_launch(tool)

    def _show_init_log_popup(self, tool):
        """PY 工具首次启动显示初始化进度弹窗"""
        win = tk.Toplevel(self)
        win.title(f"初始化环境 — {tool.name}")
        win.geometry("560x340")
        win.transient(self)
        win.grab_set()
        win.update_idletasks()
        pw, ph = self.winfo_width(), self.winfo_height()
        pp, pt = self.winfo_rootx(), self.winfo_rooty()
        ww, wh = win.winfo_width(), win.winfo_height()
        win.geometry(f"+{pp + (pw - ww) // 2}+{pt + (ph - wh) // 2}")

        ttk.Label(win, text=f"正在为「{tool.name}」准备 Python 环境，请稍候...",
                  font=("", 9)).pack(padx=12, pady=8)

        log_text = tk.Text(win, wrap="none", font=("Consolas", 9),
                           bg="#1e1e1e", fg="#d4d4d4", height=14)
        sb = ttk.Scrollbar(win, orient="vertical", command=log_text.yview)
        log_text.configure(yscrollcommand=sb.set)
        log_text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        sb.pack(side="right", fill="y", pady=(0, 8), padx=(0, 8))

        log_text.tag_configure("info", foreground="#d4d4d4")
        log_text.tag_configure("err", foreground="#ef4444")
        log_text.tag_configure("success", foreground="#22c55e")
        log_text.tag_configure("warn", foreground="#f59e0b")

        def append_log(msg, tag="info"):
            log_text.configure(state="normal")
            log_text.insert("end", msg + "\n", tag)
            log_text.see("end")
            log_text.configure(state="disabled")

        append_log("[信息] 正在初始化 Python 虚拟环境...")
        win._running = True
        win._append_log = append_log
        win._tool = tool

        def on_log(msg):
            win.after(0, lambda: append_log(msg, "info"))

        def do_start():
            try:
                self.app.engine.set_init_log_callback(tool.id, on_log)
                self.app.engine.launch(tool.id)
                self.app.engine._init_callbacks.pop(tool.id, None)
                win.after(0, lambda: (
                    append_log("[完成] 环境就绪，工具已启动！", "success"),
                    win.after(2000, win.destroy),
                ))
            except Exception as e:
                self.app.engine._init_callbacks.pop(tool.id, None)
                err_msg = str(e)
                win.after(0, lambda msg=err_msg: append_log(f"[错误] {msg}", "err"))

        threading.Thread(target=do_start, daemon=True).start()

    def _do_launch(self, tool):
        def do():
            try:
                self.app.engine.launch(tool.id)
                self.after(0, self._refresh_tool_list)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: messagebox.showerror("启动失败", msg, parent=self))

        threading.Thread(target=do, daemon=True).start()

    def _stop(self):
        tool = self._selected_tool()
        if not tool:
            return
        self.app.engine.stop(tool.id)

    def _force_kill(self):
        tool = self._selected_tool()
        if not tool:
            return
        if messagebox.askyesno("强制终止", f"强制终止「{tool.name}」进程？", parent=self):
            self.app.engine.force_kill(tool.id)

    # ─── 日志 ──────────────────────────────────────────────────────────

    def _view_log(self):
        tool = self._selected_tool()
        if not tool:
            return
        log_file = self.app.engine.get_log_file(tool.id)
        if not log_file:
            records = self.app.log_mgr.get_history(tool.id, limit=1)
            log_file = records[0].log_file if records else None
        LogViewerWindow(self, self.app.log_mgr, tool.id, tool.name, log_file=log_file)

    # ─── 右键菜单 ─────────────────────────────────────────────────────

    def _show_context_menu(self, event):
        item = self.tool_tree.identify_row(event.y)
        if item:
            self.tool_tree.selection_set(item)
            self._ctx_menu.post(event.x_root, event.y_root)

    # ─── 状态回调（线程安全） ──────────────────────────────────────────

    def _on_status_change_async(self, tool_id: str, status: ProcessStatus):
        self.after(0, lambda: self._on_status_change(tool_id, status))

    def _on_status_change(self, tool_id: str, status: ProcessStatus):
        self._refresh_tool_list()
        # PY 工具异常退出时，检查是否需要显示依赖补装提示
        if status == ProcessStatus.ERROR:
            tool = self.app.config.get_tool(tool_id)
            if tool and tool.tool_type == ToolType.PY.value and tool.use_venv:
                self._check_dep_fix_hint(tool_id, tool)

    # ─── 依赖补装提示 ─────────────────────────────────────────────────

    def _detect_missing_module(self, tool, rt_mgr=None) -> str | None:
        """
        检测工具是否有 ModuleNotFoundError 记录。
        优先读取工具目录下的 _error.log，回退到引擎日志文件。
        返回缺失的模块名，或 None。
        """
        if rt_mgr is None:
            rt_mgr = RuntimeManager(log_callback=lambda msg: self._init_log_buffer.setdefault(tool.id, []).append(msg))

        missing_module = None
        tool_dir = tool.working_dir.strip() or os.path.dirname(tool.tool_path)
        safe_name = safe_filename(tool.name)
        err_log_path = Path(tool_dir) / f"{safe_name}_error.log"

        # 优先读取工具目录下的错误日志（PY 工具 bat 生成的 _error.log）
        if err_log_path.exists():
            try:
                content = err_log_path.read_text(encoding="utf-8", errors="replace")
                for line in content.splitlines():
                    mod = rt_mgr.parse_missing_module(line)
                    if mod:
                        missing_module = mod
                        break
            except Exception:
                pass

        # 回退：检查引擎日志文件
        if not missing_module:
            log_file = self.app.engine.get_log_file(tool.id)
            if not log_file:
                records = self.app.log_mgr.get_history(tool.id, limit=1)
                log_file = records[0].log_file if records else None
            if log_file and os.path.exists(log_file):
                try:
                    content = Path(log_file).read_text(encoding="utf-8", errors="replace")
                    for line in content.splitlines():
                        mod = rt_mgr.parse_missing_module(line)
                        if mod:
                            missing_module = mod
                            break
                except Exception:
                    pass

        return missing_module

    def _check_dep_fix_hint(self, tool_id: str, tool):
        """
        PY 工具异常退出后，检查错误日志中是否有 ModuleNotFoundError。
        如果有，弹窗提示用户可自动补装依赖。
        """
        missing_module = self._detect_missing_module(tool)
        if not missing_module:
            return

        # 弹出补装确认框
        rt_mgr = RuntimeManager(log_callback=lambda msg: self._init_log_buffer.setdefault(tool.id, []).append(msg))
        pkg_name = rt_mgr.resolve_package_name(missing_module)
        if not messagebox.askyesno(
            "依赖缺失",
            f"「{tool.name}」因缺少依赖而退出：\n\n"
            f"  模块：{missing_module}\n"
            f"  将安装：{pkg_name}\n\n"
            f"是否自动补装并重新启动？",
            parent=self,
        ):
            return

        self._show_dep_fix_popup(tool, missing_module)

    def _show_dep_fix_popup(self, tool, module_name: str):
        """依赖补装进度弹窗"""
        win = tk.Toplevel(self)
        win.title(f"依赖补装 — {tool.name}")
        win.geometry("500x280")
        win.transient(self)
        win.grab_set()
        win.update_idletasks()
        pw, ph = self.winfo_width(), self.winfo_height()
        pp, pt = self.winfo_rootx(), self.winfo_rooty()
        ww, wh = win.winfo_width(), win.winfo_height()
        win.geometry(f"+{pp + (pw - ww) // 2}+{pt + (ph - wh) // 2}")

        ttk.Label(win, text=f"正在为「{tool.name}」补装缺失依赖，请稍候...",
                  font=("", 9)).pack(padx=12, pady=8)

        log_text = tk.Text(win, wrap="none", font=("Consolas", 9),
                           bg="#1e1e1e", fg="#d4d4d4", height=10)
        sb = ttk.Scrollbar(win, orient="vertical", command=log_text.yview)
        log_text.configure(yscrollcommand=sb.set)
        log_text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        sb.pack(side="right", fill="y", pady=(0, 8), padx=(0, 8))

        log_text.tag_configure("info", foreground="#d4d4d4")
        log_text.tag_configure("err", foreground="#ef4444")
        log_text.tag_configure("success", foreground="#22c55e")
        log_text.tag_configure("warn", foreground="#f59e0b")

        def append_log(msg, tag="info"):
            log_text.configure(state="normal")
            log_text.insert("end", msg + "\n", tag)
            log_text.see("end")
            log_text.configure(state="disabled")

        append_log(f"[信息] 正在补装缺失模块 '{module_name}'...")

        def on_dep_fix_log(msg):
            tag = "info"
            if "[错误]" in msg:
                tag = "err"
            elif "[成功]" in msg:
                tag = "success"
            elif "[重试]" in msg or "[警告]" in msg:
                tag = "warn"
            win.after(0, lambda m=msg, t=tag: append_log(m, t))

        def do_fix():
            try:
                # 注册回调
                self.app.engine.set_dep_fix_callback(tool.id, on_dep_fix_log)
                self.app.engine.set_init_log_callback(tool.id, on_dep_fix_log)

                tool_dir = tool.working_dir.strip() or os.path.dirname(tool.tool_path)
                python_cfg = self.app.config.get_python(tool.runtime_id)
                rt_mgr = RuntimeManager(log_callback=lambda msg: on_dep_fix_log(msg))

                # 确保 venv 存在，如果被删除则先重建
                if not rt_mgr.venv_exists(tool_dir):
                    on_dep_fix_log("[信息] 虚拟环境不存在，正在重新创建...")
                    if not rt_mgr.create_venv(tool_dir, python_cfg):
                        win.after(0, lambda: append_log("[错误] 虚拟环境创建失败，无法补装", "err"))
                        return
                    on_dep_fix_log("[成功] 虚拟环境已创建")

                success, pkg_name = rt_mgr.install_missing_package(
                    tool_dir, module_name, on_log=on_dep_fix_log
                )

                if success:
                    # 补装成功后清理旧的 error.log + 标记文件
                    # 删除标记确保下次启动重新走预检流程
                    try:
                        safe_name = safe_filename(tool.name)
                        old_err = Path(tool_dir) / f"{safe_name}_error.log"
                        if old_err.exists():
                            old_err.unlink()
                        marker = rt_mgr._deps_marker_path(tool_dir)
                        if marker.exists():
                            marker.unlink()
                    except Exception:
                        pass
                    win.after(0, lambda: append_log(f"[完成] {pkg_name} 安装成功，正在重启工具...", "success"))
                    # 重启工具
                    try:
                        self.app.engine.launch(tool.id)
                        win.after(0, lambda: append_log("[完成] 工具已重新启动！", "success"))
                        win.after(2000, win.destroy)
                    except Exception as e:
                        err_msg = str(e)
                        win.after(0, lambda msg=err_msg: append_log(f"[错误] 重启失败：{msg}", "err"))
                else:
                    win.after(0, lambda: append_log(f"[错误] {pkg_name} 安装失败，请手动安装", "err"))
            except Exception as e:
                err_msg = str(e)
                win.after(0, lambda msg=err_msg: append_log(f"[错误] {msg}", "err"))
            finally:
                self.app.engine._init_callbacks.pop(tool.id, None)

        threading.Thread(target=do_fix, daemon=True).start()
