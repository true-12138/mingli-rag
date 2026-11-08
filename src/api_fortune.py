# -*- coding: utf-8 -*-
"""排盘与解读接口：八字 / 星盘 / 塔罗。

边界和 `fortune/__init__.py` 里写的一致：

- **排盘是确定性计算**，不经过模型。同样的输入永远得到同一个盘；
- **解读**才调用模型，而且 prompt 里的盘面是服务端重新算出来的，
  不接受前端直接塞一张盘进来——否则模型看到什么就全由调用方决定了。

塔罗是例外里的细节：`seed` 不传时服务端生成一个具体 seed 并返回。
前端拿这张盘去请求解读时必须把 seed 带回来，否则会重新抽一次，
用户看到的牌和听到的解读就对不上了。
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
from fortune import interpret
from guards import _quota, _require_token, _slot

logger = logging.getLogger("mingli.api.fortune")

router = APIRouter(
    prefix="/v1/fortune",
    tags=["fortune"],
    dependencies=[Depends(_require_token)],
)


# ---------- 请求模型 ----------

class BirthRequest(BaseModel):
    """出生地当地公历时间；日期范围限制在历法库算得准的区间内。"""

    year: int = Field(ge=1900, le=2100)
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    hour: int = Field(default=0, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)


class BaziRequest(BirthRequest):
    gender: Literal["male", "female"] = "male"


class AstroRequest(BirthRequest):
    tz: float = Field(default=8.0, ge=-12, le=14)
    lat: float = Field(default=39.90, ge=-90, le=90)
    lon: float = Field(default=116.40, ge=-180, le=180)
    city: str = Field(default="北京", max_length=40)


class TarotRequest(BaseModel):
    n: int = Field(default=3, ge=1, le=10)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)
    spread: Literal["single", "three", "cross"] | None = None


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


_MODELS: dict[str, type[BaseModel]] = {
    "bazi": BaziRequest,
    "astro": AstroRequest,
    "tarot": TarotRequest,
}
_BUILDERS = {"bazi": _bazi_chart, "astro": _astro_chart, "tarot": _tarot_chart}


def _chart_from_params(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    """按 kind 重新校验并重算盘面；前端传进来的盘一概不用。"""
    model = _MODELS.get(kind)
    builder = _BUILDERS.get(kind)
    if model is None or builder is None:
        raise HTTPException(status_code=400, detail="不支持的盘类型：%s" % kind)
    try:
        parsed = model.model_validate(params or {})
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first.get("loc", ())) or "params"
        raise HTTPException(
            status_code=400, detail="排盘参数不合法：%s" % where
        ) from exc
    try:
        return builder(parsed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
