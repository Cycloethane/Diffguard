# -*- coding: utf-8 -*-
"""权限流程控制器:自动放行判定、托盘通知、浮窗展示、决策回写,
以及 ZCode 钩子权限事件的桥接轮询(高风险托盘提醒 + 前台小窗权限栏)。

从 app.py 抽出;持久化与 UIA 回写沿用原有 models/core 接口。
"""

import hashlib
import queue
import threading
import time
from typing import Any, Optional

from loguru import logger

from core.permission_advisor import advise_permission
from core.permission_risk import risk_level as permission_risk_level
from models.config import is_configured
from models.permission_history import save_permission, update_permission_decision
from ui.notify import tray_notify
from ui.permission_advice_alert import PermissionAdviceAlert
from ui.permission_alert import PermissionAlert
from ui.poller import QueuePoller

# 桥接权限事件轮询间隔(秒)与小窗展示保留时长(秒)
_BRIDGE_POLL_INTERVAL_MS: int = 1500
_OVERLAY_EVENT_TTL: float = 15.0
# 权限顾问:同类请求(tool+raw 哈希)去重窗口(秒)
_ADVICE_DEDUPE_TTL: float = 600.0


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
        # ZCode 钩子桥接事件(独立于 UIA 监听,始终轮询)
        self.recent_bridge_event: Optional[dict] = None
        self._last_bridge_seq: int = 0
        self._bridge_after_id: Optional[str] = None
        # 权限顾问(AI 分析流)
        self._advice_queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._advice_poller = QueuePoller(
            app, self._advice_queue, self._apply_advice_line,
            interval_ms=400, label="permission-advice",
        )
        self._advice_seen: dict[str, float] = {}  # 去重: hash -> time

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
        """停止权限队列轮询与权限顾问流轮询。"""
        self._poller.stop()
        self._advice_poller.stop()

    def _refresh_online_state(self) -> None:
        """每轮刷新 UIA 在线状态(供状态栏指示读取)。"""
        manager = self.app.watchers
        if manager.permission_watcher is not None:
            self.app.perm_watcher_online = manager.perm_watcher_online

    # ------------------------------------------------------------------
    # ZCode 钩子桥接事件(文件轮询,始终开启)
    # ------------------------------------------------------------------
    def start_bridge(self) -> None:
        """启动桥接权限事件轮询(幂等);高风险事件触发托盘提醒。"""
        if self._bridge_after_id is not None:
            return

        def _tick() -> None:
            self._bridge_after_id = self.app.after(
                _BRIDGE_POLL_INTERVAL_MS, _tick
            )
            self.poll_bridge_events()

        _tick()

    def stop_bridge(self) -> None:
        """停止桥接轮询。"""
        if self._bridge_after_id is not None:
            try:
                self.app.after_cancel(self._bridge_after_id)
            except Exception:
                pass
            self._bridge_after_id = None

    def poll_bridge_events(self) -> None:
        """轮询 permission_events.json;新事件 → 状态栏 + 高风险托盘提醒。"""
        try:
            from bridge import store as bridge_store

            event = bridge_store.read_permission_event()
        except Exception as exc:
            logger.debug("读取权限桥接事件失败: {}", exc)
            return
        if not isinstance(event, dict):
            return
        seq = int(event.get("seq", 0) or 0)
        if seq <= self._last_bridge_seq:
            return
        self._last_bridge_seq = seq
        event["_received_at"] = time.time()
        self.recent_bridge_event = event

        tool = str(event.get("tool", ""))
        score = int(event.get("score", 0) or 0)
        level = str(event.get("level", "low"))
        target = str(event.get("target", "") or "")
        mark = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(level, "⚪")
        self.app.set_status(f"{mark} ZCode 权限请求: {tool}（风险 {score}/100）{('· ' + target[:40]) if target else ''}")

        if level == "high":
            try:
                self.app.bell()
            except Exception:
                pass
            findings = "、".join(str(f) for f in event.get("findings", [])) or "无明细"
            threading.Thread(
                target=tray_notify,
                args=(
                    "DiffGuard 高风险权限请求（ZCode）",
                    f"{tool} {target[:60]}\n风险 {score}/100：{findings}\n请在 ZCode 弹窗中谨慎确认!",
                    3,
                ),
                daemon=True,
            ).start()

        # 权限顾问:中高风险且开关开启且未去重 → 弹 AI 分析浮窗
        try:
            self._maybe_show_advice(event)
        except Exception as exc:
            logger.debug("权限顾问触发失败: {}", exc)

    # ------------------------------------------------------------------
    # 权限顾问(是什么/后果/建议,仅提示不代答)
    # ------------------------------------------------------------------
    def _maybe_show_advice(self, event: dict) -> None:
        """按配置与阈值弹权限顾问浮窗,并按需启动 AI 分析流。"""
        config = self.app.config
        if not getattr(config, "permission_advice", True):
            return
        score = int(event.get("score", 0) or 0)
        threshold = int(getattr(config, "permission_advice_threshold", 20) or 20)
        if score < threshold:
            return
        # 去重:同类请求(tool+raw)在窗口期内不重复弹
        key_raw = f"{event.get('tool', '')}|{event.get('raw', '') or event.get('target', '')}"
        key = hashlib.md5(key_raw.encode("utf-8", errors="ignore")).hexdigest()
        now = time.time()
        self._advice_seen = {k: v for k, v in self._advice_seen.items() if now - v < _ADVICE_DEDUPE_TTL}
        if key in self._advice_seen:
            return
        self._advice_seen[key] = now

        alert = PermissionAdviceAlert.ensure_instance(self.app)
        ai_enabled = is_configured(config)
        alert.show_event(event, ai_enabled=ai_enabled)

        if not ai_enabled:
            return

        # 后台线程流式分析,主线程轮询填充浮窗
        config_ref = config

        def _run() -> None:
            try:
                for line in advise_permission(event, config_ref):
                    self._advice_queue.put(line)
            except Exception as exc:  # 兜底:不让线程崩溃
                logger.exception("权限分析线程异常: {}", exc)
                self._advice_queue.put("#ERROR# 分析线程异常，请查看日志。")
            finally:
                self._advice_queue.put(None)  # 结束哨兵

        self._advice_poller.start()  # 幂等
        threading.Thread(target=_run, daemon=True).start()

    def _apply_advice_line(self, line: Optional[str]) -> None:
        """消费一行分析输出;None 为结束哨兵。"""
        alert = PermissionAdviceAlert.get_instance(self.app)
        if alert is None:
            return
        if line is None:
            alert.set_done()  # 仅有 WHAT/CONSEQUENCE 时也标记完成
            return
        alert.apply_line(line)

    def overlay_permission(self) -> Optional[dict]:
        """供前台小窗展示的最近权限事件(超时自动消失)。"""
        event = self.recent_bridge_event
        if not event:
            return None
        age = time.time() - float(event.get("_received_at", 0) or 0)
        if age > _OVERLAY_EVENT_TTL:
            return None
        return {
            "source": str(event.get("source", "ZCode")),
            "tool": str(event.get("tool", "")),
            "target": str(event.get("target", "")),
            "score": int(event.get("score", 0) or 0),
            "level": str(event.get("level", "low")),
            "age": round(age, 1),
        }

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
