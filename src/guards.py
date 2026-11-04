# -*- coding: utf-8 -*-
"""HTTP 层的两个小闸门：鉴权与并发上限。

原来写在 `api.py` 里；第 2 步新增 `/v1` 接口后两套接口都要用，
所以抽出来共用，逻辑没有变化。
"""
from __future__ import annotations

import hmac
import os
import threading
from typing import Any

from fastapi import Header, HTTPException

MAX_CONCURRENCY = int(os.environ.get("MINGLI_MAX_CONCURRENCY", "4"))
_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENCY)


def _require_token(authorization: str | None = Header(default=None)) -> None:
    """可选 Bearer token：MINGLI_API_TOKEN 没配时直接放行。"""
    expected = os.environ.get("MINGLI_API_TOKEN")
    if not expected:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer token")
    if not hmac.compare_digest(authorization[7:].strip(), expected):
        raise HTTPException(status_code=401, detail="token 不正确")


def _slot() -> Any:
    """限制同时在跑的生成请求；超限立刻返回 429，而不是排队把内存吃满。"""
    if not _SLOTS.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail="服务繁忙，请稍后重试",
            headers={"Retry-After": "2"},
        )
    try:
        yield
    finally:
        _SLOTS.release()
