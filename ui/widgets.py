# -*- coding: utf-8 -*-
"""UI 公共小工具:悬浮提示、文字按钮、安全透明度、HTML 转义。

从 app.py 迁出,消除 nav_frame 等组件对 app.py 私有函数的反向导入。
"""

from typing import Any, Callable

import customtkinter as ctk

_TOOLTIP_REF: dict[str, Any] = {"win": None, "after": None, "owner": None}


def safe_alpha(widget: Any, value: float) -> None:
    """安全设置控件透明度（控件可能已销毁）。"""
    try:
        if widget.winfo_exists():
            widget.attributes("-alpha", value)
    except Exception:
        pass


def html_escape(text: str) -> str:
    """HTML 转义（用于导出 HTML 报告）。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def icon_button(
    parent: Any, label: str, tooltip: str, command: Callable[[], Any]
) -> ctk.CTkButton:
    """创建文字工具栏按钮（label 为按钮文字）并绑定悬浮提示。"""
    btn = ctk.CTkButton(
        parent,
        text=label,
        width=72,
        height=32,
        corner_radius=6,
        font=ctk.CTkFont(size=12),
        command=command,
    )
    btn.pack(side="left", padx=3)
    bind_tooltip(btn, tooltip)
    return btn


def bind_tooltip(widget: Any, text: str) -> None:
    """为控件绑定悬浮提示（单例 Tk tooltip，离开即销毁，防残留）。

    实现要点：
        - tooltip 为全局单例，任意时刻最多一个。
        - <Enter> 延迟 300ms 显示；<Leave> 立即销毁并取消延迟回调。
        - 全局 auto-hide 周期检查：鼠标离开按钮即销毁，防止残留。
    """
    import tkinter as _tk  # noqa: F401  (保持与原实现一致的依赖声明)

    def _under_owner() -> bool:
        try:
            w = _TOOLTIP_REF.get("owner") or widget
            if not w.winfo_exists():
                return False
            under = w.winfo_containing(w.winfo_pointerx(), w.winfo_pointery())
            if under is None:
                return False
            return str(under).startswith(str(w))
        except Exception:
            return False

    def _destroy_tip() -> None:
        _TOOLTIP_REF["after"] = None
        tip: Any = _TOOLTIP_REF.get("win")
        _TOOLTIP_REF["win"] = None
        _TOOLTIP_REF["owner"] = None
        if tip is not None:
            try:
                tip.destroy()
            except Exception:
                pass

    def _show_tip() -> None:
        _TOOLTIP_REF["after"] = None
        try:
            # 延迟期间鼠标已移开则不显示
            if not _under_owner():
                return
            _destroy_tip()
            tip = ctk.CTkToplevel(widget)
            tip.wm_overrideredirect(True)
            tip.attributes("-topmost", True)
            x: int = widget.winfo_rootx() + 12
            y: int = widget.winfo_rooty() + widget.winfo_height() + 4
            tip.wm_geometry(f"+{x}+{y}")
            ctk.CTkLabel(
                tip,
                text=text,
                text_color="#ffffff",
                fg_color="#333333",
                corner_radius=4,
            ).pack(padx=6, pady=4)
            _TOOLTIP_REF["win"] = tip
            _TOOLTIP_REF["owner"] = widget
            widget.after(150, _auto_hide)
        except Exception:
            pass

    def _auto_hide() -> None:
        _TOOLTIP_REF["after"] = None
        tip: Any = _TOOLTIP_REF.get("win")
        if tip is None:
            return
        if not _under_owner():
            _destroy_tip()
            return
        try:
            widget.after(150, _auto_hide)
        except Exception:
            pass

    def _on_enter(_event: Any) -> None:
        # 清除旧的延迟回调，重新计时
        try:
            if _TOOLTIP_REF["after"] is not None:
                widget.after_cancel(_TOOLTIP_REF["after"])
        except Exception:
            pass
        _TOOLTIP_REF["after"] = widget.after(300, _show_tip)

    def _on_leave(_event: Any) -> None:
        try:
            if _TOOLTIP_REF["after"] is not None:
                widget.after_cancel(_TOOLTIP_REF["after"])
        except Exception:
            pass
        _TOOLTIP_REF["after"] = None
        _destroy_tip()

    widget.bind("<Enter>", _on_enter)
    widget.bind("<Leave>", _on_leave)
