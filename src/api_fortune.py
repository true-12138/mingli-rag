# -*- coding: utf-8 -*-
"""排盘与解读接口：八字 / 星盘 / 塔罗。

边界和 `fortune/__init__.py` 里写的一致：

- **排盘是确定性计算**，不经过模型。同样的输入永远得到同一个盘；
- **解读**才调用模型，而且 prompt 里的盘面是服务端重新算出来的，
  不接受前端直接塞一张盘进来——否则模型看到什么就全由调用方决定了。

塔罗是例外里的细节：`seed` 不传时服务端生成一个具体 seed 并返回。
前端拿这张盘去请求解读时必须把 seed 带回来，否则会重新抽一次，
用户看到的牌和听到的解读就对不上了。

信息不全时——用户只说了年份、或者压根没说出生的钟点——`/intake`
返回需要补的字段，而不是给一个默认值把盘算出来。默认值只在可选字段上
使用，并且会明确列在 `defaults` / `warnings` 里。
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any, Literal

import requests
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fortune import draw_tarot, natal_chart, paipan_bazi
from fortune import intake, interpret
from fortune.intake import AstroRequest, BaziRequest, MODELS, TarotRequest
from guards import _quota, _require_token, _slot

logger = logging.getLogger("mingli.api.fortune")

router = APIRouter(
    prefix="/v1/fortune",
    tags=["fortune"],
    dependencies=[Depends(_require_token)],
)


# ---------- 请求模型 ----------
# 排盘参数模型定义在 fortune/intake.py，收集和校验共用同一份；
# 这里保留导入，外部代码仍然可以 from api_fortune import BaziRequest。

class IntakeRequest(BaseModel):
    """把「已知的排盘信息」交给服务端检查，缺什么就返回什么。"""

    kind: Literal["bazi", "astro", "tarot"]
    params: dict[str, Any] = Field(default_factory=dict)


class ReadRequest(BaseModel):
    kind: Literal["bazi", "astro", "tarot"]
    params: dict[str, Any]
    question: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=1000)


# ---------- 盘面计算 ----------

def _bazi_chart(req: BaziRequest) -> dict[str, Any]:
    return paipan_bazi(req.year, req.month, req.day, req.hour, req.minute, req.gender)


def _astro_chart(req: AstroRequest) -> dict[str, Any]:
    return natal_chart(
        req.year, req.month, req.day, req.hour, req.minute,
        tz=req.tz, lat=req.lat, lon=req.lon, city=req.city,
    )


def _tarot_chart(req: TarotRequest) -> dict[str, Any]:
    # 不传 seed 时固定下来再抽：否则「解读」那一步会抽到另一组牌。
    seed = req.seed if req.seed is not None else int(time.time_ns() % (2**32))
    return draw_tarot(n=req.n, seed=seed, spread=req.spread)


_MODELS = MODELS
_BUILDERS = {"bazi": _bazi_chart, "astro": _astro_chart, "tarot": _tarot_chart}


def _chart_from_params(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    """按 kind 重新校验并重算盘面；前端传进来的盘一概不用。

    参数不完整或不合法时返回 400，detail 里带 `fields`，
    调用方可以据此追问，而不是只拿到一句「参数不合法」。
    """
    builder = _BUILDERS.get(kind)
    if builder is None:
        raise HTTPException(status_code=400, detail="不支持的盘类型：%s" % kind)

    collected = intake.collect(kind, params)
    if collected["status"] != "ready":
        raise HTTPException(status_code=400, detail={
            "message": collected["message"],
            "need_input": True,
            "fields": collected["fields"],
        })
    try:
        parsed = _MODELS[kind].model_validate(collected["params"])
        return builder(parsed)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first.get("loc", ())) or "params"
        raise HTTPException(
            status_code=400, detail="排盘参数不合法：%s" % where
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={
            "message": str(exc),
            "need_input": True,
            "fields": intake.need_input(
                kind, collected["params"], ["year", "month", "day"],
                reason="calendar", message=str(exc),
                errors={"day": str(exc)},
            )["fields"],
        }) from exc


def _build_chart(req: BaziRequest | AstroRequest | TarotRequest) -> dict[str, Any]:
    if isinstance(req, BaziRequest):
        return _bazi_chart(req)
    if isinstance(req, AstroRequest):
        return _astro_chart(req)
    return _tarot_chart(req)


def _run(req: BaziRequest | AstroRequest | TarotRequest) -> dict[str, Any]:
    try:
        return _build_chart(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------- 接口 ----------

@router.post("/intake")
def post_intake(req: IntakeRequest) -> dict[str, Any]:
    """检查排盘信息是否齐全；不齐就返回「还缺什么」，不替用户猜。

    `status=ready` 时顺带返回算好的 `chart`：调用方不用再请求 /bazi 等接口，
    塔罗的 seed 也在这一步固定下来，展示的牌和之后解读用的是同一组。
    """
    collected = intake.collect(req.kind, req.params)
    if collected["status"] != "ready":
        return collected
    try:
        chart = _chart_from_params(req.kind, collected["params"])
    except HTTPException as exc:
        detail = exc.detail
        if exc.status_code != 400 or not isinstance(detail, dict):
            raise
        return {
            "status": "need_input",
            "kind": req.kind,
            "reason": "calendar",
            "known": collected["params"],
            "fields": detail.get("fields") or [],
            "message": detail.get("message") or "出生时间不合法，请检查年月日。",
        }
    return {**collected, "chart": chart}


@router.post("/bazi")
def post_bazi(req: BaziRequest) -> dict[str, Any]:
    """排八字盘。纯计算，不调模型，不走生成并发信号量。"""
    return _run(req)


@router.post("/astro")
def post_astro(req: AstroRequest) -> dict[str, Any]:
    """排西方本命盘（整宫制）。"""
    return _run(req)


@router.post("/tarot")
def post_tarot(req: TarotRequest) -> dict[str, Any]:
    """抽塔罗牌；响应里的 seed 请原样带回 `/read`。"""
    return _run(req)


@router.post("/read")
def read_fortune(
    req: ReadRequest,
    x_deepseek_key: str | None = Header(default=None),
    _: None = Depends(_quota),
    __: None = Depends(_slot),
) -> dict[str, Any]:
    """解读一张已经算好的盘。

    盘面由服务端按 `params` 重新计算，保证模型看到的和用户看到的是同一个。
    """
    chart = _chart_from_params(req.kind, req.params)
    key = (x_deepseek_key or "").strip() or None
    try:
        result = interpret.read(
            chart, question=req.question, user_note=req.note, api_key=key
        )
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        logger.warning("fortune read upstream failed kind=%s status=%s", req.kind, status)
        raise HTTPException(status_code=502, detail="上游模型调用失败（%s）" % status) from exc
    except RuntimeError as exc:
        logger.warning("fortune read configuration error: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception:
        logger.exception("fortune read failed kind=%s", req.kind)
        raise HTTPException(status_code=500, detail="解读失败") from exc
    logger.info("fortune read kind=%s sections=%d", req.kind, len(result.get("sections") or []))
    return result
