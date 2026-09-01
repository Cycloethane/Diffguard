# -*- coding: utf-8 -*-
"""UI 主题与强调色方案：基于 DiffGuard 吉祥物配色的双色系（浅/深）。

吉祥物提取色板：
    墨蓝描边 #183048 / 雾蓝 #607890-#90A8C0 / 蓝紫 #9090C0 /
    暖粉 #D89090 / 高光 #D8D8F0 / 米白 #F5F3EE
高风险警示保持标准红色（#DA3633）。
"""

# 强调色方案名 -> (主色, hover 色)
_ACCENTS: dict[str, tuple[str, str]] = {
    "blue": ("#183048", "#2A4A68"),       # 墨蓝
    "steel": ("#607890", "#7890A8"),      # 雾蓝
    "violet": ("#9090C0", "#A8A8D8"),     # 蓝紫
    "pink": ("#D89090", "#E0A8A8"),       # 暖粉
}

# 深色主题下使用更深一档
_ACCENTS_LIGHT: dict[str, tuple[str, str]] = {
    "blue": ("#183048", "#2A4A68"),
    "steel": ("#4A6078", "#607890"),
    "violet": ("#7A7AA8", "#9090C0"),
    "pink": ("#C07878", "#D89090"),
}

# 浅色主题界面表面色
SURFACE_LIGHT: str = "#FFFFFF"
SURFACE_LIGHT_MUTED: str = "#F5F3EE"     # 米白
SURFACE_LIGHT_BORDER: str = "#D8D8F0"    # 高光边框
TEXT_LIGHT: str = "#183048"              # 墨蓝文字
TEXT_LIGHT_MUTED: str = "#607890"        # 雾蓝次要文字
ACCENT_LIGHT: str = "#183048"
# 磨砂：半透明白（用于面板叠在背景上）
FROST_LIGHT: str = "#F2F4F8"
FROST_LIGHT_HI: str = "#FAFBFF"

# 深色主题界面表面色
SURFACE_DARK: str = "#183048"
SURFACE_DARK_MUTED: str = "#1F3A52"
SURFACE_DARK_BORDER: str = "#2A4A68"
TEXT_DARK: str = "#E8ECF2"
TEXT_DARK_MUTED: str = "#90A8C0"
ACCENT_DARK: str = "#90A8C0"
FROST_DARK: str = "#1B3550"
FROST_DARK_HI: str = "#23405C"

# 高风险警示色（保持不变，红色）
RISK_HIGH: str = "#DA3633"
# 中风险
RISK_MEDIUM: str = "#D29922"
# 低风险
RISK_LOW: str = "#238636"

# 默认强调色
DEFAULT_ACCENT: str = "blue"


def accent_names() -> list[str]:
    """返回所有可用的强调色方案名。"""
    return list(_ACCENTS.keys())


def accent(name: str, light: bool = False) -> tuple[str, str]:
    """返回 (主色, hover 色)；未知方案回退墨蓝。"""
    table: dict[str, tuple[str, str]] = _ACCENTS_LIGHT if light else _ACCENTS
    return table.get(name, _ACCENTS[DEFAULT_ACCENT])


def accent_primary(name: str, light: bool = False) -> str:
    """返回强调色主色。"""
    return accent(name, light)[0]


def surface(light: bool = False) -> str:
    """返回面板/卡片表面色。"""
    return SURFACE_LIGHT if light else SURFACE_DARK


def surface_muted(light: bool = False) -> str:
    """返回次级面板表面色。"""
    return SURFACE_LIGHT_MUTED if light else SURFACE_DARK_MUTED


def surface_border(light: bool = False) -> str:
    """返回边框色。"""
    return SURFACE_LIGHT_BORDER if light else SURFACE_DARK_BORDER


def text_color(light: bool = False) -> str:
    """返回正文颜色。"""
    return TEXT_LIGHT if light else TEXT_DARK


def text_muted(light: bool = False) -> str:
    """返回次要文字颜色。"""
    return TEXT_LIGHT_MUTED if light else TEXT_DARK_MUTED


def frost(light: bool = False) -> str:
    """返回磨砂半透明面板底色。"""
    return FROST_LIGHT if light else FROST_DARK


def frost_hi(light: bool = False) -> str:
    """返回磨砂面板高亮底（悬停/选中）。"""
    return FROST_LIGHT_HI if light else FROST_DARK_HI
