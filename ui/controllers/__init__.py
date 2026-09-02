# -*- coding: utf-8 -*-
"""UI 控制器层:从 app.py 抽出的业务流程组件。

- WatcherManager  三个监视线程的生命周期与配置热切换
- ReviewFlow      diff 载入/渲染/风险仪表/AI 审查流式/保存导出
- PermissionFlow  权限请求处理(自动放行/托盘/浮窗/回写)
- DecisionFlow    决策请求处理(AI 解析流/决策闭环/角标)
"""

from ui.controllers.watcher_manager import WatcherManager
from ui.controllers.review_flow import ReviewFlow
from ui.controllers.permission_flow import PermissionFlow
from ui.controllers.decision_flow import DecisionFlow

__all__ = ["WatcherManager", "ReviewFlow", "PermissionFlow", "DecisionFlow"]
