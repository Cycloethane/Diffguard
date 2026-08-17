# -*- coding: utf-8 -*-
"""UI 主题与强调色方案：集中管理强调色（accent）的明暗对。

各界面模块通过 accent() 获取当前强调色，避免散落硬编码。
"""

# 强调色方案名 -> (主色, hover 色)
_ACCENTS: dict[str, tuple[str, str]] = {
    "blue": ("#2f81f7", "#388bfd"),
    "green": ("#238636", "#2ea043"),
    "purple": ("#8250df", "#a371f7"),
    "orange": ("#d9761f", "#e8912c"),
}

# 深色主题主色（新增，供未来扩展浅色主题使用）
_ACCENTS_LIGHT: dict[str, tuple[str, str]] = {
    "blue": ("#1f6feb", "#0969da"),
    "green": ("#1a7f37", "#116329"),
    "purple": ("#6639ba", "#512a97"),
    "orange": ("#bc4c00", "#a04000"),
}


def accent_names() -> list[str]:
    """返回所有可用的强调色方案名。"""
    return list(_ACCENTS.keys())


def accent(name: str, light: bool = False) -> tuple[str, str]:
    """返回 (主色, hover 色)；未知方案回退蓝色。"""
    table: dict[str, tuple[str, str]] = _ACCENTS_LIGHT if light else _ACCENTS
    return table.get(name, _ACCENTS["blue"])


def accent_primary(name: str, light: bool = False) -> str:
    """返回强调色主色。"""
    return accent(name, light)[0]
