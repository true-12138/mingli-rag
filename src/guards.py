# -*- coding: utf-8 -*-
"""HTTP 层的三个小闸门：鉴权、每日额度与并发上限。

鉴权默认拒绝：没配置 `MINGLI_API_TOKEN` 时，除显式设置
`MINGLI_ALLOW_OPEN=1`（只用于本地开发/测试）外，所有接口返回 503。
这样「忘了配 token 就整个服务公开」不会再发生。
"""
from __future__ import annotations

import hmac
import os
import threading
from typing import Any

from fastapi import Header, HTTPException, Request

import quotas

MAX_CONCURRENCY = int(os.environ.get("MINGLI_MAX_CONCURRENCY", "4"))
_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENCY)


def _require_token(authorization: str | None = Header(default=None)) -> None:
    """Bearer token 闸门；未配置时默认拒绝，除非显式允许开放访问。"""
    expected = (os.environ.get("MINGLI_API_TOKEN") or "").strip()
    if expected:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="缺少 Bearer token")
        if not hmac.compare_digest(authorization[7:].strip(), expected):
            raise HTTPException(status_code=401, detail="token 不正确")
        return

    if os.environ.get("MINGLI_ALLOW_OPEN", "").strip() == "1":
        return

    raise HTTPException(
        status_code=503,
        detail=(
            "服务未配置 MINGLI_API_TOKEN，已默认拒绝访问；"
            "请设置 token，仅本地开发可设 MINGLI_ALLOW_OPEN=1"
        ),
    )


def client_ip(request: Request) -> str:
    """取调用方 IP。

    只有在反向代理后面（Nginx/LB）才信任 `X-Forwarded-For`，否则客户端可以
    随便伪造它来绕过单 IP 额度。部署时设置 `MINGLI_TRUST_PROXY=1`。
    """
    if os.environ.get("MINGLI_TRUST_PROXY", "").strip() == "1":
        forwarded = (request.headers.get("x-forwarded-for") or "").strip()
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _quota_gate(
    request: Request,
    x_deepseek_key: str | None = Header(default=None),
    x_anonymous_id: str | None = Header(default=None),
) -> quotas.Reservation | None:
    """占用每日额度；超限直接 429，并告诉调用方什么时候重置。"""
    try:
        return quotas.consume(
            anonymous_id=x_anonymous_id,
            ip=client_ip(request),
            visitor_key=(x_deepseek_key or "").strip() or None,
        )
    except quotas.QuotaExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={
                "Retry-After": str(exc.retry_after),
                "X-Quota-Limit": str(exc.limit),
                "X-Quota-Remaining": str(exc.remaining),
            },
        ) from exc


def _refund_quota(reservation: quotas.Reservation | None) -> None:
    quotas.refund(reservation)


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
