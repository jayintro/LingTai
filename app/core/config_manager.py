"""
配置持久化管理 - 支持 JDK / Python 运行时 + 统一工具（JAR/EXE/PY）
"""
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from app.core.models import JdkConfig, PythonConfig, ToolEntry, ToolType


class ConfigManager:
    """统一管理 JDK / Python 运行时，以及所有工具条目"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._jdk_file = self.data_dir / "jdks.json"
        self._py_file = self.data_dir / "pythons.json"
        self._tool_file = self.data_dir / "tools.json"
        self._cat_file = self.data_dir / "categories.json"

        self._jdks: Dict[str, JdkConfig] = {}
        self._pythons: Dict[str, PythonConfig] = {}
        self._tools: Dict[str, ToolEntry] = {}
        self._categories: List[str] = []  # 独立分类列表（不依赖工具条目）
        self._load()

    # ─── 加载 / 保存 ─────────────────────────────────────────────

    def _load(self):
        if self._jdk_file.exists():
            try:
                with open(self._jdk_file, encoding="utf-8") as f:
                    for d in json.load(f):
                        obj = JdkConfig.from_dict(d)
                        self._jdks[obj.id] = obj
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                print(f"[ConfigManager] jdks.json 加载失败，已跳过：{e}")

        if self._py_file.exists():
            try:
                with open(self._py_file, encoding="utf-8") as f:
                    for d in json.load(f):
                        obj = PythonConfig.from_dict(d)
                        self._pythons[obj.id] = obj
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                print(f"[ConfigManager] pythons.json 加载失败，已跳过：{e}")

        # 加载独立分类列表
        if self._cat_file.exists():
            try:
                with open(self._cat_file, encoding="utf-8") as f:
                    self._categories = json.load(f)
            except (json.JSONDecodeError, TypeError) as e:
                print(f"[ConfigManager] categories.json 加载失败，已跳过：{e}")

        # 统一工具加载：新版 tools.json 优先；旧版 jars.json 自动迁移
        old_jars_file = self.data_dir / "jars.json"
        if self._tool_file.exists():
            try:
                with open(self._tool_file, encoding="utf-8") as f:
                    for d in json.load(f):
                        try:
                            obj = ToolEntry.from_dict(d)
                            self._tools[obj.id] = obj
                        except (TypeError, KeyError) as e:
                            print(f"[ConfigManager] 工具条目跳过（数据格式错误）：{e}")
            except (json.JSONDecodeError, TypeError) as e:
                print(f"[ConfigManager] tools.json 加载失败，已跳过：{e}")
        elif old_jars_file.exists():
            # 构建 JDK name → id 映射（用于修复旧 jdk_id 占位符如 "jdk1"）
            jdk_name_to_id = {jdk.name: jdk_id for jdk_id, jdk in self._jdks.items()}

            migrated_count = 0
            try:
                with open(old_jars_file, encoding="utf-8") as f:
                    for d in json.load(f):
                        try:
                            # 修复 jdk_id 占位符：尝试用 JDK 名称匹配真实 UUID
                            old_jdk_id = d.get("jdk_id", "")
                            if old_jdk_id and old_jdk_id in jdk_name_to_id:
                                d["jdk_id"] = jdk_name_to_id[old_jdk_id]

                            obj = ToolEntry.from_dict(d)
                            self._tools[obj.id] = obj
                            migrated_count += 1
                        except (TypeError, KeyError) as e:
                            print(f"[ConfigManager] 旧工具条目跳过（数据格式错误）：{e}")

                # 迁移完成后重命名旧文件（备份）
                backup_path = old_jars_file.with_suffix(".json.bak")
                old_jars_file.rename(backup_path)
                # 保存到新版文件
                self._save_tools()
                print(f"[ConfigManager] 已从 jars.json 迁移 {migrated_count} 条工具数据 → tools.json，"
                      f"旧文件备份为 jars.json.bak")
            except (json.JSONDecodeError, TypeError) as e:
                print(f"[ConfigManager] jars.json 迁移失败，已跳过：{e}")

    def _save_jdks(self):
        self._atomic_write_json(self._jdk_file,
                                [j.to_dict() for j in self._jdks.values()])

    def _save_pythons(self):
        self._atomic_write_json(self._py_file,
                                [p.to_dict() for p in self._pythons.values()])

    def _save_tools(self):
        self._atomic_write_json(self._tool_file,
                                [t.to_dict() for t in self._tools.values()])

    def _save_categories(self):
        self._atomic_write_json(self._cat_file, self._categories)

    def _atomic_write_json(self, target: Path, data):
        """原子写入 JSON 文件：先写临时文件，再替换目标文件，防止写入中断导致损坏"""
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(target.parent), suffix=".tmp", prefix=".save_"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                Path(tmp_path).replace(target)
            except Exception:
                Path(tmp_path).unlink(missing_ok=True)
                raise
        except Exception:
            # 原子写入失败时回退到直接写入（比丢失数据好）
            with open(target, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    # ─── JDK ───────────────────────────────────────────────────

    def add_jdk(self, name: str, version: str, java_path: str,
                description: str = "") -> JdkConfig:
        jdk = JdkConfig(
            id=str(uuid.uuid4()), name=name, version=version,
            java_path=java_path, description=description,
        )
        self._jdks[jdk.id] = jdk
        self._save_jdks()
        return jdk

    def update_jdk(self, jdk: JdkConfig):
        self._jdks[jdk.id] = jdk
        self._save_jdks()

    def delete_jdk(self, jdk_id: str):
        using = [t.name for t in self._tools.values()
                 if t.tool_type == ToolType.JAR.value and t.jdk_id == jdk_id]
        if using:
            raise ValueError(f"以下 JAR 工具仍在使用此 JDK，请先修改：{', '.join(using)}")
        self._jdks.pop(jdk_id, None)
        self._save_jdks()

    def get_jdk(self, jdk_id: str) -> Optional[JdkConfig]:
        return self._jdks.get(jdk_id)

    def list_jdks(self) -> List[JdkConfig]:
        return list(self._jdks.values())

    # ─── Python ─────────────────────────────────────────────────

    def add_python(self, name: str, version: str, python_path: str,
                   description: str = "") -> PythonConfig:
        py = PythonConfig(
            id=str(uuid.uuid4()), name=name, version=version,
            python_path=python_path, description=description,
        )
        self._pythons[py.id] = py
        self._save_pythons()
        return py

    def update_python(self, py: PythonConfig):
        self._pythons[py.id] = py
        self._save_pythons()

    def delete_python(self, py_id: str):
        using = [t.name for t in self._tools.values()
                 if t.tool_type in (ToolType.EXE.value, ToolType.PY.value)
                 and t.runtime_id == py_id]
        if using:
            raise ValueError(f"以下工具仍在使用此 Python，请先修改：{', '.join(using)}")
        self._pythons.pop(py_id, None)
        self._save_pythons()

    def get_python(self, py_id: str) -> Optional[PythonConfig]:
        return self._pythons.get(py_id)

    def list_pythons(self) -> List[PythonConfig]:
        return list(self._pythons.values())

    # ─── 工具（统一 JAR / EXE / PY） ────────────────────────────

    def add_tool(self, **kwargs) -> ToolEntry:
        # 基本输入校验
        name = kwargs.get("name", "").strip()
        if not name:
            raise ValueError("工具名称不能为空")
        tool_type = kwargs.get("tool_type", "")
        valid_types = {t.value for t in ToolType}
        if tool_type not in valid_types:
            raise ValueError(f"不支持的工具类型：{tool_type}（可选：{', '.join(sorted(valid_types))}）")
        tool = ToolEntry(id=str(uuid.uuid4()), **kwargs)
        self._tools[tool.id] = tool
        self._save_tools()
        return tool

    def update_tool(self, tool: ToolEntry):
        self._tools[tool.id] = tool
        self._save_tools()

    def delete_tool(self, tool_id: str):
        self._tools.pop(tool_id, None)
        self._save_tools()

    def get_tool(self, tool_id: str) -> Optional[ToolEntry]:
        return self._tools.get(tool_id)

    def list_tools(self, category: Optional[str] = None,
                   tool_type: Optional[str] = None) -> List[ToolEntry]:
        tools = list(self._tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        if tool_type:
            tools = [t for t in tools if t.tool_type == tool_type]
        return tools

    # ─── 别名：兼容旧代码 ──────────────────────────────────────

    def add_jar(self, **kwargs) -> ToolEntry:
        """向后兼容"""
        return self.add_tool(tool_type=ToolType.JAR.value, **kwargs)

    def update_jar(self, tool: ToolEntry):
        self.update_tool(tool)

    def delete_jar(self, tool_id: str):
        self.delete_tool(tool_id)

    def get_jar(self, tool_id: str) -> Optional[ToolEntry]:
        return self.get_tool(tool_id)

    def list_jars(self, category: Optional[str] = None) -> List[ToolEntry]:
        return self.list_tools(category=category, tool_type=ToolType.JAR.value)

    # ─── 分类 ──────────────────────────────────────────────────

    def list_categories(self) -> List[str]:
        # 合并：独立分类列表 + 工具条目中存在的分类（去重排序）
        all_cats = set(self._categories)
        for t in self._tools.values():
            if t.category and t.name != "__placeholder__":
                all_cats.add(t.category)
        cats = sorted(all_cats)
        return cats if cats else ["默认"]

    def add_category(self, name: str):
        """添加新分类（独立存储，不创建假工具）"""
        if name not in self._categories:
            self._categories.append(name)
            self._save_categories()

    def delete_category(self, name: str):
        """删除独立分类（仅从列表中移除，不影响工具条目的 category 字段）"""
        if name in self._categories:
            self._categories.remove(name)
            self._save_categories()

    def rename_category(self, old_name: str, new_name: str):
        for tool in self._tools.values():
            if tool.category == old_name:
                tool.category = new_name
        if old_name in self._categories:
            self._categories[self._categories.index(old_name)] = new_name
        self._save_categories()
        self._save_tools()
