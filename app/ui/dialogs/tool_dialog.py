"""
工具添加/编辑对话框 - 支持 JAR / EXE / PY / Ftools 四种类型
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from app.core import ConfigManager, ToolEntry, ToolType


# 类型图标
TYPE_ICONS = {
    ToolType.JAR.value: "☕",
    ToolType.EXE.value: "⚙️",
    ToolType.PY.value: "🐍",
    ToolType.FTOOLS.value: "📁",
}
TYPE_LABELS = {
    ToolType.JAR.value: "JAR（Java）",
    ToolType.EXE.value: "EXE（Windows）",
    ToolType.PY.value: "PY（Python）",
    ToolType.FTOOLS.value: "Ftools（文件夹）",
}


class ToolEditDialog(tk.Toplevel):
    def __init__(self, parent, config: ConfigManager,
                 tool: ToolEntry | None, on_done,
                 default_category: str = "默认"):
        super().__init__(parent)
        self.config = config
        self.tool = tool
        self.on_done = on_done
        self.title("编辑工具" if tool else "添加工具")
        self.geometry("580x520")
        self.resizable(False, True)
        self.transient(parent)
        self.grab_set()
        self._center_on_parent(parent)
        self._default_category = default_category
        self._vars = {}
        self._type_var = tk.StringVar(value=ToolType.JAR.value)
        self._build()

    def _build(self):
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)

        # ── 基本信息 ──
        ttk.Label(main, text="基本信息", font=("", 9, "bold")).pack(anchor="w")

        row0 = ttk.Frame(main)
        row0.pack(fill="x", pady=4)
        ttk.Label(row0, text="工具类型：").pack(side="left")
        type_frame = ttk.Frame(row0)
        type_frame.pack(side="left", padx=8)
        for t in ToolType:
            rb = ttk.Radiobutton(type_frame, text=f"{TYPE_ICONS[t.value]} {TYPE_LABELS[t.value]}",
                                 variable=self._type_var, value=t.value,
                                 command=self._on_type_change)
            rb.pack(side="left", padx=(0, 6))

        self._vars["name"] = tk.StringVar()
        self._vars["category"] = tk.StringVar(value=self._default_category)
        self._vars["description"] = tk.StringVar()
        self._vars["tool_path"] = tk.StringVar()
        self._vars["working_dir"] = tk.StringVar()
        self._vars["program_args"] = tk.StringVar()
        self._vars["exe_subtype"] = tk.StringVar(value="gui")  # gui / console

        # ── 动态区域 ──
        # 使用单一容器，_refresh_dynamic_ui 每次清空后重建所有内容（含分类/备注）
        self._dynamic_area = ttk.Frame(main)
        self._dynamic_area.pack(fill="both", expand=True)

        # JAR / PY 变量
        self._jdk_var = tk.StringVar()
        self._jvm_var = tk.StringVar()
        self._py_var = tk.StringVar()
        self._venv_var = tk.BooleanVar(value=True)

        # 填充已有数据
        if self.tool:
            self._type_var.set(self.tool.tool_type)
            self._vars["name"].set(self.tool.name)
            self._vars["tool_path"].set(self.tool.tool_path)
            self._vars["category"].set(self.tool.category)
            self._vars["description"].set(self.tool.description)
            self._vars["working_dir"].set(self.tool.working_dir)
            self._vars["program_args"].set(self.tool.program_args)
            self._vars["exe_subtype"].set(getattr(self.tool, "exe_subtype", "gui"))
            if self.tool.tool_type == ToolType.JAR.value:
                self._jvm_var.set(self.tool.jvm_args)

        self._file_filter_map = {
            ToolType.JAR.value: [("JAR 文件", "*.jar"), ("所有文件", "*.*")],
            ToolType.EXE.value: [("EXE 文件", "*.exe"), ("所有文件", "*.*")],
            ToolType.PY.value: [("Python 文件", "*.py"), ("所有文件", "*.*")],
        }

        # 首次构建动态区域
        self._refresh_dynamic_ui()
        self._type_var.trace_add("write", lambda *_: self._refresh_dynamic_ui())
        self._refresh_categories()

        # ── 按钮 ──
        btns = ttk.Frame(main)
        btns.pack(pady=12)
        ttk.Button(btns, text="保存", command=self._save).pack(side="left", padx=8)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=8)

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

    def _on_type_change(self):
        self._refresh_dynamic_ui()

    def _on_exe_subtype_change(self):
        """EXE 子类型切换时无需特殊处理，仅记录值"""
        pass

    def _refresh_dynamic_ui(self):
        """根据工具类型，清空并重建整个动态区域"""
        # 销毁旧的所有子控件
        for w in self._dynamic_area.pack_slaves():
            w.destroy()

        area = self._dynamic_area
        t = self._type_var.get()

        # ── Ftools 类型：提示 + 名称 + 工作目录 ──
        if t == ToolType.FTOOLS.value:
            self._ftools_hint = ttk.Label(area, text="📂 Ftools：点击启动后只打开工作目录，不运行任何程序",
                                          foreground="#8b5cf6", font=("", 9))
            self._ftools_hint.pack(fill="x", pady=(4, 0))

            row_name = ttk.Frame(area)
            row_name.pack(fill="x", pady=3)
            ttk.Label(row_name, text="名称 *：", width=12).pack(side="left")
            ttk.Entry(row_name, textvariable=self._vars["name"], width=38).pack(side="left")

            row_dir = ttk.Frame(area)
            row_dir.pack(fill="x", pady=3)
            ttk.Label(row_dir, text="工作目录 *：", width=12).pack(side="left")
            ttk.Entry(row_dir, textvariable=self._vars["working_dir"], width=38).pack(side="left")
            ttk.Button(row_dir, text="浏览", command=self._browse_dir).pack(side="left", padx=4)

            # 分类
            self._build_cat_row(area)
            # 备注
            self._build_remarks_section(area)
            # 重建控件后刷新分类下拉选项
            self._refresh_categories()
            return

        # ── 非 Ftools：名称 + 文件路径 + ... ──
        row_name = ttk.Frame(area)
        row_name.pack(fill="x", pady=3)
        ttk.Label(row_name, text="名称 *：", width=12).pack(side="left")
        ttk.Entry(row_name, textvariable=self._vars["name"], width=38).pack(side="left")

        row_path = ttk.Frame(area)
        row_path.pack(fill="x", pady=3)
        ttk.Label(row_path, text="文件路径 *：", width=12).pack(side="left")
        ttk.Entry(row_path, textvariable=self._vars["tool_path"], width=38).pack(side="left")
        ttk.Button(row_path, text="浏览", command=self._browse_tool).pack(side="left", padx=4)

        # ── 工作目录行 ──
        row_dir = ttk.Frame(area)
        row_dir.pack(fill="x", pady=3)
        ttk.Label(row_dir, text="工作目录：", width=12).pack(side="left")
        ttk.Entry(row_dir, textvariable=self._vars["working_dir"], width=38).pack(side="left")
        ttk.Button(row_dir, text="浏览", command=self._browse_dir).pack(side="left", padx=4)

        # ── 程序参数行 ──
        row_args = ttk.Frame(area)
        row_args.pack(fill="x", pady=3)
        ttk.Label(row_args, text="程序参数：", width=12).pack(side="left")
        ttk.Entry(row_args, textvariable=self._vars["program_args"], width=38).pack(side="left")

        # ── 分类（紧跟程序参数之后）──
        self._build_cat_row(area)

        # ── 分隔线 ──
        ttk.Separator(area, orient="horizontal").pack(fill="x", pady=8)

        # ── 运行时配置：按类型构建 ──
        if t == ToolType.EXE.value:
            ttk.Label(area, text="EXE 程序类型", font=("", 9, "bold")).pack(anchor="w")
            ttk.Radiobutton(area, text="GUI EXE",
                           variable=self._vars["exe_subtype"], value="gui",
                           command=self._on_exe_subtype_change).pack(anchor="w", padx=16, pady=2)
            ttk.Radiobutton(area, text="命令行 EXE",
                           variable=self._vars["exe_subtype"], value="console",
                           command=self._on_exe_subtype_change).pack(anchor="w", padx=16, pady=2)
            ttk.Label(area, text="提示：命令行 EXE 启动时会在 exe 目录生成 .bat 脚本",
                     foreground="gray", font=("", 8)).pack(anchor="w", padx=16, pady=(0, 2))

        elif t == ToolType.JAR.value:
            ttk.Label(area, text="运行时配置", font=("", 9, "bold")).pack(anchor="w")

            row_jdk = ttk.Frame(area)
            row_jdk.pack(fill="x", pady=2)
            ttk.Label(row_jdk, text="JDK 版本：", width=12).pack(side="left")
            self._jdk_combo = ttk.Combobox(row_jdk, textvariable=self._jdk_var,
                                           state="readonly", width=36)
            self._jdk_combo.pack(side="left")
            self._populate_jdk_combo()

            row_jvm = ttk.Frame(area)
            row_jvm.pack(fill="x", pady=2)
            ttk.Label(row_jvm, text="JVM 参数：", width=12).pack(side="left")
            ttk.Entry(row_jvm, textvariable=self._jvm_var, width=38).pack(side="left")

        elif t == ToolType.PY.value:
            ttk.Label(area, text="运行时配置", font=("", 9, "bold")).pack(anchor="w")

            row_py = ttk.Frame(area)
            row_py.pack(fill="x", pady=2)
            ttk.Label(row_py, text="Python 版本：", width=12).pack(side="left")
            self._py_combo = ttk.Combobox(row_py, textvariable=self._py_var,
                                          state="readonly", width=36)
            self._py_combo.pack(side="left")
            self._populate_py_combo()

            ttk.Checkbutton(area, text="启用虚拟环境隔离（推荐）",
                           variable=self._venv_var).pack(anchor="w", padx=16, pady=2)

        # ── 备注大类（所有非 Ftools 类型都有）──
        self._build_remarks_section(area)

        # 重建控件后刷新分类下拉选项
        self._refresh_categories()

    def _build_cat_row(self, parent):
        """构建分类行（不含备注）"""
        cat_row = ttk.Frame(parent)
        cat_row.pack(fill="x", pady=3)
        ttk.Label(cat_row, text="分类：", width=12).pack(side="left")
        self._cat_combo = ttk.Combobox(cat_row, textvariable=self._vars["category"], width=36)
        self._cat_combo.pack(side="left")

    def _build_remarks_section(self, parent):
        """构建备注大类（独立标题 + 输入框，适配窗口宽度）"""
        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=8)
        ttk.Label(parent, text="备注", font=("", 9, "bold")).pack(anchor="w")
        desc_frame = ttk.Frame(parent)
        desc_frame.pack(fill="x", pady=4)
        desc_frame.columnconfigure(0, weight=1)
        desc_entry = ttk.Entry(desc_frame, textvariable=self._vars["description"])
        desc_entry.grid(row=0, column=0, sticky="ew")

    def _populate_jdk_combo(self):
        jdks = self.config.list_jdks()
        names = [f"{j.name}  ({j.version})" for j in jdks]
        self._jdk_combo.configure(values=names)
        if self.tool and self.tool.jdk_id:
            ids = [j.id for j in jdks]
            if self.tool.jdk_id in ids:
                self._jdk_var.set(names[ids.index(self.tool.jdk_id)])
        elif names:
            self._jdk_var.set(names[0])

    def _populate_py_combo(self):
        pythons = self.config.list_pythons()
        names = [f"{p.name}  ({p.version})" for p in pythons]
        self._py_combo.configure(values=names)
        if self.tool and self.tool.runtime_id:
            ids = [p.id for p in pythons]
            if self.tool.runtime_id in ids:
                self._py_var.set(names[ids.index(self.tool.runtime_id)])
        elif names:
            self._py_var.set(names[0])

    def _refresh_categories(self):
        cats = self.config.list_categories()
        self._cat_combo.configure(values=cats)

    def _browse_tool(self):
        t = self._type_var.get()
        ft = self._file_filter_map.get(t, [("所有文件", "*.*")])
        path = filedialog.askopenfilename(parent=self, title="选择文件", filetypes=ft)
        if path:
            self._vars["tool_path"].set(path)
            if not self._vars["name"].get():
                self._vars["name"].set(Path(path).stem)

    def _browse_dir(self):
        path = filedialog.askdirectory(parent=self, title="选择工作目录")
        if path:
            self._vars["working_dir"].set(path)

    def _save(self):
        t = self._type_var.get()
        name = self._vars["name"].get().strip()
        tool_path = self._vars["tool_path"].get().strip()
        category = self._vars["category"].get().strip() or "默认"
        work_dir = self._vars["working_dir"].get().strip()
        prog_args = self._vars["program_args"].get().strip()
        desc = self._vars["description"].get().strip()

        if not name:
            messagebox.showwarning("提示", "名称为必填项", parent=self)
            return

        # Ftools 类型只需要名称和工作目录
        if t == ToolType.FTOOLS.value:
            if not work_dir:
                messagebox.showwarning("提示", "Ftools 类型需要填写工作目录", parent=self)
                return
        elif not tool_path:
            messagebox.showwarning("提示", "文件路径为必填项", parent=self)
            return

        # 解析运行时 ID
        jdk_id = ""
        runtime_id = ""
        jvm_args = ""
        use_venv = True
        exe_subtype = self._vars["exe_subtype"].get()

        if t == ToolType.JAR.value:
            jdks = self.config.list_jdks()
            sel = self._jdk_var.get()
            ids = [j.id for j in jdks]
            names = [f"{j.name}  ({j.version})" for j in jdks]
            if sel in names and ids:
                jdk_id = ids[names.index(sel)]
            jvm_args = self._jvm_var.get().strip()
        elif t == ToolType.PY.value:
            pythons = self.config.list_pythons()
            sel = self._py_var.get()
            ids = [p.id for p in pythons]
            names = [f"{p.name}  ({p.version})" for p in pythons]
            if sel in names and ids:
                runtime_id = ids[names.index(sel)]
            use_venv = self._venv_var.get()

        if self.tool:
            self.tool.name = name
            self.tool.tool_type = t
            self.tool.tool_path = tool_path
            self.tool.category = category
            self.tool.jdk_id = jdk_id
            self.tool.runtime_id = runtime_id
            self.tool.jvm_args = jvm_args
            self.tool.use_venv = use_venv
            self.tool.exe_subtype = exe_subtype
            self.tool.program_args = prog_args
            self.tool.description = desc
            self.tool.working_dir = work_dir
            self.config.update_tool(self.tool)
        else:
            self.config.add_tool(
                name=name, tool_type=t, tool_path=tool_path,
                category=category, jdk_id=jdk_id, runtime_id=runtime_id,
                jvm_args=jvm_args, use_venv=use_venv,
                exe_subtype=exe_subtype,
                program_args=prog_args, description=desc, working_dir=work_dir,
            )

        self.on_done()
        self.destroy()
