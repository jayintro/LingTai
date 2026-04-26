"""
数据模型定义 - 工具启动器（支持 JAR / EXE / PY）
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List


class ProcessStatus(Enum):
    """进程运行状态"""
    STOPPED = "已停止"
    RUNNING = "运行中"
    ERROR = "异常退出"
    STARTING = "启动中"


class ToolType(Enum):
    """工具类型"""
    JAR = "jar"
    EXE = "exe"
    PY = "py"
    FTOOLS = "ftools"  # 只打开目录的工具


# ─── JDK / Python 运行时配置 ───────────────────────────────────────

@dataclass
class JdkConfig:
    """JDK配置"""
    id: str
    name: str
    version: str
    java_path: str
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "version": self.version,
            "java_path": self.java_path, "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "JdkConfig":
        return cls(**d)


@dataclass
class PythonConfig:
    """Python 运行时配置"""
    id: str
    name: str              # 显示名称，如 "Python 3.11"
    version: str           # 版本号
    python_path: str        # python.exe 完整路径
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "version": self.version,
            "python_path": self.python_path, "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PythonConfig":
        return cls(**d)


# ─── 工具条目（统一 JAR / EXE / PY） ────────────────────────────────

class ExeSubtype(Enum):
    """EXE 子类型"""
    GUI = "gui"       # GUI 程序，自带窗口
    CONSOLE = "console"  # 命令行程序，需命令行窗口


@dataclass
class ToolEntry:
    """工具条目（统一模型）"""
    id: str
    name: str               # 显示名称
    tool_path: str = ""     # JAR / EXE / PY 文件路径（Ftools 类型可为空）
    category: str = "默认"   # 所属分类
    tool_type: str = ToolType.JAR.value  # ToolType 值：jar / exe / py / ftools
    # JAR
    jdk_id: str = ""        # 绑定的 JDK id（仅 JAR 使用）
    jvm_args: str = ""      # JVM 参数（仅 JAR 使用）
    # EXE
    exe_subtype: str = ExeSubtype.GUI.value  # EXE 子类型：gui / console（仅 EXE 使用）
    # EXE / PY
    runtime_id: str = ""    # 绑定的 Python id（仅 EXE/PY 使用）
    use_venv: bool = True   # 是否使用虚拟环境隔离（仅 PY 使用）
    # 通用
    program_args: str = ""   # 程序/脚本启动参数
    description: str = ""
    working_dir: str = ""   # 工作目录，留空自动用文件所在目录
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "tool_path": self.tool_path,
            "category": self.category, "tool_type": self.tool_type,
            "jdk_id": self.jdk_id, "jvm_args": self.jvm_args,
            "exe_subtype": self.exe_subtype,
            "runtime_id": self.runtime_id, "use_venv": self.use_venv,
            "program_args": self.program_args, "description": self.description,
            "working_dir": self.working_dir,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ToolEntry":
        # 向后兼容旧数据（JAR 类型只有 jar_path）
        if "jar_path" in d and "tool_path" not in d:
            d["tool_path"] = d.pop("jar_path")

        # 字段名兼容：jdk_args → jvm_args
        if "jdk_args" in d and "jvm_args" not in d:
            d["jvm_args"] = d.pop("jdk_args")

        # 补充必填字段的默认值（防止旧 jars.json 缺失字段）
        if "tool_type" not in d:
            d["tool_type"] = ToolType.JAR.value
        if "exe_subtype" not in d:
            d["exe_subtype"] = ExeSubtype.GUI.value
        if "id" not in d:
            import uuid
            d["id"] = str(uuid.uuid4())

        # 过滤掉未知字段（防止旧数据中的废弃字段导致报错）
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        d = {k: v for k, v in d.items() if k in valid_fields}

        return cls(**d)


# ─── 运行记录 ─────────────────────────────────────────────────────

@dataclass
class RunRecord:
    """运行记录"""
    tool_id: str
    tool_name: str
    started_at: str
    status: str = ProcessStatus.STOPPED.value
    ended_at: Optional[str] = None
    exit_code: Optional[int] = None
    log_file: str = ""
    pid: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "tool_id": self.tool_id, "tool_name": self.tool_name,
            "started_at": self.started_at, "status": self.status,
            "ended_at": self.ended_at, "exit_code": self.exit_code,
            "log_file": self.log_file, "pid": self.pid,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RunRecord":
        return cls(**d)
