"""
功能模块基类 - 所有模块的统一接口

子类必须实现：
  - title: 模块显示名称
  - icon: 模块图标（emoji）
  - activate(): 模块被切换到时调用（可选重写）
  - deactivate(): 模块被切走时调用（可选重写）
"""
import tkinter as tk


class BaseModule(tk.Frame):
    """功能模块基类"""

    # 子类必须覆盖这两个类属性
    title: str = "未命名模块"
    icon: str = "📦"

    def __init__(self, parent, app, **kwargs):
        """
        Args:
            parent: 父容器（MainWindow 的模块容器）
            app: MainWindow 实例，提供 config / engine / log_mgr 等共享资源
        """
        super().__init__(parent, **kwargs)
        self.app = app

    def activate(self):
        """模块被切换到前台时调用（可选重写）"""
        pass

    def deactivate(self):
        """模块被切换到后台时调用（可选重写）"""
        pass

    @property
    def display_name(self) -> str:
        """导航栏上显示的完整名称"""
        return f"{self.icon}  {self.title}"
