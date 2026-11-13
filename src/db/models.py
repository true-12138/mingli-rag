# -*- coding: utf-8 -*-
"""业务表的定义。

关系：

    users 1 ── N conversations 1 ── N messages
                           │
                           └── N runs 1 ── N tool_calls
                                      │
                                      └── N feedback

    users 1 ── N quota_ledger

为什么主键有的是整数、有的是 32 位字符串：
- 用户、消息、工具调用：内部自增整数，查询快；
- 会话、运行：对外暴露给前端，用 `uuid4().hex`，避免别人顺序猜 ID。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .base import Base


def utcnow() -> datetime:
    """统一用带时区的 UTC 时间，避免服务器时区不同导致时间对不上。"""
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 匿名访客也有一个稳定的 anonymous_id，前端存在 localStorage 里
    anonymous_id = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)

    conversations = relationship(
        "Conversation",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    memories = relationship(
        "UserMemory",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(32), primary_key=True)  # uuid4().hex
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title = Column(String(200), nullable=False, default="新会话")
    # 会话摘要：历史太长时，用它代替早期原始消息
    summary = Column(Text, nullable=True)
    # 摘要已经覆盖到哪条消息；没变就不重复调用模型
    summary_upto_id = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="active")  # active / archived
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    user = relationship("User", back_populates="conversations")
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.created_at",
    )
    runs = relationship(
        "Run",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Run.created_at",
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant', 'system')", name="ck_messages_role"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(
        String(32),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    conversation = relationship("Conversation", back_populates="messages")


class Run(Base):
    """一次问答或 Agent 运行。

    `trace_id` 和 `id` 分开：`id` 是运行主键，`trace_id` 是接口返回给调用方的追踪号。
    现在两者可以相同，但以后换成 Langfuse 时 trace_id 可能由外部系统给。
    """

    __tablename__ = "runs"

    id = Column(String(32), primary_key=True)  # uuid4().hex
    conversation_id = Column(
        String(32),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,  # 不传会话的单次调用也允许
        index=True,
    )
    trace_id = Column(String(32), unique=True, nullable=False, index=True)
    mode = Column(String(20), nullable=False)  # rag / agent / multi / retrieve
    question = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="running")  # running / succeeded / failed / refused

    can_answer = Column(Boolean, nullable=True)
    answer = Column(Text, nullable=True)
    refusal_reason = Column(Text, nullable=True)
    invalid_output = Column(Boolean, nullable=False, default=False)
    elapsed_ms = Column(Float, nullable=True)
    # 这条回答引用了哪些 chunk：[12, 34]。消息表只存正文，不落这里的话
    # 刷新页面后引用 chip 就丢了。用 Text 存 JSON，和 args_json 的做法一致。
    citations_json = Column(Text, nullable=True)

    llm_calls = Column(Integer, nullable=False, default=0)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)

    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    conversation = relationship("Conversation", back_populates="runs")
    tool_calls = relationship(
        "ToolCall",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ToolCall.step_no",
    )
    feedback = relationship(
        "Feedback",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ToolCall(Base):
    """Agent 每一步的工具调用，用于回放和审计。

    只存结果的摘要（`result_digest`），不存完整原文——完整原文在语料里，
    重复存一遍会让数据库迅速膨胀。
    """

    __tablename__ = "tool_calls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(
        String(32), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_no = Column(Integer, nullable=False)
    # 多 Agent 版会有 supervisor / retriever 等角色；单 Agent 留空
    agent = Column(String(30), nullable=True)
    tool_name = Column(String(50), nullable=False)
    # 模型调用这个工具前的想法，回放时能看出“为什么搜这个”
    thought = Column(Text, nullable=True)
    args_json = Column(Text, nullable=True)
    ok = Column(Boolean, nullable=False, default=False)
    result_digest = Column(Text, nullable=True)
    chunk_ids_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    latency_ms = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    run = relationship("Run", back_populates="tool_calls")


class Feedback(Base):
    """用户对一次回答的反馈。

    差评会由后台任务转成 `eval_cases` 里的一条回归用例，
    这就是「线上失败 → 评测集 → 回归门」的闭环入口。
    """

    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(
        String(32), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rating = Column(Integer, nullable=False)  # 1 = 有用，-1 = 没用
    reason = Column(Text, nullable=True)
    expected_answer = Column(Text, nullable=True)
    promoted_to_eval = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    run = relationship("Run", back_populates="feedback")


class UserMemory(Base):
    """用户长期记忆：只存用户明确说过的稳定偏好/事实。

    它不是聊天记录，也不是证据库：
    - 只用于个性化（比如「以后优先查《三命通会》」）；
    - 回答里的 citations 仍然只能来自本轮工具返回的 chunk；
    - 同一 (user_id, kind, key) 只保留一条。

    写入不是无条件覆盖：
    - `version` 是乐观锁，每次成功写入 +1；并发写时后到的那个条件 UPDATE 失败，
      不会悄悄覆盖别人刚写进去的值。
    - 覆盖一个**已有值**时，新值先放在 `pending_value` 里等用户确认；
      `value` 始终是当前生效的值，所以 prompt 永远只用到确认过的记忆。
      首次写入没有可覆盖的值，直接生效。
    """

    __tablename__ = "user_memories"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "key", name="uq_user_memory_key"),
        CheckConstraint("kind in ('preference', 'fact')", name="ck_user_memory_kind"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = Column(String(20), nullable=False)  # preference / fact
    key = Column(String(50), nullable=False)
    value = Column(Text, nullable=False)
    source_conversation_id = Column(
        String(32),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    confidence = Column(Float, nullable=False, default=0.5)
    # 乐观锁版本号：UPDATE 带上 WHERE version = 读到的版本，rowcount=0 就是有人先改了。
    version = Column(Integer, nullable=False, default=1, server_default="1")
    # 待确认的新值。非空时 value 仍是生效值，prompt 不会读到这里。
    pending_value = Column(Text, nullable=True)
    pending_confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    user = relationship("User", back_populates="memories")


class PendingAction(Base):
    """模型提议、但还没获得用户授权的有副作用工具调用。

    这张表是「确认」这一动作的持久化载体：模型在运行中只能拿到
    `requires_confirmation`，真正执行要等用户对某一行点确认，拿走一个
    一次性令牌，并在下一次运行时带回来。

    `args_hash` 存参数的 canonical JSON 摘要，令牌只对「同一工具 + 同一组参数」
    有效；`token_hash` 只存令牌的 sha256，数据库泄露也拿不到可用的明文令牌。
    """

    __tablename__ = "pending_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id = Column(String(32), nullable=True)
    tool = Column(String(200), nullable=False)
    args_json = Column(Text, nullable=False, default="{}")
    args_hash = Column(String(64), nullable=False, index=True)
    reason = Column(Text, nullable=True)
    # pending / approved / rejected / consumed
    status = Column(String(20), nullable=False, default="pending", index=True)
    token_hash = Column(String(64), nullable=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)


class QuotaLedger(Base):
    """按天累计的额度/成本账本。

    以后把 `data/.quota.json` 换掉：文件计数多进程会互相覆盖，
    数据库有唯一约束和事务，才能算准。
    """

    __tablename__ = "quota_ledger"
    __table_args__ = (
        UniqueConstraint("scope", "user_id", "day", name="uq_quota_scope_user_day"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    scope = Column(String(20), nullable=False, default="user")  # user / global
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    day = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    llm_calls = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
