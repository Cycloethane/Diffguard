# -*- coding: utf-8 -*-
"""监视线程管理器:三个 watcher 的生命周期与配置热切换。

原先散落在 app.py 的 _start/_stop_*_watching 与设置保存回调中的
46 行热切换闭包收敛于此。app 只负责在启动/退出/设置变更时调用
start_all / shutdown / apply_config。

线程安全:watcher 回调在后台线程执行,这里只做 queue.put,
由 app 侧的 QueuePoller 在主线程消费。
"""

import queue
from typing import Any, Callable, Optional

from loguru import logger

from bridge import store as bridge_store
from core.clipboard_watcher import ClipboardWatcher
from core.decision_watcher import DecisionWatcher
from core.permission_watcher import PermissionWatcher
from models.config import Config
from models.decision_prompt import DecisionMode
from ui.decision_alert import DecisionAlert
from ui.permission_alert import PermissionAlert


class WatcherManager:
    """持有并管理剪贴板 / 权限 / 决策三个监视线程。

    回调注入:
        on_diff:      剪贴板检测到 diff(主线程侧消费 review 流程的队列)。
        on_permission:权限请求入队函数(PermissionFlow 提供)。
        on_decision:  决策请求入队函数(DecisionFlow 提供)。
    """

    def __init__(
        self,
        config: Config,
        on_diff: Callable[[str], None],
        on_permission: Callable[[Any], None],
        on_decision: Callable[[Any], None],
        master: Any,
        on_permission_decision: Callable[[Any, str], None],
        on_decision_chosen: Callable[[Any, str], None],
    ) -> None:
        self._config = config
        self._on_diff = on_diff
        self._on_permission = on_permission
        self._on_decision = on_decision
        self._master = master

        self.clipboard_watcher: Optional[ClipboardWatcher] = None
        self.permission_watcher: Optional[PermissionWatcher] = None
        self.permission_alert: Optional[PermissionAlert] = None
        self.decision_watcher: Optional[DecisionWatcher] = None
        self.decision_alert: Optional[DecisionAlert] = None
        self._on_permission_decision = on_permission_decision
        self._on_decision_chosen = on_decision_chosen

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------
    def start_all(self) -> None:
        """按当前配置启动全部监听。"""
        self.start_clipboard()
        self.start_permission()
        self.start_decision()

    def shutdown(self) -> None:
        """停止全部监听并销毁浮窗(退出时调用)。"""
        self.stop_clipboard()
        self.stop_permission(destroy_alert=True)
        self.stop_decision(destroy_alert=True)

    # ------------------------------------------------------------------
    # 剪贴板监听
    # ------------------------------------------------------------------
    def start_clipboard(self) -> None:
        """按配置启动剪贴板监听(权限监控开启时同时启用权限辅助通道)。"""
        if not self._config.auto_clipboard or self.clipboard_watcher is not None:
            return
        perm_cb = self._on_permission if self._config.permission_monitor else None
        self.clipboard_watcher = ClipboardWatcher(
            on_diff_detected=self._on_diff,
            on_permission_detected=perm_cb,
        )
        self.clipboard_watcher.start()

    def stop_clipboard(self) -> None:
        """停止剪贴板监听。"""
        if self.clipboard_watcher is not None:
            self.clipboard_watcher.stop()
            self.clipboard_watcher = None

    # ------------------------------------------------------------------
    # 权限监听(UIA 主通道 + 浮窗)
    # ------------------------------------------------------------------
    def start_permission(self) -> None:
        """按配置启动权限监听线程与置顶浮窗。"""
        if not self._config.permission_monitor or self.permission_watcher is not None:
            return
        if self._config.floating_mode_enabled:
            try:
                self.permission_alert = PermissionAlert(
                    self._master, on_decision=self._on_permission_decision
                )
            except Exception as exc:
                logger.debug("初始化权限浮窗失败: {}", exc)
                self.permission_alert = None
        self.permission_watcher = PermissionWatcher(
            on_prompt_detected=self._on_permission
        )
        self.permission_watcher.start()

    def stop_permission(self, destroy_alert: bool = False) -> None:
        """停止权限监听;destroy_alert 时销毁浮窗,否则仅隐藏。"""
        if self.permission_watcher is not None:
            try:
                self.permission_watcher.stop()
            except Exception as exc:
                logger.debug("停止权限监听失败: {}", exc)
            self.permission_watcher = None
        if self.permission_alert is not None:
            if destroy_alert:
                try:
                    self.permission_alert.destroy()
                except Exception as exc:
                    logger.debug("销毁权限浮窗失败: {}", exc)
                self.permission_alert = None
            else:
                try:
                    self.permission_alert.hide()
                except Exception as exc:
                    logger.debug("隐藏权限浮窗失败: {}", exc)

    # ------------------------------------------------------------------
    # 决策监听(三通道 + 浮窗)
    # ------------------------------------------------------------------
    def start_decision(self) -> None:
        """按配置启动决策监听(off 时不启动)。"""
        mode: str = getattr(self._config, "decision_assistant", DecisionMode.OFF.value)
        if mode == DecisionMode.OFF.value:
            logger.info("决策助手未启用（off）")
            return
        if self.decision_watcher is not None:
            return
        try:
            self.decision_alert = DecisionAlert(
                self._master, on_decide=self._on_decision_chosen
            )
        except Exception as exc:
            logger.debug("初始化决策浮窗失败: {}", exc)
            self.decision_alert = None
        self.decision_watcher = DecisionWatcher(
            on_decision_detected=self._on_decision,
            read_bridge_decision=(
                bridge_store.read_agent_decision_prompt
                if getattr(self._config, "agent_bridge", True)
                else None
            ),
        )
        self.decision_watcher.start()
        logger.info("决策助手已启动，模式: {}", mode)

    def stop_decision(self, destroy_alert: bool = False) -> None:
        """停止决策监听并隐藏/销毁浮窗。"""
        if self.decision_watcher is not None:
            try:
                self.decision_watcher.stop()
            except Exception as exc:
                logger.debug("停止决策监听失败: {}", exc)
            self.decision_watcher = None
        if self.decision_alert is not None:
            if destroy_alert:
                try:
                    self.decision_alert.destroy()
                except Exception as exc:
                    logger.debug("销毁决策浮窗失败: {}", exc)
                self.decision_alert = None
            else:
                try:
                    self.decision_alert.hide()
                except Exception as exc:
                    logger.debug("隐藏决策浮窗失败: {}", exc)

    def restart_decision(self) -> None:
        """重建决策监听(模式或 agent_bridge 开关变化后调用)。"""
        self.stop_decision()
        self.start_decision()

    # ------------------------------------------------------------------
    # 配置热切换
    # ------------------------------------------------------------------
    def apply_config(self, new_config: Config) -> None:
        """应用新配置到监听层(设置保存后调用),返回后 self._config 已更新。

        主题/强调色/动画等纯 UI 项由 app 自行处理。
        """
        old = self._config
        self._config = new_config

        # 剪贴板
        if new_config.auto_clipboard:
            if self.clipboard_watcher is None:
                self.start_clipboard()
            else:
                # 权限辅助通道随权限监控开关变化,需重建
                self.stop_clipboard()
                self.start_clipboard()
        else:
            self.stop_clipboard()

        # 权限监控
        if new_config.permission_monitor and not old.permission_monitor:
            self.stop_permission()
            self.start_permission()
        elif not new_config.permission_monitor and old.permission_monitor:
            self.stop_permission()

        # 决策助手模式 / agent_bridge 桥接开关
        new_decision: str = getattr(new_config, "decision_assistant", DecisionMode.OFF.value)
        old_decision: str = getattr(old, "decision_assistant", DecisionMode.OFF.value)
        bridge_changed: bool = getattr(new_config, "agent_bridge", True) != getattr(
            old, "agent_bridge", True
        )
        if new_decision != old_decision or bridge_changed:
            if new_decision == DecisionMode.OFF.value:
                self.stop_decision()
            else:
                self.restart_decision()

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    @property
    def perm_watcher_online(self) -> bool:
        """权限监听(UIA)是否可用,供状态栏指示。"""
        return bool(self.permission_watcher is not None and self.permission_watcher.available)

    def set_config(self, config: Config) -> None:
        """仅更新配置引用(不触发热切换),用于首启向导完成前的场景。"""
        self._config = config
