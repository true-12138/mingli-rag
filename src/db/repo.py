# -*- coding: utf-8 -*-
"""业务数据的读写函数。

接口层（`api_conversations.py`）不直接拼 SQL，只调用这里的函数。
这样以后换存储、加缓存，只需要改这一个文件。

约定：
- 函数自己 `commit` 的，会在文档里写明；需要把多条写操作放在一个事务里的，
  用 `commit=False`，最后由调用方统一提交。
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    Conversation,
    Feedback,
    Message,
    Run,
    ToolCall,
    User,
    UserMemory,
    utcnow,
)

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


# ---------- 运行记录 ----------

def _json(value) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def create_run(
    session: Session,
    conversation: Conversation,
    trace_id: str,
    mode: str,
    question: str,
) -> Run:
    """问答开始前先落一条 running 记录。

    好处：即使进程中途被杀，数据库里也能看到“有一次运行没结束”，
    而不是什么都没留下。会 commit。
    """
    run = Run(
        id=uuid.uuid4().hex,
        conversation_id=conversation.id,
        trace_id=trace_id,
        mode=mode,
        question=question,
        status="running",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def finish_run(
    session: Session,
    run: Run,
    result: dict,
    elapsed_ms: float,
    usage_data: dict | None,
    *,
    commit: bool = True,
) -> Run:
    """把一次成功（含拒答）的运行结果写回 runs 表。"""
    run.status = "refused" if result.get("can_answer") is False else "succeeded"
    run.can_answer = result.get("can_answer")
    run.answer = result.get("answer") or ""
    run.refusal_reason = result.get("refusal_reason")
    run.invalid_output = bool(result.get("invalid_output"))
    run.elapsed_ms = elapsed_ms
    run.llm_calls = int(result.get("llm_calls") or 0)
    # 引用正文在语料里，这里只存 id；会话回放时前端按 id 批量取原文。
    # RAG 有 citation_map（正文 [n] → chunk），连同标记一起存，回放时点 [n] 才不会串。
    run.citations_json = json.dumps(
        result.get("citation_map") or result.get("citations_chunk_ids") or [],
        ensure_ascii=False,
    )

    usage_data = usage_data or {}
    run.prompt_tokens = int(usage_data.get("prompt_tokens") or 0)
    run.completion_tokens = int(usage_data.get("completion_tokens") or 0)
    run.total_tokens = int(usage_data.get("total_tokens") or 0)
    # DeepSeek 价格随时会变，先把 token 记准，成本列留 0，按账单再回填。
    run.cost_usd = 0.0
    run.finished_at = utcnow()

    session.flush()
    if commit:
        session.commit()
    return run


def fail_run(
    session: Session, run: Run, error: str, elapsed_ms: float | None = None
) -> Run:
    """模型调用抛异常时，把运行标成 failed，错误信息截断后留档。"""
    run.status = "failed"
    run.error = (str(error) or "unknown")[:2000]
    run.elapsed_ms = elapsed_ms
    run.finished_at = utcnow()
    session.commit()
    return run


def add_tool_calls(
    session: Session, run: Run, trace: list[dict] | None, *, commit: bool = True
) -> list[ToolCall]:
    """把 agent 的 trace 逐步写进 tool_calls 表。

    只存参数、chunk_id 列表和错误摘要；完整原文留在语料里，不重复入库。
    """
    calls: list[ToolCall] = []
    for index, step in enumerate(trace or [], 1):
        if not isinstance(step, dict):
            continue
        call = ToolCall(
            run_id=run.id,
            step_no=int(step.get("step") or index),
            agent=(str(step.get("agent"))[:30] if step.get("agent") else None),
            tool_name=str(step.get("action") or "unknown")[:50],
            thought=step.get("thought"),
            args_json=_json(step.get("args")),
            ok=bool(step.get("ok")),
            chunk_ids_json=_json(step.get("chunk_ids") or []),
            error=(str(step.get("error"))[:2000] if step.get("error") else None),
        )
        session.add(call)
        calls.append(call)
    session.flush()
    if commit:
        session.commit()
    return calls


def get_run(session: Session, run_id: str, user_id: int) -> Run | None:
    """按运行 ID 取记录，并通过会话校验归属。"""
    return session.scalar(
        select(Run)
        .join(Conversation, Run.conversation_id == Conversation.id)
        .where(Run.id == run_id, Conversation.user_id == user_id)
    )


def list_runs(
    session: Session, conversation_id: str, limit: int = 50
) -> list[Run]:
    """列出某个会话下的运行记录，最近的在前。"""
    return list(
        session.scalars(
            select(Run)
            .where(Run.conversation_id == conversation_id)
            .order_by(Run.created_at.desc())
            .limit(limit)
        ).all()
    )


# ---------- 反馈 ----------

def upsert_feedback(
    session: Session,
    run: Run,
    user_id: int,
    rating: int,
    reason: str | None = None,
    expected_answer: str | None = None,
) -> Feedback:
    """一个用户对一次运行只保留一条反馈；再提交就是修改。会 commit。"""
    fb = session.scalar(
        select(Feedback).where(
            Feedback.run_id == run.id,
            Feedback.user_id == user_id,
        )
    )
    if fb is None:
        fb = Feedback(run_id=run.id, user_id=user_id, rating=rating)
        session.add(fb)
    fb.rating = rating
    fb.reason = reason
    fb.expected_answer = expected_answer
    # 改了评价就重新进入“待晋升”队列，避免旧结论被永久标记为已处理。
    fb.promoted_to_eval = False
    session.commit()
    session.refresh(fb)
    return fb


def feedback_for_run(session: Session, run_id: str) -> list[Feedback]:
    return list(
        session.scalars(
            select(Feedback)
            .where(Feedback.run_id == run_id)
            .order_by(Feedback.created_at)
        ).all()
    )


def pending_negative_feedback(
    session: Session, limit: int = 500
) -> list[tuple[Feedback, Run]]:
    """差评且还没晋升成评测用例的记录，连带对应的 run 一起返回。"""
    stmt = (
        select(Feedback, Run)
        .join(Run, Feedback.run_id == Run.id)
        .where(Feedback.rating == -1, Feedback.promoted_to_eval.is_(False))
        .order_by(Feedback.created_at)
        .limit(limit)
    )
    return list(session.execute(stmt).all())


# ---------- 长期记忆 ----------

MEMORY_KINDS = ("preference", "fact")
MEMORY_UPDATE_RETRIES = 3


class MemoryConflict(Exception):
    """乐观锁冲突：调用方持有的 version 已经不是库里最新的。

    `current` 是冲突发生时库里的那一行，接口层用它告诉前端「现在是什么」。
    """

    def __init__(self, current: UserMemory | None = None):
        super().__init__("memory version conflict")
        self.current = current


def memory_status(memory: UserMemory) -> str:
    """对外暴露的状态由 pending_value 推导，避免 status 和值不一致。"""
    return "pending" if memory.pending_value else "active"


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def list_memories(
    session: Session, user_id: int, limit: int = 12
) -> list[UserMemory]:
    """按最近更新时间取用户的长期记忆。

    返回的行里 `value` 永远是已生效的值；`pending_value` 非空只表示
    「有个新值在等确认」，不会进 prompt。所以这里不需要按状态过滤。
    """
    return list(
        session.scalars(
            select(UserMemory)
            .where(UserMemory.user_id == user_id)
            .order_by(UserMemory.updated_at.desc())
            .limit(limit)
        ).all()
    )


def get_memory(session: Session, user_id: int, memory_id: int) -> UserMemory | None:
    """按 ID 取记忆，同时校验归属。"""
    return session.scalar(
        select(UserMemory).where(
            UserMemory.id == memory_id,
            UserMemory.user_id == user_id,
        )
    )


def upsert_memory(
    session: Session,
    user_id: int,
    kind: str,
    key: str,
    value: str,
    *,
    source_conversation_id: str | None = None,
    confidence: float = 0.5,
    expected_version: int | None = None,
    commit: bool = True,
) -> UserMemory | None:
    """写入一条记忆；同一 (user, kind, key) 只留一条。

    三条边界：
    1. **首次写入直接生效**——没有旧值可覆盖，不需要确认，正常使用不受打扰。
    2. **覆盖已有值不直接生效**——新值写进 `pending_value`，`value` 保持原样，
       等用户确认。这样模型听错一句话不会当场改掉用户之前设定好的偏好。
    3. **并发写不丢更新**——UPDATE 带 `WHERE version = 读到的版本`；rowcount=0
       说明别人先改了，重新读一遍再判断（最多 3 次）。

    `expected_version` 供接口层做显式的乐观锁校验：传了且和库里不一致就抛
    `MemoryConflict`，不写入。

    返回 None 表示这条记忆不合法，被丢弃。
    """
    kind = (kind or "").strip()
    key = (key or "").strip()[:50]
    value = (value or "").strip()[:500]
    if kind not in MEMORY_KINDS or not key or not value:
        return None
    confidence = _clamp_confidence(confidence)

    memory: UserMemory | None = None
    for _ in range(MEMORY_UPDATE_RETRIES):
        memory = session.scalar(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                UserMemory.kind == kind,
                UserMemory.key == key,
            )
        )

        if memory is None:
            if expected_version is not None:
                raise MemoryConflict(None)
            # 用保存点包住 INSERT：两个请求同时首次写入时，唯一约束只让一个成功，
            # 失败方回滚到保存点后重新读，转成「待确认」，不会拖垮整个事务
            # （remember_from_turn 一轮可能写多条，前面几条不能跟着回滚）。
            savepoint = session.begin_nested()
            memory = UserMemory(
                user_id=user_id,
                kind=kind,
                key=key,
                value=value,
                source_conversation_id=source_conversation_id,
                confidence=confidence,
                version=1,
            )
            session.add(memory)
            try:
                session.flush()
            except IntegrityError:
                savepoint.rollback()
                continue
            savepoint.commit()
            if commit:
                session.commit()
                session.refresh(memory)
            return memory

        if expected_version is not None and memory.version != expected_version:
            raise MemoryConflict(memory)

        # 值没变：重复抽取同一偏好很常见，不制造一条待确认项。
        if memory.value == value:
            if commit:
                session.commit()
            return memory

        current_version = int(memory.version or 1)
        result = session.execute(
            update(UserMemory)
            .where(
                UserMemory.id == memory.id,
                UserMemory.version == current_version,
            )
            .values(
                pending_value=value,
                pending_confidence=confidence,
                version=current_version + 1,
                updated_at=utcnow(),
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount:  # 抢到了这个版本
            session.expire(memory)
            if commit:
                session.commit()
                session.refresh(memory)
            return memory
        # 版本被别的写入抢先了：吹掉本地缓存，重新读最新状态再决定。
        session.expire_all()

    raise MemoryConflict(memory)


def _transition_pending(
    session: Session,
    user_id: int,
    memory_id: int,
    *,
    accept: bool,
    expected_version: int | None = None,
) -> UserMemory | None:
    """确认或忽略一条待确认的新值；两个入口共用同一套版本校验。"""
    memory = get_memory(session, user_id, memory_id)
    if memory is None:
        return None
    if expected_version is not None and memory.version != expected_version:
        raise MemoryConflict(memory)
    # 没有待确认项：重复点击确认/忽略当作幂等成功，不报错。
    if not memory.pending_value:
        return memory

    current_version = int(memory.version or 1)
    values: dict = {
        "pending_value": None,
        "pending_confidence": None,
        "version": current_version + 1,
        "updated_at": utcnow(),
    }
    if accept:
        values["value"] = memory.pending_value
        values["confidence"] = (
            memory.pending_confidence
            if memory.pending_confidence is not None
            else memory.confidence
        )

    result = session.execute(
        update(UserMemory)
        .where(UserMemory.id == memory.id, UserMemory.version == current_version)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    session.expire(memory)
    if not result.rowcount:
        # 页面上的确认按钮点下去时，记忆已经被另一个标签页改过：拒绝而不是硬写。
        raise MemoryConflict(get_memory(session, user_id, memory_id))
    session.commit()
    session.refresh(memory)
    return memory


def confirm_memory(
    session: Session,
    user_id: int,
    memory_id: int,
    *,
    expected_version: int | None = None,
) -> UserMemory | None:
    """确认待确认的新值，把它变成生效值。会 commit。"""
    return _transition_pending(
        session, user_id, memory_id, accept=True, expected_version=expected_version
    )


def reject_memory(
    session: Session,
    user_id: int,
    memory_id: int,
    *,
    expected_version: int | None = None,
) -> UserMemory | None:
    """忽略待确认的新值，继续用原来的生效值。会 commit。"""
    return _transition_pending(
        session, user_id, memory_id, accept=False, expected_version=expected_version
    )


def delete_memory(session: Session, user_id: int, memory_id: int) -> bool:
    """删除一条属于该用户的记忆；不存在或不属于他就返回 False。"""
    memory = get_memory(session, user_id, memory_id)
    if memory is None:
        return False
    session.delete(memory)
    session.commit()
    return True


def list_messages(
    session: Session, conversation_id: str, after_id: int = 0, limit: int = 40
) -> list[Message]:
    """按 id 正序取消息；after_id 用于增量生成摘要。"""
    return list(
        session.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.id > after_id,
                Message.role.in_(("user", "assistant")),
            )
            .order_by(Message.id)
            .limit(limit)
        ).all()
    )


def mark_summary(
    session: Session,
    conversation: Conversation,
    summary: str,
    upto_id: int,
    *,
    commit: bool = True,
) -> None:
    """记录摘要和它覆盖到的最后一条消息 id。"""
    conversation.summary = summary
    conversation.summary_upto_id = upto_id
    session.flush()
    if commit:
        session.commit()
