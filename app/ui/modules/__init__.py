"""
功能模块包 - LingTai 模块化架构

每个功能模块继承 BaseModule，由 MainWindow 统一管理和切换。
新增模块步骤：
1. 在 modules/ 下创建模块文件，继承 BaseModule
2. 在此文件的 MODULE_REGISTRY 中按显示顺序注册
"""
from app.ui.modules.base import BaseModule
from app.ui.modules.toolbox import ToolboxModule
from app.ui.modules.placeholder import PlaceholderModule

# 模块注册表（按顺序显示在导航栏）
MODULE_REGISTRY = [
    ToolboxModule,
    PlaceholderModule,
]

__all__ = ["BaseModule", "ToolboxModule", "PlaceholderModule", "MODULE_REGISTRY"]
