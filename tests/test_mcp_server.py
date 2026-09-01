# -*- coding: utf-8 -*-
"""bridge.mcp_server 单元测试：JSON-RPC 协议分发与工具调用。"""

import json

from bridge import mcp_server


def _call(msg: dict) -> dict:
    resp = mcp_server._handle_request(msg)
    assert resp is not None
    return json.loads(resp)


def test_initialize() -> None:
    resp = _call({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == mcp_server._PROTOCOL_VERSION
    assert resp["result"]["serverInfo"]["name"] == "diffguard-mcp"
    assert "tools" in resp["result"]["capabilities"]


def test_initialized_notification_no_response() -> None:
    assert (
        mcp_server._handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
        is None
    )


def test_ping() -> None:
    resp = _call({"jsonrpc": "2.0", "id": 9, "method": "ping"})
    assert resp["result"] == {}


def test_tools_list_has_nine_tools() -> None:
    resp = _call({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in resp["result"]["tools"]]
    assert len(names) == 9
    for expected in (
        "get_status", "review_diff", "review_file", "get_recent_reviews",
        "get_recent_permissions", "get_decision_feedback", "get_decision_stats",
        "submit_decision", "scan_risk",
    ):
        assert expected in names


def test_call_scan_risk() -> None:
    resp = _call(
        {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "scan_risk", "arguments": {"text": "rm -rf /"}},
        }
    )
    text = resp["result"]["content"][0]["text"]
    data = json.loads(text)
    assert data["score"] >= 25
    assert data["level"] in ("low", "medium", "high")


def test_call_submit_decision_rejects_bad_options(bridge_tmp) -> None:
    resp = _call(
        {
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {
                "name": "submit_decision",
                "arguments": {"question": "q", "options": [{"key": "A", "text": "only"}]},
            },
        }
    )
    text = resp["result"]["content"][0]["text"]
    assert text.startswith("[错误]")


def test_call_submit_decision_writes_bridge_file(bridge_tmp) -> None:
    from bridge import store

    resp = _call(
        {
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {
                "name": "submit_decision",
                "arguments": {
                    "question": "打包方式？",
                    "options": [{"key": "A", "text": "单文件"}, {"key": "B", "text": "目录"}],
                },
            },
        }
    )
    text = resp["result"]["content"][0]["text"]
    assert text.startswith("已向 DiffGuard 提交决策请求")
    data = store.read_agent_decision()
    assert data is not None
    assert data["question"] == "打包方式？"
    store.clear_agent_decision()


def test_unknown_method_returns_32601() -> None:
    resp = _call({"jsonrpc": "2.0", "id": 6, "method": "foo/bar"})
    assert resp["error"]["code"] == -32601


def test_unknown_tool_returns_32601() -> None:
    resp = _call(
        {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
         "params": {"name": "nope", "arguments": {}}}
    )
    assert resp["error"]["code"] == -32601


def test_handler_exception_returns_32603() -> None:
    # limit 传非数字 → handler 内 int() 抛异常 → -32603
    resp = _call(
        {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
         "params": {"name": "get_recent_reviews", "arguments": {"limit": "abc"}}}
    )
    assert resp["error"]["code"] == -32603
