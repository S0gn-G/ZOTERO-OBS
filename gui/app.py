"""主窗口：文献列表 + 勾选生成笔记。"""
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import customtkinter as ctk

from config import load_config, save_config, CONFIG_PATH, resource_path
from obsidian_writer import ObsidianWriter
from note_generator import generate_note, load_template, default_template_path, cleanup_figures
from zotero_client import ZoteroClient, ZoteroError
from gui import icons
from gui.settings_view import SettingsWindow

MAX_WORKERS = 3  # 批量生成的并发数，兼顾速度与代理限速

FONT_FAMILY = "Microsoft YaHei"
GREEN = "#2F7D5C"
GRAY = "#7E8780"
RED = "#B4472F"
AMBER = "#B07A2A"

# 笔记状态：ok=已生成 / needs_source=证据不足待原文 / abstract_only=仅摘要 / placeholder=正文含占位符需修复 / none=未生成
NOTE_STATE_LABEL = {"ok": "已生成", "needs_source": "需原文", "abstract_only": "仅摘要", "placeholder": "需修复", "none": "未生成"}
NOTE_STATE_COLOR = {"ok": GREEN, "needs_source": AMBER, "abstract_only": AMBER, "placeholder": RED, "none": GRAY}


def _fmt_mtime(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


class PaperRow:
    """列表中的一行文献（卡片式）。"""

    def __init__(self, parent, paper: dict, note_key: str, note_state: str, on_generate, on_open_pdf, updated_at=None):
        self.paper = paper
        self.note_key = note_key
        self.note_state = note_state
        self.updated_at = updated_at
        self.frame = ctk.CTkFrame(
            parent, corner_radius=8, border_width=1,
            border_color=("#D5DAD5", "#39413D"), fg_color="transparent",
        )
        self.frame.pack(fill="x", pady=3, padx=2)
        self.frame.bind("<Enter>", lambda e: self.frame.configure(fg_color=("#ECEFEC", "#2A322F")))
        self.frame.bind("<Leave>", lambda e: self.frame.configure(fg_color="transparent"))

        self.check = ctk.CTkCheckBox(self.frame, width=28, text="")
        self.check.pack(side="left", padx=(12, 6), pady=12)

        self.status = ctk.CTkLabel(
            self.frame, text=NOTE_STATE_LABEL[note_state], width=56,
            fg_color=NOTE_STATE_COLOR[note_state],
            text_color="white", corner_radius=6,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
        )
        self.status.pack(side="right", padx=(4, 12), pady=12)

        self.generate_btn = ctk.CTkButton(
            self.frame, text="生成", width=68, height=28, image=icons.play(),
            command=lambda: on_generate(paper["key"]),
        )
        self.generate_btn.pack(side="right", padx=(0, 6), pady=12)

        if paper.get("pdf_path"):
            ctk.CTkButton(
                self.frame, text="PDF", width=58, height=28, image=icons.pdf(),
                command=lambda: on_open_pdf(paper["key"]),
            ).pack(side="right", padx=(0, 6), pady=12)

        suffix = {"ok": "  ✔", "needs_source": "  ⚠", "abstract_only": "  ⚠", "placeholder": "  ✗"}.get(note_state, "")
        title = paper["title"] + suffix
        ctk.CTkLabel(self.frame, text=title, anchor="w", justify="left",
                     font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold")).pack(
            side="top", anchor="w", padx=(0, 12), pady=(10, 0))
        self._sub_base = " · ".join(filter(None, [", ".join(paper["authors"]) if paper["authors"] else "", paper["year"], paper["itemType"]]))
        self.sub_label = ctk.CTkLabel(self.frame, text=self._sub_text(), anchor="w", text_color=("gray", "gray"),
                                      font=ctk.CTkFont(family=FONT_FAMILY, size=12))
        self.sub_label.pack(side="top", anchor="w", padx=(0, 12), pady=(0, 10))

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
        self.note_state = "ok"
        self.status.configure(text="已生成", fg_color=GREEN)
        self.set_updated_at(_fmt_mtime(time.time()))

    def mark_needs_source(self):
        self.note_state = "needs_source"
        self.status.configure(text="需原文", fg_color=AMBER)
        self.set_updated_at(_fmt_mtime(time.time()))

    def mark_abstract_only(self):
        self.note_state = "abstract_only"
        self.status.configure(text="仅摘要", fg_color=AMBER)
        self.set_updated_at(_fmt_mtime(time.time()))

    def set_generating(self, on: bool):
        if on:
            self.generate_btn.configure(state="disabled", text="生成中…")
        else:
            self.generate_btn.configure(state="normal", text="生成")

    def mark_failed(self):
        self.status.configure(text="失败", fg_color=RED)
        self.generate_btn.configure(state="normal", text="重试")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ZotNotes · Zotero → Obsidian 论文笔记")
        self.geometry("940x680")
        self.minsize(760, 500)

        self.cfg = load_config()
        if not os.path.exists(CONFIG_PATH):
            save_config(self.cfg)  # 首次启动：落盘默认配置，用户可直接编辑
        load_template(self.cfg)  # 模板缺失时自动创建默认模板
        self.papers: list[dict] = []
        self.rows: dict[str, PaperRow] = {}
        self.writer = ObsidianWriter(self.cfg["vault_path"], self.cfg["notes_folder"])
        self._busy = False
        self.generate_btn = None
        self.settings_btn = None
        self._ui_queue = queue.Queue()

        self._set_window_icon()
        self._build_ui()
        self.after(200, self.refresh)
        self.after(50, self._poll_ui_queue)

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
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                fn()
        except queue.Empty:
            pass
        self.after(50, self._poll_ui_queue)

    # ---------- UI ----------
    def _build_ui(self):
        top = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 6))
        self.settings_btn = ctk.CTkButton(top, text="设置", width=92, height=32, image=icons.settings(),
                                          command=self.open_settings)
        self.settings_btn.pack(side="left", padx=(0, 6))
        ctk.CTkButton(top, text="模板", width=92, height=32, image=icons.template(),
                      command=self.open_template).pack(side="left", padx=6)
        ctk.CTkButton(top, text="刷新", width=92, height=32, image=icons.refresh(),
                      command=self.refresh).pack(side="left", padx=6)
        self.info_label = ctk.CTkLabel(top, text="", anchor="w",
                                       font=ctk.CTkFont(family=FONT_FAMILY, size=13))
        self.info_label.pack(side="left", padx=10)

        head = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        head.pack(fill="x", padx=18)
        ctk.CTkLabel(head, text="论文", anchor="w", text_color=("gray", "gray"),
                     font=ctk.CTkFont(family=FONT_FAMILY, size=12)).pack(side="left")
        ctk.CTkLabel(head, text="操作 / 状态", anchor="e", text_color=("gray", "gray"),
                     font=ctk.CTkFont(family=FONT_FAMILY, size=12)).pack(side="right")

        self.list_frame = ctk.CTkScrollableFrame(self, corner_radius=10)
        self.list_frame.pack(fill="both", expand=True, padx=12, pady=8)

        bottom = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        bottom.pack(fill="x", side="bottom", padx=14, pady=(4, 12))
        self.generate_btn = ctk.CTkButton(bottom, text="生成勾选的笔记", width=178, height=36,
                                          image=icons.play(), command=self.generate)
        self.generate_btn.pack(side="left", padx=(0, 12))
        self.progress = ctk.CTkProgressBar(bottom, width=400)
        self.progress.set(0)
        self.progress.pack(side="left", padx=10)
        self.status_label = ctk.CTkLabel(bottom, text="就绪", anchor="w",
                                         font=ctk.CTkFont(family=FONT_FAMILY, size=12))
        self.status_label.pack(side="left", padx=10, expand=True)

    def _set_info(self, text):
        self.info_label.configure(text=text)

    def _set_status(self, text):
        self.status_label.configure(text=text)

    def _set_busy(self, busy: bool):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for row in self.rows.values():
            row.generate_btn.configure(state=state)
        if self.generate_btn:
            self.generate_btn.configure(state=state)
        if self.settings_btn:
            self.settings_btn.configure(state=state)

    def _refresh_info(self, states=None):
        """更新顶部信息行。传 states 则复用（刷新路径），否则重扫一次（生成后计数）。"""
        if states is None:
            states = self.writer.scan_states()
        done = sum(1 for _k, s, _m in states if s == "ok")
        need = sum(1 for _k, s, _m in states if s == "insufficient")
        bad = sum(1 for _k, s, _m in states if s == "placeholder")
        abstract = sum(1 for _k, s, _m in states if s == "abstract_only")
        info = f"{len(self.papers)} 篇文献 · {done} 篇已生成"
        if abstract:
            info += f" · {abstract} 篇仅摘要"
        if bad:
            info += f" · {bad} 篇需修复"
        if need:
            info += f" · {need} 篇需原文"
        self._set_info(info)

    # ---------- 数据 ----------
    def refresh(self):
        if self._busy:
            return
        self._set_status("正在读取 Zotero…")
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            client = ZoteroClient(self.cfg["zotero_base"])
            papers = client.fetch_papers()
            if self.cfg.get("only_with_pdf", True):
                papers = [p for p in papers if p.get("pdf_path")]
            for p in papers:
                p["citationKey"] = p["citationKey"] or ZoteroClient.fallback_citation_key(p)
            states = self.writer.scan_states()  # 单次扫描，各状态集合都由它派生
            result = (papers, states)
            self._post(lambda: self._apply_refresh(result))
        except Exception as e:
            err = str(e)
            self._post(lambda err=err: self._show_error(f"读取失败：{err}"))

    def _apply_refresh(self, result):
        papers, states = result
        self.papers = papers
        self.progress.stop()
        self.progress.configure(mode="determinate")
        for child in self.list_frame.winfo_children():
            child.destroy()
        self.rows.clear()
        note_keys = {k for k, _s, _m in states}
        insufficient = {k for k, s, _m in states if s == "insufficient"}
        placeholders = {k for k, s, _m in states if s == "placeholder"}
        abstract = {k for k, s, _m in states if s == "abstract_only"}
        mtimes = {k: m for k, _s, m in states}
        if not papers:
            ctk.CTkLabel(
                self.list_frame,
                text="没有可显示的文献\n\n请确认 Zotero 已运行并开启本地 API；\n或在 设置 里调整「仅显示含 PDF 的文献」",
                text_color=("gray", "gray"),
                font=ctk.CTkFont(family=FONT_FAMILY, size=14),
                justify="center",
            ).pack(pady=80)
            self._refresh_info(states)
            self._set_status("库中没有文献")
            return
        for p in papers:
            if p["key"] in placeholders:
                state = "placeholder"
            elif p["key"] in insufficient:
                state = "needs_source"
            elif p["key"] in abstract:
                state = "abstract_only"
            elif p["key"] in note_keys:
                state = "ok"
            else:
                state = "none"
            updated = _fmt_mtime(mtimes[p["key"]]) if p["key"] in mtimes else None
            row = PaperRow(self.list_frame, p, p["citationKey"], state,
                           on_generate=self.generate_one, on_open_pdf=self.open_pdf,
                           updated_at=updated)
            self.rows[p["key"]] = row
        self._refresh_info(states)
        self._set_status(f"已加载 {len(papers)} 篇")

    def _show_error(self, msg):
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self._set_status(msg)
        self._set_info("⚠ " + msg)

    # ---------- 单篇生成 ----------
    def generate_one(self, key: str):
        if self._busy:
            return
        row = self.rows.get(key)
        if not row:
            return
        if not self.cfg["vault_path"]:
            self._set_status("请先在 设置 里填写 Obsidian Vault 路径")
            return
        if row.note_state == "ok" and not self.cfg["overwrite"]:
            self._set_status("该篇已有笔记，如需覆盖请在 设置 中开启「覆盖已生成的笔记」")
            return
        if self.cfg["llm_enabled"] and not self.cfg["llm_api_key"]:
            self._set_status("LLM 已启用但未填 API Key（在 设置 里填写，或关闭 LLM）")
            return
        cfg = dict(self.cfg)  # 快照：生成期间改设置不影响本次
        self._set_busy(True)
        row.set_generating(True)
        threading.Thread(target=self._generate_one_worker, args=(row, cfg), daemon=True).start()

    def _run_generate(self, row, writer, cfg):
        """生成单篇：LLM 管道 → 先拷图表（缺图判失败）→ 写笔记（保留手写区）→ 清暂存。返回 (ok, status, msg)。"""
        figures = []
        try:
            result = generate_note(row.paper, cfg, note_key=row.note_key)
            figures = result["figures"]
            if figures:
                missing = writer.import_images(row.note_key, figures)
                if missing:
                    return False, "failed", f"图表拷贝失败：{', '.join(missing)}"
            writer.write_note_preserving(row.note_key, result["content"], zotero_key=row.paper["key"])
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
        row.set_generating(False)
        if ok and status == "needs_source":
            row.mark_needs_source()
            self._set_status(f"已生成骨架（证据不足）：{row.paper['title'][:40]}")
        elif ok and status == "abstract_only":
            row.mark_abstract_only()
            self._set_status(f"已生成（仅摘要）：{row.paper['title'][:40]}")
        elif ok:
            row.mark_done()
            self._set_status(f"已生成：{row.paper['title'][:40]}")
        else:
            row.mark_failed()
            self._set_status(f"生成失败：{err}")
        self._refresh_info()
        self._set_busy(False)

    # ---------- 批量生成 ----------
    def generate(self):
        if self._busy:
            return
        selected = [r for r in self.rows.values() if r.selected()]
        if not selected:
            self._set_status("请先勾选至少一篇文献")
            return
        if not self.cfg["vault_path"]:
            self._set_status("请先在 设置 里填写 Obsidian Vault 路径")
            return
        if self.cfg["llm_enabled"] and not self.cfg["llm_api_key"]:
            self._set_status("LLM 已启用但未填 API Key（在 设置 里填写，或关闭 LLM）")
            return
        cfg = dict(self.cfg)  # 快照：批量生成期间改设置不影响本次
        overwrite = cfg["overwrite"]
        to_process = [r for r in selected if overwrite or r.note_state != "ok"]
        skips = [r for r in selected if r.note_state == "ok" and not overwrite]
        self._set_status(f"正在生成 {len(to_process)} 篇（跳过 {len(skips)} 篇已有笔记）…")
        self.progress.set(0)
        self._set_busy(True)
        threading.Thread(
            target=self._generate_worker,
            args=(to_process, skips, cfg),
            daemon=True,
        ).start()

    def _generate_worker(self, rows, skips, cfg):
        writer = ObsidianWriter(cfg["vault_path"], cfg["notes_folder"])
        total = len(rows)
        results = [(r.paper["key"], "ok", "跳过（已有笔记）") for r in skips]
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
        for key, s, r in results:
            row = self.rows.get(key)
            if not row:
                continue
            if s == "ok" and r == "OK":
                row.mark_done()
            elif s == "needs_source":
                row.mark_needs_source()
            elif s == "abstract_only":
                row.mark_abstract_only()
            elif r != "跳过（已有笔记）":
                row.mark_failed()
        self._refresh_info()
        self._set_busy(False)
        self.progress.set(1.0)
        suffix = ""
        if need:
            suffix += f"，{need} 篇需原文"
        if abstract:
            suffix += f"，{abstract} 篇仅摘要"
        self._set_status(f"完成：成功 {ok}/{len(results)}{suffix}")

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
        self.writer = ObsidianWriter(cfg["vault_path"], cfg["notes_folder"])
        self._set_status("设置已保存")
        self.refresh()
