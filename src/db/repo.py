# -*- coding: utf-8 -*-
"""业务数据的读写函数。

接口层（`api_conversations.py`）不直接拼 SQL，只调用这里的函数。
这样以后换存储、加缓存，只需要改这一个文件。

约定：
- 函数自己 `commit` 的，会在文档里写明；需要把多条写操作放在一个事务里的，
  用 `commit=False`，最后由调用方统一提交。
"""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    Conversation,
    Feedback,
    Message,
    PendingAction,
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
    # 和 memory.MAX_VALUE_CHARS 对齐：写入保留完整偏好，prompt 侧再压缩。
    value = (value or "").strip()[:2000]
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


# ---------- 工具授权（PendingAction） ----------

class ActionConflict(Exception):
    """动作已经不在 pending 状态，不能再确认/拒绝。

    `current` 是冲突时库里的那一行，接口层用它把最新状态返回给前端。
    """

    def __init__(self, current: PendingAction | None = None):
        super().__init__("pending action state conflict")
        self.current = current


def _canonical_args(args) -> str:
    """参数规范化：键排序、无多余空格，保证同一组参数永远同一个摘要。

    不能用普通的 `json.dumps` 直接算哈希——Python 字典的顺序、空格都会变，
    同一组参数换个键顺序就成了另一个哈希，令牌会莫名其妙失效。
    """
    return json.dumps(
        args if args is not None else {},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _args_hash(args) -> str:
    return hashlib.sha256(_canonical_args(args).encode("utf-8")).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _is_expired(expires_at, now) -> bool:
    """比较过期时间；SQLite 读出来是 naive datetime，统一按 UTC 解释。

    直接拿 naive 和 aware 比会抛 TypeError，而这条路径恰好是「用户点确认」，
    不能因为数据库方言不同就 500。
    """
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= now


def _find_pending_action(
    session: Session, user_id: int, tool: str, args_hash: str
) -> PendingAction | None:
    """按「同一用户 + 同一工具 + 同一参数摘要」取仍在 pending 的那一行。"""
    return session.scalar(
        select(PendingAction)
        .where(
            PendingAction.user_id == user_id,
            PendingAction.tool == tool,
            PendingAction.args_hash == args_hash,
            PendingAction.status == "pending",
        )
        .order_by(PendingAction.id.desc())
        .limit(1)
    )


def create_pending_action(
    session: Session,
    user_id: int,
    tool: str,
    args,
    *,
    conversation_id: str | None = None,
    reason: str | None = None,
) -> PendingAction:
    """把一次「需要用户确认」的调用落库；同一用户同一工具同一参数只留一条 pending。

    幂等是必要的：模型在一轮里可能反复尝试同一个被拒的工具，前端也会重复提交，
    每轮都插入新行会让待确认列表迅速膨胀、用户还要点很多次同样的确认。

    先查一次是快路径；两个请求同时到达时都会查不到，插入阶段由部分唯一索引
    `uq_pending_actions_pending_args` 兜底，后到的那个捕获 `IntegrityError`、
    回滚后返回先写入的那一行。

    会 commit。
    """
    tool = (str(tool) or "").strip()[:200]
    args_json = _canonical_args(args)
    args_hash = _args_hash(args)

    existing = _find_pending_action(session, user_id, tool, args_hash)
    if existing is not None:
        return existing

    action = PendingAction(
        user_id=user_id,
        conversation_id=conversation_id,
        tool=tool,
        args_json=args_json,
        args_hash=args_hash,
        reason=reason,
        status="pending",
    )
    session.add(action)
    try:
        session.commit()
    except IntegrityError:
        # 并发请求抢先插入了同一组 (user, tool, args_hash) 的 pending 行。
        # rollback 让会话回到干净状态，再读回那条已存在的行。
        session.rollback()
        existing = _find_pending_action(session, user_id, tool, args_hash)
        if existing is None:
            # 不是这条部分唯一索引造成的冲突（比如 user_id 外键不存在），
            # 不能静默吞掉。
            raise
        return existing
    session.refresh(action)
    return action


def list_pending_actions(
    session: Session,
    user_id: int,
    limit: int = 20,
    *,
    conversation_id: str | None = None,
) -> list[PendingAction]:
    """按创建时间倒序列出仍在等用户确认的动作。

    `conversation_id` 是关键字参数（旧调用方可能按位置传 limit）：
    传入非空值时只返回该会话下的项，不传/传空保持原来的全量行为。
    归属仍由 `user_id` 约束，别人的会话 ID 不会带出任何行。
    """
    stmt = select(PendingAction).where(
        PendingAction.user_id == user_id,
        PendingAction.status == "pending",
    )
    if conversation_id:
        stmt = stmt.where(PendingAction.conversation_id == conversation_id)
    stmt = stmt.order_by(
        PendingAction.created_at.desc(), PendingAction.id.desc()
    ).limit(limit)
    return list(session.scalars(stmt).all())


def get_pending_action(
    session: Session, user_id: int, action_id: int
) -> PendingAction | None:
    """按 ID 取动作，同时校验归属；别人的动作一律当作不存在。"""
    return session.scalar(
        select(PendingAction).where(
            PendingAction.id == action_id,
            PendingAction.user_id == user_id,
        )
    )


def approve_action(
    session: Session, user_id: int, action_id: int, ttl_seconds: int = 600
) -> tuple[PendingAction, str] | None:
    """确认一个待执行动作，返库里的行和**一次性明文令牌**。

    明文令牌只在这里出现一次：库里只存 sha256，之后再也取不回来。
    状态切换用条件 UPDATE（`WHERE status='pending'`），并发点两次确认时
    只有一次能拿到令牌，另一次按 `ActionConflict` 处理。

    `ttl_seconds` 控制令牌有效期；过期后重放会被 `consume_grant` 拒绝。
    **令牌过期但动作还没被执行时，允许重新确认并换发新令牌**：否则用户点了
    「允许」却因为去接了杯水而失败，只能等模型下一轮重新提议，等于确认按钮坏了。
    已消费或已拒绝的动作仍然只能得到 409。

    会 commit。
    """
    action = get_pending_action(session, user_id, action_id)
    if action is None:
        return None

    now = utcnow()
    reissue = _is_expired(action.expires_at, now)
    if action.status != "pending" and not (action.status == "approved" and reissue):
        raise ActionConflict(action)

    token = "act_" + secrets.token_urlsafe(24)
    if action.status == "approved":
        # 重发只针对「已确认、未使用、已过期」的那一行，条件写进 UPDATE 里防止
        # 和并发消费撞车：令牌刚好在点确认的瞬间被重放成功时，这里不会覆盖它。
        where = (
            PendingAction.id == action_id,
            PendingAction.user_id == user_id,
            PendingAction.status == "approved",
            PendingAction.expires_at.is_not(None),
            PendingAction.expires_at <= now,
        )
    else:
        where = (
            PendingAction.id == action_id,
            PendingAction.user_id == user_id,
            PendingAction.status == "pending",
        )
    result = session.execute(
        update(PendingAction)
        .where(*where)
        .values(
            status="approved",
            token_hash=_token_hash(token),
            expires_at=now + timedelta(seconds=ttl_seconds),
            approved_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if not result.rowcount:
        # 另一个请求先点了确认：把库里最新的状态带出去，而不是覆盖它。
        session.expire_all()
        raise ActionConflict(get_pending_action(session, user_id, action_id))
    session.commit()
    session.refresh(action)
    return action, token


def reject_action(
    session: Session, user_id: int, action_id: int
) -> PendingAction | None:
    """拒绝一个待执行动作。只有 pending 能拒绝，已确认/已执行的一律冲突。

    会 commit。
    """
    action = get_pending_action(session, user_id, action_id)
    if action is None:
        return None
    if action.status != "pending":
        raise ActionConflict(action)

    result = session.execute(
        update(PendingAction)
        .where(
            PendingAction.id == action_id,
            PendingAction.user_id == user_id,
            PendingAction.status == "pending",
        )
        .values(status="rejected")
        .execution_options(synchronize_session=False)
    )
    if not result.rowcount:
        session.expire_all()
        raise ActionConflict(get_pending_action(session, user_id, action_id))
    session.commit()
    session.refresh(action)
    return action


def consume_grant(
    session: Session, user_id: int, token: str, tool: str, args
) -> bool:
    """用一次性令牌换一次工具执行权；成功返回 True，否则 False。

    三个条件必须同时满足，任何一条不满足都不放行：
    1. 令牌存在、属于该用户、状态仍是 approved、且没过期；
    2. 工具名和确认时完全一致；
    3. 参数的 canonical 摘要和确认时完全一致。

    实现上用一条条件 UPDATE 把 approved 改成 consumed，靠 `rowcount` 判断
    是否抢到。两个请求同时拿同一个令牌重放时，数据库只会让一条 UPDATE 命中，
    所以不需要额外的行锁。会 commit（仅成功时）。
    """
    if not token:
        return False
    result = session.execute(
        update(PendingAction)
        .where(
            PendingAction.user_id == user_id,
            PendingAction.token_hash == _token_hash(token),
            PendingAction.status == "approved",
            PendingAction.tool == (str(tool) or "").strip()[:200],
            PendingAction.args_hash == _args_hash(args),
            PendingAction.expires_at.is_not(None),
            PendingAction.expires_at > utcnow(),
        )
        .values(status="consumed")
        .execution_options(synchronize_session=False)
    )
    if not result.rowcount:
        # 没抢到：令牌不存在/已用过/已过期/参数对不上。不 commit，
        # 也不 rollback，避免把调用方同一事务里其他已做的修改一起回滚。
        return False
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
