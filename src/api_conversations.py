# -*- coding: utf-8 -*-
"""`/v1` 会话接口：把多轮对话历史存到服务端。

和旧的 `/chat` 的区别：
- 旧接口：前端每次把最近几轮 `history` 一起传上来，服务端不存；
- 新接口：前端只传 `conversation_id`，服务端从数据库读历史，重启也不丢。

身份用请求头 `X-Anonymous-Id` 区分（前端存在 localStorage）。
这不是登录系统，只是 Demo 级别的“同一浏览器算同一个人”。
"""
from __future__ import annotations

import logging
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent
import agent_multi
import rag
import usage
from db import repo
from db.base import get_session
from db.models import Conversation
from guards import _require_token, _slot

logger = logging.getLogger("mingli.api.conversations")

router = APIRouter(
    prefix="/v1",
    tags=["conversations"],
    dependencies=[Depends(_require_token)],
)


# ---------- 请求 / 响应模型 ----------

class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationOut(BaseModel):
    id: str
    title: str
    summary: str | None = None
    status: str
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut] = Field(default_factory=list)


class ConversationChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    mode: Literal["rag", "agent", "multi"] = "rag"
    top_k: int = Field(5, ge=1, le=10)
    max_steps: int = Field(6, ge=1, le=10)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question 不能为空")
        return value


class ConversationChatResponse(BaseModel):
    """和旧 `/chat` 的字段保持一致，额外返回会话和消息 ID。"""

    model_config = ConfigDict(extra="allow")

    conversation_id: str
    trace_id: str
    mode: Literal["rag", "agent", "multi"]
    question: str
    answer: str = ""
    elapsed_ms: float
    can_answer: bool | None = None
    citations: list[Any] = Field(default_factory=list)
    citations_chunk_ids: list[str] = Field(default_factory=list)
    invalid_citations: list[Any] = Field(default_factory=list)
    invalid_output: bool = False
    refusal_reason: str | None = None
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    rewritten_question: str | None = None
    history_turns: int = 0
    llm_calls: int = 0
    usage: dict[str, Any] | None = None
    user_message_id: int
    assistant_message_id: int


# ---------- 依赖 ----------

def current_anonymous_id(
    x_anonymous_id: str | None = Header(default=None, alias="X-Anonymous-Id"),
) -> str:
    return (x_anonymous_id or "demo").strip()[:64] or "demo"


def _conversation_out(conv: Conversation, message_count: int = 0) -> dict[str, Any]:
    return {
        "id": conv.id,
        "title": conv.title,
        "summary": conv.summary,
        "status": conv.status,
        "message_count": message_count,
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
    }


def _get_owned(session: Session, conversation_id: str, user_id: int) -> Conversation:
    conv = repo.get_conversation(session, conversation_id, user_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conv


# ---------- 会话增删查 ----------

@router.post("/conversations", response_model=ConversationOut, status_code=201)
def create_conversation(
    req: ConversationCreate | None = None,
    anonymous_id: str = Depends(current_anonymous_id),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user = repo.get_or_create_user(session, anonymous_id)
    conv = repo.create_conversation(session, user, req.title if req else None)
    return _conversation_out(conv, 0)


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    anonymous_id: str = Depends(current_anonymous_id),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    user = repo.get_or_create_user(session, anonymous_id)
    rows = repo.list_conversations(session, user.id)
    return [_conversation_out(conv, count) for conv, count in rows]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailOut)
def get_conversation(
    conversation_id: str,
    anonymous_id: str = Depends(current_anonymous_id),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user = repo.get_or_create_user(session, anonymous_id)
    conv = _get_owned(session, conversation_id, user.id)
    out = _conversation_out(conv, len(conv.messages))
    out["messages"] = [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at,
        }
        for m in conv.messages
    ]
    return out


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    anonymous_id: str = Depends(current_anonymous_id),
    session: Session = Depends(get_session),
) -> Response:
    user = repo.get_or_create_user(session, anonymous_id)
    conv = _get_owned(session, conversation_id, user.id)
    repo.delete_conversation(session, conv)
    return Response(status_code=204)


# ---------- 带记忆的对话 ----------

@router.post(
    "/conversations/{conversation_id}/chat",
    response_model=ConversationChatResponse,
)
def chat_in_conversation(
    conversation_id: str,
    req: ConversationChatRequest,
    x_deepseek_key: str | None = Header(default=None),
    anonymous_id: str = Depends(current_anonymous_id),
    session: Session = Depends(get_session),
    __: None = Depends(_slot),
) -> dict[str, Any]:
    user = repo.get_or_create_user(session, anonymous_id)
    conv = _get_owned(session, conversation_id, user.id)

    # 先读历史，再把本轮问题写进去；否则本轮问题会重复出现在 history 里。
    history = repo.recent_history(session, conv.id)
    key = (x_deepseek_key or "").strip() or None
    started = time.perf_counter()
    trace_id = uuid.uuid4().hex
    usage.reset()

    try:
        if req.mode == "rag":
            result = rag.answer(
                req.question, top_k=req.top_k, api_key=key, history=history
            )
        elif req.mode == "agent":
            result = agent.agent_answer(
                req.question, max_steps=req.max_steps, api_key=key, history=history
            )
        else:
            result = agent_multi.agent_answer(
                req.question, max_steps=req.max_steps, api_key=key, history=history
            )
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        logger.warning("upstream failed trace_id=%s status=%s", trace_id, status)
        raise HTTPException(status_code=502, detail="上游模型调用失败（%s）" % status) from exc
    except RuntimeError as exc:
        logger.warning("configuration error trace_id=%s: %s", trace_id, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("chat failed trace_id=%s mode=%s", trace_id, req.mode)
        raise HTTPException(status_code=500, detail="生成失败") from exc

    elapsed_ms = (time.perf_counter() - started) * 1000
    answer_text = str(result.get("answer") or "")

    # 用户消息和助手消息在同一个事务里提交，避免只存了半轮。
    repo.rename_if_untitled(session, conv, req.question)
    user_msg = repo.add_message(
        session, conv, "user", req.question, commit=False
    )
    assistant_msg = repo.add_message(
        session, conv, "assistant", answer_text, commit=False
    )
    session.commit()

    out = dict(result)
    # 模型偶尔把 answer / citations 返回成 null，统一成响应模型能接受的类型。
    out["answer"] = answer_text
    for name in ("citations", "citations_chunk_ids", "invalid_citations",
                 "retrieved_chunk_ids"):
        out[name] = out.get(name) or []
    out.update({
        "conversation_id": conv.id,
        "trace_id": trace_id,
        "mode": req.mode,
        "question": req.question,
        "elapsed_ms": round(elapsed_ms, 1),
        "usage": usage.snapshot(),
        "user_message_id": user_msg.id,
        "assistant_message_id": assistant_msg.id,
    })
    logger.info(
        "conversation chat conv=%s mode=%s elapsed_ms=%.0f llm_calls=%s trace_id=%s",
        conv.id, req.mode, elapsed_ms, out.get("llm_calls"), trace_id,
    )
    return out
