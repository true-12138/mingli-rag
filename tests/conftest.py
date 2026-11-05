# -*- coding: utf-8 -*-
"""测试默认环境。

- API 鉴权默认拒绝；测试里显式打开 `MINGLI_ALLOW_OPEN`，否则每个旧用例
  都要先配 token。
- 每日额度默认关闭，避免 `/chat` 用例去碰真实的 `data/app.sqlite3`；
  额度相关用例自己打开并注入内存库。
"""
import pytest


@pytest.fixture(autouse=True)
def _default_api_env(monkeypatch):
    monkeypatch.setenv("MINGLI_ALLOW_OPEN", "1")
    monkeypatch.setenv("MINGLI_QUOTA_ENABLED", "0")
