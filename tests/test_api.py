# -*- coding: utf-8 -*-
"""FastAPI 封装测试：不调模型、不联网，只验证路由、参数校验、trace 和错误映射。"""
import sys
from pathlib import Path

import numpy as np
import pytest
import requests
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import api
import gate
import semcache


class _FakeEncoder:
    """按字符码累加的确定性向量，避免单测加载 BGE-M3。"""

    def encode(self, text, normalize_embeddings=True):
        vec = np.zeros(16, dtype=np.float32)
        for ch in str(text):
            vec[ord(ch) % 16] += 1.0
        norm = float(np.linalg.norm(vec)) or 1.0
        return vec / norm


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("MINGLI_API_TOKEN", raising=False)
    monkeypatch.delenv("MINGLI_REDIS_URL", raising=False)
    gate.reset_for_tests()
    semcache.reset_for_tests()
    semcache.set_encoder(_FakeEncoder())
    yield TestClient(api.app)
    semcache.reset_for_tests()


def _rag_result():
    return {
        "can_answer": True,
        "answer": "测试回答 [1]",
        "citations": [1],
        "citations_chunk_ids": [1],
        "invalid_citations": [],
        "invalid_output": False,
        "refusal_reason": None,
        "retrieved_chunk_ids": [1],
        "rewritten_question": "独立问题",
        "history_turns": 1,
        "llm_calls": 2,
    }


def test_health_reports_corpus_and_modes(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["chunks"] == 8681
    assert data["embedding_dim"] == 1024
    assert data["modes"] == ["rag", "agent", "multi"]


def test_chat_routes_to_rag_and_exposes_trace(client, monkeypatch):
    captured = {}

    def fake_answer(question, top_k=5, mode="rrf", api_key=None, history=None):
        captured.update({
            "question": question, "top_k": top_k, "api_key": api_key, "history": history,
        })
        return _rag_result()

    monkeypatch.setattr(api.rag, "answer", fake_answer)
    r = client.post("/chat", json={
        "question": "羊刃分几种？",
        "mode": "rag",
        "top_k": 3,
        "history": [
            {"role": "user", "content": "什么是羊刃？"},
            {"role": "assistant", "content": "羊刃是..."},
        ],
    }, headers={"X-DeepSeek-Key": "visitor-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "测试回答 [1]"
    assert body["trace_id"]
    assert body["mode"] == "rag"
    assert captured["top_k"] == 3
    assert captured["api_key"] == "visitor-key"
    assert captured["history"][0]["content"] == "什么是羊刃？"

    trace = client.get("/trace/" + body["trace_id"])
    assert trace.status_code == 200
    assert trace.json()["result"]["answer"] == "测试回答 [1]"


def test_chat_routes_to_single_and_multi_agent(client, monkeypatch):
    calls = []

    def fake_agent(question, max_steps=6, api_key=None, history=None):
        calls.append(("agent", question, max_steps))
        out = _rag_result()
        out["trace"] = [{"step": 1, "action": "search_classics"}]
        out["steps"] = 1
        return out

    def fake_multi(question, max_steps=6, api_key=None, history=None):
        calls.append(("multi", question, max_steps))
        out = _rag_result()
        out["plan"] = {"searches": ["羊刃"]}
        out["verdict"] = {"supported": True, "gaps": []}
        return out

    monkeypatch.setattr(api.agent, "agent_answer", fake_agent)
    monkeypatch.setattr(api.agent_multi, "agent_answer", fake_multi)

    r1 = client.post("/chat", json={"question": "q1", "mode": "agent", "max_steps": 4})
    r2 = client.post("/chat", json={"question": "q2", "mode": "multi"})
    assert r1.status_code == r2.status_code == 200
    assert calls == [("agent", "q1", 4), ("multi", "q2", 6)]
    assert r1.json()["steps"] == 1
    assert r2.json()["plan"] == {"searches": ["羊刃"]}


def test_retrieve_returns_hits_and_stores_trace(client, monkeypatch):
    def fake_retrieve(question, top_k=5, mode="rrf"):
        return [{
            "chunk_id": 9,
            "text": "原文",
            "meta": {"book": "三命通会"},
            "rrf_score": 0.5,
        }]

    monkeypatch.setattr(api.retrieval, "retrieve_one", fake_retrieve)
    r = client.post("/retrieve", json={"question": "羊刃", "mode": "rrf", "top_k": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["hits"][0]["chunk_id"] == 9
    assert body["hits"][0]["score"] == 0.5
    assert client.get("/trace/" + body["trace_id"]).status_code == 200


def test_validation_and_auth(client, monkeypatch):
    assert client.post("/chat", json={"question": "   "}).status_code == 422
    assert client.post("/chat", json={"question": "q", "mode": "bad"}).status_code == 422

    def no_key(*args, **kwargs):
        raise RuntimeError("没有找到 DEEPSEEK_API_KEY")

    monkeypatch.setattr(api.rag, "answer", no_key)
    monkeypatch.setenv("MINGLI_API_TOKEN", "secret")
    assert client.post("/chat", json={"question": "q"}).status_code == 401
    r = client.post(
        "/chat", json={"question": "q"},
        headers={"Authorization": "Bearer secret"},
    )
    # 没配 DEEPSEEK key 时走到 rag 的 RuntimeError，映射成 503
    assert r.status_code == 503


def test_chat_reports_token_usage(client, monkeypatch):
    def fake_answer(question, top_k=5, mode="rrf", api_key=None, history=None):
        # 模拟 rag._chat 里 usage.add 的旁路采集：两次调用各记一次
        api.usage.add({"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120})
        api.usage.add({
            "prompt_tokens": 50,
            "completion_tokens": 10,
            "total_tokens": 60,
            "prompt_tokens_details": {"cached_tokens": 30},
        })
        return _rag_result()

    monkeypatch.setattr(api.rag, "answer", fake_answer)
    body = client.post("/chat", json={"question": "q"}).json()
    assert body["usage"] == {
        "prompt_tokens": 150,
        "completion_tokens": 30,
        "total_tokens": 180,
        "cached_tokens": 30,
        "llm_calls": 2,
    }
    # 用量不进 trace 之外的共享状态：下一个请求从零开始
    monkeypatch.setattr(api.rag, "answer", lambda *a, **k: _rag_result())
    assert client.post("/chat", json={"question": "q2"}).json()["usage"]["total_tokens"] == 0


def test_usage_without_reset_is_inert():
    # 脚本 / 测试直接调 rag 时不会 reset，采集器应当完全静默
    import usage as usage_mod

    if hasattr(usage_mod._local, "data"):
        del usage_mod._local.data
    usage_mod.add({"total_tokens": 5})
    assert usage_mod.snapshot() is None


def test_trace_404(client):
    assert client.get("/trace/not-found").status_code == 404


def test_upstream_error_maps_to_502(client, monkeypatch):
    def boom(*args, **kwargs):
        raise requests.HTTPError("upstream 500")

    monkeypatch.setattr(api.rag, "answer", boom)
    r = client.post("/chat", json={"question": "q"})
    assert r.status_code == 502


def test_concurrency_limit_returns_429(client):
    # 占满所有槽位，再发一个请求：必须在进模型之前被 429 挡住
    g = gate.get_gate()
    tokens = []
    try:
        for _ in range(api.MAX_CONCURRENCY):
            token = g.try_acquire("answer", gate.answer_limit(), gate.ANSWER_SLOT_TTL)
            assert token
            tokens.append(token)
        r = client.post("/chat", json={"question": "q"})
        assert r.status_code == 429
        assert r.headers["retry-after"] == "2"
    finally:
        for token in tokens:
            g.release("answer", token)


def _parse_sse(text):
    """把 SSE 文本拆成 [(event, data)]，忽略心跳注释行。"""
    import json as _json

    frames = []
    for block in text.split("\n\n"):
        event, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                data = _json.loads(line[6:])
        if event:
            frames.append((event, data))
    return frames


def test_chat_stream_emits_step_delta_done(client, monkeypatch):
    async def fake_stream(question, top_k=5, api_key=None, history=None,
                          on_delta=None, on_step=None, client=None):
        on_step({"agent": "retrieval", "tool": "retrieve", "args": {"query": question},
                 "ok": True, "chunk_ids": [1], "error": None})
        on_delta("测试")
        on_delta("回答")
        return dict(_rag_result(), usage={"total_tokens": 12})

    monkeypatch.setattr(api.rag, "answer_stream", fake_stream)
    with client.stream("POST", "/chat/stream", json={"question": "羊刃分几种？"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        frames = _parse_sse("".join(r.iter_text()))

    events = [f[0] for f in frames]
    assert events == ["step", "delta", "delta", "done"]
    assert "".join(d["text"] for e, d in frames if e == "delta") == "测试回答"
    done = [d for e, d in frames if e == "done"][0]
    assert done["answer"] == "测试回答 [1]"
    assert done["mode"] == "rag"
    assert done["usage"]["total_tokens"] == 12
    assert done["trace_id"]


def test_chat_stream_error_event(client, monkeypatch):
    class Boom(Exception):
        pass

    async def fake_stream(**kwargs):
        raise Boom("internal detail")

    monkeypatch.setattr(api.rag, "answer_stream", fake_stream)
    with client.stream("POST", "/chat/stream", json={"question": "q"}) as r:
        frames = _parse_sse("".join(r.iter_text()))

    assert [f[0] for f in frames] == ["error"]
    assert frames[0][1]["message"] == "服务内部错误"
    assert "internal detail" not in frames[0][1]["message"]


def test_chat_stream_rejects_when_stream_slots_full(client):
    """流式回答槽位满了要立刻 429，而不是把连接挂在那里排队。"""
    g = gate.get_gate()
    tokens = []
    try:
        for _ in range(api.MAX_CONCURRENCY):
            token = g.try_acquire("answer", gate.answer_limit(), gate.ANSWER_SLOT_TTL)
            assert token
            tokens.append(token)
        r = client.post("/chat/stream", json={"question": "q"})
        assert r.status_code == 429
        assert r.headers["retry-after"] == "3"
    finally:
        for token in tokens:
            g.release("answer", token)


def test_events_stream_greets_then_stops_on_disconnect(client, monkeypatch):
    """`/v1/events` 是连接保持流：只发 hello + 心跳，不占回答槽。"""
    import asyncio

    class FakeRequest:
        async def is_disconnected(self):
            return True

    async def first_frame():
        response = await api.events(FakeRequest(), None)
        iterator = response.body_iterator
        try:
            return await iterator.__anext__()
        finally:
            await iterator.aclose()

    frame = asyncio.run(first_frame())
    assert frame.startswith("event: hello\n")
    assert "keep-alive" not in frame


def test_chunks_lookup_returns_titles_and_text(client):
    # 语料第一条：书名、正文都要能取到，供前端引用 chip 展开
    r = client.post("/chunks", json={"ids": [1, 1, 999999]})
    assert r.status_code == 200
    items = r.json()
    assert [it["chunk_id"] for it in items] == [1]  # 去重 + 未知 id 略过
    item = items[0]
    assert item["title"].startswith("《")
    assert item["text"]
    assert item["book"]


def test_chunks_lookup_rejects_empty_ids(client):
    assert client.post("/chunks", json={"ids": []}).status_code == 422


# ---------- 语义缓存 ----------


def test_chat_cache_hit_skips_llm(client, monkeypatch):
    calls = []

    def fake_answer(question, top_k=5, mode="rrf", api_key=None, history=None):
        calls.append(question)
        return _rag_result()

    monkeypatch.setattr(api.rag, "answer", fake_answer)
    payload = {"question": "羊刃分几种？", "mode": "rag", "top_k": 5}

    first = client.post("/chat", json=payload)
    second = client.post("/chat", json=payload)
    assert first.status_code == second.status_code == 200
    assert calls == ["羊刃分几种？"]  # 第二次没打模型
    body = second.json()
    assert body["cached"] is True
    assert body["cache_kind"] == "exact"
    assert body["answer"] == "测试回答 [1]"
    assert body["usage"]["total_tokens"] == 0
    assert body["elapsed_ms"] < 1000

    metrics = client.get("/metrics").text
    assert 'mingli_semcache_hits_total{kind="exact"} 1' in metrics


def test_chat_no_cache_header_bypasses(client, monkeypatch):
    calls = []

    def fake_answer(question, top_k=5, mode="rrf", api_key=None, history=None):
        calls.append(question)
        return _rag_result()

    monkeypatch.setattr(api.rag, "answer", fake_answer)
    payload = {"question": "羊刃分几种？", "mode": "rag"}
    headers = {"X-No-Cache": "1"}

    client.post("/chat", json=payload, headers=headers)
    client.post("/chat", json=payload, headers=headers)
    assert calls == ["羊刃分几种？", "羊刃分几种？"]


def test_chat_with_history_is_not_cached(client, monkeypatch):
    calls = []

    def fake_answer(question, top_k=5, mode="rrf", api_key=None, history=None):
        calls.append(question)
        return _rag_result()

    monkeypatch.setattr(api.rag, "answer", fake_answer)
    payload = {
        "question": "羊刃分几种？",
        "mode": "rag",
        "history": [{"role": "user", "content": "什么是羊刃？"}],
    }
    client.post("/chat", json=payload)
    client.post("/chat", json=payload)
    assert len(calls) == 2


def test_cache_hit_does_not_consume_quota(client, monkeypatch):
    monkeypatch.setenv("MINGLI_USER_DAILY_LIMIT", "1")
    gate.reset_for_tests()
    calls = []

    def fake_answer(question, top_k=5, mode="rrf", api_key=None, history=None):
        calls.append(question)
        return _rag_result()

    monkeypatch.setattr(api.rag, "answer", fake_answer)

    assert client.post("/chat", json={"question": "q1", "mode": "rag"}).status_code == 200
    # 同一问题命中缓存：额度已用完也不该 429
    assert client.post("/chat", json={"question": "q1", "mode": "rag"}).status_code == 200
    # 新问题要打模型，额度 1 已用尽
    blocked = client.post("/chat", json={"question": "q2", "mode": "rag"})
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "3600"
    assert calls == ["q1"]


def test_chat_stream_cache_hit_returns_delta_and_done(client, monkeypatch):
    calls = []

    async def fake_stream(question, top_k=5, api_key=None, history=None,
                          on_delta=None, on_step=None, client=None):
        calls.append(question)
        on_delta("测试回答")
        return dict(_rag_result(), usage={"total_tokens": 12})

    monkeypatch.setattr(api.rag, "answer_stream", fake_stream)
    payload = {"question": "羊刃分几种？", "mode": "rag"}

    with client.stream("POST", "/chat/stream", json=payload) as r:
        _parse_sse("".join(r.iter_text()))
    with client.stream("POST", "/chat/stream", json=payload) as r:
        frames = _parse_sse("".join(r.iter_text()))

    assert calls == ["羊刃分几种？"]
    assert [f[0] for f in frames] == ["delta", "done"]
    assert frames[0][1]["text"] == "测试回答 [1]"
    assert frames[1][1]["cached"] is True
    assert frames[1][1]["usage"]["total_tokens"] == 0
