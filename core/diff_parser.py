# -*- coding: utf-8 -*-
"""Diff 解析模块：使用 unidiff 解析 git diff 文本，并应用本地风险规则。

将 diff 解析为文件级结构列表，每个文件包含路径、变更类型、增删行数、
hunk 代码片段与风险标记，供 GUI 展示与 AI 审查使用。
"""

import re
from typing import Any, Optional

from loguru import logger
from unidiff import PatchSet

from core.risk_score import compute_risk_score, score_to_level

# 疑似硬编码密钥的正则
_SECRET_PATTERN: re.Pattern[str] = re.compile(
    r"(password|secret|token|api_key|apikey|access_key)\s*[:=]", re.IGNORECASE
)
# 敏感文件名规则（小写匹配）
_SENSITIVE_PATH_PARTS: tuple[str, ...] = (".env", "config")
_DEPENDENCY_PATHS: tuple[str, ...] = ("requirements.txt", "package.json")

# 各风险标记对应的严重级别
_HIGH_FLAGS: frozenset[str] = frozenset({"文件删除", "配置文件变更", "疑似硬编码密钥"})
_MEDIUM_FLAGS: frozenset[str] = frozenset({"依赖变更"})

_CHANGE_TYPES: tuple[str, ...] = ("added", "modified", "deleted", "renamed")


def _detect_risk_flags(file_path: str, change_type: str, hunks_text: str) -> list[str]:
    """根据文件路径、变更类型与内容应用风险规则。"""
    flags: list[str] = []
    lower_path: str = file_path.lower()

    if change_type == "deleted":
        flags.append("文件删除")

    if any(part in lower_path for part in _SENSITIVE_PATH_PARTS):
        flags.append("配置文件变更")

    if any(part in lower_path for part in _DEPENDENCY_PATHS):
        flags.append("依赖变更")

    if _SECRET_PATTERN.search(hunks_text):
        flags.append("疑似硬编码密钥")

    return flags


def parse_diff(diff_text: str) -> list[dict[str, Any]]:
    """解析 git diff 文本，返回文件级变更信息列表。

    优先使用 unidiff 严格解析；当 diff 不完整（hunk 计数不符、被截断）导致
    严格解析失败时，自动回退到行级容错解析，尽量提取能识别的文件与行，
    避免界面"无反应"。
    """
    files, _ = parse_diff_with_status(diff_text)
    return files


def parse_diff_with_status(
    diff_text: str,
) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    """解析 diff 并返回 (文件列表, 解析状态)。

    状态字典:
        strict: 是否由 unidiff 严格解析成功。
        lenient: 是否使用了容错解析（diff 不完整/被截断）。
    """
    text: str = _normalize_diff(diff_text)
    status: dict[str, bool] = {"strict": True, "lenient": False}
    try:
        files: list[dict[str, Any]] = _parse_strict(text)
        if files:
            return files, status
    except Exception as exc:
        logger.warning("unidiff 严格解析失败，尝试容错解析: {}", exc)
        status["strict"] = False

    if "diff --git" in text:
        status["strict"] = False
        status["lenient"] = True
        logger.info("使用容错解析（diff 可能不完整）")
        return _parse_lenient(text), status

    status["strict"] = False
    logger.warning("diff 中未识别到变更标记，无法解析")
    return [], status


def _normalize_diff(diff_text: str) -> str:
    """去除 diff 文本前导的统一缩进。

    从聊天窗口 / 代码块 / 富文本复制出的 diff 常带整体缩进。仅当所有结构性
    行缩进一致且大于 0 时才剥离（否则文本可能被误改，交由容错解析处理）。
    """
    lines: list[str] = diff_text.splitlines()
    if not lines:
        return diff_text

    indent_counts: list[int] = []
    for raw in lines:
        stripped: str = raw.lstrip(" \t")
        if not stripped:
            continue
        if stripped.startswith(("diff --git", "--- ", "+++ ", "@@ ", "+", "-")):
            indent_counts.append(len(raw) - len(stripped))

    if not indent_counts:
        return diff_text

    count_set: set[int] = set(indent_counts)
    if len(count_set) != 1 or 0 in count_set:
        return diff_text  # 缩进不统一，交由容错解析

    indent: int = indent_counts[0]
    return "\n".join(
        raw[indent:] if len(raw) >= indent else raw for raw in lines
    )


def _parse_strict(diff_text: str) -> list[dict[str, Any]]:
    """使用 unidiff 严格解析 diff（hunk 计数必须与实际行数一致）。"""
    try:
        patch_set = PatchSet(diff_text)
    except Exception as exc:
        raise ValueError(f"unidiff 解析失败: {exc}") from exc

    files: list[dict[str, Any]] = []
    for patched_file in patch_set:
        if patched_file.is_binary_file:
            logger.warning("跳过二进制文件: {}", patched_file.path)
            continue

        change_type: str = _classify_change(patched_file)
        file_path: str = patched_file.path or "/unknown"
        hunks: list[dict[str, Any]] = _extract_hunks(patched_file)
        hunks_text: str = _hunks_to_text(hunks)
        risk_flags: list[str] = _detect_risk_flags(file_path, change_type, hunks_text)

        files.append(
            {
                "file_path": file_path,
                "change_type": change_type,
                "additions": int(patched_file.added),
                "deletions": int(patched_file.removed),
                "source_file": patched_file.source_file,
                "target_file": patched_file.target_file,
                "hunks": hunks,
                "risk_flags": risk_flags,
            }
        )

    if not files:
        logger.warning("diff 中未解析出任何文件变更")
    return files


def _iter_hunks(patched_file: Any) -> list[Any]:
    """兼容不同 unidiff 版本地获取 hunk 列表。"""
    if hasattr(patched_file, "hunks"):
        return list(patched_file.hunks)
    return list(patched_file)


def _iter_hunk_lines(hunk: Any) -> list[Any]:
    """兼容不同 unidiff 版本地获取 hunk 内的行列表。"""
    if hasattr(hunk, "lines"):
        return list(hunk.lines)
    return list(hunk)


def _classify_change(patched_file: Any) -> str:
    """根据 unidiff 的 PatchedFile 标志位判断变更类型。"""
    if patched_file.is_added_file:
        return "added"
    if patched_file.is_removed_file:
        return "deleted"
    if getattr(patched_file, "is_rename", False) or getattr(
        patched_file, "is_renamed_file", False
    ):
        return "renamed"
    if patched_file.is_modified_file:
        return "modified"
    return "modified"


def _extract_hunks(patched_file: Any) -> list[dict[str, Any]]:
    """提取 hunk 头部信息与逐行内容（兼容 unidiff 0.7/1.0）。"""
    hunks: list[dict[str, Any]] = []
    for hunk in _iter_hunks(patched_file):
        lines: list[dict[str, Any]] = []
        for line in _iter_hunk_lines(hunk):
            line_type: str = line.line_type  # ' ', '+', '-', '' 等
            content: str = getattr(line, "value", "") or ""
            if content.endswith("\n"):
                content = content[:-1]
            if content.endswith("\r"):
                content = content[:-1]
            if line_type in ("+", "-", " ") and content.startswith(line_type):
                content = content[1:]
            lines.append(
                {
                    "type": line_type,
                    "source_line_no": line.source_line_no,
                    "target_line_no": line.target_line_no,
                    "content": content,
                }
            )
        hunks.append(
            {
                "source_start": hunk.source_start,
                "source_length": hunk.source_length,
                "target_start": hunk.target_start,
                "target_length": hunk.target_length,
                "lines": lines,
            }
        )
    return hunks


def _hunks_to_text(hunks: list[dict[str, Any]]) -> str:
    """将 hunk 内容拼接为纯文本，用于风险规则扫描。"""
    parts: list[str] = []
    for hunk in hunks:
        for line in hunk["lines"]:
            parts.append(line["content"])
    return "\n".join(parts)


def _change_label(change_type: str) -> str:
    """返回变更类型的中文标签。"""
    labels: dict[str, str] = {
        "added": "新增",
        "modified": "修改",
        "deleted": "删除",
        "renamed": "重命名",
    }
    return labels.get(change_type, change_type)


def is_new_file(file_info: dict[str, Any]) -> bool:
    """判断文件是否为纯新增文件（源文件为 /dev/null 且为 added 类型）。"""
    return file_info.get("change_type") == "added" and file_info.get("source_file") == "/dev/null"


def build_file_diff(file_info: dict[str, Any]) -> str:
    """根据解析结果重建单个文件的 unified diff 文本。

    重建文本用于在 Diff 展示区进行 Pygments 语法高亮。
    """
    source_file: str = file_info.get("source_file") or f"a/{file_info['file_path']}"
    target_file: str = file_info.get("target_file") or f"b/{file_info['file_path']}"
    change_type: str = file_info["change_type"]

    header: str = f"diff --git {source_file} {target_file}"
    if change_type == "added":
        header += "\nnew file mode 100644"
    elif change_type == "deleted":
        header += "\ndeleted file mode 100644"
    elif change_type == "renamed":
        header += "\nrename from {}\nrename to {}".format(
            source_file[2:] if source_file.startswith(("a/", "b/")) else source_file,
            target_file[2:] if target_file.startswith(("a/", "b/")) else target_file,
        )

    body_parts: list[str] = [header, f"--- {source_file}", f"+++ {target_file}"]
    for hunk in file_info["hunks"]:
        body_parts.append(
            "@@ -{},{} +{},{} @@".format(
                hunk["source_start"],
                hunk["source_length"],
                hunk["target_start"],
                hunk["target_length"],
            )
        )
        for line in hunk["lines"]:
            line_type: str = line["type"]
            if line_type in ("+", "-", " "):
                body_parts.append(f"{line_type}{line['content']}")
            else:
                body_parts.append(line["content"] or "")
    return "\n".join(body_parts)


def file_risk_level(file_info: dict[str, Any]) -> str:
    """按文件风险标记计算该文件的风险等级（high/medium/low）。"""
    flags: list[str] = file_info.get("risk_flags", [])
    if any(flag in _HIGH_FLAGS for flag in flags):
        return "high"
    if any(flag in _MEDIUM_FLAGS for flag in flags):
        return "medium"
    return "low"


def compute_risk_level(files: list[dict[str, Any]]) -> str:
    """汇总文件列表计算整体风险等级（基于 0-100 评分阈值，保持兼容）。"""
    score, _ = compute_risk_score(files)
    return score_to_level(score)


def build_title(files: list[dict[str, Any]]) -> str:
    """根据文件列表自动提取变更摘要标题。"""
    if not files:
        return "空 diff"
    if len(files) == 1:
        info = files[0]
        return "{} {}".format(_change_label(info["change_type"]), info["file_path"])
    paths: list[str] = [f["file_path"] for f in files[:3]]
    joined: str = ", ".join(paths)
    if len(files) > 3:
        joined += ", ..."
    return "修改 {} 个文件: {}".format(len(files), joined)


def render_file_summary(file_info: dict[str, Any]) -> str:
    """生成文件列表项的可读摘要文本。"""
    level: str = file_risk_level(file_info)
    level_mark: str = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(level, "⚪")
    flags: str = " | ".join(file_info.get("risk_flags", [])) or "无风险标记"
    return "{} {} {} (+{} -{})  {}".format(
        level_mark,
        _change_label(file_info["change_type"]),
        file_info["file_path"],
        file_info["additions"],
        file_info["deletions"],
        flags,
    )


# ----------------------------------------------------------------------
# 容错解析（diff 不完整 / 被截断时兜底）
# ----------------------------------------------------------------------
_HUNK_HEADER_RE: re.Pattern[str] = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"
)


def _strip_vcs_prefix(path: Optional[str]) -> str:
    """去掉 a/ b/ 前缀，返回真实文件路径。"""
    if not path:
        return "/unknown"
    p: str = path
    if p.startswith(("a/", "b/")):
        p = p[2:]
    return p


def _guess_change_type(current: dict[str, Any], special: set[str]) -> str:
    """根据源/目标文件与特殊标记推断变更类型。"""
    if "deleted file mode" in special or current.get("target_file") == "/dev/null":
        return "deleted"
    if "new file mode" in special or current.get("source_file") == "/dev/null":
        return "added"
    src: str = _strip_vcs_prefix(current.get("source_file"))
    tgt: str = _strip_vcs_prefix(current.get("target_file"))
    if (
        src != "/unknown"
        and tgt != "/unknown"
        and src != tgt
        and "rename from" in special
    ):
        return "renamed"
    return "modified"


def _parse_lenient(diff_text: str) -> list[dict[str, Any]]:
    """行级容错解析：不依赖 hunk 计数，按行提取文件、增删行与代码片段。

    适用于 diff 被截断、hunk 行数与内容不一致等 unidiff 无法处理的场景。
    每一行先去除前导空白再分类，因此对从聊天窗口复制的缩进 diff 同样有效。
    hunk 行号可能为 None（尽力而为）。
    """
    files: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    special: set[str] = set()  # 记录"new file mode"等特殊行
    hunk_lines: list[dict[str, Any]] = []  # 当前 hunk 的逐行列表

    for raw in diff_text.splitlines():
        line: str = raw.rstrip("\r")
        stripped: str = line.lstrip(" \t")

        if stripped.startswith("diff --git"):
            # 提交上一个文件
            if current is not None:
                files.append(_finalize_file(current, hunk_lines, special))
            hunk_lines = []
            special = set()
            parts: list[str] = stripped.split(" ", 3)
            src: str = parts[2] if len(parts) > 2 else ""
            tgt: str = parts[3] if len(parts) > 3 else ""
            current = {
                "source_file": src,
                "target_file": tgt,
                "file_path": _strip_vcs_prefix(tgt or src),
                "change_type": "modified",
                "additions": 0,
                "deletions": 0,
                "hunks": [],
                "risk_flags": [],
            }
            continue

        if current is None:
            continue

        if stripped.startswith("---"):
            current["source_file"] = stripped[4:].lstrip() if stripped.startswith("--- ") else stripped[3:]
            continue
        if stripped.startswith("+++"):
            current["target_file"] = stripped[4:].lstrip() if stripped.startswith("+++ ") else stripped[3:]
            current["file_path"] = _strip_vcs_prefix(current["target_file"])
            continue

        if (
            "file mode" in line
            or "rename from" in line
            or "rename to" in line
            or "similarity index" in line
        ):
            special.add(line.strip())
            continue

        if stripped.startswith("@@"):
            # 结束并提交上一个 hunk
            if hunk_lines:
                current["hunks"].append(_finalize_hunk(hunk_lines))
            hunk_lines = []
            m: Optional[re.Match[str]] = _HUNK_HEADER_RE.match(stripped)
            if m:
                hunk_lines.append(
                    {
                        "meta": {
                            "source_start": int(m.group(1)),
                            "source_length": int(m.group(2) or 1),
                            "target_start": int(m.group(3)),
                            "target_length": int(m.group(4) or 1),
                        }
                    }
                )
            continue

        if stripped.startswith("Binary files") or stripped.startswith("GIT binary patch"):
            continue

        if stripped.startswith("-"):
            current["deletions"] += 1
            hunk_lines.append(
                {"type": "-", "source_line_no": None, "target_line_no": None,
                 "content": stripped[1:]}
            )
            continue
        if stripped.startswith("+"):
            current["additions"] += 1
            hunk_lines.append(
                {"type": "+", "source_line_no": None, "target_line_no": None,
                 "content": stripped[1:]}
            )
            continue
        if stripped.startswith("\\ No"):
            hunk_lines.append(
                {"type": " ", "source_line_no": None, "target_line_no": None,
                 "content": line}
            )
            continue
        # 上下文行（可能有真实前导空格），不进增删统计
        hunk_lines.append(
            {"type": " ", "source_line_no": None, "target_line_no": None,
             "content": stripped}
        )

    # 提交最后一个文件
    if current is not None:
        files.append(_finalize_file(current, hunk_lines, special))

    return files


def _finalize_hunk(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """将 hunk 行列表组装为统一结构（剥离临时 meta 头）。"""
    meta: dict[str, Any] = {}
    lines: list[dict[str, Any]] = []
    for entry in entries:
        if "meta" in entry:
            meta.update(entry["meta"])
        else:
            lines.append(entry)
    result: dict[str, Any] = {
        "source_start": meta.get("source_start", 0),
        "source_length": meta.get("source_length", 0),
        "target_start": meta.get("target_start", 0),
        "target_length": meta.get("target_length", 0),
        "lines": lines,
    }
    return result


def _finalize_file(
    current: dict[str, Any],
    hunk_lines: list[dict[str, Any]],
    special: set[str],
) -> dict[str, Any]:
    """收尾：提交最后一个 hunk，补全 change_type 与 risk_flags。"""
    if hunk_lines:
        current.setdefault("hunks", []).append(_finalize_hunk(hunk_lines))
    current["change_type"] = _guess_change_type(current, special)
    # 删除文件时 target 为 /dev/null，路径应取源文件
    if current["file_path"] in ("", "/dev/null"):
        current["file_path"] = _strip_vcs_prefix(current.get("source_file"))
    hunks: list[dict[str, Any]] = current.get("hunks", [])
    current["risk_flags"] = _detect_risk_flags(
        current["file_path"], current["change_type"], _hunks_to_text(hunks)
    )
    return current