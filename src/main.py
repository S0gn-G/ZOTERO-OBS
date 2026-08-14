"""入口：运行 ZotNotes GUI。

用法：python src/main.py
（若打包为 exe，config.json 会生成在程序同目录的 config/ 下）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import customtkinter as ctk

from core.config import BASE_DIR, load_config, resource_path
from discovery import default_discovery_service


def main():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        cfg = load_config()
        ctk.set_appearance_mode(cfg["appearance_mode"])
        ctk.set_default_color_theme(resource_path("theme.json"))
        from gui.app import App
        app = App(cfg, discovery_service=default_discovery_service())
        app.mainloop()
    except Exception:
        import traceback
        log = os.path.join(BASE_DIR, "zotnotes_error.log")
        try:
            with open(log, "w", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
