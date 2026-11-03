# -*- coding: utf-8 -*-
"""线程内的 token 用量累计。

为什么不改 `_chat` 的返回类型：所有调用方（RAG / 单 Agent / 多 Agent / 追问改写）
都只关心 content，改签名会牵一发动全身。这里用 threading.local 做旁路采集：
请求开始时 `reset()`，结束时 `snapshot()`。

FastAPI 的同步接口在线程池里执行，一个请求一个线程，所以线程内累计不会串。
多 worker 部署时每个进程各记各的，汇总要等 Langfuse / 日志系统。
"""
from __future__ import annotations

import threading
from typing import Any

_local = threading.local()
_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens")


def reset() -> None:
    _local.data = {key: 0 for key in _KEYS} | {"llm_calls": 0}


def add(usage: dict[str, Any] | None) -> None:
    data = getattr(_local, "data", None)
    if data is None or not isinstance(usage, dict):
        return
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            data[key] += value
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens") if isinstance(details, dict) else None
    if isinstance(cached, int):
        data["cached_tokens"] += cached
    data["llm_calls"] += 1


def snapshot() -> dict[str, int] | None:
    data = getattr(_local, "data", None)
    return dict(data) if data is not None else None
