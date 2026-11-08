# -*- coding: utf-8 -*-
"""并发回答压测（不依赖 k6）。

和 `k6-smoke.js` 口径一致：N 个 worker 循环发 `POST /chat/stream`，统计首字节
时间（近似首 token）、整条回答耗时、错误率和 429。区别是这里能直接看到 SSE
事件内容，能区分「200 但没收到 done」这种假成功。

默认带 `X-No-Cache: 1`：压测要测的是模型并发，不能让语义缓存把重复题全接住。
想测缓存收益时加 `--cache`。

用法::

    python loadtest/answers.py --concurrency 20 --duration 300
    python loadtest/answers.py --concurrency 20 --duration 300 \
        --base https://your-host --token "$MINGLI_API_TOKEN"
    python loadtest/answers.py --concurrency 20 --duration 60 --cache

stdout 最后只打印一行 JSON，进度走 stderr。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
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
]


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    idx = min(len(values) - 1, int(round((p / 100) * (len(values) - 1))))
    return round(values[idx], 1)


async def one_request(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    question: str,
    mode: str,
) -> dict:
    started = time.perf_counter()
    ttfb = None
    tail = ""
    done = False
    error_event = False
    try:
        async with client.stream(
            "POST",
            url,
            json={"question": question, "mode": mode, "top_k": 5},
            headers=headers,
        ) as resp:
            if resp.status_code != 200:
                return {
                    "status": resp.status_code,
                    "ok": False,
                    "retry_after": resp.headers.get("Retry-After"),
                    "ttfb_ms": None,
                    "total_ms": round((time.perf_counter() - started) * 1000, 1),
                    "error": "HTTP %d" % resp.status_code,
                }
            async for chunk in resp.aiter_bytes():
                now = time.perf_counter()
                if ttfb is None and chunk:
                    ttfb = (now - started) * 1000
                text = chunk.decode("utf-8", "ignore")
                scan = tail + text
                if "event: done" in scan:
                    done = True
                if "event: error" in scan:
                    error_event = True
                tail = scan[-64:]
    except Exception as exc:  # noqa: BLE001 - 压测要汇总所有失败
        return {
            "status": None,
            "ok": False,
            "ttfb_ms": None,
            "total_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": "%s: %s" % (type(exc).__name__, exc),
        }

    total = (time.perf_counter() - started) * 1000
    return {
        "status": 200,
        "ok": done and not error_event,
        "ttfb_ms": ttfb,
        "total_ms": round(total, 1),
        "done": done,
        "error_event": error_event,
        "error": None if done and not error_event else "缺少 done 或收到 error 事件",
    }


async def worker(
    idx: int,
    client: httpx.AsyncClient,
    url: str,
    base_headers: dict,
    args: argparse.Namespace,
    stop_at: float,
    stats: dict,
) -> None:
    headers = dict(base_headers)
    headers["X-Anonymous-Id"] = "lt-%d" % idx
    n = 0
    while time.perf_counter() < stop_at:
        question = QUESTIONS[(idx * 7 + n) % len(QUESTIONS)]
        n += 1
        stats["inflight"] += 1
        result = await one_request(client, url, headers, question, args.mode)
        stats["inflight"] -= 1
        stats["results"].append(result)
        stats["completed"] += 1
        if not result["ok"]:
            stats["failed"] += 1
        if result.get("status") == 429:
            wait = 1.0
            try:
                wait = float(result.get("retry_after") or 1.0)
            except (TypeError, ValueError):
                pass
            await asyncio.sleep(min(wait, 5.0))
        elif not result["ok"]:
            # 连不上/超时时别空转；否则 20 个 worker 会瞬间打出几万次重试
            await asyncio.sleep(0.5)


async def progress(stats: dict, started: float, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        results = stats["results"]
        ttfb = [r["ttfb_ms"] for r in results if r.get("ttfb_ms") is not None]
        print(
            "[answers] completed=%d failed=%d inflight=%d p95_ttfb=%sms elapsed=%.0fs" % (
                stats["completed"], stats["failed"], stats["inflight"],
                pct(ttfb, 95), time.perf_counter() - started,
            ),
            file=sys.stderr,
            flush=True,
        )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("MINGLI_BASE_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--duration", type=float, default=120.0)
    ap.add_argument("--mode", default="rag", choices=("rag", "agent", "multi"))
    ap.add_argument("--token", default=os.environ.get("MINGLI_API_TOKEN"))
    ap.add_argument("--cache", action="store_true", help="允许命中语义缓存（默认绕过）")
    ap.add_argument("--request-timeout", type=float, default=180.0)
    ap.add_argument("--progress-interval", type=float, default=10.0)
    ap.add_argument("--quiet", action="store_true", help="不输出进度")
    ap.add_argument("--max-error-rate", type=float, default=0.01,
                    help="错误率超过该值退出码为 1")
    args = ap.parse_args()

    url = args.base.rstrip("/") + "/chat/stream"
    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["Authorization"] = "Bearer " + args.token
    if not args.cache:
        headers["X-No-Cache"] = "1"

    limits = httpx.Limits(
        max_connections=args.concurrency + 10,
        max_keepalive_connections=args.concurrency + 10,
    )
    timeout = httpx.Timeout(
        connect=10.0, read=args.request_timeout, write=10.0, pool=10.0
    )

    stats = {"completed": 0, "failed": 0, "inflight": 0, "results": []}
    stop_at = time.perf_counter() + args.duration
    started = time.perf_counter()
    print(
        "[answers] %d 并发 -> %s，持续 %.0fs，缓存=%s" % (
            args.concurrency, url, args.duration,
            "开" if args.cache else "关（X-No-Cache: 1）",
        ),
        file=sys.stderr,
        flush=True,
    )

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        # 预检：连不上就明确报错，别让 20 个 worker 空转出几万条 ConnectError
        try:
            health = await client.get(args.base.rstrip("/") + "/health", timeout=5.0)
            if health.status_code != 200:
                print(
                    "[answers] 预检失败：GET /health -> HTTP %d" % health.status_code,
                    file=sys.stderr,
                    flush=True,
                )
                return 2
        except Exception as exc:  # noqa: BLE001
            print(
                "[answers] 预检失败：连不上 %s（%s）。先确认 API 已启动："
                "curl %s/health" % (
                    args.base, exc, args.base.rstrip("/"),
                ),
                file=sys.stderr,
                flush=True,
            )
            return 2

        if not args.quiet:
            print("[answers] 预检通过：/health 200", file=sys.stderr, flush=True)
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

    results = stats["results"]
    ok = [r for r in results if r["ok"]]
    ttfb = [r["ttfb_ms"] for r in ok if r.get("ttfb_ms") is not None]
    total = [r["total_ms"] for r in ok]
    status_counts: dict[str, int] = {}
    for r in results:
        key = str(r.get("status"))
        status_counts[key] = status_counts.get(key, 0) + 1
    throttled = status_counts.get("429", 0)
    error_rate = round((len(results) - len(ok)) / max(1, len(results)), 4)

    summary = {
        "concurrency": args.concurrency,
        "duration_s": round(elapsed, 1),
        "requests": len(results),
        "ok": len(ok),
        "error_rate": error_rate,
        "status_counts": status_counts,
        "throttled_429": throttled,
        "ttfb_ms_p50": pct(ttfb, 50),
        "ttfb_ms_p95": pct(ttfb, 95),
        "total_ms_p50": pct(total, 50),
        "total_ms_p95": pct(total, 95),
        "error_kinds": {
            # 服务端明确回了 event: error（上游 LLM / 内部异常）
            "error_event": sum(1 for r in results if r.get("error_event")),
            # 200 但流结束得干干净净，没有 done 也没有 error：连接被截断
            "stream_truncated": sum(
                1 for r in results
                if r.get("status") == 200
                and not r.get("done")
                and not r.get("error_event")
            ),
            "http": sum(
                1 for r in results
                if r.get("status") is not None and r.get("status") != 200
            ),
        },
        "errors": [
            {
                "status": r.get("status"),
                "done": r.get("done"),
                "error_event": r.get("error_event"),
                "error": r.get("error"),
            }
            for r in results if not r["ok"]
        ][:5],
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if not results:
        return 1
    return 0 if error_rate <= args.max_error_rate else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
