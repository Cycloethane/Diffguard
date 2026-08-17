# -*- coding: utf-8 -*-
"""风险评分模块：基于 diff 解析结果计算 0-100 的量化风险分数。

返回分数与触发因素明细；同时提供"纯色"分带（蓝→绿→黄→橙→红）的颜色
与语义标签映射，供风险进度条组件使用。所有逻辑为本地启发式，
可复现、可单测。
"""

from collections import Counter
from math import log2
from typing import Any

# 风险标记对应的加分（按次计，同一文件同标记只计一次）
FLAG_POINTS: dict[str, int] = {
    "疑似硬编码密钥": 30,
    "配置文件变更": 20,
    "文件删除": 20,
    "依赖变更": 15,
}

# 分带定义：自低到高 蓝→绿→黄→橙→红（纯色，无渐变）
BANDS: tuple[dict[str, Any], ...] = (
    {"lo": 0, "hi": 20, "color": "#3b82f6", "label": "极低"},
    {"lo": 20, "hi": 40, "color": "#22c55e", "label": "低"},
    {"lo": 40, "hi": 60, "color": "#eab308", "label": "中"},
    {"lo": 60, "hi": 80, "color": "#f97316", "label": "高"},
    {"lo": 80, "hi": 101, "color": "#ef4444", "label": "极高"},
)

# 风险等级阈值（与分带一致：蓝/绿=低，黄=中，橙/红=高）
_LOW_THRESHOLD: int = 40
_MEDIUM_THRESHOLD: int = 60


def _band_for(score: int) -> dict[str, Any]:
    """返回分数所属的分带字典（100 归入最高分带）。"""
    for band in BANDS:
        if band["lo"] <= score < band["hi"]:
            return band
    return BANDS[-1]


def score_color(score: int) -> str:
    """返回分数对应的纯色。"""
    return _band_for(score)["color"]


def score_label(score: int) -> str:
    """返回分数对应的语义标签（极低/低/中/高/极高）。"""
    return _band_for(score)["label"]


def clamp(score: int) -> int:
    """将分数限制在 0-100 区间。"""
    return max(0, min(100, score))


def compute_risk_score(files: list[dict[str, Any]]) -> tuple[int, list[str]]:
    """根据解析后的文件列表计算 0-100 风险分数与触发因素明细。

    返回:
        (score, contributions)：score 为 0-100 整数；
        contributions 为可展示的触发因素字符串列表（如"硬编码密钥 ×2 (+60)"）。
    """
    flag_counter: Counter[str] = Counter()
    additions: int = 0
    deletions: int = 0
    risky_files: int = 0

    for info in files:
        flags: set[str] = set(info.get("risk_flags", []))
        is_risky: bool = False
        for flag in flags:
            if flag in FLAG_POINTS:
                flag_counter[flag] += 1
                is_risky = True
        if is_risky:
            risky_files += 1
        additions += int(info.get("additions", 0))
        deletions += int(info.get("deletions", 0))

    contributions: list[str] = []

    # 1. 风险标记加分
    flag_points: int = 0
    for flag, n in sorted(flag_counter.items()):
        pts: int = FLAG_POINTS.get(flag, 0) * n
        if pts:
            flag_points += pts
            contributions.append(f"{flag} ×{n} (+{pts})")

    # 2. 变更规模（对数递减，防止大 diff 刷分）
    size: int = additions + deletions
    size_points: int = min(15, round(2 * log2(1 + size))) if size else 0
    if size_points:
        contributions.append(f"变更规模 {size} 行 (+{size_points})")

    # 3. 风险文件数量
    count_points: int = min(10, risky_files * 2)
    if count_points:
        contributions.append(f"风险文件 ×{risky_files} (+{count_points})")

    # 4. 大量删除（重写倾向，需重点确认）
    rewrite_points: int = 0
    if size > 0:
        ratio: float = deletions / size
        if ratio >= 0.5:
            rewrite_points = min(10, round((ratio - 0.5) * 20))
            if rewrite_points:
                contributions.append(f"删除占比 {ratio:.0%} (+{rewrite_points})")

    score = clamp(flag_points + size_points + count_points + rewrite_points)
    return score, contributions


def score_to_level(score: int) -> str:
    """将 0-100 分数映射为三档风险等级（low/medium/high）。"""
    if score < _LOW_THRESHOLD:
        return "low"
    if score < _MEDIUM_THRESHOLD:
        return "medium"
    return "high"


def score_text(text: str, _config: Any = None) -> dict[str, Any]:
    """对任意文本做本地风险评分（不调用 AI）。

    适用场景：MCP scan_risk 工具、OpenCode 集成快速检查。
    识别：疑似硬编码密钥、危险命令、危险路径、配置文件路径等。

    返回 dict：score（0-100）、level（low/medium/high）、
    findings（命中项列表）、label（语义标签）。
    """
    import re

    if not text:
        return {"score": 0, "level": "low", "label": "极低", "findings": []}

    findings: list[str] = []
    score = 0
    lower = text.lower()

    # 疑似硬编码密钥（赋值式）
    secret_re = re.compile(
        r"(password|passwd|secret|token|api_key|apikey|access_key|client_secret)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
        re.IGNORECASE,
    )
    if secret_re.search(text):
        score += 40
        findings.append("疑似硬编码密钥")

    # 危险命令
    danger_cmds = {
        "rm -rf /": "删除根目录",
        "rm -rf ~": "删除用户目录",
        "git push --force": "强制推送",
        "format c:": "格式化 C 盘",
        "format /": "格式化分区",
        "rd /s /q": "递归删除",
        "del /f /s /q": "强制递归删除",
        "shutdown": "关机命令",
        ":(){ :|:& };:": "fork 炸弹",
        "chmod 777": "放开全部权限",
    }
    for cmd, label in danger_cmds.items():
        if cmd in lower:
            score += 25
            findings.append(f"危险命令:{label}")

    # 危险/敏感路径
    sensitive_path = re.compile(
        r"(\.env\b|\.aws/|\.ssh/|id_rsa|id_ed25519|credentials|\.kube/config|"
        r"C:\\Windows\\System32|/etc/passwd|/etc/shadow)",
        re.IGNORECASE,
    )
    if sensitive_path.search(text):
        score += 20
        findings.append("敏感路径")

    # 系统目录写入
    sys_write = re.compile(
        r"(C:\\(Windows|Program Files|ProgramData)|/usr|/etc|/bin)",
        re.IGNORECASE,
    )
    if sys_write.search(text):
        score += 15
        findings.append("系统目录")

    score = clamp(score)
    return {
        "score": score,
        "level": score_to_level(score),
        "label": score_label(score),
        "findings": findings,
    }