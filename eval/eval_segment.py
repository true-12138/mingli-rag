# -*- coding: utf-8 -*-
"""自动断句的抽样评测：只测「没改字」，断句质量另由人读。

`segment.punctuate` 已经强制「去掉标点后逐字相同」，所以这里的失败只有两种：
模型两次都没能给出可用断句（改字、漏字或干脆原样照抄）。通过率不等于断句好坏，
它只说明这批输出可以安全地替换显示；句子断得对不对，需要人读下面打印的样本。

用法：
    python eval/eval_segment.py --n 12 --seed 20261118
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import segment  # noqa: E402

CORPUS = ROOT / "data" / "chunks" / "unpunct.jsonl"


def _round_robin_by_book(rows: list[dict], n: int, rng: random.Random) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        buckets.setdefault(str(row.get("meta", {}).get("book") or "?"), []).append(row)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    books = sorted(buckets)
    rng.shuffle(books)
    picked: list[dict] = []
    i = 0
    while len(picked) < n and books:
        for book in list(books):
            if buckets[book]:
                picked.append(buckets[book].pop())
                if len(picked) >= n:
                    break
            else:
                books.remove(book)
        i += 1
        if i > 10000:
            break
    return picked


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--seed", type=int, default=20261118)
    ap.add_argument("--min-chars", type=int, default=80)
    ap.add_argument("--max-chars", type=int, default=600)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    rows = [json.loads(line) for line in CORPUS.open(encoding="utf-8")]
    rows = [r for r in rows if args.min_chars <= len(r.get("chunk_text") or "") <= args.max_chars]
    rng = random.Random(args.seed)
    picked = _round_robin_by_book(rows, args.n, rng)
    print("抽样 {} 段，覆盖 {} 部书".format(
        len(picked), len({r["meta"]["book"] for r in picked})))

    records = []
    for row in picked:
        text = str(row["chunk_text"]).strip()
        started = time.time()
        try:
            out = segment.punctuate(text)
            ok = bool(out) and segment.same_content(text, out)
            error = None
        except Exception as exc:  # noqa: BLE001 - 失败样本正是要统计的东西
            out, ok = "", False
            error = "{}: {}".format(type(exc).__name__, exc)
        elapsed = time.time() - started
        added = len(segment._PUNCT_MARKS.findall(out)) - len(segment._PUNCT_MARKS.findall(text))
        records.append({
            "chunk_id": int(row["chunk_id"]),
            "book": row["meta"]["book"],
            "chars": len(text),
            "ok": ok,
            "added_marks": added,
            "elapsed_s": round(elapsed, 2),
            "error": error,
            "source": text,
            "output": out,
        })
        print("[{}] {} #{} {} 字 +{} 标点 {:.1f}s{}".format(
            "OK" if ok else "FAIL", row["meta"]["book"], row["chunk_id"], len(text),
            added, elapsed, "" if ok else "  " + str(error)))

    ok_records = [r for r in records if r["ok"]]
    summary = {
        "n": len(records),
        "ok": len(ok_records),
        "pass_rate": round(len(ok_records) / len(records), 3) if records else 0,
        "fails": Counter(r["error"] for r in records if not r["ok"]),
        "median_added_marks": sorted(r["added_marks"] for r in ok_records)[len(ok_records) // 2]
        if ok_records else 0,
        "p50_elapsed_s": sorted(r["elapsed_s"] for r in records)[len(records) // 2]
        if records else 0,
        "books": len({r["book"] for r in records}),
        "cache_version": segment.CACHE_VERSION,
        "note": "通过=去掉标点后与原文逐字相同且确实加了句读；断句质量需人读样本",
    }
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    out_path = Path(args.out) if args.out else (
        ROOT / "eval" / "results_segment_{}.json".format(time.strftime("%Y%m%d")))
    out_path.write_text(json.dumps(
        {"summary": summary, "records": records}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("已写入", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
