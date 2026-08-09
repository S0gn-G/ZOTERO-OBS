"""配置读写：LLM / 笔记输出设置，保存在 config.json（程序所在目录）。

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
    # 直接选择最终笔记目录，不再拆成 Vault + 子目录两个设置。
    "notes_path": "",
    # 笔记模板文件路径（空则用程序目录内 template.md）
    "template_path": os.path.join(BASE_DIR, "template.md"),
    # LLM (OpenAI 兼容)
    "llm_base_url": "https://api.deepseek.com/v1",
    "llm_api_key": "",
    "llm_model": "deepseek-chat",
    # 研究领域与写作偏好；留空使用通用学术研究者设定。
    "llm_profile": "",
}

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # v0.1 配置迁移：Vault + 子目录只在这里合并一次。
            if not saved.get("notes_path") and saved.get("vault_path"):
                saved["notes_path"] = os.path.join(
                    saved["vault_path"], saved.get("notes_folder", "LiteratureNotes")
                )
            cfg.update({k: v for k, v in saved.items() if k in DEFAULT_CONFIG})
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg: dict) -> None:
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        payload = {key: cfg.get(key, default) for key, default in DEFAULT_CONFIG.items()}
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)
