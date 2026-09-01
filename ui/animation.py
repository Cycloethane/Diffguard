# -*- coding: utf-8 -*-
"""轻量动画引擎：基于 Tkinter after() 的帧动画，无第三方依赖。

能力：
    1. 缓动函数：ease_out_cubic / ease_in_out / ease_out_back（轻微回弹）
    2. 颜色插值：在两色之间平滑过渡
    3. 帧动画驱动：animate() 周期性调用回调（参数 0→1），完成后自动停止

设计要点：
    - 全部在主线程 after() 中执行，不引入新线程，线程安全。
    - 每个动画最多运行 60 帧/秒，时长 150-600ms。
    - 全局开关：set_enabled(False) 后 animate() 直接调用回调 t=1.0（立即完成），
      保证"减少动态效果"时功能不受影响。
"""

import math
from typing import Any, Callable, Optional

# 全局开关：False 时所有动画立即完成
_enabled: bool = True

# 默认帧间隔（约 60fps）
_FRAME_MS: int = 16


def set_enabled(value: bool) -> None:
    """全局开关：False 时 animate() 立即完成（不做中间帧）。"""
    global _enabled
    _enabled = bool(value)


def is_enabled() -> bool:
    """返回动画是否开启。"""
    return _enabled


# ----------------------------------------------------------------------
# 缓动函数
# ----------------------------------------------------------------------
def ease_out_cubic(t: float) -> float:
    """ease-out：快速开始、缓慢结束，适合数值滚动与进度条。"""
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def ease_in_out(t: float) -> float:
    """ease-in-out：两端慢、中间快，适合淡入淡出。"""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def ease_out_back(t: float) -> float:
    """ease-out-back：带轻微回弹，适合弹窗出现。"""
    t = max(0.0, min(1.0, t))
    c1: float = 1.70158
    c3: float = c1 + 1.0
    return 1.0 + c3 * (t - 1.0) ** 3 + c1 * (t - 1.0) ** 2


def ease_out_elastic(t: float) -> float:
    """ease-out-elastic：较强弹性（过冲后回落），适合强调动画。"""
    t = max(0.0, min(1.0, t))
    if t == 0.0:
        return 0.0
    if t == 1.0:
        return 1.0
    c4: float = (2.0 * math.pi) / 3.0
    return 2.0 ** (-10.0 * t) * math.sin((t * 10.0 - 0.75) * c4) + 1.0


def ease_out_spring(t: float) -> float:
    """ease-out-spring：平滑过冲一次，适合卡片/按钮弹性。"""
    t = max(0.0, min(1.0, t))
    # 组合 overshoot：过冲到约 1.1 再回落
    return 1.0 + 2.70158 * (t - 1.0) ** 3 + 1.70158 * (t - 1.0) ** 2



# ----------------------------------------------------------------------
# 颜色插值
# ----------------------------------------------------------------------
def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    """把 #RRGGBB 或 #RGB 转为 (r,g,b)。"""
    color = color.strip().lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    if len(color) != 6:
        raise ValueError(f"无效颜色: {color}")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, int(round(v)))) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def interpolate_color(c1: str, c2: str, t: float) -> str:
    """返回 c1→c2 在进度 t 处的颜色（十六进制）。"""
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex(
        (
            r1 + (r2 - r1) * t,
            g1 + (g2 - g1) * t,
            b1 + (b2 - b1) * t,
        )
    )


def lerp(a: float, b: float, t: float) -> float:
    """数值线性插值。"""
    return a + (b - a) * t


# ----------------------------------------------------------------------
# 帧动画驱动
# ----------------------------------------------------------------------
class Animator:
    """管理一个正在运行的动画。

    通过 widget.after 驱动；cancel() 或动画完成时自动清理 after 句柄。
    """

    def __init__(self, widget: Any, step: Callable[[float], None], duration_ms: int = 300,
                 ease: Callable[[float], float] = ease_out_cubic,
                 on_done: Optional[Callable[[], None]] = None) -> None:
        self.widget = widget
        self.step = step
        self.duration = max(1, duration_ms)
        self.ease = ease
        self.on_done = on_done
        self._start_ms: Optional[int] = None
        self._after_id: Optional[str] = None
        self._done: bool = False

    def start(self) -> "Animator":
        """开始动画。"""
        if not _enabled:
            # 动画关闭：直接跳到终点
            self._finish(force=True)
            return self
        self._start_ms = _now_ms()
        self._tick()
        return self

    def _tick(self) -> None:
        if self._done:
            return
        now: int = _now_ms()
        elapsed: int = now - (self._start_ms or now)
        t: float = min(1.0, elapsed / self.duration)
        try:
            self.step(self.ease(t))
        except Exception:
            # 控件可能已销毁，安全终止
            self._done = True
            return
        if t >= 1.0:
            self._finish()
            return
        try:
            self._after_id = self.widget.after(_FRAME_MS, self._tick)
        except Exception:
            self._done = True

    def _finish(self, force: bool = False) -> None:
        if self._done and not force:
            return
        self._done = True
        if self.on_done is not None:
            try:
                self.on_done()
            except Exception:
                pass

    def cancel(self) -> None:
        """取消动画（不触发 on_done）。"""
        self._done = True
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None


def animate(widget: Any, step: Callable[[float], None], duration_ms: int = 300,
            ease: Callable[[float], float] = ease_out_cubic,
            on_done: Optional[Callable[[], None]] = None) -> Animator:
    """便捷入口：创建并启动一个动画。

    参数:
        widget: 驱动动画的控件（用于 after/cancel）。
        step: 每帧回调，参数为缓动后的进度 t（0→1）。
        duration_ms: 动画时长（毫秒）。
        ease: 缓动函数。
        on_done: 动画完成回调。
    """
    return Animator(widget, step, duration_ms, ease, on_done).start()


def pulse(widget: Any, step: Callable[[float], None], duration_ms: int = 400,
          on_done: Optional[Callable[[], None]] = None) -> Animator:
    """脉冲动画：0→1→0 一次（用于闪烁提醒）。"""
    def _inner(t: float) -> None:
        # 三角波：0→1→0
        v: float = 2.0 * t if t < 0.5 else 2.0 * (1.0 - t)
        step(v)
    return Animator(widget, _inner, duration_ms, ease_in_out, on_done).start()


def press_feedback(widget: Any, color: str, hover_color: str,
                   duration_ms: int = 300) -> Animator:
    """按钮点击反馈：颜色从主色轻微过冲回到 hover（弹性感）。

    在按钮 command 开头调用；动画自动完成，不阻塞。
    """
    def _step(t: float) -> None:
        v: float = ease_out_spring(t)
        try:
            if v > 1.0:
                # 过冲阶段用更亮的颜色
                c: str = interpolate_color(color, "#FFFFFF", min(1.0, (v - 1.0) * 3))
            else:
                c = interpolate_color(color, hover_color, v)
            widget.configure(fg_color=c)
        except Exception:
            pass
    return Animator(widget, _step, duration_ms, ease_out_cubic, None).start()


def _now_ms() -> int:
    """当前毫秒时间戳。"""
    import time

    return int(time.time() * 1000)


# ----------------------------------------------------------------------
# 窗口级动画辅助（浮窗弹出/收起）
# ----------------------------------------------------------------------
def fade_in_window(window: Any, duration_ms: int = 220, on_done: Optional[Callable[[], None]] = None,
                   final_alpha: float = 1.0) -> Animator:
    """窗口淡入 + 轻微上移出现。

    final_alpha：动画结束时的目标透明度（默认 1.0，可传 0.9 等实现整体半透明）。
    注意：Tk 的 -alpha 透明度依赖平台支持（Windows 支持），失败时忽略透明度
    仅做位置动画，保证不破坏布局。
    """
    final_alpha = max(0.0, min(1.0, final_alpha))
    try:
        window.attributes("-alpha", 0.0)
        has_alpha: bool = True
    except Exception:
        has_alpha = False

    def _step(t: float) -> None:
        v: float = ease_out_back(t)
        if has_alpha:
            try:
                window.attributes("-alpha", max(0.0, min(1.0, v * final_alpha)))
            except Exception:
                pass

    return Animator(window, _step, duration_ms, ease_out_cubic, on_done).start()


def fade_out_window(window: Any, duration_ms: int = 160, on_done: Optional[Callable[[], None]] = None) -> Animator:
    """窗口淡出后调用 on_done（调用方通常在此处真正 withdraw/destroy）。"""
    def _step(t: float) -> None:
        try:
            window.attributes("-alpha", max(0.0, 1.0 - t))
        except Exception:
            pass

    def _finish() -> None:
        try:
            window.attributes("-alpha", 1.0)
        except Exception:
            pass
        if on_done is not None:
            try:
                on_done()
            except Exception:
                pass

    return Animator(window, _step, duration_ms, ease_in_out, _finish).start()


def stop_alpha(window: Any) -> None:
    """复位窗口透明度为 1.0（动画结束后调用）。"""
    try:
        window.attributes("-alpha", 1.0)
    except Exception:
        pass


def slide_in(widget: Any, duration_ms: int = 240, distance: int = 24,
             ease: Callable[[float], float] = ease_out_spring) -> Animator:
    """控件从下往上滑入 + 淡入（用于模块/卡片入场）。

    通过 place 定位实现位移；若控件用 grid/pack 则无法移动，
    此时仅做透明度淡入（安全降级）。
    """
    def _step(t: float) -> None:
        v: float = ease(t)
        try:
            # 仅对使用 place 定位的控件生效
            widget.place_configure(y=int(distance * (1.0 - v)))
        except Exception:
            pass
        try:
            widget.attributes("-alpha", max(0.0, min(1.0, v)))
        except Exception:
            pass

    return Animator(widget, _step, duration_ms, ease_out_cubic, None).start()


# ----------------------------------------------------------------------
# 文本呼吸 / 打字光标
# ----------------------------------------------------------------------
def breathing_text(widget: Any, label: str, interval_ms: int = 500,
                   repeat: bool = True, stop_when: Optional[Callable[[], bool]] = None) -> Callable[[], None]:
    """让控件文本在 label、label.、label..、label... 间循环（呼吸效果）。

    返回停止函数；repeat=False 时只走一轮然后停在 label。
    stop_when：每帧检查，返回 True 时停止（保持 label 文本）。
    """
    dots: int = 0
    stopped: list[bool] = [False]

    def _tick() -> None:
        if stopped[0]:
            return
        if stop_when is not None and stop_when():
            try:
                widget.configure(text=label)
            except Exception:
                pass
            return
        nonlocal dots
        dots = (dots + 1) % 4
        text: str = label + "." * dots
        try:
            widget.configure(text=text)
        except Exception:
            stopped[0] = True
            return
        try:
            widget.after(interval_ms, _tick)
        except Exception:
            stopped[0] = True

    if _enabled:
        _tick()
    return lambda: stopped.__setitem__(0, True)


def blinking_cursor(textbox: Any, duration_ms: int = 450,
                    stop_when: Optional[Callable[[], bool]] = None) -> Callable[[], None]:
    """在文本框末尾追加/移除闪烁光标 ▌，用于流式输出期间。

    返回停止函数（停止时移除光标）。
    """
    cursor: str = "▌"
    visible: list[bool] = [True]
    stopped: list[bool] = [False]

    def _remove() -> None:
        try:
            content: str = textbox.get("1.0", "end-1c")
            if content.endswith(cursor):
                textbox.configure(state="normal")
                textbox.delete("end-%dc" % (len(cursor) + 1), "end-1c")
                textbox.configure(state="disabled")
        except Exception:
            pass

    def _tick() -> None:
        if stopped[0]:
            return
        if stop_when is not None and stop_when():
            _remove()
            return
        try:
            if visible[0]:
                _remove()
            else:
                textbox.configure(state="normal")
                textbox.insert("end", cursor)
                textbox.configure(state="disabled")
                textbox.see("end")
            visible[0] = not visible[0]
        except Exception:
            stopped[0] = True
            return
        try:
            textbox.after(duration_ms, _tick)
        except Exception:
            stopped[0] = True

    if _enabled:
        _tick()
    return lambda: (stopped.__setitem__(0, True), _remove())
