# -*- coding: utf-8 -*-
"""通用 queue→Tk after 轮询器。

把"后台线程只 put 队列、主线程 after 轮询排空"的六处重复模式收敛为一个
可复用组件:

    - start() 幂等:已在运行时直接返回,天然避免旧代码中"重启监听后
      再次 after 调度导致轮询循环双跑"的 bug;
    - stop() 取消挂起的 after 回调,空转轮询随之终止;
    - on_item 可调用 stop() 提前终止(如审查流收到 done);
    - pre_poll / on_batch 支持排空前后的钩子(刷新在线状态、批量收尾)。
"""

import queue
from typing import Any, Callable, Optional


class QueuePoller:
    """把 queue.Queue 的内容按 after 周期排空并逐项回调。

    属性:
        running: 是否处于轮询中。
    """

    def __init__(
        self,
        widget: Any,
        source: "queue.Queue[Any]",
        on_item: Callable[[Any], None],
        interval_ms: int = 200,
        pre_poll: Optional[Callable[[], None]] = None,
        on_batch: Optional[Callable[[list], None]] = None,
        label: str = "poller",
    ) -> None:
        self._widget = widget
        self._queue = source
        self._on_item = on_item
        self._interval_ms = interval_ms
        self._pre_poll = pre_poll
        self._on_batch = on_batch
        self._label = label
        self._running: bool = False
        self._after_id: Optional[str] = None

    @property
    def running(self) -> bool:
        """是否处于轮询中。"""
        return self._running

    def start(self) -> None:
        """启动轮询;已在运行时为幂等空操作(防重复调度)。"""
        if self._running:
            return
        self._running = True
        self._tick()

    def stop(self) -> None:
        """停止轮询并取消挂起的回调。"""
        self._running = False
        if self._after_id is not None:
            try:
                self._widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    # ------------------------------------------------------------------
    def _tick(self) -> None:
        if not self._running:
            return
        if self._pre_poll is not None:
            try:
                self._pre_poll()
            except Exception:
                pass
        items: list[Any] = []
        while True:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                break
        for item in items:
            if not self._running:  # on_item 中可能已 stop
                break
            try:
                self._on_item(item)
            except Exception as exc:
                from loguru import logger

                logger.debug("轮询器 {} 处理条目异常: {}", self._label, exc)
        if self._running and self._on_batch is not None and items:
            try:
                self._on_batch(items)
            except Exception as exc:
                from loguru import logger

                logger.debug("轮询器 {} 批处理异常: {}", self._label, exc)
        if self._running:
            self._after_id = self._widget.after(self._interval_ms, self._tick)
