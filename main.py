"""
LingTai - 程序入口
"""
import sys
import os

# 确保从项目根目录执行
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from app.core import ConfigManager, LaunchEngine, LogManager
from app.ui.main_window import MainWindow

# PyInstaller 打包后，资源文件在 sys._MEIPASS 指向的临时目录
def _resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(BASE_DIR, relative_path)


def main():
    # data 目录：打包时放在 MEIPASS 内；源码时在 BASE_DIR 下
    data_dir = _resource_path("data")
    logs_dir = os.path.join(BASE_DIR, "logs")  # logs 放源码目录，方便查看

    config = ConfigManager(data_dir=data_dir)
    log_mgr = LogManager(logs_dir=logs_dir)
    engine = LaunchEngine(config_mgr=config, log_mgr=log_mgr, logs_dir=logs_dir)

    app = MainWindow(config=config, engine=engine, log_mgr=log_mgr)

    # 设置应用图标（如果存在，打包后图标在 MEIPASS 内）
    icon_path = _resource_path("assets/icon.ico")
    if os.path.exists(icon_path):
        try:
            app.iconbitmap(icon_path)
        except Exception:
            pass

    app.mainloop()


if __name__ == "__main__":
    main()
