# -*- coding: utf-8 -*-
"""对照实验：jieba 用「语料篇名」当词典，能不能追上字二元组。

之前只测了 data/terminology 里的 246 条人工词表，结论是「加不加没区别」。
这个脚本把 2,830 个带篇名 chunk 的篇名拆成词条（约 1k 条），再造一份
真正贴合语料的词典，重测同一批 20 道题——用来回答「是不是词典不够好」。

用法：python scripts/probe_jieba_dict.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import corpus  # noqa: E402
from rank_bm25 import BM25Okapi  # noqa: E402

import retrieval_utils as ru  # noqa: E402

SEP = "/．、，。；：()（）· "


def chapter_terms() -> list[str]:
    """把篇名拆成候选词条：'并释男女命例 / 夫妇位 / 妨夫妇' -> 三段。"""
    words = set()
    for c in corpus.load_chunks():
        chapter = c["meta"].get("chapter") or ""
        buf = []
        for ch in chapter + SEP:
            if ch in SEP:
                piece = "".join(buf).strip()
                buf = []
                if 2 <= len(piece) <= 6:
                    words.add(piece)
            else:
                buf.append(ch)
    return sorted(words)


def evaluate(tok, texts, gold, questions):
    bm25 = BM25Okapi([tok(t) for t in texts])
    ranks = []
    for q in questions:
        scores = bm25.get_scores(tok(q["question"]))
        order = list(scores.argsort()[::-1])
        ranks.append(min(order.index(g) + 1 for g in gold[q["id"]]))
    hit5 = sum(1 for r in ranks if r <= 5) / len(ranks)
    mrr = sum(1 / r for r in ranks) / len(ranks)
    return hit5, mrr, ranks


def main() -> None:
    chunks = corpus.load_chunks()
    texts = [c["chunk_text"] for c in chunks]
    idx = {c["chunk_id"]: i for i, c in enumerate(chunks)}
    questions = [json.loads(l) for l in open(ROOT / "eval" / "questions.jsonl",
                                             encoding="utf-8") if l.strip()]
    questions = [q for q in questions if q.get("answerable")]
    gold = {q["id"]: [idx[c] for c in q["gold_chunk_ids"] if c in idx] for q in questions}

    terms = chapter_terms()
    print("篇名词条 {} 条，样例 {}".format(len(terms), terms[:12]), flush=True)

    import jieba

    results = {}
    for name, mode in (("jieba+篇名词典", "jieba"), ("jieba_search+篇名词典", "jieba_search")):
        for t in terms:
            jieba.add_word(t, freq=100000)

        def tok(text, mode=mode):
            cut = jieba.cut_for_search if mode == "jieba_search" else jieba.lcut
            return [w for w in cut(text) if w.strip()]

        results[name] = evaluate(tok, texts, gold, questions)
        print("{} hit@5={:.3f} MRR={:.3f}".format(name, *results[name][:2]), flush=True)

    results["bigram"] = evaluate(ru.bigram_tokens, texts, gold, questions)
    print("bigram hit@5={:.3f} MRR={:.3f}".format(*results["bigram"][:2]), flush=True)

    print("\nid     " + "  ".join("{:>18}".format(k) for k in results))
    for i, q in enumerate(questions):
        print("{:<6} ".format(q["id"]) + "  ".join(
            "{:>18}".format(results[k][2][i]) for k in results))


if __name__ == "__main__":
    main()
