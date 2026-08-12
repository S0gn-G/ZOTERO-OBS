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
        self.geometry("760x680")
        self.minsize(680, 620)
        self.configure(fg_color=ui.APP_BG)
        self.transient(master)
        self.grab_set()
        self.entries = {}

        header = ctk.CTkFrame(self, height=86, corner_radius=0, fg_color=ui.SURFACE)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        ctk.CTkFrame(header, height=1, fg_color=ui.BORDER).pack(fill="x", side="bottom")
        heading = ctk.CTkFrame(header, fg_color="transparent")
        heading.pack(fill="x", padx=28, pady=17)
        badge = ctk.CTkFrame(heading, width=40, height=40, corner_radius=10, fg_color=ui.ACCENT)
        badge.pack(side="left", padx=(0, 12))
        badge.pack_propagate(False)
        ctk.CTkLabel(
            badge, text="", image=icons.sliders_on_accent()
        ).place(relx=.5, rely=.5, anchor="center")
        heading_text = ctk.CTkFrame(heading, fg_color="transparent")
        heading_text.pack(side="left")
        ctk.CTkLabel(
            heading_text, text="设置", anchor="w", text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=22, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            heading_text, text="配置笔记位置、模板和模型接口",
            anchor="w", text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        ).pack(anchor="w")

        bottom = ctk.CTkFrame(self, height=72, corner_radius=0, fg_color=ui.SURFACE)
        bottom.pack(fill="x", side="bottom")
        bottom.pack_propagate(False)
        ctk.CTkFrame(bottom, height=1, fg_color=ui.BORDER).pack(fill="x", side="top")
        ctk.CTkButton(
            bottom, text="保存设置", width=126, height=40, corner_radius=8,
            fg_color=ui.ACCENT, hover_color=ui.ACCENT_HOVER,
            command=self._save,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="bold"),
        ).pack(side="right", padx=(8, 28), pady=15)
        ctk.CTkButton(
            bottom, text="取消", width=96, height=40, corner_radius=8,
            fg_color=ui.SURFACE, hover_color=ui.SURFACE_HOVER,
            border_width=1, border_color=ui.BORDER_STRONG,
            text_color=ui.TEXT, command=self.destroy,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13),
        ).pack(side="right", pady=15)

        content = ctk.CTkScrollableFrame(
            self, fg_color=ui.APP_BG, corner_radius=0,
            scrollbar_button_color=ui.BORDER_STRONG,
            scrollbar_button_hover_color=ui.TEXT_TERTIARY,
        )
        content.pack(fill="both", expand=True, padx=8, pady=0)

        output = self._section(content, "笔记输出", "决定 Markdown 笔记与图片最终保存的位置")
        self._entry(output, "notes_path", "输出文件夹", cfg["notes_path"], row=1, browse_dir=True)
        self._entry(output, "template_path", "笔记模板", cfg["template_path"], row=2, browse_file=True)

        model = self._section(content, "模型与写作", "使用 OpenAI 兼容接口生成结构化论文笔记")
        self._entry(model, "llm_base_url", "接口地址", cfg["llm_base_url"], row=1)
        self._entry(model, "llm_api_key", "API Key", cfg["llm_api_key"], row=2, show="*", reveal=True)
        self._entry(model, "llm_model", "模型", cfg["llm_model"], row=3)

        ctk.CTkLabel(
            model, text="研究领域 / 写作偏好", anchor="w", text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        ).grid(row=4, column=0, sticky="nw", padx=(0, 16), pady=(8, 4))
        self.profile_box = ctk.CTkTextbox(
            model, height=72, wrap="word", corner_radius=8,
            border_width=1, border_color=ui.BORDER_STRONG,
            fg_color=ui.SURFACE_ALT, text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13),
        )
        self.profile_box.grid(row=4, column=1, columnspan=2, sticky="ew", pady=(8, 16))
        self.profile_box.insert("1.0", cfg.get("llm_profile") or "")

    def _section(self, parent, title, description):
        section = ctk.CTkFrame(parent, corner_radius=0, fg_color=ui.SURFACE)
        section.pack(fill="x", padx=28, pady=(16, 0))
        section.grid_columnconfigure(1, weight=1)
        title_box = ctk.CTkFrame(section, fg_color="transparent")
        title_box.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ctk.CTkLabel(
            title_box, text=title, anchor="w", text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=16, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_box, text=description, anchor="w", text_color=ui.TEXT_TERTIARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        ).pack(anchor="w", pady=(2, 6))
        ctk.CTkFrame(title_box, height=1, fg_color=ui.BORDER).pack(fill="x")
        return section

    def _entry(self, parent, key, label, value, row, show=None,
               browse_dir=False, browse_file=False, reveal=False):
        ctk.CTkLabel(
            parent, text=label, anchor="w", width=124, text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        ).grid(row=row, column=0, sticky="w", padx=(0, 16), pady=4)
        entry = ctk.CTkEntry(
            parent, show=show, height=38, corner_radius=8, border_width=1,
            border_color=ui.BORDER_STRONG, fg_color=ui.SURFACE_ALT,
            text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13),
        )
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        entry.insert(0, value or "")
        self.entries[key] = entry

        if browse_dir or browse_file:
            command = (lambda: self._browse_dir(key)) if browse_dir else (lambda: self._browse_file(key))
            ctk.CTkButton(
                parent, text="选择", width=68, height=36, corner_radius=8,
                fg_color=ui.SURFACE, hover_color=ui.SURFACE_HOVER,
                border_width=1, border_color=ui.BORDER_STRONG,
                text_color=ui.TEXT, command=command,
            ).grid(row=row, column=2, padx=(10, 0), pady=4)
        elif reveal:
            ctk.CTkButton(
                parent, text="显示", width=68, height=36, corner_radius=8,
                fg_color=ui.SURFACE, hover_color=ui.SURFACE_HOVER,
                border_width=1, border_color=ui.BORDER_STRONG,
                text_color=ui.TEXT,
                command=lambda: self._toggle_key(entry),
            ).grid(row=row, column=2, padx=(10, 0), pady=4)
        else:
            ctk.CTkLabel(parent, text="", width=68).grid(row=row, column=2, padx=(10, 0))

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
