# -*- coding: utf-8 -*-
"""UI 模块层：各功能模块的独立内容构建器。

每个模块负责在给定容器中构建自身 UI，并提供导航元信息。
主框架（ui/app.py）负责布局容器 + 模块路由，不关心模块内部细节。

约定：
    class Module:
        key: str                      # 唯一标识
        title: str                    # 显示名
        icon: str                     # 导航图标（emoji 或文本）
        def build(self, container):   # 在 container 中构建内容
"""
