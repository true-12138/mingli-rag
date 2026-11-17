# -*- coding: utf-8 -*-
"""预生成术语卡的「原文例句」：data/terminology/term_snippets.jsonl。

术语卡的释义来自 bazi-terms / iztro 两个词典，多数是英文注解，对读原文的人
帮助有限；真正有用的是「这个词在古籍里长什么样」。这里扫一遍语料，给每个词条
挑 1–2 条原文例句（不同书名优先），运行时只读结果文件，不加载检索索引。

用法（仓库根目录）：
    python scripts/build_term_snippets.py            # 写 data/terminology/term_snippets.jsonl
    python scripts/build_term_snippets.py --dry-run  # 只打印统计

口径：
- 只收两字以上的词条，和 terms.annotate 的标注口径一致；
- 同一个词条取两个不同书名，各取「本 chunk 内出现次数最多」的那一段，
  全篇只出现一次的词条就只有一条例句；
- 例句是检索语料里的原文，不是本轮回答的引用依据，前端会单独注明。
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import corpus  # noqa: E402
import terms  # noqa: E402

CONTEXT = 60          # 例句在词条前后各取多少字
SNIPPET_PER_TERM = 2


def excerpt(text: str, term: str) -> str:
    pos = text.find(term)
    if pos < 0:
        return ""
    start = max(0, pos - CONTEXT)
    end = min(len(text), pos + len(term) + CONTEXT)
    body = " ".join(text[start:end].split())
    if start > 0:
        body = "…" + body
    if end < len(text):
        body = body + "…"
    return body


def build(chunks: list[dict]) -> list[dict]:
    keys = [t for t in terms.load() if len(t) >= terms.MIN_ANNOTATE_LEN]
    # term → book → [chunk]
    found: dict[str, dict[str, list[dict]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    for chunk in chunks:
        text = chunk.get("chunk_text") or ""
        if not text:
            continue
        meta = chunk.get("meta") or {}
        book = str(meta.get("book") or "")
        for term in keys:
            if term in text:
                found[term][book].append({
                    "chunk_id": int(chunk["chunk_id"]),
                    "book": book,
                    "chapter": str(meta.get("chapter") or ""),
                    "count": text.count(term),
                    "punct": bool(meta.get("has_punctuation")),
                    "text": text,
                })

    rows = []
    for term in keys:
        by_book = found.get(term)
        if not by_book:
            continue
        # 书名按「出现该词的 chunk 数」排序，并列时按书名，保证结果可复现
        books = sorted(by_book, key=lambda b: (-len(by_book[b]), b))
        snippets = []
        for book in books[:SNIPPET_PER_TERM]:
            # 有标点的原文好读得多——无标点组的文本是一整串，例句断句全靠猜
            best = sorted(by_book[book], key=lambda c: (not c["punct"], -c["count"], c["chunk_id"]))[0]
            body = excerpt(best["text"], term)
            if body:
                snippets.append({
                    "chunk_id": best["chunk_id"],
                    "book": best["book"],
                    "chapter": best["chapter"],
                    "text": body,
                })
        if snippets:
            rows.append({"term": term, "snippets": snippets})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=str(Path("data") / "terminology" / "term_snippets.jsonl"))
    args = ap.parse_args()

    import retrieval  # 只有这里需要语料，导入一次约几秒

    rows = build(retrieval.chunks)
    covered = sum(1 for r in rows for _ in r["snippets"])
    print("词条 {} 个，有例句 {} 个，例句 {} 条".format(len(terms.load()), len(rows), covered))
    if args.dry_run:
        for row in rows[:5]:
            print(" -", row["term"], "|", row["snippets"][0]["book"], "|", row["snippets"][0]["text"][:50])
        return 0

    out = Path(args.out)
    if not out.is_absolute():
        out = corpus.data_dir() / out.relative_to("data") if out.parts[0] == "data" else out
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("写入", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
