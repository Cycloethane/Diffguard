# -*- coding: utf-8 -*-
"""历史 / 权限 / 决策 / 设置模块。

历史与权限为内嵌列表视图;决策为状态页;设置为占位面板 +
打开设置弹窗按钮(消除旧实现"导航点设置弹空页"的不对称)。
"""

from typing import Any

import customtkinter as ctk

from ui.theme import accent_primary, frost, text_color


class HistoryModule:
    """历史模块:内嵌审查历史列表。"""

    key = "history"
    title = "历史"
    icon = "🕘"

    def build(self, container: Any, app: Any) -> None:
        from ui.history_view import HistoryView

        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        view = HistoryView(container, app=app)
        view.grid(row=0, column=0, sticky="nsew")


class PermissionModule:
    """权限模块:内嵌权限记录列表。"""

    key = "permission"
    title = "权限"
    icon = "🔐"

    def build(self, container: Any, app: Any) -> None:
        from ui.permission_history_view import PermissionHistoryView

        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        view = PermissionHistoryView(container, app=app)
        view.grid(row=0, column=0, sticky="nsew")


class DecisionModule:
    """决策模块:待决策状态 + 历史偏好。"""

    key = "decision"
    title = "决策"
    icon = "🤔"

    def build(self, container: Any, app: Any) -> None:
        from ui.decision_view import DecisionView

        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        view = DecisionView(container, app=app)
        view.grid(row=0, column=0, sticky="nsew")


class SettingsModule:
    """设置模块:轻量面板 + 打开设置弹窗。"""

    key = "settings"
    title = "设置"
    icon = "⚙"

    def build(self, container: Any, app: Any) -> None:
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        panel: ctk.CTkFrame = ctk.CTkFrame(container, fg_color=frost(True), corner_radius=12)
        panel.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        panel.grid_rowconfigure(3, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        accent_color: str = accent_primary(getattr(app.config, "accent", "blue"), light=True)
        ctk.CTkLabel(
            panel, text="⚙ 设置", font=ctk.CTkFont(size=18, weight="bold"),
            text_color=text_color(True),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 4))
        ctk.CTkLabel(
            panel,
            text="API 提供方与模型、监听开关、决策助手、Agent 集成等均在设置窗口中配置。",
            font=ctk.CTkFont(size=13), text_color=text_color(True), justify="left",
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 8))
        ctk.CTkButton(
            panel, text="打开设置窗口", width=140, height=34,
            fg_color=accent_color, hover_color="#7890A8",
            command=app.open_settings,
        ).grid(row=2, column=0, sticky="w", padx=16, pady=(0, 12))
