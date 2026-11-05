# -*- coding: utf-8 -*-
"""FastAPI 封装：把 RAG / 单 Agent / 多 Agent 暴露成 HTTP 接口。

设计约束（和 Streamlit 版本保持一致）：
- key 只从环境变量或请求头读，绝不写进日志、响应或仓库；
- 检索/生成都是阻塞调用，接口用同步 def，让 FastAPI 丢到线程池；
- 并发用信号量兜底，超了直接 429，不让 DeepSeek 并发把进程拖死；
- trace 只留最近 N 条在内存里，进程重启即清空——真正的持久化 trace 交给 Langfuse。

启动：
    python src/api.py
    # 或
    uvicorn api:app --app-dir src --host 0.0.0.0 --port 8000

环境变量：
    DEEPSEEK_API_KEY      必填，服务端 key
    MINGLI_API_TOKEN      强烈建议设置；未设置时默认拒绝访问（503）
    MINGLI_ALLOW_OPEN     仅本地开发：设为 1 才允许无 token 访问
    MINGLI_MAX_CONCURRENCY 可选，默认 4
    MINGLI_TRACE_CACHE    可选，内存里保留的 trace 条数，默认 200
    MINGLI_QUOTA_USER_DAILY / _IP_DAILY / _GLOBAL_DAILY
                          可选，服务端 key 的每日额度，默认 20 / 60 / 300
    MINGLI_TRUST_PROXY    可选，设为 1 时信任 X-Forwarded-For 取客户端 IP
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent
import agent_multi
import api_conversations
import quotas
import rag
import retrieval
import usage
from guards import (
    MAX_CONCURRENCY,
    _SLOTS,
    _quota_gate,
    _refund_quota,
    _require_token,
    _slot,
)
from observability import (
    METRICS,
    configure_logging,
    current_request_id,
    install_observability,
)

API_VERSION = "1.0.0"
logger = logging.getLogger("mingli.api")

MAX_TRACES = int(os.environ.get("MINGLI_TRACE_CACHE", "200"))

_TRACES: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_TRACES_LOCK = threading.Lock()

app = FastAPI(
    title="命理古籍 RAG API",
    version=API_VERSION,
    description="45 部古籍 / 8,681 chunk 的检索、单 Agent、多 Agent 与多轮对话接口。",
)
app.include_router(api_conversations.router)
# request id、结构化日志、/metrics 共用这一个中间件
install_observability(app)


# ---------- 请求 / 响应模型 ----------

class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    mode: Literal["rag", "agent", "multi"] = "rag"
    top_k: int = Field(5, ge=1, le=10)
    max_steps: int = Field(6, ge=1, le=10)
    # 前端最多带 3 轮；这里放宽到 20 条，normalize_history 会再裁剪
    history: list[HistoryTurn] = Field(default_factory=list, max_length=20)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question 不能为空")
        return value


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    trace_id: str
    mode: Literal["rag", "agent", "multi"]
    question: str
    elapsed_ms: float
    can_answer: bool | None = None
    answer: str = ""
    citations: list[Any] = Field(default_factory=list)
    # chunk_id 在 corpus.build() 里被重编成 1 起的整数，这里如实声明
    citations_chunk_ids: list[int] = Field(default_factory=list)
    invalid_citations: list[Any] = Field(default_factory=list)
    invalid_output: bool = False
    refusal_reason: str | None = None
    retrieved_chunk_ids: list[int] = Field(default_factory=list)
    rewritten_question: str | None = None
    history_turns: int = 0
    llm_calls: int = 0
    usage: dict[str, Any] | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)
    steps: int | None = None


class RetrieveRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    mode: Literal["dense", "bm25", "rrf"] = "rrf"
    top_k: int = Field(5, ge=1, le=10)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question 不能为空")
        return value


class RetrieveHit(BaseModel):
    chunk_id: int
    text: str
    meta: dict[str, Any]
    score: float


class RetrieveResponse(BaseModel):
    trace_id: str
    question: str
    mode: Literal["dense", "bm25", "rrf"]
    top_k: int
    hits: list[RetrieveHit]
    elapsed_ms: float


class TraceResponse(BaseModel):
    trace_id: str
    created_at: str
    mode: str
    question: str
    elapsed_ms: float
    result: dict[str, Any]


# ---------- trace ----------

def _remember(trace_id: str, mode: str, question: str, elapsed_ms: float,
              result: dict[str, Any]) -> None:
    payload = {
        "trace_id": trace_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": mode,
        "question": question,
        "elapsed_ms": round(elapsed_ms, 1),
        "result": result,
    }
    with _TRACES_LOCK:
        _TRACES[trace_id] = payload
        _TRACES.move_to_end(trace_id)
        while len(_TRACES) > MAX_TRACES:
            _TRACES.popitem(last=False)


def _history_payload(history: list[HistoryTurn]) -> list[dict[str, str]]:
    return [{"role": h.role, "content": h.content} for h in history]


def _api_key(x_deepseek_key: str | None) -> str | None:
    # 访客自带 key 只用于这一次请求；不落日志、不进 trace。
    return (x_deepseek_key or "").strip() or None


# ---------- 接口 ----------

@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "mingli-rag-api",
        "version": API_VERSION,
        "docs": "/docs",
        "endpoints": [
            "/health",
            "/ready",
            "/metrics",
            "/chat",
            "/retrieve",
            "/trace/{trace_id}",
            "/v1/conversations",
            "/v1/conversations/{conversation_id}/chat",
            "/v1/conversations/{conversation_id}/runs",
            "/v1/runs/{run_id}",
            "/v1/runs/{run_id}/feedback",
        ],
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "mingli-rag-api",
        "version": API_VERSION,
        "chunks": len(retrieval.chunks),
        "embedding_rows": int(retrieval.embeds.shape[0]),
        "embedding_dim": int(retrieval.embeds.shape[1]),
        "embedding_model": retrieval.MODEL_ID,
        "embedding_loaded": bool(getattr(retrieval.model, "loaded", False)),
        "modes": ["rag", "agent", "multi"],
        "retrieval_modes": ["dense", "bm25", "rrf"],
        "max_concurrency": MAX_CONCURRENCY,
        "trace_cache": len(_TRACES),
    }


@app.get("/ready")
def ready() -> JSONResponse:
    """就绪探针：配置齐全、索引一致时才返回 200。

    和 `/health` 的分工：
    - `/health` 是存活探针，进程还在就给 200，用于 Docker 判断要不要重启；
    - `/ready` 是就绪探针，缺 key / 未配置 token / 索引不一致时给 503，
      负载均衡据此摘流量。

    这里**不加载** BGE-M3：加载要下载几 GB 权重，探针不能触发它。
    模型按需加载是刻意的，所以 `embedding_loaded=false` 不算未就绪。
    """
    problems: list[str] = []
    if not (os.environ.get("DEEPSEEK_API_KEY") or "").strip():
        problems.append("DEEPSEEK_API_KEY 未配置（访客自带 key 仍可用，但服务端无法兜底）")

    token_configured = bool((os.environ.get("MINGLI_API_TOKEN") or "").strip())
    allow_open = os.environ.get("MINGLI_ALLOW_OPEN", "").strip() == "1"
    if not token_configured and not allow_open:
        problems.append(
            "MINGLI_API_TOKEN 未配置，服务默认拒绝访问；"
            "仅本地开发可设 MINGLI_ALLOW_OPEN=1"
        )

    n_chunks = len(retrieval.chunks)
    n_rows = int(retrieval.embeds.shape[0])
    if n_chunks == 0:
        problems.append("语料为空")
    elif n_rows != n_chunks:
        problems.append("embeddings 行数 {} 与语料 {} 不一致".format(n_rows, n_chunks))

    payload = {
        "status": "not_ready" if problems else "ready",
        "service": "mingli-rag-api",
        "version": API_VERSION,
        "problems": problems,
        "chunks": n_chunks,
        "embedding_rows": n_rows,
        "embedding_loaded": bool(getattr(retrieval.model, "loaded", False)),
        "server_key_configured": bool(
            (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
        ),
        "auth": "token" if token_configured else ("open" if allow_open else "deny"),
        "quota_enabled": quotas.enabled(),
    }
    return JSONResponse(status_code=503 if problems else 200, content=payload)


@app.get("/metrics", response_class=PlainTextResponse, tags=["ops"])
def metrics() -> str:
    """Prometheus 文本格式。只暴露计数和直方图，不含任何用户内容。"""
    return METRICS.render()


@app.get("/trace/{trace_id}", response_model=TraceResponse)
def get_trace(trace_id: str, _: None = Depends(_require_token)) -> dict[str, Any]:
    with _TRACES_LOCK:
        payload = _TRACES.get(trace_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="trace 不存在或已被淘汰")
    return payload


@app.post("/retrieve", response_model=RetrieveResponse)
def retrieve(req: RetrieveRequest, _: None = Depends(_require_token)) -> dict[str, Any]:
    started = time.perf_counter()
    trace_id = uuid.uuid4().hex
    try:
        hits = retrieval.retrieve_one(req.question, top_k=req.top_k, mode=req.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("retrieve failed trace_id=%s", trace_id)
        raise HTTPException(status_code=500, detail="检索失败") from exc

    elapsed_ms = (time.perf_counter() - started) * 1000
    out = {
        "trace_id": trace_id,
        "question": req.question,
        "mode": req.mode,
        "top_k": req.top_k,
        "hits": [
            {
                "chunk_id": h["chunk_id"],
                "text": h["text"],
                "meta": h["meta"],
                "score": float(h["rrf_score"]),
            }
            for h in hits
        ],
        "elapsed_ms": round(elapsed_ms, 1),
    }
    _remember(trace_id, "retrieve", req.question, elapsed_ms, out)
    logger.info("retrieve mode=%s top_k=%d elapsed_ms=%.0f", req.mode, req.top_k, elapsed_ms)
    return out


@app.post("/chat", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    x_deepseek_key: str | None = Header(default=None),
    _: None = Depends(_require_token),
    # 先拿并发槽再扣额度：服务繁忙被 429 时不应该消耗用户当天的次数
    __: None = Depends(_slot),
    quota: quotas.Reservation | None = Depends(_quota_gate),
) -> dict[str, Any]:
    started = time.perf_counter()
    trace_id = uuid.uuid4().hex
    history = _history_payload(req.history)
    key = _api_key(x_deepseek_key)
    usage.reset()

    try:
        if req.mode == "rag":
            result = rag.answer(
                req.question, top_k=req.top_k, api_key=key, history=history
            )
        elif req.mode == "agent":
            result = agent.agent_answer(
                req.question, max_steps=req.max_steps, api_key=key, history=history
            )
        else:
            result = agent_multi.agent_answer(
                req.question, max_steps=req.max_steps, api_key=key, history=history
            )
    except requests.HTTPError as exc:
        _refund_quota(quota)
        status = exc.response.status_code if exc.response is not None else 502
        logger.warning("upstream failed trace_id=%s status=%s", trace_id, status)
        raise HTTPException(status_code=502, detail="上游模型调用失败（%s）" % status) from exc
    except RuntimeError as exc:
        # 没配 DEEPSEEK_API_KEY 时 rag._get_api_key 抛这个
        _refund_quota(quota)
        logger.warning("configuration error trace_id=%s: %s", trace_id, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        _refund_quota(quota)
        logger.exception("chat failed trace_id=%s mode=%s", trace_id, req.mode)
        raise HTTPException(status_code=500, detail="生成失败") from exc

    elapsed_ms = (time.perf_counter() - started) * 1000
    out = dict(result)
    tokens = usage.snapshot()
    METRICS.observe_llm(tokens)
    out.update({
        "trace_id": trace_id,
        "mode": req.mode,
        "question": req.question,
        "elapsed_ms": round(elapsed_ms, 1),
        "usage": tokens,
    })
    _remember(trace_id, req.mode, req.question, elapsed_ms, out)
    logger.info(
        "chat mode=%s elapsed_ms=%.0f llm_calls=%s tokens=%s can_answer=%s trace_id=%s",
        req.mode, elapsed_ms, out.get("llm_calls"),
        (tokens or {}).get("total_tokens"), out.get("can_answer"), trace_id,
    )
    return out


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error path=%s", request.url.path)
    # 把 request id 回给调用方，用户报障时能直接对上日志
    return JSONResponse(
        status_code=500,
        content={"detail": "服务内部错误", "request_id": current_request_id()},
    )


if __name__ == "__main__":
    import uvicorn

    configure_logging()
    uvicorn.run(
        app,
        host=os.environ.get("MINGLI_HOST", "0.0.0.0"),
        port=int(os.environ.get("MINGLI_PORT", "8000")),
        log_level="info",
    )
