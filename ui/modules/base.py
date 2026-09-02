# -*- coding: utf-8 -*-
"""模块协议:主窗口内容区的可切换模块。

每个模块实现 build(container, app):在容器内构建自己的界面。
app 由 DiffGuardApp 提供,模块通过它与控制器层交互。
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Module(Protocol):
    """主窗口模块协议。"""

    key: str
    title: str
    icon: str

    def build(self, container: Any, app: Any) -> None:
        """在 container(CTkFrame)内构建模块界面。"""
        ...
