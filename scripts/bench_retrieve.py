# -*- coding: utf-8 -*-
"""单进程内多线程跑 retrieve_one，量「去掉 HTTP 之后」的检索吞吐。

用途是定位瓶颈：`loadtest/retrieve.py` 打的是 HTTP，客户端延迟里混了排队、
线程池、序列化。这里直接在线程里调 `retrieval.retrieve_one`，只剩 Python 层：

    python scripts/bench_retrieve.py --threads 8 --duration 10
    python scripts/bench_retrieve.py --threads 8 --duration 10 --skip-encode
    python scripts/bench_retrieve.py --threads 8 --duration 10 --mode bm25

`--skip-encode` 把 query 编码固定成一个预计算向量（缓存命中的等价物），
用来单独看 BM25 + 点积那一段。两个数一比，就知道该优化编码还是优化 BM25。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import retrieval  # noqa: E402

QUESTIONS = [
    "羊刃分几种？",
    "正官和七杀有什么区别？",
    "什么是食神制杀？",
    "伤官见官为什么不好？",
    "日主强弱怎么判断？",
    "什么是天乙贵人？",
    "三合局和半合局有什么区别？",
    "财星入库是什么意思？",
]


def pct(values, p):
    if not values:
        return None
    values = sorted(values)
    idx = min(len(values) - 1, int(round((p / 100) * (len(values) - 1))))
    return round(values[idx], 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--duration", type=float, default=10.0)
    ap.add_argument("--mode", default="rrf", choices=("rrf", "dense", "bm25"))
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--skip-encode", action="store_true",
                    help="复用同一个 query 向量，只测 BM25 + 点积")
    args = ap.parse_args()

    # 先热一遍：加载模型 / 填缓存，别把冷启动算进吞吐
    warm = retrieval.encode_query(QUESTIONS[0])
    if args.skip_encode:
        retrieval.encode_query = lambda q: warm  # type: ignore[assignment]
    for q in QUESTIONS:
        retrieval.retrieve_one(q, top_k=args.top_k, mode=args.mode)

    latencies: list[float] = []
    lock = threading.Lock()
    stop_at = time.perf_counter() + args.duration

    def worker(idx: int) -> None:
        local: list[float] = []
        n = 0
        while time.perf_counter() < stop_at:
            q = QUESTIONS[(idx * 3 + n) % len(QUESTIONS)]
            n += 1
            started = time.perf_counter()
            retrieval.retrieve_one(q, top_k=args.top_k, mode=args.mode)
            local.append((time.perf_counter() - started) * 1000)
        with lock:
            latencies.extend(local)

    started = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(i,), daemon=True)
               for i in range(args.threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - started

    out = {
        "threads": args.threads,
        "mode": args.mode,
        "skip_encode": bool(args.skip_encode),
        "duration_s": round(elapsed, 1),
        "requests": len(latencies),
        "qps": round(len(latencies) / elapsed, 1),
        "latency_ms_p50": pct(latencies, 50),
        "latency_ms_p95": pct(latencies, 95),
        "latency_ms_mean": round(statistics.fmean(latencies), 1) if latencies else None,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
