# -*- coding: utf-8 -*-
"""bridge.cli 单元测试：scan / submit-decision / install-git-hook 基本路径。"""

import json

from bridge import cli


def test_cmd_scan(capsys) -> None:
    rc = cli.main(["scan", "rm -rf /"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["score"] >= 25
    assert "危险命令" in json.dumps(data["findings"], ensure_ascii=False) or data["findings"]


def test_cmd_scan_flags_risky_text(capsys) -> None:
    rc = cli.main(["scan", 'password = "abcdefgh123"'])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["score"] == 40


def test_cmd_submit_decision(bridge_tmp, capsys) -> None:
    from bridge import store

    rc = cli.main(
        ["submit-decision", "--question", "选哪个？", "--options", "A) 方案甲 B) 方案乙"]
    )
    assert rc == 0
    data = store.read_agent_decision()
    assert data is not None
    assert data["question"] == "选哪个？"
    assert len(data["options"]) == 2
    store.clear_agent_decision()


def test_cmd_submit_decision_requires_two_options(bridge_tmp, capsys) -> None:
    rc = cli.main(["submit-decision", "--question", "q", "--options", "A) 只有一个"])
    assert rc == 2


def test_cmd_install_git_hook(tmp_path) -> None:
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    rc = cli.main(["install-git-hook", "--dir", str(tmp_path)])
    assert rc == 0
    hook = hooks / "pre-commit"
    assert hook.is_file()
    content = hook.read_text(encoding="utf-8")
    assert "DIFFGUARD_HOOK_SKIP" in content
    assert "score_text" in content


def test_cmd_install_git_hook_rejects_non_git_dir(tmp_path) -> None:
    rc = cli.main(["install-git-hook", "--dir", str(tmp_path)])
    assert rc == 1
