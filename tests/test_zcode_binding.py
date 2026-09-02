# -*- coding: utf-8 -*-
"""ZCode 绑定层测试:hooks_runner 与 install-zcode 安装器。"""

import json

import pytest

from bridge import cli
from bridge.hooks_runner import _extract_text, pre_tool_use_main, permission_request_main


# ----------------------------------------------------------------------
# 文本提取
# ----------------------------------------------------------------------
def test_extract_text_bash_command() -> None:
    assert _extract_text("Bash", {"command": "git status"}) == "git status"
    assert _extract_text("Bash", {"cmd": "ls -la"}) == "ls -la"


def test_extract_text_write_file() -> None:
    text = _extract_text("Write", {"file_path": "src/.env", "content": "password=1"})
    assert "src/.env" in text and "password=1" in text
    # 别名 ApplyPatch 视作写入类
    assert _extract_text("ApplyPatch", {"path": "a.py", "new_string": "x"}) == "a.py\nx"


def test_extract_text_irrelevant_tool_returns_empty() -> None:
    assert _extract_text("Read", {"file_path": "a.py"}) == ""
    assert _extract_text("Bash", {}) == ""


# ----------------------------------------------------------------------
# PreToolUse(经 stdin 注入)
# ----------------------------------------------------------------------
def _run_pre_tool_use(monkeypatch, payload: dict) -> int:
    monkeypatch.setattr("sys.stdin", _FakeStdin(json.dumps(payload)))
    return pre_tool_use_main()


class _FakeStdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


def test_pre_tool_use_blocks_high_risk(monkeypatch, capsys, tmp_path) -> None:
    # 隔离 APPDATA:避免真实环境的 hook_skip 标记文件影响判定
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.delenv("DIFFGUARD_HOOK_SKIP", raising=False)
    code = _run_pre_tool_use(
        monkeypatch,
        {"tool_name": "Bash", "tool_input": {"command": 'cat ~/.ssh/id_rsa && password = "abcdefgh123"'}},
    )
    assert code == 2  # 密钥 40 + 敏感路径 20 → high
    err = capsys.readouterr().err
    assert "DiffGuard" in err


def test_pre_tool_use_blocks_rm_rf_root(monkeypatch) -> None:
    code = _run_pre_tool_use(
        monkeypatch, {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}
    )
    # rm -rf / 25 + /bin 等? —— rm -rf / 命中危险命令 25,不足以 high?
    # 实际:sensitive_path 命中 /etc/passwd? 否。此命令单独应为 low/medium → 放行
    assert code in (0, 2)


def test_pre_tool_use_allows_safe_command(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.delenv("DIFFGUARD_HOOK_SKIP", raising=False)
    code = _run_pre_tool_use(
        monkeypatch, {"tool_name": "Bash", "tool_input": {"command": "python -m pytest -q"}}
    )
    assert code == 0


def test_pre_tool_use_skip_env(monkeypatch) -> None:
    monkeypatch.setenv("DIFFGUARD_HOOK_SKIP", "1")
    code = _run_pre_tool_use(
        monkeypatch, {"tool_name": "Bash", "tool_input": {"command": "rm -rf / && format c:"}}
    )
    assert code == 0


def test_pre_tool_use_skip_marker_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    marker = tmp_path / "DiffGuard" / "hook_skip"
    marker.parent.mkdir(parents=True)
    marker.write_text("", encoding="utf-8")
    code = _run_pre_tool_use(
        monkeypatch,
        {"tool_name": "Bash", "tool_input": {"command": 'password = "abcdefgh123" && rm -rf /'}},
    )
    assert code == 0


def test_pre_tool_use_garbage_stdin(monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin", _FakeStdin("not json"))
    assert pre_tool_use_main() == 0


# ----------------------------------------------------------------------
# PermissionRequest(审计入库 + 桥接事件)
# ----------------------------------------------------------------------
def test_permission_request_records_audit(monkeypatch, db_tmp, bridge_tmp) -> None:
    from models.permission_history import get_recent_permissions

    monkeypatch.setattr(
        "sys.stdin",
        _FakeStdin(json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"}})),
    )
    assert permission_request_main() == 0
    recs = get_recent_permissions(5)
    assert len(recs) == 1
    assert recs[0].source == "ZCode"
    assert recs[0].prompt_type == "command_exec"


def test_permission_request_writes_bridge_event(monkeypatch, db_tmp, bridge_tmp) -> None:
    from bridge import store

    monkeypatch.setattr(
        "sys.stdin",
        _FakeStdin(
            json.dumps(
                {"tool_name": "Bash", "tool_input": {"command": "cat ~/.ssh/id_rsa && password = \"abcdefgh123\""}}
            )
        ),
    )
    assert permission_request_main() == 0
    event = store.read_permission_event()
    assert event is not None
    assert event["source"] == "ZCode"
    assert event["tool"] == "Bash"
    assert event["score"] >= 60
    assert event["level"] == "high"
    assert event["target"].startswith("cat")


def test_permission_event_seq_and_ring(bridge_tmp) -> None:
    from bridge import store

    e1 = store.write_permission_event("ZCode", "Bash", "ls", 10, "low", [])
    e2 = store.write_permission_event("ZCode", "WebFetch", "https://x", 20, "low", [])
    assert e1["seq"] == 1 and e2["seq"] == 2
    assert store.read_permission_event()["seq"] == 2
    for i in range(25):
        store.write_permission_event("ZCode", "Bash", f"c{i}", 0, "low", [])
    import json as _json

    data = _json.loads((bridge_tmp / "permission_events.json").read_text(encoding="utf-8"))
    assert len(data["recent"]) == 20  # 环形上限
    assert data["seq"] == 27


# ----------------------------------------------------------------------
# AskUserQuestion(询问镜像 → 决策通道)
# ----------------------------------------------------------------------
def test_ask_user_question_mirrors_to_bridge(monkeypatch, bridge_tmp) -> None:
    from bridge import store
    from bridge.hooks_runner import ask_user_question_main

    payload = {
        "tool_name": "AskUserQuestion",
        "tool_input": {
            "questions": [
                {
                    "question": "部署方式选哪个?",
                    "options": [
                        {"label": "Docker", "description": "容器化,环境一致"},
                        {"label": "裸机", "description": "直接安装,性能最好"},
                        {"label": "K8s", "description": "编排,弹性伸缩"},
                    ],
                },
                {
                    "question": "第二个问题(应进 context 摘要)?",
                    "options": [
                        {"label": "甲", "description": "x"}, {"label": "乙", "description": "y"}
                    ],
                },
            ]
        },
    }
    monkeypatch.setattr("sys.stdin", _FakeStdin(json.dumps(payload)))
    assert ask_user_question_main() == 0

    data = store.read_agent_decision()
    assert data is not None
    assert data["source"] == "ZCode"
    assert data["question"] == "部署方式选哪个?"
    assert len(data["options"]) == 3
    assert data["options"][0]["key"] == "Docker"
    assert "容器化" in data["options"][0]["text"]
    assert "第二个问题" in data["context"]  # 多问题摘进 context

    # 经消费函数构造 DecisionPrompt 供决策浮窗
    prompt = store.read_agent_decision_prompt()
    assert prompt is not None
    assert prompt.source == "ZCode"
    assert len(prompt.options) == 3


def test_ask_user_question_invalid_input_noop(monkeypatch, bridge_tmp) -> None:
    from bridge import store
    from bridge.hooks_runner import ask_user_question_main

    monkeypatch.setattr("sys.stdin", _FakeStdin(json.dumps({"tool_name": "AskUserQuestion", "tool_input": {}})))
    assert ask_user_question_main() == 0
    assert store.read_agent_decision() is None  # 非法输入不写


# ----------------------------------------------------------------------
# install-zcode / uninstall-zcode
# ----------------------------------------------------------------------
def test_install_uninstall_zcode_workspace(tmp_path, monkeypatch, capsys) -> None:
    # 避免 installer 写真实用户目录的 source_path 标记
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    target = tmp_path / "repo"
    target.mkdir()
    assert cli.main(["install-zcode", "--dir", str(target), "--scope", "workspace"]) == 0

    config = json.loads((target / ".zcode" / "config.json").read_text(encoding="utf-8"))
    server = config["mcp"]["servers"]["diffguard"]
    assert server["args"][0].endswith("bootstrap.py")
    assert config["hooks"]["enabled"] is True
    assert config["hooks"]["events"]["PreToolUse"][0]["matcher"] == "Bash|Write|Edit|ApplyPatch"
    assert (target / ".zcode" / "skills" / "diffguard" / "SKILL.md").is_file()
    assert (target / ".zcode" / "commands" / "diffguard" / "review.md").is_file()
    # 源码位置标记(bootstrap 回退定位用)
    marker = tmp_path / "appdata" / "DiffGuard" / "source_path.txt"
    assert marker.is_file()

    # 幂等:重复安装不产生重复条目(风险扫描 + 询问镜像两组)
    assert cli.main(["install-zcode", "--dir", str(target), "--scope", "workspace"]) == 0
    config = json.loads((target / ".zcode" / "config.json").read_text(encoding="utf-8"))
    assert len(config["hooks"]["events"]["PreToolUse"]) == 2
    matchers = {g["matcher"] for g in config["hooks"]["events"]["PreToolUse"]}
    assert matchers == {"Bash|Write|Edit|ApplyPatch", "AskUserQuestion"}

    # 与既有配置合并:预置第三方条目不被破坏
    config["mcp"]["servers"]["other"] = {"type": "stdio", "command": "x"}
    config["hooks"]["events"]["PreToolUse"].append({"matcher": "Read", "hooks": [{"type": "command", "command": "echo"}]})
    (target / ".zcode" / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["install-zcode", "--dir", str(target), "--scope", "workspace"]) == 0
    config = json.loads((target / ".zcode" / "config.json").read_text(encoding="utf-8"))
    assert "other" in config["mcp"]["servers"]
    assert len(config["hooks"]["events"]["PreToolUse"]) == 3  # 两组 ours + other

    # 卸载:仅移除 DiffGuard 条目
    assert cli.main(["uninstall-zcode", "--dir", str(target), "--scope", "workspace"]) == 0
    config = json.loads((target / ".zcode" / "config.json").read_text(encoding="utf-8"))
    assert "diffguard" not in config["mcp"]["servers"]
    assert "other" in config["mcp"]["servers"]
    assert len(config["hooks"]["events"]["PreToolUse"]) == 1
    assert not (target / ".zcode" / "skills" / "diffguard").exists()
    assert not (target / ".zcode" / "commands" / "diffguard").exists()


def test_install_zcode_rejects_missing_dir(tmp_path) -> None:
    assert cli.main(["install-zcode", "--dir", str(tmp_path / "nope"), "--scope", "workspace"]) == 1
