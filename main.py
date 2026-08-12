"""入口：运行 ZotNotes GUI。

用法：python main.py
（若打包为 exe，config.json 会生成在程序同目录）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import customtkinter as ctk

from config import BASE_DIR, load_config, resource_path


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
        app = App(cfg)
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
