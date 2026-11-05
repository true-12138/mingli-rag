# -*- coding: utf-8 -*-
"""业务数据库包：连接、模型、会话。

    from db import Base, SessionLocal, User, Conversation

Alembic 通过 `db.base.Base.metadata` 发现所有表，所以新增模型后
一定要在这里导入，否则迁移脚本看不到它。
"""
from .base import Base, SessionLocal, db_url, engine, get_session, make_engine
from .models import (
    Conversation,
    Feedback,
    Message,
    QuotaLedger,
    QuotaUsage,
    Run,
    ToolCall,
    User,
)

__all__ = [
    "Base",
    "SessionLocal",
    "Conversation",
    "Feedback",
    "Message",
    "QuotaLedger",
    "QuotaUsage",
    "Run",
    "ToolCall",
    "User",
    "db_url",
    "engine",
    "get_session",
    "make_engine",
]
