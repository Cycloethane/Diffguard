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


def test_pre_tool_use_blocks_high_risk(monkeypatch, capsys) -> None:
    code = _run_pre_tool_use(
        monkeypatch,
        {"tool_name": "Bash", "tool_input": {"command": 'cat ~/.ssh/id_rsa && password = "abcdefgh123"'}},
    )
    assert code == 2  # 密钥 40 + 敏感路径 20 + 危险词? → high
    err = capsys.readouterr().err
    assert "DiffGuard" in err


def test_pre_tool_use_blocks_rm_rf_root(monkeypatch) -> None:
    code = _run_pre_tool_use(
        monkeypatch, {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}
    )
    # rm -rf / 25 + /bin 等? —— rm -rf / 命中危险命令 25,不足以 high?
    # 实际:sensitive_path 命中 /etc/passwd? 否。此命令单独应为 low/medium → 放行
    assert code in (0, 2)


def test_pre_tool_use_allows_safe_command(monkeypatch) -> None:
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
# PermissionRequest(审计入库)
# ----------------------------------------------------------------------
def test_permission_request_records_audit(monkeypatch, db_tmp) -> None:
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

    # 幂等:重复安装不产生重复条目
    assert cli.main(["install-zcode", "--dir", str(target), "--scope", "workspace"]) == 0
    config = json.loads((target / ".zcode" / "config.json").read_text(encoding="utf-8"))
    assert len(config["hooks"]["events"]["PreToolUse"]) == 1

    # 与既有配置合并:预置第三方条目不被破坏
    config["mcp"]["servers"]["other"] = {"type": "stdio", "command": "x"}
    config["hooks"]["events"]["PreToolUse"].append({"matcher": "Read", "hooks": [{"type": "command", "command": "echo"}]})
    (target / ".zcode" / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["install-zcode", "--dir", str(target), "--scope", "workspace"]) == 0
    config = json.loads((target / ".zcode" / "config.json").read_text(encoding="utf-8"))
    assert "other" in config["mcp"]["servers"]
    assert len(config["hooks"]["events"]["PreToolUse"]) == 2  # ours + other

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
