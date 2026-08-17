# -*- coding: utf-8 -*-
"""OpenCode 桥接层：DiffGuard 与 AI Agent（OpenCode）之间的文件级通信。

设计目标：不要求 OpenCode 侧安装任何额外依赖，通过约定的 JSON 文件交换
状态，配合 Skill 说明文件让 Agent 学会读写这些文件。

文件约定（位于 %APPDATA%/DiffGuard/bridge/）：
    decision_feedback.json  决策反馈（用户已作出的选择），Agent 可读取了解偏好。
    agent_decision_in.json  Agent 写入的"待决策"请求（可选的精确通道，
                           替代剪贴板猜测），格式见 write_agent_decision()。
    report_requests.json    审查请求队列（Agent 请求 DiffGuard 审查 diff）。
    report_results.json     审查结果（DiffGuard 完成审查后写回）。
    status.json             当前状态（监听开关、模式等）。
"""

import json
import os
import platformdirs
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger


def bridge_dir() -> Path:
    """返回桥接目录，并确保其存在。"""
    base = Path(platformdirs.user_config_dir("DiffGuard")) / "bridge"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.debug("创建桥接目录失败: {}", exc)
    return base


def _path(name: str) -> Path:
    return bridge_dir() / name


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("读取桥接文件 {} 失败: {}", path.name, exc)
    return default


def _write_json(path: Path, data: Any) -> bool:
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(path)
        return True
    except OSError as exc:
        logger.error("写入桥接文件 {} 失败: {}", path.name, exc)
        return False


# ----------------------------------------------------------------------
# 决策反馈（功能7：用户选择回写，供 Agent 参考历史偏好）
# ----------------------------------------------------------------------
def record_decision_feedback(
    question: str,
    chosen: str,
    chosen_text: str,
    recommendation: str,
    source: str = "Unknown",
) -> bool:
    """把用户一次决策写入决策反馈文件（追加历史列表）。"""
    path = _path("decision_feedback.json")
    data = _read_json(path, {"decisions": []})
    if not isinstance(data, dict):
        data = {"decisions": []}
    data.setdefault("decisions", [])
    data["decisions"].append(
        {
            "timestamp": datetime.now().isoformat(),
            "source": source,
            "question": question,
            "chosen": chosen,
            "chosen_text": chosen_text,
            "recommendation": recommendation,
        }
    )
    # 仅保留最近 500 条，避免无限增长
    data["decisions"] = data["decisions"][-500:]
    return _write_json(path, data)


def read_decision_feedback(limit: int = 50) -> list[dict]:
    """读取最近 limit 条决策反馈（供 Agent 了解用户偏好）。"""
    data = _read_json(_path("decision_feedback.json"), {})
    decisions = data.get("decisions", []) if isinstance(data, dict) else []
    return decisions[-limit:][::-1]


# ----------------------------------------------------------------------
# Agent 决策请求（功能10：Agent 显式提交决策，替代剪贴板猜测）
# ----------------------------------------------------------------------
def write_agent_decision(
    question: str,
    options: list[dict],
    context: str = "",
) -> bool:
    """供 Agent 调用：写入一个待决策请求。

    参数:
        question: 决策问题。
        options: [{"key": "A", "text": "..."}, ...]。
        context: 可选上下文说明。
    """
    path = _path("agent_decision_in.json")
    return _write_json(
        path,
        {
            "timestamp": datetime.now().isoformat(),
            "source": "OpenCode",
            "question": question,
            "options": options,
            "context": context,
        },
    )


def read_agent_decision() -> Optional[dict]:
    """读取 Agent 提交的待决策请求；不存在返回 None。"""
    data = _read_json(_path("agent_decision_in.json"), None)
    return data if isinstance(data, dict) else None


def clear_agent_decision() -> None:
    """清空已处理的 Agent 决策请求。"""
    try:
        _path("agent_decision_in.json").unlink(missing_ok=True)
    except OSError:
        pass


# ----------------------------------------------------------------------
# 审查请求 / 结果（功能1/2：Agent 请求审查，DiffGuard 返回结果）
# ----------------------------------------------------------------------
def submit_review_request(diff_text: str, title: str = "") -> Optional[int]:
    """Agent 提交审查请求，返回请求 id。"""
    path = _path("report_requests.json")
    data = _read_json(path, {"requests": [], "next_id": 1})
    if not isinstance(data, dict):
        data = {"requests": [], "next_id": 1}
    req_id = int(data.get("next_id", 1))
    data["requests"].append(
        {
            "id": req_id,
            "timestamp": datetime.now().isoformat(),
            "title": title,
            "diff": diff_text,
            "status": "pending",
        }
    )
    data["next_id"] = req_id + 1
    _write_json(path, data)
    return req_id


def read_review_requests() -> list[dict]:
    """读取所有审查请求。"""
    data = _read_json(_path("report_requests.json"), {})
    return data.get("requests", []) if isinstance(data, dict) else []


def mark_review_request_done(req_id: int, result: str) -> bool:
    """标记审查请求完成并写入结果。"""
    req_path = _path("report_requests.json")
    res_path = _path("report_results.json")
    data = _read_json(req_path, {})
    requests = data.get("requests", []) if isinstance(data, dict) else []
    updated = False
    for req in requests:
        if req.get("id") == req_id:
            req["status"] = "done"
            updated = True
            break
    if updated:
        _write_json(req_path, data)
    results = _read_json(res_path, {"results": []})
    if not isinstance(results, dict):
        results = {"results": []}
    results.setdefault("results", [])
    results["results"].append(
        {
            "id": req_id,
            "timestamp": datetime.now().isoformat(),
            "report": result,
        }
    )
    results["results"] = results["results"][-500:]
    _write_json(res_path, results)
    return True


def read_review_results(limit: int = 20) -> list[dict]:
    """读取最近 limit 条审查结果。"""
    data = _read_json(_path("report_results.json"), {})
    results = data.get("results", []) if isinstance(data, dict) else []
    return results[-limit:][::-1]


# ----------------------------------------------------------------------
# 状态（供 Agent 快速了解 DiffGuard）
# ----------------------------------------------------------------------
def write_status(**kwargs: Any) -> bool:
    """写入当前状态快照。"""
    data = {"timestamp": datetime.now().isoformat()}
    data.update(kwargs)
    return _write_json(_path("status.json"), data)


def read_status() -> dict:
    """读取状态快照。"""
    data = _read_json(_path("status.json"), {})
    return data if isinstance(data, dict) else {}


def clear_all_bridge_files() -> None:
    """清理所有桥接文件（测试或卸载时使用）。"""
    for name in (
        "decision_feedback.json",
        "agent_decision_in.json",
        "report_requests.json",
        "report_results.json",
        "status.json",
    ):
        try:
            _path(name).unlink(missing_ok=True)
        except OSError:
            pass
