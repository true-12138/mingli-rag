# -*- coding: utf-8 -*-
"""FastAPI 封装测试：不调模型、不联网，只验证路由、参数校验、trace 和错误映射。"""
import sys
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import api


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("MINGLI_API_TOKEN", raising=False)
    return TestClient(api.app)


def _rag_result():
    return {
        "can_answer": True,
        "answer": "测试回答 [1]",
        "citations": [1],
        "citations_chunk_ids": ["c1"],
        "invalid_citations": [],
        "invalid_output": False,
        "refusal_reason": None,
        "retrieved_chunk_ids": ["c1"],
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
            "chunk_id": "c9",
            "text": "原文",
            "meta": {"book": "三命通会"},
            "rrf_score": 0.5,
        }]

    monkeypatch.setattr(api.retrieval, "retrieve_one", fake_retrieve)
    r = client.post("/retrieve", json={"question": "羊刃", "mode": "rrf", "top_k": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["hits"][0]["chunk_id"] == "c9"
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
    for _ in range(api.MAX_CONCURRENCY):
        assert api._SLOTS.acquire(blocking=False)
    try:
        r = client.post("/chat", json={"question": "q"})
        assert r.status_code == 429
        assert r.headers["retry-after"] == "2"
    finally:
        for _ in range(api.MAX_CONCURRENCY):
            api._SLOTS.release()
