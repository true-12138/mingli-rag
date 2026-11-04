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
from db.base import Base, get_session, make_engine


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

    def fake_answer(question, top_k=5, mode="rrf", api_key=None, history=None):
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
