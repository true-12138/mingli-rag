import csv
import json
import sys
sys.path.append("../src")
from retrieval import retrieve_one
import corpus
# -------------------------- 配置区 --------------------------
QUESTION_PATH = "./questions.jsonl"
OUTPUT_CSV = "./results_v2.csv"
TOP_K = 5
STRATEGIES = ["dense", "bm25", "rrf"]
def load_chunks():
    """chunk_id -> (sourcefile, line_start, line_end)
    行号是书内行号，不同书的行号都从 1 开始，**必须带 sourcefile 一起比**，
    否则两本不相关的书只要行号碰巧重叠就会被误判为命中。
    语料顺序与编号跟 retrieval 共用 corpus.load_chunks，新增语料文件后这里不用改。
    """
    chunks = {}
    for obj in corpus.load_chunks():
        meta = obj["meta"]
        chunks[obj["chunk_id"]] = (
            meta.get("sourcefile"),
            meta.get("line_start"),
            meta.get("line_end"),
        )
    return chunks
def load_questions():
    questions = []
    with open(QUESTION_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return questions
def get_retrieved_ids(res, chunks):
    """retrieval 必须返回 chunk_id；如果返回的是矩阵行号，直接报错而不是算错。"""
    ids = []
    bad = []
    for item in res:
        if "chunk_id" not in item:
            raise SystemExit(
                "\n[STOP] retrieve_one 的返回里没有 'chunk_id' 字段。\n"
                f"当前字段：{list(item.keys())}\n"
                "如果只有 'chunk_idx'/'idx'，那是语料行号（0 起），不是 chunk_id（1 起）。\n"
                "用 src/retrieval.py 的修正版：在 final.append 里加 "
                '"chunk_id": c["chunk_id"]，然后再跑评测。\n'
            )
        cid = item["chunk_id"]
        ids.append(cid)
        if cid not in chunks:
            bad.append(cid)
    if bad:
        raise SystemExit(
            f"\n[STOP] retrieve_one 返回了 {len(bad)} 个不在 chunk_id 集合里的 id，"
            f"示例：{bad[:5]}。检查 chunks 与 embeddings 是否同一份文件、同一顺序。\n"
        )
    return ids
def line_overlap(a, b):
    """a,b = (sourcefile, line_start, line_end)；同一本书且行区间相交才算命中。"""
    if a[0] is None or b[0] is None or a[0] != b[0]:
        return False
    return not (a[2] < b[1] or b[2] < a[1])
def score_one(q, retrieved_ids, chunks, mode):
    """返回 (recall, mrr, covered, n_gold)。"""
    golds = q.get("gold_chunk_ids") 
    if not golds:
        return None
    top = retrieved_ids[:TOP_K]
    if mode == "exact":
        covered = [g for g in golds if g in top]
        first = next((i + 1 for i, cid in enumerate(top) if cid in golds), None)
    elif mode == "line":
        covered = [
            g for g in golds
            if any(line_overlap(chunks[g], chunks[cid]) for cid in top)
        ]
        first = next(
            (
                i + 1
                for i, cid in enumerate(top)
                if any(line_overlap(chunks[g], chunks[cid]) for g in golds)
            ),
            None,
        )
    else:
        raise ValueError(mode)

    recall = len(covered) / len(golds)
    mrr = 1.0 / first if first else 0.0
    return recall, mrr, len(covered), len(golds)
def main():
    chunks = load_chunks()
    questions = load_questions()
    rows = []
    # agg[strategy][mode] -> list
    agg = {
        s: {m: [] for m in ("exact", "line")}
        for s in STRATEGIES
    }
    # 分题型只统计 line 口径
    by_cat = {
        s: {}
        for s in STRATEGIES
    }
    for q in questions:
        row = {
            "id": q["id"],
            "answerable": q["answerable"],
            "category": q["category"],
            "question": q["question"],
        }
        for strat in STRATEGIES:
            res = retrieve_one(q["question"], top_k=TOP_K, mode=strat)
            ids = get_retrieved_ids(res, chunks)
            for mode in ("exact", "line"):
                r = score_one(q, ids, chunks, mode)
                if r is None:
                    row[f"{strat}_{mode}_recall"] = ""
                    row[f"{strat}_{mode}_mrr"] = ""
                    continue
                recall, mrr, covered, n_gold = r
                row[f"{strat}_{mode}_recall"] = round(recall, 4)
                row[f"{strat}_{mode}_mrr"] = round(mrr, 4)
                row[f"{strat}_{mode}_covered"] = f"{covered}/{n_gold}"
                if q["answerable"]:
                    agg[strat][mode].append(recall)
                    by_cat[strat].setdefault(q["category"], []).append(recall)
        rows.append(row)
    fieldnames = list(rows[0].keys())
    with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"明细结果：{OUTPUT_CSV}")
    print("\n===== 总指标（20 条可答） =====")
    print(f"{'strategy':<8}{'exact_R@5':>12}{'line_R@5':>12}{'line_MRR':>12}")
    for s in STRATEGIES:
        exact_r = sum(agg[s]["exact"]) / len(agg[s]["exact"]) if agg[s]["exact"] else 0
        line_r = sum(agg[s]["line"]) / len(agg[s]["line"]) if agg[s]["line"] else 0
        line_m = (
            sum(
                float(r[f"{s}_line_mrr"])
                for r in rows
                if r["answerable"] and r[f"{s}_line_mrr"] != ""
            )
            / len(agg[s]["line"])
            if agg[s]["line"]
            else 0
        )
        print(f"{s:<8}{exact_r:>12.4f}{line_r:>12.4f}{line_m:>12.4f}")
    print("\n===== 分题型 Recall@5（line 口径） =====")
    cats = sorted({q["category"] for q in questions if q["answerable"]})
    header = "category".ljust(10) + "".join(f"{s:>10}" for s in STRATEGIES)
    print(header)
    for cat in cats:
        line = cat.ljust(10)
        for s in STRATEGIES:
            vals = by_cat[s].get(cat, [])
            line += f"{sum(vals) / len(vals):>10.2f}" if vals else f"{'-':>10}"
        print(line)
if __name__ == "__main__":
    main()
