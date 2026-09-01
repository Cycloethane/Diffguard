# -*- coding: utf-8 -*-
"""监视线程公共骨架包:三个 watcher(剪贴板/权限/决策)共享的线程与 UIA 设施。"""

from core.watchers.base import (
    BaseWatcher,
    collect_control_texts,
    iter_controls,
    uia_thread_session,
)

__all__ = [
    "BaseWatcher",
    "collect_control_texts",
    "iter_controls",
    "uia_thread_session",
]
