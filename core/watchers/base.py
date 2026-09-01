# -*- coding: utf-8 -*-
"""监视线程公共骨架:生命周期、UIA/COM 会话、去重缓存、控件文本采集。

此前 ClipboardWatcher / PermissionWatcher / DecisionWatcher 三处维护
同构的线程骨架(约 60% 重复),且降级语义不一致。收敛后:

    - 子类只实现 tick()(每轮做什么)与通道私有逻辑;
    - start() 统一为"依赖探测 + 起线程":UIA 探测失败仅置
      uia_available=False,线程照常启动,通道自行禁用(降级不死线程);
    - UIA/COM 线程会话由 uia_thread_session 统一管理
      (UIAutomationInitializerInThread + CoInitialize,退出反向清理)。

回调在后台线程中执行,调用方需自行切回 GUI 主线程。
"""

import os
import threading
import time
from contextlib import contextmanager, nullcontext
from typing import Iterator, Optional

from loguru import logger

# 去重缓存预算与条目存活时间
SEEN_BUDGET: int = 256
SEEN_TTL: float = 3600.0

# 控件文本采集默认参数
DEFAULT_CONTROL_TYPES: tuple[str, ...] = (
    "TextControl",
    "ButtonControl",
    "EditControl",
    "DocumentControl",
    "HyperlinkControl",
    "ListItemControl",
    "CheckBoxControl",
    "RadioButtonControl",
)
DEFAULT_MAX_CONTROLS: int = 200
DEFAULT_MIN_TEXT_LEN: int = 8
DEFAULT_MAX_DEPTH: int = 6


@contextmanager
def uia_thread_session(ua: Optional[object], com: Optional[object]) -> Iterator[None]:
    """UIA 线程会话:初始化器上下文 + COM 初始化,退出时反向清理。

    ua/com 为 None(UIA 不可用)时为空操作,调用方循环照常执行。
    COM 必须在使用它的线程内初始化,故由本会话在监听线程内完成。
    """
    initializer = None
    if ua is not None:
        try:
            initializer = ua.UIAutomationInitializerInThread(True)
        except Exception as exc:
            logger.debug("创建 UIA 线程初始化器失败: {}", exc)
    ctx = initializer if initializer is not None else nullcontext()
    with ctx:
        if com is not None:
            com.CoInitialize()
        try:
            yield
        finally:
            if com is not None:
                try:
                    com.CoUninitialize()
                except Exception:
                    pass


def iter_controls(control: object, max_depth: int = DEFAULT_MAX_DEPTH) -> Iterator[object]:
    """深度优先遍历控件子树(带深度限制),供决策回写查找按钮。"""
    stack: list[tuple[object, int]] = [(control, 0)]
    while stack:
        node, depth = stack.pop()
        yield node
        if depth < max_depth:
            try:
                children = node.GetChildren()
            except Exception:
                children = []
            for child in children:
                stack.append((child, depth + 1))


def collect_control_texts(
    control: object,
    texts: list[str],
    depth: int = 0,
    control_types: tuple[str, ...] = DEFAULT_CONTROL_TYPES,
    max_controls: int = DEFAULT_MAX_CONTROLS,
    min_text_len: int = DEFAULT_MIN_TEXT_LEN,
) -> None:
    """递归收集控件文本:仅采集指定类型、限长、去重。"""
    if len(texts) >= max_controls:
        return
    name: str = getattr(control, "Name", "") or ""
    ctype: str = getattr(control, "ControlTypeName", "") or ""
    if name and ctype in control_types and len(name.strip()) >= min_text_len:
        if name not in texts:
            texts.append(name)
    if depth >= DEFAULT_MAX_DEPTH or len(texts) >= max_controls:
        return
    try:
        children = control.GetChildren()
    except Exception:
        children = []
    for child in children:
        collect_control_texts(child, texts, depth + 1, control_types, max_controls, min_text_len)


class BaseWatcher(threading.Thread):
    """周期轮询的后台守护线程骨架。

    子类契约:
        tick()          每轮轮询逻辑(异常由骨架捕获并记日志)。
        _try_init_uia() 可选:UIA 依赖探测(置 self._ua/_com)。
        seen()/prune_seen()  去重缓存。

    属性:
        interval: 轮询间隔(秒)。
        uia_available: UIA 依赖是否探测成功(供 UI 状态展示)。
    """

    def __init__(self, interval: float, name: str) -> None:
        super().__init__(daemon=True)
        self.interval: float = interval
        self.name = name
        self._stop_event = threading.Event()
        self._seen: dict = {}
        self._ua: Optional[object] = None
        self._com: Optional[object] = None

    # ------------------------------------------------------------------
    # 依赖探测
    # ------------------------------------------------------------------
    @property
    def uia_available(self) -> bool:
        """UIA 依赖是否可用。"""
        return self._ua is not None

    def _try_init_uia(self) -> bool:
        """探测 uiautomation/pywin32;成功置依赖并返回 True,失败返回 False。

        降级语义:失败仅代表 UIA 通道禁用,不影响线程启动与其余通道。
        """
        try:
            import uiautomation as ua  # type: ignore
            import pythoncom  # type: ignore

            self._ua = ua
            self._com = pythoncom
            logger.info("{} UIA 通道已初始化", self.name)
            return True
        except Exception as exc:
            self._ua = None
            self._com = None
            logger.warning("{} UIA 通道不可用: {}", self.name, exc)
            return False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def run(self) -> None:
        logger.info("{} 线程启动，间隔 {} 秒", self.name, self.interval)
        with uia_thread_session(self._ua, self._com):
            while not self._stop_event.is_set():
                try:
                    self.tick()
                except Exception as exc:
                    logger.debug("{} 轮询异常: {}", self.name, exc)
                self._stop_event.wait(self.interval)
        logger.info("{} 线程已停止", self.name)

    def tick(self) -> None:
        """每轮轮询逻辑,子类实现。"""
        raise NotImplementedError

    def stop(self) -> None:
        """请求停止监听线程。"""
        logger.info("请求停止 {} 线程", self.name)
        self._stop_event.set()

    # ------------------------------------------------------------------
    # 去重缓存
    # ------------------------------------------------------------------
    def seen(self, key) -> bool:
        """新条目记录并返回 True;已存在返回 False。"""
        if key in self._seen:
            return False
        self._seen[key] = time.time()
        return True

    def prune_seen(
        self, budget: int = SEEN_BUDGET, ttl: float = SEEN_TTL
    ) -> None:
        """清理去重缓存,防止无限增长。"""
        if len(self._seen) > budget:
            now: float = time.time()
            self._seen = {k: v for k, v in self._seen.items() if now - v < ttl}

    # ------------------------------------------------------------------
    # UIA 窗口遍历
    # ------------------------------------------------------------------
    def iter_windows(self) -> Iterator[object]:
        """遍历顶层窗口(排除本进程自身),UIA 不可用时为空迭代。

        排除自身窗口的原因:权限/决策浮窗自身的按钮文本恰好满足
        证据判定,不排除会自我识别、循环弹窗。
        """
        if self._ua is None:
            return
        root: Optional[object] = self._ua.GetRootControl()
        if root is None:
            return
        my_pid: int = os.getpid()
        for win in root.GetChildren():
            try:
                if getattr(win, "ProcessId", None) == my_pid:
                    continue
            except Exception:
                pass
            yield win
