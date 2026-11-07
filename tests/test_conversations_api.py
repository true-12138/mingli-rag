# -*- coding: utf-8 -*-
"""`/v1/conversations` 接口测试：不调模型、不联网，用内存 SQLite。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import api
import api_conversations
from db import repo
from db.base import Base, get_session, make_engine


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


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("MINGLI_API_TOKEN", raising=False)

    # 每个测试一个独立的内存库；覆盖 get_session，接口不会碰 data/app.sqlite3。
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    api.app.dependency_overrides[get_session] = override_session
    with TestClient(api.app) as test_client:
        yield test_client
    api.app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def _create(client, anon="anon-1", title=None):
    r = client.post(
        "/v1/conversations",
        json={"title": title} if title else {},
        headers={"X-Anonymous-Id": anon},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_create_list_get_delete(client):
    conv = _create(client, title="第一个会话")
    assert conv["title"] == "第一个会话"
    assert conv["message_count"] == 0

    listed = client.get(
        "/v1/conversations", headers={"X-Anonymous-Id": "anon-1"}
    ).json()
    assert [c["id"] for c in listed] == [conv["id"]]

    detail = client.get(
        f"/v1/conversations/{conv['id']}", headers={"X-Anonymous-Id": "anon-1"}
    )
    assert detail.status_code == 200
    assert detail.json()["messages"] == []

    deleted = client.delete(
        f"/v1/conversations/{conv['id']}", headers={"X-Anonymous-Id": "anon-1"}
    )
    assert deleted.status_code == 204
    assert client.get(
        f"/v1/conversations/{conv['id']}", headers={"X-Anonymous-Id": "anon-1"}
    ).status_code == 404


def test_chat_stores_messages_and_reuses_history(client, monkeypatch):
    seen_history = []

    def fake_answer(question, top_k=5, mode="rrf", api_key=None, history=None, memories=None):
        seen_history.append(history)
        return _rag_result()

    monkeypatch.setattr(api_conversations.rag, "answer", fake_answer)
    conv = _create(client)
    headers = {"X-Anonymous-Id": "anon-1"}

    first = client.post(
        f"/v1/conversations/{conv['id']}/chat",
        json={"question": "什么是羊刃？"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["conversation_id"] == conv["id"]
    assert first.json()["user_message_id"] > 0
    assert seen_history[0] == []

    second = client.post(
        f"/v1/conversations/{conv['id']}/chat",
        json={"question": "那它分几种？"},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    # 第二次请求时，服务端应该已经读到了第一轮的问答
    assert [m["role"] for m in seen_history[1]] == ["user", "assistant"]
    assert seen_history[1][0]["content"] == "什么是羊刃？"
    assert seen_history[1][1]["content"] == "测试回答 [1]"

    detail = client.get(
        f"/v1/conversations/{conv['id']}", headers=headers
    ).json()
    assert detail["message_count"] == 4
    assert [m["role"] for m in detail["messages"]] == [
        "user", "assistant", "user", "assistant",
    ]
    # 第一次提问后，默认标题改成问题前 30 个字
    assert detail["title"] == "什么是羊刃？"


def test_conversation_is_isolated_by_anonymous_id(client):
    conv = _create(client, anon="alice")
    assert client.get(
        f"/v1/conversations/{conv['id']}", headers={"X-Anonymous-Id": "bob"}
    ).status_code == 404
    assert client.get(
        "/v1/conversations", headers={"X-Anonymous-Id": "bob"}
    ).json() == []


def test_blank_question_and_unknown_conversation(client):
    conv = _create(client)
    headers = {"X-Anonymous-Id": "anon-1"}
    assert client.post(
        f"/v1/conversations/{conv['id']}/chat",
        json={"question": "   "},
        headers=headers,
    ).status_code == 422
    assert client.post(
        "/v1/conversations/not-exist/chat",
        json={"question": "q"},
        headers=headers,
    ).status_code == 404


def test_v1_requires_token_when_configured(client, monkeypatch):
    monkeypatch.setenv("MINGLI_API_TOKEN", "secret")
    assert client.get("/v1/conversations").status_code == 401
    assert client.get(
        "/v1/conversations", headers={"Authorization": "Bearer secret"}
    ).status_code == 200


def test_chat_persists_run_and_tool_calls(client, monkeypatch):
    def fake_agent(question, max_steps=6, api_key=None, history=None, memories=None):
        out = _rag_result()
        out["llm_calls"] = 3
        out["trace"] = [{
            "step": 1,
            "agent": "retriever",
            "thought": "先搜术语",
            "action": "search_classics",
            "args": {"query": "羊刃", "book": "三命通会"},
            "ok": True,
            "chunk_ids": ["c1", "c2"],
            "error": None,
        }]
        out["steps"] = 1
        return out

    monkeypatch.setattr(api_conversations.agent, "agent_answer", fake_agent)
    headers = {"X-Anonymous-Id": "anon-1"}
    conv = _create(client)
    body = client.post(
        f"/v1/conversations/{conv['id']}/chat",
        json={"question": "羊刃分几种？", "mode": "agent"},
        headers=headers,
    ).json()
    assert body["run_id"]

    run = client.get(f"/v1/runs/{body['run_id']}", headers=headers)
    assert run.status_code == 200, run.text
    detail = run.json()
    assert detail["status"] == "succeeded"
    assert detail["can_answer"] is True
    assert detail["llm_calls"] == 3
    assert detail["tool_calls"][0]["tool_name"] == "search_classics"
    assert detail["tool_calls"][0]["agent"] == "retriever"
    assert detail["tool_calls"][0]["args"] == {"query": "羊刃", "book": "三命通会"}
    assert detail["tool_calls"][0]["chunk_ids"] == ["c1", "c2"]

    runs = client.get(
        f"/v1/conversations/{conv['id']}/runs", headers=headers
    ).json()
    assert [r["id"] for r in runs] == [body["run_id"]]


def test_refusal_run_is_marked_refused(client, monkeypatch):
    def fake_answer(question, top_k=5, mode="rrf", api_key=None, history=None, memories=None):
        out = _rag_result()
        out.update({"can_answer": False, "answer": "拒答", "citations": []})
        return out

    monkeypatch.setattr(api_conversations.rag, "answer", fake_answer)
    headers = {"X-Anonymous-Id": "anon-1"}
    conv = _create(client)
    body = client.post(
        f"/v1/conversations/{conv['id']}/chat",
        json={"question": "能预测股票吗？"},
        headers=headers,
    ).json()
    detail = client.get(f"/v1/runs/{body['run_id']}", headers=headers).json()
    assert detail["status"] == "refused"
    assert detail["tool_calls"] == []


def test_failed_run_is_recorded(client, monkeypatch):
    import requests

    def boom(*args, **kwargs):
        raise requests.HTTPError("upstream 500")

    monkeypatch.setattr(api_conversations.rag, "answer", boom)
    headers = {"X-Anonymous-Id": "anon-1"}
    conv = _create(client)
    r = client.post(
        f"/v1/conversations/{conv['id']}/chat",
        json={"question": "q"},
        headers=headers,
    )
    assert r.status_code == 502

    runs = client.get(
        f"/v1/conversations/{conv['id']}/runs", headers=headers
    ).json()
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert "上游" in runs[0]["error"]


def test_run_is_isolated_by_anonymous_id(client, monkeypatch):
    def fake_answer(question, top_k=5, mode="rrf", api_key=None, history=None, memories=None):
        return _rag_result()

    monkeypatch.setattr(api_conversations.rag, "answer", fake_answer)
    conv = _create(client, anon="alice")
    body = client.post(
        f"/v1/conversations/{conv['id']}/chat",
        json={"question": "q"},
        headers={"X-Anonymous-Id": "alice"},
    ).json()

    assert client.get(
        f"/v1/runs/{body['run_id']}", headers={"X-Anonymous-Id": "bob"}
    ).status_code == 404


def test_memory_endpoints_and_chat_injection(client, monkeypatch):
    seen = []

    def fake_answer(question, top_k=5, mode="rrf", api_key=None, history=None, memories=None):
        seen.append(memories)
        return _rag_result()

    def fake_remember(session, user_id, conversation_id, question, answer,
                      api_key=None, counter=None):
        return [repo.upsert_memory(
            session, user_id, "preference", "preferred_book", "《三命通会》",
            source_conversation_id=conversation_id,
        )]

    monkeypatch.setattr(api_conversations.rag, "answer", fake_answer)
    monkeypatch.setattr(api_conversations.memory, "remember_from_turn", fake_remember)

    headers = {"X-Anonymous-Id": "anon-1"}
    conv = _create(client)
    first = client.post(
        f"/v1/conversations/{conv['id']}/chat",
        json={"question": "记住：以后优先查三命通会"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["memories_written"] == 1
    assert first.json()["memories_used"] == 0
    assert seen[0] == []

    listed = client.get("/v1/memories", headers=headers).json()
    assert len(listed) == 1 and listed[0]["key"] == "preferred_book"

    second = client.post(
        f"/v1/conversations/{conv['id']}/chat",
        json={"question": "那它和阳刃一样吗？"},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert len(seen[1]) == 1 and seen[1][0].key == "preferred_book"
    assert second.json()["memories_used"] == 1

    # 另一个匿名用户看不到、也删不掉
    assert client.get("/v1/memories", headers={"X-Anonymous-Id": "anon-2"}).json() == []
    assert client.delete(
        "/v1/memories/%d" % listed[0]["id"], headers={"X-Anonymous-Id": "anon-2"}
    ).status_code == 404

    assert client.delete(
        "/v1/memories/%d" % listed[0]["id"], headers=headers
    ).status_code == 204
    assert client.get("/v1/memories", headers=headers).json() == []


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


def test_chat_stream_persists_turn_and_returns_ids(client, monkeypatch):
    async def fake_stream(question, top_k=5, api_key=None, history=None, memories=None,
                          on_delta=None, on_step=None, client=None):
        on_delta("测试")
        on_delta("回答")
        return dict(_rag_result(), usage={"total_tokens": 7})

    monkeypatch.setattr(api_conversations.rag, "answer_stream", fake_stream)
    conv = _create(client)
    headers = {"X-Anonymous-Id": "anon-1"}

    with client.stream(
        "POST", f"/v1/conversations/{conv['id']}/chat/stream",
        json={"question": "羊刃分几种？"}, headers=headers,
    ) as r:
        assert r.status_code == 200
        frames = _parse_sse("".join(r.iter_text()))

    assert [f[0] for f in frames] == ["delta", "delta", "done"]
    done = frames[-1][1]
    assert done["conversation_id"] == conv["id"]
    assert done["answer"] == "测试回答 [1]"
    assert done["user_message_id"] > 0
    assert done["run_id"]

    detail = client.get(f"/v1/conversations/{conv['id']}", headers=headers).json()
    assert detail["message_count"] == 2
    assert detail["messages"][1]["content"] == "测试回答 [1]"


def test_chat_stream_marks_run_failed_on_error(client, monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("上游炸了")

    monkeypatch.setattr(api_conversations.rag, "answer_stream", boom)
    conv = _create(client)
    headers = {"X-Anonymous-Id": "anon-1"}

    with client.stream(
        "POST", f"/v1/conversations/{conv['id']}/chat/stream",
        json={"question": "q"}, headers=headers,
    ) as r:
        frames = _parse_sse("".join(r.iter_text()))

    assert [f[0] for f in frames] == ["error"]
    assert frames[0][1]["conversation_id"] == conv["id"]

    runs = client.get(
        f"/v1/conversations/{conv['id']}/runs", headers=headers
    ).json()
    assert runs[0]["status"] == "failed"

    detail = client.get(f"/v1/conversations/{conv['id']}", headers=headers).json()
    assert detail["messages"] == []


def test_conversation_detail_keeps_citations_after_reload(client, monkeypatch):
    def fake_answer(question, top_k=5, mode="rrf", api_key=None, history=None, memories=None):
        return _rag_result()

    monkeypatch.setattr(api_conversations.rag, "answer", fake_answer)
    conv = _create(client)
    headers = {"X-Anonymous-Id": "anon-1"}
    client.post(f"/v1/conversations/{conv['id']}/chat",
                json={"question": "什么是羊刃？"}, headers=headers)

    detail = client.get(f"/v1/conversations/{conv['id']}", headers=headers).json()
    assert len(detail["runs"]) == 1
    run = detail["runs"][0]
    assert run["citations_chunk_ids"] == [1]
    assert run["question"] == "什么是羊刃？"
    assert run["mode"] == "rag"
