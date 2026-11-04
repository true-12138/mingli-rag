# -*- coding: utf-8 -*-
"""Alembic 运行时入口。

两件事：
1. 把 `src/` 加进 sys.path，这样能 import `db.base` / `db.models`；
2. 数据库地址从 `MINGLI_DB_URL` 读，和业务代码保持同一个来源。
"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from db.base import Base, db_url  # noqa: E402
import db.models  # noqa: E402,F401  # 让 Base.metadata 注册所有表

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 业务代码和迁移脚本用同一个数据库地址。
# ConfigParser 会把 % 当插值符号，Postgres 密码里带 % 时要转义。
config.set_main_option("sqlalchemy.url", db_url().replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """不连数据库，只生成 SQL（CI 或审查时用）。"""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite 不支持大部分 ALTER TABLE，batch 模式会重建表来模拟
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
