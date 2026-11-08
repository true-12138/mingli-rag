# -*- coding: utf-8 -*-
"""HTTP 层的三个小闸门：鉴权、全局并发槽、每用户额度。

并发槽从「进程内信号量」换成 `gate.py`：没有 Redis 时退化为进程内，
配了 `MINGLI_REDIS_URL` 后多 worker / 多实例共享同一条容量线。
语义不变：满了立刻 429，不排队。
"""
from __future__ import annotations

import asyncio
import hmac
import os
from typing import Any

from fastapi import Header, HTTPException

import gate

# 兼容旧调用方 / 测试：实际槽数由 `MINGLI_ANSWER_SLOTS` 决定，默认 20。
MAX_CONCURRENCY = gate.answer_limit()
STREAM_CONCURRENCY = MAX_CONCURRENCY


def _slot() -> Any:
    """同步回答槽：`/chat`、`/v1/.../chat`。"""
    token = gate.get_gate().try_acquire("answer", gate.answer_limit(), gate.ANSWER_SLOT_TTL)
    if token is None:
        raise HTTPException(
            status_code=429,
            detail="服务繁忙，请稍后重试",
            headers={"Retry-After": "2"},
        )
    try:
        yield
    finally:
        gate.get_gate().release("answer", token)


async def _stream_slot() -> Any:
    """SSE 回答槽：与同步接口共用同一条全局容量线。"""
    try:
        token = await asyncio.to_thread(
            gate.get_gate().try_acquire,
            "answer",
            gate.answer_limit(),
            gate.ANSWER_SLOT_TTL,
        )
    except Exception as exc:  # noqa: BLE001 - 闸门异常不该拖垮请求
        raise HTTPException(status_code=503, detail="并发闸门暂不可用") from exc
    if token is None:
        raise HTTPException(
            status_code=429,
            detail="流式回答排队已满，请稍后重试",
            headers={"Retry-After": "3"},
        )
    try:
        yield
    finally:
        try:
            await asyncio.to_thread(gate.get_gate().release, "answer", token)
        except Exception:  # noqa: BLE001
            pass


def check_quota(
    x_anonymous_id: str | None = None, x_deepseek_key: str | None = None
) -> None:
    """每用户每日 LLM 次数。默认关闭；访客自带 key 不计数。

    单独抽成普通函数，是因为缓存命中不该扣额度：依赖 `_quota` 在进入处理函数
    前就执行，拿不到「是否命中缓存」的结果。`/chat` 两个端点在缓存 miss 后
    才调用这里。
    """
    if x_deepseek_key or gate.quota_limit() <= 0:
        return
    anon = (x_anonymous_id or "demo").strip()[:64] or "demo"
    ok, used = gate.take_quota(anon)
    if not ok:
        raise HTTPException(
            status_code=429,
            detail="今日免费额度已用完（{}/天），请明天再试或填入自己的 Key".format(
                gate.quota_limit()
            ),
            headers={
                "Retry-After": "3600",
                "X-Quota-Limit": str(gate.quota_limit()),
                "X-Quota-Used": str(used),
            },
        )


def _quota(
    x_anonymous_id: str | None = Header(default=None, alias="X-Anonymous-Id"),
    x_deepseek_key: str | None = Header(default=None, alias="X-DeepSeek-Key"),
) -> None:
    check_quota(x_anonymous_id, x_deepseek_key)


def _require_token(authorization: str | None = Header(default=None)) -> None:
    """可选 Bearer token：MINGLI_API_TOKEN 没配时直接放行。"""
    expected = os.environ.get("MINGLI_API_TOKEN")
    if not expected:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer token")
    if not hmac.compare_digest(authorization[7:].strip(), expected):
        raise HTTPException(status_code=401, detail="token 不正确")


def gate_info() -> dict[str, Any]:
    return gate.info()
