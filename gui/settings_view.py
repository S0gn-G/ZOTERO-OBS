"""设置窗口：Zotero / Obsidian / LLM 配置。"""
import customtkinter as ctk
from tkinter import filedialog

from config import save_config


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master, cfg: dict, on_saved=None):
        super().__init__(master)
        self.cfg = dict(cfg)
        self.on_saved = on_saved
        self.title("设置")
        self.geometry("600x560")
        self.minsize(520, 420)
        self.transient(master)
        self.grab_set()

        self.entries = {}
        # 滚动区：内容超出窗口高度时可上下滚动
        body = ctk.CTkScrollableFrame(self, corner_radius=10)
        body.pack(fill="both", expand=True, padx=16, pady=(16, 8))

        # --- Zotero ---
        self._section_label(body, "Zotero 本地 API")
        self._entry(body, "zotero_base", "API 地址", cfg["zotero_base"], width=430)

        # --- Obsidian ---
        self._section_label(body, "Obsidian 仓库")
        self._entry(body, "vault_path", "Vault 路径", cfg["vault_path"], width=320, browse_dir=True)
        self._entry(body, "notes_folder", "笔记文件夹", cfg["notes_folder"], width=320)
        self._entry(body, "template_path", "模板文件", cfg["template_path"], width=320, browse_file=True)
        ctk.CTkLabel(
            body, text="模板占位符：{{zotero:title}} {{zotero:authors}} {{zotero:year}} {{zotero:doi}} {{zotero:pdf}}\n{{zotero:llm}}（LLM 生成的深度笔记正文：核心信息/摘要翻译/创新点/方法/实验/局限），路径不存在会自动创建默认模板",
            text_color="gray", justify="left", anchor="w", font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(0, 8))

        # --- LLM ---
        self._section_label(body, "LLM（OpenAI 兼容接口）")
        self._entry(body, "llm_base_url", "Base URL", cfg["llm_base_url"], width=430)
        self._entry(body, "llm_api_key", "API Key", cfg["llm_api_key"], width=430, show="*")
        self._entry(body, "llm_model", "模型名", cfg["llm_model"], width=430)

        self.llm_var = ctk.BooleanVar(value=cfg.get("llm_enabled", True))
        ctk.CTkCheckBox(body, text="启用 LLM 生成深度笔记", variable=self.llm_var).pack(anchor="w", pady=(0, 8))

        self.overwrite_var = ctk.BooleanVar(value=cfg.get("overwrite", False))
        ctk.CTkCheckBox(body, text="覆盖已生成的笔记", variable=self.overwrite_var).pack(anchor="w")

        self.pdf_var = ctk.BooleanVar(value=cfg.get("only_with_pdf", True))
        ctk.CTkCheckBox(body, text="仅显示含 PDF 的文献（隐藏视频/网页快照）", variable=self.pdf_var).pack(anchor="w", pady=(4, 0))

        self.pdftext_var = ctk.BooleanVar(value=cfg.get("use_pdf_text", True))
        ctk.CTkCheckBox(body, text="LLM 生成前读取 PDF 正文与图表（深度笔记，稍慢）", variable=self.pdftext_var).pack(anchor="w", pady=(0, 8))

        # 底部固定操作栏（不随滚动区滚动，始终可见）
        bottom = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        bottom.pack(fill="x", side="bottom", padx=16, pady=(0, 16))
        ctk.CTkButton(bottom, text="保存", width=120, command=self._save).pack(side="left")

    def _section_label(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", pady=(10, 4)
        )

    def _entry(self, parent, key, label, value, width, show=None, browse_dir=False, browse_file=False):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=label, width=110, anchor="w").pack(side="left")
        e = ctk.CTkEntry(row, width=width, show=show)
        e.pack(side="left", padx=(0, 6))
        e.insert(0, value or "")
        self.entries[key] = e
        if browse_dir:
            ctk.CTkButton(row, text="浏览…", width=64, command=lambda: self._browse_dir(key)).pack(side="left")
        if browse_file:
            ctk.CTkButton(row, text="浏览…", width=64, command=lambda: self._browse_file(key)).pack(side="left")

    def _browse_dir(self, key):
        path = filedialog.askdirectory(title="选择文件夹")
        if path:
            self.entries[key].delete(0, "end")
            self.entries[key].insert(0, path)

    def _browse_file(self, key):
        path = filedialog.askopenfilename(title="选择模板文件", filetypes=[("Markdown", "*.md"), ("文本", "*.txt"), ("所有文件", "*.*")])
        if path:
            self.entries[key].delete(0, "end")
            self.entries[key].insert(0, path)

    def _save(self):
        for key, e in self.entries.items():
            self.cfg[key] = e.get().strip()
        self.cfg["llm_enabled"] = self.llm_var.get()
        self.cfg["overwrite"] = self.overwrite_var.get()
        self.cfg["only_with_pdf"] = self.pdf_var.get()
        self.cfg["use_pdf_text"] = self.pdftext_var.get()
        save_config(self.cfg)
        if self.on_saved:
            self.on_saved(self.cfg)
        self.destroy()
