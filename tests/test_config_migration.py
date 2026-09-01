# -*- coding: utf-8 -*-
"""Phase 2 客户端中立化测试:配置迁移、MCP 门控、source 透传。"""

import json

import pytest

from bridge import mcp_server
from models.config import Config, config_path, load_config


@pytest.fixture
def cfg_file(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """把配置文件路径重定向到临时目录。"""
    target = tmp_path / "config.json"
    monkeypatch.setattr("models.config.config_path", lambda: target)
    return target


# ----------------------------------------------------------------------
# 配置迁移
# ----------------------------------------------------------------------
def test_legacy_keys_migrated_and_persisted(cfg_file) -> None:
    cfg_file.write_text(
        json.dumps({"opencode_bridge": False, "opencode_mcp": False, "model": "m1"}),
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.agent_bridge is False
    assert cfg.agent_mcp is False
    assert cfg.model == "m1"
    # 迁移结果回写磁盘,旧键消失
    data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert "opencode_bridge" not in data
    assert data["agent_bridge"] is False
    assert data["agent_mcp"] is False


def test_new_keys_untouched_by_migration(cfg_file) -> None:
    cfg_file.write_text(json.dumps({"agent_bridge": False}), encoding="utf-8")
    cfg = load_config()
    assert cfg.agent_bridge is False
    assert cfg.agent_mcp is True  # 默认


def test_corrupt_config_returns_default(cfg_file) -> None:
    cfg_file.write_text("{not json", encoding="utf-8")
    cfg = load_config()
    assert cfg.agent_bridge is True


def test_defaults_client_neutral() -> None:
    cfg = Config()
    assert cfg.agent_bridge is True
    assert cfg.agent_mcp is True


# ----------------------------------------------------------------------
# MCP 门控(agent_mcp=False 时写入类工具返回提示)
# ----------------------------------------------------------------------
def _call_tool(name: str, arguments: dict) -> str:
    resp = mcp_server._handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": name, "arguments": arguments}}
    )
    return json.loads(resp)["result"]["content"][0]["text"]


@pytest.fixture
def mcp_gated(monkeypatch: pytest.MonkeyPatch) -> Config:
    """让 MCP server 读到 agent_mcp=False 的配置。"""
    monkeypatch.setattr(mcp_server, "load_config", lambda: Config(api_key="k", agent_mcp=False))
    return Config(api_key="k", agent_mcp=False)


def test_mcp_submit_decision_gated(bridge_tmp, mcp_gated) -> None:
    text = _call_tool(
        "submit_decision",
        {"question": "q", "options": [{"key": "A", "text": "x"}, {"key": "B", "text": "y"}]},
    )
    assert text.startswith("[提示]")
    from bridge import store

    assert store.read_agent_decision() is None  # 未写入


def test_mcp_review_diff_gated(mcp_gated) -> None:
    assert _call_tool("review_diff", {"diff_text": "x"}).startswith("[提示]")


def test_mcp_scan_risk_not_gated(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "load_config", lambda: Config(agent_mcp=False))
    text = _call_tool("scan_risk", {"text": "rm -rf /"})
    assert json.loads(text)["score"] >= 25  # 只读工具不受门控


# ----------------------------------------------------------------------
# source 透传
# ----------------------------------------------------------------------
def test_mcp_submit_decision_passes_source(bridge_tmp, monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "load_config", lambda: Config(api_key="k"))
    from bridge import store

    text = _call_tool(
        "submit_decision",
        {
            "question": "部署到哪？",
            "options": [{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
            "source": "ZCode",
        },
    )
    assert text.startswith("已向 DiffGuard 提交决策请求")
    data = store.read_agent_decision()
    assert data["source"] == "ZCode"

    prompt = store.read_agent_decision_prompt()
    assert prompt.source == "ZCode"


def test_cli_submit_decision_source_flag(bridge_tmp, capsys) -> None:
    from bridge import cli, store

    rc = cli.main(
        ["submit-decision", "--question", "q", "--options", "A) 甲 B) 乙", "--source", "ZCode"]
    )
    assert rc == 0
    assert store.read_agent_decision()["source"] == "ZCode"
    store.clear_agent_decision()
