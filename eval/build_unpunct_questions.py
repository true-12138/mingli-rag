# -*- coding: utf-8 -*-
"""把人工起草的题目补上 evidence，并校验引文确实出自对应 chunk。

草稿里每题只写 {id, answerable, category, question, answer, gold_chunk_ids, quote}，
这里按 chunk_id 回填 book/volume/chapter/line_start/line_end/sourcefile，同时做两道检查：

1. gold_chunk_ids 必须都在无标点语料里，且正好 1 条（这组题一题一段）；
2. quote 去掉标点空白后必须是对应 chunk_text 的子串——引文不许手写记忆。
任一条不过就直接报错退出，不生成半成品题库。

**编号口径**：草稿里的 id 是 `unpunct.jsonl` 文件内的局部编号（1..5851），
而检索与评测用的是 `corpus.py` 重编的全局编号（标点组在前、无标点组顺延，
无标点组从 2831 起）。两者差整整一个标点组，直接用局部编号出题会让所有
golds 落到别的书上——2026-11-18 第一次跑评测就是 36 题全 0。这里按
`corpus.load_chunks()` 的顺序把局部编号对到全局编号，写入题库的一律是全局编号。

用法：
    python eval/build_unpunct_questions.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import corpus  # noqa: E402
import segment  # noqa: E402

DRAFT = ROOT / "eval" / "_draft_unpunct.json"
CORPUS = ROOT / "data" / "chunks" / "unpunct.jsonl"
OUT = ROOT / "eval" / "questions_unpunct.jsonl"

PREFIX = "data/clean_text/"


def _plain(text: str) -> str:
    return segment._PUNCT.sub("", text)


def _local_to_global(raw_rows: list[dict]) -> dict[int, int]:
    """unpunct 文件内局部编号 -> 检索用的全局编号。

    顺序是唯一契约（corpus.py 的注释写明了）：两边都按文件行序产出，
    所以按序 zip 即可；数量对不上说明语料文件被改过，直接报错。
    """
    global_ids = [c["chunk_id"] for c in corpus.load_chunks()
                  if c["meta"].get("index_source") == "unpunct"]
    if len(global_ids) != len(raw_rows):
        raise SystemExit(
            "语料行数对不上：unpunct.jsonl {} 行，corpus.load_chunks 里 {} 条——"
            "先检查语料文件是否被改动".format(len(raw_rows), len(global_ids)))
    return {int(raw["chunk_id"]): gid for raw, gid in zip(raw_rows, global_ids)}


def main() -> int:
    raw_rows = [json.loads(line) for line in CORPUS.open(encoding="utf-8")]
    local_to_global = _local_to_global(raw_rows)
    chunks = {local_to_global[int(r["chunk_id"])]: r for r in raw_rows}

    drafts = json.loads(DRAFT.read_text(encoding="utf-8"))
    seen_ids = set()
    rows = []
    problems = []
    for d in drafts:
        qid = d["id"]
        if qid in seen_ids:
            problems.append("{}: id 重复".format(qid))
        seen_ids.add(qid)
        local_golds = d["gold_chunk_ids"]
        golds = [local_to_global.get(int(g)) for g in local_golds]
        if len(golds) != 1 or golds[0] is None:
            problems.append("{}: gold_chunk_ids 应正好 1 条且在无标点语料里，实际 {}".format(
                qid, local_golds))
            continue
        row = chunks[golds[0]]
        meta = row["meta"]
        text = str(row.get("chunk_text") or "")
        quote = d["quote"]
        plain_quote = _plain(quote)
        if len(plain_quote) < 8:
            problems.append("{}: 引文太短（去标点后 {} 字）".format(qid, len(plain_quote)))
        elif plain_quote not in _plain(text):
            problems.append("{}: 引文不在 #{} 原文里：{}".format(qid, golds[0], quote))
        if not d.get("answer"):
            problems.append("{}: 缺 answer".format(qid))
        sourcefile = str(meta.get("sourcefile") or "")
        rows.append({
            "id": qid,
            "answerable": bool(d.get("answerable", True)),
            "category": d["category"],
            "question": d["question"],
            "answer": d["answer"],
            "gold_chunk_ids": golds,
            "evidence": [{
                "book": meta.get("book"),
                "volume": meta.get("volume") or "",
                "chapter": meta.get("chapter") or "",
                "chunk_id": golds[0],
                "line_start": meta.get("line_start"),
                "line_end": meta.get("line_end"),
                "sourcefile": sourcefile[len(PREFIX):] if sourcefile.startswith(PREFIX)
                else sourcefile,
                "quote": quote,
            }],
        })

    if problems:
        print("校验未通过：")
        for p in problems:
            print(" -", p)
        return 1

    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    books = {r["evidence"][0]["book"] for r in rows}
    print("已写入 {}：{} 题，覆盖 {} 部书".format(OUT, len(rows), len(books)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
