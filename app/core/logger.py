"""
日志管理器 - 运行历史记录 + 实时日志读取
"""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.core.models import RunRecord
from app.core.utils import safe_filename


class LogManager:
    """管理运行历史和日志文件"""

    def __init__(self, logs_dir: str = "logs"):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._history_file = self.logs_dir / "run_history.json"
        self._history: List[RunRecord] = []
        self._load_history()

    # ─── 历史记录 ───────────────────────────────────────────────────

    def _load_history(self):
        if self._history_file.exists():
            try:
                with open(self._history_file, encoding="utf-8") as f:
                    data = json.load(f)
                    for d in data:
                        # 向后兼容旧数据（jar_id -> tool_id）
                        if "jar_id" in d and "tool_id" not in d:
                            d["tool_id"] = d.pop("jar_id")
                        if "jar_name" in d and "tool_name" not in d:
                            d["tool_name"] = d.pop("jar_name")
                    self._history = [RunRecord.from_dict(d) for d in data]
            except Exception:
                self._history = []

    def _save_history(self):
        # 只保留最近 500 条
        self._history = self._history[-500:]
        data = [r.to_dict() for r in self._history]
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._history_file.parent), suffix=".tmp", prefix=".save_"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                Path(tmp_path).replace(self._history_file)
            except Exception:
                Path(tmp_path).unlink(missing_ok=True)
                raise
        except Exception:
            # 原子写入失败时回退到直接写入
            with open(self._history_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def append_run_record(self, record: RunRecord):
        self._history.append(record)
        self._save_history()

    def get_history(self, tool_id: Optional[str] = None,
                    limit: int = 100) -> List[RunRecord]:
        records = self._history
        if tool_id:
            records = [r for r in records if r.tool_id == tool_id]
        return list(reversed(records))[:limit]

    def clear_history(self, tool_id: Optional[str] = None):
        if tool_id:
            self._history = [r for r in self._history if r.tool_id != tool_id]
        else:
            self._history = []
        self._save_history()

    # ─── 实时日志文件读取 ───────────────────────────────────────────

    def read_log_tail(self, log_file: str, last_n_lines: int = 300) -> str:
        """读取日志文件末尾 N 行"""
        p = Path(log_file)
        if not p.exists():
            return "(日志文件尚未生成)"
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            return "".join(lines[-last_n_lines:])
        except Exception as e:
            return f"(读取日志失败：{e})"

    def list_log_files(self, tool_name: Optional[str] = None) -> List[Path]:
        """列出所有日志文件，可按工具名称过滤"""
        files = []
        for f in self.logs_dir.glob("*.log"):
            try:
                mtime = f.stat().st_mtime
                files.append((mtime, f))
            except FileNotFoundError:
                pass  # TOCTOU：文件在 glob 和 stat 之间被删除
        files.sort(key=lambda x: x[0], reverse=True)
        result = [f for _, f in files]
        if tool_name:
            safe = safe_filename(tool_name)
            result = [f for f in result if f.name.startswith(safe)]
        return result

    def delete_log_file(self, log_file: str):
        p = Path(log_file)
        if p.exists():
            try:
                p.unlink()
            except PermissionError:
                pass  # 文件被占用，跳过

    def clean_old_logs(self, keep_days: int = 7) -> int:
        """清理超过 keep_days 天的日志，返回清理的文件数"""
        now = datetime.now().timestamp()
        count = 0
        for f in self.logs_dir.glob("*.log"):
            try:
                age_days = (now - f.stat().st_mtime) / 86400
                if age_days > keep_days:
                    f.unlink()
                    count += 1
            except (PermissionError, FileNotFoundError):
                pass  # 跳过被占用或已删除的文件
        return count

    def clean_all_logs(self) -> int:
        """清理全部日志文件，返回清理的文件数"""
        count = 0
        for f in self.logs_dir.glob("*.log"):
            try:
                f.unlink()
                count += 1
            except (PermissionError, FileNotFoundError):
                pass  # 跳过被占用或已删除的文件
        # 同时清理历史记录
        self.clear_history()
        return count
