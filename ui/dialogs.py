# -*- coding: utf-8 -*-
"""弹窗组件:审查历史 / 历史详情 / 权限审批记录。

从 app.py 迁出的三个 CTkToplevel 对话框,仅依赖 models 与主题常量,
与主窗口通过构造参数弱耦合。
"""

from typing import Any, Callable, Optional

import customtkinter as ctk

from core.risk_score import score_color
from models.history import (
    DECISION_APPROVED,
    DECISION_REJECTED,
    get_recent,
    update_decision,
)
from models.permission_history import get_recent_permissions

_FG_MUTED: str = "#8A96A8"


class HistoryDialog(ctk.CTkToplevel):
    """历史记录弹窗：支持关键字搜索与风险过滤，点击可查看详情。"""

    def __init__(
        self,
        master: Any,
        on_review_open: Callable[[Any], None],
    ) -> None:
        """构造并显示历史记录弹窗。

        参数:
            master: 父窗口。
            on_review_open: 点击记录详情时回调，参数为 ReviewHistory 对象。
        """
        super().__init__(master)
        self.title("DiffGuard - 历史记录")
        self.geometry("880x560")
        self._on_review_open: Callable[[Any], None] = on_review_open
        self._records: list[Any] = get_recent(200)
        self._search_var = ctk.StringVar(value="")

        self._build_ui()
        self.after(50, self.lift)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # 过滤区
        filter_bar: ctk.CTkFrame = ctk.CTkFrame(self, fg_color="transparent")
        filter_bar.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        filter_bar.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(filter_bar, text="搜索:", anchor="w").grid(
            row=0, column=0, padx=(0, 6), pady=4
        )
        search_entry: ctk.CTkEntry = ctk.CTkEntry(
            filter_bar, textvariable=self._search_var, placeholder_text="标题 / 文件名关键字…"
        )
        search_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        search_entry.bind("<KeyRelease>", lambda e: self._refresh())
        self._risk_filter = ctk.StringVar(value="全部")
        risk_menu: ctk.CTkOptionMenu = ctk.CTkOptionMenu(
            filter_bar,
            values=["全部", "低", "中", "高"],
            variable=self._risk_filter,
            width=90,
            command=lambda _v: self._refresh(),
        )
        risk_menu.grid(row=0, column=2, padx=6, pady=4)
        ctk.CTkButton(
            filter_bar, text="重新加载", width=90, command=self._reload
        ).grid(row=0, column=3, padx=6, pady=4)

        header: ctk.CTkFrame = ctk.CTkFrame(self)
        header.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 2))
        for col, w, txt in (
            (0, 3, "时间"),
            (1, 2, "文件数"),
            (2, 2, "风险"),
            (3, 2, "决策"),
            (4, 6, "标题"),
            (5, 1, "操作"),
        ):
            header.grid_columnconfigure(col, weight=w)
            ctk.CTkLabel(
                header,
                text=txt,
                text_color=_FG_MUTED,
                font=ctk.CTkFont(size=12, weight="bold"),
                anchor="w",
            ).grid(row=0, column=col, sticky="ew", padx=6, pady=6)

        self._body: ctk.CTkScrollableFrame = ctk.CTkScrollableFrame(self)
        self._body.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        for col, w in ((0, 3), (1, 2), (2, 2), (3, 2), (4, 6), (5, 1)):
            self._body.grid_columnconfigure(col, weight=w)

        self._refresh()

    def _filtered(self) -> list[Any]:
        """按搜索关键字 + 风险等级过滤。"""
        kw: str = self._search_var.get().strip().lower()
        risk: str = self._risk_filter.get()
        out: list[Any] = []
        for rec in self._records:
            if risk != "全部" and rec.risk_level != {"低": "low", "中": "medium", "高": "high"}[risk]:
                continue
            if kw:
                hay: str = f"{(rec.title or '').lower()} {rec.raw_diff or ''}".lower()
                if kw not in hay:
                    continue
            out.append(rec)
        return out[:120]

    def _reload(self) -> None:
        self._records = get_recent(200)
        self._refresh()

    def _refresh(self) -> None:
        """刷新表格内容（依据当前过滤条件）。"""
        for widget in self._body.winfo_children():
            widget.destroy()
        items: list[Any] = self._filtered()
        if not items:
            ctk.CTkLabel(
                self._body, text="（没有匹配的记录）", text_color=_FG_MUTED
            ).grid(row=0, column=0, columnspan=6, padx=8, pady=16)
            return
        for idx, record in enumerate(items):
            self._build_record_row(self._body, idx, record)

    def _build_record_row(self, body: Any, row: int, record: Any) -> None:
        """渲染一条历史记录行。"""
        risk_mark: str = {"high": "🔴 高", "medium": "🟡 中", "low": "🟢 低"}.get(
            record.risk_level, record.risk_level
        )
        decision_text: str = {
            "pending": "待决策",
            "approved": "已批准",
            "rejected": "已拒绝",
        }.get(record.user_decision, record.user_decision)

        ctk.CTkLabel(
            body,
            text=record.timestamp.strftime("%Y-%m-%d %H:%M"),
            anchor="w",
        ).grid(row=row, column=0, sticky="ew", padx=6, pady=4)
        ctk.CTkLabel(body, text=str(record.file_count), anchor="w").grid(
            row=row, column=1, sticky="ew", padx=6, pady=4
        )
        ctk.CTkLabel(body, text=risk_mark, anchor="w").grid(
            row=row, column=2, sticky="ew", padx=6, pady=4
        )
        ctk.CTkLabel(body, text=decision_text, anchor="w").grid(
            row=row, column=3, sticky="ew", padx=6, pady=4
        )
        ctk.CTkLabel(
            body,
            text=(record.title or "")[:40],
            anchor="w",
            text_color=_FG_MUTED,
        ).grid(row=row, column=4, sticky="ew", padx=6, pady=4)
        ctk.CTkButton(
            body,
            text="详情",
            width=56,
            height=26,
            command=lambda record=record: self._open_detail(record),
        ).grid(row=row, column=5, sticky="e", padx=6, pady=4)

    def _open_detail(self, record: Any) -> None:
        """打开单条记录的详情弹窗。"""
        DetailDialog(self, record, refresh=self._refresh)


class DetailDialog(ctk.CTkToplevel):
    """历史详情弹窗：展示报告与原始 diff，并允许更改决策。"""

    def __init__(
        self,
        master: Any,
        record: Any,
        refresh: Optional[Callable[[], Any]] = None,
    ) -> None:
        """构造详情弹窗。

        参数:
            master: 父窗口。
            record: ReviewHistory 记录对象。
            refresh: 决策变更后的回调（用于刷新父列表）。
        """
        super().__init__(master)
        self.title(f"DiffGuard - 历史详情 #{record.id}")
        self.geometry("900x640")
        self._record = record
        self._refresh_cb: Optional[Callable[[], Any]] = refresh

        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(0, weight=1)

        content: ctk.CTkFrame = ctk.CTkFrame(self)
        content.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        content.grid_rowconfigure(0, weight=1)
        content.grid_rowconfigure(2, weight=1)
        content.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            content, text="AI 审查报告", font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, sticky="w")
        report_box: ctk.CTkTextbox = ctk.CTkTextbox(
            content, font=ctk.CTkFont(family="微软雅黑", size=12), state="disabled"
        )
        report_box.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        report_box.configure(state="normal")
        report_box.insert("1.0", record.ai_report or "")
        report_box.configure(state="disabled")

        ctk.CTkLabel(
            content, text="原始 Diff", font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=2, column=0, sticky="w")
        diff_box: ctk.CTkTextbox = ctk.CTkTextbox(
            content, font=ctk.CTkFont(family="Consolas", size=12), state="disabled"
        )
        diff_box.grid(row=3, column=0, sticky="nsew")
        diff_box.configure(state="normal")
        diff_box.insert("1.0", record.raw_diff or "")
        diff_box.configure(state="disabled")

        decision_bar: ctk.CTkFrame = ctk.CTkFrame(self)
        decision_bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        decision_bar.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(
            decision_bar,
            text="决策: {}".format(
                {
                    "pending": "待决策",
                    "approved": "已批准",
                    "rejected": "已拒绝",
                }.get(record.user_decision, record.user_decision)
            ),
        ).grid(row=0, column=0, padx=6, pady=6)
        for col, label, decision in (
            (1, "批准", DECISION_APPROVED),
            (2, "拒绝", DECISION_REJECTED),
        ):
            ctk.CTkButton(
                decision_bar,
                text=label,
                fg_color="#238636" if decision == DECISION_APPROVED else "#da3633",
                hover_color="#2ea043" if decision == DECISION_APPROVED else "#f85149",
                width=80,
                command=lambda d=decision: self._set_decision(d),
            ).grid(row=0, column=col, padx=6, pady=6)
        self._decision_var: ctk.StringVar = ctk.StringVar(value=record.user_decision)

    def _set_decision(self, decision: str) -> None:
        """持久化用户决策并关闭弹窗。"""
        if update_decision(self._record.id, decision):
            self._record.user_decision = decision
            self._decision_var.set(decision)
            if callable(self._refresh_cb):
                self._refresh_cb()
            self.destroy()
        else:
            ctk.CTkLabel(self, text="更新决策失败，请查看日志", text_color="#f85149").pack()


class PermissionHistoryDialog(ctk.CTkToplevel):
    """权限审批记录弹窗：以表格展示已捕获/已决策的权限请求。"""

    def __init__(self, master: Any) -> None:
        super().__init__(master)
        self.title("DiffGuard - 权限审批记录")
        self.geometry("980x560")
        self._records: list[Any] = get_recent_permissions(100)

        self._build_ui()
        self.after(50, self.lift)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header: ctk.CTkFrame = ctk.CTkFrame(self)
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 2))
        for col, w, txt in (
            (0, 3, "时间"),
            (1, 2, "来源"),
            (2, 2, "类型"),
            (3, 2, "动作"),
            (4, 2, "风险"),
            (5, 5, "目标"),
            (6, 2, "决策"),
        ):
            header.grid_columnconfigure(col, weight=w)
            ctk.CTkLabel(
                header,
                text=txt,
                text_color=_FG_MUTED,
                font=ctk.CTkFont(size=12, weight="bold"),
                anchor="w",
            ).grid(row=0, column=col, sticky="ew", padx=6, pady=6)

        body: ctk.CTkScrollableFrame = ctk.CTkScrollableFrame(self)
        body.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        for col, w in ((0, 3), (1, 2), (2, 2), (3, 2), (4, 2), (5, 5), (6, 2)):
            body.grid_columnconfigure(col, weight=w)

        if not self._records:
            ctk.CTkLabel(body, text="（暂无权限审批记录）", text_color=_FG_MUTED).grid(
                row=0, column=0, columnspan=7, padx=8, pady=16
            )
            return

        decision_text: dict[str, str] = {
            "pending": "待决策",
            "once_allowed": "允许一次",
            "always_allowed": "总是允许",
            "rejected": "已拒绝",
        }
        for idx, record in enumerate(self._records):
            ctk.CTkLabel(
                body,
                text=record.timestamp.strftime("%Y-%m-%d %H:%M"),
                anchor="w",
            ).grid(row=idx, column=0, sticky="ew", padx=6, pady=4)
            ctk.CTkLabel(body, text=record.source, anchor="w").grid(
                row=idx, column=1, sticky="ew", padx=6, pady=4
            )
            ctk.CTkLabel(body, text=record.prompt_type, anchor="w").grid(
                row=idx, column=2, sticky="ew", padx=6, pady=4
            )
            ctk.CTkLabel(body, text=record.action, anchor="w").grid(
                row=idx, column=3, sticky="ew", padx=6, pady=4
            )
            ctk.CTkLabel(
                body,
                text=str(record.risk_score),
                anchor="w",
                text_color=score_color(record.risk_score),
            ).grid(row=idx, column=4, sticky="ew", padx=6, pady=4)
            ctk.CTkLabel(
                body,
                text=(record.target or "")[:40],
                anchor="w",
                text_color=_FG_MUTED,
            ).grid(row=idx, column=5, sticky="ew", padx=6, pady=4)
            ctk.CTkLabel(
                body, text=decision_text.get(record.user_decision, record.user_decision), anchor="w"
            ).grid(row=idx, column=6, sticky="ew", padx=6, pady=4)
