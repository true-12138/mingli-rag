# -*- coding: utf-8 -*-
"""反馈接口测试：不调模型，用内存 SQLite。"""
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
        "history_turns": 0,
        "llm_calls": 2,
    }


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("MINGLI_API_TOKEN", raising=False)
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


def _chat(client, anon="anon-1"):
    conv = client.post(
        "/v1/conversations", json={}, headers={"X-Anonymous-Id": anon}
    ).json()
    body = client.post(
        f"/v1/conversations/{conv['id']}/chat",
        json={"question": "什么是羊刃？"},
        headers={"X-Anonymous-Id": anon},
    ).json()
    return conv, body


def test_feedback_is_stored_and_visible_in_run(client, monkeypatch):
    monkeypatch.setattr(
        api_conversations.rag, "answer", lambda *a, **k: _rag_result()
    )
    headers = {"X-Anonymous-Id": "anon-1"}
    _, body = _chat(client)

    r = client.post(
        f"/v1/runs/{body['run_id']}/feedback",
        json={"rating": -1, "reason": "没引用原文", "expected_answer": "羊刃有六种"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    fb = r.json()
    assert fb["rating"] == -1
    assert fb["promoted_to_eval"] is False

    detail = client.get(f"/v1/runs/{body['run_id']}", headers=headers).json()
    assert len(detail["feedback"]) == 1
    assert detail["feedback"][0]["reason"] == "没引用原文"
    assert detail["feedback"][0]["expected_answer"] == "羊刃有六种"


def test_feedback_upsert_keeps_one_row(client, monkeypatch):
    monkeypatch.setattr(
        api_conversations.rag, "answer", lambda *a, **k: _rag_result()
    )
    headers = {"X-Anonymous-Id": "anon-1"}
    _, body = _chat(client)

    client.post(
        f"/v1/runs/{body['run_id']}/feedback",
        json={"rating": -1, "reason": "不好"},
        headers=headers,
    )
    client.post(
        f"/v1/runs/{body['run_id']}/feedback",
        json={"rating": 1, "reason": "再看还行"},
        headers=headers,
    )
    detail = client.get(f"/v1/runs/{body['run_id']}", headers=headers).json()
    assert len(detail["feedback"]) == 1
    assert detail["feedback"][0]["rating"] == 1
    assert detail["feedback"][0]["reason"] == "再看还行"


def test_feedback_validates_rating_and_ownership(client, monkeypatch):
    monkeypatch.setattr(
        api_conversations.rag, "answer", lambda *a, **k: _rag_result()
    )
    _, body = _chat(client, anon="alice")
    assert client.post(
        f"/v1/runs/{body['run_id']}/feedback",
        json={"rating": 0},
        headers={"X-Anonymous-Id": "alice"},
    ).status_code == 422
    assert client.post(
        f"/v1/runs/{body['run_id']}/feedback",
        json={"rating": -1},
        headers={"X-Anonymous-Id": "bob"},
    ).status_code == 404
    assert client.post(
        "/v1/runs/not-exist/feedback",
        json={"rating": -1},
        headers={"X-Anonymous-Id": "alice"},
    ).status_code == 404
