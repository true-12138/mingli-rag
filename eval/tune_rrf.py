# -*- coding: utf-8 -*-
"""RRF 参数网格搜索。

背景：语料从 2,830 条扩到 8,681 条后，RRF 的 line Recall@5 从 0.7750 掉到 0.7000，
但 dense（0.6250→0.6250）和 BM25（0.4750→0.5250）两路各自都没退步。
退化发生在融合环节，说明 rrf_k=60 / candidate_k=20 是在小候选池上调出来的。

这个脚本只做检索：每个问句只编码一次，之后在内存里反复融合，扫参数不会重复付编码成本。
不调用大模型，可以放心跑。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append("../src")

import numpy as np

import corpus
from retrieval import bm25, embeds, model, tokenize

QUESTION_PATH = "./questions.jsonl"
TOP_K = 5

RRF_KS = [10, 20, 30, 40, 60, 80, 100, 150]
CAND_K = [10, 20, 30, 40, 60, 100, 200]
WEIGHTS = [(1.0, 1.0), (1.0, 0.7), (1.0, 0.5), (0.7, 1.0), (0.5, 1.0)]


def load_questions(path):
    qs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                qs.append(json.loads(line))
    return [q for q in qs if q.get("answerable")]


def line_overlap(a, b):
    if a[0] is None or b[0] is None or a[0] != b[0]:
        return False
    return not (a[2] < b[1] or b[2] < a[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=QUESTION_PATH)
    ap.add_argument("--top-k", type=int, default=TOP_K)
    args = ap.parse_args()

    rows = corpus.load_chunks()
    chunks = {}
    for r in rows:
        m = r["meta"]
        chunks[r["chunk_id"]] = (m.get("sourcefile"), m.get("line_start"), m.get("line_end"))

    questions = load_questions(args.questions)
    print(f"语料 {len(rows)} 条｜可答题目 {len(questions)} 条｜Recall@{args.top_k}")

    # 每个问句只编码一次，拿到两路的**完整**降序排名；不同 candidate_k 只是取前缀
    ranks = []
    for q in questions:
        text = q["question"]
        q_emb = model.encode(text, normalize_embeddings=True)
        d_order = np.argsort(embeds @ q_emb)[::-1]
        b_order = np.argsort(np.asarray(bm25.get_scores(tokenize(text)), dtype=np.float32))[::-1]
        golds = q.get("gold_chunk_ids") or [e["chunk_id"] for e in q.get("evidence", [])]
        ranks.append((d_order, b_order, golds, q["category"]))
    print("两路排名已就绪，开始扫参数")

    results = []
    for cand in CAND_K:
        for k in RRF_KS:
            for wd, wb in WEIGHTS:
                covs, mrrs, by_cat = [], [], {}
                for d_order, b_order, golds, cat in ranks:
                    fused = {}
                    for rank, idx in enumerate(d_order[:cand], start=1):
                        cid = rows[int(idx)]["chunk_id"]
                        fused[cid] = fused.get(cid, 0.0) + wd / (rank + k)
                    for rank, idx in enumerate(b_order[:cand], start=1):
                        cid = rows[int(idx)]["chunk_id"]
                        fused[cid] = fused.get(cid, 0.0) + wb / (rank + k)
                    top = [cid for cid, _ in sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[: args.top_k]]
                    hit = [g for g in golds if any(line_overlap(chunks[g], chunks[c]) for c in top)]
                    covs.append(len(hit) / len(golds))
                    by_cat.setdefault(cat, []).append(len(hit) / len(golds))
                    first = next(
                        (i + 1 for i, c in enumerate(top) if any(line_overlap(chunks[g], chunks[c]) for g in golds)),
                        None,
                    )
                    mrrs.append(1.0 / first if first else 0.0)
                results.append(
                    {
                        "candidate_k": cand,
                        "rrf_k": k,
                        "w_dense": wd,
                        "w_bm25": wb,
                        "recall": sum(covs) / len(covs),
                        "mrr": sum(mrrs) / len(mrrs),
                        "by_cat": {c: sum(v) / len(v) for c, v in by_cat.items()},
                    }
                )

    results.sort(key=lambda r: (-r["recall"], -r["mrr"]))
    print(f"\n共 {len(results)} 组配置，前 15：")
    print(f"{'cand_k':>7}{'rrf_k':>7}{'w_dense':>9}{'w_bm25':>8}{'line_R@5':>11}{'line_MRR':>10}")
    for r in results[:15]:
        print(
            f"{r['candidate_k']:>7}{r['rrf_k']:>7}{r['w_dense']:>9.1f}"
            f"{r['w_bm25']:>8.1f}{r['recall']:>11.4f}{r['mrr']:>10.4f}"
        )

    # 总 recall 相同的配置可能在不同题型上此消彼长，所以把分题型也打出来
    cats = sorted(results[0]["by_cat"])
    print(f"\n{'cand_k':>7}{'rrf_k':>7}{'w_d':>5}{'w_b':>5}{'R@5':>9}  " + "".join(f"{c:>10}" for c in cats))
    seen = set()
    for r in results:
        sig = (r["recall"], tuple(sorted(r["by_cat"].items())))
        if sig in seen:
            continue
        seen.add(sig)
        print(
            f"{r['candidate_k']:>7}{r['rrf_k']:>7}{r['w_dense']:>5.1f}{r['w_bm25']:>5.1f}"
            f"{r['recall']:>9.4f}  " + "".join(f"{r['by_cat'][c]:>10.2f}" for c in cats)
        )
        if len(seen) >= 8:
            break

    cur = next(r for r in results if r["rrf_k"] == 60 and r["candidate_k"] == 20 and (r["w_dense"], r["w_bm25"]) == (1.0, 1.0))
    print(f"\n原线上配置 (cand_k=20, rrf_k=60, 1:1)：line_R@5={cur['recall']:.4f}  MRR={cur['mrr']:.4f}")
    best = results[0]
    print(f"最优配置 (cand_k={best['candidate_k']}, rrf_k={best['rrf_k']}, "
          f"{best['w_dense']:.1f}:{best['w_bm25']:.1f})："
          f"line_R@5={best['recall']:.4f}  MRR={best['mrr']:.4f}")


if __name__ == "__main__":
    main()
