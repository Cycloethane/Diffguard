# -*- coding: utf-8 -*-
"""历史模块视图：在模块容器中展示审查历史列表，点击查看详情。"""

from typing import Any, Optional

import customtkinter as ctk

from models.history import get_recent
from ui.theme import frost, text_color, text_muted

_RISK_COLOR: dict[str, str] = {
    "high": "#DA3633",
    "medium": "#D29922",
    "low": "#238636",
    "pending": "#607890",
}


class HistoryView(ctk.CTkFrame):
    """内嵌审查历史列表。"""

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="审查历史", font=ctk.CTkFont(size=16, weight="bold"),
            text_color=text_color(True),
        ).grid(row=0, column=0, sticky="w", padx=6, pady=(0, 6))

        self.list_scroll: ctk.CTkScrollableFrame = ctk.CTkScrollableFrame(
            self, fg_color="transparent"
        )
        self.list_scroll.grid(row=1, column=0, sticky="nsew")
        self.list_scroll.grid_columnconfigure(0, weight=1)
        self._row: int = 0
        self._reload()

    def _reload(self) -> None:
        """载入最近记录。"""
        for w in self.list_scroll.winfo_children():
            w.destroy()
        self._row = 0
        records = get_recent(100)
        if not records:
            ctk.CTkLabel(
                self.list_scroll, text="暂无审查记录", text_color=text_muted(True)
            ).grid(row=0, column=0, padx=12, pady=30)
            return
        for rec in records:
            self._build_row(rec)

    def _build_row(self, rec: Any) -> None:
        color: str = _RISK_COLOR.get(rec.risk_level, "#607890")
        row: ctk.CTkFrame = ctk.CTkFrame(self.list_scroll, corner_radius=8, fg_color="transparent")
        row.grid(row=self._row, column=0, sticky="ew", padx=6, pady=3)
        row.grid_columnconfigure(1, weight=1)
        self._row += 1

        ctk.CTkLabel(
            row, text=f"[{rec.timestamp:%Y-%m-%d %H:%M}]",
            font=ctk.CTkFont(size=11), text_color=text_muted(True),
        ).grid(row=0, column=0, sticky="w", padx=8, pady=(6, 0))
        ctk.CTkLabel(
            row, text=rec.title or "(无标题)",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=text_color(True),
            anchor="w", justify="left",
        ).grid(row=0, column=1, sticky="ew", padx=6, pady=(6, 0))
        ctk.CTkLabel(
            row, text=rec.risk_level,
            font=ctk.CTkFont(size=11, weight="bold"), text_color=color,
        ).grid(row=0, column=2, sticky="e", padx=8, pady=(6, 0))
        ctk.CTkLabel(
            row,
            text=f"{rec.file_count} 文件 · 决策 {rec.user_decision}",
            font=ctk.CTkFont(size=11), text_color=text_muted(True),
        ).grid(row=1, column=1, columnspan=2, sticky="ew", padx=6, pady=(0, 6))

        row.bind("<Button-1>", lambda e, r=rec: self._open_detail(r))

    def _open_detail(self, rec: Any) -> None:
        """打开记录详情弹窗。"""
        dlg = ctk.CTkToplevel(self)
        dlg.title("DiffGuard - 审查详情")
        dlg.geometry("760x560")
        dlg.attributes("-topmost", True)
        try:
            dlg.attributes("-alpha", 1.0)
        except Exception:
            pass
        dlg.grid_rowconfigure(0, weight=1)
        dlg.grid_columnconfigure(0, weight=1)

        box: ctk.CTkFrame = ctk.CTkFrame(dlg, fg_color="transparent", corner_radius=10)
        box.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        box.grid_rowconfigure(1, weight=1)
        box.grid_columnconfigure(0, weight=1)

        meta = (
            f"[{rec.timestamp:%Y-%m-%d %H:%M}]  {rec.file_count} 文件  "
            f"风险 {rec.risk_level}  决策 {rec.user_decision}"
        )
        ctk.CTkLabel(
            box, text=rec.title or "(无标题)",
            font=ctk.CTkFont(size=16, weight="bold"), text_color=text_color(True),
            anchor="w", justify="left",
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        ctk.CTkLabel(
            box, text=meta, font=ctk.CTkFont(size=12), text_color=text_muted(True), anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 4))

        tb: ctk.CTkTextbox = ctk.CTkTextbox(
            box, font=ctk.CTkFont(family="微软雅黑", size=13), wrap="word"
        )
        tb.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        tb.insert("1.0", rec.ai_report or "(无报告)")
        tb.configure(state="disabled")

        ctk.CTkButton(
            box, text="关闭", width=90, height=32,
            command=dlg.destroy, fg_color="#607890", hover_color="#7890A8",
        ).grid(row=3, column=0, padx=10, pady=(0, 10))
