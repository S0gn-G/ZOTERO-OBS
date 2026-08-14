"""主窗口：文献列表 + 勾选生成笔记。"""
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import quote

import customtkinter as ctk
from tkinter import messagebox

from core.config import load_config, save_config, CONFIG_PATH, resource_path
from discovery.core import (
    DiscoveryCandidate,
    DiscoveryKind,
    DiscoveryReport,
    notes_path_for_vault,
)
from core.obsidian_writer import NoteState, ObsidianWriter
from core.note_generator import generate_note, load_template, default_template_path, cleanup_figures
from core.zotero_client import DEFAULT_BASE_URL, ZoteroClient
from gui import icons
from gui import design as ui
from gui.settings_view import SettingsWindow
from gui.vault_selection import VaultSelectionDialog

MAX_WORKERS = 3  # 批量生成的并发数，兼顾速度与代理限速

ITEM_TYPE_LABEL = {
    "journalArticle": "期刊论文",
    "conferencePaper": "会议论文",
    "preprint": "预印本",
    "bookSection": "书籍章节",
    "thesis": "学位论文",
    "report": "报告",
    "videoRecording": "视频",
}


def _fmt_mtime(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _needs_sync(paper: dict, note: NoteState | None) -> bool:
    source = paper.get("source_modified") or ""
    return bool(note and note.path and source and note.source != source)


def _generation_targets(rows: dict, mode: str) -> list:
    selected = [row for row in rows.values() if row.selected()]
    return selected or (list(rows.values()) if mode == "待同步" else [])


def _zotero_uri(key: str) -> str:
    return f"zotero://select/library/items/{quote(key, safe='')}"


def _obsidian_uri(path: str) -> str:
    normalized = os.path.abspath(path).replace("\\", "/")
    return f"obsidian://open?path={quote(normalized, safe='')}"


class PaperRow:
    """论文列表行：网页式扁平布局，整行共享悬停状态。"""

    def __init__(self, parent, paper: dict, note_key: str, note_state: str,
                 on_generate, on_open, on_select, updated_at=None, has_note=False):
        self.paper = paper
        self.note_key = note_key
        self.note_state = note_state
        self.has_note = has_note
        self.updated_at = updated_at
        self._hovered = False
        self._hover_job = None
        self._title_wrap_job = None
        self.frame = ctk.CTkFrame(
            parent, corner_radius=10, border_width=1,
            border_color=ui.SURFACE, fg_color=ui.SURFACE,
        )
        self.frame.grid_columnconfigure(2, weight=1, minsize=220)

        self.accent = ctk.CTkFrame(
            self.frame, width=3, height=42, corner_radius=2, fg_color="transparent"
        )
        self.accent.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(5, 0), pady=13)

        self.check = ctk.CTkCheckBox(
            self.frame, width=22, height=22, checkbox_width=20, checkbox_height=20, text="",
            command=lambda: self._selection_changed(on_select),
        )
        self.check.grid(row=0, column=1, rowspan=2, padx=(12, 14), pady=16)

        self.title_label = ctk.CTkLabel(
            self.frame, text=paper["title"], anchor="w", justify="left", wraplength=560,
            width=100, height=42, text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
        )
        self.title_label.grid(row=0, column=2, sticky="ew", pady=(12, 2))

        self._sub_base = "  ·  ".join(filter(None, [
            ", ".join(paper["authors"][:3]) + (" 等" if len(paper["authors"]) > 3 else "")
            if paper["authors"] else "",
            paper["year"],
        ]))
        meta = ctk.CTkFrame(self.frame, fg_color="transparent")
        meta.grid(row=1, column=2, sticky="ew", pady=(0, 12))
        meta.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            meta, text=ITEM_TYPE_LABEL.get(paper["itemType"], paper["itemType"]),
            height=21, corner_radius=6, fg_color=ui.NEUTRAL_SOFT,
            text_color=ui.NEUTRAL_TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.sub_label = ctk.CTkLabel(
            meta, text=self._sub_text(), anchor="w", width=20,
            text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        )
        self.sub_label.grid(row=0, column=1, sticky="ew")

        links = ctk.CTkFrame(meta, fg_color="transparent")
        links.grid(row=0, column=2, sticky="e")
        ctk.CTkButton(
            links, text="Zotero", width=54, height=22, corner_radius=6,
            fg_color="transparent", hover_color=ui.SURFACE_HOVER,
            text_color=ui.ACCENT_TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            command=lambda: on_open("zotero", paper["key"]),
        ).pack(side="left")
        self.obsidian_btn = ctk.CTkButton(
            links, text="Obsidian", width=66, height=22, corner_radius=6,
            fg_color="transparent", hover_color=ui.SURFACE_HOVER,
            text_color=ui.ACCENT_TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            command=lambda: on_open("obsidian", paper["key"]),
            state="normal" if has_note else "disabled",
        )
        self.obsidian_btn.pack(side="left", padx=(2, 0))

        label, bg, fg = ui.STATE_STYLE[note_state]
        self.status = ctk.CTkLabel(
            self.frame, text=label, width=64, height=26,
            fg_color=bg, text_color=fg, corner_radius=7,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
        )
        self.status.grid(row=0, column=3, rowspan=2, padx=(18, 14), pady=12)

        actions = ctk.CTkFrame(self.frame, fg_color="transparent")
        actions.grid(row=0, column=4, rowspan=2, padx=(0, 12), pady=12)

        self.generate_btn = ctk.CTkButton(
            actions, text=self._action_text(),
            width=102, height=34, corner_radius=8, image=icons.play(),
            fg_color=ui.ACCENT, hover_color=ui.ACCENT_HOVER,
            command=lambda: on_generate(paper["key"]),
        )
        self.generate_btn.pack(side="right", padx=(6, 0))

        if paper.get("pdf_path"):
            ctk.CTkButton(
                actions, text="PDF", width=56, height=34, corner_radius=8,
                fg_color=ui.SURFACE, hover_color=ui.SURFACE_HOVER,
                border_width=1, border_color=ui.BORDER_STRONG,
                text_color=ui.TEXT,
                command=lambda: on_open("pdf", paper["key"]),
            ).pack(side="right")

        self.frame.bind("<Configure>", self._resize_title, add="+")
        self._bind_hover_tree(self.frame)

    def _resize_title(self, _event=None):
        if self._title_wrap_job is not None:
            self.frame.after_cancel(self._title_wrap_job)
        self._title_wrap_job = self.frame.after_idle(self._sync_title_wrap)

    def _sync_title_wrap(self):
        self._title_wrap_job = None
        width = self.title_label._reverse_widget_scaling(self.title_label.winfo_width())
        wraplength = max(240, int(width) - 12)
        if self.title_label.cget("wraplength") != wraplength:
            self.title_label.configure(wraplength=wraplength)

    def _bind_hover_tree(self, widget):
        """让卡片内所有子控件共用整张卡片的悬停命中区。"""
        widget.bind("<Enter>", self._schedule_hover_sync, add="+")
        widget.bind("<Leave>", self._schedule_hover_sync, add="+")
        for child in widget.winfo_children():
            self._bind_hover_tree(child)

    def _schedule_hover_sync(self, _event=None):
        if self._hover_job is not None:
            self.frame.after_cancel(self._hover_job)
        self._hover_job = self.frame.after_idle(self._sync_hover)

    def _sync_hover(self):
        self._hover_job = None
        pointer_x, pointer_y = self.frame.winfo_pointerxy()
        left, top = self.frame.winfo_rootx(), self.frame.winfo_rooty()
        inside = (
            left <= pointer_x < left + self.frame.winfo_width()
            and top <= pointer_y < top + self.frame.winfo_height()
        )
        self._hover(inside)

    def _hover(self, on: bool):
        self._hovered = on
        if not self.selected():
            self.frame.configure(
                fg_color=ui.SURFACE_HOVER if on else ui.SURFACE,
                border_color=ui.BORDER if on else ui.SURFACE,
            )

    def _selection_changed(self, on_select):
        selected = self.selected()
        self._apply_selection_style(selected)
        on_select(self.paper["key"], selected)

    def _apply_selection_style(self, selected: bool):
        self.frame.configure(
            fg_color=(
                ui.SURFACE_SELECTED if selected
                else ui.SURFACE_HOVER if self._hovered
                else ui.SURFACE
            ),
            border_color=(
                ui.SELECTION_MARK if selected
                else ui.BORDER if self._hovered
                else ui.SURFACE
            ),
        )
        self.accent.configure(fg_color=ui.SELECTION_MARK if selected else "transparent")

    def set_selected(self, selected: bool):
        self.check.select() if selected else self.check.deselect()
        self._apply_selection_style(selected)

    def _sub_text(self) -> str:
        if self.updated_at:
            return f"{self._sub_base} · 更新于 {self.updated_at}"
        return self._sub_base

    def set_updated_at(self, updated: str | None):
        self.updated_at = updated
        self.sub_label.configure(text=self._sub_text())

    def selected(self) -> bool:
        return bool(self.check.get())

    def _set_state(self, state: str):
        self.note_state = state
        label, bg, fg = ui.STATE_STYLE[state]
        self.status.configure(text=label, fg_color=bg, text_color=fg)

    def _action_text(self) -> str:
        if self.note_state == "failed":
            return "重试"
        if self.note_state == "stale":
            return "同步更新"
        return "生成笔记" if self.note_state == "none" else "重新生成"

    def apply_state(self, state: str, updated_at=None, has_note=None):
        self._set_state(state)
        if updated_at is not None:
            self.set_updated_at(updated_at)
        if has_note is not None:
            self.has_note = has_note
            self.obsidian_btn.configure(state="normal" if has_note else "disabled")
        self.generate_btn.configure(state="normal", text=self._action_text())

    def set_generating(self, on: bool):
        if on:
            self.generate_btn.configure(state="disabled", text="生成中…")
        else:
            self.generate_btn.configure(state="normal", text=self._action_text())


class App(ctk.CTk):
    def __init__(self, cfg=None, discovery_service=None):
        super().__init__()
        self.title("ZotNotes · Zotero → Obsidian 论文笔记")
        ui.fit_window(self, (1220, 820), (900, 560), (64, 80))
        self.configure(fg_color=ui.APP_BG)

        self.cfg = dict(cfg) if cfg is not None else load_config()
        self.discovery_service = discovery_service
        self.zotero_base_url = DEFAULT_BASE_URL
        if not os.path.exists(CONFIG_PATH):
            save_config(self.cfg)  # 首次启动：落盘默认配置，用户可直接编辑
        load_template(self.cfg)  # 模板缺失时自动创建默认模板
        self.papers: list[dict] = []
        self.notes: dict[str, NoteState] = {}
        self.failed_keys: set[str] = set()
        self.rows: dict[str, PaperRow] = {}
        self.visible_rows: dict[str, PaperRow] = {}
        self._empty_label = None
        self._filter_job = None
        self._last_search_query = ""
        self.writer = ObsidianWriter(self.cfg["notes_path"])
        self._busy = False
        self._generating = False
        self._destroyed = False
        self.generate_btn = None
        self.settings_btn = None
        self.template_btn = None
        self.auto_connect_btn = None
        self.theme_btn = None
        self.refresh_btn = None
        self.connection_label = None
        self.generated_stat = None
        self.pending_stat = None
        self.attention_stat = None
        self.selected_label = None
        self.filter_var = ctk.StringVar(value="含 PDF")
        self.select_all_var = ctk.BooleanVar(value=False)
        self._ui_queue = queue.Queue()

        self._set_window_icon()
        self._build_ui()
        self.after(20, self.focus_set)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(200, self.refresh)
        self.after(50, self._poll_ui_queue)

    def _on_close(self):
        """生成中拦截关闭：防 daemon 线程被杀导致「图片已换/笔记未换」等事务悬空。"""
        if self._generating:
            messagebox.showinfo("正在生成", "笔记生成任务进行中，请等待完成后再关闭窗口。")
            return
        self._destroyed = True
        self.destroy()

    def _set_window_icon(self):
        ico = resource_path("icon.ico")
        if os.path.exists(ico):
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

    # ---------- 线程安全 UI 调度 ----------
    def _post(self, fn):
        """从工作线程调用：把 UI 更新放进队列，主线程统一执行（tkinter 非线程安全）。"""
        self._ui_queue.put(fn)

    def _poll_ui_queue(self):
        if self._destroyed:
            return  # 窗口已关闭：不再调度 after，避免对已销毁控件操作
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                fn()
        except queue.Empty:
            pass
        finally:
            if not self._destroyed:
                self.after(50, self._poll_ui_queue)

    # ---------- UI ----------
    def _build_ui(self):
        # 平面顶栏：品牌、连接状态和全局操作保持在同一视觉层。
        topbar = ctk.CTkFrame(self, height=76, corner_radius=0, fg_color=ui.SURFACE)
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)
        ctk.CTkFrame(topbar, height=1, fg_color=ui.BORDER).pack(fill="x", side="bottom")

        brand = ctk.CTkFrame(topbar, fg_color="transparent")
        brand.pack(side="left", padx=(28, 0), pady=16)
        logo = ctk.CTkFrame(brand, width=40, height=40, corner_radius=10, fg_color=ui.ACCENT)
        logo.pack(side="left", padx=(0, 12))
        logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="", image=icons.book()).place(relx=.5, rely=.5, anchor="center")
        brand_text = ctk.CTkFrame(brand, fg_color="transparent")
        brand_text.pack(side="left")
        ctk.CTkLabel(
            brand_text, text="ZotNotes", anchor="w", text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=20, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand_text, text="Zotero × Obsidian 论文阅读工作台",
            text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
        ).pack(anchor="w")

        actions = ctk.CTkFrame(topbar, fg_color="transparent")
        actions.pack(side="right", padx=(0, 28), pady=18)
        connection = ctk.CTkFrame(
            actions, height=36, corner_radius=8, fg_color=ui.SURFACE_ALT,
            border_width=1, border_color=ui.BORDER,
        )
        connection.pack(side="left", padx=(0, 10))
        self.connection_dot = ctk.CTkLabel(
            connection, text="●", width=16, text_color=ui.TEXT_TERTIARY,
            font=ctk.CTkFont(size=10),
        )
        self.connection_dot.pack(side="left", padx=(9, 0), pady=6)
        self.connection_label = ctk.CTkLabel(
            connection, text="正在同步", text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
        )
        self.connection_label.pack(side="left", padx=(2, 10), pady=6)
        secondary = dict(
            fg_color=ui.SURFACE, hover_color=ui.SURFACE_HOVER,
            text_color=ui.TEXT, border_width=1, border_color=ui.BORDER_STRONG,
            corner_radius=8,
        )
        self.auto_connect_btn = ctk.CTkButton(
            actions, text="自动接入", width=94, height=36,
            command=self.auto_connect,
            state="normal" if self.discovery_service is not None else "disabled",
            **secondary,
        )
        self.auto_connect_btn.pack(side="left", padx=4)
        self.theme_btn = ctk.CTkButton(
            actions, width=80, height=36,
            command=self._toggle_appearance, **secondary,
        )
        self.theme_btn.pack(side="left", padx=4)
        self._sync_appearance_button()
        self.template_btn = ctk.CTkButton(
            actions, text="模板", width=82, height=36, image=icons.file(),
            command=self.open_template, **secondary,
        )
        self.template_btn.pack(side="left", padx=4)
        self.settings_btn = ctk.CTkButton(
            actions, text="设置", width=82, height=36, image=icons.sliders(),
            command=self.open_settings, **secondary,
        )
        self.settings_btn.pack(side="left", padx=4)
        self.refresh_btn = ctk.CTkButton(
            actions, text="刷新文献", width=104, height=36, corner_radius=8,
            fg_color=ui.ACCENT, hover_color=ui.ACCENT_HOVER,
            image=icons.refresh(), command=self.refresh,
        )
        self.refresh_btn.pack(side="left", padx=(4, 0))

        # 固定底部批量操作条。
        bottom = ctk.CTkFrame(self, height=72, corner_radius=0, fg_color=ui.SURFACE)
        bottom.pack(fill="x", side="bottom")
        bottom.pack_propagate(False)
        ctk.CTkFrame(bottom, height=1, fg_color=ui.BORDER).pack(fill="x", side="top")
        bottom_inner = ctk.CTkFrame(bottom, fg_color="transparent")
        bottom_inner.pack(fill="both", expand=True, padx=28)
        bottom_inner.grid_columnconfigure(2, weight=1)
        self.select_all = ctk.CTkCheckBox(
            bottom_inner, text="全选当前列表", variable=self.select_all_var,
            command=self._toggle_select_all,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        )
        self.select_all.grid(row=0, column=0, padx=(0, 10), pady=18)
        self.selected_label = ctk.CTkLabel(
            bottom_inner, text="已选 0 篇", text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        )
        self.selected_label.grid(row=0, column=1, padx=(0, 14), pady=18)
        self.progress = ctk.CTkProgressBar(
            bottom_inner, height=4, progress_color=ui.ACCENT, fg_color=ui.NEUTRAL_SOFT,
        )
        self.progress.set(0)
        self.progress.grid(row=0, column=2, sticky="ew", padx=16, pady=18)
        self.progress.grid_remove()
        self.status_label = ctk.CTkLabel(
            bottom_inner, text="就绪", anchor="e", width=240,
            text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
        )
        self.status_label.grid(row=0, column=3, padx=(8, 14), pady=18)
        self.generate_btn = ctk.CTkButton(
            bottom_inner, text="生成所选笔记", width=154, height=40, corner_radius=8,
            image=icons.play(), fg_color=ui.ACCENT, hover_color=ui.ACCENT_HOVER,
            command=self.generate, state="disabled",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="bold"),
        )
        self.generate_btn.grid(row=0, column=4, padx=(0, 0), pady=14)

        # 主内容：页面标题、统计、命令栏和单一列表面板。
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=28, pady=(22, 16))

        overview = ctk.CTkFrame(main, fg_color="transparent")
        overview.pack(fill="x", pady=(0, 16))
        intro = ctk.CTkFrame(overview, fg_color="transparent")
        intro.pack(side="left")
        ctk.CTkLabel(
            intro, text="论文库", anchor="w", text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=26, weight="bold"),
        ).pack(anchor="w")
        self.info_label = ctk.CTkLabel(
            intro, text="", anchor="w", text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        )
        self.info_label.pack(anchor="w", pady=(3, 0))

        stats = ctk.CTkFrame(overview, fg_color="transparent")
        stats.pack(side="right", pady=2)
        self.generated_stat = ctk.CTkLabel(
            stats, text="已生成 0", height=30, corner_radius=8,
            fg_color=ui.SUCCESS_SOFT, text_color=ui.SUCCESS_TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
        )
        self.generated_stat.pack(side="left")
        self.pending_stat = ctk.CTkLabel(
            stats, text="未生成 0", height=30, corner_radius=8,
            fg_color=ui.NEUTRAL_SOFT, text_color=ui.NEUTRAL_TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
        )
        self.pending_stat.pack(side="left", padx=(8, 0))
        self.attention_stat = ctk.CTkLabel(
            stats, text="需处理 0", height=30, corner_radius=8,
            fg_color=ui.WARNING_SOFT, text_color=ui.WARNING_TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
        )
        self.attention_stat.pack(side="left", padx=(8, 0))

        toolbar = ctk.CTkFrame(main, corner_radius=10, fg_color=ui.SURFACE_ALT)
        toolbar.pack(fill="x", pady=(0, 12))
        toolbar.grid_columnconfigure(0, weight=1)
        search_box = ctk.CTkFrame(
            toolbar, height=40, corner_radius=8, fg_color=ui.SURFACE,
            border_width=1, border_color=ui.BORDER_STRONG,
        )
        search_box.grid(row=0, column=0, sticky="ew", padx=(10, 12), pady=10)
        search_box.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(search_box, text="", image=icons.search()).grid(
            row=0, column=0, padx=(12, 4), pady=2
        )
        self.search_entry = ctk.CTkEntry(
            search_box, height=36, border_width=0, fg_color="transparent",
            placeholder_text="搜索论文标题、作者或年份…",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13),
        )
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=2)
        self.search_entry.bind("<KeyRelease>", self._schedule_filter)
        self.filter_control = ctk.CTkSegmentedButton(
            toolbar, values=["含 PDF", "全部", "未生成", "待同步", "需处理"],
            variable=self.filter_var, command=lambda _value: self._filter_changed(),
            height=36, corner_radius=8,
            selected_color=ui.SURFACE_SELECTED, selected_hover_color=ui.BORDER_STRONG,
            unselected_color=ui.SURFACE_ALT, unselected_hover_color=ui.SURFACE_HOVER,
            text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        )
        self.filter_control.grid(row=0, column=1, padx=(0, 10), pady=10)

        list_shell = ctk.CTkFrame(
            main, corner_radius=12, fg_color=ui.SURFACE,
            border_width=1, border_color=ui.BORDER,
        )
        list_shell.pack(fill="both", expand=True)
        list_header = ctk.CTkFrame(list_shell, height=38, corner_radius=0, fg_color=ui.SURFACE_ALT)
        list_header.pack(fill="x", padx=1, pady=(1, 0))
        list_header.pack_propagate(False)
        ctk.CTkLabel(
            list_header, text="论文", anchor="w", text_color=ui.TEXT_TERTIARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
        ).pack(side="left", padx=(58, 0), pady=8)
        ctk.CTkLabel(
            list_header, text="操作", width=174, text_color=ui.TEXT_TERTIARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
        ).pack(side="right", padx=(0, 10), pady=8)
        ctk.CTkLabel(
            list_header, text="状态", width=74, text_color=ui.TEXT_TERTIARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11, weight="bold"),
        ).pack(side="right", padx=(0, 6), pady=8)
        ctk.CTkFrame(list_shell, height=1, fg_color=ui.BORDER).pack(fill="x")
        self.list_frame = ctk.CTkScrollableFrame(
            list_shell, corner_radius=0, fg_color=ui.SURFACE,
            border_width=0,
        )
        self.list_frame.pack(fill="both", expand=True, padx=5, pady=(4, 6))

    def _set_info(self, text):
        self.info_label.configure(text=text)

    def _set_status(self, text):
        self.status_label.configure(text=text)

    def _set_busy(self, busy: bool):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for row in self.rows.values():
            row.generate_btn.configure(state=state)
            row.check.configure(state=state)
        for widget in (
            self.generate_btn, self.settings_btn, self.template_btn,
            self.auto_connect_btn, self.refresh_btn,
        ):
            if widget:
                widget.configure(state=state)
        if self.auto_connect_btn and self.discovery_service is None:
            self.auto_connect_btn.configure(state="disabled")
        for widget in (getattr(self, "search_entry", None), getattr(self, "filter_control", None),
                       getattr(self, "select_all", None)):
            if widget:
                widget.configure(state=state)
        if not busy:
            self._update_selection_status()

    def _filter_changed(self):
        if self._filter_job is not None:
            self.after_cancel(self._filter_job)
            self._filter_job = None
        self.select_all_var.set(False)
        for row in self.visible_rows.values():
            if row.selected():
                row.set_selected(False)
        papers = self._filtered_papers()
        self._render_rows(papers)
        self._refresh_info(len(papers))
        self._update_selection_status()

    def _schedule_filter(self, *_args):
        query = self.search_entry.get()
        if query == self._last_search_query:
            return
        self._last_search_query = query
        if self._filter_job is not None:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(180, self._apply_scheduled_filter)

    def _apply_scheduled_filter(self):
        self._filter_job = None
        self._filter_changed()

    def _toggle_select_all(self):
        selected = self.select_all_var.get()
        for row in self.visible_rows.values():
            row.set_selected(selected)
        self._update_selection_status()

    def _on_row_selected(self, _key: str, _selected: bool):
        self.select_all_var.set(
            bool(self.visible_rows) and all(r.selected() for r in self.visible_rows.values())
        )
        self._update_selection_status()

    def _update_selection_status(self):
        count = sum(1 for row in self.visible_rows.values() if row.selected())
        self.selected_label.configure(text=f"已选 {count} 篇")
        sync_all = bool(
            not count and self.filter_var.get() == "待同步" and self.visible_rows
        )
        if count:
            button_text = f"生成 / 更新 {count} 篇"
        elif sync_all:
            button_text = f"同步当前 {len(self.visible_rows)} 篇"
        else:
            button_text = "生成所选笔记"
        self.generate_btn.configure(text=button_text)
        if not self._busy:
            enabled = bool(count or sync_all)
            self.generate_btn.configure(
                state="normal" if enabled else "disabled",
                fg_color=ui.ACCENT if enabled else ui.NEUTRAL_SOFT,
                text_color=ui.ON_ACCENT if enabled else ui.TEXT_TERTIARY,
            )

    def auto_connect(self):
        """只在用户明确点击后运行发现插件。"""
        if self._busy or self.discovery_service is None:
            return
        self._set_busy(True)
        self._set_status("正在寻找 Zotero 与 Obsidian…")
        threading.Thread(target=self._discovery_worker, daemon=True).start()

    def _discovery_worker(self):
        try:
            report = self.discovery_service.discover()
            self._post(lambda: self._apply_auto_discovery(report))
        except Exception as exc:
            message = str(exc)
            self._post(lambda: self._show_discovery_error(message))

    def _show_discovery_error(self, message: str):
        self._set_busy(False)
        self._set_status(f"自动接入失败：{message}")

    def _apply_auto_discovery(self, report: DiscoveryReport):
        zotero_candidates = report.candidates_for(DiscoveryKind.ZOTERO_API)
        vault_candidates = report.candidates_for(DiscoveryKind.OBSIDIAN_VAULT)
        zotero = zotero_candidates[0] if zotero_candidates else None

        if len(vault_candidates) > 1:
            self._set_status(f"检测到 {len(vault_candidates)} 个 Obsidian 仓库，请选择")
            VaultSelectionDialog(
                self,
                vault_candidates,
                on_selected=lambda vault: self._complete_auto_connect(vault, zotero, report),
                on_cancel=self._cancel_auto_connect,
            )
            return

        vault = vault_candidates[0] if vault_candidates else None
        self._complete_auto_connect(vault, zotero, report)

    def _cancel_auto_connect(self):
        self._set_busy(False)
        self._set_status("已取消自动接入")

    def _complete_auto_connect(
        self,
        vault: DiscoveryCandidate | None,
        zotero: DiscoveryCandidate | None,
        report: DiscoveryReport,
    ):
        if vault is not None:
            notes_path = notes_path_for_vault(vault)
            next_cfg = {**self.cfg, "notes_path": notes_path}
            try:
                save_config(next_cfg)
            except OSError as exc:
                self._show_discovery_error(f"无法保存设置：{exc}")
                return
            self.cfg = next_cfg
            self.writer = ObsidianWriter(notes_path)

        self._set_busy(False)
        obsidian_failure = next(
            (item.message for item in report.failures
             if item.kind == DiscoveryKind.OBSIDIAN_VAULT),
            None,
        )

        if zotero is not None:
            self.zotero_base_url = zotero.value
            if vault is not None:
                status = f"已自动接入 Zotero 与 {vault.label}"
            elif obsidian_failure:
                status = f"已连接 Zotero；{obsidian_failure}"
            else:
                status = "已连接 Zotero；未发现有效的 Obsidian 仓库"
            self.refresh(status)
            return

        self.connection_dot.configure(text_color=ui.DANGER_TEXT)
        self.connection_label.configure(text="未检测到 Zotero", text_color=ui.DANGER_TEXT)
        failure = next(
            (item.message for item in report.failures if item.kind == DiscoveryKind.ZOTERO_API),
            "未检测到正在运行的 Zotero",
        )
        if vault is not None:
            self._set_status(f"已接入 {vault.label}；{failure}")
        else:
            vault_status = obsidian_failure or "未发现可接入的 Obsidian 仓库"
            self._set_status(f"{vault_status}；{failure}")

    def _toggle_appearance(self):
        mode = "dark" if self.cfg["appearance_mode"] == "light" else "light"
        self.cfg["appearance_mode"] = mode
        ctk.set_appearance_mode(mode)
        self._sync_appearance_button()
        save_config(self.cfg)

    def _sync_appearance_button(self):
        dark = self.cfg["appearance_mode"] == "dark"
        self.theme_btn.configure(
            text="白天" if dark else "夜间",
            image=icons.sun() if dark else icons.moon(),
        )

    def _paper_state(self, paper: dict) -> tuple[str, float | None]:
        key = paper["key"]
        note = self.notes.get(key)
        if _needs_sync(paper, note):
            return "stale", note.mtime
        if key in self.failed_keys:
            return "failed", note.mtime if note else None
        if note is None:
            return "none", None
        return note.status, note.mtime

    def _filtered_papers(self) -> list[dict]:
        query = self.search_entry.get().strip().lower()
        mode = self.filter_var.get()
        out = []
        for paper in self.papers:
            state, _mtime = self._paper_state(paper)
            if mode == "含 PDF" and not paper.get("pdf_path"):
                continue
            if mode == "未生成" and state != "none":
                continue
            if mode == "待同步" and state != "stale":
                continue
            if mode == "需处理" and state not in (
                "stale", "needs_source", "abstract_only", "placeholder", "failed"
            ):
                continue
            if query:
                haystack = " ".join([
                    paper["title"], " ".join(paper["authors"]), paper["year"], paper["itemType"]
                ]).lower()
                if query not in haystack:
                    continue
            out.append(paper)
        return out

    def _clear_rows(self):
        for row in self.rows.values():
            row.frame.destroy()
        self.rows.clear()
        self.visible_rows.clear()
        if self._empty_label is not None:
            self._empty_label.destroy()
            self._empty_label = None

    def _render_rows(self, papers=None):
        papers = self._filtered_papers() if papers is None else papers
        if self._empty_label is not None:
            self._empty_label.destroy()
            self._empty_label = None
        visible_before = set(self.visible_rows)
        visible_now = {paper["key"] for paper in papers}
        for key in visible_before - visible_now:
            self.rows[key].frame.pack_forget()
        if not papers:
            self.visible_rows = {}
            self._empty_label = ctk.CTkLabel(
                self.list_frame,
                text="没有符合条件的论文\n\n可以调整搜索词或筛选条件",
                text_color=ui.TEXT_SECONDARY,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=14),
                justify="center",
            )
            self._empty_label.pack(pady=80)
            return
        ordered_rows = []
        for paper in papers:
            row = self.rows.get(paper["key"])
            if row is None:
                state, mtime = self._paper_state(paper)
                updated = _fmt_mtime(mtime) if mtime else None
                has_note = bool(self.notes.get(paper["key"]) and self.notes[paper["key"]].path)
                row = PaperRow(
                    self.list_frame, paper, paper["citationKey"], state,
                    on_generate=self.generate_one, on_open=self.open_target,
                    on_select=self._on_row_selected, updated_at=updated, has_note=has_note,
                )
                self.rows[paper["key"]] = row
            ordered_rows.append((paper["key"], row))

        anchor = None
        for key, row in reversed(ordered_rows):
            if key not in visible_before:
                options = {"fill": "x", "pady": 2, "padx": 4}
                if anchor is not None:
                    options["before"] = anchor.frame
                row.frame.pack(**options)
            anchor = row
        self.visible_rows = dict(ordered_rows)

    def _refresh_info(self, visible=None):
        """从当前内存状态更新视图统计，不重复扫描磁盘。"""
        visible = len(self._filtered_papers()) if visible is None else visible
        states = [self._paper_state(p)[0] for p in self.papers]
        done = states.count("ok")
        pending = states.count("none")
        attention = sum(
            s in ("stale", "needs_source", "abstract_only", "placeholder", "failed")
            for s in states
        )
        self._set_info(f"显示 {visible} / {len(self.papers)} 篇")
        self.generated_stat.configure(text=f"已生成 {done}")
        self.pending_stat.configure(text=f"未生成 {pending}")
        self.attention_stat.configure(text=f"需处理 {attention}")

    # ---------- 数据 ----------
    def refresh(self, success_status: str | None = None):
        if self._busy:
            return
        self._set_busy(True)
        self._set_status("正在读取 Zotero…")
        self.connection_dot.configure(text_color=ui.WARNING_TEXT)
        self.connection_label.configure(text="正在同步", text_color=ui.WARNING_TEXT)
        self.progress.configure(mode="indeterminate")
        self.progress.grid()
        self.progress.start()
        writer = ObsidianWriter(self.cfg["notes_path"])
        threading.Thread(
            target=self._refresh_worker,
            args=(writer, self.zotero_base_url, success_status),
            daemon=True,
        ).start()

    def _refresh_worker(self, writer, base_url, success_status):
        try:
            client = ZoteroClient(base_url)
            papers = client.fetch_papers()
            for p in papers:
                p["citationKey"] = p["citationKey"] or ZoteroClient.fallback_citation_key(p)
            states = writer.scan_states()
            result = (papers, states, success_status)
            self._post(lambda: self._apply_refresh(result))
        except Exception as e:
            err = str(e)
            self._post(lambda err=err: self._show_error(f"读取失败：{err}"))

    def _apply_refresh(self, result):
        papers, states, success_status = result
        self._clear_rows()
        self.papers = papers
        self.notes = {
            note.key: NoteState(
                note.key,
                {"insufficient": "needs_source"}.get(note.status, note.status),
                note.mtime,
                note.path,
                note.source,
            )
            for note in states
        }
        self.failed_keys.clear()
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.grid_remove()
        if not papers:
            self._empty_label = ctk.CTkLabel(
                self.list_frame,
                text="Zotero 中还没有文献\n\n请确认 Zotero 已运行并开启本地 API",
                text_color=ui.TEXT_SECONDARY,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=14),
                justify="center",
            )
            self._empty_label.pack(pady=80)
            self._refresh_info(0)
            self._set_status(
                f"{success_status}；库中没有文献" if success_status else "库中没有文献"
            )
            self.connection_dot.configure(text_color=ui.SUCCESS_TEXT)
            self.connection_label.configure(text="Zotero 已连接", text_color=ui.SUCCESS_TEXT)
            self._set_busy(False)
            return
        visible = self._filtered_papers()
        self._render_rows(visible)
        self._refresh_info(len(visible))
        loaded = f"已加载 {len(papers)} 篇"
        self._set_status(f"{success_status}；{loaded}" if success_status else loaded)
        self.connection_dot.configure(text_color=ui.SUCCESS_TEXT)
        self.connection_label.configure(text="Zotero 已连接", text_color=ui.SUCCESS_TEXT)
        self._set_busy(False)

    def _show_error(self, msg):
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.grid_remove()
        self._set_busy(False)
        self._set_status(msg)
        self._set_info("⚠ " + msg)
        self.connection_dot.configure(text_color=ui.DANGER_TEXT)
        self.connection_label.configure(text="连接失败", text_color=ui.DANGER_TEXT)

    # ---------- 单篇生成 ----------
    def generate_one(self, key: str):
        if self._busy:
            return
        row = self.rows.get(key)
        if not row:
            return
        if not self.cfg["notes_path"]:
            self._set_status("请先在设置里选择笔记输出文件夹")
            return
        if not self.cfg["llm_api_key"]:
            self._set_status("请先在设置里填写 API Key")
            return
        cfg = dict(self.cfg)  # 快照：生成期间改设置不影响本次
        self.progress.configure(mode="indeterminate")
        self.progress.grid()
        self.progress.start()
        self._set_busy(True)
        row.set_generating(True)
        self._generating = True
        threading.Thread(target=self._generate_one_worker, args=(row, cfg), daemon=True).start()

    def _run_generate(self, row, writer, cfg):
        """生成单篇：LLM 管道 → commit_generation 整体事务（笔记+图表一起提交，失败回滚）→ 清暂存。返回 (ok, status, msg)。"""
        figures = []
        try:
            result = generate_note(row.paper, cfg, note_key=row.note_key)
            figures = result["figures"]
            missing = writer.commit_generation(
                row.note_key, result["content"], figures,
                zotero_key=row.paper["key"], note_title=row.paper["title"],
                zotero_source=row.paper.get("source_modified"))
            if missing:
                return False, "failed", f"图表拷贝失败：{', '.join(missing)}"
            return True, result["status"], "OK"
        except Exception as e:
            return False, "failed", str(e)
        finally:
            if figures:
                cleanup_figures(figures)

    def _generate_one_worker(self, row, cfg):
        ok, status, err = self._run_generate(row, self.writer, cfg)
        self._post(lambda: self._finish_one(row, ok, status, err))

    def _finish_one(self, row, ok, status, err):
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.grid_remove()
        row.set_generating(False)
        if ok and status == "needs_source":
            self._record_result(row, "needs_source", True)
            self._set_status(f"已生成骨架（证据不足）：{row.paper['title'][:40]}")
        elif ok and status == "abstract_only":
            self._record_result(row, "abstract_only", True)
            self._set_status(f"已生成（仅摘要）：{row.paper['title'][:40]}")
        elif ok:
            self._record_result(row, "ok", True)
            self._set_status(f"已生成：{row.paper['title'][:40]}")
        else:
            self._record_result(row, "failed", False)
            self._set_status(f"生成失败：{err}")
        self._generating = False
        self._set_busy(False)
        self._filter_changed()

    def _record_result(self, row, status: str, success: bool):
        key = row.paper["key"]
        if success:
            path = self.writer.find_note(key) or ""
            now = time.time()
            self.notes[key] = NoteState(
                key, status, now, path, row.paper.get("source_modified") or ""
            )
            self.failed_keys.discard(key)
            row.apply_state(status, _fmt_mtime(now), has_note=bool(path))
            return
        self.failed_keys.add(key)
        note = self.notes.get(key)
        row.apply_state("failed", has_note=bool(note and note.path))

    # ---------- 批量生成 ----------
    def generate(self):
        if self._busy:
            return
        selected = _generation_targets(self.visible_rows, self.filter_var.get())
        if not selected:
            self._set_status("请先勾选文献，或切换到“待同步”一键更新当前列表")
            return
        if not self.cfg["notes_path"]:
            self._set_status("请先在设置里选择笔记输出文件夹")
            return
        if not self.cfg["llm_api_key"]:
            self._set_status("请先在设置里填写 API Key")
            return
        cfg = dict(self.cfg)  # 快照：批量生成期间改设置不影响本次
        self._set_status(f"正在生成 {len(selected)} 篇…")
        self.progress.configure(mode="determinate")
        self.progress.grid()
        self.progress.set(0)
        self._set_busy(True)
        self._generating = True
        threading.Thread(
            target=self._generate_worker,
            args=(selected, cfg),
            daemon=True,
        ).start()

    def _generate_worker(self, rows, cfg):
        writer = ObsidianWriter(cfg["notes_path"])
        total = len(rows)
        results = []
        if not rows:
            self._post(lambda: self._finish_generate(results))
            return
        done = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            future_to_row = {pool.submit(self._run_generate, r, writer, cfg): r for r in rows}
            for fut in as_completed(future_to_row):
                row = future_to_row[fut]
                ok, status, msg = fut.result()
                results.append((row.paper["key"], status, msg))
                done += 1
                self._post(lambda v=done / total: self.progress.set(v))
                self._post(lambda t=f"[{done}/{total}] {row.paper['title'][:40]}": self._set_status(t))
        self._post(lambda: self._finish_generate(results))

    def _finish_generate(self, results):
        ok = sum(1 for _, s, r in results if s == "ok" and r == "OK")
        need = sum(1 for _, s, r in results if s == "needs_source")
        abstract = sum(1 for _, s, r in results if s == "abstract_only")
        failed = sum(1 for _, s, _r in results if s == "failed")
        first_error = next((r for _, s, r in results if s == "failed" and r), "")
        for key, s, r in results:
            row = self.rows.get(key)
            if not row:
                continue
            if s == "ok" and r == "OK":
                self._record_result(row, "ok", True)
            elif s == "needs_source":
                self._record_result(row, "needs_source", True)
            elif s == "abstract_only":
                self._record_result(row, "abstract_only", True)
            else:
                self._record_result(row, "failed", False)
        self._generating = False
        self._set_busy(False)
        self.progress.set(1.0)
        self.progress.grid_remove()
        parts = [f"完整 {ok}"]
        if need:
            parts.append(f"需原文 {need}")
        if abstract:
            parts.append(f"仅摘要 {abstract}")
        if failed:
            parts.append(f"失败 {failed}")
        self._set_status("完成 · " + " · ".join(parts))
        self._filter_changed()
        if first_error:
            self._set_info(f"首个错误：{first_error[:80]}")

    # ---------- 外部跳转 ----------
    def open_target(self, target: str, key: str):
        paper = next((p for p in self.papers if p["key"] == key), None)
        if target == "pdf":
            path = paper.get("pdf_path") if paper else None
            if not path:
                self._set_status("该条目没有 PDF 附件")
                return
            if not os.path.exists(path):
                self._set_status(f"PDF 文件不存在：{path}")
                return
            destination = path
            label = "PDF"
        elif target == "zotero":
            destination = _zotero_uri(key)
            label = "Zotero"
        else:
            try:
                path = self.writer.find_note(key)
            except RuntimeError as exc:
                self._set_status(str(exc))
                return
            if not path:
                self._set_status("该条目还没有对应的 Obsidian 笔记")
                return
            destination = _obsidian_uri(path)
            label = "Obsidian"
        try:
            os.startfile(destination)
        except OSError as exc:
            self._set_status(f"无法打开 {label}：{exc}")

    # ---------- 模板 ----------
    def open_template(self):
        load_template(self.cfg)
        path = (self.cfg.get("template_path") or "").strip() or default_template_path()
        try:
            os.startfile(path)
        except Exception as e:
            self._set_status(f"无法打开模板文件：{e}")

    # ---------- 设置 ----------
    def open_settings(self):
        SettingsWindow(self, self.cfg, on_saved=self._on_settings_saved)

    def _on_settings_saved(self, cfg):
        self.cfg = cfg
        self.writer = ObsidianWriter(cfg["notes_path"])
        self._set_status("设置已保存")
        self.refresh()
