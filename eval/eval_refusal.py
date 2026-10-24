import argparse
import csv
import io
import json
import sys

sys.path.append("../src")
from rag import answer

QUESTION_PATH = "./questions.jsonl"
CHUNK_PATH = "../data/chunks/punct.jsonl"
OUTPUT_CSV = "./refusal_results.csv"


def load_chunks():
    """chunk_id -> (sourcefile, line_start, line_end)"""
    chunks = {}
    with open(CHUNK_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            m = obj["meta"]
            chunks[obj["chunk_id"]] = (
                m.get("sourcefile"),
                m.get("line_start"),
                m.get("line_end"),
            )
    return chunks


def line_overlap(a, b):
    if a[0] is None or b[0] is None or a[0] != b[0]:
        return False
    return not (a[2] < b[1] or b[2] < a[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条，0 为全量")
    ap.add_argument("--mode", default="rrf", choices=["dense", "bm25", "rrf"])
    ap.add_argument("--top-k", type=int, default=5)
    args = ap.parse_args()
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    questions = []
    with open(QUESTION_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    if args.limit:
        questions = questions[: args.limit]

    chunks = load_chunks()
    rows = []

    for q in questions:
        r = answer(q["question"], top_k=args.top_k, mode=args.mode)
        refused = r.get("can_answer") is False
        rows.append(
            {
                "id": q["id"],
                "answerable": q["answerable"],
                "category": q["category"],
                "question": q["question"],
                "refused": refused,
                "can_answer": r.get("can_answer"),
                "invalid_output": r.get("invalid_output", False),
                "citations": json.dumps(r.get("citations", []), ensure_ascii=False),
                "citations_chunk_ids": json.dumps(
                    r.get("citations_chunk_ids", []), ensure_ascii=False
                ),
                "answer": r.get("answer", ""),
                "refusal_reason": r.get("refusal_reason"),
                "retrieved_chunk_ids": json.dumps(
                    r.get("retrieved_chunk_ids", []), ensure_ascii=False
                ),
            }
        )
        status = "拒答" if refused else "回答"
        print(f"{q['id']} [{q['category']}] {status}")

    with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n明细已保存：{OUTPUT_CSV}")

    unans = [r for r in rows if not r["answerable"]]
    ans = [r for r in rows if r["answerable"]]

    refused_unans = sum(1 for r in unans if r["refused"])
    refused_ans = sum(1 for r in ans if r["refused"])
    errors = sum(1 for r in rows if r["can_answer"] is None)

    print("\n===== 拒答 2x2 =====")
    print(f"{'':<14}{'拒答':>8}{'回答':>8}")
    print(f"{'语料外':<14}{refused_unans:>8}{len(unans) - refused_unans:>8}")
    print(f"{'可答':<14}{refused_ans:>8}{len(ans) - refused_ans:>8}")
    print(f"\n拒答率   = {refused_unans}/{len(unans)} = {refused_unans / len(unans):.1%}")
    print(f"误拒率   = {refused_ans}/{len(ans)} = {refused_ans / len(ans):.1%}")
    print(f"解析失败 = {errors} 条（can_answer=None，既不算拒答也不算正常回答）")

    # 需要人看的失败样本
    hallu = [r["id"] for r in unans if not r["refused"]]
    false_ref = [r["id"] for r in ans if r["refused"]]
    if hallu:
        print(f"\n语料外却作答（幻觉风险）：{hallu}")
        for r in unans:
            if r["id"] in hallu:
                print(f"  {r['id']}: {r['answer'][:100]}")
    if false_ref:
        print(f"可答却被拒（误拒）：{false_ref}")

    # 引用准确率：只算可答且作答的
    answered = [r for r in ans if not r["refused"] and r["can_answer"] is True]
    prec_exact, cov_exact, prec_line, cov_line = [], [], [], []
    no_citation = []
    for r in answered:
        q = next(x for x in questions if x["id"] == r["id"])
        gold = q.get("gold_chunk_ids") or [e["chunk_id"] for e in q["evidence"]]
        cited = json.loads(r["citations_chunk_ids"])
        if not cited:
            no_citation.append(r["id"])
            cov_exact.append(0.0)
            cov_line.append(0.0)
            continue
        prec_exact.append(sum(1 for c in cited if c in gold) / len(cited))
        cov_exact.append(sum(1 for g in gold if g in cited) / len(gold))
        prec_line.append(
            sum(
                1
                for c in cited
                if any(line_overlap(chunks[c], chunks[g]) for g in gold)
            )
            / len(cited)
        )
        cov_line.append(
            sum(
                1
                for g in gold
                if any(line_overlap(chunks[c], chunks[g]) for c in cited)
            )
            / len(gold)
        )

    def avg(xs):
        return sum(xs) / len(xs) if xs else float("nan")

    print("\n===== 引用（仅可答且作答） =====")
    print(f"作答题数：{len(answered)}")
    print(f"引用精确率 exact：{avg(prec_exact):.3f}")
    print(f"引用覆盖率 exact：{avg(cov_exact):.3f}")
    print(f"引用精确率 line ：{avg(prec_line):.3f}")
    print(f"引用覆盖率 line ：{avg(cov_line):.3f}")
    if no_citation:
        print(f"声称能答但无有效引用：{no_citation}")


if __name__ == "__main__":
    main()
