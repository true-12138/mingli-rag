# -*- coding: utf-8 -*-
"""按固定间隔采样 API 进程树的总 RSS，用于长时间稳定性测试。

为什么要按进程树采样：`MINGLI_WORKERS=2` 时 master 下面还有 worker 子进程，
只看 `pgrep` 拿到的一个 PID 会漏掉一半内存。这个脚本从所有匹配的命令行出发，
沿 `/proc/<pid>/task/<tid>/children` 递归收集子进程，再累加 VmRSS。

用法::

    python loadtest/rss_sampler.py --duration 1800 --interval 30 > rss.csv

输出 CSV：`elapsed_s,timestamp,processes,total_rss_mb,roots`
进度与错误写 stderr（设置 `--quiet` 可关闭）。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _cmdline(pid: int) -> str:
    try:
        raw = Path("/proc/%d/cmdline" % pid).read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", "ignore").strip()


def _children(pid: int) -> list[int]:
    out: list[int] = []
    try:
        tasks = Path("/proc/%d/task" % pid).iterdir()
    except OSError:
        return out
    for task in tasks:
        try:
            text = (task / "children").read_text().strip()
        except OSError:
            continue
        for item in text.split():
            try:
                out.append(int(item))
            except ValueError:
                pass
    return out


def _tree(pid: int) -> set[int]:
    seen: set[int] = set()
    stack = [pid]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(_children(current))
    return seen


def _rss_kb(pid: int) -> int:
    try:
        text = Path("/proc/%d/status" % pid).read_text()
    except OSError:
        return 0
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return 0
    return 0


def _roots(pattern: str) -> list[int]:
    roots: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pattern and pattern in _cmdline(pid):
            roots.append(pid)
    return roots


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", default="src/api.py", help="匹配 master 进程的命令行片段")
    ap.add_argument("--duration", type=float, default=1800.0, help="采样总时长（秒）")
    ap.add_argument("--interval", type=float, default=30.0, help="采样间隔（秒）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    started = time.time()
    print("elapsed_s,timestamp,processes,total_rss_mb,roots", flush=True)
    while True:
        elapsed = time.time() - started
        roots = _roots(args.pattern)
        pids: set[int] = set()
        for root in roots:
            pids |= _tree(root)
        total_kb = sum(_rss_kb(pid) for pid in pids)
        print(
            "%.0f,%s,%d,%.1f,%s" % (
                elapsed,
                time.strftime("%Y-%m-%dT%H:%M:%S"),
                len(pids),
                total_kb / 1024.0,
                "|".join(str(r) for r in roots),
            ),
            flush=True,
        )
        if not args.quiet:
            print(
                "[rss] elapsed=%.0fs processes=%d total=%.1fMB roots=%s" % (
                    elapsed, len(pids), total_kb / 1024.0, roots,
                ),
                file=sys.stderr,
                flush=True,
            )
        if elapsed >= args.duration:
            break
        time.sleep(max(1.0, args.interval))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
