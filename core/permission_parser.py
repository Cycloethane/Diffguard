# -*- coding: utf-8 -*-
"""权限解析层：把感知层采集的窗口/剪贴板文本解析为 PermissionPrompt。

纯工具类、无状态。来源识别、类型推断、目标提取、选项提取、内容证据判定
全部收敛在此（哨兵层只负责"发现候选文本"，避免逻辑两处实现）。

主要入口:
    PermissionParser().parse(window_texts, window_title) -> PermissionPrompt
    PermissionParser().is_likely_permission_prompt(text) -> bool
"""

import os
import re
from typing import List, Optional

from models.permission_prompt import PermissionPrompt, PromptAction, PromptType

# ----------------------------------------------------------------------
# 来源特征词（在"标题+正文"中累计命中 2 个及以上才判定位来源）
# ----------------------------------------------------------------------
_SOURCE_MARKERS: dict[str, tuple[str, ...]] = {
    "OpenCode": ("opencode", "permission required", "allow once", "allow always", "reject"),
    "Cursor": ("cursor", "composer", "auto-review"),
    "Cline": ("cline", "api request", "terminal command"),
}

# ----------------------------------------------------------------------
# 内容证据词（用于减少误报）
# ----------------------------------------------------------------------
_OPERATION_EVIDENCE: dict[str, tuple[str, ...]] = {
    "file": ("directory", "folder", "file", "path", "目录", "文件", "文件夹", "路径"),
    "command": ("command", "bash", "shell", "execute", "run", "命令", "执行", "运行"),
    "network": ("fetch", "url", "http", "web", "request", "请求", "访问网址", "通知"),
    "delete": ("delete", "remove", "删除", "移除"),
}

_OPTION_ALLOW: tuple[str, ...] = ("allow", "permit", "grant", "允许", "批准")
_OPTION_SCOPE: tuple[str, ...] = ("once", "always", "本次", "总是", "永久")
_OPTION_DENY: tuple[str, ...] = ("reject", "deny", "refuse", "拒绝", "否")

# 选项文本提取正则（匹配常见按钮文案，去重后保留原始文本）
_OPTION_PATTERNS: tuple[str, ...] = (
    r"allow\s+once",
    r"(?:allow|always)\s+always|always\s+allow",
    r"reject",
    r"deny",
    r"confirm",
    r"cancel",
    r"仅本次允许|允许一次",
    r"总是允许|永久允许",
    r"拒绝",
    r"确认",
    r"取消",
)

# ----------------------------------------------------------------------
# 目标提取正则
# ----------------------------------------------------------------------
_PATH_RE = re.compile(
    r"(?:directory|folder|file|path|文件|目录|文件夹|路径)\s*[:-]?\s*[\"'`]?"
    r"([~A-Za-z]:[\\/][^ \t\"'`]+|[~/.\w][^ \t\"'`]*)",
    re.IGNORECASE,
)
_COMMAND_RE = re.compile(
    r"(?:command|bash|shell|命令|执行)\s*[:：]?\s*[\"'`]?([^\n\r\"'`]+)",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"(https?://[^\s\"'`]+)", re.IGNORECASE)
_IP_OR_HOST_RE = re.compile(r"\b(?:\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?|[a-zA-Z0-9-]+\.[a-zA-Z]{2,})\b")


class PermissionParser:
    """权限文本解析器：将原始文本转换为结构化 PermissionPrompt。"""

    # ------------------------------------------------------------------
    # 证据判定
    # ------------------------------------------------------------------
    @staticmethod
    def has_operation_evidence(text: str) -> bool:
        """是否包含'操作证据'（文件/命令/网络/删除 至少一类）。"""
        lower: str = text.lower()
        return any(
            any(key in lower for key in keys) for keys in _OPERATION_EVIDENCE.values()
        )

    @staticmethod
    def has_option_evidence(text: str) -> bool:
        """是否包含'选项证据'（允许/范围/拒绝 三组中至少两类）。"""
        lower: str = text.lower()
        present: int = 0
        if any(k in lower for k in _OPTION_ALLOW):
            present += 1
        if any(k in lower for k in _OPTION_SCOPE):
            present += 1
        if any(k in lower for k in _OPTION_DENY):
            present += 1
        return present >= 2

    @classmethod
    def is_likely_permission_prompt(cls, text: str) -> bool:
        """整体证据判定：操作证据 + 选项证据 同时满足才视为候选。"""
        return cls.has_operation_evidence(text) and cls.has_option_evidence(text)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    @classmethod
    def parse(
        cls,
        window_texts: List[str],
        window_title: str = "",
        window_handle: Optional[int] = None,
    ) -> PermissionPrompt:
        """解析文本列表与窗口标题，返回 PermissionPrompt。

        参数:
            window_texts: 采集到的控件文本列表（剪贴板通道可传 [raw_text]）。
            window_title: 窗口标题（剪贴板通道可传 "Clipboard"）。
            window_handle: 窗口句柄（UIA 通道可用，剪贴板传 None）。
        """
        raw_text: str = "\n".join(window_texts).strip()
        full: str = f"{window_title}\n{raw_text}"

        prompt: PermissionPrompt = PermissionPrompt(
            source=cls._detect_source(window_title, raw_text),
            prompt_type=cls.infer_prompt_type(full),
            action=PromptAction.UNKNOWN,
            target="unknown",
            options=cls.extract_options(raw_text),
            raw_text=raw_text,
            window_handle=window_handle,
        )
        prompt.action = cls.infer_action(full, prompt.prompt_type)
        prompt.target = cls.extract_target(
            full, prompt.prompt_type, prompt.action
        )
        if prompt.prompt_type == PromptType.FILE_ACCESS and prompt.target != "unknown":
            prompt.target_expanded = cls.expand_path(prompt.target)
        return prompt

    # ------------------------------------------------------------------
    # 来源识别
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_source(window_title: str, text: str) -> str:
        lower: str = f"{window_title}\n{text}".lower()
        best: str = "Unknown"
        best_hits: int = 0
        for source, markers in _SOURCE_MARKERS.items():
            hits: int = sum(1 for m in markers if m in lower)
            if hits > best_hits:
                best, best_hits = source, hits
        # 标题直接命中来源名也算强信号
        title_lower: str = window_title.lower()
        for source in _SOURCE_MARKERS:
            if source.lower() in title_lower:
                return source
        return best if best_hits >= 2 else "Unknown"

    # ------------------------------------------------------------------
    # 类型 / 动作推断
    # ------------------------------------------------------------------
    @staticmethod
    def infer_prompt_type(text: str) -> PromptType:
        lower: str = text.lower()
        if any(k in lower for k in ("command", "bash", "shell", "execute", "run", "命令", "执行", "运行")):
            return PromptType.COMMAND_EXEC
        if any(k in lower for k in ("http", "url", "fetch", "web", "请求", "访问网址")):
            return PromptType.NETWORK_FETCH
        if any(k in lower for k in ("config", "setting", "配置", "设置")):
            return PromptType.CONFIG_CHANGE
        if any(k in lower for k in ("directory", "file", "path", "目录", "文件", "文件夹")):
            return PromptType.FILE_ACCESS
        return PromptType.UNKNOWN

    @staticmethod
    def infer_action(text: str, prompt_type: PromptType) -> PromptAction:
        lower: str = text.lower()
        if any(k in lower for k in ("delete", "remove", "删除", "移除")):
            return PromptAction.DELETE
        if any(k in lower for k in ("write", "modify", "create", "写入", "修改", "创建")):
            return PromptAction.WRITE
        if any(k in lower for k in ("execute", "run", "执行", "运行")):
            return PromptAction.EXECUTE
        if any(k in lower for k in ("fetch", "request", "请求")):
            return PromptAction.FETCH
        if prompt_type == PromptType.FILE_ACCESS:
            return PromptAction.READ
        return PromptAction.UNKNOWN

    # ------------------------------------------------------------------
    # 目标提取
    # ------------------------------------------------------------------
    @staticmethod
    def extract_options(text: str) -> List[str]:
        """从按钮/选项文本中提取选项（去重、保留原始）。"""
        found: List[str] = []
        lower: str = text.lower()
        for pattern in _OPTION_PATTERNS:
            m: Optional[re.Match[str]] = re.search(pattern, lower)
            if m and m.group(0) not in found:
                found.append(m.group(0))
        return found

    @classmethod
    def extract_target(
        cls, text: str, prompt_type: PromptType, action: PromptAction
    ) -> str:
        """按类型提取目标（路径/命令/URL/IP）。提取不到返回 "unknown"。"""
        if prompt_type == PromptType.FILE_ACCESS:
            m: Optional[re.Match[str]] = _PATH_RE.search(text)
            return m.group(1).strip().strip("\"'`") if m else "unknown"
        if prompt_type == PromptType.COMMAND_EXEC:
            m = _COMMAND_RE.search(text)
            return m.group(1).strip().strip("\"'`") if m else "unknown"
        if prompt_type == PromptType.NETWORK_FETCH:
            m = _URL_RE.search(text)
            if m:
                return m.group(1)
            m = _IP_OR_HOST_RE.search(text)
            return m.group(0) if m else "unknown"
        return text[:120] if text.strip() else "unknown"

    # ------------------------------------------------------------------
    # 路径展开
    # ------------------------------------------------------------------
    @staticmethod
    def expand_path(path: str) -> str:
        """把 ~ 展开为用户目录，相对路径转为绝对路径。

        保留原始路径为 target，展开结果作为 target_expanded。
        """
        p: str = path.strip().strip("\"'`")
        if not p:
            return ""
        try:
            if p.startswith("~"):
                p = os.path.expanduser(p)
            else:
                p = os.path.abspath(p)
        except (OSError, ValueError):
            return ""
        return p