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
    MINGLI_API_TOKEN      可选，设置后所有接口要求 Bearer token
    MINGLI_MAX_CONCURRENCY 可选，默认 4
    MINGLI_TRACE_CACHE    可选，内存里保留的 trace 条数，默认 200
"""
from __future__ import annotations

import asyncio
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
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent
import agent_multi
import api_conversations
import api_fortune
import gate
import llm
import rag
import retrieval
import semcache
import sse
import usage
from db.base import db_info
from guards import (
    MAX_CONCURRENCY,
    STREAM_CONCURRENCY,
    _require_token,
    _slot,
    _stream_slot,
    check_quota,
    gate_info,
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
app.include_router(api_fortune.router)
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


class ChunkLookupRequest(BaseModel):
    """按 chunk_id 批量取原文，给前端的引用 chip 展开用。"""

    ids: list[int] = Field(min_length=1, max_length=20)


class ChunkOut(BaseModel):
    chunk_id: int
    book: str = ""
    volume: str = ""
    chapter: str = ""
    title: str = ""
    text: str = ""


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


def _cache_allowed(
    req: ChatRequest,
    history: list[dict[str, str]],
    api_key: str | None,
    x_no_cache: str | None,
) -> bool:
    """语义缓存只接单轮 RAG。

    - agent / multi 的答案带工具轨迹与步数，不能按问题复用；
    - 有历史时同一句问题的含义可能不同；
    - 访客自带 key 不缓存，避免拿别人的结果冒充自己 key 的输出；
    - `X-No-Cache: 1` 给压测和调试留后门。
    """
    if (x_no_cache or "").strip().lower() not in ("", "0", "false", "no"):
        return False
    return req.mode == "rag" and not history and api_key is None


# ---------- 接口 ----------

@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "mingli-rag-api",
        "version": API_VERSION,
        "docs": "/docs",
        "endpoints": [
            "/health",
            "/metrics",
            "/v1/events",
            "/chat",
            "/chat/stream",
            "/retrieve",
            "/chunks",
            "/trace/{trace_id}",
            "/v1/conversations",
            "/v1/conversations/{conversation_id}/chat",
            "/v1/conversations/{conversation_id}/runs",
            "/v1/runs/{run_id}",
            "/v1/runs/{run_id}/feedback",
            "/v1/memories",
            "/v1/fortune/bazi",
            "/v1/fortune/astro",
            "/v1/fortune/tarot",
            "/v1/fortune/read",
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
        "embedding_backend": getattr(retrieval, "EMBED_BACKEND", "unknown"),
        "modes": ["rag", "agent", "multi"],
        "retrieval_modes": ["dense", "bm25", "rrf"],
        "max_concurrency": MAX_CONCURRENCY,
        "stream_concurrency": STREAM_CONCURRENCY,
        "concurrency_gate": gate_info(),
        "semantic_cache": semcache.info(),
        "database": db_info(),
        "llm_keys": llm.default_client().key_count(),
        "llm_model": llm.MODEL,
        "llm_url": llm.DEEPSEEK_URL,
        "streaming": True,
        "trace_cache": len(_TRACES),
    }


_CHUNK_INDEX: dict[int, dict[str, Any]] | None = None
_CHUNK_INDEX_LOCK = threading.Lock()


def _chunk_index() -> dict[int, dict[str, Any]]:
    """chunk_id → 语料行。只建一次；语料在进程启动后不变。"""
    global _CHUNK_INDEX
    if _CHUNK_INDEX is None:
        with _CHUNK_INDEX_LOCK:
            if _CHUNK_INDEX is None:
                _CHUNK_INDEX = {int(c["chunk_id"]): c for c in retrieval.chunks}
    return _CHUNK_INDEX


@app.post("/chunks", response_model=list[ChunkOut])
def lookup_chunks(
    req: ChunkLookupRequest,
    _: None = Depends(_require_token),
) -> list[dict[str, Any]]:
    """引用展开：前端拿到 citations_chunk_ids 后按 id 取书名与原文。

    只读、不调模型，所以不走生成并发信号量；查不到的 id 直接略过。
    """
    index = _chunk_index()
    out = []
    for cid in dict.fromkeys(req.ids):  # 保序去重
        chunk = index.get(int(cid))
        if not chunk:
            continue
        meta = chunk.get("meta") or {}
        parts = [str(meta.get(k) or "").strip() for k in ("book", "volume", "chapter")]
        out.append({
            "chunk_id": int(cid),
            "book": str(meta.get("book") or ""),
            "volume": str(meta.get("volume") or ""),
            "chapter": str(meta.get("chapter") or ""),
            "title": "《{}》".format("·".join(p for p in parts if p)) if any(parts)
            else "《未标书名》",
            "text": str(chunk.get("chunk_text") or "").strip(),
        })
    return out


@app.get("/metrics", response_class=PlainTextResponse, tags=["ops"])
def metrics() -> str:
    """Prometheus 文本格式。只暴露计数和直方图，不含任何用户内容。"""
    lines = METRICS.render().rstrip("\n").split("\n")
    lines += gate.render_metrics()
    lines += semcache.render_metrics()
    return "\n".join(lines) + "\n"


@app.get("/v1/events")
async def events(
    request: Request,
    _: None = Depends(_require_token),
) -> StreamingResponse:
    """轻量 SSE 连接流：只保持连接、发心跳，不触发模型调用。

    200 连接压测挂在这里，回答槽另算。真正的通知（会话完成、后台任务）
    以后可以复用这条通道，往队列里推事件即可。
    """
    heartbeat = min(SSE_HEARTBEAT, 15.0)

    async def gen():
        yield sse.sse_frame("hello", {"ok": True, "ts": round(time.time(), 3)})
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(heartbeat)
            yield ": keep-alive\n\n"

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers=dict(sse.SSE_HEADERS)
    )


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
    x_anonymous_id: str | None = Header(default=None, alias="X-Anonymous-Id"),
    x_no_cache: str | None = Header(default=None, alias="X-No-Cache"),
    _: None = Depends(_require_token),
    __: None = Depends(_slot),
) -> dict[str, Any]:
    started = time.perf_counter()
    trace_id = uuid.uuid4().hex
    history = _history_payload(req.history)
    key = _api_key(x_deepseek_key)
    usage.reset()

    cache_ok = _cache_allowed(req, history, key, x_no_cache)
    cached: dict[str, Any] | None = None
    query_vec = None
    if cache_ok:
        cached, query_vec = semcache.lookup(req.question, req.mode, req.top_k)
    if cached is not None:
        elapsed_ms = (time.perf_counter() - started) * 1000
        out = dict(cached)
        out.update({
            "trace_id": trace_id,
            "mode": req.mode,
            "question": req.question,
            "elapsed_ms": round(elapsed_ms, 1),
            "usage": usage.snapshot(),
        })
        _remember(trace_id, req.mode, req.question, elapsed_ms, out)
        logger.info(
            "chat cache_hit kind=%s similarity=%s elapsed_ms=%.0f trace_id=%s",
            out.get("cache_kind"), out.get("cache_similarity"), elapsed_ms, trace_id,
        )
        return out

    check_quota(x_anonymous_id, x_deepseek_key)

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
        status = exc.response.status_code if exc.response is not None else 502
        logger.warning("upstream failed trace_id=%s status=%s", trace_id, status)
        raise HTTPException(status_code=502, detail="上游模型调用失败（%s）" % status) from exc
    except RuntimeError as exc:
        # 没配 DEEPSEEK_API_KEY 时 rag._get_api_key 抛这个
        logger.warning("configuration error trace_id=%s: %s", trace_id, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
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
    if cache_ok:
        semcache.remember(
            req.question, req.mode, req.top_k, result, query_vec=query_vec
        )
    _remember(trace_id, req.mode, req.question, elapsed_ms, out)
    logger.info(
        "chat mode=%s elapsed_ms=%.0f llm_calls=%s tokens=%s can_answer=%s trace_id=%s",
        req.mode, elapsed_ms, out.get("llm_calls"),
        (tokens or {}).get("total_tokens"), out.get("can_answer"), trace_id,
    )
    return out


# ---------- 流式接口 ----------
#
# 事件契约（docs/ROADMAP-v2.md §3）：
#   step  {"agent","tool","args","ok","chunk_ids","error"}   一次工具调用完成
#   stage {"agent","detail"}                                 多 Agent 阶段推进
#   delta {"text"}                                           正文增量
#   done  {完整 ChatResponse}                                终稿（以此为准）
#   error {"message","request_id"}                            失败
#
# `delta` 是预览：拒答归一化等终稿处理可能改正文，前端收到 `done` 后
# 用 done.answer 覆盖消息正文即可，不需要重连。

SSE_HEARTBEAT = sse.SSE_HEARTBEAT
_sse_frame = sse.sse_frame


@app.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    x_deepseek_key: str | None = Header(default=None),
    x_anonymous_id: str | None = Header(default=None, alias="X-Anonymous-Id"),
    x_no_cache: str | None = Header(default=None, alias="X-No-Cache"),
    _: None = Depends(_require_token),
    __: None = Depends(_stream_slot),
) -> StreamingResponse:
    """和 `/chat` 同样的入参，按 SSE 逐 token 返回。"""
    started = time.perf_counter()
    trace_id = uuid.uuid4().hex
    history = _history_payload(req.history)
    key = _api_key(x_deepseek_key)
    queue: "asyncio.Queue[str | None]" = asyncio.Queue()
    client = llm.default_client()

    cache_ok = _cache_allowed(req, history, key, x_no_cache)
    cached: dict[str, Any] | None = None
    query_vec = None
    if cache_ok:
        # 编码可能走本地 BGE-M3 或远端 embedding 服务，别占事件循环
        cached, query_vec = await asyncio.to_thread(
            semcache.lookup, req.question, req.mode, req.top_k
        )
    if cached is not None:
        elapsed_ms = (time.perf_counter() - started) * 1000
        out = dict(cached)
        out.update({
            "trace_id": trace_id,
            "mode": req.mode,
            "question": req.question,
            "elapsed_ms": round(elapsed_ms, 1),
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cached_tokens": 0,
                "llm_calls": 0,
            },
        })
        _remember(trace_id, req.mode, req.question, elapsed_ms, out)
        logger.info(
            "chat_stream cache_hit kind=%s similarity=%s elapsed_ms=%.0f trace_id=%s",
            out.get("cache_kind"), out.get("cache_similarity"), elapsed_ms, trace_id,
        )

        async def cached_source():
            yield _sse_frame("delta", {"text": out.get("answer", "")})
            yield _sse_frame("done", out)

        return StreamingResponse(
            cached_source(), media_type="text/event-stream", headers=sse.SSE_HEADERS
        )

    # 缓存未命中才扣额度：命中缓存不消耗 LLM 次数
    check_quota(x_anonymous_id, x_deepseek_key)

    def push(event: str, data: dict[str, Any]) -> None:
        queue.put_nowait(_sse_frame(event, data))

    def on_delta(text: str) -> None:
        push("delta", {"text": text})

    def on_step(payload: dict[str, Any]) -> None:
        push("step", payload)

    def on_stage(payload: dict[str, Any]) -> None:
        push("stage", payload)

    async def produce() -> None:
        try:
            if req.mode == "rag":
                result = await rag.answer_stream(
                    req.question, top_k=req.top_k, api_key=key, history=history,
                    on_delta=on_delta, on_step=on_step, client=client,
                )
            elif req.mode == "agent":
                result = await agent.agent_answer_stream(
                    req.question, max_steps=req.max_steps, api_key=key,
                    history=history, on_delta=on_delta, on_step=on_step, client=client,
                )
            else:
                result = await agent_multi.agent_answer_stream(
                    req.question, max_steps=req.max_steps, api_key=key, history=history,
                    on_delta=on_delta, on_step=on_step, on_stage=on_stage, client=client,
                )
            elapsed_ms = (time.perf_counter() - started) * 1000
            out = dict(result)
            out.update({
                "trace_id": trace_id,
                "mode": req.mode,
                "question": req.question,
                "elapsed_ms": round(elapsed_ms, 1),
            })
            tokens = out.get("usage")
            if tokens:
                METRICS.observe_llm(tokens)
            if cache_ok:
                await asyncio.to_thread(
                    semcache.remember,
                    req.question,
                    req.mode,
                    req.top_k,
                    result,
                    query_vec,
                )
            _remember(trace_id, req.mode, req.question, elapsed_ms, out)
            logger.info(
                "chat_stream mode=%s elapsed_ms=%.0f llm_calls=%s can_answer=%s trace_id=%s",
                req.mode, elapsed_ms, out.get("llm_calls"), out.get("can_answer"), trace_id,
            )
            push("done", out)
        except llm.LLMError as exc:
            logger.warning(
                "stream upstream failed trace_id=%s status=%s body=%s",
                trace_id, exc.status, (getattr(exc, "body", "") or "")[:200],
            )
            push("error", {"message": "上游模型调用失败", "request_id": current_request_id()})
        except Exception:
            logger.exception("stream failed trace_id=%s mode=%s", trace_id, req.mode)
            push("error", {"message": "服务内部错误", "request_id": current_request_id()})
        finally:
            queue.put_nowait(None)

    return StreamingResponse(
        sse.sse_source(produce, queue),
        media_type="text/event-stream",
        headers=sse.SSE_HEADERS,
    )


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
    workers = int(os.environ.get("MINGLI_WORKERS", "1"))
    if workers > 1:
        # 多 worker 时传 import string；全局回答槽在 Redis，不会变成 N 倍上限
        uvicorn.run(
            "api:app",
            host=os.environ.get("MINGLI_HOST", "0.0.0.0"),
            port=int(os.environ.get("MINGLI_PORT", "8000")),
            log_level="info",
            workers=workers,
        )
    else:
        uvicorn.run(
            app,
            host=os.environ.get("MINGLI_HOST", "0.0.0.0"),
            port=int(os.environ.get("MINGLI_PORT", "8000")),
            log_level="info",
        )
