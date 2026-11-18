# -*- coding: utf-8 -*-
"""路由评测：同一批题分别强制走小模型、大模型、自动路由。

为什么要有这份评测
------------------
规则路由（src/router.py）的每条加减分都是假设：跨书比较小模型压不住、
单跳释义大模型是浪费。假设要用同一批题上的「引用命中 + 拒答是否正确 +
花费」来验，不能只看响应里写了哪个档位。

三个臂
------
- small：强制小模型，等价于路由上线前的行为基线；
- large：强制大模型，是质量上界，也是成本上界；
- auto：规则路由 + 输出不可用时升级，是真正要上线的配置。

指标口径
--------
- 可答题「引用命中」：`citations_chunk_ids` 里至少有一条在 `gold_chunk_ids`
  中。只看最终引用，不看召回，因为用户看到的是答案里挂的出处。
- 语料外「正确拒答」：`can_answer is False`。
- 无效输出：JSON 无法解析，或声称能答却没有有效引用。
- 成本：按每次尝试的 usage 分别记到 small / large 单价上；改写问题的调用
  归到小模型单价。默认单价是 DeepSeek 非高峰价，`--peak` 翻倍，也可用
  环境变量逐项覆盖（见 PRICES）。

用法（key 由环境变量 DEEPSEEK_API_KEY 提供）：
    python eval/eval_router.py                 # 30 题 × 3 臂
    python eval/eval_router.py --limit 6       # 先冒烟
    python eval/eval_router.py --peak          # 按高峰价估
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import rag  # noqa: E402
import router  # noqa: E402
import usage  # noqa: E402

ARMS = ("small", "large", "auto")

# DeepSeek 公开价，USD / 1M token，非高峰。高峰（UTC 01–04、06–10 工作日）翻倍。
# 价格会变：用环境变量覆盖，别把这里当成长期合同。
PRICES = {
    "small": {"input": 0.15, "cached_input": 0.003, "output": 0.60},
    "large": {"input": 0.66, "cached_input": 0.022, "output": 1.98},
}


def resolve_prices(peak: bool) -> dict:
    """环境变量优先；没有就用内置价，`--peak` 对内置价翻倍。"""
    out = {}
    for tier, base in PRICES.items():
        prefix = "MINGLI_PRICE_{}_".format(tier.upper())
        price = {}
        for key, env_key in (
            ("input", "INPUT"),
            ("cached_input", "CACHED_INPUT"),
            ("output", "OUTPUT"),
        ):
            raw = os.environ.get(prefix + env_key)
            if raw:
                try:
                    price[key] = float(raw)
                    continue
                except ValueError:
                    pass
            price[key] = round(base[key] * (2 if peak else 1), 6)
        out[tier] = price
    return out


def estimate_cost(usage_d: dict | None, price: dict) -> float:
    """一次尝试的成本；usage 缺失时返回 0，并在汇总里单列缺失数。"""
    if not usage_d:
        return 0.0
    prompt = int(usage_d.get("prompt_tokens") or 0)
    cached = int(usage_d.get("cached_tokens") or 0)
    completion = int(usage_d.get("completion_tokens") or 0)
    cached = max(0, min(cached, prompt))
    return (
        (prompt - cached) * price["input"]
        + cached * price["cached_input"]
        + completion * price["output"]
    ) / 1_000_000


def record_cost(rec: dict, prices: dict) -> float:
    """一条记录的总成本：各尝试按档位计费，改写等辅助调用按小模型计费。"""
    total = 0.0
    attempts_usage = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
    for attempt in rec.get("attempts") or []:
        used = attempt.get("usage") or {}
        total += estimate_cost(used, prices.get(attempt.get("tier"), prices["small"]))
        for key in attempts_usage:
            attempts_usage[key] += int(used.get(key) or 0)
    overall = rec.get("usage") or {}
    aux = {
        key: max(0, int(overall.get(key) or 0) - attempts_usage[key])
        for key in attempts_usage
    }
    total += estimate_cost(aux, prices["small"])
    rec["cost_usd"] = round(total, 6)
    return rec["cost_usd"]


def load_questions(path: Path, limit: int = 0) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            q = json.loads(line)
            if limit and len(rows) >= limit:
                break
            rows.append(q)
    return rows


def run_one(q: dict, arm: str, *, top_k: int, mode: str) -> dict:
    usage.reset()
    t0 = time.time()
    rec = {
        "id": q["id"],
        "answerable": bool(q["answerable"]),
        "category": q.get("category", ""),
        "question": q["question"],
        "arm": arm,
        "gold_chunk_ids": q.get("gold_chunk_ids") or [],
    }
    try:
        result = rag.answer(q["question"], top_k=top_k, mode=mode, tier=arm)
        rec["seconds"] = round(time.time() - t0, 2)
        rec["usage"] = usage.snapshot()
        route = result.get("route") or {}
        attempts = route.get("attempts") or []
        rec.update({
            "can_answer": result.get("can_answer"),
            "answer": result.get("answer") or "",
            "refusal_reason": result.get("refusal_reason"),
            "invalid_output": bool(result.get("invalid_output")),
            "citations_chunk_ids": result.get("citations_chunk_ids") or [],
            "retrieved_chunk_ids": result.get("retrieved_chunk_ids") or [],
            "error": result.get("error"),
            "llm_calls": result.get("llm_calls"),
            "route": {
                "tier": route.get("tier"),
                "model": route.get("model"),
                "reason": route.get("reason"),
                "score": route.get("score"),
                "signals": route.get("signals") or [],
                "forced": route.get("forced"),
                "escalated": route.get("escalated"),
                "escalation_reason": route.get("escalation_reason"),
                "initial_tier": route.get("initial_tier"),
            },
            "attempts": [
                {
                    "tier": a.get("tier"),
                    "model": a.get("model"),
                    "ok": a.get("ok"),
                    "usage": a.get("usage"),
                }
                for a in attempts
            ],
        })
        gold = set(rec["gold_chunk_ids"])
        rec["gold_hit"] = bool(gold & set(rec["citations_chunk_ids"]))
    except Exception as exc:  # noqa: BLE001 - 单题失败不终止整批
        rec["seconds"] = round(time.time() - t0, 2)
        rec["usage"] = usage.snapshot()
        rec["error"] = "{}: {}".format(type(exc).__name__, str(exc)[:200])
        rec["can_answer"] = None
        rec["invalid_output"] = True
        rec["gold_hit"] = False
        rec["citations_chunk_ids"] = []
        rec["attempts"] = []
        rec["route"] = {}
    return rec


def is_good(rec: dict) -> bool:
    """这一题在这个臂下是否算答对。

    可答：给出答案且引用命中 gold；不可答：明确拒答。
    无效输出、JSON 失败都算错。
    """
    if rec.get("answerable"):
        return rec.get("can_answer") is True and bool(rec.get("gold_hit"))
    return rec.get("can_answer") is False


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = max(1, -(-int(p * len(ordered)) // 100))  # ceil(p/100 * n)
    return ordered[min(k, len(ordered)) - 1]


def summarize(records: list[dict]) -> dict:
    answerable = [r for r in records if r["answerable"]]
    outside = [r for r in records if not r["answerable"]]
    seconds = [r["seconds"] for r in records if isinstance(r.get("seconds"), (int, float))]
    return {
        "n": len(records),
        "answerable_n": len(answerable),
        "outside_n": len(outside),
        "good_n": sum(1 for r in records if is_good(r)),
        "good_rate": round(sum(1 for r in records if is_good(r)) / len(records), 3)
        if records else None,
        "answered_rate": round(
            sum(1 for r in answerable if r.get("can_answer") is True) / len(answerable), 3
        ) if answerable else None,
        "gold_hit_rate": round(
            sum(1 for r in answerable if r.get("gold_hit")) / len(answerable), 3
        ) if answerable else None,
        "refusal_rate": round(
            sum(1 for r in outside if r.get("can_answer") is False) / len(outside), 3
        ) if outside else None,
        "invalid_output": sum(1 for r in records if r.get("invalid_output")),
        "json_fail": sum(1 for r in records if r.get("can_answer") is None),
        "errors": sum(1 for r in records if r.get("error")),
        "escalated": sum(
            1 for r in records if (r.get("route") or {}).get("escalated")
        ),
        "llm_calls": sum(int(r.get("llm_calls") or 0) for r in records),
        "prompt_tokens": sum(int((r.get("usage") or {}).get("prompt_tokens") or 0)
                             for r in records),
        "completion_tokens": sum(int((r.get("usage") or {}).get("completion_tokens") or 0)
                                 for r in records),
        "cached_tokens": sum(int((r.get("usage") or {}).get("cached_tokens") or 0)
                             for r in records),
        "p50_seconds": percentile(seconds, 50),
        "p95_seconds": percentile(seconds, 95),
        "cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in records), 6),
    }


def compare_arms(by_arm: dict[str, list[dict]]) -> dict:
    """自动路由相对「每题都知道该用哪档」的差距，以及选档倾向。"""
    index = {arm: {r["id"]: r for r in rows} for arm, rows in by_arm.items()}
    ids = sorted(set(index["small"]) & set(index["large"]) & set(index["auto"]))
    buckets = {"small_only": [], "large_only": [], "both_good": [], "both_bad": []}
    auto_miss = []
    for qid in ids:
        s_good = is_good(index["small"][qid])
        l_good = is_good(index["large"][qid])
        a = index["auto"][qid]
        key = (
            "both_good" if s_good and l_good
            else "both_bad" if not s_good and not l_good
            else "small_only" if s_good
            else "large_only"
        )
        buckets[key].append(qid)
        if not is_good(a) and (s_good or l_good):
            auto_miss.append({
                "id": qid,
                "auto_tier": (a.get("route") or {}).get("tier"),
                "auto_reason": (a.get("route") or {}).get("reason"),
            })
    auto_tiers = {}
    for qid in ids:
        tier = (index["auto"][qid].get("route") or {}).get("tier") or "unknown"
        auto_tiers[tier] = auto_tiers.get(tier, 0) + 1
    return {
        "n": len(ids),
        "small_only": buckets["small_only"],
        "large_only": buckets["large_only"],
        "both_good": len(buckets["both_good"]),
        "both_bad": len(buckets["both_bad"]),
        "auto_miss": auto_miss,
        "auto_tiers": auto_tiers,
    }


def format_report(payload: dict) -> str:
    s = payload["summary"]
    lines = [
        "# 路由评测",
        "",
        "- 时间：{}".format(s["generated_at"]),
        "- 题目：{}（可答 {} / 语料外 {}）".format(
            s["n"], payload["by_arm"]["small"]["answerable_n"],
            payload["by_arm"]["small"]["outside_n"]),
        "- 小模型：`{}`｜大模型：`{}`".format(s["small_model"], s["large_model"]),
        "- 单价（USD/1M，{}）：small in {} / cached {} / out {}；"
        "large in {} / cached {} / out {}".format(
            s["price_profile"],
            s["prices"]["small"]["input"], s["prices"]["small"]["cached_input"],
            s["prices"]["small"]["output"],
            s["prices"]["large"]["input"], s["prices"]["large"]["cached_input"],
            s["prices"]["large"]["output"]),
        "",
        "| 臂 | 答对 | 可答·给出答案 | 可答·引用命中 | 语料外·拒答 | 无效输出 | 升级 | 均次调用 | P50 | P95 | 成本 (USD) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm in ARMS:
        a = payload["by_arm"][arm]
        lines.append(
            "| {arm} | {good}/{n} | {ans} | {hit} | {ref} | {inv} | {esc} | {calls} | "
            "{p50}s | {p95}s | ${cost} |".format(
                arm=arm, good=a["good_n"], n=a["n"],
                ans=_fmt_rate(a["answered_rate"]), hit=_fmt_rate(a["gold_hit_rate"]),
                ref=_fmt_rate(a["refusal_rate"]), inv=a["invalid_output"],
                esc=a["escalated"],
                calls=round(a["llm_calls"] / a["n"], 2) if a["n"] else 0,
                p50=_fmt_num(a["p50_seconds"]), p95=_fmt_num(a["p95_seconds"]),
                cost="{:.4f}".format(a["cost_usd"]),
            )
        )
    c = payload["comparison"]
    lines += [
        "",
        "## 两档模型的分工验证",
        "",
        "- 只有小模型答对：{} 题 {}".format(len(c["small_only"]), _ids(c["small_only"])),
        "- 只有大模型答对：{} 题 {}".format(len(c["large_only"]), _ids(c["large_only"])),
        "- 两档都答对：{} 题；都答错：{} 题".format(c["both_good"], c["both_bad"]),
        "- 自动路由选档：{}".format(
            "，".join("{} {} 题".format(k, v) for k, v in sorted(c["auto_tiers"].items()))),
        "- 自动路由漏掉（至少一档能答对而它没答对）：{} 题".format(len(c["auto_miss"])),
    ]
    for miss in c["auto_miss"]:
        lines.append("  - {}：{}（{}）".format(
            miss["id"], miss["auto_tier"], miss["auto_reason"]))
    lines += [
        "",
        "## 逐题明细",
        "",
        "| 题 | 类型 | small | large | auto 档位 | auto 结果 |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    index = {arm: {r["id"]: r for r in rows} for arm, rows in payload["records"].items()}
    for qid in sorted(index["auto"]):
        row = index["auto"][qid]
        lines.append("| {} | {} | {} | {} | {} | {} |".format(
            qid, row["category"],
            _mark(index["small"][qid]), _mark(index["large"][qid]),
            (row.get("route") or {}).get("tier") or "—",
            "✓" if is_good(row) else "✗",
        ))
    lines += [
        "",
        "## 读法",
        "",
        "- 「答对」对可答题要求引用命中 gold，对语料外要求明确拒答；"
        "它比「给出了答案」严格，适合比较质量。",
        "- auto 的成本若明显低于 large、答对数接近，路由就站得住；"
        "若 small_only 和 large_only 都很少，说明这个阈值分不出难度，应调规则。",
        "- 「无效输出」包含 JSON 失败和声称能答却无有效引用；auto 的升级只处理这一类。",
        "",
    ]
    return "\n".join(lines)


def _fmt_rate(v) -> str:
    return "—" if v is None else "{:.0%}".format(v)


def _fmt_num(v) -> str:
    return "—" if v is None else "{:.1f}".format(v)


def _mark(rec: dict) -> str:
    if is_good(rec):
        return "✓"
    if rec.get("can_answer") is False:
        return "拒"
    if rec.get("can_answer") is None:
        return "×"
    return "✗"


def _ids(ids: list[str]) -> str:
    return "、".join(ids) if ids else "（无）"


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=str(ROOT / "eval" / "questions.jsonl"))
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题，用于冒烟")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--mode", default="rrf")
    ap.add_argument("--peak", action="store_true", help="按高峰价估算")
    ap.add_argument("--out-json", default="")
    ap.add_argument("--out-md", default="")
    args = ap.parse_args()

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY 未设置：这个脚本要真调模型，不能用假 key 跑。",
              file=sys.stderr)
        return 2

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    unknown = [a for a in arms if a not in ARMS]
    if unknown:
        print("未知臂：{}（可选 {}）".format(", ".join(unknown), ", ".join(ARMS)),
              file=sys.stderr)
        return 2

    prices = resolve_prices(args.peak)
    small_model, large_model = router._models()
    if small_model == large_model and set(arms) & {"small", "large", "auto"}:
        print("小模型和大模型名相同（{}）：这个部署没有两档可比。".format(small_model),
              file=sys.stderr)
        return 2

    questions = load_questions(Path(args.questions), args.limit)
    if not questions:
        print("没有题目。", file=sys.stderr)
        return 2

    # 第一次检索会顺带把 BGE-M3 载进内存（本机 CPU 约 70s，CUDA 更久）。
    # 不预热的话这笔时间会算到第一题的耗时上，把 P95 拉成假数字。
    t_warm = time.time()
    try:
        rag.retrieve_one("预热", top_k=1)
    except Exception as exc:  # noqa: BLE001 - 预热失败不拦整批
        print("[warn] 检索预热失败：{}: {}".format(type(exc).__name__, exc),
              file=sys.stderr)
    print("检索预热 {:.1f}s".format(time.time() - t_warm))

    by_arm: dict[str, list[dict]] = {}
    for arm in arms:
        records = []
        for i, q in enumerate(questions, 1):
            rec = run_one(q, arm, top_k=args.top_k, mode=args.mode)
            record_cost(rec, prices)
            records.append(rec)
            print("[{} {}/{}] {} {} {} 题 {}s ${}".format(
                arm, i, len(questions), q["id"],
                "✓" if is_good(rec) else "✗",
                (rec.get("route") or {}).get("tier") or "—",
                rec.get("seconds"), rec.get("cost_usd")))
        by_arm[arm] = records

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_commit": git_commit(),
        "n": len(questions),
        "arms": arms,
        "top_k": args.top_k,
        "retrieval_mode": args.mode,
        "small_model": small_model,
        "large_model": large_model,
        "price_profile": "peak" if args.peak else "offpeak",
        "prices": prices,
    }
    payload = {
        "summary": summary,
        "by_arm": {arm: summarize(rows) for arm, rows in by_arm.items()},
        "records": by_arm,
    }
    if set(ARMS) <= set(arms):
        payload["comparison"] = compare_arms(by_arm)
    else:
        payload["comparison"] = None

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_json = Path(args.out_json) if args.out_json else (
        ROOT / "eval" / "results_router_{}.json".format(stamp))
    out_md = Path(args.out_md) if args.out_md else (
        ROOT / "eval" / "router_report_{}.md".format(stamp))
    out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== 汇总 ==")
    for arm in arms:
        a = payload["by_arm"][arm]
        print("{:<6} 答对 {}/{}｜引用命中 {}｜语料外拒答 {}｜无效 {}｜升级 {}｜"
              "P50 {}s｜${:.4f}".format(
                  arm, a["good_n"], a["n"], _fmt_rate(a["gold_hit_rate"]),
                  _fmt_rate(a["refusal_rate"]), a["invalid_output"], a["escalated"],
                  _fmt_num(a["p50_seconds"]), a["cost_usd"]))
    if payload["comparison"]:
        c = payload["comparison"]
        print("只有小模型答对：{}；只有大模型答对：{}；自动漏掉：{} 题".format(
            _ids(c["small_only"]), _ids(c["large_only"]),
            _ids([m["id"] for m in c["auto_miss"]])))
        out_md.write_text(format_report(payload), encoding="utf-8")
        print("报告：{}".format(out_md))
    print("明细：{}".format(out_json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
