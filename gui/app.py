"""主窗口：文献列表 + 勾选生成笔记。"""
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import customtkinter as ctk
from tkinter import messagebox

from config import load_config, save_config, CONFIG_PATH, resource_path
from obsidian_writer import ObsidianWriter
from note_generator import generate_note, load_template, default_template_path, cleanup_figures
from zotero_client import ZoteroClient
from gui import icons
from gui import design as ui
from gui.settings_view import SettingsWindow

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


class PaperRow:
    """列表中的一行文献（卡片式）。"""

    def __init__(self, parent, paper: dict, note_key: str, note_state: str,
                 on_generate, on_open_pdf, on_select, updated_at=None):
        self.paper = paper
        self.note_key = note_key
        self.note_state = note_state
        self.updated_at = updated_at
        self.frame = ctk.CTkFrame(
            parent, corner_radius=15, border_width=1,
            border_color=ui.BORDER, fg_color=ui.SURFACE,
        )
        self.frame.pack(fill="x", pady=6, padx=2)
        self.frame.grid_columnconfigure(2, weight=1)
        self.frame.bind("<Enter>", lambda _e: self._hover(True))
        self.frame.bind("<Leave>", lambda _e: self._hover(False))

        self.accent = ctk.CTkFrame(
            self.frame, width=4, height=50, corner_radius=2, fg_color="transparent"
        )
        self.accent.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(0, 0), pady=14)

        self.check = ctk.CTkCheckBox(
            self.frame, width=24, text="",
            command=lambda: self._selection_changed(on_select),
        )
        self.check.grid(row=0, column=1, rowspan=2, padx=(16, 12), pady=17)

        title = ctk.CTkLabel(
            self.frame, text=paper["title"], anchor="w", justify="left", wraplength=620,
            text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=15, weight="bold"),
        )
        title.grid(row=0, column=2, sticky="ew", pady=(14, 2))

        self._sub_base = "  ·  ".join(filter(None, [
            ", ".join(paper["authors"][:3]) + (" 等" if len(paper["authors"]) > 3 else "")
            if paper["authors"] else "",
            paper["year"],
        ]))
        meta = ctk.CTkFrame(self.frame, fg_color="transparent")
        meta.grid(row=1, column=2, sticky="ew", pady=(0, 14))
        ctk.CTkLabel(
            meta, text=ITEM_TYPE_LABEL.get(paper["itemType"], paper["itemType"]),
            height=22, corner_radius=11, fg_color=ui.NEUTRAL_SOFT,
            text_color=ui.NEUTRAL_TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
        ).pack(side="left", padx=(0, 8))
        self.sub_label = ctk.CTkLabel(
            meta, text=self._sub_text(), anchor="w", text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        )
        self.sub_label.pack(side="left")

        actions = ctk.CTkFrame(self.frame, fg_color="transparent")
        actions.grid(row=0, column=3, rowspan=2, padx=(12, 10), pady=12)

        label, bg, fg = ui.STATE_STYLE[note_state]
        self.status = ctk.CTkLabel(
            self.frame, text=label, width=64, height=26,
            fg_color=bg, text_color=fg, corner_radius=13,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
        )
        self.status.grid(row=0, column=4, rowspan=2, padx=(0, 16), pady=12)

        self.generate_btn = ctk.CTkButton(
            actions, text="重新生成" if note_state == "ok" else "生成笔记",
            width=104, height=34, corner_radius=9, image=icons.play(),
            fg_color=ui.ACCENT, hover_color=ui.ACCENT_HOVER,
            command=lambda: on_generate(paper["key"]),
        )
        self.generate_btn.pack(side="right", padx=(6, 0))

        if paper.get("pdf_path"):
            ctk.CTkButton(
                actions, text="PDF", width=60, height=34, corner_radius=9,
                fg_color=ui.ACCENT_SOFT, hover_color=ui.SURFACE_SELECTED,
                text_color=ui.ACCENT_TEXT,
                command=lambda: on_open_pdf(paper["key"]),
            ).pack(side="right")

    def _hover(self, on: bool):
        if not self.selected():
            self.frame.configure(fg_color=ui.SURFACE_HOVER if on else ui.SURFACE)

    def _selection_changed(self, on_select):
        selected = self.selected()
        self._apply_selection_style(selected)
        on_select(self.paper["key"], selected)

    def _apply_selection_style(self, selected: bool):
        self.frame.configure(
            fg_color=ui.SURFACE_SELECTED if selected else ui.SURFACE,
            border_color=ui.ACCENT if selected else ui.BORDER,
        )
        self.accent.configure(fg_color=ui.ACCENT if selected else "transparent")

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

    def mark_done(self):
        self._set_state("ok")
        self.generate_btn.configure(text="重新生成")
        self.set_updated_at(_fmt_mtime(time.time()))

    def mark_needs_source(self):
        self._set_state("needs_source")
        self.set_updated_at(_fmt_mtime(time.time()))

    def mark_abstract_only(self):
        self._set_state("abstract_only")
        self.set_updated_at(_fmt_mtime(time.time()))

    def _set_state(self, state: str):
        self.note_state = state
        label, bg, fg = ui.STATE_STYLE[state]
        self.status.configure(text=label, fg_color=bg, text_color=fg)

    def set_generating(self, on: bool):
        if on:
            self.generate_btn.configure(state="disabled", text="生成中…")
        else:
            self.generate_btn.configure(state="normal", text="生成笔记")

    def mark_failed(self):
        self._set_state("failed")
        self.generate_btn.configure(state="normal", text="重试")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ZotNotes · Zotero → Obsidian 论文笔记")
        self.geometry("1140x780")
        self.minsize(920, 640)
        self.configure(fg_color=ui.APP_BG)

        self.cfg = load_config()
        if not os.path.exists(CONFIG_PATH):
            save_config(self.cfg)  # 首次启动：落盘默认配置，用户可直接编辑
        load_template(self.cfg)  # 模板缺失时自动创建默认模板
        self.papers: list[dict] = []
        self.paper_states: dict[str, tuple[str, float | None]] = {}
        self.rows: dict[str, PaperRow] = {}
        self.writer = ObsidianWriter(self.cfg["notes_path"])
        self._busy = False
        self._generating = False
        self._destroyed = False
        self.generate_btn = None
        self.settings_btn = None
        self.template_btn = None
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
        self.after(50, self._poll_ui_queue)

    # ---------- UI ----------
    def _build_ui(self):
        header = ctk.CTkFrame(
            self, corner_radius=18, fg_color=ui.SURFACE,
            border_width=1, border_color=ui.BORDER,
        )
        header.pack(fill="x", padx=20, pady=(18, 12))
        header.grid_columnconfigure(0, weight=1)

        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w", padx=18, pady=14)
        logo = ctk.CTkFrame(brand, width=48, height=48, corner_radius=14, fg_color=ui.ACCENT)
        logo.pack(side="left", padx=(0, 12))
        logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="", image=icons.book()).place(relx=.5, rely=.5, anchor="center")
        brand_text = ctk.CTkFrame(brand, fg_color="transparent")
        brand_text.pack(side="left")
        ctk.CTkLabel(
            brand_text, text="ZotNotes", anchor="w", text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=23, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand_text, text="Zotero → Obsidian 研究工作台",
            text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        ).pack(anchor="w", pady=(1, 0))

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, padx=16, pady=14)
        connection = ctk.CTkFrame(actions, corner_radius=15, fg_color=ui.NEUTRAL_SOFT)
        connection.pack(side="left", padx=(0, 10))
        self.connection_dot = ctk.CTkLabel(
            connection, text="●", width=16, text_color=ui.TEXT_TERTIARY,
            font=ctk.CTkFont(size=10),
        )
        self.connection_dot.pack(side="left", padx=(9, 0), pady=5)
        self.connection_label = ctk.CTkLabel(
            connection, text="正在同步", text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
        )
        self.connection_label.pack(side="left", padx=(2, 10), pady=5)
        secondary = dict(
            fg_color=ui.ACCENT_SOFT, hover_color=ui.SURFACE_SELECTED,
            text_color=ui.ACCENT_TEXT, corner_radius=9,
        )
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
            actions, text="刷新", width=88, height=36, corner_radius=9,
            fg_color=ui.ACCENT, hover_color=ui.ACCENT_HOVER,
            image=icons.refresh(), command=self.refresh,
        )
        self.refresh_btn.pack(side="left", padx=(4, 0))

        toolbar = ctk.CTkFrame(
            self, corner_radius=15, fg_color=ui.SURFACE,
            border_width=1, border_color=ui.BORDER,
        )
        toolbar.pack(fill="x", padx=20, pady=(0, 12))
        toolbar.grid_columnconfigure(0, weight=1)

        search_box = ctk.CTkFrame(
            toolbar, height=40, corner_radius=11, fg_color=ui.SURFACE_ALT,
            border_width=1, border_color=ui.BORDER_STRONG,
        )
        search_box.grid(row=0, column=0, sticky="ew", padx=(14, 12), pady=12)
        search_box.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(search_box, text="", image=icons.search()).grid(
            row=0, column=0, padx=(12, 4), pady=2
        )
        self.search_entry = ctk.CTkEntry(
            search_box, height=36, border_width=0, fg_color="transparent",
            placeholder_text="搜索标题、作者或年份…",
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13),
        )
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=2)
        self.search_entry.bind("<KeyRelease>", lambda _event: self._filter_changed())
        self.filter_control = ctk.CTkSegmentedButton(
            toolbar, values=["含 PDF", "全部", "未生成", "需处理"],
            variable=self.filter_var, command=lambda _value: self._filter_changed(),
            height=36, corner_radius=9,
            selected_color=ui.ACCENT, selected_hover_color=ui.ACCENT_HOVER,
            unselected_color=ui.NEUTRAL_SOFT, unselected_hover_color=ui.SURFACE_HOVER,
            text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        )
        self.filter_control.grid(row=0, column=1, padx=(0, 14), pady=12)

        summary = ctk.CTkFrame(self, fg_color="transparent")
        summary.pack(fill="x", padx=26, pady=(0, 4))
        ctk.CTkLabel(
            summary, text="论文库", anchor="w", text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=16, weight="bold"),
        ).pack(side="left")
        self.info_label = ctk.CTkLabel(
            summary, text="", anchor="w", text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        )
        self.info_label.pack(side="left", padx=(10, 0))
        self.attention_stat = ctk.CTkLabel(
            summary, text="需处理 0", height=26, corner_radius=13,
            fg_color=ui.WARNING_SOFT, text_color=ui.WARNING_TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
        )
        self.attention_stat.pack(side="right", padx=(8, 0))
        self.pending_stat = ctk.CTkLabel(
            summary, text="未生成 0", height=26, corner_radius=13,
            fg_color=ui.NEUTRAL_SOFT, text_color=ui.NEUTRAL_TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
        )
        self.pending_stat.pack(side="right", padx=(8, 0))
        self.generated_stat = ctk.CTkLabel(
            summary, text="已生成 0", height=26, corner_radius=13,
            fg_color=ui.ACCENT_SOFT, text_color=ui.ACCENT_TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
        )
        self.generated_stat.pack(side="right")

        self.list_frame = ctk.CTkScrollableFrame(
            self, corner_radius=16, fg_color=ui.SURFACE_ALT,
            border_width=1, border_color=ui.BORDER,
        )
        self.list_frame.pack(fill="both", expand=True, padx=20, pady=(6, 10))

        bottom = ctk.CTkFrame(
            self, corner_radius=16, fg_color=ui.SURFACE,
            border_width=1, border_color=ui.BORDER,
        )
        bottom.pack(fill="x", side="bottom", padx=20, pady=(0, 18))
        bottom.grid_columnconfigure(2, weight=1)
        self.select_all = ctk.CTkCheckBox(
            bottom, text="全选当前列表", variable=self.select_all_var,
            command=self._toggle_select_all,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        )
        self.select_all.grid(row=0, column=0, padx=(16, 10), pady=14)
        self.selected_label = ctk.CTkLabel(
            bottom, text="已选 0 篇", text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
        )
        self.selected_label.grid(row=0, column=1, padx=(0, 12), pady=14)
        self.progress = ctk.CTkProgressBar(
            bottom, height=5, progress_color=ui.ACCENT,
            fg_color=ui.NEUTRAL_SOFT,
        )
        self.progress.set(0)
        self.progress.grid(row=0, column=2, sticky="ew", padx=12, pady=14)
        self.progress.grid_remove()
        self.status_label = ctk.CTkLabel(
            bottom, text="就绪", anchor="e", width=150, text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
        )
        self.status_label.grid(row=0, column=3, padx=(8, 12), pady=14)
        self.generate_btn = ctk.CTkButton(
            bottom, text="生成所选笔记", width=150, height=40, corner_radius=10,
            image=icons.play(), fg_color=ui.ACCENT, hover_color=ui.ACCENT_HOVER,
            command=self.generate, state="disabled",
        )
        self.generate_btn.grid(row=0, column=4, padx=(0, 14), pady=10)

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
        for widget in (self.generate_btn, self.settings_btn, self.template_btn, self.refresh_btn):
            if widget:
                widget.configure(state=state)
        for widget in (getattr(self, "search_entry", None), getattr(self, "filter_control", None),
                       getattr(self, "select_all", None)):
            if widget:
                widget.configure(state=state)
        if not busy:
            self._update_selection_status()

    def _filter_changed(self):
        self.select_all_var.set(False)
        self._render_rows()
        self._refresh_info()
        self._update_selection_status()

    def _toggle_select_all(self):
        selected = self.select_all_var.get()
        for row in self.rows.values():
            row.set_selected(selected)
        self._update_selection_status()

    def _on_row_selected(self, _key: str, _selected: bool):
        self.select_all_var.set(bool(self.rows) and all(r.selected() for r in self.rows.values()))
        self._update_selection_status()

    def _update_selection_status(self):
        count = sum(1 for row in self.rows.values() if row.selected())
        self.selected_label.configure(text=f"已选 {count} 篇")
        self.generate_btn.configure(text=f"生成 {count} 篇笔记" if count else "生成所选笔记")
        if not self._busy:
            self.generate_btn.configure(
                state="normal" if count else "disabled",
                fg_color=ui.ACCENT if count else ui.NEUTRAL_SOFT,
                text_color="#FFFFFF" if count else ui.TEXT_TERTIARY,
            )

    def _paper_state(self, key: str) -> tuple[str, float | None]:
        return self.paper_states.get(key, ("none", None))

    def _filtered_papers(self) -> list[dict]:
        query = self.search_entry.get().strip().lower()
        mode = self.filter_var.get()
        out = []
        for paper in self.papers:
            state, _mtime = self._paper_state(paper["key"])
            haystack = " ".join([
                paper["title"], " ".join(paper["authors"]), paper["year"], paper["itemType"]
            ]).lower()
            if query and query not in haystack:
                continue
            if mode == "含 PDF" and not paper.get("pdf_path"):
                continue
            if mode == "未生成" and state != "none":
                continue
            if mode == "需处理" and state not in ("needs_source", "abstract_only", "placeholder", "failed"):
                continue
            out.append(paper)
        return out

    def _render_rows(self):
        if not hasattr(self, "list_frame"):
            return
        for child in self.list_frame.winfo_children():
            child.destroy()
        self.rows.clear()
        papers = self._filtered_papers()
        if not papers:
            ctk.CTkLabel(
                self.list_frame,
                text="没有符合条件的论文\n\n可以调整搜索词或筛选条件",
                text_color=ui.TEXT_SECONDARY,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=14),
                justify="center",
            ).pack(pady=80)
            return
        for paper in papers:
            state, mtime = self._paper_state(paper["key"])
            updated = _fmt_mtime(mtime) if mtime else None
            row = PaperRow(
                self.list_frame, paper, paper["citationKey"], state,
                on_generate=self.generate_one, on_open_pdf=self.open_pdf,
                on_select=self._on_row_selected, updated_at=updated,
            )
            self.rows[paper["key"]] = row

    def _refresh_info(self, _states=None):
        """从当前内存状态更新视图统计，不重复扫描磁盘。"""
        visible = len(self._filtered_papers())
        states = [self._paper_state(p["key"])[0] for p in self.papers]
        done = states.count("ok")
        pending = states.count("none")
        attention = sum(s in ("needs_source", "abstract_only", "placeholder", "failed") for s in states)
        self._set_info(f"显示 {visible} / {len(self.papers)} 篇")
        self.generated_stat.configure(text=f"已生成 {done}")
        self.pending_stat.configure(text=f"未生成 {pending}")
        self.attention_stat.configure(text=f"需处理 {attention}")

    # ---------- 数据 ----------
    def refresh(self):
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
        threading.Thread(target=self._refresh_worker, args=(writer,), daemon=True).start()

    def _refresh_worker(self, writer):
        try:
            client = ZoteroClient()
            papers = client.fetch_papers()
            for p in papers:
                p["citationKey"] = p["citationKey"] or ZoteroClient.fallback_citation_key(p)
            states = writer.scan_states()
            result = (papers, states)
            self._post(lambda: self._apply_refresh(result))
        except Exception as e:
            err = str(e)
            self._post(lambda err=err: self._show_error(f"读取失败：{err}"))

    def _apply_refresh(self, result):
        papers, states = result
        self.papers = papers
        self.paper_states = {
            key: ({"insufficient": "needs_source"}.get(state, state), mtime)
            for key, state, mtime in states
        }
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.grid_remove()
        if not papers:
            for child in self.list_frame.winfo_children():
                child.destroy()
            self.rows.clear()
            ctk.CTkLabel(
                self.list_frame,
                text="Zotero 中还没有文献\n\n请确认 Zotero 已运行并开启本地 API",
                text_color=ui.TEXT_SECONDARY,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=14),
                justify="center",
            ).pack(pady=80)
            self._refresh_info(states)
            self._set_status("库中没有文献")
            self.connection_dot.configure(text_color=ui.ACCENT)
            self.connection_label.configure(text="Zotero 已连接", text_color=ui.ACCENT_TEXT)
            self._set_busy(False)
            return
        self._render_rows()
        self._refresh_info(states)
        self._set_status(f"已加载 {len(papers)} 篇")
        self.connection_dot.configure(text_color=ui.ACCENT)
        self.connection_label.configure(text="Zotero 已连接", text_color=ui.ACCENT_TEXT)
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
                row.note_key, result["content"], figures, zotero_key=row.paper["key"])
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
            row.mark_needs_source()
            self.paper_states[row.paper["key"]] = ("needs_source", time.time())
            self._set_status(f"已生成骨架（证据不足）：{row.paper['title'][:40]}")
        elif ok and status == "abstract_only":
            row.mark_abstract_only()
            self.paper_states[row.paper["key"]] = ("abstract_only", time.time())
            self._set_status(f"已生成（仅摘要）：{row.paper['title'][:40]}")
        elif ok:
            row.mark_done()
            self.paper_states[row.paper["key"]] = ("ok", time.time())
            self._set_status(f"已生成：{row.paper['title'][:40]}")
        else:
            row.mark_failed()
            self.paper_states[row.paper["key"]] = ("failed", None)
            self._set_status(f"生成失败：{err}")
        self._refresh_info()
        self._generating = False
        self._set_busy(False)

    # ---------- 批量生成 ----------
    def generate(self):
        if self._busy:
            return
        selected = [r for r in self.rows.values() if r.selected()]
        if not selected:
            self._set_status("请先勾选至少一篇文献")
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
        for key, s, r in results:
            row = self.rows.get(key)
            if not row:
                continue
            if s == "ok" and r == "OK":
                row.mark_done()
                self.paper_states[key] = ("ok", time.time())
            elif s == "needs_source":
                row.mark_needs_source()
                self.paper_states[key] = ("needs_source", time.time())
            elif s == "abstract_only":
                row.mark_abstract_only()
                self.paper_states[key] = ("abstract_only", time.time())
            else:
                row.mark_failed()
                self.paper_states[key] = ("failed", None)
        self._refresh_info()
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

    # ---------- PDF ----------
    def open_pdf(self, key: str):
        paper = next((p for p in self.papers if p["key"] == key), None)
        path = paper.get("pdf_path") if paper else None
        if not path:
            self._set_status("该条目没有 PDF 附件")
            return
        if not os.path.exists(path):
            self._set_status(f"PDF 文件不存在：{path}")
            return
        try:
            os.startfile(path)
        except Exception as e:
            self._set_status(f"无法打开 PDF：{e}")

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
