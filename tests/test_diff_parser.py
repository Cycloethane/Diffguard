# -*- coding: utf-8 -*-
"""core.diff_parser 单元测试：严格解析、容错解析、风险标记、辅助函数。"""

from core.diff_parser import (
    build_title,
    compute_risk_level,
    is_new_file,
    parse_diff,
    parse_diff_with_status,
    render_file_summary,
)

DIFF_MODIFIED_ENV = """\
diff --git a/config/prod.env b/config/prod.env
index 1111111..2222222 100644
--- a/config/prod.env
+++ b/config/prod.env
@@ -1,2 +1,3 @@
 BASE=1
-API_KEY="abcdefgh123456"
+API_KEY="abcdefgh12345678"
+NEW=2
"""

DIFF_DELETED = """\
diff --git a/legacy.py b/legacy.py
deleted file mode 100644
index 3333333..0000000
--- a/legacy.py
+++ /dev/null
@@ -1,1 +0,0 @@
-print("bye")
"""

DIFF_ADDED = """\
diff --git a/new_module.py b/new_module.py
new file mode 100644
index 0000000..4444444
--- /dev/null
+++ b/new_module.py
@@ -0,0 +1,2 @@
+import os
+print("hi")
"""

# hunk 头声明 5 行但只有 1 行 —— unidiff 严格解析必然失败，走容错解析
DIFF_TRUNCATED = """\
diff --git a/trunc.py b/trunc.py
index 1111111..2222222 100644
--- a/trunc.py
+++ b/trunc.py
@@ -1,5 +1,5 @@
+only one line remains
"""


def test_parse_strict_modified_with_flags() -> None:
    files, status = parse_diff_with_status(DIFF_MODIFIED_ENV)
    assert status["strict"] is True
    assert status["lenient"] is False
    assert len(files) == 1
    info = files[0]
    assert info["file_path"] == "config/prod.env"
    assert info["change_type"] == "modified"
    assert info["additions"] == 2
    assert info["deletions"] == 1
    assert "配置文件变更" in info["risk_flags"]
    assert "疑似硬编码密钥" in info["risk_flags"]


def test_parse_deleted_file() -> None:
    files = parse_diff(DIFF_DELETED)
    assert len(files) == 1
    info = files[0]
    assert info["change_type"] == "deleted"
    assert info["deletions"] == 1
    assert "文件删除" in info["risk_flags"]
    assert not is_new_file(info)


def test_parse_added_file() -> None:
    files = parse_diff(DIFF_ADDED)
    assert len(files) == 1
    info = files[0]
    assert info["change_type"] == "added"
    assert info["additions"] == 2
    assert is_new_file(info)


def test_parse_truncated_falls_back_to_lenient() -> None:
    files, status = parse_diff_with_status(DIFF_TRUNCATED)
    assert status["strict"] is False
    assert status["lenient"] is True
    assert len(files) == 1
    assert files[0]["file_path"] == "trunc.py"
    assert files[0]["additions"] == 1


def test_parse_empty_text() -> None:
    files, status = parse_diff_with_status("")
    assert files == []
    assert status["strict"] is False
    assert status["lenient"] is False


def test_dependency_flag() -> None:
    diff = (
        "diff --git a/requirements.txt b/requirements.txt\n"
        "index 111..222 100644\n"
        "--- a/requirements.txt\n"
        "+++ b/requirements.txt\n"
        "@@ -1,2 +1,2 @@\n"
        " customtkinter==5.2.1\n"
        "-unidiff==0.7.4\n"
        "+unidiff==0.7.5\n"
    )
    files = parse_diff(diff)
    assert "依赖变更" in files[0]["risk_flags"]


def test_risk_level_and_title_summary() -> None:
    files = parse_diff(DIFF_MODIFIED_ENV)
    # 密钥 30 + 配置 20 + 风险文件 2 + 规模 4 = 56 → medium
    assert compute_risk_level(files) == "medium"
    assert build_title(files) == "修改 config/prod.env"
    summary = render_file_summary(files[0])
    assert "config/prod.env" in summary
    assert "🔴" in summary
