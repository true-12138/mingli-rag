# -*- coding: utf-8 -*-
"""检索 QPS 压测：直接打 `POST /retrieve`，不经过 LLM、不经过语义缓存。

`/retrieve` 是同步端点（FastAPI 放线程池），每次都要过一遍向量检索，
所以这里测到的才是「检索链路」的真实吞吐，不会被缓存命中抬高。

同时打印 QPS 与延迟分位；`--min-qps` / `--max-p95` 用来卡验收线，
不达标退出码为 1，方便直接放进脚本。

用法::

    python loadtest/retrieve.py --concurrency 32 --duration 30
    python loadtest/retrieve.py --concurrency 64 --duration 60 \
        --min-qps 100 --max-p95 200
    python loadtest/retrieve.py --base https://your-host --token "$MINGLI_API_TOKEN"

stdout 最后只打印一行 JSON，进度走 stderr。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time

import httpx

QUESTIONS = [
    "羊刃分几种？",
    "正官和七杀有什么区别？",
    "什么是食神制杀？",
    "伤官见官为什么不好？",
    "日主强弱怎么判断？",
    "什么是天乙贵人？",
    "三合局和半合局有什么区别？",
    "财星入库是什么意思？",
    "印绶格适合什么职业？",
    "如何看大运流年？",
    "孤辰寡宿怎么查？",
    "什么是身杀两停？",
    "月令和日支哪个更重要？",
    "七杀有制化和无制化差别在哪？",
    "什么叫财多身弱？",
    "调候用神怎么取？",
    "什么是阴阳差错？",
    "偏印格和正印格的区别？",
    "怎么看婚姻宫？",
    "什么是禄神？",
]


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    idx = min(len(values) - 1, int(round((p / 100) * (len(values) - 1))))
    return round(values[idx], 1)


async def worker(
    idx: int,
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    args: argparse.Namespace,
    stop_at: float,
    stats: dict,
) -> None:
    rng = random.Random(idx)
    n = 0
    while time.perf_counter() < stop_at:
        question = QUESTIONS[rng.randrange(len(QUESTIONS))]
        n += 1
        stats["inflight"] += 1
        started = time.perf_counter()
        try:
            resp = await client.post(
                url,
                json={"question": question, "top_k": args.top_k, "mode": args.mode},
                headers=headers,
            )
            elapsed = (time.perf_counter() - started) * 1000
            if resp.status_code != 200:
                stats["failed"] += 1
                stats["status_counts"][str(resp.status_code)] = (
                    stats["status_counts"].get(str(resp.status_code), 0) + 1
                )
                if len(stats["errors"]) < 5:
                    stats["errors"].append(
                        {"status": resp.status_code, "body": resp.text[:200]}
                    )
            else:
                hits = len(resp.json().get("hits") or [])
                if hits == 0:
                    # 200 但一条没召回：检索算失败，不能计入 QPS
                    stats["failed"] += 1
                    stats["empty"] += 1
                else:
                    stats["ok"] += 1
                    stats["latencies"].append(elapsed)
        except Exception as exc:  # noqa: BLE001 - 压测要汇总所有失败
            stats["failed"] += 1
            if len(stats["errors"]) < 5:
                stats["errors"].append(
                    {"status": None, "body": "%s: %s" % (type(exc).__name__, exc)}
                )
        finally:
            stats["inflight"] -= 1
            stats["completed"] += 1


async def progress(stats: dict, started: float, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        elapsed = time.perf_counter() - started
        print(
            "[retrieve] completed=%d failed=%d qps=%.0f p95=%sms elapsed=%.0fs" % (
                stats["completed"], stats["failed"],
                stats["ok"] / elapsed if elapsed > 0 else 0.0,
                pct(stats["latencies"], 95), elapsed,
            ),
            file=sys.stderr,
            flush=True,
        )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("MINGLI_BASE_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--mode", default="rrf", choices=("dense", "bm25", "rrf"))
    ap.add_argument("--token", default=os.environ.get("MINGLI_API_TOKEN"))
    ap.add_argument("--min-qps", type=float, default=0.0,
                    help="低于该 QPS 退出码为 1（验收线 100）")
    ap.add_argument("--max-p95", type=float, default=0.0,
                    help="P95 超过该毫秒数退出码为 1（验收线 200）")
    ap.add_argument("--progress-interval", type=float, default=5.0)
    ap.add_argument("--quiet", action="store_true", help="不输出进度")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    url = base + "/retrieve"
    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["Authorization"] = "Bearer " + args.token

    limits = httpx.Limits(
        max_connections=args.concurrency + 10,
        max_keepalive_connections=args.concurrency + 10,
    )
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

    stats = {
        "completed": 0, "ok": 0, "failed": 0, "empty": 0,
        "inflight": 0, "latencies": [], "status_counts": {}, "errors": [],
    }

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        try:
            health = await client.get(base + "/health", timeout=5.0)
            if health.status_code != 200:
                print("[retrieve] 预检失败：/health -> HTTP %d" % health.status_code,
                      file=sys.stderr, flush=True)
                return 2
        except Exception as exc:  # noqa: BLE001
            print("[retrieve] 预检失败：连不上 %s（%s）" % (base, exc),
                  file=sys.stderr, flush=True)
            return 2

        print(
            "[retrieve] %d 并发 -> %s，mode=%s top_k=%d，持续 %.0fs" % (
                args.concurrency, url, args.mode, args.top_k, args.duration,
            ),
            file=sys.stderr, flush=True,
        )

        started = time.perf_counter()
        stop_at = started + args.duration
        reporter = None
        if not args.quiet:
            reporter = asyncio.create_task(
                progress(stats, started, args.progress_interval)
            )
        try:
            await asyncio.gather(
                *(worker(i, client, url, headers, args, stop_at, stats)
                  for i in range(args.concurrency))
            )
        finally:
            if reporter is not None:
                reporter.cancel()
            elapsed = time.perf_counter() - started

    lat = stats["latencies"]
    qps = round(stats["ok"] / elapsed, 1) if elapsed > 0 else 0.0
    p95 = pct(lat, 95)
    summary = {
        "concurrency": args.concurrency,
        "duration_s": round(elapsed, 1),
        "mode": args.mode,
        "top_k": args.top_k,
        "requests": stats["completed"],
        "ok": stats["ok"],
        "failed": stats["failed"],
        "empty_hits": stats["empty"],
        "qps": qps,
        "status_counts": stats["status_counts"],
        "latency_ms_p50": pct(lat, 50),
        "latency_ms_p95": p95,
        "latency_ms_p99": pct(lat, 99),
        "errors": stats["errors"],
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)

    if not stats["ok"]:
        return 1
    if args.min_qps and qps < args.min_qps:
        print("[retrieve] FAIL: qps %.1f < %.1f" % (qps, args.min_qps),
              file=sys.stderr, flush=True)
        return 1
    if args.max_p95 and (p95 is None or p95 > args.max_p95):
        print("[retrieve] FAIL: p95 %s > %.1f" % (p95, args.max_p95),
              file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
