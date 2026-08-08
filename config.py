"""配置读写：Zotero / LLM / Obsidian vault 设置，保存在 config.json（程序所在目录）。

打包成 exe 后，配置和模板文件放在 exe 旁边，方便用户直接编辑。
"""
import json
import os
import sys

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resource_path(name: str) -> str:
    """定位随程序分发的静态资源（theme.json/icon.ico）。

    源码运行：zotnotes_tool/ 下；单文件 exe：优先 exe 同目录的用户文件
    （用户可覆盖配色/图标），缺失时回退到打包内置的 _MEIPASS。
    """
    if getattr(sys, "frozen", False):
        local = os.path.join(BASE_DIR, name)
        if os.path.exists(local):
            return local
        return os.path.join(getattr(sys, "_MEIPASS", BASE_DIR), name)
    return os.path.join(BASE_DIR, name)

DEFAULT_CONFIG = {
    # Zotero
    "zotero_base": "http://127.0.0.1:23119/api/",
    # Obsidian
    "vault_path": r"C:\Users\pbrii\Desktop\论文笔记\REID",
    "notes_folder": "LiteratureNotes",
    # 笔记模板文件路径（空则用程序目录内 template.md）
    "template_path": os.path.join(BASE_DIR, "template.md"),
    # LLM (OpenAI 兼容)
    "llm_base_url": "https://api.deepseek.com/v1",
    "llm_api_key": "",
    "llm_model": "deepseek-chat",
    "llm_enabled": True,
    # 生成选项
    "overwrite": False,
    # 仅显示含 PDF 附件的文献（隐藏视频/网页快照等）
    "only_with_pdf": True,
    # LLM 生成前读取 PDF 正文（提升摘要质量，稍慢）
    "use_pdf_text": True,
}

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
