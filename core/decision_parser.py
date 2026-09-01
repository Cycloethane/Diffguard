# -*- coding: utf-8 -*-
"""决策解析层：从原始文本中识别"需要用户决策"的候选并提取问题与选项。

判定逻辑（证据判定，减少误报）：
    - 必须同时满足"决策疑问句"与"选项列表"两类证据，才视为一次有效决策。
    - 选项列表支持 A/B/C、1./2./3.、中文顿号分隔等形式。
    - 剪贴板通道按整段文本判定；UIA 通道可传入多段控件文本拼接。

本模块为纯工具类、无状态，仅做本地规则解析，不做 AI 调用。
"""

import re
from typing import List, Optional

from core.agent_sources import DECISION_SOURCE_ORDER
from models.decision_prompt import DecisionOption, DecisionPrompt

# ----------------------------------------------------------------------
# 决策疑问句特征词（命中任一即视为"在向用户要决策"）
# ----------------------------------------------------------------------
_QUESTION_MARKERS: tuple[str, ...] = (
    "请选择",
    "请选择以下",
    "请决定",
    "选哪个",
    "选择其中一个",
    "选择其中一种",
    "选择一种",
    "你希望",
    "你想要",
    "要不要",
    "是否采用",
    "是否使用",
    "是否继续",
    "请确认",
    "还是",
    "which",
    "please choose",
    "please select",
    "choose one",
    "select one",
    "what do you want",
    "would you like",
    "do you want",
    "or?",
    "选一个",
    "需要你决策",
    "需要你决定",
    "请指示",
)

# ----------------------------------------------------------------------
# 选项列表证据：行首标记（用于识别列表项）
# ----------------------------------------------------------------------
_OPTION_LINE_RE = re.compile(
    r"^\s*(?:[\(（]?[A-Za-z0-9一二三四五六七八九十]+[\)）]?[\.、:：)]"
    r"|\*|\-)\s+(.+)$"
)
# 行内"或"分隔（如 "A 或 B 或 C"）
_OR_SPLIT_RE = re.compile(r"\s+或\s+|\s+or\s+", re.IGNORECASE)
# 英文选项行：A) xxx / a. xxx / 1. xxx / [x] xxx
# 英文/数字选项行：1. xxx / A) xxx / [1] xxx / - xxx / (x) xxx
_EN_LINE_RE = re.compile(
    r"^\s*(?:(\d{1,2}|[A-Za-z])[\.、:：)）]"
    r"|\[([A-Za-z0-9]{1,3})\]"
    r"|\(([A-Za-z0-9]{1,3})\)"
    r"|-)\s+(.+)$"
)
# 中文选项行：①③ / 第一、 等较少见，暂以 汉字数字/顿号 为主
_CN_LINE_RE = re.compile(r"^\s*([一二三四五六七八九十]+)[、.)．]\s*(.+)$")
# 行内编号选项： "1、Windows 本机 2、远程服务器 3、Docker 容器"
_INLINE_ITEM_RE = re.compile(
    r"(?:^|[^\w])([1-9Ａ-ＺA-Z]|[一二三四五六七八九十])\s*[、.．:：)）]\s*"
)

# 单个选项内部关键词（命中说明该行更像"说明"而非新选项）
_EXPLANATION_WORDS: tuple[str, ...] = (
    "特点",
    "优点",
    "缺点",
    "适用",
    "推荐",
    "默认",
    "例如",
    "比如",
    "说明",
    "注意",
    "风险",
)

# 疑似决策但实际为"普通问句"的豁免词（降低误报）
_NON_DECISION_MARKERS: tuple[str, ...] = (
    "你是不是",
    "你是否需要帮助",
    "还有什么",
    "还有什么可以",
    "还有什么问题",
    "还有别",
    "其他问题",
    "其它问题",
    "还有什么需要",
)

# 单条决策文本长度上限（防止超大剪贴板拖垮判定）
_MAX_TEXT_LEN: int = 6000


def _contains_question_marker(text: str) -> bool:
    """是否命中决策疑问句特征词。"""
    lower: str = text.lower()
    return any(m in lower for m in _QUESTION_MARKERS)


def _contains_non_decision(text: str) -> bool:
    """是否命中普通寒暄/继续询问（豁免，避免误报）。"""
    return any(m in text for m in _NON_DECISION_MARKERS)


def is_likely_decision(text: str) -> bool:
    """整体证据判定：疑问特征 + 选项证据 同时满足才视为候选。"""
    t: str = (text or "").strip()
    if not t:
        return False
    if len(t) > _MAX_TEXT_LEN:
        t = t[:_MAX_TEXT_LEN]
    if not _contains_question_marker(t):
        return False
    if _contains_non_decision(t):
        return False
    return (
        _count_option_lines(t) >= 2
        or _count_inline_items(t) >= 2
        or _count_or_items(t) >= 2
        or _count_dunhao_items(t) >= 2
    )


def _count_option_lines(text: str) -> int:
    """统计"列表行"数量（A)/1./- 等开头）。"""
    count: int = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if _EN_LINE_RE.match(line) or _CN_LINE_RE.match(line):
            count += 1
    return count


def _count_or_items(text: str) -> int:
    """统计"或/or"分隔出的候选项数量（排除问题句残留片段）。"""
    parts: List[str] = _OR_SPLIT_RE.split(text)
    meaningful: int = 0
    for p in parts:
        p = p.strip().rstrip("？?。.")
        if len(p) < 2 or _contains_question_marker(p):
            continue
        meaningful += 1
    return meaningful


def _count_inline_items(text: str) -> int:
    """统计行内编号选项（1、xx 2、xx）数量。"""
    return len(_INLINE_ITEM_RE.findall(text))


def _count_dunhao_items(text: str) -> int:
    """统计顿号/逗号分隔出的候选项数量（剥离问题句前缀后）。"""
    total: int = 0
    for line in text.splitlines():
        if "、" not in line and "，" not in line and "," not in line:
            continue
        body: str = line
        colon = max(body.rfind("："), body.rfind(":"))
        if colon >= 0:
            body = body[colon + 1 :]
        segs: List[str] = re.split(r"[、，,]", body)
        for s in segs:
            s = s.strip().rstrip("？?。.")
            if len(s) >= 2 and not _contains_question_marker(s):
                total += 1
    return total


def extract_options(text: str) -> List[DecisionOption]:
    """从文本中提取选项列表。

    策略：
        1. 优先按"列表行"提取（A)/1./- 开头），保留行首标记。
        2. 若无列表行，退化为按"或/or"切分，生成无标记选项。
    返回至少包含 1 个元素；不足 1 个时返回空列表。
    """
    options: List[DecisionOption] = []
    seen: set[str] = set()

    # 策略 1：列表行
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _EN_LINE_RE.match(line)
        if not m:
            m = _CN_LINE_RE.match(line)
        if not m:
            continue
        # 新正则的 key/text 组位置：
        #   _EN_LINE_RE: group1(数字/字母) 或 group2([x]) 或 group3((x)) 或 -，group4=文本
        #   _CN_LINE_RE: group1(汉字数字)，group2=文本
        if m.re is _EN_LINE_RE:
            key = (m.group(1) or m.group(2) or m.group(3) or "").strip()
            rest = (m.group(4) or "").strip()
        else:
            key = m.group(1).strip()
            rest = m.group(2).strip()
        if not rest:
            continue
        # 跳过"说明性"选项文本（如 "默认选择："）
        if any(w in rest for w in _EXPLANATION_WORDS) and not any(
            c.isalnum() for c in rest[:6]
        ):
            continue
        dedup = f"{key}|{rest}".lower()
        if dedup in seen:
            continue
        seen.add(dedup)
        options.append(DecisionOption(key=key, text=rest))

    if len(options) >= 2:
        return options

    # 策略 3：行内编号选项（如 "1、Windows 本机 2、远程服务器 3、Docker"）
    options.clear()
    for line in text.splitlines():
        for m in _INLINE_ITEM_RE.finditer(line):
            start: int = m.end()
            nxt = _INLINE_ITEM_RE.search(line, start)
            seg: str = line[start : nxt.start() if nxt else len(line)]
            seg = seg.strip().strip("，,。.；;").strip()
            if len(seg) < 2:
                continue
            dedup = f"{m.group(1)}|{seg}".lower()
            if dedup in seen:
                continue
            seen.add(dedup)
            options.append(DecisionOption(key=m.group(1).strip(), text=seg))
        if len(options) >= 2:
            break

    if len(options) >= 2:
        return options

    # 策略 3.5：顿号分隔候选项（如 "请选择语言：Python、JavaScript、Rust 或 Go"）
    options.clear()
    for line in text.splitlines():
        # 仅对含顿号/逗号的行尝试；避免把普通描述句切碎
        if "、" not in line and "，" not in line and "," not in line:
            continue
        # 剥离问题句前缀（取最后一个冒号后），避免问题句残留被当选项
        body: str = line
        colon = max(body.rfind("："), body.rfind(":"))
        if colon >= 0:
            body = body[colon + 1 :]
        segs: List[str] = re.split(r"[、，,]", body)
        for s in segs:
            s = s.strip().strip("()[]（）【】").rstrip("？?。.")
            if len(s) < 2 or _contains_question_marker(s):
                continue
            # 去掉行首编号残留
            s = re.sub(r"^[\dA-Za-z一二三四五六七八九十]+[\.、:：)）]\s*", "", s).strip()
            if len(s) < 2:
                continue
            dedup = s.lower()
            if dedup in seen:
                continue
            seen.add(dedup)
            options.append(DecisionOption(key=str(len(options) + 1), text=s))
        if len(options) >= 2:
            break
    if len(options) >= 2:
        return options

    # 策略 2：或/or 切分（仅当列表行/行内编号都不足时）
    options.clear()
    parts: List[str] = _OR_SPLIT_RE.split(text)
    for i, p in enumerate(parts):
        p = p.strip().strip("()[]（）【】").strip()
        p = re.sub(r"^[\dA-Za-z]+[\.、:：)）]\s*", "", p).strip()
        p = p.rstrip("？?。.")
        if len(p) < 2:
            continue
        # 片段若含问题特征词，说明是问题句残留（如 "你希望用 A"），跳过
        if _contains_question_marker(p):
            continue
        dedup = p.lower()
        if dedup in seen:
            continue
        seen.add(dedup)
        options.append(DecisionOption(key=str(i + 1), text=p))

    return options


def parse(
    texts: List[str],
    window_title: str = "",
    window_handle: Optional[int] = None,
) -> Optional[DecisionPrompt]:
    """解析文本列表为 DecisionPrompt；不满足证据判定时返回 None。

    参数:
        texts: 采集到的文本列表（剪贴板通道传 [raw_text]；UIA 通道传控件文本）。
        window_title: 窗口标题（剪贴板通道传 "Clipboard"）。
        window_handle: 窗口句柄（UIA 通道可用，剪贴板传 None）。
    """
    raw: str = "\n".join(texts).strip()
    if not raw:
        return None
    if len(raw) > _MAX_TEXT_LEN:
        raw = raw[:_MAX_TEXT_LEN]

    if not is_likely_decision(raw):
        return None

    options: List[DecisionOption] = extract_options(raw)
    if len(options) < 2:
        return None

    question: str = _extract_question(raw, options)
    return DecisionPrompt(
        question=question,
        options=options,
        source=_detect_source(window_title, raw),
        raw_text=raw,
        window_handle=window_handle,
    )


def _extract_question(text: str, options: List[DecisionOption]) -> str:
    """提取问题句：优先取第一个选项行之前的文本，去掉尾部标点。"""
    lines: List[str] = text.splitlines()
    # 找到第一个选项行的行号
    first_idx: Optional[int] = None
    for i, line in enumerate(lines):
        if _EN_LINE_RE.match(line.strip()) or _CN_LINE_RE.match(line.strip()):
            first_idx = i
            break
    if first_idx is not None:
        q: str = "\n".join(lines[:first_idx]).strip()
    else:
        # 无列表行：若为行内编号，取第一个编号前的文本；否则取"或"之前
        m = _INLINE_ITEM_RE.search(text)
        q = text[: m.start(1)].strip() if m else _OR_SPLIT_RE.split(text)[0].strip()
    q = q.strip(" \t\r\n：:，,。.？?")
    # 去掉 "A)" 之类残留
    q = re.sub(r"^[\[\(]?[A-Za-z0-9]+[\]\)]?[\.、:：)）]\s*", "", q).strip()
    if not q:
        q = "Agent 请求你做出一个选择"
    return q[:200]


def _detect_source(window_title: str, text: str) -> str:
    """来源识别：标题或正文命中来源关键词即归属该来源。"""
    lower: str = f"{window_title}\n{text}".lower()
    for source in DECISION_SOURCE_ORDER:
        if source.lower() in lower:
            return source
    if "clipboard" in window_title.lower():
        return "Clipboard"
    return "Unknown"
