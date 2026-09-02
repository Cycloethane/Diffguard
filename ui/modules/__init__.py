# -*- coding: utf-8 -*-
"""主窗口模块注册表:导航 key → 模块实例。

每个模块在给定容器中构建自身 UI 并提供导航元信息(key/title/icon),
主窗口(ui/app.py)只负责布局容器 + 注册表驱动的模块路由。
新增模块只需在这里注册。
"""

from typing import Any

from ui.modules.base import Module
from ui.modules.review import ReviewModule
from ui.modules.views import (
    DecisionModule,
    HistoryModule,
    PermissionModule,
    SettingsModule,
)

# 导航条目顺序即注册表顺序
MODULES: dict[str, Any] = {
    ReviewModule.key: ReviewModule(),
    HistoryModule.key: HistoryModule(),
    PermissionModule.key: PermissionModule(),
    DecisionModule.key: DecisionModule(),
    SettingsModule.key: SettingsModule(),
}

# 导航显示条目 (key, icon, title)
NAV_ITEMS: list[tuple[str, str, str]] = [
    (m.key, m.icon, m.title) for m in MODULES.values()
]

__all__ = ["MODULES", "NAV_ITEMS", "Module"]
