# -*- coding: utf-8 -*-
"""设置弹窗：API Key、模型、监听开关、主题、强调色与权限策略配置。

窗口内容较多，使用可滚动容器承载，所有配置写回 config.json 并通过回调
通知主窗口应用新配置。
"""

from typing import Any, Callable, Optional

import customtkinter as ctk
from loguru import logger

from models.config import (
    Config,
    PROVIDER_OPENCODE_GO,
    PROVIDER_OPENCODE_ZEN,
    PROVIDER_SILICONFLOW,
    load_config,
    provider_default_model,
    provider_models,
    save_config,
)
from models.decision_prompt import DecisionMode
from ui.theme import accent_names


def _apply_window_icon(window: Any) -> None:
    """为弹窗设置标题栏图标：优先 app.ico，退回 tray.ico。"""
    from pathlib import Path

    import sys

    names = ("app.ico", "tray.ico")
    cands: list[str] = []
    try:
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
    except Exception:
        cands.append(str(Path("app.ico")))
    for c in cands:
        if Path(c).is_file():
            try:
                window.iconbitmap(c)
                return
            except Exception:
                continue

# AI 提供方选项
_PROVIDER_OPTIONS: tuple[str, ...] = (
    PROVIDER_SILICONFLOW,
    PROVIDER_OPENCODE_ZEN,
    PROVIDER_OPENCODE_GO,
)
_PROVIDER_LABELS: dict[str, str] = {
    PROVIDER_SILICONFLOW: "SiliconFlow (硅基流动)",
    PROVIDER_OPENCODE_ZEN: "OpenCode Zen",
    PROVIDER_OPENCODE_GO: "OpenCode Go",
}

_THEME_OPTIONS: tuple[str, ...] = ("dark", "light")

_DECISION_MODE_OPTIONS: tuple[str, ...] = (
    "off",
    "ask",
    "on",
)
_DECISION_MODE_LABELS: dict[str, str] = {
    "off": "off (不启用)",
    "ask": "ask (每次询问我)",
    "on": "on (自动解析)",
}
_DECISION_LEVEL_OPTIONS: tuple[str, ...] = (
    "beginner",
    "normal",
    "advanced",
)
_DECISION_LEVEL_LABELS: dict[str, str] = {
    "beginner": "beginner (小白·最通俗)",
    "normal": "normal (普通·通俗加轻术语)",
    "advanced": "advanced (进阶·保留术语)",
}


class SettingsDialog(ctk.CTkToplevel):
    """设置窗口，编辑并保存 DiffGuard 配置。

    初始化属性:
        on_saved: 保存成功后的回调，参数为新 Config 对象。
    """

    def __init__(
        self,
        master: Optional[Any],
        on_saved: Callable[[Config], None],
        config: Optional[Config] = None,
    ) -> None:
        """构造并显示设置窗口。

        参数:
            master: 父窗口。
            on_saved: 保存成功后回调，签名 callable(new_config: Config)。
            config: 初始配置；为 None 时从磁盘加载。
        """
        super().__init__(master)
        self.title("DiffGuard - 设置")
        self.geometry("520x620")
        self.resizable(False, False)
        self._on_saved: Callable[[Config], None] = on_saved
        _apply_window_icon(self)

        self._config: Config = config if config is not None else load_config()
        self._build_ui()
        self._load_values()
        self.attributes("-topmost", True)
        self.attributes("-alpha", 1.0)
        self.after(50, self.lift)
        self.after(120, self.focus_force)

    def _build_ui(self) -> None:
        """构建可滚动的设置界面。"""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        scroll: ctk.CTkScrollableFrame = ctk.CTkScrollableFrame(self)
        scroll.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 6))
        scroll.grid_columnconfigure(0, weight=1)

        self._scroll = scroll
        r: int = 0

        # ---------------- 基本 ----------------
        ctk.CTkLabel(
            scroll, text="基本", font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
        ).grid(row=r, column=0, sticky="ew", pady=(4, 2))
        r += 1

        ctk.CTkLabel(scroll, text="AI 提供方", anchor="w").grid(
            row=r, column=0, sticky="ew", pady=(4, 2)
        )
        r += 1
        self.provider_option: ctk.CTkOptionMenu = ctk.CTkOptionMenu(
            scroll,
            values=[_PROVIDER_LABELS[p] for p in _PROVIDER_OPTIONS],
            command=self._on_provider_changed,
        )
        self.provider_option.grid(row=r, column=0, sticky="ew", pady=(0, 6))
        r += 1

        ctk.CTkLabel(scroll, text="API Key", anchor="w").grid(
            row=r, column=0, sticky="ew", pady=(4, 2)
        )
        r += 1
        self.api_key_entry: ctk.CTkEntry = ctk.CTkEntry(
            scroll, show="*", placeholder_text="sk-... (SiliconFlow / OpenCode Zen / OpenCode Go)"
        )
        self.api_key_entry.grid(row=r, column=0, sticky="ew", pady=(0, 6))
        r += 1

        ctk.CTkLabel(scroll, text="模型", anchor="w").grid(
            row=r, column=0, sticky="ew", pady=(4, 2)
        )
        r += 1
        self.model_option: ctk.CTkOptionMenu = ctk.CTkOptionMenu(
            scroll, values=list(provider_models(PROVIDER_SILICONFLOW))
        )
        self.model_option.grid(row=r, column=0, sticky="ew", pady=(0, 6))
        r += 1

        # ---------------- 外观 ----------------
        ctk.CTkLabel(
            scroll, text="外观", font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
        ).grid(row=r, column=0, sticky="ew", pady=(10, 2))
        r += 1

        self.theme_option: ctk.CTkOptionMenu = ctk.CTkOptionMenu(
            scroll, values=list(_THEME_OPTIONS)
        )
        self.theme_option.grid(row=r, column=0, sticky="ew", pady=(0, 6))
        r += 1

        self.accent_option: ctk.CTkOptionMenu = ctk.CTkOptionMenu(
            scroll, values=list(accent_names())
        )
        self.accent_option.grid(row=r, column=0, sticky="ew", pady=(0, 6))
        r += 1

        # ---------------- 监听与权限 ----------------
        ctk.CTkLabel(
            scroll, text="监听与权限", font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
        ).grid(row=r, column=0, sticky="ew", pady=(10, 2))
        r += 1

        self.auto_clipboard_switch: ctk.CTkSwitch = ctk.CTkSwitch(
            scroll, text="自动监听剪贴板 (检测 git diff)"
        )
        self.auto_clipboard_switch.grid(row=r, column=0, sticky="w", pady=4)
        r += 1

        self.permission_monitor_switch: ctk.CTkSwitch = ctk.CTkSwitch(
            scroll, text="权限审批监控 (识别并提示授权请求)"
        )
        self.permission_monitor_switch.grid(row=r, column=0, sticky="w", pady=4)
        r += 1

        self.floating_mode_switch: ctk.CTkSwitch = ctk.CTkSwitch(
            scroll, text="权限审批浮窗置顶显示"
        )
        self.floating_mode_switch.grid(row=r, column=0, sticky="w", pady=4)
        r += 1

        self.tray_notify_switch: ctk.CTkSwitch = ctk.CTkSwitch(
            scroll, text="高风险权限请求发送系统托盘通知"
        )
        self.tray_notify_switch.grid(row=r, column=0, sticky="w", pady=4)
        r += 1

        # ---------------- 权限策略 ----------------
        ctk.CTkLabel(
            scroll, text="权限策略", font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
        ).grid(row=r, column=0, sticky="ew", pady=(10, 2))
        r += 1

        self.auto_allow_switch: ctk.CTkSwitch = ctk.CTkSwitch(
            scroll, text="低风险权限请求自动放行"
        )
        self.auto_allow_switch.grid(row=r, column=0, sticky="w", pady=4)
        r += 1

        thr_row: int = r
        ctk.CTkLabel(scroll, text="自动放行风险阈值 (风险分 < 值)，默认 20", anchor="w").grid(
            row=r, column=0, sticky="w", pady=(2, 2)
        )
        r += 1
        self.threshold_slider: ctk.CTkSlider = ctk.CTkSlider(
            scroll, from_=5, to=40, number_of_steps=35
        )
        self.threshold_slider.grid(row=r, column=0, sticky="ew", pady=(0, 4))
        r += 1
        self.threshold_value_label: ctk.CTkLabel = ctk.CTkLabel(
            scroll, text="", anchor="w", text_color="#8A96A8"
        )
        self.threshold_value_label.grid(row=r, column=0, sticky="w", pady=(0, 6))
        self.threshold_slider.configure(
            command=lambda v: self.threshold_value_label.configure(text=f"阈值: {int(v)}")
        )
        r += 1

        self.keyboard_inject_switch: ctk.CTkSwitch = ctk.CTkSwitch(
            scroll,
            text="键盘注入回写 (TUI 终端工具，实验性，默认关闭)",
        )
        self.keyboard_inject_switch.grid(row=r, column=0, sticky="w", pady=4)
        r += 1

        # ---------------- 决策助手 ----------------
        ctk.CTkLabel(
            scroll, text="决策助手", font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
        ).grid(row=r, column=0, sticky="ew", pady=(10, 2))
        r += 1

        ctk.CTkLabel(
            scroll,
            text="模式：off=关闭 / ask=检测到后询问 / on=自动解析",
            anchor="w",
            wraplength=470,
            justify="left",
        ).grid(row=r, column=0, sticky="ew", pady=(2, 2))
        r += 1
        self.decision_mode_option: ctk.CTkOptionMenu = ctk.CTkOptionMenu(
            scroll, values=[_DECISION_MODE_LABELS[k] for k in _DECISION_MODE_OPTIONS]
        )
        self.decision_mode_option.grid(row=r, column=0, sticky="ew", pady=(0, 6))
        r += 1

        ctk.CTkLabel(scroll, text="解释措辞水平", anchor="w").grid(
            row=r, column=0, sticky="ew", pady=(4, 2)
        )
        r += 1
        self.decision_level_option: ctk.CTkOptionMenu = ctk.CTkOptionMenu(
            scroll,
            values=[_DECISION_LEVEL_LABELS[k] for k in _DECISION_LEVEL_OPTIONS],
        )
        self.decision_level_option.grid(row=r, column=0, sticky="ew", pady=(0, 6))
        r += 1

        self.decision_auto_switch: ctk.CTkSwitch = ctk.CTkSwitch(
            scroll, text="检测到决策自动调用 AI 解析 (ask 模式下无效)"
        )
        self.decision_auto_switch.grid(row=r, column=0, sticky="w", pady=4)
        r += 1

        self.decision_overlay_switch: ctk.CTkSwitch = ctk.CTkSwitch(
            scroll, text="前台模式显示决策徽标"
        )
        self.decision_overlay_switch.grid(row=r, column=0, sticky="w", pady=4)
        r += 1

        # ---------------- Agent 集成（OpenCode / ZCode 等） ----------------
        ctk.CTkLabel(
            scroll, text="Agent 集成（OpenCode / ZCode 等）", font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
        ).grid(row=r, column=0, sticky="ew", pady=(10, 2))
        r += 1

        self.agent_bridge_switch: ctk.CTkSwitch = ctk.CTkSwitch(
            scroll, text="启用决策反馈闭环 (用户选择回写供 Agent 参考)"
        )
        self.agent_bridge_switch.grid(row=r, column=0, sticky="w", pady=4)
        r += 1

        self.agent_mcp_switch: ctk.CTkSwitch = ctk.CTkSwitch(
            scroll, text="启用 Agent 决策请求通道 (Agent 可提交决策)"
        )
        self.agent_mcp_switch.grid(row=r, column=0, sticky="w", pady=4)
        r += 1

        # ---------------- 其它 ----------------
        ctk.CTkLabel(
            scroll, text="其它", font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
        ).grid(row=r, column=0, sticky="ew", pady=(10, 2))
        r += 1

        self.check_update_switch: ctk.CTkSwitch = ctk.CTkSwitch(
            scroll, text="启动时检查更新"
        )
        self.check_update_switch.grid(row=r, column=0, sticky="w", pady=4)
        r += 1

        self.animations_switch: ctk.CTkSwitch = ctk.CTkSwitch(
            scroll, text="启用界面动画 (数字滚动 / 弹窗过渡 / 闪烁提醒)"
        )
        self.animations_switch.grid(row=r, column=0, sticky="w", pady=4)
        r += 1

        # 保存按钮
        self.save_button: ctk.CTkButton = ctk.CTkButton(
            scroll, text="保存", command=self._on_save_clicked
        )
        self.save_button.grid(row=r, column=0, pady=16, sticky="ew")
        r += 1

    def _current_provider(self) -> str:
        """从下拉框读取当前选择的提供方标识。"""
        label: str = self.provider_option.get()
        return next((k for k, v in _PROVIDER_LABELS.items() if v == label), PROVIDER_SILICONFLOW)

    def _apply_provider_models(self, provider: str, preferred: str = "") -> None:
        """按提供方刷新模型下拉框；preferred 指定优先选中的模型。"""
        models: tuple[str, ...] = provider_models(provider)
        if preferred in models:
            current: str = preferred
        else:
            current = provider_default_model(provider)
        self.model_option.configure(values=list(models))
        self.model_option.set(current)

    def _on_provider_changed(self, _label: str) -> None:
        """用户切换提供方：更新模型下拉框。"""
        provider: str = self._current_provider()
        self._apply_provider_models(provider)

    def _load_values(self) -> None:
        """将当前配置填充到控件中。"""
        self.api_key_entry.delete(0, "end")
        self.api_key_entry.insert(0, self._config.api_key)
        provider: str = getattr(self._config, "provider", PROVIDER_SILICONFLOW)
        if provider not in _PROVIDER_OPTIONS:
            provider = PROVIDER_SILICONFLOW
        self.provider_option.set(_PROVIDER_LABELS[provider])
        # 加载时保留已保存的模型（若属于该提供方列表）
        self._apply_provider_models(provider, preferred=self._config.model)
        self.theme_option.set(
            self._config.theme if self._config.theme in _THEME_OPTIONS else "light"
        )
        self.accent_option.set(
            self._config.accent if self._config.accent in accent_names() else "blue"
        )
        sw = (
            self.auto_clipboard_switch,
            self.permission_monitor_switch,
            self.floating_mode_switch,
            self.tray_notify_switch,
            self.auto_allow_switch,
            self.keyboard_inject_switch,
            self.check_update_switch,
            self.animations_switch,
        )
        vals = (
            self._config.auto_clipboard,
            self._config.permission_monitor,
            self._config.floating_mode_enabled,
            self._config.tray_notify,
            self._config.auto_allow_low_risk,
            self._config.keyboard_inject,
            self._config.check_updates,
            bool(getattr(self._config, "animations", True)),
        )
        for s, v in zip(sw, vals):
            (s.select() if v else s.deselect())
        self.threshold_slider.set(self._config.auto_allow_threshold)
        self.threshold_value_label.configure(
            text=f"阈值: {self._config.auto_allow_threshold}"
        )

        mode: str = self._config.decision_assistant
        self.decision_mode_option.set(
            _DECISION_MODE_LABELS[mode]
            if mode in _DECISION_MODE_LABELS
            else _DECISION_MODE_LABELS["off"]
        )
        level: str = self._config.decision_level
        self.decision_level_option.set(
            _DECISION_LEVEL_LABELS[level]
            if level in _DECISION_LEVEL_LABELS
            else _DECISION_LEVEL_LABELS["normal"]
        )
        (self.decision_auto_switch.select() if self._config.decision_auto else self.decision_auto_switch.deselect())
        (self.decision_overlay_switch.select() if self._config.decision_show_overlay else self.decision_overlay_switch.deselect())
        (self.agent_bridge_switch.select() if getattr(self._config, "agent_bridge", True) else self.agent_bridge_switch.deselect())
        (self.agent_mcp_switch.select() if getattr(self._config, "agent_mcp", True) else self.agent_mcp_switch.deselect())

    def _on_save_clicked(self) -> None:
        """收集界面值、保存配置并关闭窗口。"""
        mode_val: str = self.decision_mode_option.get()
        mode: str = next(
            (k for k, v in _DECISION_MODE_LABELS.items() if v == mode_val), "off"
        )
        level_val: str = self.decision_level_option.get()
        level: str = next(
            (k for k, v in _DECISION_LEVEL_LABELS.items() if v == level_val), "normal"
        )
        cfg = Config(
            api_key=self.api_key_entry.get().strip(),
            model=self.model_option.get(),
            provider=self._current_provider(),
            auto_clipboard=bool(self.auto_clipboard_switch.get()),
            permission_monitor=bool(self.permission_monitor_switch.get()),
            floating_mode_enabled=bool(self.floating_mode_switch.get()),
            theme=self.theme_option.get(),
            accent=self.accent_option.get(),
            tray_notify=bool(self.tray_notify_switch.get()),
            auto_allow_low_risk=bool(self.auto_allow_switch.get()),
            auto_allow_threshold=int(self.threshold_slider.get()),
            keyboard_inject=bool(self.keyboard_inject_switch.get()),
            check_updates=bool(self.check_update_switch.get()),
            decision_assistant=mode,
            decision_level=level,
            decision_auto=bool(self.decision_auto_switch.get()),
            decision_show_overlay=bool(self.decision_overlay_switch.get()),
            agent_bridge=bool(self.agent_bridge_switch.get()),
            agent_mcp=bool(self.agent_mcp_switch.get()),
            animations=bool(self.animations_switch.get()),
        )
        try:
            save_config(cfg)
            logger.info("设置已保存")
            self._on_saved(cfg)
            self.destroy()
        except Exception as exc:
            logger.error("保存设置失败: {}", exc)
            ctk.CTkLabel(
                self._scroll, text=f"保存失败: {exc}", text_color="red", anchor="w"
            ).grid(row=99, column=0, sticky="w", padx=4, pady=(4, 0))


# ----------------------------------------------------------------------
# 首启引导：首次使用决策助手时询问启用方式
# ----------------------------------------------------------------------
class FirstRunDecisionDialog(ctk.CTkToplevel):
    """首次启动引导：让用户选择决策助手启用方式（只弹一次）。

    三选一：
        off 不启用 / ask 每次询问我 / on 自动解析。
    另有"暂不设置，稍后再说"选项，选择后以 off 保存但标记为已引导。
    """

    def __init__(
        self,
        master: Any,
        on_choice: Callable[[str], None],
        config: Optional[Config] = None,
    ) -> None:
        super().__init__(master)
        self._on_choice: Callable[[str], None] = on_choice
        self._config: Config = config if config is not None else load_config()
        self.title("DiffGuard - 决策助手")
        self.geometry("540x430")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 1.0)
        _apply_window_icon(self)
        self.grab_set()

        self._build_ui()
        self.after(50, self.lift)
        self.after(120, self.focus_force)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        title: ctk.CTkLabel = ctk.CTkLabel(
            self,
            text="欢迎使用「决策助手」",
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        )
        title.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 4))

        body: ctk.CTkLabel = ctk.CTkLabel(
            self,
            text=(
                "当你用 AI 编程助手（如 OpenCode、Cursor 等）时，它有时会让你做选择，"
                "比如「打包成哪种格式」。\n\n"
                "决策助手能帮你：\n"
                "   • 用通俗的话解释每个选项是什么意思\n"
                "   • 评估每个选项的风险，并给出推荐\n\n"
                "请选择启用方式："
            ),
            anchor="w",
            justify="left",
            wraplength=490,
            text_color=_FG,
            font=ctk.CTkFont(size=12),
        )
        body.grid(row=1, column=0, sticky="nw", padx=20, pady=(4, 8))

        choices: list[tuple[str, str]] = [
            (
                DecisionMode.OFF.value,
                "不启用 — 关闭此功能，需要时可到设置里打开",
            ),
            (
                DecisionMode.ASK.value,
                "每次询问我 — 检测到决策时先问我要不要解析",
            ),
            (
                DecisionMode.ON.value,
                "启用 — 检测到决策自动解析并给出建议",
            ),
        ]
        self._choice_var: Any = ctk.StringVar(value=DecisionMode.ON.value)
        r: int = 2
        for value, label in choices:
            ctk.CTkRadioButton(
                self,
                text=label,
                value=value,
                variable=self._choice_var,
                anchor="w",
                font=ctk.CTkFont(size=12),
            ).grid(row=r, column=0, sticky="ew", padx=26, pady=3)
            r += 1

        btns: ctk.CTkFrame = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=r + 1, column=0, sticky="ew", padx=20, pady=(12, 16))
        btns.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            btns, text="保存选择", width=120, height=34, command=self._save
        ).grid(row=0, column=1, padx=(0, 8))
        ctk.CTkButton(
            btns,
            text="暂不设置，稍后再说",
            width=160,
            height=34,
            fg_color="#E0E6EE",
            hover_color="#D2DAE4",
            text_color="#3A4A5A",
            command=self._skip,
        ).grid(row=0, column=2, padx=(8, 0))

    def _save(self) -> None:
        """保存选择并调用回调。"""
        mode: str = self._choice_var.get()
        self._config.decision_assistant = mode
        if mode == DecisionMode.OFF.value:
            self._config.decision_auto = False
        try:
            save_config(self._config)
            logger.info("首启引导：决策助手模式设为 {}", mode)
        except Exception as exc:
            logger.error("保存首启引导配置失败: {}", exc)
        self._on_choice(mode)
        self.destroy()

    def _skip(self) -> None:
        """暂不设置：以 off 保存并标记已引导。"""
        self._config.decision_assistant = DecisionMode.OFF.value
        try:
            save_config(self._config)
            logger.info("首启引导：用户暂不设置，默认 off")
        except Exception as exc:
            logger.error("保存首启引导配置失败: {}", exc)
        self._on_choice(DecisionMode.OFF.value)
        self.destroy()

# ----------------------------------------------------------------------
# 首次运行配置向导
# ----------------------------------------------------------------------
class FirstRunWizard(ctk.CTkToplevel):
    """首次运行配置向导：分步引导完成 API 配置。

    步骤：
        1. 欢迎页（介绍 + 提供方选择）
        2. API Key 输入（含模型选择）
        3. 完成
    只在未配置 API Key 且首次运行时弹出（main.py 判定）。
    """

    def __init__(
        self,
        master: Any,
        on_done: Callable[[Config], None],
        config: Optional[Config] = None,
    ) -> None:
        super().__init__(master)
        self._on_done: Callable[[Config], None] = on_done
        self._config: Config = config if config is not None else load_config()
        self._step: int = 1
        self.title("DiffGuard - 首次配置")
        self.geometry("560x460")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 1.0)
        except Exception:
            pass
        _apply_window_icon(self)

        self._content: Optional[ctk.CTkFrame] = None
        self._build_ui()
        self.after(50, self.lift)
        self.after(120, self.focus_force)

    # ------------------------------------------------------------------
    # 步骤容器
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._render_step()

    def _clear_content(self) -> None:
        if self._content is not None:
            self._content.destroy()

    def _render_step(self) -> None:
        self._clear_content()
        self._content = ctk.CTkFrame(self, fg_color="#FFFFFF", corner_radius=10)
        self._content.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(1, weight=1)
        if self._step == 1:
            self._step_welcome()
        elif self._step == 2:
            self._step_key()
        else:
            self._step_done()

    # ------------------------------------------------------------------
    # 步骤 1：欢迎 + 提供方
    # ------------------------------------------------------------------
    def _step_welcome(self) -> None:
        ctk.CTkLabel(
            self._content, text="欢迎使用 DiffGuard",
            font=ctk.CTkFont(size=22, weight="bold"), text_color="#183048",
        ).grid(row=0, column=0, sticky="w", padx=24, pady=(20, 4))
        ctk.CTkLabel(
            self._content,
            text="DiffGuard 帮你审查 git diff 的安全性，并监控 AI 编程助手的权限请求。\n"
                 "开始前需要选择 AI 提供方并配置 API Key（部分功能可跳过配置使用）。",
            font=ctk.CTkFont(size=13), text_color="#607890", justify="left", anchor="w",
        ).grid(row=1, column=0, sticky="nw", padx=24, pady=4)

        sel = ctk.CTkFrame(self._content, fg_color="#F5F3EE", corner_radius=8)
        sel.grid(row=2, column=0, sticky="ew", padx=24, pady=(12, 0))
        sel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(sel, text="选择 AI 提供方", font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="#183048").grid(row=0, column=0, sticky="w", padx=14, pady=(10, 2))
        self._provider_var = ctk.StringVar(value=self._config.provider)
        for i, (p, label) in enumerate(_PROVIDER_LABELS.items(), start=1):
            ctk.CTkRadioButton(
                sel, text=label, variable=self._provider_var, value=p,
                text_color="#183048", font=ctk.CTkFont(size=13),
            ).grid(row=i, column=0, sticky="w", padx=18, pady=3)
        ctk.CTkLabel(
            sel, text="OpenCode Zen / Go 可在 opencode.ai 获取 API Key；SiliconFlow 在 cloud.siliconflow.cn 获取。",
            font=ctk.CTkFont(size=11), text_color="#8A96A8", justify="left", anchor="w",
        ).grid(row=len(_PROVIDER_LABELS) + 1, column=0, sticky="w", padx=14, pady=(2, 10))

        btns = ctk.CTkFrame(self._content, fg_color="transparent")
        btns.grid(row=3, column=0, sticky="ew", padx=24, pady=(14, 16))
        btns.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(btns, text="跳过配置，稍后再说", width=130, height=34,
                      fg_color="#E0E6EE", hover_color="#D2DAE4", text_color="#3A4A5A",
                      command=self._skip).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(btns, text="下一步 →", width=120, height=34,
                      fg_color="#183048", hover_color="#2A4A68",
                      command=self._go_key).grid(row=0, column=1, sticky="e")

    def _go_key(self) -> None:
        self._config.provider = self._provider_var.get()
        self._step = 2
        self._render_step()

    # ------------------------------------------------------------------
    # 步骤 2：API Key
    # ------------------------------------------------------------------
    def _step_key(self) -> None:
        ctk.CTkLabel(
            self._content, text="配置 API Key",
            font=ctk.CTkFont(size=20, weight="bold"), text_color="#183048",
        ).grid(row=0, column=0, sticky="w", padx=24, pady=(20, 2))
        ctk.CTkLabel(
            self._content,
            text=f"提供方：{_PROVIDER_LABELS.get(self._config.provider, self._config.provider)}",
            font=ctk.CTkFont(size=13), text_color="#607890",
        ).grid(row=1, column=0, sticky="w", padx=24, pady=(0, 8))

        form = ctk.CTkFrame(self._content, fg_color="#F5F3EE", corner_radius=8)
        form.grid(row=2, column=0, sticky="ew", padx=24)
        form.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(form, text="API Key", font=ctk.CTkFont(size=13), text_color="#183048",
                     anchor="w").grid(row=0, column=0, sticky="w", padx=14, pady=(10, 2))
        self._key_entry = ctk.CTkEntry(form, show="*", placeholder_text="sk-...")
        self._key_entry.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 8))
        ctk.CTkLabel(form, text="模型", font=ctk.CTkFont(size=13), text_color="#183048",
                     anchor="w").grid(row=2, column=0, sticky="w", padx=14, pady=(4, 2))
        self._model_option = ctk.CTkOptionMenu(
            form, values=list(provider_models(self._config.provider))
        )
        self._model_option.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 12))
        self._model_option.set(
            self._config.model if self._config.model in provider_models(self._config.provider)
            else provider_default_model(self._config.provider)
        )

        btns = ctk.CTkFrame(self._content, fg_color="transparent")
        btns.grid(row=3, column=0, sticky="ew", padx=24, pady=(14, 16))
        btns.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(btns, text="← 上一步", width=100, height=34,
                      fg_color="#E0E6EE", hover_color="#D2DAE4", text_color="#3A4A5A",
                      command=self._go_back).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(btns, text="完成", width=120, height=34,
                      fg_color="#183048", hover_color="#2A4A68",
                      command=self._finish).grid(row=0, column=1, sticky="e")

    def _go_back(self) -> None:
        self._step = 1
        self._render_step()

    # ------------------------------------------------------------------
    # 步骤 3：完成
    # ------------------------------------------------------------------
    def _step_done(self) -> None:
        ctk.CTkLabel(
            self._content, text="✅ 配置完成",
            font=ctk.CTkFont(size=22, weight="bold"), text_color="#183048",
        ).grid(row=0, column=0, sticky="w", padx=24, pady=(24, 8))
        ctk.CTkLabel(
            self._content,
            text="现在可以开始使用 DiffGuard 了。\n"
                 "复制一段 git diff 到剪贴板即可自动载入，点击「开始审查」生成 AI 报告。",
            font=ctk.CTkFont(size=13), text_color="#607890", justify="left", anchor="w",
        ).grid(row=1, column=0, sticky="nw", padx=24, pady=4)
        ctk.CTkButton(self._content, text="开始使用", width=140, height=36,
                      fg_color="#183048", hover_color="#2A4A68",
                      command=self.destroy).grid(row=2, column=0, padx=24, pady=(20, 24))

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------
    def _finish(self) -> None:
        self._config.api_key = self._key_entry.get().strip()
        self._config.model = self._model_option.get()
        try:
            save_config(self._config)
            logger.info("首次配置完成：provider={} model={}", self._config.provider, self._config.model)
        except Exception as exc:
            logger.error("保存首次配置失败: {}", exc)
        self._on_done(self._config)
        self._step = 3
        self._render_step()

    def _skip(self) -> None:
        """跳过配置：不保存 Key，仅关闭向导。"""
        self._on_done(self._config)
        self.destroy()
