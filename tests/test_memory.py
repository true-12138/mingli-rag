# -*- coding: utf-8 -*-
"""长期记忆的离线测试：不调真实模型，只验证边界。"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import conversation  # noqa: E402
import memory  # noqa: E402
import rag  # noqa: E402
from db import repo  # noqa: E402
from db.base import Base, make_engine  # noqa: E402
from db.models import Conversation, Message, User, UserMemory  # noqa: E402


@pytest.fixture()
def session():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    Base.metadata.drop_all(engine)


@pytest.fixture()
def user(session):
    u = User(anonymous_id="mem-user")
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


@pytest.fixture()
def conv(session, user):
    c = Conversation(id="d" * 32, user_id=user.id, title="t")
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


def test_should_extract_gate():
    assert memory.should_extract("记住：以后优先查《三命通会》")
    assert memory.should_extract("我的出生时间是 1992-11-15")
    assert not memory.should_extract("羊刃是什么意思")


def test_extract_filters_bad_items_and_dedupes(monkeypatch):
    payload = {
        "memories": [
            {"kind": "preference", "key": "preferred_book", "value": "以后优先查《三命通会》"},
            {"kind": "fact", "key": "birth_time", "value": "1992-11-15 14:00 女"},
            {"kind": "preference", "key": "preferred_book", "value": "重复项"},
            {"kind": "fact", "key": "Bad-Key", "value": "x"},
            {"kind": "fact", "key": "phone", "value": "13800138000"},
            {"kind": "fact", "key": "id_card", "value": "110101199001011234"},
            {"kind": "other", "key": "x", "value": "y"},
        ]
    }
    monkeypatch.setattr(rag, "_chat", lambda *a, **k: __import__("json").dumps(payload))
    counter = {"llm_calls": 0}
    got = memory.extract_memories("记住我以后优先查三命通会", "好的", counter=counter)
    assert [g["key"] for g in got] == ["preferred_book", "birth_time"]
    assert got[0]["value"] == "以后优先查《三命通会》"
    assert counter["llm_calls"] == 1


def test_extract_failure_returns_empty(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(rag, "_chat", boom)
    assert memory.extract_memories("记住：只看原文", "好") == []


def test_summarize_uses_previous_summary(monkeypatch):
    seen = {}

    def fake_chat(messages, **kwargs):
        seen["prompt"] = messages[-1]["content"]
        return '{"summary": "  新摘要  "}'

    monkeypatch.setattr(rag, "_chat", fake_chat)
    msgs = [SimpleNamespace(role="user", content="问题"),
            SimpleNamespace(role="assistant", content="回答")]
    got = memory.summarize_messages(msgs, previous="旧摘要")
    assert got == "新摘要"
    assert "旧摘要" in seen["prompt"] and "问题" in seen["prompt"]


def test_memory_block_marks_not_evidence_and_supports_orm():
    block = conversation.memory_block([
        {"kind": "preference", "key": "preferred_book", "value": "《三命通会》"},
        SimpleNamespace(kind="fact", key="birth_time", value="1992-11-15 14:00"),
    ])
    assert "不作为回答证据" in block
    assert "[偏好] preferred_book: 《三命通会》" in block
    assert "[事实] birth_time: 1992-11-15 14:00" in block


def test_upsert_memory_updates_in_place(session, user, conv):
    first = repo.upsert_memory(
        session, user.id, "preference", "preferred_book", "《三命通会》",
        source_conversation_id=conv.id,
    )
    second = repo.upsert_memory(
        session, user.id, "preference", "preferred_book", "《穷通宝鉴》"
    )
    assert first.id == second.id
    # 覆盖已有值不直接生效：新值进 pending，等用户确认
    assert second.value == "《三命通会》"
    assert second.pending_value == "《穷通宝鉴》"
    assert repo.memory_status(second) == "pending"
    assert session.query(UserMemory).count() == 1
    assert repo.upsert_memory(session, user.id, "bad", "k", "v") is None
    assert repo.upsert_memory(session, user.id, "fact", "k", "   ") is None


def test_first_write_is_active_and_same_value_is_idempotent(session, user):
    first = repo.upsert_memory(session, user.id, "preference", "style", "回答简短")
    assert repo.memory_status(first) == "active"
    assert first.version == 1

    # 同一偏好被重复抽取：不制造待确认项，也不涨版本
    again = repo.upsert_memory(session, user.id, "preference", "style", "回答简短")
    assert repo.memory_status(again) == "active"
    assert again.version == 1


def test_confirm_and_reject_pending_value(session, user):
    memory = repo.upsert_memory(session, user.id, "preference", "style", "回答简短")
    repo.upsert_memory(session, user.id, "preference", "style", "回答详细")

    confirmed = repo.confirm_memory(session, user.id, memory.id)
    assert confirmed.value == "回答详细"
    assert confirmed.pending_value is None
    assert confirmed.version == 3

    # 没有待确认项时，确认是幂等的
    assert repo.confirm_memory(session, user.id, memory.id).value == "回答详细"

    repo.upsert_memory(session, user.id, "preference", "style", "用古文腔")
    rejected = repo.reject_memory(session, user.id, memory.id)
    assert rejected.value == "回答详细"
    assert rejected.pending_value is None
    assert repo.memory_status(rejected) == "active"


def test_stale_version_raises_conflict(session, user):
    memory = repo.upsert_memory(session, user.id, "fact", "city", "杭州")
    repo.upsert_memory(session, user.id, "fact", "city", "南京")  # version 2

    with pytest.raises(repo.MemoryConflict) as excinfo:
        repo.upsert_memory(
            session, user.id, "fact", "city", "成都", expected_version=1
        )
    assert excinfo.value.current.value == "杭州"

    with pytest.raises(repo.MemoryConflict):
        repo.confirm_memory(session, user.id, memory.id, expected_version=1)
    # 冲突没有写坏任何东西
    session.expire_all()
    fresh = repo.get_memory(session, user.id, memory.id)
    assert fresh.value == "杭州" and fresh.pending_value == "南京"


def test_concurrent_upserts_do_not_lose_updates(tmp_path):
    """8 个线程同时覆盖同一条记忆：生效值不能被悄悄改掉，版本要能对上账。"""
    import threading

    engine = make_engine(
        "sqlite:///" + str(tmp_path / "conc.db").replace("\\", "/")
    )
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        u = User(anonymous_id="conc-user")
        s.add(u)
        s.commit()
        s.refresh(u)
        repo.upsert_memory(s, u.id, "fact", "city", "杭州")
        user_id = u.id

    values = ["城市%d" % i for i in range(8)]
    errors = []

    def worker(value):
        try:
            with Session(engine) as s:
                repo.upsert_memory(s, user_id, "fact", "city", value)
        except Exception as exc:  # noqa: BLE001 - 测试要把线程里的异常带回主线程
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(v,)) for v in values]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    with Session(engine) as s:
        row = repo.list_memories(s, user_id)[0]
        # 覆盖已有值只进 pending：已生效的「杭州」不能被并发写改掉
        assert row.value == "杭州"
        assert row.pending_value in values
        # 1 次插入 + 8 次成功覆盖，没有丢更新时版本正好是 9
        assert row.version == 9


def test_confirm_only_own_memory(session, user):
    mine = repo.upsert_memory(session, user.id, "fact", "city", "杭州")
    other = User(anonymous_id="other-confirm")
    session.add(other)
    session.commit()
    assert repo.confirm_memory(session, other.id, mine.id) is None
    assert repo.reject_memory(session, other.id, mine.id) is None


def test_list_and_delete_memory_only_own(session, user):
    mine = repo.upsert_memory(session, user.id, "fact", "birth_time", "1992-11-15")
    other = User(anonymous_id="other")
    session.add(other)
    session.commit()
    theirs = repo.upsert_memory(session, other.id, "fact", "birth_time", "2000-01-01")

    assert [m.id for m in repo.list_memories(session, user.id)] == [mine.id]
    assert repo.delete_memory(session, user.id, theirs.id) is False
    assert repo.delete_memory(session, user.id, mine.id) is True
    assert repo.list_memories(session, user.id) == []


def test_maybe_summarize_writes_upto_and_stops(session, conv, monkeypatch):
    for i in range(5):
        session.add(Message(conversation_id=conv.id, role="user", content="问%d" % i))
        session.add(Message(conversation_id=conv.id, role="assistant", content="答%d" % i))
    session.commit()

    calls = []

    def fake_summary(msgs, previous=None, api_key=None):
        calls.append(len(msgs))
        return "摘要"

    monkeypatch.setattr(memory, "summarize_messages", fake_summary)
    all_msgs = repo.list_messages(session, conv.id)
    got = memory.maybe_summarize(session, conv, min_new_messages=8, keep_recent=4)
    assert got == "摘要"
    assert calls == [6]  # 10 条里留最近 4 条，摘要前 6 条
    assert conv.summary == "摘要"
    assert conv.summary_upto_id == all_msgs[5].id

    # 只新增 4 条，不够 8 条，不应再调用模型
    assert memory.maybe_summarize(session, conv, min_new_messages=8, keep_recent=4) is None
    assert calls == [6]


def test_rag_injects_memory_but_citations_stay_from_hits(monkeypatch):
    hits = [{"chunk_id": 7, "text": "羊刃者……",
             "meta": {"book": "三命通会", "volume": "", "chapter": ""}}]
    monkeypatch.setattr(rag, "retrieve_one", lambda *a, **k: hits)
    seen = {}

    def fake_chat(messages, **kwargs):
        seen["user"] = messages[-1]["content"]
        return '{"can_answer": true, "answer": "羊刃……[1]", "citations": [1]}'

    monkeypatch.setattr(rag, "_chat", fake_chat)
    res = rag.answer(
        "羊刃是什么",
        memories=[{"kind": "preference", "key": "preferred_book",
                   "value": "《三命通会》"}],
    )
    assert "长期记忆" in seen["user"]
    assert "不作为回答证据" in seen["user"]
    assert res["citations_chunk_ids"] == [7]


def test_agent_injects_memory_into_first_prompt(monkeypatch):
    import agent

    monkeypatch.setattr(agent, "rewrite_question", lambda q, h, **k: q)
    seen = {}

    def fake_chat(messages, **kwargs):
        seen["user"] = messages[-1]["content"]
        # function calling 路径：没有 tool_calls 的消息就是终稿
        return {"content": ('{"thought": "无依据", "can_answer": false, '
                            '"answer": "没有依据", "citations": [], "refusal_reason": "无"}')}

    monkeypatch.setattr(rag, "_chat_message", fake_chat)
    agent.agent_answer(
        "羊刃是什么",
        memories=[{"kind": "fact", "key": "birth_time", "value": "1992-11-15"}],
    )
    assert "长期记忆" in seen["user"]
    assert "1992-11-15" in seen["user"]


def test_long_preference_is_stored_in_full_but_prompt_keeps_first_200(session, user, conv):
    """存储上限（2000）和 prompt 上限（200）是两回事：库里不丢，进 prompt 时压缩。"""
    long_value = "以后优先查《三命通会》，其次《穷通宝鉴》。" * 20
    saved = repo.upsert_memory(
        session, user.id, "preference", "reading_order", long_value,
        source_conversation_id=conv.id,
    )
    # 旧实现写入就砍到 500/200，后半句在库里也找不回来
    assert saved.value == long_value
    assert len(saved.value) > 400

    block = conversation.memory_block([saved])
    line = next(item for item in block.splitlines() if item.startswith("- "))
    value_part = line.split(": ", 1)[1]
    assert len(value_part) == 200
    assert value_part.endswith("…")
    # 截断的是尾巴，不是开头：模型仍能看到偏好开头
    assert long_value[:199] in block


def test_extract_keeps_values_longer_than_prompt_budget(monkeypatch):
    """抽取器不能把 200 当作拒绝线：长偏好先存下来，展示时再压缩。"""
    import json

    value = "甲" * 500
    payload = {"memories": [{"kind": "preference", "key": "style", "value": value}]}
    monkeypatch.setattr(rag, "_chat", lambda *a, **k: json.dumps(payload))
    got = memory.extract_memories("记住我的偏好", "好")
    assert [g["value"] for g in got] == [value]


def test_extract_rejects_value_beyond_storage_limit():
    assert memory._valid_item(
        {"kind": "fact", "key": "kk", "value": "甲" * memory.MAX_VALUE_CHARS}
    ) is not None
    assert memory._valid_item(
        {"kind": "fact", "key": "kk", "value": "甲" * (memory.MAX_VALUE_CHARS + 1)}
    ) is None
