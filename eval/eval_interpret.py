# -*- coding: utf-8 -*-
"""白话释义的忠实度评测：抽段 → 真翻 → 规则检查 + 模型评委。

口径先说清楚：
- **模型评委不是人工标注。** 它和译文出自同一个模型家族，存在「同族偏爱」；
  这里用它把「明显增删」筛出来，结论只能当上界宽松的估计。
- 规则检查（`src/interpret_check.py`）是确定性的，但它只抓三类硬伤，
  漏报远多于误报。
- 所以这份报告的正确读法是：**规则命中率可复现；评委通过率只能参考。**
  真要作为对外数字，得抽 30 段人工逐句对照（见 README 局限 #21）。

用法（key 由环境变量 DEEPSEEK_API_KEY 提供）：
    python eval/eval_interpret.py --n 30 --seed 20261118
    python eval/eval_interpret.py --source unpunct --n 10
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import interpret  # noqa: E402
import interpret_check  # noqa: E402
import rag  # noqa: E402
import usage  # noqa: E402

JUDGE_PROMPT = """你在核对一段古籍原文的现代汉语译文，只判断忠实与否，不评价文笔。

对下面五项各给一个布尔值：
1. translated：译文是否真的把文言译成了现代汉语。只换标点、照抄原句算 false。
2. added：译文是否加入了原文没有的信息（背景、人物关系、因果、吉凶评价、现代类比）。
3. dropped：是否漏掉了原文的转折（虽/然/但）、条件（若/则）或限定（唯/独/仅）。
4. advice：是否把陈述变成了建议、预测、吉凶判断，或出现第二人称劝导。
5. readable：译文是否是通顺的现代汉语（不涉及忠实，只做记录）。

判断以原文为唯一依据。译文比原文长是正常的；只有「原文没有的东西」才算 added。
干支清单、术语名这类内容本身就该照录，不影响 translated 的判断。

只输出 JSON，不要输出 JSON 以外的任何文字。JSON 格式：
{"translated": true, "added": false, "dropped": false, "advice": false, "readable": true,
 "reason": "一句话，指出最具体的一处；全部通过就写「无」"}
"""


def _load_chunks(source: str) -> list[dict]:
    path = ROOT / "data" / "chunks" / ("punct.jsonl" if source == "punct" else "unpunct.jsonl")
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            rows.append({
                "chunk_id": row["chunk_id"],
                "book": row["meta"].get("book") or "",
                "text": row["chunk_text"],
            })
    return rows


def sample(chunks: list[dict], n: int, seed: int, lo: int, hi: int) -> list[dict]:
    """按书轮转抽样：先保证每本书都有机会，再在书内随机。"""
    rng = random.Random(seed)
    by_book: dict[str, list[dict]] = {}
    for row in chunks:
        text = row["text"].strip()
        if lo <= len(text) <= hi:
            by_book.setdefault(row["book"], []).append(row)
    for rows in by_book.values():
        rng.shuffle(rows)
    books = sorted(by_book)
    rng.shuffle(books)
    picked: list[dict] = []
    i = 0
    while len(picked) < n and any(by_book[b] for b in books):
        b = books[i % len(books)]
        if by_book[b]:
            picked.append(by_book[b].pop())
        i += 1
    return picked[:n]


def judge(source: str, translation: str) -> dict:
    user = "【原文】\n{}\n\n【译文】\n{}".format(source, translation)
    raw = rag._chat([
        {"role": "system", "content": JUDGE_PROMPT},
        {"role": "user", "content": user},
    ])
    data = rag._parse_json(raw)
    out = {}
    for key in ("translated", "added", "dropped", "advice", "readable"):
        value = data.get(key)
        out[key] = value if isinstance(value, bool) else None
    out["reason"] = str(data.get("reason") or "")[:200]
    return out


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=20261118)
    ap.add_argument("--source", choices=["punct", "unpunct"], default="punct")
    ap.add_argument("--min-chars", type=int, default=150)
    ap.add_argument("--max-chars", type=int, default=900)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY 未设置：这个脚本要真调模型，不能用假 key 跑。", file=sys.stderr)
        return 2

    # 评测译文不写进线上缓存，避免把跑批结果当成用户请求的结果。
    tmp_cache = Path(tempfile.mkdtemp(prefix="interpret-eval-")) / "cache.jsonl"
    os.environ["MINGLI_INTERPRET_CACHE"] = str(tmp_cache)

    chunks = _load_chunks(args.source)
    rows = sample(chunks, args.n, args.seed, args.min_chars, args.max_chars)
    if not rows:
        print("没有符合长度条件的片段。", file=sys.stderr)
        return 2

    records = []
    for i, row in enumerate(rows, 1):
        text = row["text"].strip()
        usage.reset()
        t0 = time.time()
        record = {"chunk_id": row["chunk_id"], "book": row["book"], "chars": len(text),
                  "text": text}
        try:
            translation = interpret.translate(text)
            record["translation"] = translation
            record["seconds"] = round(time.time() - t0, 2)
            record["usage"] = usage.snapshot()
            record["rules"] = interpret_check.check(
                text, translation, terms=interpret_check.source_terms(text))
        except Exception as exc:  # noqa: BLE001 - 单段失败不终止整批
            record["error"] = "{}: {}".format(type(exc).__name__, str(exc)[:200])
            record["seconds"] = round(time.time() - t0, 2)
            records.append(record)
            print("[{}/{}] chunk {} 失败：{}".format(i, len(rows), row["chunk_id"], record["error"]))
            continue
        try:
            record["judge"] = judge(text, translation)
        except Exception as exc:  # noqa: BLE001
            record["judge"] = {"error": str(exc)[:200]}
        records.append(record)
        hard = interpret_check.hard_rules(record["rules"])
        print("[{}/{}] chunk {} 《{}》 hard={} judge={}".format(
            i, len(rows), row["chunk_id"], row["book"], len(hard),
            record["judge"].get("reason", record["judge"].get("error", ""))[:40]))

    ok = [r for r in records if r.get("translation")]
    rule_hits = {rule: 0 for rule in sorted(interpret_check.HARD_RULES | interpret_check.SOFT_RULES)}
    for r in ok:
        for hit in r["rules"]:
            rule_hits[hit["rule"]] = rule_hits.get(hit["rule"], 0) + 1
    judged = [r for r in ok if isinstance(r.get("judge"), dict) and "added" in r["judge"]]
    fails = [r for r in judged if r["judge"].get("translated") is False
             or r["judge"].get("added") or r["judge"].get("dropped")
             or r["judge"].get("advice")]
    untranslated = [r for r in judged if r["judge"].get("translated") is False]
    unreadable = [r for r in judged if r["judge"].get("readable") is False]
    hard_flagged = [r for r in ok if interpret_check.hard_rules(r["rules"])]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_commit": git_commit(),
        "source": args.source,
        "seed": args.seed,
        "n_requested": args.n,
        "n_translated": len(ok),
        "n_failed": len(records) - len(ok),
        "rule_violations": rule_hits,
        "rule_hard_rate": round(len(hard_flagged) / len(ok), 3) if ok else None,
        "judge_n": len(judged),
        "judge_fail": len(fails),
        "judge_fail_rate": round(len(fails) / len(judged), 3) if judged else None,
        "judge_untranslated": len(untranslated),
        "judge_added": sum(1 for r in judged if r["judge"].get("added")),
        "judge_dropped": sum(1 for r in judged if r["judge"].get("dropped")),
        "judge_advice": sum(1 for r in judged if r["judge"].get("advice")),
        "judge_unreadable": len(unreadable),
        "cache_version": interpret.CACHE_VERSION,
    }
    out = ROOT / "eval" / (args.out or "results_interpret_{}.json".format(
        datetime.now().strftime("%Y%m%d")))
    payload = {"summary": summary, "records": records}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== 汇总 ==")
    for key in ("n_translated", "n_failed", "rule_hard_rate", "judge_n",
                "judge_fail_rate", "judge_untranslated", "judge_added",
                "judge_dropped", "judge_advice"):
        print("{}: {}".format(key, summary[key]))
    print("规则明细: {}".format(json.dumps(rule_hits, ensure_ascii=False)))
    print("写入 {}".format(out.relative_to(ROOT)))
    if fails:
        print("\n== 评委判为不忠实的段落 ==")
        for r in fails[:10]:
            print("- chunk {} 《{}》：{}".format(r["chunk_id"], r["book"],
                                                r["judge"].get("reason", "")[:80]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
