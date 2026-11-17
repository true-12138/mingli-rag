# -*- coding: utf-8 -*-
"""术语卡：给回答正文里的命理术语加下划线和释义卡。

数据只取两份人工整理过的 jsonl（`bazi-terms.jsonl` / `iztro-terms.jsonl`），
不用 `data/terminology/sudo-biao/` 里那些程序生成的文本——那边的 term 字段
是「简介」「nature」「口诀」这类键名，直接标在正文上会把普通词标成术语。
单字（甲、子、木）和「性别」「当前」这类通用词只在搜索里返回，不自动加下划线：
标错一个词比少标十个更伤。

术语卡里的词典释义和原文例句都不是本轮检索片段，不能当引用依据；回答的
引用编号仍然只来自 `retrieve_one()` 的结果，这条边界和 `tools.search_terms` 一致。

原文例句由 `scripts/build_term_snippets.py` 预先生成到
`data/terminology/term_snippets.jsonl`，运行时只读文件，不加载检索索引。
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

import corpus

# 只标注两字以上的词条：单字（甲/子/木）在正文里出现得太密，标了反而看不清。
MIN_ANNOTATE_LEN = 2
# 有几条虽然进了词典，但在白话正文里是普通词，加下划线只会干扰阅读。
# 它们仍然能搜到，只是不自动标注。
ANNOTATE_BLOCK = frozenset({
    "性别", "当前", "顺行", "逆行", "星运", "五行分值",
})

_CACHE: dict[str, dict[str, Any]] | None = None
_LOCK = threading.Lock()


def _term_dir() -> Path:
    return corpus.data_dir() / "terminology"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("term"):
                rows.append(obj)
    return rows


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def _looks_broken(text: str) -> bool:
    """源数据里有的词条被截断成「五行属，。」（iztro 的 6 个星曜）。

    这种释义直接展示比没有更糟，宁可留空、只给原文例句。
    """
    return bool(re.search(r"[，、；：]\s*。", text))


def _clean(text: str, term: str) -> str:
    """去掉释义里重复的词条名。

    「食神：Eating God；…」→「Eating God；…」
    「紫微斗数十二宫之一：命宫。」→「紫微斗数十二宫之一」
    """
    body = str(text or "").strip()
    for sep in ("：", ":"):
        prefix = term + sep
        if body.startswith(prefix):
            return body[len(prefix):].strip()
    tail = re.match(r"^(.+?)[：:]\s*" + re.escape(term) + r"[。．.\s]*$", body)
    if tail:
        return tail.group(1).strip()
    return body


def _snippets() -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in _read_jsonl(_term_dir() / "term_snippets.jsonl"):
        term = str(row.get("term") or "").strip()
        items = row.get("snippets")
        if term and isinstance(items, list):
            out[term] = [i for i in items if isinstance(i, dict)]
    return out


def load() -> dict[str, dict[str, Any]]:
    """词条 → {term, category, definition, source, snippets}。进程内只读一次。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    with _LOCK:
        if _CACHE is None:
            root = _term_dir()
            out: dict[str, dict[str, Any]] = {}
            # 两个来源都收同一个词时按释义质量挑：中文释义 > 英文释义 > 空。
            # bazi-terms 收的体系全（十神/神煞/纳音都有词条），iztro 的释义是中文，
            # 能覆盖时就换成中文——给中文读者看的卡片，「五行属土，阴」比
            # 「Earth, yin」有用；但 iztro 有 6 个星曜的释义在源数据里被截断了，
            # 那种算空，不能用它盖掉能看的英文。
            for name in ("bazi-terms.jsonl", "iztro-terms.jsonl"):
                for row in _read_jsonl(root / name):
                    term = str(row["term"]).strip()
                    text = str(row.get("text") or "").strip()
                    if not term or not text:
                        continue
                    definition = _clean(text, term)
                    if _looks_broken(definition):
                        definition = ""
                    item = {
                        "term": term,
                        "category": str(row.get("category") or ""),
                        "definition": definition,
                        "source": name,
                    }
                    old = out.get(term)
                    if old is None or _definition_rank(item) > _definition_rank(old):
                        out[term] = item
            for term, snippets in _snippets().items():
                if term in out:
                    out[term]["snippets"] = snippets
            for item in out.values():
                item.setdefault("snippets", [])
            _CACHE = out
    return _CACHE


def _definition_rank(item: dict[str, Any]) -> int:
    text = item["definition"]
    if not text:
        return 0
    return 2 if _has_cjk(text) else 1


def get(term: str) -> dict[str, Any] | None:
    return load().get(str(term or "").strip())


def search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """按词条名或释义做子串检索，给「查术语」入口用。"""
    needle = str(query or "").strip()
    if not needle:
        return []
    hits = []
    for item in load().values():
        if needle in item["term"] or needle in item["definition"]:
            hits.append(item)
    # 词条名命中的排前面，短的在前——查「贵人」时先给「天乙贵人」再给释义里的长尾。
    hits.sort(key=lambda i: (needle not in i["term"], len(i["term"]), i["term"]))
    return hits[:max(1, int(limit))]


def _annotatable() -> dict[str, list[str]]:
    """首字 → 该首字开头的可标注词条（按长度降序，长词优先命中）。"""
    buckets: dict[str, list[str]] = {}
    for term in load():
        if len(term) < MIN_ANNOTATE_LEN or term in ANNOTATE_BLOCK:
            continue
        buckets.setdefault(term[0], []).append(term)
    for terms in buckets.values():
        terms.sort(key=len, reverse=True)
    return buckets


def annotate(text: str, limit: int = 40) -> list[dict[str, Any]]:
    """在正文里找词条，返回左闭右开的区间，互不重叠、长词优先。

    只做定位，不返回释义——调用方要么自己拼 `entries`，要么走 HTTP 接口。
    """
    src = str(text or "")
    buckets = _annotatable()
    spans: list[dict[str, Any]] = []
    i = 0
    while i < len(src) and len(spans) < limit:
        terms = buckets.get(src[i])
        if terms:
            for term in terms:
                if src.startswith(term, i):
                    spans.append({"term": term, "start": i, "end": i + len(term)})
                    i += len(term) - 1
                    break
        i += 1
    return spans


def annotate_with_entries(text: str, limit: int = 40) -> list[dict[str, Any]]:
    """标注 + 带上释义，给 HTTP 接口用；同一个词条在一段话里只回一次释义。"""
    entries = load()
    out = []
    for span in annotate(text, limit=limit):
        item = entries.get(span["term"])
        if not item:
            continue
        out.append({
            "term": item["term"],
            "start": span["start"],
            "end": span["end"],
            "category": item["category"],
            "definition": item["definition"],
            "source": item["source"],
            "snippets": item["snippets"],
        })
    return out


def stats() -> dict[str, Any]:
    entries = load()
    return {
        "terms": len(entries),
        "annotatable": sum(len(v) for v in _annotatable().values()),
        "with_snippets": sum(1 for i in entries.values() if i["snippets"]),
    }
