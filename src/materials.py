# -*- coding: utf-8 -*-
"""素材收藏的展示字段与 Markdown 导出。

收藏表里只存 `chunk_id` 和用户笔记，原文每次按 id 回语料取：
语料是唯一原文来源，导出和引用永远看到同一段字。
代价是语料重编编号后旧收藏会指空——列表里直接略过那一行，
不会拿着错位的 id 去显示别的书（这正是无标点题库踩过的坑）。
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import corpus

_INDEX: dict[int, dict[str, Any]] | None = None
_LOCK = threading.Lock()

BEIJING = timezone(timedelta(hours=8))

# 单条笔记的上限；太长说明该写文章，不该塞进素材夹。
MAX_NOTE_CHARS = 2000


def chunk_index() -> dict[int, dict[str, Any]]:
    """chunk_id → 语料行。只建一次；语料在进程启动后不变。"""
    global _INDEX
    if _INDEX is None:
        with _LOCK:
            if _INDEX is None:
                _INDEX = {int(c["chunk_id"]): c for c in corpus.load_chunks()}
    return _INDEX


def chunk_of(chunk_id: int) -> dict[str, Any] | None:
    return chunk_index().get(int(chunk_id))


def favorite_out(favorite: Any) -> dict[str, Any] | None:
    """把一行收藏补成前端要的完整素材；原文不在了返回 None。"""
    chunk = chunk_of(favorite.chunk_id)
    if chunk is None:
        return None
    meta = chunk.get("meta") or {}
    parts = [str(meta.get(k) or "").strip() for k in ("book", "volume", "chapter")]
    return {
        "id": int(favorite.id),
        "chunk_id": int(favorite.chunk_id),
        "book": str(meta.get("book") or ""),
        "volume": str(meta.get("volume") or ""),
        "chapter": str(meta.get("chapter") or ""),
        "title": "《{}》".format("·".join(p for p in parts if p))
        if any(parts) else "《未标书名》",
        "text": str(chunk.get("chunk_text") or "").strip(),
        "line_start": meta.get("line_start"),
        "line_end": meta.get("line_end"),
        "sourcefile": str(meta.get("sourcefile") or ""),
        "note": favorite.note,
        "created_at": favorite.created_at,
    }


def export_filename(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(BEIJING)).astimezone(BEIJING).strftime("%Y%m%d")
    return "问古素材-{}.md".format(stamp)


def content_disposition(now: datetime | None = None) -> str:
    """中文文件名走 RFC 5987；ASCII 回退名给不认 filename* 的客户端。"""
    stamp = (now or datetime.now(BEIJING)).astimezone(BEIJING).strftime("%Y%m%d")
    return 'attachment; filename="wengu-materials-{}.md"; filename*=UTF-8\'\'{}'.format(
        stamp, quote(export_filename(now))
    )


def render_markdown(items: list[dict[str, Any]], now: datetime | None = None) -> str:
    """把素材按收藏顺序导出成一份 Markdown。

    原文用引用块，笔记单独一行——这样贴进稿子后，哪些是古人的话、
    哪些是自己的批注一眼能分开。
    """
    stamp = (now or datetime.now(BEIJING)).astimezone(BEIJING)
    lines = [
        "# 问古 · 古籍素材",
        "",
        "导出时间：{}｜共 {} 条".format(stamp.strftime("%Y-%m-%d %H:%M"), len(items)),
        "",
        "> 原文来自语料库，引用时以原文为准；笔记是整理时的批注。",
        "",
    ]
    for i, item in enumerate(items, 1):
        title = item.get("title") or "《未标书名》"
        meta = " · ".join(
            str(x) for x in (item.get("volume"), item.get("chapter")) if x
        )
        lines.append("## {}. {}{}".format(i, title, " · " + meta if meta else ""))
        lines.append("")
        text = str(item.get("text") or "").rstrip()
        for line in text.splitlines() or [""]:
            lines.append("> " + line)
        lines.append("")

        loc = str(item.get("sourcefile") or "").strip() or "语料库"
        start = item.get("line_start")
        if start is not None:
            end = item.get("line_end")
            loc = "{}，第 {}–{} 行".format(loc, start, end if end is not None else start)
        lines.append("- 原文位置：{}".format(loc))

        note = str(item.get("note") or "").strip()
        if note:
            note_lines = note.splitlines()
            lines.append("- 笔记：" + note_lines[0])
            for extra in note_lines[1:]:
                lines.append("  " + extra)
        lines += ["", "---", ""]
    return "\n".join(lines).rstrip() + "\n"
