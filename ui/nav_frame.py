# -*- coding: utf-8 -*-
"""左侧窄导航组件：磨砂质感、激活指示条滑动、弹性反馈。

通过回调通知选中变化；激活项有高光圆角底 + 左侧指示条，
切换时指示条平滑移动到新位置（place 动画）。
"""

from typing import Any, Callable, Optional

import customtkinter as ctk

from ui.animation import animate, ease_out_spring, interpolate_color, press_feedback
from ui.theme import frost, frost_hi, text_color, text_muted


class NavFrame(ctk.CTkFrame):
    """窄导航条。

    属性:
        on_select: 选中回调 callback(key: str)。
        items: [(key, icon, title), ...]。
    """

    def __init__(
        self,
        master: Any,
        items: list[tuple[str, str, str]],
        on_select: Callable[[str], None],
        light: bool = True,
        width: int = 150,
        wide: bool = True,
    ) -> None:
        super().__init__(master, fg_color="transparent", corner_radius=0, width=width)
        self.light = light
        self.on_select = on_select
        self.items = items
        self.wide = wide
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._badges: dict[str, ctk.CTkLabel] = {}
        self._active: Optional[str] = None
        self._indicator = None  # 激活指示条

        self.pack_propagate(False)
        self._build()
        # 布局完成后定位指示条（winfo_y 需在渲染后有效）
        self.after(80, lambda: self._move_indicator(self.items[0][0] if self.items else None, False))
        # 仅设置激活态，不触发 on_select（等外部初始化完成后调用）
        self.select(items[0][0] if items else None, animate=False, notify=False)

    def set_wide(self, wide: bool) -> None:
        """切换宽/窄形态（保留接口；默认文字模式）。"""
        self.wide = wide
        for key, btn in self._buttons.items():
            title = dict((i[0], i[2]) for i in self.items)[key]
            if wide:
                btn.configure(text=f"{title}", width=120, font=ctk.CTkFont(size=13))
            else:
                btn.configure(text=f"{title[:2]}", width=40, font=ctk.CTkFont(size=13))
        self.configure(width=150 if wide else 64)

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        # 顶部 Logo（文字）
        logo = ctk.CTkLabel(
            self, text="DiffGuard", font=ctk.CTkFont(size=15, weight="bold"),
            text_color=text_color(self.light),
        )
        logo.grid(row=0, column=0, pady=(16, 18))

        # 指示条（绝对定位，激活项左侧）——用原生 tk.Frame 支持 place width/height
        import tkinter as tk

        self._indicator = tk.Frame(self, bg=text_color(self.light))

        for idx, (key, icon, title) in enumerate(self.items, start=1):
            btn = ctk.CTkButton(
                self,
                text=title,
                width=120,
                height=40,
                corner_radius=10,
                fg_color="transparent",
                hover_color=frost_hi(self.light),
                text_color=text_color(self.light),
                font=ctk.CTkFont(size=13),
                anchor="w",
                command=lambda k=key: self.select(k),
            )
            btn.grid(row=idx, column=0, padx=12, pady=4, sticky="ew")
            self._buttons[key] = btn
            # 悬停提示
            try:
                from ui.widgets import bind_tooltip as _bind

                _bind(btn, title)
            except Exception:
                pass
            # 角标（默认隐藏，如决策待办数）
            badge = ctk.CTkLabel(
                btn,
                text="",
                font=ctk.CTkFont(size=9, weight="bold"),
                width=16,
                height=16,
                corner_radius=8,
                fg_color="#DA3633",
                text_color="#FFFFFF",
            )
            badge.place(relx=1.0, x=2, y=-2, anchor="ne")
            badge.place_forget()
            self._badges[key] = badge

        # 底部弹性占位（用于底部对齐的额外项）
        self.grid_rowconfigure(len(self.items) + 1, weight=1)

    def select(self, key: Optional[str], animate: bool = True, notify: bool = True) -> None:
        """选中某项：更新高亮与指示条位置。"""
        if key is None or key not in self._buttons:
            return
        self._active = key
        for k, btn in self._buttons.items():
            if k == key:
                btn.configure(fg_color=frost_hi(self.light))
                if animate:
                    press_feedback(btn, frost_hi(self.light), frost_hi(self.light))
            else:
                btn.configure(fg_color="transparent")
        # 指示条滑动到激活项
        self._move_indicator(key, animate)
        if notify and self.on_select:
            self.on_select(key)

    def _move_indicator(self, key: str, animated: bool) -> None:
        btn = self._buttons.get(key)
        if btn is None or self._indicator is None:
            return
        y0 = btn.winfo_y() + 8
        y1 = btn.winfo_y() + btn.winfo_height() - 8

        def _step(t: float) -> None:
            if self._indicator is None:
                return
            self._indicator.place(
                x=2, y=int(y0 + (y1 - y0) * t), width=3, height=max(8, int((y1 - y0) * (0.6 + 0.4 * t)))
            )

        if animated:
            animate(self._indicator, _step, duration_ms=260, ease=ease_out_spring)
        else:
            _step(1.0)

    @property
    def active(self) -> Optional[str]:
        return self._active

    def set_badge(self, key: str, count: int = 0) -> None:
        """设置某导航项的角标；count<=0 时隐藏。"""
        badge = self._badges.get(key)
        if badge is None:
            return
        if count <= 0:
            badge.place_forget()
        else:
            badge.configure(text=str(count) if count <= 99 else "99+")
            badge.place(relx=1.0, x=2, y=-2, anchor="ne")
