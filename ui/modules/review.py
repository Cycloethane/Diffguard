# -*- coding: utf-8 -*-
"""审查模块:风险仪表盘 + 左右分栏(文件/Diff + AI 报告)+ 空状态引导。

只负责布局构建;业务逻辑在 ui.controllers.ReviewFlow,控件引用经
flow.attach() 绑定。
"""

from typing import Any

import customtkinter as ctk

from ui.theme import accent, accent_primary, frost_hi, surface_border, text_color

_FG_MUTED: str = "#8A96A8"


class ReviewModule:
    """审查模块。"""

    key = "review"
    title = "审查"
    icon = "🛡"

    def build(self, container: Any, app: Any) -> None:
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        main: ctk.CTkFrame = ctk.CTkFrame(container, fg_color="transparent")
        main.grid(row=0, column=0, sticky="nsew")
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=2, minsize=380)
        main.grid_columnconfigure(1, weight=3, minsize=480)

        # 顶部：仪表盘 + 快捷操作
        top: ctk.CTkFrame = ctk.CTkFrame(main, fg_color="transparent")
        top.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        top.grid_columnconfigure(1, weight=1)

        # 左侧：文件列表 + Diff
        left: ctk.CTkFrame = ctk.CTkFrame(
            main, corner_radius=12, fg_color="transparent",
            border_width=1, border_color=surface_border(True),
        )
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        left.grid_rowconfigure(1, weight=1)
        left.grid_rowconfigure(3, weight=3)
        left.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(left, text="变更文件", font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 2)
        )
        file_list_frame: ctk.CTkScrollableFrame = ctk.CTkScrollableFrame(left)
        file_list_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=2)
        ctk.CTkLabel(left, text="Diff 详情", font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=2, column=0, sticky="w", padx=10, pady=(6, 2)
        )
        diff_body: ctk.CTkFrame = ctk.CTkFrame(left)
        diff_body.grid(row=3, column=0, sticky="nsew", padx=6, pady=(0, 6))
        diff_body.grid_rowconfigure(0, weight=1)
        diff_body.grid_columnconfigure(0, weight=1)
        diff_textbox: ctk.CTkTextbox = ctk.CTkTextbox(
            diff_body, font=ctk.CTkFont(family="Consolas", size=12), wrap="none",
            fg_color="#EAF0F6",
        )
        diff_textbox.grid(row=0, column=0, sticky="nsew")
        diff_scroll_y: ctk.CTkScrollbar = ctk.CTkScrollbar(diff_body, command=diff_textbox.yview)
        diff_scroll_y.grid(row=0, column=1, sticky="ns")
        diff_textbox.configure(yscrollcommand=diff_scroll_y.set)

        # 右侧：AI 报告
        right: ctk.CTkFrame = ctk.CTkFrame(
            main, corner_radius=12, fg_color="transparent",
            border_width=1, border_color=surface_border(True),
        )
        right.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(right, text="AI 审查报告", font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 2)
        )
        report_body: ctk.CTkFrame = ctk.CTkFrame(right)
        report_body.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        report_body.grid_rowconfigure(0, weight=1)
        report_body.grid_columnconfigure(0, weight=1)
        report_textbox: ctk.CTkTextbox = ctk.CTkTextbox(
            report_body, font=ctk.CTkFont(family="微软雅黑", size=13), state="disabled",
            fg_color="#EAF0F6",
        )
        report_textbox.grid(row=0, column=0, sticky="nsew")
        report_scroll_y: ctk.CTkScrollbar = ctk.CTkScrollbar(report_body, command=report_textbox.yview)
        report_scroll_y.grid(row=0, column=1, sticky="ns")
        report_textbox.configure(yscrollcommand=report_scroll_y.set)

        # 仪表盘(最后构建,确保位于 top 内)
        dash_score, dash_level, dash_count, dash_points = self._build_dashboard(top, app)

        app.review_flow.attach(
            diff_textbox=diff_textbox,
            report_textbox=report_textbox,
            file_list_frame=file_list_frame,
            dash_score=dash_score,
            dash_level=dash_level,
            dash_count=dash_count,
            dash_points=dash_points,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _build_dashboard(parent: Any, app: Any) -> tuple[Any, Any, Any, Any]:
        """构建顶部风险仪表盘卡(右端嵌吉祥物头像),返回四个数据标签。"""
        dash: ctk.CTkFrame = ctk.CTkFrame(parent, corner_radius=12, fg_color="transparent")
        dash.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        dash.grid_columnconfigure(3, weight=1)
        for col in range(3):
            dash.grid_columnconfigure(col, weight=0)

        ctk.CTkLabel(
            dash, text="综合风险", font=ctk.CTkFont(size=12), text_color=_FG_MUTED
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(8, 0))
        dash_score: ctk.CTkLabel = ctk.CTkLabel(
            dash, text="--", font=ctk.CTkFont(size=26, weight="bold"), text_color=_FG_MUTED,
        )
        dash_score.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 6))

        ctk.CTkLabel(
            dash, text="风险等级", font=ctk.CTkFont(size=12), text_color=_FG_MUTED
        ).grid(row=0, column=1, sticky="w", padx=12, pady=(8, 0))
        dash_level: ctk.CTkLabel = ctk.CTkLabel(
            dash, text="--", font=ctk.CTkFont(size=18, weight="bold")
        )
        dash_level.grid(row=1, column=1, sticky="w", padx=12, pady=(0, 6))

        ctk.CTkLabel(
            dash, text="变更文件", font=ctk.CTkFont(size=12), text_color=_FG_MUTED
        ).grid(row=0, column=2, sticky="w", padx=12, pady=(8, 0))
        dash_count: ctk.CTkLabel = ctk.CTkLabel(
            dash, text="0", font=ctk.CTkFont(size=18, weight="bold")
        )
        dash_count.grid(row=1, column=2, sticky="w", padx=12, pady=(0, 6))

        ctk.CTkLabel(
            dash, text="主要风险点", font=ctk.CTkFont(size=12), text_color=_FG_MUTED
        ).grid(row=0, column=3, sticky="nw", padx=12, pady=(8, 0))
        dash_points: ctk.CTkLabel = ctk.CTkLabel(
            dash, font=ctk.CTkFont(size=13), anchor="w", justify="left",
            text="欢迎使用 DiffGuard —— 复制 git diff 到剪贴板即可自动载入\n"
                 "Ctrl+V 载入 · Ctrl+Enter 审查 · Ctrl+S 保存 · Ctrl+E 导出",
        )
        dash_points.grid(row=1, column=3, sticky="new", padx=12, pady=(0, 6))

        # 右端吉祥物头像(空态欢迎感,载入后保留)
        try:
            from pathlib import Path

            from PIL import Image

            mascot_path = Path(__file__).resolve().parent.parent.parent / "assets" / "mascot_dash.png"
            if mascot_path.is_file():
                pil = Image.open(mascot_path)
                avatar = ctk.CTkImage(light_image=pil, size=pil.size)
                ctk.CTkLabel(dash, text="", image=avatar).grid(
                    row=0, column=4, rowspan=2, sticky="e", padx=(0, 10)
                )
        except Exception:
            pass
        return dash_score, dash_level, dash_count, dash_points

