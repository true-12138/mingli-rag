# -*- coding: utf-8 -*-
"""业务数据的读写函数。

接口层（`api_conversations.py`）不直接拼 SQL，只调用这里的函数。
这样以后换存储、加缓存，只需要改这一个文件。

约定：
- 函数自己 `commit` 的，会在文档里写明；需要把多条写操作放在一个事务里的，
  用 `commit=False`，最后由调用方统一提交。
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Conversation, Message, User, utcnow

# 一次最多带最近 3 轮（6 条）进 prompt；和 conversation.normalize_history 的预算一致。
DEFAULT_HISTORY_MESSAGES = 6


def get_or_create_user(session: Session, anonymous_id: str) -> User:
    """按匿名 ID 找用户，没有就建一个。会 commit。"""
    anonymous_id = (anonymous_id or "").strip()[:64] or "demo"

    user = session.scalar(select(User).where(User.anonymous_id == anonymous_id))
    if user is None:
        user = User(anonymous_id=anonymous_id)

    user.last_seen_at = utcnow()
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        # 两个请求同时首次访问同一个匿名 ID，唯一约束只让一个成功。
        session.rollback()
        user = session.scalar(select(User).where(User.anonymous_id == anonymous_id))
        user.last_seen_at = utcnow()
        session.commit()
    return user


def create_conversation(session: Session, user: User, title: str | None = None) -> Conversation:
    """新建会话。会 commit。"""
    conv = Conversation(
        id=uuid.uuid4().hex,
        user_id=user.id,
        title=(title or "新会话").strip()[:200] or "新会话",
    )
    session.add(conv)
    session.commit()
    session.refresh(conv)
    return conv


def list_conversations(
    session: Session, user_id: int, limit: int = 50
) -> list[tuple[Conversation, int]]:
    """列出用户的会话，附带每个会话的消息数。

    先按会话分组数出消息数，再和会话表 LEFT JOIN，
    避免“先查 50 个会话、再逐个查消息”的 N+1，也兼容 Postgres 的 GROUP BY 规则。
    返回 [(Conversation, message_count), ...]，最近更新的在前。
    """
    counts = (
        select(
            Message.conversation_id.label("conversation_id"),
            func.count(Message.id).label("message_count"),
        )
        .group_by(Message.conversation_id)
        .subquery()
    )
    stmt = (
        select(Conversation, func.coalesce(counts.c.message_count, 0))
        .outerjoin(counts, counts.c.conversation_id == Conversation.id)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).all())


def get_conversation(session: Session, conversation_id: str, user_id: int) -> Conversation | None:
    """按 ID 取会话，同时校验归属。

    别人的会话一律当作“不存在”（404），不返回 403——
    否则等于告诉对方“这个 ID 真的存在”。
    """
    return session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )


def add_message(
    session: Session,
    conversation: Conversation,
    role: str,
    content: str,
    *,
    commit: bool = True,
) -> Message:
    """追加一条消息，并更新会话的 updated_at。

    `commit=False` 时只 flush（拿到自增 id），由调用方统一提交。
    """
    msg = Message(
        conversation_id=conversation.id,
        role=role,
        content=content,
        token_count=len(content),  # 先按字符数粗记，等接入 tokenizer 再换
    )
    session.add(msg)
    conversation.updated_at = utcnow()
    session.flush()
    if commit:
        session.commit()
        session.refresh(msg)
    return msg


def recent_history(
    session: Session, conversation_id: str, limit: int = DEFAULT_HISTORY_MESSAGES
) -> list[dict[str, str]]:
    """取最近 N 条消息，按时间正序返回，直接喂给 rag.answer(history=...)。

    先按 id 倒序取 N 条，再反转，避免数据库不支持“倒序取尾部”的写法。
    """
    rows = session.scalars(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.role.in_(("user", "assistant")),
        )
        .order_by(Message.id.desc())
        .limit(limit)
    ).all()
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


def rename_if_untitled(session: Session, conversation: Conversation, question: str) -> None:
    """第一次提问时，用问题前 30 个字当标题。"""
    if conversation.title in ("", "新会话"):
        conversation.title = question.strip()[:30] or "新会话"
        session.flush()


def delete_conversation(session: Session, conversation: Conversation) -> None:
    """删除会话。消息、运行、工具调用、反馈由数据库级联删除。"""
    session.delete(conversation)
    session.commit()
