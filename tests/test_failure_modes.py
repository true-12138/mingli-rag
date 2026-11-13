# -*- coding: utf-8 -*-
"""失败模式与边界测试：只覆盖「出问题时应该怎样」，不重复 happy path。

复用 `test_conversations_api.py` / `test_fortune_api.py` 的建库方式：
每个测试一个独立的内存 SQLite，覆盖 FastAPI 的 `get_session` 依赖。
不调真实模型、不联网。
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import agent  # noqa: E402
import api  # noqa: E402
import rag  # noqa: E402
from db import repo  # noqa: E402
from db.base import Base, get_session, make_engine  # noqa: E402


# ---------- fixtures（与既有 API 测试同一套建库方式） ----------

@pytest.fixture()
def engine():
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def db(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture()
def client(monkeypatch, session_factory):
    monkeypatch.delenv("MINGLI_API_TOKEN", raising=False)

    def override_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    api.app.dependency_overrides[get_session] = override_session
    with TestClient(api.app) as test_client:
        yield test_client
    api.app.dependency_overrides.clear()


BAZI = {"year": 1995, "month": 8, "day": 20, "hour": 14, "gender": "male"}


def _seed_pending_memory(db, anon="lock-user"):
    """建一条 active + 一条待确认的覆盖值，返回 (memory_id, version)。"""
    user = repo.get_or_create_user(db, anon)
    memory = repo.upsert_memory(db, user.id, "fact", "city", "杭州")
    repo.upsert_memory(db, user.id, "fact", "city", "南京")
    db.refresh(memory)
    assert memory.value == "杭州" and memory.pending_value == "南京"
    return memory.id, memory.version


def _memory_headers(anon):
    return {"X-Anonymous-Id": anon}


# ---------- 长期记忆：乐观锁 / 确认流程 ----------

def test_memory_lost_update_is_rejected_with_409(client, db):
    """两个标签页都拿着 version=2 点确认：后到的那个不能覆盖先到的那次写入。"""
    memory_id, version = _seed_pending_memory(db, anon="lock-user")
    headers = _memory_headers("lock-user")

    first = client.post(
        f"/v1/memories/{memory_id}/confirm", json={"version": version}, headers=headers
    )
    assert first.status_code == 200, first.text
    assert first.json()["value"] == "南京"
    assert first.json()["version"] == version + 1

    # 第二个标签页的 version 已经过期：必须 409，并且带回库里当前状态。
    stale = client.post(
        f"/v1/memories/{memory_id}/confirm", json={"version": version}, headers=headers
    )
    assert stale.status_code == 409, stale.text
    current = stale.json()["detail"]["current"]
    assert current["value"] == "南京"
    assert current["pending_value"] is None
    assert current["version"] == version + 1

    # 冲突没有写坏数据：再确认一次（不带 version）仍然只看到「南京」。
    fresh = client.get("/v1/memories", headers=headers).json()
    assert [m["value"] for m in fresh] == ["南京"]
    assert fresh[0]["status"] == "active"


def test_memory_confirm_is_idempotent(client, db):
    """确认成功后再点一次（不带 version）：不报错、不涨版本、值不变。"""
    memory_id, version = _seed_pending_memory(db, anon="idem-user")
    headers = _memory_headers("idem-user")

    first = client.post(f"/v1/memories/{memory_id}/confirm", json={}, headers=headers)
    assert first.status_code == 200, first.text
    done = first.json()

    again = client.post(f"/v1/memories/{memory_id}/confirm", json={}, headers=headers)
    assert again.status_code == 200, again.text
    body = again.json()
    assert body["value"] == done["value"] == "南京"
    assert body["version"] == done["version"]
    assert body["pending_value"] is None
    assert body["status"] == "active"


def test_pending_memory_is_not_in_prompt(db, monkeypatch):
    """新值只在 pending_value 里等确认，绝不能提前混进 prompt。"""
    user = repo.get_or_create_user(db, "prompt-user")
    memory = repo.upsert_memory(
        db, user.id, "preference", "preferred_book", "《三命通会》"
    )
    repo.upsert_memory(
        db, user.id, "preference", "preferred_book", "《穷通宝鉴》"
    )
    db.refresh(memory)
    assert memory.value == "《三命通会》"
    assert memory.pending_value == "《穷通宝鉴》"

    hits = [{
        "chunk_id": 7,
        "text": "羊刃者……",
        "meta": {"book": "三命通会", "volume": "", "chapter": ""},
    }]
    monkeypatch.setattr(rag, "retrieve_one", lambda *a, **k: hits)
    seen = {}

    def fake_chat(messages, **kwargs):
        seen["user"] = messages[-1]["content"]
        return '{"can_answer": true, "answer": "羊刃……[1]", "citations": [1]}'

    monkeypatch.setattr(rag, "_chat", fake_chat)
    rag.answer("羊刃是什么", memories=[memory])

    assert "《三命通会》" in seen["user"]
    assert "《穷通宝鉴》" not in seen["user"]


def test_reject_rolls_back_pending_value(client, db):
    """忽略新值后，旧值继续生效，pending 被清空，别处也不该再看到新值。"""
    memory_id, version = _seed_pending_memory(db, anon="reject-user")
    headers = _memory_headers("reject-user")

    rejected = client.post(
        f"/v1/memories/{memory_id}/reject", json={"version": version}, headers=headers
    )
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()
    assert body["value"] == "杭州"
    assert body["pending_value"] is None
    assert body["status"] == "active"
    assert body["version"] == version + 1

    listed = client.get("/v1/memories", headers=headers).json()
    assert [(m["value"], m["pending_value"]) for m in listed] == [("杭州", None)]


# ---------- 结构化追问 / intake ----------

def test_intake_does_not_guess_required_birth_fields(client):
    """什么都不知道时：把必填项全列出来，不能补默认值直接算盘。"""
    r = client.post("/v1/fortune/intake", json={"kind": "bazi", "params": {}})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["status"] == "need_input"
    assert body["reason"] == "missing"
    assert body["known"] == {}
    assert [f["name"] for f in body["fields"]] == [
        "year", "month", "day", "hour", "gender",
    ]
    # 没有 chart / params / defaults：没猜过任何出生信息。
    assert "chart" not in body
    assert "params" not in body
    assert "defaults" not in body


def test_intake_invalid_value_only_asks_that_field(client):
    """多个值不合法时只问出错的两个，合法字段不再重复追问。"""
    r = client.post("/v1/fortune/intake", json={
        "kind": "bazi",
        "params": {
            "year": 1995, "month": 13, "day": 20, "hour": True, "gender": "male",
        },
    })
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["status"] == "need_input"
    assert body["reason"] == "invalid"
    assert [f["name"] for f in body["fields"]] == ["month", "hour"]
    assert all(f.get("error") for f in body["fields"])
    # 合法字段保留在 known 里，不会被当成「缺」或「错」再问一遍。
    assert body["known"] == {"year": 1995, "day": 20, "gender": "male"}


def test_intake_calendar_error_does_not_500(client):
    """4 月 31 日能过单字段范围，但历法上不存在：应返回追问而不是 500。"""
    r = client.post("/v1/fortune/intake", json={
        "kind": "bazi",
        "params": {"year": 1995, "month": 4, "day": 31, "hour": 14, "gender": "male"},
    })
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["status"] == "need_input"
    assert body["reason"] == "calendar"
    assert "day" in [f["name"] for f in body["fields"]]
    assert "不合法" in body["message"]
    assert "chart" not in body


def test_intake_defaults_are_disclosed_not_silent(client):
    """可选字段用了默认值必须写进 defaults / warnings，不能悄悄补 0 分钟。"""
    r = client.post("/v1/fortune/intake", json={"kind": "bazi", "params": BAZI})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["status"] == "ready"
    assert body["defaults"] == {"minute": 0}
    assert any("0 分" in warning for warning in body["warnings"])
    # defaults 里只能出现可选字段，必填项不可能被默认值顶掉。
    assert set(body["defaults"]) <= {"minute"}


def test_read_incomplete_params_returns_structured_400(client):
    """/read 拿到非法参数时返回 400 + fields，而不是 422 或 500。"""
    r = client.post("/v1/fortune/read", json={
        "kind": "bazi",
        "params": {"year": 1995, "month": 13, "day": 20, "hour": 14, "gender": "male"},
    })
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["need_input"] is True
    assert [f["name"] for f in detail["fields"]] == ["month"]
    assert detail["fields"][0].get("error")


# ---------- 塔罗 seed ----------

def test_tarot_seed_is_fixed_once_cards_are_shown(client):
    """intake 展示的牌必须能用它返回的 seed 原样复现，不能重新抽一组。"""
    first = client.post(
        "/v1/fortune/intake", json={"kind": "tarot", "params": {"spread": "three"}}
    )
    assert first.status_code == 200, first.text
    shown = first.json()["chart"]
    assert shown["seed"] is not None

    again = client.post("/v1/fortune/intake", json={
        "kind": "tarot",
        "params": {"spread": "three", "seed": shown["seed"]},
    })
    assert again.status_code == 200, again.text
    recalculated = again.json()["chart"]
    assert recalculated["seed"] == shown["seed"]
    assert recalculated["cards"] == shown["cards"]


def test_intake_tarot_seed_zero_is_not_treated_as_missing(client):
    """seed=0 是合法值，不能因为它是 falsy 就换成随机 seed。"""
    payload = {"kind": "tarot", "params": {"spread": "single", "seed": 0}}
    first = client.post("/v1/fortune/intake", json=payload)
    assert first.status_code == 200, first.text
    chart = first.json()["chart"]
    assert chart["seed"] == 0

    second = client.post("/v1/fortune/intake", json=payload)
    assert second.json()["chart"]["cards"] == chart["cards"]


# ---------- 引用白名单 ----------

def test_agent_citation_not_in_trace_goes_to_invalid():
    """模型编出来的 chunk_id 不能出现在引用里，只能进 invalid_citations。"""
    seen = {11, 12}
    data = {
        "can_answer": True,
        "answer": "有依据的回答 [11]",
        "citations": [11, 999, "12", "not-a-chunk"],
    }
    out = agent._finalize(data, seen, trace=[])

    assert out["citations_chunk_ids"] == [11, 12]
    assert out["invalid_citations"] == [999, "not-a-chunk"]
    assert out["retrieved_chunk_ids"] == [11, 12]
    assert out["invalid_output"] is True
