# -*- coding: utf-8 -*-
"""数据中台 / 评测中台共用的 SQLite 连接与建表。

刻意不引入 Postgres / 消息队列：这个项目的规模（8,681 段、几十次评测）
用单文件 SQLite 足够，部署到创空间也不用多起一个服务。
真正要保留的是「版本、血缘、质量门、可复现的 run」这四件事，而不是中间件数量。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from corpus import data_dir


def db_path() -> Path:
    """默认 data/platform.sqlite3；部署时可用 MINGLI_PLATFORM_DB 指到持久化目录。"""
    import os

    return Path(os.environ.get("MINGLI_PLATFORM_DB") or (data_dir() / "platform.sqlite3"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    path TEXT,
    books INTEGER,
    chunks INTEGER,
    chars INTEGER,
    meta_json TEXT,
    created_at TEXT NOT NULL,
    scanned_at TEXT NOT NULL,
    UNIQUE(name, version)
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT,
    bytes INTEGER,
    meta_json TEXT,
    UNIQUE(dataset_id, kind, path)
);

CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    check_name TEXT NOT NULL,
    status TEXT NOT NULL,
    value TEXT,
    detail TEXT,
    checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source TEXT UNIQUE,
    suite TEXT NOT NULL,
    backend TEXT,
    dataset_version TEXT,
    config_json TEXT,
    metrics_json TEXT,
    status TEXT NOT NULL DEFAULT 'done',
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    case_id TEXT,
    question TEXT,
    answerable INTEGER,
    category TEXT,
    output TEXT,
    can_answer INTEGER,
    citations_json TEXT,
    recall REAL,
    mrr REAL,
    passed INTEGER,
    latency_ms REAL,
    detail_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_eval_cases_run ON eval_cases(run_id);
CREATE INDEX IF NOT EXISTS idx_checks_dataset ON checks(dataset_id);
"""


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def ensure_schema() -> Path:
    with connect():
        pass
    return db_path()
