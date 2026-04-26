"""
通用工具函数 - 全项目复用
"""
import re

# 文件名安全化：替换 Windows 非法字符为下划线
_UNSAFE_CHARS_RE = re.compile(r'[<>:"/\\|?*]')


def safe_filename(name: str) -> str:
    """将工具名称转换为安全的文件名（替换 Windows 非法字符）"""
    return _UNSAFE_CHARS_RE.sub('_', name)
