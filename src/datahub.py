# -*- coding: utf-8 -*-
"""数据中台的 MVP：扫描语料 / chunk / embedding，登记版本、血缘和质量门。

这里不做「上传数据集」那种平台功能，先解决这个项目真实存在的三个风险：
1. chunks 和 embeddings 顺序不一致（症状是检索看起来正常、分数悄悄变差）；
2. 改了语料但评测还引用旧基线（版本对不上）；
3. 空 chunk、重复 chunk、缺元数据在入库时没被发现。

一次扫描产出：
- dataset：内容指纹 + 书数 / chunk 数 / 字数；
- assets：每个源文件的 sha256 和大小，构成最朴素的版本血缘；
- checks：可机器判的质量门，pass / warn / fail。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

import corpus
from platform_db import connect

DATASET_NAME = "mingli-classics"
EMBED_DIM = 1024


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _git_commit():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _check(name, status, value, detail=""):
    return {"check_name": name, "status": status, "value": str(value), "detail": detail}


def scan(data_dir=None) -> dict:
    """只读扫描，不写库；返回可直接展示的 dict。"""
    dd = Path(data_dir) if data_dir else corpus.data_dir()
    chunks = corpus.load_chunks(dd)

    h = hashlib.sha256()
    books = Counter()
    chars = 0
    empty = 0
    short = 0
    missing_source = 0
    missing_lines = 0
    texts = Counter()
    ids = Counter()

    for c in chunks:
        meta = c.get("meta") or {}
        text = (c.get("chunk_text") or "").strip()
        source = c.get("sourcefile") or meta.get("sourcefile") or ""
        book = meta.get("book") or (source.split("/")[0] if source else "（未知）")
        books[book] += 1
        chars += len(text)
        ids[c["chunk_id"]] += 1
        if not text:
            empty += 1
        elif len(text) < 20:
            short += 1
        if not source:
            missing_source += 1
        if meta.get("line_start") is None or meta.get("line_end") is None:
            missing_lines += 1
        if text:
            texts[text] += 1
        h.update("{}|{}|{}|{}|{}\n".format(
            c["chunk_id"], source, meta.get("line_start"), meta.get("line_end"), text,
        ).encode("utf-8"))
    fingerprint = h.hexdigest()
    version = "ds-" + fingerprint[:12]

    emb_path = dd / "embeddings.npy"
    emb_meta = {}
    emb = None
    if emb_path.exists():
        emb = np.load(emb_path, mmap_mode="r")
        emb_meta = {
            "shape": list(emb.shape),
            "dtype": str(emb.dtype),
            "bytes": emb_path.stat().st_size,
        }
        finite = bool(np.isfinite(np.asarray(emb[: min(len(emb), 256)])).all())
        # 全量 isfinite 在 8k×1024 上是 35MB 扫描，可接受；但某些部署内存紧张，
        # 先抽样 256 行，行数维度仍全量校验。
        if len(emb) <= 20000:
            finite = bool(np.isfinite(emb).all())
    else:
        finite = False

    checks = [
        _check("chunk_count", "pass" if chunks else "fail", len(chunks),
               "语料非空" if chunks else "没有读到任何 chunk"),
        _check("unique_chunk_ids", "pass" if all(v == 1 for v in ids.values()) else "fail",
               sum(1 for v in ids.values() if v > 1), "重复 chunk_id 数量"),
        _check("empty_text", "pass" if empty == 0 else "fail", empty, "空正文 chunk 数量"),
        _check("missing_sourcefile", "pass" if missing_source == 0 else "warn",
               missing_source, "缺少 sourcefile 的 chunk 数量"),
        _check("missing_line_range", "pass" if missing_lines == 0 else "warn",
               missing_lines, "缺少 line_start/line_end 的 chunk 数量"),
        _check("short_chunks", "pass" if short / max(len(chunks), 1) < 0.01 else "warn",
               short, "正文少于 20 字的 chunk 数量（阈值 1%）"),
    ]

    dup_text = sum(v - 1 for v in texts.values() if v > 1)
    dup_ratio = dup_text / max(len(chunks), 1)
    checks.append(_check(
        "duplicate_text",
        "pass" if dup_ratio < 0.01 else "warn",
        dup_text,
        "完全重复正文的多余条数（阈值 1%）：{:.2%}".format(dup_ratio),
    ))

    checks.append(_check(
        "book_coverage", "pass" if len(books) >= 40 else "warn", len(books),
        "涉及书目数量（阈值 40）",
    ))

    if emb is None:
        checks.append(_check("embedding_file", "fail", 0, "缺少 embeddings.npy"))
        checks.append(_check("embedding_alignment", "fail", 0, "没有 embedding 无法校验顺序"))
        checks.append(_check("embedding_dim", "fail", 0, "没有 embedding 无法校验维度"))
        checks.append(_check("embedding_finite", "fail", 0, "没有 embedding 无法校验数值"))
    else:
        rows, dim = emb.shape[0], (emb.shape[1] if emb.ndim == 2 else 0)
        checks.append(_check("embedding_file", "pass", 1, "embeddings.npy 存在"))
        checks.append(_check(
            "embedding_alignment", "pass" if rows == len(chunks) else "fail",
            "{} / {}".format(rows, len(chunks)),
            "embedding 行数 / chunk 数必须一致，否则 chunk_id 会错位",
        ))
        checks.append(_check(
            "embedding_dim", "pass" if dim == EMBED_DIM else "fail", dim,
            "BGE-M3 期望 {} 维".format(EMBED_DIM),
        ))
        checks.append(_check(
            "embedding_finite", "pass" if finite else "fail", str(finite),
            "是否含 NaN / Inf",
        ))

    assets = []
    for rel, kind in (
        ("chunks/punct.jsonl", "chunks"),
        ("chunks/unpunct.jsonl", "chunks"),
        ("embeddings.npy", "embeddings"),
    ):
        path = dd / rel
        if path.exists():
            assets.append({
                "kind": kind, "path": rel, "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            })
    term_dir = dd / "terminology"
    if term_dir.exists():
        for path in sorted(term_dir.glob("*.jsonl")):
            assets.append({
                "kind": "terminology", "path": str(path.relative_to(dd)),
                "sha256": _sha256(path), "bytes": path.stat().st_size,
            })

    meta = {
        "fingerprint_rule": "sha256(chunk_id|sourcefile|line_start|line_end|text)",
        "git_commit": _git_commit(),
        "embedding": emb_meta,
        "books": dict(books.most_common()),
        "dup_text": dup_text,
        "empty_text": empty,
    }
    return {
        "name": DATASET_NAME,
        "version": version,
        "fingerprint": fingerprint,
        "path": str(dd),
        "books": len(books),
        "chunks": len(chunks),
        "chars": chars,
        "meta": meta,
        "assets": assets,
        "checks": checks,
    }


def store(result: dict) -> int:
    """把一次扫描写进库；同版本重复扫描只刷新时间与 checks，不新增版本。"""
    now = _now()
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM datasets WHERE name=? AND version=?",
            (result["name"], result["version"]),
        ).fetchone()
        if row:
            dataset_id = row["id"]
            conn.execute(
                "UPDATE datasets SET scanned_at=?, meta_json=? WHERE id=?",
                (now, json.dumps(result["meta"], ensure_ascii=False), dataset_id),
            )
            conn.execute("DELETE FROM checks WHERE dataset_id=?", (dataset_id,))
        else:
            cur = conn.execute(
                "INSERT INTO datasets(name, version, fingerprint, path, books, chunks, chars,"
                " meta_json, created_at, scanned_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (result["name"], result["version"], result["fingerprint"], result["path"],
                 result["books"], result["chunks"], result["chars"],
                 json.dumps(result["meta"], ensure_ascii=False), now, now),
            )
            dataset_id = cur.lastrowid

        for a in result["assets"]:
            conn.execute(
                "INSERT INTO assets(dataset_id, kind, path, sha256, bytes, meta_json)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(dataset_id, kind, path) DO UPDATE SET"
                " sha256=excluded.sha256, bytes=excluded.bytes",
                (dataset_id, a["kind"], a["path"], a["sha256"], a["bytes"], None),
            )
        for c in result["checks"]:
            conn.execute(
                "INSERT INTO checks(dataset_id, check_name, status, value, detail, checked_at)"
                " VALUES (?,?,?,?,?,?)",
                (dataset_id, c["check_name"], c["status"], c["value"], c["detail"], now),
            )
        conn.commit()
        return dataset_id


def scan_and_store(data_dir=None) -> dict:
    result = scan(data_dir)
    result["id"] = store(result)
    return result


def latest(conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        row = conn.execute("SELECT * FROM datasets ORDER BY scanned_at DESC, id DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        if own:
            conn.close()


def checks_for(dataset_id, conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM checks WHERE dataset_id=? ORDER BY id", (dataset_id,)
        )]
    finally:
        if own:
            conn.close()


def assets_for(dataset_id, conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM assets WHERE dataset_id=? ORDER BY kind, path", (dataset_id,)
        )]
    finally:
        if own:
            conn.close()


def history(limit=20, conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, version, books, chunks, chars, created_at, scanned_at"
            " FROM datasets ORDER BY id DESC LIMIT ?", (limit,)
        )]
    finally:
        if own:
            conn.close()


if __name__ == "__main__":
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    r = scan_and_store()
    print("dataset #%s %s" % (r["id"], r["version"]))
    print("%d 本书 / %d 段 / %d 字 / %d 个资产" % (
        r["books"], r["chunks"], r["chars"], len(r["assets"])))
    for c in r["checks"]:
        print("  [%-4s] %-22s %-10s %s" % (c["status"], c["check_name"], c["value"], c["detail"]))
