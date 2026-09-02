# -*- coding: utf-8 -*-
"""决策流程控制器:决策请求处理、AI 解析流、决策闭环与角标。

从 app.py 抽出。决策闭环:用户选择 → 桥接文件(decision_feedback.json,
供 Agent 读取)+ 决策历史库;agent_bridge 关闭时跳过桥接回写。
"""

import queue
import threading
from typing import Any

from loguru import logger

from bridge import store as bridge_store
from core.decision_explainer import explain_decision
from models.decision_history import save_decision as save_decision_record
from models.decision_prompt import DecisionMode
from ui.decision_alert import DecisionAlert
from ui.poller import QueuePoller


class DecisionFlow:
    """决策业务流。依赖 app(config/状态栏/nav 角标/浮窗实例)。"""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.queue: "queue.Queue[Any]" = queue.Queue()
        self._decision_stream: "queue.Queue[str]" = queue.Queue()
        self.pending: bool = False
        self._queue_poller = QueuePoller(
            app, self.queue, self.handle_prompt,
            interval_ms=300, label="decision",
        )
        self._stream_poller = QueuePoller(
            app, self._decision_stream, self._apply_stream_line,
            interval_ms=400, label="decision-stream",
        )

    # ------------------------------------------------------------------
    # 入口(watcher 回调,后台线程执行)
    # ------------------------------------------------------------------
    def enqueue(self, prompt: Any) -> None:
        """决策请求入队(后台线程调用安全)。"""
        self.queue.put(prompt)

    def start(self) -> None:
        """启动决策相关轮询(幂等,首启引导后重复调用安全)。"""
        self._queue_poller.start()
        self._stream_poller.start()

    def stop(self) -> None:
        """停止决策相关轮询。"""
        self._queue_poller.stop()
        self._stream_poller.stop()

    # ------------------------------------------------------------------
    # 处理
    # ------------------------------------------------------------------
    def handle_prompt(self, prompt: Any) -> None:
        """处理一个决策请求：ask 询问 / on 自动解析。"""
        config = self.app.config
        mode: str = getattr(config, "decision_assistant", DecisionMode.OFF.value)
        auto: bool = bool(getattr(config, "decision_auto", True))
        self.pending = True
        self.app.set_status(f"检测到 Agent 决策：{prompt.question[:40]}")
        self.app.update_decision_badge()

        alert = DecisionAlert.get_instance(self.app)
        if alert is None:
            logger.warning("决策浮窗未就绪，忽略决策请求")
            return

        if mode == DecisionMode.ASK.value:
            alert.show_prompt(prompt, auto_explain=False)
            self._ask_parse_confirmation(prompt)
        elif mode == DecisionMode.ON.value:
            alert.show_prompt(prompt, auto_explain=True)
            if auto:
                self.start_explain(prompt)
            else:
                self._ask_parse_confirmation(prompt)
        # off 分支不会进入（watcher 未启动）

    def _ask_parse_confirmation(self, prompt: Any) -> None:
        """ask 模式：弹出确认框询问是否解析。"""
        import tkinter.messagebox as mb

        resp: bool = mb.askyesno(
            "DiffGuard 决策助手",
            f"检测到 Agent 需要你决策：\n\n{prompt.question}\n\n"
            f"共 {len(prompt.options)} 个选项。是否让 AI 帮你解析并给出建议？",
            parent=self.app,
        )
        if resp:
            self.start_explain(prompt)

    # ------------------------------------------------------------------
    # AI 解析(流式)
    # ------------------------------------------------------------------
    def start_explain(self, prompt: Any) -> None:
        """在后台线程流式调用 AI 解析。"""
        alert = DecisionAlert.get_instance(self.app)
        if alert is not None:
            alert.set_explaining(True)
        config = self.app.config

        def _run() -> None:
            try:
                for line in explain_decision(prompt, config):
                    self._decision_stream.put(line)
            except Exception as exc:
                logger.exception("决策解析线程异常: {}", exc)
                self._decision_stream.put("#ERROR# 解析线程异常，请查看日志。")

        threading.Thread(target=_run, daemon=True).start()

    def _apply_stream_line(self, line: str) -> None:
        """把一行解析输出增量填充浮窗。"""
        alert = DecisionAlert.get_instance(self.app)
        if alert is not None:
            alert.apply_line(line)
            self.app.set_status("决策解析完成")

    # ------------------------------------------------------------------
    # 决策闭环
    # ------------------------------------------------------------------
    def on_chosen(self, prompt: Any, key: str) -> None:
        """用户点击某个选项后：写桥接反馈 + 决策历史,清除角标。"""
        try:
            setattr(prompt, "user_decision", key)
        except Exception:
            pass
        self.app.set_status(f"已记录你的选择：{key}")
        try:
            chosen_text = ""
            for opt in getattr(prompt, "options", []) or []:
                if getattr(opt, "key", "") == key:
                    chosen_text = getattr(opt, "text", "")
                    break
            if getattr(self.app.config, "agent_bridge", True):
                bridge_store.record_decision_feedback(
                    question=getattr(prompt, "question", ""),
                    chosen=key,
                    chosen_text=chosen_text,
                    recommendation=getattr(prompt, "recommendation", ""),
                    source=getattr(prompt, "source", "Unknown"),
                )
            options_list = [
                {
                    "key": getattr(o, "key", ""),
                    "text": getattr(o, "text", ""),
                    "meaning": getattr(o, "meaning", ""),
                }
                for o in getattr(prompt, "options", []) or []
            ]
            save_decision_record(
                source=getattr(prompt, "source", "Unknown"),
                question=getattr(prompt, "question", ""),
                options=options_list,
                recommendation=getattr(prompt, "recommendation", ""),
                conclusion=getattr(prompt, "conclusion", ""),
                user_decision=key,
                raw_text=getattr(prompt, "raw_text", ""),
            )
        except Exception as exc:
            logger.debug("记录决策反馈失败: {}", exc)
        self.pending = False
        self.app.update_decision_badge()

    # ------------------------------------------------------------------
    # 浮窗入口(前台小窗徽标点击)
    # ------------------------------------------------------------------
    def open_alert(self) -> None:
        """展示当前待决策的浮窗(有待决策时)。"""
        alert = DecisionAlert.get_instance(self.app)
        if alert is None or not self.pending:
            return
        try:
            alert.deiconify()
            alert.lift()
            alert.attributes("-topmost", True)
        except Exception as exc:
            logger.debug("打开决策浮窗失败: {}", exc)

    def on_watcher_stopped(self) -> None:
        """决策监听停止后复位待处理标志。"""
        self.pending = False
