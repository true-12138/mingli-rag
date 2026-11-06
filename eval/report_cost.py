# -*- coding: utf-8 -*-
"""把评测结果和业务库汇总成 P50/P95 + token/成本报表。

数据来源有两类：

1. `eval/results_agent_*.json` / `eval/results_multiturn_*.json`
   —— 每条记录有 `seconds`、`llm_calls`、`usage`（2026-11-06 起采集）；
2. `data/app.sqlite3` 的 `runs` 表
   —— 线上真实请求的 `elapsed_ms` / token；`cost_usd` 目前按设计留 0。

单价不写死：DeepSeek 的价格会变，而且缓存命中/未命中是两档。
用环境变量或参数传入，不填就只报 token、不编金额：

    export MINGLI_INPUT_PRICE_PER_M=0.27
    export MINGLI_CACHED_INPUT_PRICE_PER_M=0.07
    export MINGLI_OUTPUT_PRICE_PER_M=1.10
    python eval/report_cost.py

输出：终端 Markdown + eval/cost_report.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"


def percentile(values: list[float], p: float) -> float | None:
    """nearest-rank 百分位：p=50 时返回中位数，p=95 时返回第 95 百分位。

    样本很小时不做插值——插值会造出一个不存在的延迟值，不如直接取实际观测。
    """
    if not values:
        return None
    if not 0 < p <= 100:
        raise ValueError("p 必须在 (0, 100] 内")
    ordered = sorted(values)
    k = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[k - 1]


def estimate_cost(prompt_tokens: int, cached_tokens: int, completion_tokens: int,
                  input_price: float | None, cached_input_price: float | None,
                  output_price: float | None) -> float | None:
    """按「每百万 token 单价」估算一次调用成本。

    cached_tokens 是 prompt_tokens 的子集：缓存命中部分按 cached_input_price 算，
    其余按 input_price 算。任一必需单价缺失就返回 None，不假装算出了金额。
    """
    if input_price is None or output_price is None:
        return None
    cached = max(0, min(int(cached_tokens or 0), int(prompt_tokens or 0)))
    miss = max(0, int(prompt_tokens or 0) - cached)
    cached_price = input_price if cached_input_price is None else cached_input_price
    return round(
        (miss * input_price + cached * cached_price + int(completion_tokens or 0) * output_price)
        / 1_000_000,
        6,
    )


def load_results(paths: list[Path]) -> list[dict]:
    """把结果文件摊平成记录列表；一个文件一个 tag。"""
    rows = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        summary = data.get("summary") or {}
        tasks = data.get("tasks") or []
        tag = summary.get("tag") or path.stem
        agent = summary.get("agent") or ("multi" if "multi" in tag else "single")
        for rec in tasks:
            usage_data = rec.get("usage") or {}
            judge = rec.get("judge") or {}
            rows.append({
                "file": path.name,
                "tag": tag,
                "agent": agent,
                "id": rec.get("id"),
                "seconds": rec.get("seconds"),
                "passed": bool(judge.get("auto_pass")),
                "llm_calls": rec.get("llm_calls"),
                "prompt_tokens": usage_data.get("prompt_tokens"),
                "completion_tokens": usage_data.get("completion_tokens"),
                "total_tokens": usage_data.get("total_tokens"),
                "cached_tokens": usage_data.get("cached_tokens"),
            })
    return rows


def load_db(path: Path) -> list[dict] | None:
    """读业务库 runs 表；文件不存在或还没建表就返回 None。"""
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            "SELECT elapsed_ms, llm_calls, prompt_tokens, completion_tokens, "
            "total_tokens, cost_usd, status FROM runs"
        )]
        conn.close()
        return rows
    except sqlite3.Error:
        return None


def _sum(rows: list[dict], key: str) -> int:
    return sum(int(r.get(key) or 0) for r in rows)


def _latencies(rows: list[dict], key: str, scale: float = 1.0) -> list[float]:
    return [float(r[key]) / scale for r in rows if isinstance(r.get(key), (int, float))]


def summarize(rows: list[dict], lat_key: str = "seconds", scale: float = 1.0) -> dict:
    lats = _latencies(rows, lat_key, scale)
    prompt = _sum(rows, "prompt_tokens")
    completion = _sum(rows, "completion_tokens")
    cached = _sum(rows, "cached_tokens")
    return {
        "n": len(rows),
        "passed": sum(1 for r in rows if r.get("passed")),
        "p50_seconds": percentile(lats, 50),
        "p95_seconds": percentile(lats, 95),
        "mean_seconds": round(sum(lats) / len(lats), 3) if lats else None,
        "max_seconds": max(lats) if lats else None,
        "llm_calls": _sum(rows, "llm_calls"),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": _sum(rows, "total_tokens") or (prompt + completion),
        "cached_tokens": cached,
        "missing_usage": sum(1 for r in rows if r.get("total_tokens") is None),
    }


def _fmt(v, digits: int = 2) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return ("{:.%df}" % digits).format(v)
    return str(v)


def build_report(result_rows: list[dict], db_rows: list[dict] | None,
                 prices: dict) -> dict:
    by_tag: dict[str, dict] = {}
    for row in result_rows:
        key = row["tag"] if row["tag"] == row["agent"] else "{} ({})".format(
            row["tag"], row["agent"])
        by_tag.setdefault(key, []).append(row)

    tags = []
    for key, rows in sorted(by_tag.items()):
        s = summarize(rows)
        # 整批都没有 usage 时，0 不是「免费」，是「没测到」；报 None 而不是 0。
        if s["missing_usage"] == s["n"] and s["n"]:
            s["cost"] = None
        else:
            s["cost"] = estimate_cost(s["prompt_tokens"], s["cached_tokens"],
                                      s["completion_tokens"], prices["input"],
                                      prices["cached_input"], prices["output"])
        tags.append({"tag": key, **s})

    db = None
    if db_rows is not None:
        db = summarize(db_rows, lat_key="elapsed_ms", scale=1000.0)
        db["stored_cost"] = round(sum(float(r.get("cost_usd") or 0) for r in db_rows), 6)
        db["status"] = {}
        for r in db_rows:
            status = r.get("status") or "unknown"
            db["status"][status] = db["status"].get(status, 0) + 1

    total = summarize(result_rows)
    if total["missing_usage"] == total["n"] and total["n"]:
        total["cost"] = None
    else:
        total["cost"] = estimate_cost(total["prompt_tokens"], total["cached_tokens"],
                                      total["completion_tokens"], prices["input"],
                                      prices["cached_input"], prices["output"])
    return {
        "prices": prices,
        "overall": total,
        "by_tag": tags,
        "db": db,
    }


def render(report: dict) -> str:
    p = report["prices"]
    lines = ["# 成本与延迟报表", ""]
    if p["input"] is None or p["output"] is None:
        lines.append("> 未配置单价，只统计 token，不计算金额。设置 "
                     "`MINGLI_INPUT_PRICE_PER_M` / `MINGLI_OUTPUT_PRICE_PER_M` 后重跑。")
    else:
        lines.append("> 单价（每百万 token）：input={}，cached_input={}，output={}；"
                     "金额币种取决于你填的单价。".format(
                         p["input"], p["cached_input"], p["output"]))
    lines.append("")

    lines += ["## 1. 评测结果文件", ""]
    lines.append("| 来源 | 条数 | 通过 | P50 (s) | P95 (s) | 均值 (s) | LLM 调用 | "
                 "prompt | completion | cached | 估算金额 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for t in report["by_tag"]:
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            t["tag"], t["n"], t["passed"], _fmt(t["p50_seconds"]), _fmt(t["p95_seconds"]),
            _fmt(t["mean_seconds"]), t["llm_calls"], t["prompt_tokens"],
            t["completion_tokens"], t["cached_tokens"], _fmt(t["cost"], 4)))
    o = report["overall"]
    lines.append("| **合计** | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
        o["n"], o["passed"], _fmt(o["p50_seconds"]), _fmt(o["p95_seconds"]),
        _fmt(o["mean_seconds"]), o["llm_calls"], o["prompt_tokens"],
        o["completion_tokens"], o["cached_tokens"], _fmt(o["cost"], 4)))
    if o["missing_usage"]:
        lines.append("")
        lines.append("> {} 条记录没有 `usage`（2026-11-06 之前跑的旧结果），token 合计只覆盖有采集的记录。".format(
            o["missing_usage"]))

    db = report.get("db")
    if db is not None:
        lines += ["", "## 2. 业务库 runs 表", ""]
        lines.append("| 请求数 | P50 (s) | P95 (s) | 均值 (s) | LLM 调用 | "
                     "prompt | completion | 已记 cost_usd | 状态 |")
        lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---|")
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            db["n"], _fmt(db["p50_seconds"]), _fmt(db["p95_seconds"]),
            _fmt(db["mean_seconds"]), db["llm_calls"], db["prompt_tokens"],
            db["completion_tokens"], _fmt(db["stored_cost"], 4),
            json.dumps(db["status"], ensure_ascii=False)))
        lines.append("")
        lines.append("> `runs.cost_usd` 目前按设计写 0（见 `src/db/repo.py::finish_run`），"
                     "成本列以上表的 token 估算为准；等对账单回来再回填。")
    else:
        lines += ["", "## 2. 业务库 runs 表", "", "> 没找到可读的 `data/app.sqlite3`，跳过。"]
    return "\n".join(lines)


def _price(value, fallback=None):
    if value in (None, ""):
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def main() -> None:
    ap = argparse.ArgumentParser(description="P50/P95 + token/成本报表")
    ap.add_argument("--results", nargs="*", default=[],
                    help="结果 JSON；不传则扫 eval/results_agent_*.json 与 results_multiturn_*.json")
    ap.add_argument("--db", default=str(ROOT / "data" / "app.sqlite3"))
    ap.add_argument("--no-db", action="store_true")
    ap.add_argument("--out", default=str(EVAL_DIR / "cost_report.json"))
    ap.add_argument("--input-price", default=os.environ.get("MINGLI_INPUT_PRICE_PER_M"))
    ap.add_argument("--cached-input-price",
                    default=os.environ.get("MINGLI_CACHED_INPUT_PRICE_PER_M"))
    ap.add_argument("--output-price", default=os.environ.get("MINGLI_OUTPUT_PRICE_PER_M"))
    args = ap.parse_args()

    if args.results:
        paths = [Path(p) for p in args.results]
    else:
        paths = sorted(EVAL_DIR.glob("results_agent_*.json")) + \
                sorted(EVAL_DIR.glob("results_multiturn_*.json"))
        paths = [p for p in paths if "rescored" not in p.stem and "selftest" not in p.stem]

    input_price = _price(args.input_price)
    prices = {
        "input": input_price,
        "cached_input": _price(args.cached_input_price, input_price),
        "output": _price(args.output_price),
    }
    result_rows = load_results(paths)
    db_rows = None if args.no_db else load_db(Path(args.db))
    report = build_report(result_rows, db_rows, prices)
    report["sources"] = [p.name for p in paths]
    report["db_path"] = None if args.no_db else args.db

    print(render(report))
    out = Path(args.out)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n写出：{}".format(out))


if __name__ == "__main__":
    main()
