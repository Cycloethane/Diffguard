# -*- coding: utf-8 -*-
"""窗口背景模块：加载背景图并作为窗口最底层显示。

背景图随包分发（DiffGuard_背景.png），路径兼容源码运行 / PyInstaller 打包。
使用 tk.Canvas 承载背景，lower() 到最底层，其余控件照常叠加。
"""

from pathlib import Path
from typing import Optional

import customtkinter as ctk
import tkinter as tk
from loguru import logger

# 背景文件名（含 .png 后缀的完整文件名）
_BG_NAME: str = "DiffGuard_背景.png"


def _find_background() -> Optional[str]:
    """在源码运行 / 打包 / 当前目录下定位背景图。"""
    import sys

    names = (_BG_NAME,)
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
            cands.append(str(Path(__file__).resolve().parent.parent / n))
    except Exception:
        cands.append(_BG_NAME)
    for c in cands:
        if Path(c).is_file():
            return c
    return None


class WindowBackground:
    """把一张背景图作为窗口最底层（Canvas）。"""

    def __init__(self, master: ctk.CTk) -> None:
        self.master = master
        self.canvas: Optional[tk.Canvas] = None
        self._photo = None  # 保持引用防止 GC
        self._path: Optional[str] = _find_background()
        self._last_w: int = 0
        self._last_h: int = 0
        if self._path is None:
            logger.info("未找到背景图 {}，跳过背景", _BG_NAME)
            return

    def _load_and_draw(self, w: int, h: int) -> None:
        """按 contain 模式绘制背景：完整显示整张图（等比缩放，不裁剪），居中。

        若窗口比例与图比例不同，四周以画布底色填充。
        """
        from PIL import Image, ImageTk

        img = Image.open(self._path).convert("RGBA")
        iw, ih = img.size
        # 等比缩放：取使整图完整显示的比例
        scale = min(w / iw, h / ih)
        nw = max(1, int(iw * scale))
        nh = max(1, int(ih * scale))
        img = img.resize((nw, nh), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(img)

        # 画布底色（取图片边缘主色，保证与背景协调）
        base = img.getpixel((nw // 2, 1))[:3] if nh > 1 else (245, 243, 238)
        bg_hex = "#%02x%02x%02x" % base

        self.canvas.delete("all")
        self.canvas.configure(width=w, height=h, bg=bg_hex)
        # 居中放置
        x = (w - nw) // 2
        y = (h - nh) // 2
        self.canvas.create_image(x, y, image=self._photo, anchor="nw")

    def attach(self) -> None:
        """创建背景 Canvas 并置于最底层。"""
        if self._path is None:
            return
        try:
            from PIL import Image, ImageTk

            w: int = self.master.winfo_width() or 1200
            h: int = self.master.winfo_height() or 800
            self._last_w, self._last_h = w, h
            # 先做一张占位 PhotoImage（避免空引用）
            self._photo = ImageTk.PhotoImage(
                Image.open(self._path).resize((1, 1))
            )
            self.canvas = tk.Canvas(
                self.master,
                highlightthickness=0,
                bd=0,
            )
            self.canvas.grid(row=0, column=0, rowspan=99, columnspan=99)
            self._load_and_draw(w, h)
            try:
                self.canvas.lower("all")
            except Exception:
                pass
            logger.info("已加载窗口背景: {}", self._path)
        except Exception as exc:
            logger.debug("加载窗口背景失败: {}", exc)

    def resize(self) -> None:
        """窗口尺寸变化时重载背景（仅在尺寸明显变化时执行，避免刷屏）。"""
        if self._path is None or self.canvas is None:
            return
        try:
            w: int = max(1, self.master.winfo_width())
            h: int = max(1, self.master.winfo_height())
            if abs(w - self._last_w) < 8 and abs(h - self._last_h) < 8:
                return
            self._last_w, self._last_h = w, h
            self._load_and_draw(w, h)
            try:
                self.canvas.lower("all")
            except Exception:
                pass
        except Exception as exc:
            logger.debug("重载窗口背景失败: {}", exc)
