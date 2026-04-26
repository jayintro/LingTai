"""
主窗口 - LingTai 模块宿主

负责：顶部导航栏、模块切换、菜单栏、全局设置。
具体功能由各 Module 实现，默认显示「工具箱」模块。
"""
import tkinter as tk
from tkinter import ttk, messagebox

from app.__version__ import APP_NAME, APP_VERSION
from app.core import ConfigManager, LaunchEngine, LogManager
from app.ui.dialogs.runtime_dialog import RuntimeManagerDialog
from app.ui.modules import MODULE_REGISTRY


class MainWindow(tk.Tk):
    def __init__(self, config: ConfigManager, engine: LaunchEngine,
                 log_mgr: LogManager):
        super().__init__()
        self.config = config
        self.engine = engine
        self.log_mgr = log_mgr

        self.title(f"{APP_NAME}  {APP_VERSION}")
        self.geometry("980x620")
        self.minsize(720, 420)

        self._modules = {}          # module_id -> BaseModule 实例
        self._active_module = None  # 当前激活的模块 ID
        self._nav_buttons = {}      # module_id -> 导航按钮

        self._build_menu()
        self._build_nav_bar()
        self._build_module_container()
        self._register_modules()

        # 默认激活第一个模块
        if self._modules:
            self._switch_to(list(self._modules.keys())[0])

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # 全局屏蔽 Alt 和 F10 键，防止 IME 组字时误激活菜单栏
        # Alt 单键在 Windows 上会激活菜单栏，IME 组字过程中可能产生 Alt 事件
        self.bind_all("<Alt_L>", lambda e: "break")
        self.bind_all("<Alt_R>", lambda e: "break")
        self.bind_all("<F10>", lambda e: "break")

    # ─── 菜单 ────────────────────────────────────────────────────────

    def _build_menu(self):
        menubar = tk.Menu(self)
        m_tools = tk.Menu(menubar, tearoff=0)
        m_tools.add_command(label="运行环境（JDK / Python）", command=self._open_runtime_mgr)
        m_tools.add_separator()
        m_tools.add_command(label="退出", command=self._on_close)
        # underline=-1 禁用菜单助记符，防止 IME 组字时 Alt 事件误激活菜单栏
        menubar.add_cascade(label="设置", menu=m_tools, underline=-1)

        m_log = tk.Menu(menubar, tearoff=0)
        m_log.add_command(label="清理 7 天前日志", command=self._clean_old_logs)
        m_log.add_command(label="清理全部日志", command=self._clean_all_logs)
        menubar.add_cascade(label="日志", menu=m_log, underline=-1)

        self.configure(menu=menubar)

    # ─── 顶部导航栏 ──────────────────────────────────────────────────

    def _build_nav_bar(self):
        """构建顶部模块切换导航栏"""
        nav_frame = ttk.Frame(self)
        nav_frame.pack(fill="x", padx=6, pady=(6, 0))

        ttk.Separator(nav_frame, orient="horizontal").pack(fill="x", side="bottom")

        btn_container = ttk.Frame(nav_frame)
        btn_container.pack(fill="x", pady=4)

        self._btn_container = btn_container

    # ─── 模块容器 ────────────────────────────────────────────────────

    def _build_module_container(self):
        """模块内容区域 - 模块 Frame 将 pack 在此"""
        self._module_container = ttk.Frame(self)
        self._module_container.pack(fill="both", expand=True, padx=6, pady=6)

    # ─── 模块注册 ────────────────────────────────────────────────────

    def _register_modules(self):
        """根据 MODULE_REGISTRY 创建并注册所有模块"""
        for ModuleClass in MODULE_REGISTRY:
            module = ModuleClass(self._module_container, app=self)
            module_id = ModuleClass.__name__
            self._modules[module_id] = module

            # 创建导航按钮
            btn = ttk.Button(
                self._btn_container,
                text=module.display_name,
                width=14,
                command=lambda mid=module_id: self._switch_to(mid),
            )
            btn.pack(side="left", padx=3)
            self._nav_buttons[module_id] = btn

    # ─── 模块切换 ────────────────────────────────────────────────────

    def _switch_to(self, module_id: str):
        """切换到指定模块"""
        if module_id not in self._modules:
            return

        # 反激活旧模块
        if self._active_module and self._active_module in self._modules:
            old = self._modules[self._active_module]
            old.deactivate()
            old.pack_forget()
            # 恢复旧按钮样式
            self._nav_buttons[self._active_module].configure(style="TButton")

        # 激活新模块
        new_module = self._modules[module_id]
        new_module.pack(in_=self._module_container, fill="both", expand=True)
        new_module.activate()
        self._active_module = module_id

        # 高亮当前按钮
        self._update_nav_style()

    def _update_nav_style(self):
        """更新导航按钮样式 - 当前激活的按钮使用强调色"""
        for mid, btn in self._nav_buttons.items():
            if mid == self._active_module:
                # 激活状态：背景色加深表示选中
                btn.state(["pressed"])
            else:
                btn.state(["!pressed"])

    # ─── 全局操作 ────────────────────────────────────────────────────

    def _open_runtime_mgr(self):
        RuntimeManagerDialog(self, self.config)

    def _clean_old_logs(self):
        count = self.log_mgr.clean_old_logs(keep_days=7)
        messagebox.showinfo("完成", f"已清理 7 天前的旧日志（{count} 个文件）", parent=self)

    def _clean_all_logs(self):
        if not messagebox.askyesno("确认", "确定要清理全部日志文件？\n此操作不可恢复。", parent=self):
            return
        count = self.log_mgr.clean_all_logs()
        messagebox.showinfo("完成", f"已清理全部日志（{count} 个文件）", parent=self)

    # ─── 退出 ────────────────────────────────────────────────────────

    def _on_close(self):
        running = self.engine.running_tool_ids()
        if running:
            names = [self.config.get_tool(j).name for j in running
                     if self.config.get_tool(j)]
            msg = f"以下工具仍在运行，退出将终止它们：\n{chr(10).join(names)}\n\n确认退出？"
            if not messagebox.askyesno("确认退出", msg, parent=self):
                return
        self.engine.stop_all()
        self.destroy()
