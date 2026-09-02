# -*- coding: utf-8 -*-
"""窗口背景模块：加载素材背景图并作为窗口最底层显示。

背景图随包分发（assets/bg_full.png），路径兼容源码运行 / PyInstaller 打包。
使用 tk.Canvas 承载背景，lower() 到最底层，其余控件照常叠加。

性能与可读性优化：
    - 基底图在加载时一次性叠加"右侧向右渐深的白色遮罩"——素材角色
      位于左侧，右侧为内容区，遮罩提升前景文字可读性；
    - 重采样结果按 64px 宽度分桶缓存（最多 3 桶），窗口拖动缩放时
      不再反复对 2560×1600 大图做全尺寸插值。
"""

from pathlib import Path
from typing import Any, Optional

import customtkinter as ctk
import tkinter as tk
from loguru import logger

# 背景素材查找名（新 assets/ 路径 + 旧根目录兼容）
_BG_NAMES: tuple[str, ...] = ("assets/bg_full.png", "DiffGuard_背景.png")

# 重采样宽度分桶与缓存上限
_BUCKET: int = 64
_CACHE_LIMIT: int = 3

# 右侧渐变遮罩：从 45% 宽度起向右渐深至该不透明度（白色）
_GRADIENT_START_RATIO: float = 0.45
_GRADIENT_MAX_ALPHA: int = 200


def _find_background() -> Optional[str]:
    """在源码运行 / 打包 / 当前目录下定位背景图。"""
    import sys

    cands: list[str] = []
    try:
        roots: list[Path] = [
            Path(__file__).resolve().parent.parent,
            Path(sys.executable).resolve().parent,
            Path.cwd(),
        ]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.insert(0, Path(meipass))
        for root in roots:
            for name in _BG_NAMES:
                cands.append(str(root / name))
                cands.append(str(root / "_internal" / name))
    except Exception:
        cands.extend(_BG_NAMES)
    for c in cands:
        if Path(c).is_file():
            return c
    return None


def _with_gradient(img: "Any") -> "Any":
    """在基底图右侧叠加向右渐深的白色遮罩（一次性执行）。"""
    from PIL import Image, ImageDraw

    w, h = img.size
    start = int(w * _GRADIENT_START_RATIO)
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    span = max(1, w - start)
    for x in range(start, w):
        alpha = int(_GRADIENT_MAX_ALPHA * (x - start) / span)
        draw.line([(x, 0), (x, h)], fill=(255, 255, 255, alpha))
    return Image.alpha_composite(img, overlay)


class WindowBackground:
    """把一张背景图作为窗口最底层（Canvas）。"""

    def __init__(self, master: ctk.CTk) -> None:
        self.master = master
        self.canvas: Optional[tk.Canvas] = None
        self._photo = None  # 当前展示的 PhotoImage（保持引用防 GC）
        self._base: Optional[Any] = None  # 叠加遮罩后的基底 PIL 图
        self._cache: dict[int, Any] = {}  # 宽度桶 -> PhotoImage
        self._last_w: int = 0
        self._last_h: int = 0
        path = _find_background()
        if path is None:
            logger.info("未找到背景图 {}，跳过背景", "/".join(_BG_NAMES))
            return
        try:
            from PIL import Image

            self._base = _with_gradient(Image.open(path).convert("RGBA"))
        except Exception as exc:
            logger.debug("背景图加载失败: {}", exc)

    def _scaled_photo(self, w: int, h: int) -> Optional[Any]:
        """按 contain 尺寸取分桶缓存的 PhotoImage（等比、完整显示）。"""
        from PIL import Image, ImageTk

        if self._base is None:
            return None
        iw, ih = self._base.size
        scale = min(w / iw, h / ih)
        nw = max(1, int(iw * scale))
        nh = max(1, int(ih * scale))
        bucket = max(_BUCKET, (nw + _BUCKET - 1) // _BUCKET * _BUCKET)
        photo = self._cache.get(bucket)
        if photo is None:
            img = self._base.resize((bucket, int(bucket * ih / iw)), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._cache[bucket] = photo
            if len(self._cache) > _CACHE_LIMIT:
                self._cache.pop(next(iter(self._cache)))
        return photo

    def _load_and_draw(self, w: int, h: int) -> None:
        """按 contain 模式绘制背景：完整显示整张图（等比缩放，不裁剪），居中。

        若窗口比例与图比例不同，四周以图片边缘主色填充。
        """
        photo = self._scaled_photo(w, h)
        if photo is None or self.canvas is None:
            return
        self._photo = photo
        nw, nh = photo.width(), photo.height()

        # 画布底色（取图片上边缘中部主色，保证与背景协调）
        try:
            px = self._base.getpixel((self._base.width // 2, 1))
            base = px[:3]
        except Exception:
            base = (245, 243, 238)
        bg_hex = "#%02x%02x%02x" % base

        self.canvas.delete("all")
        self.canvas.configure(width=w, height=h, bg=bg_hex)
        self.canvas.create_image((w - nw) // 2, (h - nh) // 2, image=self._photo, anchor="nw")

    def attach(self) -> None:
        """创建背景 Canvas 并置于最底层。"""
        if self._base is None:
            return
        try:
            w: int = self.master.winfo_width() or 1200
            h: int = self.master.winfo_height() or 800
            self._last_w, self._last_h = w, h
            self.canvas = tk.Canvas(self.master, highlightthickness=0, bd=0)
            self.canvas.grid(row=0, column=0, rowspan=99, columnspan=99)
            self._load_and_draw(w, h)
            try:
                self.canvas.lower("all")
            except Exception:
                pass
            logger.info("已加载窗口背景")
        except Exception as exc:
            logger.debug("加载窗口背景失败: {}", exc)

    def resize(self) -> None:
        """窗口尺寸变化时重铺背景（分桶缓存，避免重复全尺寸插值）。"""
        if self._base is None or self.canvas is None:
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
