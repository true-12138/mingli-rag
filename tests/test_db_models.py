# -*- coding: utf-8 -*-
"""业务表结构测试：不连真实数据库、不调模型。

只验证三件事：
1. 7 张表能建出来；
2. 外键和关系能正常用；
3. 删除会话时，消息 / 运行 / 工具调用 / 反馈会跟着删。
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from db.base import Base, make_engine
from db.models import (
    Conversation,
    Feedback,
    Message,
    QuotaLedger,
    Run,
    ToolCall,
    User,
)


@pytest.fixture()
def session():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    Base.metadata.drop_all(engine)


def _user(session: Session, anonymous_id: str = "anon-1") -> User:
    user = User(anonymous_id=anonymous_id)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _conversation(session: Session, user: User) -> Conversation:
    conv = Conversation(id="c" * 32, user=user, title="第一问")
    session.add(conv)
    session.commit()
    return conv


def test_creates_seven_business_tables(session):
    assert set(Base.metadata.tables) == {
        "users",
        "conversations",
        "messages",
        "runs",
        "tool_calls",
        "feedback",
        "quota_ledger",
    }


def test_user_conversation_message_relationship(session):
    user = _user(session)
    conv = _conversation(session, user)
    msg = Message(conversation_id=conv.id, role="user", content="羊刃是什么？")
    session.add(msg)
    session.commit()

    assert conv.user.anonymous_id == "anon-1"
    assert conv.messages[0].content == "羊刃是什么？"
    assert user.conversations[0].id == conv.id


def test_run_tool_call_and_feedback_relationship(session):
    user = _user(session)
    conv = _conversation(session, user)
    run = Run(
        id="r" * 32,
        trace_id="t" * 32,
        conversation_id=conv.id,
        mode="agent",
        question="羊刃分几种？",
    )
    session.add(run)
    session.commit()

    call = ToolCall(
        run_id=run.id,
        step_no=1,
        tool_name="search_classics",
        args_json='{"query": "羊刃"}',
        ok=True,
        chunk_ids_json="[1, 2]",
    )
    feedback = Feedback(run_id=run.id, user_id=user.id, rating=-1, reason="没引用原文")
    session.add_all([call, feedback])
    session.commit()

    assert run.tool_calls[0].tool_name == "search_classics"
    assert run.feedback[0].rating == -1
    assert call.run.id == run.id


def test_deleting_conversation_cascades_to_children(session):
    user = _user(session)
    conv = _conversation(session, user)
    run = Run(
        id="r" * 32, trace_id="t" * 32, conversation_id=conv.id,
        mode="rag", question="q",
    )
    session.add(run)
    session.commit()
    session.add(Message(conversation_id=conv.id, role="user", content="hi"))
    session.add(ToolCall(run_id=run.id, step_no=1, tool_name="search_classics"))
    session.add(Feedback(run_id=run.id, user_id=user.id, rating=1))
    session.commit()

    session.delete(conv)
    session.commit()

    assert session.query(Message).count() == 0
    assert session.query(Run).count() == 0
    assert session.query(ToolCall).count() == 0
    assert session.query(Feedback).count() == 0
    # 用户本身不能被会话的级联删掉
    assert session.query(User).count() == 1


def test_foreign_key_is_enforced(session):
    session.add(Conversation(id="c" * 32, user_id=999))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_quota_ledger_is_unique_per_scope_user_day(session):
    user = _user(session)
    row = dict(scope="user", user_id=user.id, day="2026-11-04", llm_calls=1)
    session.add(QuotaLedger(**row))
    session.commit()

    session.add(QuotaLedger(**row))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
