"""
启动引擎 - 支持 JAR / EXE / PY 三种工具类型
PY 工具使用独立虚拟环境隔离
"""
import os
import re
import shlex
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

from app.core.config_manager import ConfigManager
from app.core.models import ProcessStatus, RunRecord, ToolEntry, ToolType
from app.core.logger import LogManager
from app.core.runtime_manager import RuntimeManager
from app.core.utils import safe_filename


class ProcessHandle:
    """单个运行中进程的句柄"""

    def __init__(self, tool: ToolEntry, process: subprocess.Popen,
                 log_file: str, record: RunRecord):
        self.tool = tool
        self.process = process
        self.log_file = log_file
        self.record = record
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        # 依赖补装相关
        self._dep_fix_attempted: bool = False   # 是否已尝试过依赖补装（只允许一次）
        self._dep_fix_callback: Optional[Callable] = None  # 补装进度回调


class LaunchEngine:
    """统一启动引擎"""

    # 文件名安全化：委托到公共工具函数，保持向后兼容
    _UNSAFE_CHARS_RE = re.compile(r'[<>:"/\\|?*]')

    @staticmethod
    def _safe_filename(name: str) -> str:
        """将工具名称转换为安全的文件名（替换 Windows 非法字符）"""
        return safe_filename(name)

    @staticmethod
    def _bat_escape(s: str) -> str:
        """转义 bat 文件中的特殊字符"""
        s = s.replace("^", "^^")
        for ch in ('&', '|', '<', '>', '%'):
            s = s.replace(ch, f"^{ch}")
        return s

    def __init__(self, config_mgr: ConfigManager, log_mgr: "LogManager",
                 logs_dir: str = "logs"):
        self.config = config_mgr
        self.log_mgr = log_mgr
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._handles: Dict[str, ProcessHandle] = {}
        self._status_callbacks: list[Callable] = []
        self._init_callbacks: Dict[str, Callable] = {}
        # 初始化锁：防止同一工具并发重复初始化（导致 venv 被删重建）
        self._init_locks: Dict[str, threading.Lock] = {}

    def set_init_log_callback(self, tool_id: str, callback: Callable[[str], None]):
        """注册初始化日志回调，实时显示 venv/依赖安装进度"""
        self._init_callbacks[tool_id] = callback

    def set_dep_fix_callback(self, tool_id: str, callback: Callable[[str], None]):
        """注册依赖补装回调，实时显示 ModuleNotFoundError 后的补装进度"""
        handle = self._handles.get(tool_id)
        if handle:
            handle._dep_fix_callback = callback

    def _emit_init_log(self, tool_id: str, msg: str):
        if tool_id in self._init_callbacks:
            self._init_callbacks[tool_id](msg)

    def on_status_change(self, fn: Callable):
        self._status_callbacks.append(fn)

    def _notify(self, tool_id: str, status: ProcessStatus):
        for fn in self._status_callbacks:
            try:
                fn(tool_id, status)
            except Exception:
                pass

    # ─── 统一启动入口 ───────────────────────────────────────────

    def launch(self, tool_id: str) -> bool:
        """
        启动指定工具（自动识别类型）。
        返回 True 表示启动成功，抛出异常表示失败。
        """
        if self.is_running(tool_id):
            return False

        tool = self.config.get_tool(tool_id)
        if not tool:
            raise ValueError(f"找不到工具配置：{tool_id}")

        ttype = ToolType(tool.tool_type)
        if ttype == ToolType.JAR:
            return self._launch_jar(tool)
        elif ttype == ToolType.EXE:
            return self._launch_exe(tool)
        elif ttype == ToolType.PY:
            return self._launch_py(tool)
        elif ttype == ToolType.FTOOLS:
            return self._open_dir(tool)
        else:
            raise ValueError(f"不支持的工具类型：{tool.tool_type}")

    # ─── Ftools（只打开目录）────────────────────────────────────

    def _open_dir(self, tool: ToolEntry) -> bool:
        """Ftools 类型：只打开工作目录
        注意：资源管理器窗口无法被进程跟踪，因此状态为瞬时 RUNNING → STOPPED
        """
        work_dir = tool.working_dir.strip()
        if not work_dir or not Path(work_dir).exists():
            raise FileNotFoundError(f"工作目录不存在：{work_dir}")

        if os.name == "nt":
            os.startfile(work_dir)
        else:
            subprocess.Popen(["xdg-open", work_dir])

        # 记录 RUNNING 状态
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = self._safe_filename(tool.name)
        log_path = str(self.logs_dir / f"{safe_name}_{ts}.log")
        record = RunRecord(
            tool_id=tool.id, tool_name=tool.name,
            started_at=datetime.now().isoformat(),
            status=ProcessStatus.RUNNING.value,
            log_file=log_path,
        )
        # Ftools 无子进程可跟踪，process 设为 None
        handle = ProcessHandle(tool, None, log_path, record)
        self._handles[tool.id] = handle
        self._notify(tool.id, ProcessStatus.RUNNING)

        # 资源管理器窗口无法跟踪关闭时机，延迟后自动变为 STOPPED
        def auto_stop():
            time.sleep(1.5)
            record.ended_at = datetime.now().isoformat()
            record.status = ProcessStatus.STOPPED.value
            self.log_mgr.append_run_record(record)
            self._handles.pop(tool.id, None)
            self._notify(tool.id, ProcessStatus.STOPPED)

        threading.Thread(target=auto_stop, daemon=True).start()
        return True

    # ─── JAR ────────────────────────────────────────────────────

    def _launch_jar(self, tool: ToolEntry) -> bool:
        jdk = self.config.get_jdk(tool.jdk_id)
        if not jdk:
            raise ValueError(f"找不到 JDK 配置（{tool.jdk_id}），请先在运行环境中添加 JDK。")
        if not Path(jdk.java_path).exists():
            raise FileNotFoundError(f"java 可执行文件不存在：{jdk.java_path}")
        if not Path(tool.tool_path).exists():
            raise FileNotFoundError(f"JAR 文件不存在：{tool.tool_path}")

        cmd = [jdk.java_path]
        if tool.jvm_args.strip():
            jvm_parts = shlex.split(tool.jvm_args)
            # 校验 JVM 参数：必须以 - 开头且紧跟字母，防止命令注入
            for arg in jvm_parts:
                if arg.startswith("-") and len(arg) > 1 and not arg[1].isalpha():
                    raise ValueError(f"JVM 参数包含非法值：{arg}\n"
                                     f"仅允许标准 JVM 选项（如 -Xmx, -Dkey=val），不允许 shell 元字符。")
            cmd += jvm_parts
        cmd += ["-jar", tool.tool_path]
        if tool.program_args.strip():
            cmd += shlex.split(tool.program_args)

        cwd = tool.working_dir.strip() or str(Path(tool.tool_path).parent)
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._do_start(tool, cmd, cwd, creationflags=creationflags)
        return True

    # ─── EXE ────────────────────────────────────────────────────

    def _launch_exe(self, tool: ToolEntry) -> bool:
        if not Path(tool.tool_path).exists():
            raise FileNotFoundError(f"EXE 文件不存在：{tool.tool_path}")

        exe_dir = str(Path(tool.tool_path).parent)
        cwd = tool.working_dir.strip() or exe_dir

        args = []
        if tool.program_args.strip():
            args = shlex.split(tool.program_args)

        exe_subtype = getattr(tool, "exe_subtype", "gui")

        if exe_subtype == "console":
            # 命令行程序：生成 .bat 脚本，用 cmd /k 启动（窗口保持打开）
            safe_name = self._safe_filename(tool.name)
            bat_name = f"{safe_name}_launcher.bat"
            bat_path = Path(exe_dir) / bat_name

            # 构建 bat 内容（cmd /k 保持窗口不关闭）
            # 所有参数加引号并转义 cmd 特殊字符，防止路径/参数注入
            exe_path_escaped = self._bat_escape(tool.tool_path)
            if args:
                args_escaped = " ".join(f'"{self._bat_escape(a)}"' for a in args)
                # cmd /k 的引号规则：如果路径含空格需引号，则整个命令外层要再包一对引号
                # 即 cmd /k ""C:\path\to\exe" arg1 arg2" → cmd 把 ""C:\path\to\exe" arg1 arg2" 当作完整命令
                bat_content = f'@echo off\ncmd /k ""{exe_path_escaped}" {args_escaped}"\n'
            else:
                bat_content = f'@echo off\ncmd /k ""{exe_path_escaped}""\n'

            bat_path.write_text(bat_content, encoding="utf-8")

            # cmd /c start /wait "" "bat路径"：
            #   start /wait 让 cmd.exe 阻塞等待新窗口关闭才返回，
            #   这样 process.wait() 能正确跟踪"窗口打开=运行中，窗口关闭=已停止"
            cmd = ["cmd", "/c", "start", "/wait", "", str(bat_path)]
            self._do_start(tool, cmd, cwd, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            # GUI 程序：直接启动，隐藏控制台
            cmd = [tool.tool_path] + args
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self._do_start(tool, cmd, cwd, creationflags=creationflags)

        return True

    # ─── PY ─────────────────────────────────────────────────────

    def _launch_py(self, tool: ToolEntry) -> bool:
        python_cfg = self.config.get_python(tool.runtime_id)
        if not python_cfg:
            raise ValueError(f"找不到 Python 运行时配置，请先在运行环境中添加。")
        if not Path(python_cfg.python_path).exists():
            raise FileNotFoundError(f"Python 可执行文件不存在：{python_cfg.python_path}")
        if not Path(tool.tool_path).exists():
            raise FileNotFoundError(f"PY 文件不存在：{tool.tool_path}")

        tool_dir = tool.working_dir.strip() or str(Path(tool.tool_path).parent)

        # 初始化虚拟环境 + 依赖（带锁，防止并发重复初始化）
        rt_mgr = RuntimeManager(
            log_callback=lambda msg, tid=tool.id: self._emit_init_log(tid, msg)
        )

        # 确定 Python 可执行文件路径（仅 use_venv 时才用 venv python）
        python_exec = (
            str(rt_mgr.get_venv_python(tool_dir))
            if tool.use_venv else python_cfg.python_path
        )

        if tool.use_venv:
            # 获取或创建该工具的初始化锁，防止并发重复初始化
            if tool.id not in self._init_locks:
                self._init_locks[tool.id] = threading.Lock()
            lock = self._init_locks[tool.id]

            if lock.acquire(blocking=False):
                # 拿到锁：执行初始化
                try:
                    def dep_progress(msg, done, total):
                        self._emit_init_log(tool.id, f"[进度] {done}/{total} {msg}")
                    ready = rt_mgr.ensure_ready(tool_dir, python_cfg, on_dep_status=dep_progress,
                                                tool_path=tool.tool_path)
                    if not ready:
                        raise RuntimeError("虚拟环境初始化失败，请查看上方日志")
                finally:
                    lock.release()
            else:
                # 未拿到锁：另一个线程正在初始化，等待完成后直接启动
                self._emit_init_log(tool.id, "[信息] 初始化已在进行中，等待完成...")
                lock.acquire(blocking=True)
                lock.release()
                self._emit_init_log(tool.id, "[信息] 初始化已完成，启动工具...")
        else:
            # 无 venv 模式：直接用系统 Python 跳过 venv
            self._emit_init_log(tool.id, "[信息] 使用系统 Python 运行（无虚拟环境隔离）")

        # 用 bat 包装，保持独立窗口在程序结束后不关闭（pause 等待用户查看结果）
        # bat 生成在工具目录下，不积累在 logs 里
        safe_name = self._safe_filename(tool.name)
        bat_path = Path(tool_dir) / f"{safe_name}_launcher.bat"
        err_log_path = Path(tool_dir) / f"{safe_name}_error.log"

        # 生成 Python wrapper 脚本：
        # - tee stderr：同时输出到窗口和 error.log 文件
        # - 捕获 ModuleNotFoundError → exit(42) 触发 bat 依赖补装流程
        # - 使用 runpy.run_path 运行目标脚本，保证 __name__="__main__" 和正常 import 行为
        wrapper_path = Path(tool_dir) / f"{safe_name}_wrapper.py"
        err_log_name = err_log_path.name
        target_path = tool.tool_path
        prog_args_list = shlex.split(tool.program_args) if tool.program_args.strip() else []

        wrapper_code = (
            '"""Auto-generated launcher wrapper - detects missing dependencies"""\n'
            'import sys\n'
            'import os\n'
            '\n'
            '# stderr tee: 同时输出到窗口和日志文件\n'
            f'_err_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), {repr(err_log_name)})\n'
            '\n'
            'class _TeeStderr:\n'
            '    def __init__(self, original, log_path):\n'
            '        self._original = original\n'
            '        self._log_file = None\n'
            '        try:\n'
            '            self._log_file = open(log_path, "w", encoding="utf-8", errors="replace")\n'
            '        except Exception:\n'
            '            pass\n'
            '\n'
            '    def write(self, data):\n'
            '        self._original.write(data)\n'
            '        self._original.flush()\n'
            '        if self._log_file and data:\n'
            '            try:\n'
            '                self._log_file.write(data)\n'
            '                self._log_file.flush()\n'
            '            except Exception:\n'
            '                pass\n'
            '\n'
            '    def flush(self):\n'
            '        self._original.flush()\n'
            '        if self._log_file:\n'
            '            try:\n'
            '                self._log_file.flush()\n'
            '            except Exception:\n'
            '                pass\n'
            '\n'
            '    def fileno(self):\n'
            '        return self._original.fileno()\n'
            '\n'
            '    def isatty(self):\n'
            '        return self._original.isatty()\n'
            '\n'
            '    def __getattr__(self, name):\n'
            '        return getattr(self._original, name)\n'
            '\n'
            'sys.stderr = _TeeStderr(sys.stderr, _err_log)\n'
            '\n'
            '# 运行目标脚本\n'
            f'_target = {repr(target_path)}\n'
            f'_args = {repr(prog_args_list)}\n'
            'sys.argv = [_target] + _args\n'
            '\n'
            'try:\n'
            '    import runpy\n'
            '    runpy.run_path(_target, run_name="__main__")\n'
            'except (ModuleNotFoundError, ImportError) as _e:\n'
            '    _mod_name = str(getattr(_e, "name", "") or getattr(_e, "msg", "") or "").split(".")[0]\n'
            '    if not _mod_name:\n'
            '        _mod_name = "unknown"\n'
            '    print(f"\\n[依赖缺失] {type(_e).__name__}: No module named \'{_mod_name}\'", file=sys.stderr)\n'
            '    print("[提示] 请返回主窗口查看补装进度，本窗口将自动关闭", file=sys.stderr)\n'
            '    sys.stderr.flush()\n'
            '    sys.exit(42)\n'
        )
        wrapper_path.write_text(wrapper_code, encoding="utf-8")

        # bat 内容：
        # 1. 清空旧错误日志
        # 2. 运行 wrapper（stdout/stderr 都正常显示到窗口）
        # 3. 如果 exit code == 42 → 依赖缺失，3 秒后自动关闭
        # 4. 否则正常 pause
        bat_content = "@echo off\n"
        bat_content += f'del /q "{self._bat_escape(str(err_log_path))}" 2>nul\n'
        bat_content += f'"{self._bat_escape(python_exec)}" "{self._bat_escape(str(wrapper_path))}"\n'
        bat_content += f'set _EXIT_CODE=%errorlevel%\n'
        bat_content += f'if %_EXIT_CODE%==42 (\n'
        bat_content += f'  timeout /t 3 /nobreak ^>nul\n'
        bat_content += f'  exit 1\n'
        bat_content += f')\n'
        bat_content += "pause\n"
        bat_path.write_text(bat_content, encoding="utf-8")

        # cmd /c start /wait "" bat路径：
        #   start /wait 让 cmd.exe 阻塞等待新窗口关闭才返回，
        #   这样 process.wait() 能正确跟踪"窗口打开=运行中，窗口关闭=已停止"
        #   CREATE_NO_WINDOW 防止父 cmd 产生额外窗口
        cmd = ["cmd", "/c", "start", "/wait", "", str(bat_path)]
        self._do_start(tool, cmd, tool_dir, creationflags=subprocess.CREATE_NO_WINDOW)

        # 启动 error.log 监控线程：将工具目录下的错误日志同步到引擎日志文件
        # 这样用户在主窗口点击"查看日志"时能看到错误内容
        handle = self._handles.get(tool.id)
        if handle:
            self._start_errlog_monitor(handle, err_log_path)

        return True

    # ─── 通用进程启动 ───────────────────────────────────────────

    def _do_start(self, tool: ToolEntry, cmd: list, cwd: str,
                  creationflags: int = 0):
        """通用进程启动逻辑"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = self._safe_filename(tool.name)
        log_path = str(self.logs_dir / f"{safe_name}_{ts}.log")

        started_at = datetime.now().isoformat()
        record = RunRecord(
            tool_id=tool.id, tool_name=tool.name,
            started_at=started_at,
            status=ProcessStatus.STARTING.value,
            log_file=log_path,
        )

        # 控制台程序需要独立控制台窗口，不重定向输出
        use_console = bool(creationflags & subprocess.CREATE_NEW_CONSOLE)
        try:
            if use_console:
                # 有控制台窗口：不重定向，进程拥有自己的终端
                proc = subprocess.Popen(
                    cmd, cwd=cwd,
                    creationflags=creationflags,
                )
            else:
                # 无控制台窗口：重定向 stdout/stderr 用于日志记录
                proc = subprocess.Popen(
                    cmd, cwd=cwd,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=creationflags,
                )
        except Exception as e:
            record.status = ProcessStatus.ERROR.value
            record.ended_at = datetime.now().isoformat()
            self.log_mgr.append_run_record(record)
            raise RuntimeError(f"启动失败：{e}") from e

        record.pid = proc.pid
        record.status = ProcessStatus.RUNNING.value
        handle = ProcessHandle(tool, proc, log_path, record)
        self._handles[tool.id] = handle
        self._start_log_threads(handle)
        self._notify(tool.id, ProcessStatus.RUNNING)

    # ─── 日志采集 ────────────────────────────────────────────────

    def _start_log_threads(self, handle: ProcessHandle):
        def collect(stream, prefix: str):
            if stream is None:
                return
            try:
                with open(handle.log_file, "a", encoding="utf-8") as f:
                    for line in stream:
                        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        f.write(f"[{ts}] {prefix}{line}")
                        f.flush()
            except Exception:
                pass

        def watch_exit():
            handle.process.wait()
            exit_code = handle.process.returncode
            handle.record.ended_at = datetime.now().isoformat()
            handle.record.exit_code = exit_code
            status = (ProcessStatus.STOPPED if exit_code == 0
                      else ProcessStatus.ERROR)
            handle.record.status = status.value
            self.log_mgr.append_run_record(handle.record)
            self._handles.pop(handle.tool.id, None)
            self._notify(handle.tool.id, status)

        t1 = threading.Thread(target=collect, args=(handle.process.stdout, ""),
                             daemon=True)
        t2 = threading.Thread(target=collect, args=(handle.process.stderr, "[ERR] "),
                             daemon=True)
        t3 = threading.Thread(target=watch_exit, daemon=True)
        handle._stdout_thread = t1
        handle._stderr_thread = t2
        t1.start(); t2.start(); t3.start()

    def _start_errlog_monitor(self, handle: ProcessHandle, err_log_path: Path):
        """
        监控工具目录下的 _error.log 文件，将内容同步写入引擎日志文件。
        解决 PY 工具通过 bat 窗口启动时，引擎日志文件为空的问题。
        """
        def monitor():
            last_pos = 0
            try:
                while True:
                    # 进程已退出 → 延迟后做最后一次读取再停止
                    if handle.process.poll() is not None:
                        time.sleep(0.5)  # 等待 error.log 写入完成
                        self._read_errlog_tail(handle, err_log_path, last_pos)
                        break
                    if err_log_path.exists():
                        last_pos = self._read_errlog_tail(handle, err_log_path, last_pos)
                    time.sleep(2)
            except Exception:
                pass

        threading.Thread(target=monitor, daemon=True).start()

    def _read_errlog_tail(self, handle: ProcessHandle, err_log_path: Path,
                          last_pos: int) -> int:
        """读取 err_log_path 从 last_pos 开始的新内容，追加到引擎日志"""
        try:
            with open(err_log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(last_pos)
                new_content = f.read()
                if new_content:
                    with open(handle.log_file, "a", encoding="utf-8") as log_f:
                        for line in new_content.splitlines():
                            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                            log_f.write(f"[{ts}] [ERR] {line}\n")
                        log_f.flush()
                    return f.tell()
        except Exception:
            pass
        return last_pos

    # ─── 运行时依赖补装 ──────────────────────────────────────────────

    def _try_fix_missing_dep(self, handle: ProcessHandle, module_name: str):
        """
        检测到 ModuleNotFoundError 后自动补装缺失依赖并重启工具。
        仅在 use_venv=True 时启用，且每个进程只允许补装一次。
        """
        tool = handle.tool
        # 标记已尝试补装，防止无限循环
        handle._dep_fix_attempted = True
        # 仅 PY + use_venv 类型支持自动补装
        if ToolType(tool.tool_type) != ToolType.PY or not tool.use_venv:
            return

        tool_dir = tool.working_dir.strip() or str(Path(tool.tool_path).parent)
        python_cfg = self.config.get_python(tool.runtime_id)
        if not python_cfg:
            return

        rt_mgr = RuntimeManager(
            log_callback=lambda msg, tid=tool.id: self._emit_init_log(tid, msg)
        )

        # 补装日志回调
        def on_dep_fix_log(msg: str):
            self._emit_init_log(tool.id, msg)
            if handle._dep_fix_callback:
                try:
                    handle._dep_fix_callback(msg)
                except Exception:
                    pass

        on_dep_fix_log(f"[依赖补充] 检测到缺失模块 '{module_name}'，正在自动补装...")

        # 执行补装
        success, pkg_name = rt_mgr.install_missing_package(
            tool_dir, module_name, on_log=on_dep_fix_log
        )

        if not success:
            on_dep_fix_log(f"[依赖补充] 自动补装 '{pkg_name}' 失败，请手动安装")
            return

        on_dep_fix_log(f"[依赖补充] '{pkg_name}' 安装成功，正在重启工具...")

        # 等待旧进程结束
        try:
            handle.process.wait(timeout=5)
        except Exception:
            handle.process.kill()

        # 清理旧 handle
        self._handles.pop(tool.id, None)

        # 重启工具（在新线程中，避免阻塞 stderr 收集线程）
        def relaunch():
            try:
                self.launch(tool.id)
                on_dep_fix_log("[依赖补充] 工具已重启")
            except Exception as e:
                on_dep_fix_log(f"[依赖补充] 重启失败：{e}")

        threading.Thread(target=relaunch, daemon=True).start()

    # ─── 停止 ────────────────────────────────────────────────────

    def stop(self, tool_id: str):
        handle = self._handles.get(tool_id)
        if not handle or handle.process is None:
            return
        try:
            handle.process.terminate()
        except Exception:
            pass

    def force_kill(self, tool_id: str):
        handle = self._handles.get(tool_id)
        if not handle or handle.process is None:
            return
        try:
            handle.process.kill()
        except Exception:
            pass

    # ─── 查询 ────────────────────────────────────────────────────

    def is_running(self, tool_id: str) -> bool:
        handle = self._handles.get(tool_id)
        if not handle:
            return False
        # Ftools 的 process 为 None，状态由 auto_stop 管理
        if handle.process is None:
            return True
        return handle.process.poll() is None

    def get_status(self, tool_id: str) -> ProcessStatus:
        return ProcessStatus.RUNNING if self.is_running(tool_id) else ProcessStatus.STOPPED

    def get_log_file(self, tool_id: str) -> Optional[str]:
        handle = self._handles.get(tool_id)
        return handle.log_file if handle else None

    def running_tool_ids(self) -> list:
        return [tid for tid in list(self._handles) if self.is_running(tid)]

    def stop_all(self):
        for tid in list(self._handles):
            self.stop(tid)
