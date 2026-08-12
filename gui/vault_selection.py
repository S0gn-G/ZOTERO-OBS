"""多个 Obsidian Vault 的专用选择窗口。"""
from __future__ import annotations

from collections.abc import Callable, Sequence

import customtkinter as ctk

from discovery.core import DiscoveryCandidate, notes_path_for_vault
from gui import design as ui


class VaultSelectionDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        candidates: Sequence[DiscoveryCandidate],
        on_selected: Callable[[DiscoveryCandidate], None],
        on_cancel: Callable[[], None] | None = None,
    ):
        super().__init__(master)
        indexed = [(str(index), candidate) for index, candidate in enumerate(candidates)]
        self._candidates = dict(indexed)
        self._on_selected = on_selected
        self._on_cancel = on_cancel
        self._closed = False

        self.title("选择 Obsidian 仓库")
        ui.fit_window(self, (700, 480), (620, 400), (48, 64))
        self.configure(fg_color=ui.APP_BG)
        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        header = ctk.CTkFrame(self, height=92, corner_radius=0, fg_color=ui.SURFACE)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text="选择 Obsidian 仓库", anchor="w", text_color=ui.TEXT,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=22, weight="bold"),
        ).pack(anchor="w", padx=28, pady=(18, 2))
        ctk.CTkLabel(
            header, text="检测到多个 Vault，请选择论文笔记要接入的位置",
            anchor="w", text_color=ui.TEXT_SECONDARY,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=12),
        ).pack(anchor="w", padx=28)
        ctk.CTkFrame(header, height=1, fg_color=ui.BORDER).pack(fill="x", side="bottom")

        footer = ctk.CTkFrame(self, height=72, corner_radius=0, fg_color=ui.SURFACE)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        ctk.CTkFrame(footer, height=1, fg_color=ui.BORDER).pack(fill="x")
        ctk.CTkButton(
            footer, text="接入所选仓库", width=142, height=40,
            fg_color=ui.ACCENT, hover_color=ui.ACCENT_HOVER,
            command=self._confirm,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13, weight="bold"),
        ).pack(side="right", padx=(8, 28), pady=15)
        ctk.CTkButton(
            footer, text="取消", width=90, height=40,
            fg_color=ui.SURFACE, hover_color=ui.SURFACE_HOVER,
            border_width=1, border_color=ui.BORDER_STRONG, text_color=ui.TEXT,
            command=self._cancel,
            font=ctk.CTkFont(family=ui.FONT_FAMILY, size=13),
        ).pack(side="right", pady=15)

        content = ctk.CTkScrollableFrame(
            self, corner_radius=0, fg_color=ui.APP_BG,
            scrollbar_button_color=ui.BORDER_STRONG,
            scrollbar_button_hover_color=ui.TEXT_TERTIARY,
        )
        content.pack(fill="both", expand=True, padx=18, pady=12)

        first = indexed[0][0] if indexed else ""
        self._selected = ctk.StringVar(value=first)
        for token, candidate in indexed:
            row = ctk.CTkFrame(
                content, corner_radius=10, fg_color=ui.SURFACE,
                border_width=1, border_color=ui.BORDER,
            )
            row.pack(fill="x", padx=8, pady=5)
            radio = ctk.CTkRadioButton(
                row, text="", width=24, variable=self._selected,
                value=token,
            )
            radio.pack(side="left", padx=(16, 10), pady=18)
            text = ctk.CTkFrame(row, fg_color="transparent")
            text.pack(side="left", fill="x", expand=True, padx=(0, 16), pady=12)
            ctk.CTkLabel(
                text, text=candidate.label, anchor="w", text_color=ui.TEXT,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=14, weight="bold"),
            ).pack(fill="x", anchor="w")
            ctk.CTkLabel(
                text, text=candidate.value, anchor="w", justify="left",
                wraplength=540, text_color=ui.TEXT_SECONDARY,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            ).pack(fill="x", anchor="w", pady=(2, 0))
            ctk.CTkLabel(
                text, text=f"笔记目录：{notes_path_for_vault(candidate)}",
                anchor="w", justify="left", wraplength=540,
                text_color=ui.TEXT_TERTIARY,
                font=ctk.CTkFont(family=ui.FONT_FAMILY, size=11),
            ).pack(fill="x", anchor="w", pady=(2, 0))

    def _confirm(self):
        candidate = self._candidates.get(self._selected.get())
        if candidate is None:
            return
        self._closed = True
        self.grab_release()
        self.destroy()
        self._on_selected(candidate)

    def _cancel(self):
        if self._closed:
            return
        self._closed = True
        self.grab_release()
        self.destroy()
        if self._on_cancel:
            self._on_cancel()
