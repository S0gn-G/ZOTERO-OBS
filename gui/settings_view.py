"""精简设置窗口：输出目录、模板与 LLM。"""
import customtkinter as ctk
from tkinter import filedialog

from config import save_config
from gui import design as ui
from gui import icons


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master, cfg: dict, on_saved=None):
        super().__init__(master)
        self.cfg = dict(cfg)
        self.on_saved = on_saved
        self.title("ZotNotes 设置")
        self.geometry("720x700")
        self.minsize(640, 620)
        self.configure(fg_color=ui.APP_BG)
        self.transient(master)
        self.grab_set()
        self.entries = {}

        content = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=ui.BORDER_STRONG,
            scrollbar_button_hover_color=ui.ACCENT,
        )
        content.pack(fill="both", expand=True, padx=10, pady=(8, 0))

        heading = ctk.CTkFrame(content, fg_color="transparent")
        heading.pack(fill="x", padx=16, pady=(12, 10))
        badge = ctk.CTkFrame(heading, width=46, height=46, corner_radius=14, fg_color=ui.ACCENT_SOFT)
        badge.pack(side="left", padx=(0, 12))
        badge.pack_propagate(False)
        ctk.CTkLabel(badge, text="", image=icons.sliders()).place(relx=.5, rely=.5, anchor="center")
        heading_text = ctk.CTkFrame(heading, fg_color="transparent")
        heading_text.pack(side="left")
        ctk.CTkLabel(
            heading_text, text="设置", anchor="w", text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=23, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            heading_text, text="只保留会直接影响笔记结果的选项",
            anchor="w", text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        ).pack(anchor="w", pady=(1, 0))

        output = self._card(content, "01", "笔记输出", "决定笔记与图片最终保存的位置")
        self._entry(output, "notes_path", "输出文件夹", cfg["notes_path"], row=1, browse_dir=True)
        self._entry(output, "template_path", "笔记模板", cfg["template_path"], row=2, browse_file=True)

        model = self._card(content, "02", "模型与写作", "使用 OpenAI 兼容接口生成结构化论文笔记")
        self._entry(model, "llm_base_url", "接口地址", cfg["llm_base_url"], row=1)
        self._entry(model, "llm_api_key", "API Key", cfg["llm_api_key"], row=2, show="*", reveal=True)
        self._entry(model, "llm_model", "模型", cfg["llm_model"], row=3)

        ctk.CTkLabel(
            model, text="研究领域 / 写作偏好", anchor="w", text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        ).grid(row=4, column=0, sticky="nw", padx=(18, 10), pady=(10, 4))
        self.profile_box = ctk.CTkTextbox(
            model, height=74, wrap="word", corner_radius=10,
            border_width=1, border_color=ui.BORDER_STRONG,
            fg_color=ui.SURFACE_ALT, text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13),
        )
        self.profile_box.grid(row=4, column=1, columnspan=2, sticky="ew", padx=(0, 18), pady=(10, 18))
        self.profile_box.insert("1.0", cfg.get("llm_profile") or "")

        bottom = ctk.CTkFrame(
            self, height=70, corner_radius=0, fg_color=ui.SURFACE,
            border_width=1, border_color=ui.BORDER,
        )
        bottom.pack(fill="x", side="bottom")
        ctk.CTkButton(
            bottom, text="取消", width=96, height=38, corner_radius=10,
            fg_color=ui.NEUTRAL_SOFT, hover_color=ui.SURFACE_HOVER,
            text_color=ui.NEUTRAL_TEXT, command=self.destroy,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13),
        ).pack(side="right", padx=(8, 18), pady=14)
        ctk.CTkButton(
            bottom, text="保存设置", width=126, height=38, corner_radius=10,
            fg_color=ui.ACCENT, hover_color=ui.ACCENT_HOVER,
            command=self._save,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="bold"),
        ).pack(side="right", pady=14)

    def _card(self, parent, number, title, description):
        card = ctk.CTkFrame(
            parent, corner_radius=15, fg_color=ui.SURFACE,
            border_width=1, border_color=ui.BORDER,
        )
        card.pack(fill="x", padx=16, pady=8)
        card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            card, text=number, width=34, height=24, corner_radius=12,
            fg_color=ui.ACCENT_SOFT, text_color=ui.ACCENT_TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=(18, 10), pady=(15, 10))
        title_box = ctk.CTkFrame(card, fg_color="transparent")
        title_box.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(0, 18), pady=(12, 8))
        ctk.CTkLabel(
            title_box, text=title, anchor="w", text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=14, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_box, text=description, anchor="w", text_color=ui.TEXT_TERTIARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=10),
        ).pack(anchor="w")
        return card

    def _entry(self, parent, key, label, value, row, show=None,
               browse_dir=False, browse_file=False, reveal=False):
        ctk.CTkLabel(
            parent, text=label, anchor="w", width=116, text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        ).grid(row=row, column=0, sticky="w", padx=(18, 10), pady=6)
        entry = ctk.CTkEntry(
            parent, show=show, height=36, corner_radius=9,
            border_color=ui.BORDER_STRONG, fg_color=ui.SURFACE_ALT,
            text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13),
        )
        entry.grid(row=row, column=1, sticky="ew", pady=6)
        entry.insert(0, value or "")
        self.entries[key] = entry

        if browse_dir or browse_file:
            command = (lambda: self._browse_dir(key)) if browse_dir else (lambda: self._browse_file(key))
            ctk.CTkButton(
                parent, text="选择", width=64, height=34, corner_radius=9,
                fg_color=ui.ACCENT_SOFT, hover_color=ui.SURFACE_SELECTED,
                text_color=ui.ACCENT_TEXT, command=command,
            ).grid(row=row, column=2, padx=(8, 18), pady=6)
        elif reveal:
            ctk.CTkButton(
                parent, text="显示", width=64, height=34, corner_radius=9,
                fg_color=ui.ACCENT_SOFT, hover_color=ui.SURFACE_SELECTED,
                text_color=ui.ACCENT_TEXT,
                command=lambda: self._toggle_key(entry),
            ).grid(row=row, column=2, padx=(8, 18), pady=6)
        else:
            ctk.CTkLabel(parent, text="", width=64).grid(row=row, column=2, padx=(8, 18))

    @staticmethod
    def _toggle_key(entry):
        entry.configure(show="" if entry.cget("show") else "*")

    def _browse_dir(self, key):
        path = filedialog.askdirectory(title="选择笔记输出文件夹")
        if path:
            self.entries[key].delete(0, "end")
            self.entries[key].insert(0, path)

    def _browse_file(self, key):
        path = filedialog.askopenfilename(
            title="选择模板文件",
            filetypes=[("Markdown", "*.md"), ("文本", "*.txt"), ("所有文件", "*.*")],
        )
        if path:
            self.entries[key].delete(0, "end")
            self.entries[key].insert(0, path)

    def _save(self):
        for key, entry in self.entries.items():
            self.cfg[key] = entry.get().strip()
        self.cfg["llm_profile"] = self.profile_box.get("1.0", "end").strip()
        save_config(self.cfg)
        if self.on_saved:
            self.on_saved(self.cfg)
        self.destroy()
