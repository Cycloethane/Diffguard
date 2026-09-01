# -*- coding: utf-8 -*-
"""坐姿吉祥物资源：加载、裁剪透明背景、按目标高度缩放。

坐姿吉祥物.png 本身已是透明背景（角色主体 alpha=255，周围 alpha=0）。
本模块提供 find / load / fit 能力，供前台悬浮窗把吉祥物"坐"在窗口下沿、
头伸出窗口上沿之外（异形效果由调用方用 -transparentcolor 实现）。
"""

from pathlib import Path
from typing import Optional, Tuple

from loguru import logger
from PIL import Image

_MASCOT_NAME: str = "坐姿吉祥物.png"
# 兜底：也尝试站立吉祥物
_FALLBACK_NAMES: tuple[str, ...] = ("DiffGuard吉祥物.png",)


def find_mascot() -> Optional[str]:
    """定位坐姿吉祥物图片路径（源码运行 / 打包 / 桌面 / 当前目录）。"""
    import sys

    cands: list[str] = []
    try:
        cwd = Path.cwd()
        exe_dir = Path(sys.executable).resolve().parent
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            cands.append(str(Path(meipass) / _MASCOT_NAME))
        for n in (_MASCOT_NAME,) + _FALLBACK_NAMES:
            cands.append(str(exe_dir / n))
            cands.append(str(exe_dir / "_internal" / n))
            cands.append(str(cwd / n))
            cands.append(str(Path(__file__).resolve().parent.parent / n))
        # 桌面
        import os

        desktop = Path(os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"))
        cands.append(str(desktop / _MASCOT_NAME))
        cands.append(str(desktop / _FALLBACK_NAMES[0]))
    except Exception:
        cands.append(_MASCOT_NAME)
    for c in cands:
        if Path(c).is_file():
            return c
    return None


def load_mascot(target_height: Optional[int] = None) -> Optional[Image.Image]:
    """加载吉祥物并裁剪到透明内容，返回 RGBA 图。

    target_height：目标高度（px）；None 时保持原始尺寸。
    自动裁剪透明内容包围盒。
    """
    path: Optional[str] = find_mascot()
    if path is None:
        logger.info("未找到坐姿吉祥物，跳过")
        return None
    try:
        img = Image.open(path).convert("RGBA")
        # 裁剪非透明内容
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        if target_height:
            w, h = img.size
            new_w = max(1, int(target_height * w / h))
            img = img.resize((new_w, target_height), Image.LANCZOS)
        return img
    except Exception as exc:
        logger.debug("加载吉祥物失败: {}", exc)
        return None
