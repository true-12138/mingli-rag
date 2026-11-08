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


def normalize_db_url(url: str) -> str:
    """`postgres://` / `postgresql://` 统一走 psycopg 3 驱动。

    不依赖 psycopg2：psycopg 3 的 binary wheel 更好装，SQLAlchemy 2.x 原生支持。
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def db_url() -> str:
    """环境变量优先；没配就用本地 SQLite。"""
    return normalize_db_url(os.environ.get("MINGLI_DB_URL") or _default_db_url())


def make_engine(url: str | None = None) -> Engine:
    """按 URL 建 engine。

    SQLite 有两个特殊处理：
    1. `check_same_thread=False`：FastAPI 的同步接口跑在线程池里，连接会跨线程；
    2. `PRAGMA foreign_keys=ON`：SQLite 默认不执行外键，必须每个连接手动打开。
    内存库用 StaticPool，保证同一份内存库在多次连接之间共享。

    Postgres 用有界连接池：默认 20 个常驻 + 10 个溢出，够 20 并发回答
    （每个请求一个连接，写 runs 很快归还）。`pre_ping` 处理数据库重启后的死连接。
    """
    url = normalize_db_url(url or db_url())
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
    elif url.startswith("postgresql"):
        kwargs.update(
            pool_size=int(os.environ.get("MINGLI_DB_POOL_SIZE", "20")),
            max_overflow=int(os.environ.get("MINGLI_DB_MAX_OVERFLOW", "10")),
            pool_timeout=float(os.environ.get("MINGLI_DB_POOL_TIMEOUT", "10")),
            pool_recycle=int(os.environ.get("MINGLI_DB_POOL_RECYCLE", "1800")),
            pool_pre_ping=True,
        )

    engine = create_engine(url, future=True, **kwargs)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
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


def db_info() -> dict:
    """给 `/health` 用的连接信息；不打 URL，避免把密码带进响应或日志。"""
    from sqlalchemy.engine import make_url

    url = make_url(engine.url)
    size = getattr(engine.pool, "size", None)
    return {
        "dialect": url.get_backend_name(),
        "driver": url.get_driver_name(),
        "pool": type(engine.pool).__name__,
        "pool_size": size() if callable(size) else size,
    }
