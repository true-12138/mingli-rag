# -*- coding: utf-8 -*-
"""业务数据库的连接与会话。

设计原则：
- 开发/测试默认用 SQLite（`data/app.sqlite3`），部署时用 `MINGLI_DB_URL`
  换成 Postgres 即可，业务代码不用改；
- 所有表继承同一个 `Base`，Alembic 靠它生成迁移；
- `get_session()` 是给 FastAPI 用的依赖，每个请求一个 session。

为什么不用现有 `platform_db.py`：
那是「数据/评测中台」的账本，和业务数据（用户、会话、运行）生命周期不同。
拆成两个库，评测库可以随时删掉重建，不会误伤用户数据。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


def _default_db_url() -> str:
    """默认把业务库放在 <repo>/data/app.sqlite3。"""
    root = Path(__file__).resolve().parents[2]  # src/db/base.py -> 仓库根目录
    return "sqlite:///" + str(root / "data" / "app.sqlite3").replace("\\", "/")


def db_url() -> str:
    """环境变量优先；没配就用本地 SQLite。"""
    return os.environ.get("MINGLI_DB_URL") or _default_db_url()


def make_engine(url: str | None = None) -> Engine:
    """按 URL 建 engine。

    SQLite 的四个特殊处理：
    1. `check_same_thread=False`：FastAPI 的同步接口跑在线程池里，连接会跨线程；
    2. `PRAGMA foreign_keys=ON`：SQLite 默认不执行外键，必须每个连接手动打开；
    3. `PRAGMA journal_mode=WAL`：读不阻塞写，多个用户同时问时不会因为一次写入
       把所有人的会话读取都卡住；
    4. `PRAGMA busy_timeout=5000`：第二个写者排队 5 秒，而不是立刻抛
       `database is locked`。它不把 SQLite 变成 Postgres，但能把「4 路并发写」
       从偶发 500 变成可预期。
    内存库用 StaticPool，保证同一份内存库在多次连接之间共享。
    """
    url = url or db_url()
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool

    engine = create_engine(url, future=True, **kwargs)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _configure_sqlite(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # WAL 对内存库会返回 "memory"，不报错；对文件库是持久设置。
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


class Base(DeclarativeBase):
    """所有业务表的基类。Alembic 的 target_metadata 指向它。"""


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个 session，请求结束自动关闭。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
