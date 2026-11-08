# -*- coding: utf-8 -*-
"""保持 N 条 SSE 连接，统计建连错误与心跳。

200 连接验收挂在这里，而不是压 `/chat/stream`：后者每条连接都会触发一次
模型调用，200 条就是 200 条并发回答，和「20 并发回答」的验收口径冲突。
本脚本只连 `GET /v1/events`，服务端只发 hello + 心跳，不占回答槽。

用法::

    python loadtest/hold_sse.py --connections 200 --duration 600
    python loadtest/hold_sse.py --connections 200 --duration 600 \
        --url https://your-host/v1/events --token "$MINGLI_API_TOKEN"

输出一行 JSON，可直接贴进压测报告。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import httpx


async def hold_one(client: httpx.AsyncClient, url: str, headers: dict,
                   duration: float, stats: dict) -> dict:
    started = time.perf_counter()
    heartbeats = 0
    try:
        async with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code != 200:
                return {"ok": False, "error": "HTTP %d" % resp.status_code,
                        "connect_ms": None}
            lines = resp.aiter_lines()
            first = await asyncio.wait_for(lines.__anext__(), timeout=10.0)
            connect_ms = (time.perf_counter() - started) * 1000
            if not first.startswith("event: hello"):
                return {"ok": False, "error": "首帧不是 hello", "connect_ms": connect_ms}
            stats["connected"] += 1
            deadline = started + duration
            while True:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break
                try:
                    line = await asyncio.wait_for(lines.__anext__(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                if line.startswith(":"):
                    heartbeats += 1
                    stats["heartbeats"] += 1
            return {"ok": True, "connect_ms": round(connect_ms, 1),
                    "heartbeats": heartbeats}
    except Exception as exc:  # noqa: BLE001 - 压测脚本要汇总所有失败
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc),
                "connect_ms": None}


async def _progress(stats: dict, started: float, interval: float) -> None:
    """进度走 stderr，stdout 只留最后那行 JSON，方便直接重定向到文件。"""
    while True:
        await asyncio.sleep(interval)
        print(
            "[hold] connected=%d/%d heartbeats=%d elapsed=%.0fs" % (
                stats["connected"], stats["target"],
                stats["heartbeats"], time.perf_counter() - started,
            ),
            file=sys.stderr,
            flush=True,
        )


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    idx = min(len(values) - 1, int(round((p / 100) * (len(values) - 1))))
    return round(values[idx], 1)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/v1/events")
    ap.add_argument("--connections", type=int, default=200)
    ap.add_argument("--duration", type=float, default=600.0)
    ap.add_argument("--token", default=None)
    ap.add_argument("--anonymous-id", default="loadtest")
    ap.add_argument("--progress-interval", type=float, default=10.0,
                    help="进度输出间隔（秒），0 表示关闭")
    ap.add_argument("--quiet", action="store_true", help="不输出进度，只在结束时打印 JSON")
    args = ap.parse_args()

    headers = {"X-Anonymous-Id": args.anonymous_id}
    if args.token:
        headers["Authorization"] = "Bearer " + args.token

    limits = httpx.Limits(
        max_connections=args.connections + 10,
        max_keepalive_connections=args.connections + 10,
    )
    timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)
    stats = {"connected": 0, "heartbeats": 0, "target": args.connections}
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        started = time.perf_counter()
        print(
            "[hold] 建立 %d 条连接 -> %s，保持 %.0fs（结束时打印 JSON）" % (
                args.connections, args.url, args.duration),
            file=sys.stderr,
            flush=True,
        )
        progress = None
        if not args.quiet and args.progress_interval > 0:
            progress = asyncio.create_task(
                _progress(stats, started, args.progress_interval)
            )
        try:
            results = await asyncio.gather(
                *(hold_one(client, args.url, headers, args.duration, stats)
                  for _ in range(args.connections))
            )
        finally:
            if progress is not None:
                progress.cancel()
        elapsed = time.perf_counter() - started

    ok = [r for r in results if r["ok"]]
    connects = [r["connect_ms"] for r in ok if r["connect_ms"] is not None]
    errors = [r["error"] for r in results if not r["ok"]]
    summary = {
        "connections": args.connections,
        "ok": len(ok),
        "error_rate": round(len(errors) / max(1, len(results)), 4),
        "duration_s": round(elapsed, 1),
        "connect_ms_p50": pct(connects, 50),
        "connect_ms_p95": pct(connects, 95),
        "heartbeats_total": sum(r.get("heartbeats", 0) for r in ok),
        "errors": errors[:5],
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
