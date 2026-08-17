# -*- coding: utf-8 -*-
"""主窗口模块：DiffGuard 的 CustomTkinter 图形界面。

包含左右分栏布局、文件列表、Diff 展示（含 Pygments 高亮与 +/- 着色）、
AI 报告流式展示、历史记录弹窗以及剪贴板自动监听等交互逻辑。
线程安全：剪贴板监听线程与截图流线程均通过 queue.Queue + after 轮询
切换到 GUI 主线程执行。
"""

import queue
import threading
import time as _time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import customtkinter as ctk
from loguru import logger
from pygments import token
from pygments.lexers import TextLexer, get_lexer_by_name, guess_lexer_for_filename

from bridge import store as bridge_store
from core.clipboard_watcher import ClipboardWatcher
from core.decision_explainer import explain_decision
from core.decision_watcher import DecisionWatcher
from core.diff_parser import (
    build_file_diff,
    build_title,
    compute_risk_level,
    file_risk_level,
    parse_diff,
    parse_diff_with_status,
    render_file_summary,
)
from core.permission_risk import risk_level as permission_risk_level
from core.permission_watcher import PermissionWatcher
from core.reviewer import analyze_diff
from core.risk_score import compute_risk_score, score_color, score_to_level
from models.config import Config, is_configured
from models.decision_prompt import DecisionPrompt, DecisionMode
from models.decision_history import save_decision as save_decision_record
from models.history import (
    DECISION_APPROVED,
    DECISION_REJECTED,
    get_by_id,
    get_recent,
    save_review,
    update_decision,
)
from models.permission_history import (
    get_recent_permissions,
    save_permission,
    update_permission_decision,
)
from ui.notify import tray_destroy, tray_host, tray_notify
from ui.decision_alert import DecisionAlert
from ui.overlay import MiniOverlay
from ui.permission_alert import PermissionAlert
from ui.risk_gauge import RiskGauge
from ui.settings_view import SettingsDialog
from ui.theme import accent, accent_names, accent_primary

# 颜色（深色主题）常量
_FG: str = "#e6e6e6"
_FG_MUTED: str = "#9ca3af"
_BG: str = "#1e1e1e"

# 风险等级对应的刻度符号
_RISK_MARK: dict[str, str] = {"high": "🔴 高", "medium": "🟡 中", "low": "🟢 低"}

# 文件风险对应的按钮颜色（dark 主题）
_RISK_BUTTON_COLORS_DARK: dict[str, tuple[str, str]] = {
    "high": ("#7f1d1d", "#991b1b"),
    "medium": ("#854d0e", "#a16207"),
    "low": ("#14532d", "#166534"),
}
_RISK_BUTTON_COLORS_LIGHT: dict[str, tuple[str, str]] = {
    "high": ("#fca5a5", "#f87171"),
    "medium": ("#fcd34d", "#fbbf24"),
    "low": ("#86efac", "#4ade80"),
}

# token 类型 -> 颜色（dark / light）
_TOKEN_COLORS_DARK: dict[str, str] = {
    "tok.keyword": "#ff7b72",
    "tok.string": "#a5d6ff",
    "tok.comment": "#8b949e",
    "tok.number": "#79c0ff",
    "tok.func": "#d2a8ff",
    "tok.name": "#d2a8ff",
    "tok.operator": "#ff7b72",
    "tok.punct": "#c9d1d9",
    "tok.generic": "#7ee787",
    "tok.default": _FG,
}
_TOKEN_COLORS_LIGHT: dict[str, str] = {
    "tok.keyword": "#d73a49",
    "tok.string": "#032f62",
    "tok.comment": "#6a737d",
    "tok.number": "#005cc5",
    "tok.func": "#6f42c1",
    "tok.name": "#6f42c1",
    "tok.operator": "#d73a49",
    "tok.punct": "#24292e",
    "tok.generic": "#22863a",
    "tok.default": "#24292e",
}


class DiffGuardApp(ctk.CTk):
    """DiffGuard 主窗口。

    负责整体的 GUI 组装与交互：
        - 加载 / 粘贴 / 自动监听剪贴板 diff
        - 解析并展示文件列表与 Diff 内容
        - 调用 AI 后台线程流式生成报告并通过队列更新界面
        - 保存与查看审查历史，管理应用设置
    """

    def __init__(self, config: Config) -> None:
        """构造主窗口。

        参数:
            config: 应用配置（包含 API Key、模型、主题等）。
        """
        super().__init__()
        self.config: Config = config
        self.title("DiffGuard")
        self.geometry("1200x800")
        self.minsize(900, 600)
        ctk.set_appearance_mode(config.theme)
        self._set_window_icon()

        # 状态字段
        self._current_diff: str = ""
        self._current_files: list[dict[str, Any]] = []
        self._current_report: str = ""
        self._current_report_id: Optional[int] = None
        self._analyzing: bool = False
        self._stream_queue: queue.Queue[tuple[str, Optional[str]]] = queue.Queue()
        self._clipboard_queue: queue.Queue[str] = queue.Queue()
        self._permission_queue: queue.Queue[Any] = queue.Queue()
        self._decision_queue: queue.Queue[Any] = queue.Queue()
        self._decision_stream: queue.Queue[str] = queue.Queue()
        self._decision_pending: bool = False
        self._tray_queue: queue.Queue[str] = queue.Queue()
        self._tray_hosted: bool = False
        self._watcher: Optional[ClipboardWatcher] = None
        self._permission_watcher: Optional[PermissionWatcher] = None
        self._permission_alert: Optional[PermissionAlert] = None
        self._decision_watcher: Optional[DecisionWatcher] = None
        self._decision_alert: Optional[DecisionAlert] = None
        self._file_buttons: list[ctk.CTkButton] = []
        self._overlay: Optional[MiniOverlay] = None
        self._watcher_online: bool = False
        self._perm_watcher_online: bool = False
        self._accent: str = getattr(config, "accent", "blue") or "blue"

        self._build_ui()
        self._define_text_tags()
        self._start_clipboard_watching()
        self._start_permission_watching()
        self._start_decision_watching()
        self._bind_shortcuts()
        if config.check_updates:
            self.after(3000, self._check_updates_background)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._init_tray()
        self.after(200, self._poll_tray_queue)
        self.after(300, self._poll_decision_queue)
        self.after(400, self._poll_decision_stream)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    @staticmethod
    def _find_icon(*names: str) -> Optional[str]:
        """在源码运行 / PyInstaller 打包 / 当前目录下定位图标文件。"""
        from pathlib import Path

        try:
            import sys

            cands: list[str] = []
            cwd = Path.cwd()
            exe_dir = Path(sys.executable).resolve().parent
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                for n in names:
                    cands.append(str(Path(meipass) / n))
            for n in names:
                cands.append(str(exe_dir / n))
                cands.append(str(exe_dir / "_internal" / n))
                cands.append(str(cwd / n))
            for c in cands:
                if Path(c).is_file():
                    return c
        except Exception:
            pass
        return None

    def _set_window_icon(self) -> None:
        """设置主窗口图标（任务栏/标题栏）：优先 app.ico。"""
        ico = self._find_icon("app.ico", "tray.ico")
        if ico:
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

    def _build_ui(self) -> None:
        """构建主窗口的全部控件。"""
        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_toolbar()
        self._build_dashboard()
        self._build_main_area()
        self._build_status_bar()
        self._show_empty_guide()

    def _build_toolbar(self) -> None:
        """构建顶部工具栏：Logo + 主操作组 + 工具组。"""
        toolbar: ctk.CTkFrame = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 4))
        toolbar.grid_columnconfigure(3, weight=1)

        # Logo 区
        logo: ctk.CTkFrame = ctk.CTkFrame(toolbar, fg_color="transparent")
        logo.grid(row=0, column=0, sticky="w", padx=(0, 8))
        accent_color = accent_primary(self._accent, light=False)
        ctk.CTkLabel(
            logo,
            text="◆ DiffGuard",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=accent_color,
        ).pack(side="left", padx=(0, 10))

        # 主操作组
        self.paste_button: ctk.CTkButton = ctk.CTkButton(
            toolbar,
            text="📋 从剪贴板粘贴",
            command=self._on_paste_clicked,
            height=34,
        )
        self.paste_button.grid(row=0, column=1, padx=4, pady=4)

        self.review_button: ctk.CTkButton = ctk.CTkButton(
            toolbar,
            text="🚀 开始审查",
            command=self._start_review,
            height=34,
            fg_color=accent_color,
        )
        _, _hover = accent(self._accent)
        self.review_button.configure(hover_color=_hover)
        self.review_button.grid(row=0, column=2, padx=4, pady=4)

        # 工具组（图标式）
        tools: ctk.CTkFrame = ctk.CTkFrame(toolbar, fg_color="transparent")
        tools.grid(row=0, column=4, sticky="e")
        self.save_button = _icon_button(tools, "💾", "保存到历史 (Ctrl+S)", self._save_history)
        _icon_button(tools, "📤", "导出报告 (Ctrl+E)", self._export_report)
        _icon_button(tools, "⚙", "设置", self._open_settings)
        _icon_button(tools, "🕘", "历史记录", self._open_history)
        _icon_button(tools, "🔐", "权限记录", self._open_permission_history)
        self.overlay_button: ctk.CTkButton = _icon_button(
            tools, "📌", "前台模式", self._toggle_overlay
        )

    def _build_dashboard(self) -> None:
        """构建顶部风险仪表盘卡：总分 + 等级色带 + 文件数 + 主要风险点。"""
        dash: ctk.CTkFrame = ctk.CTkFrame(self, corner_radius=8, fg_color="#262626")
        dash.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 4))
        dash.grid_columnconfigure(2, weight=1)
        for col in range(3):
            dash.grid_columnconfigure(col, weight=0)
        dash.grid_columnconfigure(3, weight=1)

        # 分数
        ctk.CTkLabel(
            dash, text="综合风险", font=ctk.CTkFont(size=12), text_color=_FG_MUTED
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(8, 0))
        self.dash_score: ctk.CTkLabel = ctk.CTkLabel(
            dash,
            text="--",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color=_FG_MUTED,
        )
        self.dash_score.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 6))

        # 等级
        ctk.CTkLabel(
            dash, text="风险等级", font=ctk.CTkFont(size=12), text_color=_FG_MUTED
        ).grid(row=0, column=1, sticky="w", padx=12, pady=(8, 0))
        self.dash_level: ctk.CTkLabel = ctk.CTkLabel(
            dash, text="--", font=ctk.CTkFont(size=18, weight="bold")
        )
        self.dash_level.grid(row=1, column=1, sticky="w", padx=12, pady=(0, 6))

        # 文件数
        ctk.CTkLabel(
            dash, text="变更文件", font=ctk.CTkFont(size=12), text_color=_FG_MUTED
        ).grid(row=0, column=2, sticky="w", padx=12, pady=(8, 0))
        self.dash_count: ctk.CTkLabel = ctk.CTkLabel(
            dash, text="0", font=ctk.CTkFont(size=18, weight="bold")
        )
        self.dash_count.grid(row=1, column=2, sticky="w", padx=12, pady=(0, 6))

        # 主要风险点
        ctk.CTkLabel(
            dash, text="主要风险点", font=ctk.CTkFont(size=12), text_color=_FG_MUTED
        ).grid(row=0, column=3, sticky="nw", padx=12, pady=(8, 0))
        self.dash_points: ctk.CTkLabel = ctk.CTkLabel(
            dash, text="尚未加载 diff", font=ctk.CTkFont(size=13), anchor="w", justify="left"
        )
        self.dash_points.grid(row=1, column=3, sticky="new", padx=12, pady=(0, 6))

    def _show_empty_guide(self) -> None:
        """空状态引导层：未载入 diff 时显示在主体区域中央。"""
        self._guide = ctk.CTkFrame(self, fg_color="transparent")
        self._guide.grid(row=2, column=0, sticky="nsew", padx=12, pady=4)
        self._guide.grid_rowconfigure(0, weight=1)
        self._guide.grid_columnconfigure(0, weight=1)

        box: ctk.CTkFrame = ctk.CTkFrame(self._guide, corner_radius=12, fg_color="#202020")
        box.grid(row=0, column=0)
        accent_color: str = accent_primary(self._accent)
        ctk.CTkLabel(
            box,
            text="🛡 欢迎使用 DiffGuard",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=accent_color,
        ).grid(row=0, column=0, padx=48, pady=(28, 6))
        ctk.CTkLabel(
            box,
            text="复制一段 git diff 到剪贴板即可自动载入开始审查",
            font=ctk.CTkFont(size=14),
            text_color=_FG_MUTED,
        ).grid(row=1, column=0, padx=48, pady=4)
        ctk.CTkLabel(
            box,
            text="Ctrl+V 从剪贴板载入   ·   Ctrl+Enter 开始审查   ·   Ctrl+S 保存历史",
            font=ctk.CTkFont(size=12),
            text_color=_FG_MUTED,
        ).grid(row=2, column=0, padx=48, pady=4)
        ctk.CTkButton(
            box,
            text="打开设置",
            command=self._open_settings,
            fg_color=accent_color,
            hover_color=accent(self._accent)[1],
            width=140,
        ).grid(row=3, column=0, padx=48, pady=(18, 28))

    def _build_main_area(self) -> None:
        """构建左右分栏主体区域（左侧 40% / 右侧 60%）。"""
        main: ctk.CTkFrame = ctk.CTkFrame(self)
        main.grid(row=3, column=0, sticky="nsew", padx=12, pady=4)
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=2, minsize=380)
        main.grid_columnconfigure(1, weight=3, minsize=480)

        # ---------------- 左侧 ----------------
        left: ctk.CTkFrame = ctk.CTkFrame(main, corner_radius=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.grid_rowconfigure(1, weight=1)
        left.grid_rowconfigure(3, weight=3)
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="变更文件", font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 2)
        )
        self.file_list_frame: ctk.CTkScrollableFrame = ctk.CTkScrollableFrame(left)
        self.file_list_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=2)

        ctk.CTkLabel(left, text="Diff 详情", font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=2, column=0, sticky="w", padx=10, pady=(6, 2)
        )
        diff_body: ctk.CTkFrame = ctk.CTkFrame(left)
        diff_body.grid(row=3, column=0, sticky="nsew", padx=6, pady=(0, 6))
        diff_body.grid_rowconfigure(0, weight=1)
        diff_body.grid_columnconfigure(0, weight=1)

        self.diff_textbox: ctk.CTkTextbox = ctk.CTkTextbox(
            diff_body, font=ctk.CTkFont(family="Consolas", size=12), wrap="none"
        )
        self.diff_textbox.grid(row=0, column=0, sticky="nsew")
        diff_scroll_y: ctk.CTkScrollbar = ctk.CTkScrollbar(
            diff_body, command=self.diff_textbox.yview
        )
        diff_scroll_y.grid(row=0, column=1, sticky="ns")
        self.diff_textbox.configure(yscrollcommand=diff_scroll_y.set)

        # ---------------- 右侧 ----------------
        right: ctk.CTkFrame = ctk.CTkFrame(main, corner_radius=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            right, text="AI 审查报告", font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 2))

        # 风险进度条（0-100 纯色）
        risk_panel: ctk.CTkFrame = ctk.CTkFrame(right, fg_color="transparent")
        risk_panel.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 2))
        risk_panel.grid_columnconfigure(0, weight=1)
        self.risk_gauge: RiskGauge = RiskGauge(risk_panel)
        self.risk_gauge.grid(row=0, column=0, sticky="ew")

        report_body: ctk.CTkFrame = ctk.CTkFrame(right)
        report_body.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        report_body.grid_rowconfigure(0, weight=1)
        report_body.grid_columnconfigure(0, weight=1)

        self.report_textbox: ctk.CTkTextbox = ctk.CTkTextbox(
            report_body, font=ctk.CTkFont(family="微软雅黑", size=13), state="disabled"
        )
        self.report_textbox.grid(row=0, column=0, sticky="nsew")
        report_scroll_y: ctk.CTkScrollbar = ctk.CTkScrollbar(
            report_body, command=self.report_textbox.yview
        )
        report_scroll_y.grid(row=0, column=1, sticky="ns")
        self.report_textbox.configure(yscrollcommand=report_scroll_y.set)

    def _build_status_bar(self) -> None:
        """构建底部状态栏：左状态 + 右监听在线指示。"""
        bar: ctk.CTkFrame = ctk.CTkFrame(self, corner_radius=0)
        bar.grid(row=4, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        self.status_var = ctk.StringVar(value="就绪")
        ctk.CTkLabel(
            bar, textvariable=self.status_var, text_color=_FG_MUTED, anchor="w"
        ).grid(row=0, column=0, sticky="w", padx=12, pady=6)

        self._watcher_state = ctk.CTkLabel(
            bar, text="", text_color=_FG_MUTED, anchor="e"
        )
        self._watcher_state.grid(row=0, column=1, sticky="e", padx=12, pady=6)
        self._refresh_watcher_state()

    def _refresh_watcher_state(self) -> None:
        """刷新状态栏右侧的监听在线指示（剪贴板 / 权限监控）。"""
        ok_color: str = "#22c55e"
        off_color: str = "#6b7280"
        clip: str = ("● 剪贴板" if self.config.auto_clipboard else "○ 剪贴板")
        perm_on: bool = bool(self.config.permission_monitor)
        perm_ok: str | None = None
        if self._permission_watcher is not None:
            perm_ok = ("● 权限" if self._perm_watcher_online else "○ 权限(UIA可用)")
            if not perm_on:
                perm_ok = "○ 权限"
        elif perm_on:
            perm_ok = "○ 权限(初始中)"
        text: str = clip
        if perm_ok:
            text += "  " + perm_ok
        try:
            self._watcher_state.configure(
                text=text,
                text_color=ok_color if "● 权限" in text and self._perm_watcher_online else off_color,
            )
        except Exception:
            pass
        self.after(2000, self._refresh_watcher_state)

    # ------------------------------------------------------------------
    # 文本标签定义
    # ------------------------------------------------------------------
    def _define_text_tags(self) -> None:
        """为 diff 与报告文本框定义颜色/字体标签。"""
        dark: bool = ctk.get_appearance_mode() == "Dark"
        token_colors: dict[str, str] = _TOKEN_COLORS_DARK if dark else _TOKEN_COLORS_LIGHT

        # diff +/- 前缀与行背景
        for tag, opts in {
            "pfx_add": {"foreground": "#3fb950"},
            "pfx_del": {"foreground": "#f85149"},
            "bg_add": {"background": "#0f2b1a" if dark else "#e6ffec"},
            "bg_del": {"background": "#331414" if dark else "#ffebe9"},
            "hunk": {"foreground": "#8b949e"},
        }.items():
            self.diff_textbox.tag_config(tag, **opts)

        for tag, color in token_colors.items():
            self.diff_textbox.tag_config(tag, foreground=color)

        # 报告文本框中的错误信息
        self.report_textbox.tag_config("report_error", foreground="#f85149")

    # ------------------------------------------------------------------
    # 剪贴板监听（线程安全：queue + after）
    # ------------------------------------------------------------------
    def _start_clipboard_watching(self) -> None:
        """按配置启动剪贴板监听线程，并轮询其队列。

        权限监控开启时，同时启用剪贴板的权限文本辅助通道。
        """
        if self.config.auto_clipboard:
            perm_cb = (
                self._on_watcher_permission if self.config.permission_monitor else None
            )
            self._watcher = ClipboardWatcher(
                on_diff_detected=self._on_watcher_detected,
                on_permission_detected=perm_cb,
            )
            self._watcher.start()
            self._watcher_online = True
            self.after(200, self._poll_clipboard_queue)

    def _on_watcher_detected(self, diff_text: str) -> None:
        """后台线程回调：仅将 diff 放入队列，由主线程处理。"""
        self._clipboard_queue.put(diff_text)

    def _on_watcher_permission(self, prompt: Any) -> None:
        """后台线程回调：权限文本放入队列，由主线程处理。"""
        self._permission_queue.put(prompt)

    def _poll_clipboard_queue(self) -> None:
        """主线程周期性处理剪贴板队列。"""
        applied: bool = False
        while True:
            try:
                diff_text: str = self._clipboard_queue.get_nowait()
            except queue.Empty:
                break
            logger.info("自动检测到剪贴板中的 git diff")
            self._apply_diff(diff_text)
            applied = True
        if applied:
            self.status_var.set("已自动从剪贴板加载 diff")
        self.after(200, self._poll_clipboard_queue)

    def stop_clipboard_watching(self) -> None:
        """停止剪贴板监听线程，用于退出时清理。"""
        if self._watcher is not None:
            self._watcher.stop()

    # ------------------------------------------------------------------
    # 权限审批监控（主通道 UIA + 辅助通道剪贴板）
    # ------------------------------------------------------------------
    def _start_permission_watching(self) -> None:
        """按配置启动权限监听线程与浮窗，并轮询其队列。"""
        if not self.config.permission_monitor:
            return
        if self.config.floating_mode_enabled:
            self._permission_alert = PermissionAlert(
                self, on_decision=self._on_permission_decision
            )
        self._permission_watcher = PermissionWatcher(
            on_prompt_detected=self._on_watcher_permission
        )
        self._permission_watcher.start()
        self._perm_watcher_online = self._permission_watcher.available
        self.after(400, self._poll_permission_queue)

    def _poll_permission_queue(self) -> None:
        """主线程周期性处理权限队列。"""
        if self._permission_watcher is not None:
            self._perm_watcher_online = bool(self._permission_watcher.available)
        while True:
            try:
                prompt: Any = self._permission_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_permission_prompt(prompt)
        self.after(200, self._poll_permission_queue)

    def _handle_permission_prompt(self, prompt: Any) -> None:
        """处理一个权限请求：自动放行判定、保存记录、通知、浮窗。"""
        record_id: Optional[int] = save_permission(prompt)
        prompt.db_id = record_id
        logger.info("已记录权限请求 → 入库 id={}", record_id)

        # 功能A：低风险自动放行
        if self.config.auto_allow_low_risk and prompt.risk_score < self.config.auto_allow_threshold:
            logger.info(
                "低风险自动放行: risk={} < threshold={}",
                prompt.risk_score,
                self.config.auto_allow_threshold,
            )
            if prompt.window_handle is not None and self._permission_watcher is not None:
                if self.config.keyboard_inject:
                    self._permission_watcher.apply_decision_keyboard(prompt, "once_allowed")
                else:
                    self._permission_watcher.apply_decision(prompt, "once_allowed")
            if prompt.db_id is not None:
                update_permission_decision(prompt.db_id, "once_allowed")
            self.status_var.set(
                f"已自动放行低风险权限请求: {prompt.target}（风险 {prompt.risk_score}）"
            )
            return

        level: str = permission_risk_level(prompt)
        self.status_var.set(
            f"权限请求: {prompt.source} {prompt.action.value} {prompt.target}"
            f"（风险 {prompt.risk_score}/100）"
        )
        try:
            self.bell()
        except Exception:
            pass

        # 功能B：高风险系统托盘通知
        if self.config.tray_notify and prompt.risk_score >= 60:
            threading.Thread(
                target=tray_notify,
                args=(
                    "DiffGuard 高风险权限请求",
                    f"{prompt.source} 请求 {prompt.action.value} {prompt.target}\n"
                    f"风险 {prompt.risk_score}/100，请确认!",
                    2,
                ),
                daemon=True,
            ).start()

        if self._permission_alert is not None:
            self._permission_alert.show_prompt(prompt)
        # 高频下防止面板被覆盖丢失提示
        self.lift()

    def _on_permission_decision(self, prompt: Any, decision: str) -> None:
        """浮窗决策回调：写回 UIA 原始窗口并持久化记录。"""
        # 回写：若来自 UIA 通道，尽力点击原窗口对应按钮（或键盘注入）
        if prompt.window_handle is not None and self._permission_watcher is not None:
            if self.config.keyboard_inject:
                self._permission_watcher.apply_decision_keyboard(prompt, decision)
            else:
                self._permission_watcher.apply_decision(prompt, decision)
        if getattr(prompt, "db_id", None) is not None:
            update_permission_decision(prompt.db_id, decision)
        self.status_var.set(
            f"已{'允许' if decision != 'rejected' else '拒绝'}权限请求: {prompt.target}"
        )
        if self._permission_alert is not None:
            existing: Optional[PermissionAlert] = PermissionAlert.get_instance(self)
            if existing is not None and self._prompt_is_current(existing, prompt):
                self._permission_alert.hide()

    def _prompt_is_current(self, alert: Any, prompt: Any) -> bool:
        """判断浮窗当前展示的提示与所决策提示是否一致。"""
        return getattr(alert, "_prompt", None) is prompt

    def _open_permission_history(self) -> None:
        """打开权限审批记录弹窗。"""
        PermissionHistoryDialog(self)

    # ------------------------------------------------------------------
    # 决策助手（感知 → 浮窗 → AI 解析）
    # ------------------------------------------------------------------
    def _start_decision_watching(self) -> None:
        """按配置启动决策监听（off 时不启动）。"""
        mode: str = getattr(self.config, "decision_assistant", DecisionMode.OFF.value)
        if mode == DecisionMode.OFF.value:
            logger.info("决策助手未启用（off）")
            return
        try:
            self._decision_alert = DecisionAlert(
                self, on_decide=self._on_decision_chosen
            )
        except Exception as exc:
            logger.debug("初始化决策浮窗失败: {}", exc)
            self._decision_alert = None
        self._decision_watcher = DecisionWatcher(
            on_decision_detected=self._on_watcher_decision
        )
        self._decision_watcher.start()
        logger.info("决策助手已启动，模式: {}", mode)

    def _stop_decision_watching(self) -> None:
        """停止决策监听并隐藏浮窗。"""
        if self._decision_watcher is not None:
            try:
                self._decision_watcher.stop()
            except Exception as exc:
                logger.debug("停止决策监听失败: {}", exc)
            self._decision_watcher = None
        if self._decision_alert is not None:
            try:
                self._decision_alert.hide()
            except Exception as exc:
                logger.debug("隐藏决策浮窗失败: {}", exc)
        self._decision_pending = False

    def _on_watcher_decision(self, prompt: Any) -> None:
        """后台线程回调：决策放入队列，由主线程处理。"""
        self._decision_queue.put(prompt)

    def _poll_decision_queue(self) -> None:
        """主线程处理决策请求队列。"""
        while True:
            try:
                prompt: Any = self._decision_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_decision_prompt(prompt)
        self.after(300, self._poll_decision_queue)

    def _handle_decision_prompt(self, prompt: Any) -> None:
        """处理一个决策请求：ask 询问 / on 自动解析。"""
        mode: str = getattr(self.config, "decision_assistant", DecisionMode.OFF.value)
        auto: bool = bool(getattr(self.config, "decision_auto", True))
        self._decision_pending = True
        self.status_var.set(f"检测到 Agent 决策：{prompt.question[:40]}")

        alert: Optional[DecisionAlert] = DecisionAlert.get_instance(self)
        if alert is None:
            logger.warning("决策浮窗未就绪，忽略决策请求")
            return

        if mode == DecisionMode.ASK.value:
            alert.show_prompt(prompt, auto_explain=False)
            self._ask_parse_confirmation(prompt)
        elif mode == DecisionMode.ON.value:
            alert.show_prompt(prompt, auto_explain=True)
            if auto:
                self._start_decision_explain(prompt)
            else:
                self._ask_parse_confirmation(prompt)
        # off 分支不会进入（watcher 未启动）

    def _ask_parse_confirmation(self, prompt: Any) -> None:
        """ask 模式：弹出确认框询问是否解析。"""
        import tkinter.messagebox as mb

        resp: bool = mb.askyesno(
            "DiffGuard 决策助手",
            f"检测到 Agent 需要你决策：\n\n{prompt.question}\n\n"
            f"共 {len(prompt.options)} 个选项。是否让 AI 帮你解析并给出建议？",
            parent=self,
        )
        if resp:
            self._start_decision_explain(prompt)

    def _start_decision_explain(self, prompt: Any) -> None:
        """在后台线程流式调用 AI 解析。"""
        alert: Optional[DecisionAlert] = DecisionAlert.get_instance(self)
        if alert is not None:
            alert.set_explaining(True)
        config = self.config

        def _run() -> None:
            try:
                for line in explain_decision(prompt, config):
                    self._decision_stream.put(line)
            except Exception as exc:
                logger.exception("决策解析线程异常: {}", exc)
                self._decision_stream.put("#ERROR# 解析线程异常，请查看日志。")

        threading.Thread(target=_run, daemon=True).start()

    def _poll_decision_stream(self) -> None:
        """主线程轮询决策解析输出并增量填充浮窗。"""
        changed: bool = False
        while True:
            try:
                line: str = self._decision_stream.get_nowait()
            except queue.Empty:
                break
            alert: Optional[DecisionAlert] = DecisionAlert.get_instance(self)
            if alert is not None:
                alert.apply_line(line)
                changed = True
        if changed:
            # 刷新一次状态栏
            self.status_var.set("决策解析完成")
        self.after(400, self._poll_decision_stream)

    def _on_decision_chosen(self, prompt: Any, key: str) -> None:
        """用户点击某个选项后：高亮已在浮窗内完成，这里记录并提示。"""
        try:
            setattr(prompt, "user_decision", key)
        except Exception:
            pass
        self.status_var.set(f"已记录你的选择：{key}")
        # 决策反馈闭环：写入桥接文件 + 决策历史库，供 Agent 后续参考
        try:
            chosen_text = ""
            for opt in getattr(prompt, "options", []) or []:
                if getattr(opt, "key", "") == key:
                    chosen_text = getattr(opt, "text", "")
                    break
            bridge_store.record_decision_feedback(
                question=getattr(prompt, "question", ""),
                chosen=key,
                chosen_text=chosen_text,
                recommendation=getattr(prompt, "recommendation", ""),
                source=getattr(prompt, "source", "Unknown"),
            )
            options_list = [
                {
                    "key": getattr(o, "key", ""),
                    "text": getattr(o, "text", ""),
                    "meaning": getattr(o, "meaning", ""),
                }
                for o in getattr(prompt, "options", []) or []
            ]
            save_decision_record(
                source=getattr(prompt, "source", "Unknown"),
                question=getattr(prompt, "question", ""),
                options=options_list,
                recommendation=getattr(prompt, "recommendation", ""),
                conclusion=getattr(prompt, "conclusion", ""),
                user_decision=key,
                raw_text=getattr(prompt, "raw_text", ""),
            )
        except Exception as exc:
            logger.debug("记录决策反馈失败: {}", exc)

    def open_decision_alert(self, _master: Any) -> None:
        """前台小窗徽标点击回调：展示当前待决策的浮窗。"""
        alert: Optional[DecisionAlert] = DecisionAlert.get_instance(self)
        if alert is None or not self._decision_pending:
            return
        try:
            alert.deiconify()
            alert.lift()
            alert.attributes("-topmost", True)
        except Exception as exc:
            logger.debug("打开决策浮窗失败: {}", exc)

    def restart_decision_watching(self) -> None:
        """首启引导选择非 off 后调用：启动决策监听。"""
        mode: str = getattr(self.config, "decision_assistant", DecisionMode.OFF.value)
        if mode == DecisionMode.OFF.value:
            return
        if self._decision_watcher is None:
            self._start_decision_watching()
            self.after(300, self._poll_decision_queue)
            self.after(400, self._poll_decision_stream)

    def overlay_payload_decision(self) -> bool:
        """返回是否有待处理的决策（供前台小窗展示徽标）。"""
        return bool(self._decision_pending)

    # ------------------------------------------------------------------
    # diff 加载与展示
    # ------------------------------------------------------------------
    def _on_paste_clicked(self) -> None:
        """从剪贴板读取内容并尝试加载。"""
        try:
            import pyperclip

            text: str = pyperclip.paste()
        except Exception as exc:
            logger.error("读取剪贴板失败: {}", exc)
            self.status_var.set("读取剪贴板失败")
            return
        if text and "diff --git" in text:
            self._apply_diff(text)
            self.status_var.set("已从剪贴板加载 diff")
        else:
            self.status_var.set("剪贴板中没有检测到 git diff")

    def _apply_diff(self, diff_text: str) -> None:
        """解析并展示一段 diff：重置文件列表、Diff 区与报告区。"""
        self._current_diff = diff_text.strip()
        files, status = parse_diff_with_status(self._current_diff)
        self._current_files = files
        self._current_report = ""
        self._current_report_id = None
        if getattr(self, "_guide", None) is not None:
            try:
                self._guide.grid_remove()
            except Exception:
                pass

        self._populate_file_list(files)
        self._render_raw_diff(self._current_diff)
        self._clear_report()
        self._update_risk_gauge()
        if not files:
            self.status_var.set("未识别到文件变更（请确认是否为 git diff）")
        else:
            base: str = f"已加载 diff：{len(files)} 个文件"
            if status.get("lenient"):
                base += "（内容不完整/被截断，仅粗略解析）"
            elif status.get("strict") is False:
                base += "（部分内容无法严格解析）"
            self.status_var.set(base)

    def _update_risk_gauge(self) -> None:
        """根据当前文件列表刷新风险进度条与顶部仪表盘卡。"""
        score, contributions = compute_risk_score(self._current_files)
        self.risk_gauge.set_score(score, contributions)
        try:
            # 仪表盘
            self.dash_score.configure(text=str(score), text_color=score_color(score))
            self.dash_level.configure(
                text=_RISK_MARK.get(score_to_level(score), score_to_level(score)),
                text_color=score_color(score),
            )
            self.dash_count.configure(text=str(len(self._current_files)))
            top: list[str] = contributions[:3] if contributions else ["无突出风险点"]
            self.dash_points.configure(text="\n".join(top))
        except Exception:
            pass

    def _populate_file_list(self, files: list[dict[str, Any]]) -> None:
        """根据文件风险等级渲染文件列表（红/黄/绿 + 高危标记）。"""
        for widget in self.file_list_frame.winfo_children():
            widget.destroy()
        self._file_buttons = []

        if not files:
            ctk.CTkLabel(self.file_list_frame, text="（无文件变更）", text_color=_FG_MUTED).pack(
                fill="x", padx=8, pady=6
            )
            return

        colors: dict[str, tuple[str, str]] = (
            _RISK_BUTTON_COLORS_DARK
            if ctk.get_appearance_mode() == "Dark"
            else _RISK_BUTTON_COLORS_LIGHT
        )
        for info in files:
            level: str = file_risk_level(info)
            base, hover = colors.get(level, ("#333333", "#444444"))
            flags: list[str] = info.get("risk_flags", []) or []
            mark: str = ""
            tooltip_parts: list[str] = []
            if level == "high":
                mark = "⚠ "
                tooltip_parts.append("高风险")
            elif flags:
                tooltip_parts.append("含风险标记")

            text: str = f"{mark}{render_file_summary(info)}"
            btn: ctk.CTkButton = ctk.CTkButton(
                self.file_list_frame,
                text=text,
                anchor="w",
                height=36,
                fg_color=base,
                hover_color=hover,
                text_color=_FG,
                font=ctk.CTkFont(size=12),
                command=lambda info=info: self._on_file_selected(info),
            )
            btn.pack(fill="x", padx=4, pady=3)
            self._file_buttons.append(btn)

            if tooltip_parts:
                reason: str = "；".join(flags) if flags else "文件级风险"
                tip: str = f"{info.get('file_path','')}\n" + reason
                _bind_tooltip(btn, tip)

    def _on_file_selected(self, file_info: dict[str, Any]) -> None:
        """点击文件列表项：在 Diff 区展示该文件的高亮内容。"""
        diff_text: str = build_file_diff(file_info)
        self._render_raw_diff(diff_text)
        self.status_var.set(
            "正在查看: {} (+{} -{})".format(
                file_info["file_path"], file_info["additions"], file_info["deletions"]
            )
        )

    def _guess_lexer(self, file_path: str) -> Any:
        """根据文件名猜测 Pygments 词法分析器，失败时回退到纯文本。"""
        try:
            return guess_lexer_for_filename(file_path, "")
        except Exception:
            try:
                return get_lexer_by_name("diff")
            except Exception:
                return TextLexer()

    def _render_raw_diff(self, diff_text: str) -> None:
        """渲染 diff 文本：以 Pygments 分词着色，并标记 + / - 前缀。"""
        self.diff_textbox.delete("1.0", "end")
        if not diff_text:
            return
        lexer: Any = self._guess_lexer("_.diff")
        try:
            tokens = list(lexer.get_tokens(diff_text + "\n"))
        except Exception as exc:
            logger.warning("Pygments 高亮失败: {}", exc)
            tokens = [(token.Text, diff_text + "\n")]

        tb = self.diff_textbox
        line_index: int = 0
        col: int = 0
        lines: list[list[tuple[str, Optional[str], int]]] = [[]]

        for ttype, value in tokens:
            tag: Optional[str] = self._classify_token(ttype)
            parts: list[str] = value.split("\n")
            for i, piece in enumerate(parts):
                if i > 0:
                    line_index += 1
                    lines.append([])
                    col = 0
                if piece:
                    lines[line_index].append((piece, tag, col))
                    col += len(piece)

        for i, segs in enumerate(lines):
            self._insert_highlighted_line(i + 1, segs)

    def _classify_token(self, ttype: Any) -> Optional[str]:
        """将 Pygments token 映射到预定义标签。"""
        if ttype in token.Keyword:
            return "tok.keyword"
        if ttype in token.String:
            return "tok.string"
        if ttype in token.Comment:
            return "tok.comment"
        if ttype in token.Number:
            return "tok.number"
        if ttype in token.Name.Function:
            return "tok.func"
        if ttype in token.Name:
            return "tok.name"
        if ttype in token.Operator:
            return "tok.operator"
        if ttype in token.Punctuation:
            return "tok.punct"
        if ttype in token.Generic:
            return "tok.generic"
        return None

    def _insert_highlighted_line(
        self, line_no: int, segs: list[tuple[str, Optional[str], int]]
    ) -> None:
        """插入单行到 diff 文本框，并应用 token 颜色与 +/- 行标记。"""
        tb = self.diff_textbox
        line_text: str = "".join(chunk for chunk, _, _ in segs)
        line_type: str = line_text[0] if line_text else ""

        if line_type in ("+", "-"):
            bg_tag: str = "bg_add" if line_type == "+" else "bg_del"
            tb.tag_add(bg_tag, f"{line_no}.0", f"{line_no}.end")

        for chunk, tag, start_col in segs:
            tb.insert("end", chunk)
            end_col = start_col + len(chunk)
            if tag and chunk[0] != line_type:
                tb.tag_add(tag, f"{line_no}.{start_col}", f"{line_no}.{end_col}")

        if line_type in ("+", "-"):
            tb.tag_add(
                "pfx_add" if line_type == "+" else "pfx_del",
                f"{line_no}.0",
                f"{line_no}.1",
            )
        elif line_text.startswith("@@"):
            tb.tag_add("hunk", f"{line_no}.0", f"{line_no}.end")

        tb.insert("end", "\n")

    # ------------------------------------------------------------------
    # AI 审查（流式）
    # ------------------------------------------------------------------
    def _start_review(self) -> None:
        """开始 AI 审查：后台线程调用模型，主线程轮询队列流式展示。"""
        if self._analyzing:
            return
        if not self._current_diff.strip() and not self.diff_textbox.get("1.0", "end").strip():
            self.status_var.set("请先粘贴 diff")
            return
        if not is_configured(self.config):
            self.status_var.set("尚未配置 API Key，请先设置")
            self._open_settings()
            return

        # 未解析过文件时先解析一次
        if not self._current_files:
            self._current_files = parse_diff(self._current_diff or self.diff_textbox.get("1.0", "end"))
            self._populate_file_list(self._current_files)

        self._analyzing = True
        self.review_button.configure(state="disabled")
        self.save_button.configure(state="disabled")
        self.status_var.set("分析中…")
        self._clear_report()
        self._stream_queue = queue.Queue()

        worker: threading.Thread = threading.Thread(
            target=self._review_worker, daemon=True
        )
        worker.start()
        self.after(50, self._poll_stream)

    def _review_worker(self) -> None:
        """后台线程：消费 analyze_diff 生成器，将片段送入流式队列。"""
        try:
            for chunk in analyze_diff(self._current_diff, self.config):
                self._stream_queue.put(("chunk", chunk))
        except Exception as exc:  # 兜底：不让线程崩溃
            logger.exception("审查线程发生异常: {}", exc)
            self._stream_queue.put(("error", str(exc)))
        finally:
            self._stream_queue.put(("done", None))

    def _poll_stream(self) -> None:
        """主线程周期性刷新流式报告的界面展示。"""
        updates: bool = False
        while True:
            try:
                kind, payload = self._stream_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "chunk":
                self._insert_report(payload or "")
                updates = True
            elif kind == "error":
                self._insert_report(f"\n\n[错误] {payload}\n")
            elif kind == "done":
                self._on_review_done()
                return
        if updates:
            self.report_textbox.see("end")
        self.after(50, self._poll_stream)

    def _on_review_done(self) -> None:
        """审查完成：恢复按钮并缓存报告。"""
        self._analyzing = False
        self.review_button.configure(state="normal")
        self.save_button.configure(state="normal")
        self._current_report = self.report_textbox.get("1.0", "end").strip()
        self._current_report_id = None
        if self._current_report:
            self.status_var.set("审查完成，可保存到历史")
        else:
            self.status_var.set("审查完成，但未获得有效内容")

    # ------------------------------------------------------------------
    # 报告展示辅助
    # ------------------------------------------------------------------
    def _clear_report(self) -> None:
        """清空报告文本框。"""
        self.report_textbox.configure(state="normal")
        self.report_textbox.delete("1.0", "end")
        self.report_textbox.configure(state="disabled")

    def _insert_report(self, chunk: str) -> None:
        """向只读的报告文本框追加文本。"""
        self.report_textbox.configure(state="normal")
        self.report_textbox.insert("end", chunk)
        self.report_textbox.configure(state="disabled")

    # ------------------------------------------------------------------
    # 历史记录
    # ------------------------------------------------------------------
    def _save_history(self) -> None:
        """保存当前审查结果到历史数据库。"""
        if self._analyzing:
            self.status_var.set("审查尚未完成")
            return
        if not self._current_report:
            self.status_var.set("还没有可保存的审查报告")
            return
        record_id: Optional[int] = save_review(
            title=build_title(self._current_files),
            file_count=len(self._current_files),
            risk_level=compute_risk_level(self._current_files),
            ai_report=self._current_report,
            raw_diff=self._current_diff,
        )
        if record_id is not None:
            self._current_report_id = record_id
            self.status_var.set(f"已保存到历史 (id={record_id})")
        else:
            self.status_var.set("保存失败，请查看日志")

    def _open_history(self) -> None:
        """打开历史记录弹窗。"""
        HistoryDialog(self, on_review_open=self._restore_review)

    # ------------------------------------------------------------------
    # 快捷键
    # ------------------------------------------------------------------
    def _bind_shortcuts(self) -> None:
        """绑定全局快捷键：Ctrl+V 载入、Ctrl+Enter 审查、Ctrl+S 保存、Ctrl+E 导出。"""
        try:
            self.bind_all("<Control-v>", lambda e: self._on_paste_clicked())
            self.bind_all("<Control-r>", lambda e: self._start_review())
            self.bind_all("<Control-Enter>", lambda e: self._start_review())
            self.bind_all("<Control-s>", lambda e: self._save_history())
            self.bind_all("<Control-e>", lambda e: self._export_report())
        except Exception as exc:
            logger.debug("绑定快捷键失败: {}", exc)

    # ------------------------------------------------------------------
    # 导出报告
    # ------------------------------------------------------------------
    def _export_report(self) -> None:
        """将当前 AI 审查报告导出为 Markdown / HTML。"""
        if not self._current_report:
            self.status_var.set("当前没有可导出的报告")
            return
        from tkinter import filedialog

        path: str = filedialog.asksaveasfilename(
            parent=self,
            title="导出审查报告",
            defaultextension=".md",
            filetypes=(
                ("Markdown", "*.md"),
                ("HTML", "*.html"),
                ("文本", "*.txt"),
            ),
            initialfile=f"diffguard-report-{datetime.now():%Y%m%d-%H%M}.md",
        )
        if not path:
            return
        try:
            body: str = str(self._current_report)
            ext: str = Path(path).suffix.lower()
            content: str
            if ext == ".html":
                content = (
                    "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
                    "<title>DiffGuard 审查报告</title></head><body>"
                    "<pre>" + _html_escape(body) + "</pre></body></html>"
                )
            else:
                content = (
                    f"# DiffGuard 审查报告\n\n"
                    f"- 时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                    f"- 文件数: {len(self._current_files)}\n\n---\n\n{body}\n"
                )
            Path(path).write_text(content, encoding="utf-8")
            self.status_var.set(f"报告已导出: {path}")
        except Exception as exc:
            logger.error("导出报告失败: {}", exc)
            self.status_var.set("导出报告失败，请查看日志")

    def _restore_review(self, record: Any) -> None:
        """从历史记录恢复某次审查到主界面。"""
        try:
            self._current_diff = record.raw_diff
            self._current_files = parse_diff(record.raw_diff)
            self._current_report = record.ai_report
            if getattr(self, "_guide", None) is not None:
                try:
                    self._guide.grid_remove()
                except Exception:
                    pass
            self._populate_file_list(self._current_files)
            self._render_raw_diff(record.raw_diff)
            self._clear_report()
            self._insert_report(record.ai_report)
            self._update_risk_gauge()
            self.status_var.set(f"已恢复历史 id={record.id}")
        except Exception as exc:
            logger.error("恢复历史记录失败: {}", exc)
            self.status_var.set("恢复历史记录失败")

    # ------------------------------------------------------------------
    # 设置
    # ------------------------------------------------------------------
    def _open_settings(self) -> None:
        """打开设置弹窗。"""

        def _on_config_saved(new_config: Config) -> None:
            old_perm: bool = self.config.permission_monitor
            old_decision: str = getattr(
                self.config, "decision_assistant", DecisionMode.OFF.value
            )
            self.config = new_config
            self.configure_theme(new_config.theme)
            if new_config.accent != self._accent:
                self.configure_accent(new_config.accent)
            if new_config.auto_clipboard and self._watcher is None:
                self._start_clipboard_watching()
            elif not new_config.auto_clipboard and self._watcher is not None:
                self.stop_clipboard_watching()
                self._watcher = None
                self._watcher_online = False
            if new_config.permission_monitor and not old_perm:
                # 权限监控从关闭变为开启：重建监听
                if self._permission_watcher is not None:
                    self._permission_watcher.stop()
                    self._permission_watcher = None
                self._start_permission_watching()
            elif not new_config.permission_monitor and old_perm:
                if self._permission_watcher is not None:
                    self._permission_watcher.stop()
                    self._permission_watcher = None
                if self._permission_alert is not None:
                    try:
                        self._permission_alert.hide()
                    except Exception as exc:
                        logger.debug("隐藏权限浮窗失败: {}", exc)
            # 决策助手模式热切换
            new_decision: str = getattr(
                new_config, "decision_assistant", DecisionMode.OFF.value
            )
            if new_decision != old_decision:
                if new_decision == DecisionMode.OFF.value:
                    self._stop_decision_watching()
                else:
                    if self._decision_watcher is not None:
                        self._stop_decision_watching()
                    self._start_decision_watching()
            self.status_var.set("配置已更新")

        SettingsDialog(self, on_saved=_on_config_saved, config=self.config)

    def configure_theme(self, theme: str) -> None:
        """按配置切换界面主题并刷新标签颜色。"""
        try:
            ctk.set_appearance_mode(theme)
            self._define_text_tags()
            self._populate_file_list(self._current_files)
        except Exception as exc:
            logger.error("切换主题失败: {}", exc)

    def configure_accent(self, accent_name: str) -> None:
        """切换强调色并刷新关键控件。"""
        if accent_name not in accent_names():
            return
        self._accent = accent_name
        primary: str = accent_primary(accent_name)
        hover: str = accent(accent_name)[1]
        try:
            self.review_button.configure(fg_color=primary, hover_color=hover)
            if getattr(self, "_guide", None) is not None:
                for child in self._guide.winfo_children():
                    if isinstance(child, ctk.CTkFrame):
                        for sub in child.winfo_children():
                            if isinstance(sub, ctk.CTkButton):
                                sub.configure(fg_color=primary, hover_color=hover)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 检查更新（G）：异步检查 GitHub 发布页
    # ------------------------------------------------------------------
    def _check_updates_background(self) -> None:
        """后台线程检查最新版本，发现新版则提示（失败静默）。"""
        repo: str = "anomalyco/DiffGuard"
        current: str = "0.0.3"

        def _check() -> None:
            try:
                import json
                import urllib.request

                url: str = f"https://api.github.com/repos/{repo}/releases/latest"
                req = urllib.request.Request(url, headers={"User-Agent": "DiffGuard"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                latest: str = str(data.get("tag_name", "")).lstrip("v")
                if latest and latest > current:
                    self.after(
                        0,
                        lambda: self.status_var.set(
                            f"发现新版本 v{latest}（当前 v{current}），可前往发布页获取"
                        ),
                    )
            except Exception as exc:
                logger.debug("检查更新失败（忽略）: {}", exc)

        threading.Thread(target=_check, daemon=True).start()

    # ------------------------------------------------------------------
    # 前台模式
    # ------------------------------------------------------------------
    def _toggle_overlay(self) -> None:
        """切换前台小窗：开启时主界面收进托盘，仅保留小窗。"""
        if self._overlay is None or not self._overlay.winfo_exists():
            self._overlay = MiniOverlay(self)
            self.overlay_button.configure(text="关闭前台")
            self._hide_to_tray()
            return
        try:
            if self._overlay.winfo_viewable():
                self._overlay.withdraw()
                self.overlay_button.configure(text="前台模式")
                self._restore_from_tray()
            else:
                self._overlay.deiconify()
                self._overlay.lift()
                self.overlay_button.configure(text="关闭前台")
                self._hide_to_tray()
        except Exception as exc:
            logger.error("切换前台模式失败: {}", exc)
            self.status_var.set("前台模式切换失败")

    def overlay_payload(self) -> dict[str, Any]:
        """返回供前台小窗展示的状态数据（主线程轮询读取）。"""
        score, contributions = compute_risk_score(self._current_files)
        return {
            "status": self.status_var.get(),
            "file_count": len(self._current_files),
            "score": score,
            "contributions": contributions,
            "decision_pending": self.overlay_payload_decision(),
        }

    # ------------------------------------------------------------------
    # 系统托盘常驻
    # ------------------------------------------------------------------
    def _init_tray(self) -> None:
        """启动常驻托盘图标并注册恢复/退出回调。"""
        try:
            self._tray_hosted = tray_host(
                on_show=self._tray_show, on_quit=self._tray_quit
            )
        except Exception as exc:
            logger.debug("初始化托盘失败: {}", exc)
            self._tray_hosted = False

    def _tray_show(self) -> None:
        """托盘左键/双击回调（托盘线程）→ 主线程恢复窗口。"""
        self._tray_queue.put("show")

    def _tray_quit(self) -> None:
        """托盘菜单"退出"回调（托盘线程）→ 主线程真正退出。"""
        self._tray_queue.put("quit")

    def _poll_tray_queue(self) -> None:
        """主线程轮询托盘事件并执行。"""
        try:
            while True:
                ev: str = self._tray_queue.get_nowait()
                if ev == "show":
                    self._restore_from_tray()
                elif ev == "quit":
                    self._quit_app()
        except queue.Empty:
            pass
        self.after(200, self._poll_tray_queue)

    def _hide_to_tray(self) -> None:
        """隐藏主界面到系统托盘。"""
        try:
            self.withdraw()
            logger.debug("主界面已收进托盘")
        except Exception as exc:
            logger.debug("隐藏主界面失败: {}", exc)

    def _restore_from_tray(self) -> None:
        """从托盘恢复主界面（若前台小窗开着则一并收起）。"""
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception as exc:
            logger.debug("恢复主界面失败: {}", exc)
        if self._overlay is not None and self._overlay.winfo_exists():
            try:
                self._overlay.withdraw()
                self.overlay_button.configure(text="前台模式")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 退出
    # ------------------------------------------------------------------
    def _on_close(self) -> None:
        """点关闭按钮：收进系统托盘而不是退出。"""
        logger.info("关闭按钮触发，收进系统托盘")
        self._hide_to_tray()
        tray_notify("DiffGuard", "已收进系统托盘，双击图标或右键菜单可恢复", 1)

    def _quit_app(self) -> None:
        """真正退出：停止监听线程、销毁浮窗与托盘图标。"""
        logger.info("退出 DiffGuard")
        self.stop_clipboard_watching()
        if self._permission_watcher is not None:
            try:
                self._permission_watcher.stop()
            except Exception as exc:
                logger.debug("停止权限监听失败: {}", exc)
        if self._permission_alert is not None:
            try:
                self._permission_alert.destroy()
            except Exception as exc:
                logger.debug("销毁权限浮窗失败: {}", exc)
        if self._decision_watcher is not None:
            try:
                self._decision_watcher.stop()
            except Exception as exc:
                logger.debug("停止决策监听失败: {}", exc)
        if self._decision_alert is not None:
            try:
                self._decision_alert.destroy()
            except Exception as exc:
                logger.debug("销毁决策浮窗失败: {}", exc)
        if self._overlay is not None:
            try:
                self._overlay.destroy()
            except Exception as exc:
                logger.debug("销毁前台小窗失败: {}", exc)
        if self._tray_hosted:
            tray_destroy()
        self.destroy()


# ----------------------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------------------
def _make_toolbar_button(
    parent: ctk.CTkFrame,
    text: str,
    command: Callable[[], Any],
    primary: bool = False,
) -> ctk.CTkButton:
    """创建文本工具栏按钮（保留向后兼容）。"""
    if primary:
        btn = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            fg_color="#2f81f7",
            hover_color="#388bfd",
        )
    else:
        btn = ctk.CTkButton(parent, text=text, command=command)
    btn.grid(row=0, column=_make_toolbar_button._counter, padx=4, pady=4)
    _make_toolbar_button._counter += 1
    return btn


_make_toolbar_button._counter = 0


def _icon_button(
    parent: ctk.CTkFrame, icon: str, tooltip: str, command: Callable[[], Any]
) -> ctk.CTkButton:
    """创建图标式工具栏按钮并绑定悬浮提示。"""
    btn = ctk.CTkButton(
        parent,
        text=icon,
        width=36,
        height=32,
        corner_radius=6,
        command=command,
    )
    btn.pack(side="left", padx=3)
    _bind_tooltip(btn, tooltip)
    return btn


_TOOLTIP_REF: dict[str, Any] = {"win": None}


def _bind_tooltip(widget: Any, text: str) -> None:
    """为控件绑定简单的悬浮提示（单例 Tk tooltip，自动消失防卡死）。"""

    def _under_widget() -> bool:
        try:
            under = widget.winfo_containing(
                widget.winfo_pointerx(), widget.winfo_pointery()
            )
            return under is not None and str(under).startswith(str(widget))
        except Exception:
            return False

    def _show_tip() -> None:
        try:
            # 300ms 延迟期间鼠标可能已移开，移开则不显示
            if not _under_widget():
                return
            tip: Any = _TOOLTIP_REF.get("win")
            if tip is not None:
                try:
                    tip.destroy()
                except Exception:
                    pass
            tip = ctk.CTkToplevel(widget)
            tip.wm_overrideredirect(True)
            tip.attributes("-topmost", True)
            x: int = widget.winfo_rootx() + 12
            y: int = widget.winfo_rooty() + widget.winfo_height() + 4
            tip.wm_geometry(f"+{x}+{y}")
            ctk.CTkLabel(
                tip,
                text=text,
                text_color="#e6e6e6",
                fg_color="#333333",
                corner_radius=4,
            ).pack(padx=6, pady=4)
            _TOOLTIP_REF["win"] = tip
            _schedule_auto_hide()
        except Exception:
            pass

    def _auto_hide() -> None:
        try:
            tip: Any = _TOOLTIP_REF.get("win")
            if tip is None or not tip.winfo_exists():
                return
            if not _under_widget():
                tip.destroy()
                _TOOLTIP_REF["win"] = None
                return
            _schedule_auto_hide()
        except Exception:
            pass

    def _schedule_auto_hide() -> None:
        try:
            widget.after(150, _auto_hide)
        except Exception:
            pass

    def _hide_tip() -> None:
        try:
            tip: Any = _TOOLTIP_REF.get("win")
            if tip is not None:
                tip.destroy()
                _TOOLTIP_REF["win"] = None
        except Exception:
            pass

    widget.bind("<Enter>", lambda e: widget.after(300, _show_tip))
    widget.bind("<Leave>", lambda e: _hide_tip())


def _html_escape(text: str) -> str:
    """HTML 转义（用于导出 HTML 报告）。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


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


# ----------------------------------------------------------------------
# 权限审批记录弹窗
# ----------------------------------------------------------------------
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