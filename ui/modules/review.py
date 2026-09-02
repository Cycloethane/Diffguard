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

        # 空状态引导(未载入 diff 时,覆盖在模块区左上角,与旧实现一致)
        guide = self._build_guide(container, app)

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
            guide=guide,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _build_dashboard(parent: Any, app: Any) -> tuple[Any, Any, Any, Any]:
        """构建顶部风险仪表盘卡,返回四个数据标签。"""
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
            dash, text="尚未加载 diff", font=ctk.CTkFont(size=13), anchor="w", justify="left"
        )
        dash_points.grid(row=1, column=3, sticky="new", padx=12, pady=(0, 6))
        return dash_score, dash_level, dash_count, dash_points

    @staticmethod
    def _build_guide(parent: Any, app: Any) -> Any:
        """空状态欢迎卡：坐姿吉祥物 + 快捷键指引（未载入 diff 时）。"""
        from pathlib import Path

        from ui.theme import frost

        accent_color: str = accent_primary(getattr(app.config, "accent", "blue"), light=True)
        accent_hover: str = accent(getattr(app.config, "accent", "blue"), light=True)[1]
        guide = ctk.CTkFrame(parent, fg_color=frost(True), corner_radius=14)
        guide.grid(row=0, column=0, sticky="nw", padx=8, pady=8)

        row = ctk.CTkFrame(guide, fg_color="transparent")
        row.pack(padx=14, pady=12)

        # 左：坐姿吉祥物
        mascot_path = Path(__file__).resolve().parent.parent.parent / "assets" / "mascot_guide.png"
        if mascot_path.is_file():
            try:
                from PIL import Image

                pil = Image.open(mascot_path)
                mascot_img = ctk.CTkImage(light_image=pil, size=(175, 240))
                ctk.CTkLabel(row, text="", image=mascot_img).pack(side="left", padx=(0, 18))
            except Exception:
                pass

        # 右：标题 / 说明 / 快捷键 / 按钮
        col = ctk.CTkFrame(row, fg_color="transparent")
        col.pack(side="left", fill="y")
        ctk.CTkLabel(
            col, text="欢迎使用 DiffGuard",
            font=ctk.CTkFont(size=19, weight="bold"),
            text_color=accent_color,
        ).pack(anchor="w", pady=(16, 2))
        ctk.CTkLabel(
            col, text="复制 git diff 到剪贴板即可自动载入",
            font=ctk.CTkFont(size=12), text_color="#4B5563",
        ).pack(anchor="w", pady=(0, 6))
        for key, desc in (
            ("Ctrl+V", "载入剪贴板 diff"),
            ("Ctrl+Enter", "开始 AI 审查"),
            ("Ctrl+S", "保存到历史"),
        ):
            hint = ctk.CTkFrame(col, fg_color="transparent")
            hint.pack(anchor="w", pady=1)
            ctk.CTkLabel(
                hint, text=key, font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#3A4A5A",
            ).pack(side="left")
            ctk.CTkLabel(
                hint, text=f"  {desc}", font=ctk.CTkFont(size=11),
                text_color=_FG_MUTED,
            ).pack(side="left")
        ctk.CTkButton(
            col, text="打开设置", command=app.open_settings,
            fg_color=accent_color, hover_color=accent_hover,
            width=118, height=30, corner_radius=8,
        ).pack(anchor="w", pady=(10, 4))
        return guide
