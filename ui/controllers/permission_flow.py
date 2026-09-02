# -*- coding: utf-8 -*-
"""权限流程控制器:自动放行判定、托盘通知、浮窗展示与决策回写。

从 app.py 抽出;持久化与 UIA 回写沿用原有 models/core 接口。
"""

import queue
import threading
from typing import Any

from loguru import logger

from core.permission_risk import risk_level as permission_risk_level
from models.permission_history import save_permission, update_permission_decision
from ui.notify import tray_notify
from ui.permission_alert import PermissionAlert
from ui.poller import QueuePoller


class PermissionFlow:
    """权限请求处理流。依赖 app(config/状态栏/watcher_manager/浮窗实例)。"""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.queue: "queue.Queue[Any]" = queue.Queue()
        self._poller = QueuePoller(
            app, self.queue, self.handle_prompt,
            interval_ms=200,
            pre_poll=self._refresh_online_state,
            label="permission",
        )

    # ------------------------------------------------------------------
    # 入口(watcher 回调,后台线程执行)
    # ------------------------------------------------------------------
    def enqueue(self, prompt: Any) -> None:
        """权限请求入队(后台线程调用安全)。"""
        self.queue.put(prompt)

    def start(self) -> None:
        """启动权限队列轮询(幂等)。"""
        self._poller.start()

    def stop(self) -> None:
        """停止权限队列轮询。"""
        self._poller.stop()

    def _refresh_online_state(self) -> None:
        """每轮刷新 UIA 在线状态(供状态栏指示读取)。"""
        manager = self.app.watchers
        if manager.permission_watcher is not None:
            self.app.perm_watcher_online = manager.perm_watcher_online

    # ------------------------------------------------------------------
    # 处理
    # ------------------------------------------------------------------
    def handle_prompt(self, prompt: Any) -> None:
        """处理一个权限请求：自动放行判定、保存记录、通知、浮窗。"""
        config = self.app.config
        manager = self.app.watchers
        record_id = save_permission(prompt)
        prompt.db_id = record_id
        logger.info("已记录权限请求 → 入库 id={}", record_id)

        # 低风险自动放行
        if config.auto_allow_low_risk and prompt.risk_score < config.auto_allow_threshold:
            logger.info(
                "低风险自动放行: risk={} < threshold={}",
                prompt.risk_score,
                config.auto_allow_threshold,
            )
            if prompt.window_handle is not None and manager.permission_watcher is not None:
                if config.keyboard_inject:
                    manager.permission_watcher.apply_decision_keyboard(prompt, "once_allowed")
                else:
                    manager.permission_watcher.apply_decision(prompt, "once_allowed")
            if prompt.db_id is not None:
                update_permission_decision(prompt.db_id, "once_allowed")
            self.app.set_status(
                f"已自动放行低风险权限请求: {prompt.target}（风险 {prompt.risk_score}）"
            )
            return

        self.app.set_status(
            f"权限请求: {prompt.source} {prompt.action.value} {prompt.target}"
            f"（风险 {prompt.risk_score}/100）"
        )
        try:
            self.app.bell()
        except Exception:
            pass

        # 高风险系统托盘通知
        if config.tray_notify and prompt.risk_score >= 60:
            threading.Thread(
                target=tray_notify,
                args=(
                    "DiffGuard 高风险权限请求",
                    f"{prompt.source} 请求 {prompt.action.value} {prompt.target}\n"
                    f"风险 {prompt.risk_score}/100，请确认!",
                    2,
                ),
                daemon=True,
            ).start()

        if manager.permission_alert is not None:
            manager.permission_alert.show_prompt(prompt)
        # 高频下防止面板被覆盖丢失提示
        self.app.lift()

    # ------------------------------------------------------------------
    # 决策回写
    # ------------------------------------------------------------------
    def on_alert_decision(self, prompt: Any, decision: str) -> None:
        """浮窗决策回调：写回 UIA 原始窗口并持久化记录。"""
        config = self.app.config
        manager = self.app.watchers
        if prompt.window_handle is not None and manager.permission_watcher is not None:
            if config.keyboard_inject:
                manager.permission_watcher.apply_decision_keyboard(prompt, decision)
            else:
                manager.permission_watcher.apply_decision(prompt, decision)
        if getattr(prompt, "db_id", None) is not None:
            update_permission_decision(prompt.db_id, decision)
        self.app.set_status(
            f"已{'允许' if decision != 'rejected' else '拒绝'}权限请求: {prompt.target}"
        )
        alert = manager.permission_alert
        if alert is not None:
            existing = PermissionAlert.get_instance(self.app)
            if existing is not None and getattr(existing, "_prompt", None) is prompt:
                try:
                    alert.hide()
                except Exception:
                    pass
