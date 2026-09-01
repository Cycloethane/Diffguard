# -*- coding: utf-8 -*-
"""权限审批置顶浮窗模块：以单例 Toplevel 展示权限请求并回写决策。

设计要点：
    - 单例：整个进程只存在一个浮窗，重复请求只更新内容并重新置顶。
    - 置顶：attributes("-topmost") 保证浮窗浮在主窗口与其它应用之上。
    - 决策回写：点击"允许一次/总是允许/拒绝"后调用回调，由调用方
      （app.py）负责持久化记录，并可进一步调用 UIA 回写原始窗口按钮。
"""

from typing import Any, Callable, Optional

import customtkinter as ctk
from loguru import logger

from core.risk_score import score_color
from models.permission_prompt import PermissionPrompt
from ui.animation import fade_in_window, fade_out_window, interpolate_color, pulse
from ui.theme import surface, surface_muted, text_color, text_muted

# 颜色（浅色主题，配合吉祥物配色；高风险警示保持红色）
_FG: str = text_color(light=True)
_FG_MUTED: str = text_muted(light=True)
_BG: str = surface(light=True)
_SURFACE: str = surface_muted(light=True)
# 浮窗整体不透明度（让桌面背景透出）
_POPUP_ALPHA: float = 1.0

_DECISION_LABELS: dict[str, str] = {
    "once_allowed": "允许一次",
    "always_allowed": "总是允许",
    "rejected": "拒绝",
}


class PermissionAlert(ctk.CTkToplevel):
    """权限审批单例浮窗。

    属性:
        _instance: 类级单例引用。
        on_decision: 决策回调，签名 callback(prompt, decision: str)。
    """

    _instance: Optional["PermissionAlert"] = None

    def __init__(
        self,
        master: Any,
        on_decision: Callable[[PermissionPrompt, str], None],
    ) -> None:
        super().__init__(master)
        PermissionAlert._instance = self
        self._on_decision: Callable[[PermissionPrompt, str], None] = on_decision
        self._prompt: Optional[PermissionPrompt] = None
        self.title("DiffGuard - 权限审批")
        self.geometry("560x420")
        self.minsize(480, 360)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.withdraw)

        self._build_ui()
        self.withdraw()  # 初始隐藏，首次识别到请求时才显示

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        card: ctk.CTkFrame = ctk.CTkFrame(self, corner_radius=8)
        card.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        card.grid_rowconfigure(3, weight=1)
        card.grid_columnconfigure(0, weight=1)

        header: ctk.CTkFrame = ctk.CTkFrame(card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header, text="⚠ 权限审批请求", font=ctk.CTkFont(size=16, weight="bold")
        ).grid(row=0, column=0, sticky="w")
        self.score_label: ctk.CTkLabel = ctk.CTkLabel(header, text="风险 --")
        self.score_label.grid(row=0, column=1, sticky="e")

        # 高风险警示条（risk > 70 时显示）：且慢（Wait）
        self.warning_bar: ctk.CTkFrame = ctk.CTkFrame(
            card, fg_color="#7a1f1d", corner_radius=6
        )
        self.warning_bar.grid(row=2, column=0, sticky="ew", padx=12, pady=(4, 0))
        self.warning_bar.grid_columnconfigure(1, weight=1)
        self.warning_icon: ctk.CTkLabel = ctk.CTkLabel(
            self.warning_bar,
            text="⚠",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#ffb4b4",
        )
        self.warning_icon.grid(row=0, column=0, padx=(10, 4), pady=6)
        self.warning_title: ctk.CTkLabel = ctk.CTkLabel(
            self.warning_bar,
            text="且慢（Wait）：",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#ffffff",
        )
        self.warning_title.grid(row=0, column=1, sticky="w", pady=6)
        self.warning_reason: ctk.CTkLabel = ctk.CTkLabel(
            self.warning_bar,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#ffb4b4",
            anchor="w",
            justify="left",
            wraplength=460,
        )
        self.warning_reason.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(0, 6))
        self.warning_bar.grid_remove()  # 默认隐藏

        self.meta_label: ctk.CTkLabel = ctk.CTkLabel(
            card, text="", anchor="w", text_color=_FG_MUTED, justify="left"
        )
        self.meta_label.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 4))

        body: ctk.CTkFrame = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=3, column=0, sticky="nsew", padx=12, pady=4)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        self.target_box: ctk.CTkTextbox = ctk.CTkTextbox(
            body, font=ctk.CTkFont(family="Consolas", size=12), state="disabled"
        )
        self.target_box.grid(row=0, column=0, sticky="nsew")

        detail = ctk.CTkLabel(
            body,
            text="",
            anchor="w",
            justify="left",
            text_color=_FG_MUTED,
            font=ctk.CTkFont(size=12),
            wraplength=500,
        )
        detail.grid(row=1, column=0, sticky="new", pady=(6, 0))
        self.detail_label: ctk.CTkLabel = detail

        btns: ctk.CTkFrame = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        btns.grid_columnconfigure(0, weight=1)
        for idx, (decision, label) in enumerate(_DECISION_LABELS.items(), start=1):
            color: str = {
                "once_allowed": "#2f81f7",
                "always_allowed": "#238636",
                "rejected": "#da3633",
            }[decision]
            btn: ctk.CTkButton = ctk.CTkButton(
                btns,
                text=label,
                fg_color=color,
                hover_color="#1f6feb",
                height=36,
                command=lambda d=decision: self._decide(d),
            )
            btn.grid(row=0, column=idx, sticky="ew", padx=6)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def show_prompt(self, prompt: PermissionPrompt) -> None:
        """更新内容并显示浮窗（高风险时显示"且慢"警示条）。"""
        self._prompt = prompt
        self.meta_label.configure(
            text=(
                f"来源：{prompt.source}    类型：{prompt.prompt_type.value}    "
                f"动作：{prompt.action.value}"
            )
        )
        self.score_label.configure(
            text=f"风险 {prompt.risk_score}",
            text_color=score_color(prompt.risk_score),
        )
        self._fill_target(prompt)
        self._update_warning(prompt)
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.focus_force()
        fade_in_window(self, final_alpha=_POPUP_ALPHA)

    def _update_warning(self, prompt: PermissionPrompt) -> None:
        """risk_score > 70 时显示"且慢（Wait）："警示条并闪动。"""
        high: bool = int(prompt.risk_score or 0) > 70
        if high:
            # 取最高分触发项作为原因
            breakdown: list[str] = prompt.breakdown or []
            reason: str = "；".join(breakdown) if breakdown else "该操作风险较高，请谨慎确认"
            self.warning_reason.configure(text=reason)
            self.warning_bar.grid()
            # 警示条背景闪动两次吸引注意（深红 → 更亮红 → 深红）
            base: str = "#7a1f1d"
            bright: str = "#c0392b"

            def _flash(v: float) -> None:
                # v 为三角波 0→1→0，两次脉冲
                c: str = interpolate_color(base, bright, v)
                self.warning_bar.configure(fg_color=c)

            pulse(self.warning_bar, _flash, duration_ms=700)
        else:
            self.warning_bar.grid_remove()

    def hide(self) -> None:
        """隐藏浮窗（先淡出再收起）。"""
        fade_out_window(self, duration_ms=140, on_done=self.withdraw)

    def _fill_target(self, prompt: PermissionPrompt) -> None:
        self.target_box.configure(state="normal")
        self.target_box.delete("1.0", "end")
        target: str = prompt.target_expanded or prompt.target or "unknown"
        self.target_box.insert("1.0", f"目标: {target}\n\n")
        self.target_box.insert("end", (prompt.raw_text or "")[:2000])
        self.target_box.configure(state="disabled")

        breakdown: list[str] = prompt.breakdown or []
        lines: list[str] = [f"评分明细: {'；'.join(breakdown)}"] if breakdown else []
        if prompt.options:
            lines.append(f"检测到选项: {' / '.join(prompt.options)}")
        if prompt.target_expanded and prompt.target_expanded != prompt.target:
            lines.append(f"展开路径: {prompt.target_expanded}")
        self.detail_label.configure(text="\n".join(lines))

    # ------------------------------------------------------------------
    # 决策
    # ------------------------------------------------------------------
    def _decide(self, decision: str) -> None:
        if self._prompt is None:
            return
        logger.info("用户对权限请求做出决策: {}", decision)
        self._on_decision(self._prompt, decision)

    @classmethod
    def get_instance(cls, master: Any) -> Optional["PermissionAlert"]:
        """返回已存在的单例；不存在或已销毁时返回使用新 master 创建的实例。"""
        inst = cls._instance
        if inst is not None:
            try:
                if inst.winfo_exists():
                    return inst
            except Exception:
                pass
        return None