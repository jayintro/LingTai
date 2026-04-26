"""
扩展功能占位模块 - 后续功能扩展模板

复制此文件作为新模块的起点：
1. 重命名文件和类
2. 修改 title / icon
3. 在 modules/__init__.py 的 MODULE_REGISTRY 中注册
4. 实现 _build_ui() 构建模块界面
"""
from tkinter import ttk

from app.ui.modules.base import BaseModule


class PlaceholderModule(BaseModule):
    """扩展功能占位模块"""

    title = "更多"
    icon = "✨"

    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, app, **kwargs)
        self._build_ui()

    def _build_ui(self):
        """构建模块界面"""
        center = ttk.Frame(self)
        center.place(relx=0.5, rely=0.5, anchor="center")

        ttk.Label(center, text="🚀",
                  font=("", 36)).pack(pady=(0, 12))
        ttk.Label(center, text="更多功能即将推出",
                  font=("", 14, "bold")).pack()
        ttk.Label(center, text="后续版本将在此处添加新功能模块",
                  font=("", 10), foreground="#888").pack(pady=(4, 0))

    def activate(self):
        pass

    def deactivate(self):
        pass
