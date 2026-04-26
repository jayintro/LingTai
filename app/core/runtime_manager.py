"""
Python 运行环境管理器
- 创建 / 删除虚拟环境
- 自动检测并安装依赖（requirements.txt / pyproject.toml）
- 依赖安装到工具目录下的 .venv/
"""
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from app.core.models import PythonConfig


class RuntimeManager:
    """Python 虚拟环境和依赖管理"""

    VENV_DIR = ".venv"          # 虚拟环境目录名（放在工具文件夹内）
    VENV_PYTHON = "Scripts\\python.exe" if os.name == "nt" else "bin/python"

    def __init__(self, log_callback=None):
        # log_callback: fn(message: str) 用于将安装日志写回 UI
        self._log = log_callback or (lambda x: None)
        self.MODULE_TO_PACKAGE = self._load_module_map()

    # ─── 虚拟环境 ────────────────────────────────────────────────

    def get_venv_path(self, tool_dir: str) -> Path:
        return Path(tool_dir) / self.VENV_DIR

    def get_venv_python(self, tool_dir: str) -> Path:
        return self.get_venv_path(tool_dir) / self.VENV_PYTHON

    def venv_exists(self, tool_dir: str) -> bool:
        return self.get_venv_python(tool_dir).exists()

    def venv_ready(self, tool_dir: str) -> bool:
        """
        快速检测 venv 是否已就绪。
        委托 venv_exists()，语义上 ready 包含"存在且可用"。
        """
        return self.venv_exists(tool_dir)

    def create_venv(self, tool_dir: str, python_cfg: PythonConfig) -> bool:
        """
        为指定工具目录创建虚拟环境（幂等：venv 已存在则跳过）。
        成功返回 True，失败返回 False。
        """
        venv_path = self.get_venv_path(tool_dir)
        python_exe = Path(python_cfg.python_path)

        if not python_exe.exists():
            self._log(f"[错误] Python 可执行文件不存在：{python_exe}")
            return False

        # venv 已存在则跳过（不删重建，防止并发初始化互相覆盖）
        if venv_path.exists():
            self._log("[信息] 虚拟环境已存在，跳过创建")
            return True

        self._log(f"[信息] 正在创建虚拟环境（使用 {python_cfg.name}）...")
        try:
            result = subprocess.run(
                [str(python_exe), "-m", "venv", str(venv_path)],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                self._log(f"[错误] 创建虚拟环境失败：{result.stderr}")
                return False

            self._log("[信息] 虚拟环境创建成功")

            # 立即升级 pip：新版 pip 能找到预编译 wheel，避免本地编译 C 扩展失败
            # 典型场景：greenlet、psycopg2 等包需要编译，升级 pip 后可直接下载 wheel
            self._log("[信息] 正在升级 pip...")
            venv_python = str(self.get_venv_python(tool_dir))
            up_r = self._pip_run(venv_python, "install", "--upgrade", "pip", timeout=120)
            if up_r is not None and up_r.returncode == 0:
                self._log("[成功] pip 已升级到最新版")
            else:
                # 升级失败不阻塞，仅警告（后续安装可能遇到编译问题）
                self._log("[警告] pip 升级失败，部分依赖可能因缺少编译工具而安装失败")

            return True
        except subprocess.TimeoutExpired:
            self._log("[错误] 创建虚拟环境超时")
            return False
        except Exception as e:
            self._log(f"[错误] 创建虚拟环境异常：{e}")
            return False

    def delete_venv(self, tool_dir: str):
        venv_path = self.get_venv_path(tool_dir)
        if venv_path.exists():
            shutil.rmtree(venv_path)

    # ─── 依赖检测 ────────────────────────────────────────────────

    def find_dep_files(self, tool_dir: str) -> dict:
        """
        扫描工具目录，返回找到的依赖文件路径。
        返回 {"requirements": Path, "pyproject": Path}
        """
        td = Path(tool_dir)
        result = {}
        req = td / "requirements.txt"
        if req.exists():
            result["requirements"] = req
        pyproj = td / "pyproject.toml"
        if pyproj.exists():
            result["pyproject"] = pyproj
        return result

    def read_requirements(self, req_file: Path) -> list:
        """读取 requirements.txt，返回包名列表"""
        lines = req_file.read_text(encoding="utf-8").splitlines()
        pkgs = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#"):
                # 去掉版本约束和注释
                pkg = line.split("<")[0].split(">")[0].split("=")[0].split("!")[0].strip()
                if pkg:
                    pkgs.append(pkg)
        return pkgs

    # ─── 依赖安装 ────────────────────────────────────────────────

    def _pip_run(self, python_exe: str, *args, timeout: int = 300) -> subprocess.CompletedProcess | None:
        """封装 pip 调用，统一处理超时"""
        cmd = [python_exe, "-m", "pip"] + list(args)
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            self._log(f"[警告] 命令执行超时（{timeout}s）：{' '.join(args)}")
            return None

    # 依赖安装标记文件名（安装成功后写入，用于跳过后续 pip list 检查）
    DEPS_MARKER = ".deps_installed"

    def _deps_marker_path(self, tool_dir: str) -> Path:
        return self.get_venv_path(tool_dir) / self.DEPS_MARKER

    def install_deps(self, tool_dir: str, on_dep_status: callable = None) -> bool:
        """
        在虚拟环境中安装依赖。
        on_dep_status(msg, done, total): 进度回调
        返回 True 表示全部成功。
        """
        venv_python = self.get_venv_python(tool_dir)
        if not venv_python.exists():
            self._log("[错误] 虚拟环境不存在，请先创建")
            return False

        dep_files = self.find_dep_files(tool_dir)
        if not dep_files:
            self._log("[信息] 未找到依赖文件（requirements.txt / pyproject.toml），跳过安装")
            return True

        python_exe = str(venv_python)

        # pyproject.toml（用 pip install -e .）
        if "pyproject" in dep_files:
            proj_file = dep_files["pyproject"]
            self._log(f"[信息] 发现 pyproject.toml，执行 pip install -e .")
            if on_dep_status:
                on_dep_status("安装 pyproject.toml 项目...", 0, 1)
            r = self._pip_run(python_exe, "install", "-e", str(proj_file.parent), timeout=300)
            if r is None:
                self._log("[错误] pyproject.toml 安装超时")
                return False
            elif r.returncode != 0:
                self._log(f"[错误] pyproject.toml 安装失败：{r.stderr}")
                return False
            else:
                self._log("[成功] pyproject.toml 安装完成")

        # requirements.txt：先检查依赖是否已满足，跳过不必要的安装
        if "requirements" in dep_files:
            req_file = dep_files["requirements"]
            pkgs = self.read_requirements(req_file)

            # 快速路径：如果标记文件存在且内容匹配当前 requirements，跳过 pip list
            marker = self._deps_marker_path(tool_dir)
            if marker.exists():
                marker_content = marker.read_text(encoding="utf-8").strip()
                # 标记内容是 requirements.txt 的行数+校验和，不一致则重新检查
                req_hash = self._req_fingerprint(req_file)
                if marker_content == req_hash:
                    self._log("[信息] 依赖已安装（标记匹配），跳过检查")
                    return True
                else:
                    self._log("[信息] requirements.txt 已变更，重新检查依赖")

            # 慢速路径：首次安装或标记不匹配，用 pip list 对比
            installed = self.list_installed(tool_dir)
            installed_names = {p.split("==")[0].lower() for p in installed}
            required_names = {p.split("==")[0].lower() for p in pkgs}

            # 找出缺失的包
            missing = required_names - installed_names

            if not missing:
                self._log("[信息] 依赖已全部安装，跳过")
                # 写入标记文件
                self._write_deps_marker(marker, req_file)
                return True

            # Python 3.12+ 移除了 distutils，setuptools 是必需的兼容层
            if "setuptools" not in installed_names:
                self._log("[安装] setuptools（Python 3.12+ 兼容）")
                self._pip_run(python_exe, "install", "setuptools", timeout=120)

            self._log(f"[信息] 发现 {len(missing)} 个缺失依赖（共 {len(pkgs)} 个），正在安装...")
            if on_dep_status:
                on_dep_status(f"正在安装 {len(missing)} 个依赖...", 0, len(missing))

            all_ok = True
            for i, pkg in enumerate(pkgs):
                pkg_name = pkg.split("<")[0].split(">")[0].split("=")[0].split("!")[0].split("[")[0].strip().lower()
                # 跳过已安装的包
                if pkg_name in installed_names:
                    continue
                self._log(f"[安装] {pkg}")
                if on_dep_status:
                    on_dep_status(f"安装 {pkg}...", i, len(missing))
                r = self._pip_run(python_exe, "install", pkg, timeout=300)
                if r is None:
                    self._log(f"[错误] 安装 {pkg} 超时")
                    all_ok = False
                elif r.returncode != 0:
                    stderr = r.stderr or ""
                    # 如果是编译失败（wheel building），尝试仅安装二进制 wheel
                    if "Failed building wheel" in stderr or "Could not build wheels" in stderr:
                        self._log(f"[重试] {pkg} 编译失败，尝试安装预编译版本...")
                        r2 = self._pip_run(python_exe, "install", pkg,
                                           "--only-binary", ":all:", timeout=300)
                        if r2 is not None and r2.returncode == 0:
                            self._log(f"[成功] {pkg} 预编译版本安装完成")
                            continue
                        else:
                            self._log(f"[错误] {pkg} 预编译版本不可用，需要安装编译工具")
                    self._log(f"[错误] 安装 {pkg} 失败：{stderr[:200]}")
                    all_ok = False
                else:
                    self._log(f"[成功] {pkg} 安装完成")

            if not all_ok:
                # 有失败：删除标记文件，下次启动会重新检查
                if marker.exists():
                    marker.unlink()
                self._log("[信息] 部分依赖安装失败，下次启动将重新安装（虚拟环境保留）")
                return False

        self._log("[信息] 依赖安装完成")

        # 写入标记文件，下次启动跳过 pip list 检查
        marker = self._deps_marker_path(tool_dir)
        self._write_deps_marker(marker, req_file if "requirements" in dep_files else None)

        return True

    def _req_fingerprint(self, req_file: Path) -> str:
        """计算 requirements.txt 的指纹（行数 + 内容哈希），用于判断是否变更"""
        content = req_file.read_text(encoding="utf-8")
        lines = [l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#")]
        h = hashlib.sha256(content.encode()).hexdigest()[:16]
        return f"{len(lines)}:{h}"

    def _write_deps_marker(self, marker: Path, req_file: Path = None):
        """写入依赖安装标记文件"""
        try:
            if req_file:
                fingerprint = self._req_fingerprint(req_file)
                marker.write_text(fingerprint, encoding="utf-8")
            else:
                marker.write_text("ok", encoding="utf-8")
        except Exception:
            pass

    # ─── 运行时依赖补装（处理 ModuleNotFoundError） ────────────────

    # 模块名 → 包名映射（常见的不一致情况）
    # 内置默认表，外置 data/module_map.json 可覆盖/扩展
    _BUILTIN_MODULE_MAP = {
        "cv2": "opencv-python",
        "PIL": "Pillow",
        "sklearn": "scikit-learn",
        "yaml": "PyYAML",
        "bs4": "beautifulsoup4",
        "dotenv": "python-dotenv",
        "gi": "PyGObject",
        "serial": "pyserial",
        "usb": "pyusb",
        "Crypto": "pycryptodome",
        "HTMLParser": "html5lib",
        "lxml": "lxml",
        "numpy": "numpy",
        "pandas": "pandas",
        "requests": "requests",
        "flask": "flask",
        "django": "django",
        "selenium": "selenium",
        "httpx": "httpx",
        "aiohttp": "aiohttp",
        "sqlalchemy": "SQLAlchemy",
        "jwt": "PyJWT",
        "dateutil": "python-dateutil",
        "colorama": "colorama",
        "rich": "rich",
        "click": "click",
        "toml": "toml",
        "charset_normalizer": "charset-normalizer",
        "attr": "attrs",
        "pydantic": "pydantic",
    }

    @classmethod
    def _load_module_map(cls) -> dict:
        """加载模块→包名映射：外置 JSON 覆盖内置默认值"""
        merged = dict(cls._BUILTIN_MODULE_MAP)
        # 查找 data/module_map.json（相对于项目根目录或 EXE 所在目录）
        search_paths = [
            Path("data") / "module_map.json",
            Path(__file__).resolve().parent.parent.parent / "data" / "module_map.json",
        ]
        if getattr(os, "frozen", False):
            # PyInstaller 打包后，从 _MEIPASS 查找
            meipass = getattr(sys, "_MEIPASS", "")
            if meipass:
                search_paths.insert(0, Path(meipass) / "data" / "module_map.json")
        for p in search_paths:
            if p.exists():
                try:
                    custom = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(custom, dict):
                        merged.update(custom)
                        break
                except Exception:
                    pass
        return merged

    def parse_missing_module(self, stderr_line: str) -> str | None:
        """
        从 stderr 行中解析缺失的模块名。
        支持：
          - ModuleNotFoundError: No module named 'xxx'
          - ImportError: No module named 'xxx'
          - ModuleNotFoundError: No module named 'xxx.yyy' → 取顶层 'xxx'
        """
        m = re.search(
            r"(?:ModuleNotFoundError|ImportError):\s*No module named ['\"](\w+)",
            stderr_line,
        )
        if m:
            return m.group(1)
        return None

    def resolve_package_name(self, module_name: str) -> str:
        """
        将模块名解析为 pip 包名。
        优先查映射表，否则直接用模块名作为包名。
        """
        return self.MODULE_TO_PACKAGE.get(module_name, module_name)

    def install_missing_package(self, tool_dir: str, module_name: str,
                                 on_log: callable = None) -> tuple[bool, str]:
        """
        在虚拟环境中补装缺失的依赖包。
        返回 (成功与否, 包名)。
        """
        venv_python = self.get_venv_python(tool_dir)
        if not venv_python.exists():
            msg = f"[错误] 虚拟环境不存在，无法补装 {module_name}"
            self._log(msg)
            if on_log:
                on_log(msg)
            return False, module_name

        pkg_name = self.resolve_package_name(module_name)
        msg = f"[依赖补充] 检测到缺失模块 '{module_name}'，正在安装包 '{pkg_name}'..."
        self._log(msg)
        if on_log:
            on_log(msg)

        python_exe = str(venv_python)
        r = self._pip_run(python_exe, "install", pkg_name, timeout=120)

        if r is None:
            msg = f"[错误] 安装 {pkg_name} 超时"
            self._log(msg)
            if on_log:
                on_log(msg)
            return False, pkg_name
        elif r.returncode != 0:
            stderr = r.stderr or ""
            # 编译失败时尝试仅安装预编译版本
            if "Failed building wheel" in stderr or "Could not build wheels" in stderr:
                msg = f"[重试] {pkg_name} 编译失败，尝试预编译版本..."
                self._log(msg)
                if on_log:
                    on_log(msg)
                r2 = self._pip_run(python_exe, "install", pkg_name,
                                   "--only-binary", ":all:", timeout=120)
                if r2 is not None and r2.returncode == 0:
                    msg = f"[成功] {pkg_name} 预编译版本安装完成"
                    self._log(msg)
                    if on_log:
                        on_log(msg)
                    return True, pkg_name

            msg = f"[错误] 安装 {pkg_name} 失败：{stderr[:200]}"
            self._log(msg)
            if on_log:
                on_log(msg)
            return False, pkg_name
        else:
            msg = f"[成功] {pkg_name} 安装完成"
            self._log(msg)
            if on_log:
                on_log(msg)
            # 删除旧的 deps_marker，下次启动会重新校验
            marker = self._deps_marker_path(tool_dir)
            if marker.exists():
                marker.unlink()
            return True, pkg_name

    # ─── Import 预检（启动前自动发现并安装缺失依赖） ──────────────

    # 预检时跳过的目录（不扫描这些目录下的 .py 文件）
    _PREFLIGHT_SKIP_DIRS = {".venv", "__pycache__", ".git", "node_modules",
                             "build", "dist", ".mypy_cache", ".pytest_cache"}

    def scan_imports(self, tool_path: str) -> list[str]:
        """
        扫描单个 Python 源文件的 import 语句，返回顶层模块名列表。
        过滤掉以 '_' 开头的模块和相对导入（level > 0）。
        """
        try:
            source = Path(tool_path).read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(tool_path))
        except Exception:
            return []

        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if not top.startswith("_"):
                        modules.add(top)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:  # 只关心绝对导入
                    top = node.module.split(".")[0]
                    if not top.startswith("_"):
                        modules.add(top)

        return sorted(modules)

    def preflight_import_check(self, tool_dir: str, tool_path: str) -> bool:
        """
        预检：扫描工具目录下所有 .py 文件的 import 语句，
        在 venv 中批量检查模块可导入性，自动安装缺失的第三方包。

        使用 importlib.util.find_spec() 而非 import 语句：
        - 无副作用：不执行模块代码，不会触发网络请求/GUI弹窗/长初始化
        - 无注入风险：模块名作为字符串参数传入 find_spec()，不拼入可执行代码

        返回 True 表示可以继续启动（允许部分失败，运行时兜底）。
        """
        venv_python = self.get_venv_python(tool_dir)
        if not venv_python.exists():
            return False

        # 1. 扫描工具目录下所有 .py 文件的 import 语句
        all_modules = set()
        tool_dir_path = Path(tool_dir)
        file_count = 0
        max_files = 80  # 限制扫描文件数，避免超大项目耗时过长

        for py_file in tool_dir_path.rglob("*.py"):
            # 跳过排除目录和自动生成的文件
            try:
                parts = py_file.relative_to(tool_dir_path).parts
            except ValueError:
                continue
            if any(p in self._PREFLIGHT_SKIP_DIRS for p in parts):
                continue
            if py_file.name.endswith("_wrapper.py") or py_file.name.endswith("_launcher.py"):
                continue

            all_modules.update(self.scan_imports(str(py_file)))
            file_count += 1
            if file_count >= max_files:
                break

        if not all_modules:
            self._log("[信息] 依赖预检：未扫描到第三方 import 语句")
            return True

        # 2. 在 venv 中批量检查模块可导入性
        #    使用 importlib.util.find_spec() 而非 import：
        #    - find_spec 只查找模块位置信息，不执行模块代码，无副作用
        #    - 模块名作为 repr() 字符串参数传入，不拼入可执行代码，无注入风险
        #    将工具目录加入 sys.path，使本地模块能被找到而不被误判为缺失

        # 过滤出合法的 Python 标识符（scan_imports 已过滤 _ 开头，此处双重保险）
        valid_modules = sorted(m for m in all_modules if m.isidentifier())

        check_script = (
            "import sys\n"
            "import importlib.util\n"
            f"sys.path.insert(0, {repr(tool_dir)})\n"
            "missing = []\n"
        )
        for mod in valid_modules:
            # find_spec(name) 返回 None 表示模块不可导入
            # repr() 确保模块名被安全地作为字符串字面量传入
            check_script += (
                f"if importlib.util.find_spec({repr(mod)}) is None:\n"
                f"    missing.append({repr(mod)})\n"
            )
        check_script += "if missing:\n    print('MISSING:' + ','.join(missing))\n"

        try:
            r = subprocess.run(
                [str(venv_python), "-c", check_script],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0 and "MISSING:" in r.stdout:
                missing_str = r.stdout.split("MISSING:", 1)[1].strip()
                missing = [m for m in missing_str.split(",") if m]
            else:
                missing = []
        except Exception:
            self._log("[警告] 依赖预检执行异常，跳过")
            return True

        if not missing:
            self._log(f"[信息] 依赖预检通过（扫描了 {file_count} 个文件，{len(all_modules)} 个模块）")
            return True

        # 3. 自动安装缺失依赖
        self._log(f"[信息] 依赖预检发现 {len(missing)} 个缺失模块：{', '.join(missing)}")
        for mod in missing:
            pkg_name = self.resolve_package_name(mod)
            self._log(f"[依赖补充] 正在安装 '{mod}' → {pkg_name}...")
            success, _ = self.install_missing_package(tool_dir, mod)
            if not success:
                self._log(f"[警告] 模块 '{mod}' 安装失败，将在运行时重试")

        self._log("[信息] 依赖预检完成")
        return True

    # ─── 一键初始化（创建 venv + 安装依赖） ────────────────────────

    def ensure_ready(self, tool_dir: str, python_cfg: PythonConfig,
                     on_dep_status: callable = None,
                     tool_path: str = None) -> bool:
        """
        确保工具的虚拟环境已就绪（创建 venv + 安装依赖 + import 预检）。
        on_dep_status(msg, done, total): 进度回调
        tool_path: 工具主脚本路径，提供后启用 import 预检
        返回 True 表示完全就绪。

        预检策略：
        - 仅在标记文件不存在时执行（首次初始化或标记被删除后）
        - 扫描工具目录所有 .py 文件的 import 语句
        - 在 venv 中批量检查可导入性，缺失的自动补装
        - 预检完成后写入标记，后续启动跳过预检（快速路径）
        """
        if not self.venv_exists(tool_dir):
            if not self.create_venv(tool_dir, python_cfg):
                return False

        # 记录进入时标记是否存在，决定是否需要执行 import 预检
        marker = self._deps_marker_path(tool_dir)
        needs_preflight = not marker.exists()

        deps = self.find_dep_files(tool_dir)
        if deps:
            if not self.install_deps(tool_dir, on_dep_status):
                return False

        # Import 预检：首次初始化时扫描 import 语句并自动补装缺失依赖
        if needs_preflight and tool_path:
            self._log("[信息] 正在执行 import 预检...")
            self.preflight_import_check(tool_dir, tool_path)
            # 确保标记存在（install_deps 可能已写入；若无 dep 文件则在此写入）
            if not marker.exists():
                self._write_deps_marker(marker)

        self._log("[信息] 环境准备就绪")
        return True

    # ─── 检测已安装的包 ──────────────────────────────────────────

    def list_installed(self, tool_dir: str) -> list:
        """列出虚拟环境中已安装的包"""
        venv_python = self.get_venv_python(tool_dir)
        if not venv_python.exists():
            return []
        try:
            r = subprocess.run(
                [str(venv_python), "-m", "pip", "list", "--format=freeze"],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0:
                return [l.strip() for l in r.stdout.splitlines() if l.strip()]
        except Exception:
            pass
        return []
