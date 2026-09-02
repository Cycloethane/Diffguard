# -*- coding: utf-8 -*-
"""主窗口模块:DiffGuard 的 CustomTkinter 图形界面(薄壳)。

职责收敛为:窗口组装(工具栏/导航/模块容器/状态栏)、模块路由(注册表
驱动)、系统托盘与前台小窗、设置与快捷键入口。业务逻辑分布在:

    - ui.controllers.WatcherManager  监视线程生命周期与配置热切换
    - ui.controllers.ReviewFlow      审查(diff 载入/渲染/AI 流式/保存导出)
    - ui.controllers.PermissionFlow  权限请求处理
    - ui.controllers.DecisionFlow    决策处理与闭环
    - ui.modules                     各导航模块的内容构建
    - ui.dialogs                     历史/详情/权限弹窗

线程安全:后台回调只做 queue.put,由 QueuePoller(ui/poller.py)在主
线程排空;轮询器幂等启动,杜绝旧实现"重启后轮询双跑"的问题。
"""

import queue
import threading
from typing import Any, Optional

import customtkinter as ctk
from loguru import logger

from bridge import store as bridge_store
from models.config import Config
from ui.animation import fade_in_window, set_enabled as _set_anim_enabled
from ui.background import WindowBackground
from ui.controllers import DecisionFlow, PermissionFlow, ReviewFlow, WatcherManager
from ui.dialogs import HistoryDialog, PermissionHistoryDialog
from ui.modules import MODULES, NAV_ITEMS
from ui.notify import tray_destroy, tray_host, tray_notify
from ui.overlay import MiniOverlay
from ui.poller import QueuePoller
from ui.settings_view import SettingsDialog
from ui.theme import accent, accent_names, accent_primary
from ui.widgets import icon_button, safe_alpha

_FG: str = "#3A4A5A"
_FG_MUTED: str = "#8A96A8"

# 主窗口整体不透明度（<1 让桌面背景透出）
_WINDOW_ALPHA: float = 1.0


class DiffGuardApp(ctk.CTk):
    """DiffGuard 主窗口:GUI 组装与各控制器的宿主。"""

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config: Config = config
        _set_anim_enabled(bool(getattr(config, "animations", True)))
        self.title("DiffGuard")
        self.geometry("1200x800")
        self.minsize(900, 600)
        ctk.set_appearance_mode(config.theme)
        self._set_window_icon()
        try:
            self.attributes("-alpha", 0.0)
            self.after(120, lambda: fade_in_window(self, duration_ms=350, final_alpha=_WINDOW_ALPHA))
        except Exception:
            pass

        # ------------------------------------------------------------------
        # 控制器与队列
        # ------------------------------------------------------------------
        self.review_flow = ReviewFlow(self)
        self.permission_flow = PermissionFlow(self)
        self.decision_flow = DecisionFlow(self)
        self._clipboard_queue: "queue.Queue[str]" = queue.Queue()
        self._clipboard_poller = QueuePoller(
            self, self._clipboard_queue, self.review_flow.apply_diff,
            interval_ms=200, on_batch=self._on_clipboard_batch, label="clipboard",
        )
        self._tray_queue: "queue.Queue[str]" = queue.Queue()
        self._tray_poller = QueuePoller(
            self, self._tray_queue, self._handle_tray_event,
            interval_ms=200, label="tray",
        )
        self.watchers = WatcherManager(
            config,
            on_diff=self._clipboard_queue.put,
            on_permission=self.permission_flow.enqueue,
            on_decision=self.decision_flow.enqueue,
            master=self,
            on_permission_decision=self.permission_flow.on_alert_decision,
            on_decision_chosen=self.decision_flow.on_chosen,
        )

        # 状态
        self._tray_hosted: bool = False
        self._overlay: Optional[MiniOverlay] = None
        self._nav_wide: bool = False
        self._accent: str = getattr(config, "accent", "blue") or "blue"
        self.perm_watcher_online: bool = False
        self._current_module: str = "review"

        # UI 与监听
        self._build_ui()
        self.watchers.start_all()
        self._sync_flow_pollers()
        self._clipboard_poller.start()
        self.permission_flow.start_bridge()  # ZCode 钩子权限事件(与 UIA 监听无关,常启)
        self._bind_shortcuts()
        if config.check_updates:
            self.after(3000, self._check_updates_background)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._init_tray()
        self._tray_poller.start()
        # 状态快照供 Agent 桥接读取(status.json)
        try:
            bridge_store.write_status(
                running=True,
                model=config.model,
                decision_assistant=config.decision_assistant,
                permission_monitor=config.permission_monitor,
                auto_clipboard=config.auto_clipboard,
            )
        except Exception as exc:
            logger.debug("写入状态快照失败: {}", exc)

    # ------------------------------------------------------------------
    # 宿主 API(供控制器/模块/浮窗使用)
    # ------------------------------------------------------------------
    def set_status(self, text: str) -> None:
        """更新底部状态栏文本。"""
        self.status_var.set(text)

    def set_review_buttons(self, state: str) -> None:
        """审查进行中禁用/恢复工具栏的审查与保存按钮。"""
        try:
            self.review_button.configure(state=state)
            self.save_button.configure(state=state)
        except Exception:
            pass

    def select_module(self, key: str) -> None:
        """切换到指定模块(程序化入口,同步导航视觉)。"""
        if key in MODULES and key != self._current_module:
            try:
                self.nav.select(key)
            except Exception:
                pass
        self._on_module_selected(key)

    def open_settings(self) -> None:
        """打开设置弹窗,保存后热应用到监听层与界面。"""

        def _on_config_saved(new_config: Config) -> None:
            self._apply_new_config(new_config)
            self.set_status("配置已更新")

        SettingsDialog(self, on_saved=_on_config_saved, config=self.config)

    def on_wizard_done(self, new_config: Config) -> None:
        """首次配置向导完成后:应用新配置。"""
        self._apply_new_config(new_config)
        self.set_status("配置已应用")

    def restart_decision_watching(self) -> None:
        """首启引导选择非 off 后调用:启动决策监听与轮询。"""
        self.watchers.restart_decision()
        self._sync_flow_pollers()

    @property
    def decision_pending(self) -> bool:
        """是否有待处理的决策(决策页/前台小窗读取)。"""
        return self.decision_flow.pending

    def update_decision_badge(self) -> None:
        """刷新导航"决策"项的待处理角标。"""
        try:
            if getattr(self, "nav", None) is not None:
                self.nav.set_badge("decision", 1 if self.decision_flow.pending else 0)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 配置热应用
    # ------------------------------------------------------------------
    def _apply_new_config(self, new_config: Config) -> None:
        """应用新配置:监听层热切换 + 主题/强调色/动画。"""
        try:
            self.watchers.apply_config(new_config)
            self.configure_theme(new_config.theme)
            if new_config.accent != self._accent:
                self.configure_accent(new_config.accent)
            self._sync_flow_pollers()
            _set_anim_enabled(bool(getattr(new_config, "animations", True)))
        except Exception as exc:
            logger.debug("应用新配置失败: {}", exc)

    def _sync_flow_pollers(self) -> None:
        """按监听线程存活状态启停各流程的队列轮询。"""
        if self.watchers.clipboard_watcher is not None:
            self._clipboard_poller.start()
        if self.watchers.permission_watcher is not None:
            self.permission_flow.start()
        else:
            self.permission_flow.stop()
        if self.watchers.decision_watcher is not None:
            self.decision_flow.start()
        else:
            self.decision_flow.stop()
            self.decision_flow.on_watcher_stopped()

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
            repo_root = Path(__file__).resolve().parent.parent
            exe_dir = Path(sys.executable).resolve().parent
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                for n in names:
                    cands.append(str(Path(meipass) / n))
            for n in names:
                cands.append(str(exe_dir / n))
                cands.append(str(exe_dir / "_internal" / n))
                cands.append(str(cwd / n))
                cands.append(str(repo_root / n))
            for c in cands:
                if Path(c).is_file():
                    return c
        except Exception:
            pass
        return None

    def _set_window_icon(self) -> None:
        """设置主窗口图标（任务栏/标题栏）：优先 PNG 素材图标，回退 app.ico。"""
        png = self._find_icon("assets/icon_512.png", "icon_512.png")
        if png:
            try:
                import tkinter as tk

                self.iconphoto(True, tk.PhotoImage(file=png))
                return
            except Exception:
                pass
        ico = self._find_icon("app.ico", "tray.ico")
        if ico:
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

    def _build_ui(self) -> None:
        """构建主窗口：顶部工具栏 + 左侧导航 + 模块内容区 + 状态栏。"""
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 背景图（最底层）
        try:
            self._bg = WindowBackground(self)
            self._bg.attach()
            self.bind("<Configure>", lambda e: self._bg.resize() if getattr(self, "_bg", None) is not None else None)
        except Exception as exc:
            logger.debug("背景初始化失败: {}", exc)
            self._bg = None

        self._build_toolbar()
        self._build_body()
        self._build_status_bar()

    def _build_body(self) -> None:
        """主体：左侧窄导航 + 模块内容容器。"""
        body: ctk.CTkFrame = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=10, pady=(2, 4))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        from ui.nav_frame import NavFrame

        self.nav = NavFrame(
            body,
            items=[(key, icon, title) for key, icon, title in NAV_ITEMS],
            on_select=self._on_module_selected,
            light=True,
        )
        self.nav.grid(row=0, column=0, sticky="ns", padx=(0, 8))

        self.module_container: ctk.CTkFrame = ctk.CTkFrame(body, fg_color="transparent")
        self.module_container.grid(row=0, column=1, sticky="nsew")
        self.module_container.grid_rowconfigure(0, weight=1)
        self.module_container.grid_columnconfigure(0, weight=1)

        # 初始加载审查模块
        self._current_module = "review"
        MODULES["review"].build(self.module_container, self)

    def _on_module_selected(self, key: str) -> None:
        """导航选中：切换模块内容(注册表驱动)。"""
        module = MODULES.get(key)
        if module is None:
            return
        if self._current_module == "review" and key != "review":
            self.review_flow.detach()  # 审查控件即将销毁
        self._current_module = key
        for w in self.module_container.winfo_children():
            w.destroy()
        module.build(self.module_container, self)
        self._animate_module_in()

    def _animate_module_in(self) -> None:
        """模块内容淡入（仅透明度动画，不动布局，兼容 grid/place）。"""
        child = self.module_container.winfo_children()
        if not child:
            return
        from ui.animation import animate

        widget = child[0]
        try:
            widget.attributes("-alpha", 0.0)
        except Exception:
            pass

        def _step(t: float) -> None:
            try:
                widget.attributes("-alpha", t)
            except Exception:
                pass

        animate(widget, _step, duration_ms=220)
        # 动画结束后复位透明度，避免残留
        widget.after(260, lambda: safe_alpha(widget, 1.0))

    def _build_toolbar(self) -> None:
        """构建顶部工具栏：Logo + 主操作组 + 工具组。"""
        toolbar: ctk.CTkFrame = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 4))
        toolbar.grid_columnconfigure(3, weight=1)

        # Logo 区
        logo: ctk.CTkFrame = ctk.CTkFrame(toolbar, fg_color="transparent")
        logo.grid(row=0, column=0, sticky="w", padx=(0, 8))
        accent_color = accent_primary(self._accent, light=True)
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
            command=self.review_flow.paste_from_clipboard,
            height=34,
        )
        self.paste_button.grid(row=0, column=1, padx=4, pady=4)

        self.review_button: ctk.CTkButton = ctk.CTkButton(
            toolbar,
            text="🚀 开始审查",
            command=self.review_flow.start_review,
            height=34,
            fg_color=accent_color,
        )
        _, _hover = accent(self._accent, light=True)
        self.review_button.configure(hover_color=_hover)
        self.review_button.grid(row=0, column=2, padx=4, pady=4)

        # 布局切换（窄导航 ⇄ 宽导航）
        self.layout_button: ctk.CTkButton = ctk.CTkButton(
            toolbar,
            text="布局",
            width=64,
            height=34,
            fg_color="transparent",
            hover_color="#E0E6EE",
            text_color=_FG,
            command=self._toggle_nav_wide,
        )
        self.layout_button.grid(row=0, column=3, padx=4, pady=4)

        # 工具组（文字式）
        tools: ctk.CTkFrame = ctk.CTkFrame(toolbar, fg_color="transparent")
        tools.grid(row=0, column=4, sticky="e")
        self.save_button = icon_button(tools, "保存", "保存到历史 (Ctrl+S)", self.review_flow.save_history)
        icon_button(tools, "导出", "导出报告 (Ctrl+E)", self.review_flow.export_report)
        icon_button(tools, "设置", "打开设置", self.open_settings)
        icon_button(tools, "历史", "历史记录", self._open_history)
        icon_button(tools, "权限", "权限记录", self._open_permission_history)
        self.overlay_button: ctk.CTkButton = icon_button(
            tools, "前台", "前台模式", self._toggle_overlay
        )

    def _toggle_nav_wide(self) -> None:
        """切换导航宽窄形态。"""
        self._nav_wide = not self._nav_wide
        try:
            self.nav.set_wide(self._nav_wide)
            self.layout_button.configure(text="窄布局" if self._nav_wide else "布局")
        except Exception as exc:
            logger.debug("布局切换失败: {}", exc)

    def _build_status_bar(self) -> None:
        """构建底部状态栏：左状态 + 右监听在线指示。"""
        bar: ctk.CTkFrame = ctk.CTkFrame(self, corner_radius=0)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        self.status_var = ctk.StringVar(value="就绪")
        self.status_label = ctk.CTkLabel(
            bar, textvariable=self.status_var, text_color=_FG_MUTED, anchor="w"
        )
        self.status_label.grid(row=0, column=0, sticky="w", padx=12, pady=6)

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
        if self.watchers.permission_watcher is not None:
            perm_ok = ("● 权限" if self.perm_watcher_online else "○ 权限(UIA可用)")
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
                text_color=ok_color if "● 权限" in text and self.perm_watcher_online else off_color,
            )
        except Exception:
            pass
        self.after(2000, self._refresh_watcher_state)

    # ------------------------------------------------------------------
    # 剪贴板 diff 队列
    # ------------------------------------------------------------------
    def _on_clipboard_batch(self, _items: list) -> None:
        """剪贴板批量应用完成后的状态提示。"""
        self.set_status("已自动从剪贴板加载 diff")

    # ------------------------------------------------------------------
    # 历史与权限弹窗
    # ------------------------------------------------------------------
    def _open_history(self) -> None:
        """打开历史记录弹窗。"""
        HistoryDialog(self, on_review_open=self.review_flow.restore_review)

    def _open_permission_history(self) -> None:
        """打开权限审批记录弹窗。"""
        PermissionHistoryDialog(self)

    # ------------------------------------------------------------------
    # 快捷键
    # ------------------------------------------------------------------
    def _bind_shortcuts(self) -> None:
        """绑定全局快捷键：Ctrl+V 载入、Ctrl+Enter 审查、Ctrl+S 保存、Ctrl+E 导出、? 快捷键面板。"""
        try:
            self.bind_all("<Control-v>", lambda e: self.review_flow.paste_from_clipboard())
            self.bind_all("<Control-r>", lambda e: self.review_flow.start_review())
            self.bind_all("<Control-Enter>", lambda e: self.review_flow.start_review())
            self.bind_all("<Control-s>", lambda e: self.review_flow.save_history())
            self.bind_all("<Control-e>", lambda e: self.review_flow.export_report())
            self.bind_all("?", lambda e: self._show_shortcuts_help())
        except Exception as exc:
            logger.debug("绑定快捷键失败: {}", exc)

    def _show_shortcuts_help(self) -> None:
        """显示快捷键速查弹窗。"""
        from ui.theme import frost as _frost, text_color as _tc

        dlg = ctk.CTkToplevel(self)
        dlg.title("DiffGuard - 快捷键")
        dlg.geometry("460x320")
        dlg.attributes("-topmost", True)
        try:
            dlg.attributes("-alpha", 1.0)
        except Exception:
            pass
        dlg.grid_columnconfigure(0, weight=1)
        box = ctk.CTkFrame(dlg, fg_color=_frost(True), corner_radius=10)
        box.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        box.grid_columnconfigure(0, weight=1)
        rows = [
            ("Ctrl+V", "从剪贴板载入 diff"),
            ("Ctrl+Enter / Ctrl+R", "开始 AI 审查"),
            ("Ctrl+S", "保存到历史"),
            ("Ctrl+E", "导出报告"),
            ("?", "显示本快捷键面板"),
        ]
        ctk.CTkLabel(box, text="快捷键", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=_tc(True)).grid(row=0, column=0, sticky="w", padx=14, pady=(14, 6))
        for i, (key, desc) in enumerate(rows, start=1):
            ctk.CTkLabel(box, text=key, font=ctk.CTkFont(size=13, weight="bold"),
                         text_color="#183048", width=110, anchor="w").grid(
                row=i, column=0, sticky="w", padx=14, pady=2)
            ctk.CTkLabel(box, text=desc, font=ctk.CTkFont(size=13),
                         text_color=_tc(True), anchor="w").grid(
                row=i, column=1, sticky="w", padx=8, pady=2)
        ctk.CTkButton(box, text="关闭", width=90, height=32, command=dlg.destroy,
                      fg_color="#607890", hover_color="#7890A8").grid(
            row=len(rows) + 1, column=0, columnspan=2, pady=(14, 12))

    # ------------------------------------------------------------------
    # 主题与强调色
    # ------------------------------------------------------------------
    def configure_theme(self, theme: str) -> None:
        """按配置切换界面主题并刷新审查区标签颜色。"""
        try:
            ctk.set_appearance_mode(theme)
            self.review_flow.refresh_theme()
        except Exception as exc:
            logger.error("切换主题失败: {}", exc)

    def configure_accent(self, accent_name: str) -> None:
        """切换强调色并刷新关键控件。"""
        if accent_name not in accent_names():
            return
        self._accent = accent_name
        primary: str = accent_primary(accent_name, light=True)
        hover: str = accent(accent_name, light=True)[1]
        try:
            self.review_button.configure(fg_color=primary, hover_color=hover)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 检查更新
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
                        lambda: self.set_status(
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
            self.set_status("前台模式切换失败")

    def overlay_payload(self) -> dict[str, Any]:
        """返回供前台小窗展示的状态数据（主线程轮询读取）。"""
        score, contributions = self.review_flow.risk_snapshot()
        return {
            "status": self.status_var.get(),
            "file_count": self.review_flow.file_count,
            "score": score,
            "contributions": contributions,
            "decision_pending": self.decision_flow.pending,
            "permission": self.permission_flow.overlay_permission(),
        }

    def open_decision_alert(self, _master: Any) -> None:
        """前台小窗徽标点击回调：展示当前待决策的浮窗。"""
        self.decision_flow.open_alert()

    # ------------------------------------------------------------------
    # 系统托盘常驻
    # ------------------------------------------------------------------
    def _init_tray(self) -> None:
        """启动常驻托盘图标并注册恢复/退出回调。"""
        try:
            self._tray_hosted = tray_host(
                on_show=lambda: self._tray_queue.put("show"),
                on_quit=lambda: self._tray_queue.put("quit"),
            )
        except Exception as exc:
            logger.debug("初始化托盘失败: {}", exc)
            self._tray_hosted = False

    def _handle_tray_event(self, ev: str) -> None:
        """处理一条托盘事件。"""
        if ev == "show":
            self._restore_from_tray()
        elif ev == "quit":
            self._quit_app()

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
        try:
            bridge_store.write_status(running=False)
        except Exception as exc:
            logger.debug("写入退出状态快照失败: {}", exc)
        self._clipboard_poller.stop()
        self._tray_poller.stop()
        self.permission_flow.stop()
        self.permission_flow.stop_bridge()
        self.decision_flow.stop()
        self.watchers.shutdown()
        if self._overlay is not None:
            try:
                self._overlay.destroy()
            except Exception as exc:
                logger.debug("销毁前台小窗失败: {}", exc)
        if self._tray_hosted:
            tray_destroy()
        self.destroy()
