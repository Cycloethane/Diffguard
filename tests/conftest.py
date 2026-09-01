# -*- coding: utf-8 -*-
"""pytest 全局夹具：项目根加入 sys.path、桥接目录重定向。"""

import sys
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest


@pytest.fixture
def bridge_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """把 bridge.store 的桥接目录重定向到临时目录，避免污染真实用户数据。"""
    from bridge import store

    target: Path = tmp_path / "bridge"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(store, "bridge_dir", lambda: target)
    return target
