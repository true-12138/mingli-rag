# -*- coding: utf-8 -*-
"""Agent 工具层。

这里只有纯函数：不调用大模型，也不维护对话状态。
agent 循环（src/agent.py）负责决定调哪个工具、传什么参数。

统一返回格式，方便 trace 落盘和单测::

    {"ok": True, "tool": 名称, "args": 入参, "result": ...}
    {"ok": False, "tool": 名称, "args": 入参, "error": 原因}
"""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus
from fortune.astro import natal_chart
from fortune.bazi import paipan as _paipan_bazi
from fortune.tarot import draw as _draw_tarot
from retrieval import bm25, chunks, embeds, encode_query, rrf_k, tokenize

logger = logging.getLogger("mingli.tools")

BOOK_FIELDS = ("book", "volume", "chapter")

# chunk_id（1 起）→ 语料行号（0 起）。两者现在一一对应，但不写死这个假设。
_ID2IDX = {c["chunk_id"]: i for i, c in enumerate(chunks)}


def _title(meta):
    parts = [str(meta.get(k) or "").strip() for k in BOOK_FIELDS]
    return "《{}》".format("·".join(p for p in parts if p))


def _payload(c, score):
    return {
        "chunk_id": c["chunk_id"],
        "title": _title(c["meta"]),
        "book": c["meta"].get("book") or "",
        "volume": c["meta"].get("volume") or "",
        "chapter": c["meta"].get("chapter") or "",
        "text": c["chunk_text"],
        "score": round(float(score), 6),
    }


def _rows_for_book(book):
    """按书名模糊匹配语料行号；book 为空返回 None 表示不过滤。"""
    if not book:
        return None
    needle = str(book).strip().strip("《》")
    return [i for i, c in enumerate(chunks) if needle in (c["meta"].get("book") or "")]


def _topk(scores, mask_rows, k):
    """取分数最高的 k 个行号；给了 mask_rows 就只在其中取。"""
    if mask_rows is not None:
        keep = np.asarray(mask_rows, dtype=np.int64)
        if keep.size == 0:
            return []
        sub = scores[keep]
        order = np.argsort(sub)[::-1][:k]
        return [int(keep[o]) for o in order]
    return [int(i) for i in np.argsort(scores)[::-1][:k]]


def search_classics(query, k=5, book=None, mode="rrf"):
    """在全库或指定书内检索。

    mode: dense（语义）/ bm25（字面）/ rrf（两路融合，默认）
    book: 书名片段，例如 "三命通会"；不传则全库检索
    """
    args = {"query": query, "k": k, "book": book, "mode": mode}
    if not query or not str(query).strip():
        return {"ok": False, "tool": "search_classics", "args": args, "error": "query 不能为空"}
    if mode not in ("dense", "bm25", "rrf"):
        return {"ok": False, "tool": "search_classics", "args": args, "error": "mode 只能是 dense / bm25 / rrf"}

    try:
        k = max(1, min(int(k), 20))
    except (TypeError, ValueError):
        return {"ok": False, "tool": "search_classics", "args": args, "error": "k 必须是整数"}

    rows = _rows_for_book(book)
    if rows is not None and not rows:
        return {"ok": False, "tool": "search_classics", "args": args, "error": "书库里没有匹配「%s」的书，先调 list_books 看书名" % book}

    cand = max(k * 4, 20)

    q_emb = encode_query(query)
    sims = embeds @ q_emb
    d_rows = _topk(sims, rows, cand)

    scores = bm25.get_scores(tokenize(query))
    b_rows = _topk(np.asarray(scores, dtype=np.float32), rows, cand)

    if mode == "dense":
        picked = [(i, float(sims[i])) for i in d_rows[:k]]
    elif mode == "bm25":
        picked = [(i, float(scores[i])) for i in b_rows[:k]]
    else:
        fused = {}
        for rank, i in enumerate(d_rows, start=1):
            fused[i] = fused.get(i, 0.0) + 1.0 / (rank + rrf_k)
        for rank, i in enumerate(b_rows, start=1):
            fused[i] = fused.get(i, 0.0) + 1.0 / (rank + rrf_k)
        ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:k]
        picked = [(i, s) for i, s in ranked]

    hits = [_payload(chunks[i], s) for i, s in picked]
    return {
        "ok": True,
        "tool": "search_classics",
        "args": args,
        "result": {"hits": hits, "n": len(hits)},
    }


def fetch_chunk(chunk_id, with_neighbors=False):
    """按 chunk_id 取完整原文。with_neighbors=True 时附带前后各一条的摘要。"""
    args = {"chunk_id": chunk_id, "with_neighbors": with_neighbors}
    try:
        cid = int(chunk_id)
    except (TypeError, ValueError):
        return {"ok": False, "tool": "fetch_chunk", "args": args, "error": "chunk_id 必须是整数"}
    idx = _ID2IDX.get(cid)
    if idx is None:
        return {"ok": False, "tool": "fetch_chunk", "args": args, "error": "chunk_id %s 不存在，取值范围 1..%d" % (cid, len(chunks))}

    out = _payload(chunks[idx], 0.0)
    if with_neighbors:
        for name, j in (("prev", idx - 1), ("next", idx + 1)):
            if 0 <= j < len(chunks):
                nb = chunks[j]
                out[name] = {
                    "chunk_id": nb["chunk_id"],
                    "title": _title(nb["meta"]),
                    "head": nb["chunk_text"][:60],
                }
            else:
                out[name] = None
    return {"ok": True, "tool": "fetch_chunk", "args": args, "result": out}


def list_books():
    """列出库里所有书及 chunk 数，让模型知道有什么可查。"""
    agg = {}
    for c in chunks:
        b = c["meta"].get("book") or "(未命名)"
        item = agg.setdefault(b, {"book": b, "chunks": 0, "groups": set()})
        item["chunks"] += 1
        src = c["meta"].get("index_source")
        if src:
            item["groups"].add(src)
    books = [
        {"book": v["book"], "chunks": v["chunks"], "groups": sorted(v["groups"])}
        for v in agg.values()
    ]
    books.sort(key=lambda x: (-x["chunks"], x["book"]))
    return {
        "ok": True,
        "tool": "list_books",
        "args": {},
        "result": {"n_books": len(books), "books": books},
    }


_TERM_CACHE = None


def _load_terms():
    """把 data/terminology 下的 jsonl / txt 读成 (term, text, file) 三元组。"""
    global _TERM_CACHE
    if _TERM_CACHE is not None:
        return _TERM_CACHE
    root = corpus.data_dir() / "terminology"
    rows = []
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            try:
                if path.suffix == ".jsonl":
                    with open(path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            obj = json.loads(line)
                            term = str(obj.get("term") or "").strip()
                            text = str(obj.get("text") or "").strip()
                            if term:
                                rows.append((term, text, path.name))
                elif path.suffix == ".txt":
                    # 术语表是「天乙贵人：Heavenly Nobleman；...」这种一行一条，冒号前就是词条
                    with open(path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith("#"):
                                continue
                            term = re.split(r"[：:]", line, 1)[0].strip() or line[:40]
                            rows.append((term, line, path.name))
            except (OSError, ValueError):
                continue
    _TERM_CACHE = rows
    return rows


def search_terms(term, limit=5):
    """在术语表里查词条，补 BM25 在生僻术语上的短板。"""
    args = {"term": term, "limit": limit}
    if not term or not str(term).strip():
        return {"ok": False, "tool": "search_terms", "args": args, "error": "term 不能为空"}
    needle = str(term).strip()
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        return {"ok": False, "tool": "search_terms", "args": args, "error": "limit 必须是整数"}

    rows = _load_terms()
    hits = []
    for t, text, src in rows:
        if needle in t or needle in text:
            hits.append({"term": t, "text": text, "source": src})
            if len(hits) >= limit:
                break
    return {
        "ok": True,
        "tool": "search_terms",
        "args": args,
        "result": {"hits": hits, "n": len(hits)},
    }


def draw_bazi(year, month, day, hour=0, minute=0, gender="male"):
    """排八字盘。纯历法计算，同样的输入永远同一个盘。"""
    args = {"year": year, "month": month, "day": day,
            "hour": hour, "minute": minute, "gender": gender}
    try:
        chart = _paipan_bazi(year, month, day, hour, minute, gender)
    except ValueError as exc:
        return {"ok": False, "tool": "draw_bazi", "args": args, "error": str(exc)}
    return {"ok": True, "tool": "draw_bazi", "args": args, "result": chart}


def draw_astro(year, month, day, hour=0, minute=0,
               tz=8.0, lat=39.90, lon=116.40, city="北京"):
    """排西方本命盘（整宫制）。行星位置是地心视黄经。"""
    args = {"year": year, "month": month, "day": day, "hour": hour, "minute": minute,
            "tz": tz, "lat": lat, "lon": lon, "city": city}
    try:
        chart = natal_chart(year, month, day, hour, minute, tz, lat, lon, city)
    except ValueError as exc:
        return {"ok": False, "tool": "draw_astro", "args": args, "error": str(exc)}
    return {"ok": True, "tool": "draw_astro", "args": args, "result": chart}


def draw_tarot(n=3, seed=None, spread=None):
    """抽塔罗牌。seed 固定时结果可复现，用于测试。"""
    args = {"n": n, "seed": seed, "spread": spread}
    try:
        result = _draw_tarot(n, seed, spread)
    except ValueError as exc:
        return {"ok": False, "tool": "draw_tarot", "args": args, "error": str(exc)}
    return {"ok": True, "tool": "draw_tarot", "args": args, "result": result}


TOOLS = {
    "search_classics": search_classics,
    "fetch_chunk": fetch_chunk,
    "list_books": list_books,
    "search_terms": search_terms,
    "draw_bazi": draw_bazi,
    "draw_astro": draw_astro,
    "draw_tarot": draw_tarot,
}


# 外部 MCP server 挂载的工具。没配 `mcp_servers.json` 时这里永远是 None，
# 只有一次文件存在性检查的代价，不会起进程、不会联网。
_EXTERNAL = None
_EXTERNAL_LOCK = threading.Lock()
_NO_EXTERNAL = object()


def external_registry():
    """返回已配置的 MCP 注册表；没配置返回 None。首次调用时才建连。"""
    global _EXTERNAL
    if _EXTERNAL is not None:
        return None if _EXTERNAL is _NO_EXTERNAL else _EXTERNAL
    with _EXTERNAL_LOCK:
        if _EXTERNAL is None:
            try:
                import mcp_client
                reg = mcp_client.registry()
                _EXTERNAL = reg if reg.configs else _NO_EXTERNAL
            except Exception:  # noqa: BLE001 - 挂载失败不能拖垮内置工具
                logger.warning("MCP client 初始化失败，外部工具不可用", exc_info=True)
                _EXTERNAL = _NO_EXTERNAL
    return None if _EXTERNAL is _NO_EXTERNAL else _EXTERNAL




def permission(name):
    """这次调用属于 read 还是 side_effect，是否放行。见 `tool_policy.py`。"""
    try:
        from tool_policy import evaluate
        return evaluate(name, external_registry())
    except Exception:  # noqa: BLE001 - 权限层自己坏了不能把工具循环拖死
        logger.warning("工具权限检查失败，按 read 放行：%s", name, exc_info=True)
        return {"allowed": True, "tier": "read", "reason": None}


def call(name, **kwargs):
    """按名字调工具。未知工具名或参数不合法都返回 ok=False，而不是抛异常。

    agent 可能拼错工具名，也可能给工具塞不存在的参数（实测 draw_astro 被传过 gender）。
    这两种情况都应该变成一条 observation 让模型自己纠正，而不是让整个循环崩掉。
    """
    fn = TOOLS.get(name)
    if fn is None:
        reg = external_registry()
        if reg is not None and reg.has(name):
            return reg.call(name, kwargs)
        return {
            "ok": False,
            "tool": name,
            "args": kwargs,
            "error": "未知工具，可用：%s" % ", ".join(
                sorted(list(TOOLS) + ([t["function"]["name"]
                                       for t in reg.schemas()] if reg else []))
            ),
        }
    try:
        return fn(**kwargs)
    except TypeError as exc:
        import inspect
        params = list(inspect.signature(fn).parameters)
        return {
            "ok": False,
            "tool": name,
            "args": kwargs,
            "error": "参数不合法：{}。{} 接受的参数：{}".format(exc, name, ", ".join(params)),
        }


if __name__ == "__main__":
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    for r in (
        search_classics("正官和七杀有什么区别", k=3),
        fetch_chunk(2831),
        list_books(),
        search_terms("天乙贵人", limit=3),
        call("no_such_tool"),
    ):
        print(json.dumps(r, ensure_ascii=False)[:400])
