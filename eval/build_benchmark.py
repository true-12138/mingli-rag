# -*- coding: utf-8 -*-
"""把 eval/agent_tasks.jsonl 冻结成一个带版本、可校验的 Benchmark。

产出（eval/tasks/agent_v1/）：

    benchmark.json     版本、冻结时间、cases 的 sha256、dev/holdout 划分
    cases.jsonl        公开题面：id / split / type / name / question / max_steps
    gold/<id>.json     私有判据：required_tools / evidence_books / pass_criteria

为什么要把题面和判据拆开：调提示词的人应该只看得到题目，看不到「必须引用哪本书」。
拆开之后，「看一眼判据再改提示词」就变成一次需要刻意越界的行为，而不是默认状态。

冻结是什么意思：`cases.jsonl` 的 sha256 写进 benchmark.json。之后如果有人改了题目
却没有重新冻结，`run_agent.py` 会在开跑时提示「结果不可与旧 run 直接比」。

用法::

    python eval/build_benchmark.py --check        # 只校验，不写
    python eval/build_benchmark.py --force        # 重新冻结（会换 cases_sha256）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_PATH = ROOT / "eval" / "agent_tasks.jsonl"
OUT_DIR = ROOT / "eval" / "tasks" / "agent_v1"

# 谁进 dev、谁进 holdout。holdout 覆盖四种题型，且刻意避开已知判据有缺陷的 a02 / b04。
# 改这张表等于换 benchmark 版本，必须 --force 并同步更新 benchmark.json 的 note。
SPLIT = {
    "a01": "dev", "a02": "dev", "a03": "holdout", "a04": "dev", "a05": "holdout",
    "b01": "dev", "b02": "dev", "b03": "dev", "b04": "dev", "b05": "holdout",
    "c01": "dev", "c02": "holdout", "c03": "dev",
    "d01": "dev", "d02": "holdout",
}

NOTE = (
    "holdout 自本版本起冻结。此前提示词迭代已看过全部 15 条，因此 v1 的 holdout 分数"
    "只能约束后续改动，不能当作无污染的泛化指标；扩题到 30 条后按 build_benchmark.py "
    "--force 重新冻结。"
)


def _sort(obj):
    """递归按 key 排序，保证同样的输入永远写出同样的字节（sha256 才有意义）。"""
    if isinstance(obj, list):
        return [_sort(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _sort(obj[k]) for k in sorted(obj)}
    return obj


def _git_rev() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True
        ).strip()
    except Exception:
        return "unknown"


def _read_tasks(path: Path = TASKS_PATH) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build(out_dir: Path = OUT_DIR, force: bool = False) -> dict:
    cases: list[dict] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "gold").mkdir(exist_ok=True)

    for task in _read_tasks():
        tid = task["id"]
        if tid not in SPLIT:
            raise SystemExit("任务 {} 没有分到 dev/holdout，先补 SPLIT".format(tid))
        cases.append({
            "id": tid,
            "split": SPLIT[tid],
            "type": task.get("type"),
            "name": task.get("name"),
            "question": task.get("question"),
            "max_steps": task.get("max_steps"),
        })
        gold = {
            "id": tid,
            "required_tools": task.get("required_tools") or [],
            "evidence_books": task.get("evidence_books") or [],
            "pass_criteria": task.get("pass_criteria") or [],
            "why_agentic": task.get("why_agentic"),
            "retrieval_note": task.get("retrieval_note"),
            "baseline_expectation": task.get("baseline_expectation"),
        }
        (out_dir / "gold" / "{}.json".format(tid)).write_text(
            json.dumps(_sort(gold), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    cases.sort(key=lambda c: c["id"])
    cases_text = "\n".join(
        json.dumps(_sort(c), ensure_ascii=False, separators=(",", ":")) for c in cases
    ) + "\n"
    (out_dir / "cases.jsonl").write_text(cases_text, encoding="utf-8")
    digest = hashlib.sha256(cases_text.encode("utf-8")).hexdigest()

    dev = [c["id"] for c in cases if c["split"] == "dev"]
    holdout = [c["id"] for c in cases if c["split"] == "holdout"]
    index = {
        "name": "mingli-agent",
        "version": "agent_v1",
        "status": "frozen",
        "frozen_at": "2026-11-05",
        "frozen_since": _git_rev(),
        "cases_sha256": digest,
        "splits": {"dev": len(dev), "holdout": len(holdout)},
        "dev_cases": dev,
        "holdout_cases": holdout,
        "primary_metric": "pass_rate",
        "note": NOTE,
    }
    (out_dir / "benchmark.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return index


def check(out_dir: Path = OUT_DIR) -> dict:
    """校验当前文件与 benchmark.json 是否一致。返回 {ok, errors, ...}。"""
    index_path = out_dir / "benchmark.json"
    cases_path = out_dir / "cases.jsonl"
    errors: list[str] = []
    if not index_path.exists() or not cases_path.exists():
        return {"ok": False, "errors": ["缺少 benchmark.json 或 cases.jsonl"]}

    index = json.loads(index_path.read_text(encoding="utf-8"))
    actual = hashlib.sha256(cases_path.read_bytes()).hexdigest()
    if actual != index.get("cases_sha256"):
        errors.append(
            "cases.jsonl 的 sha256 与 benchmark.json 不一致：{} != {}（改过题却没有重新冻结）".format(
                actual[:12], (index.get("cases_sha256") or "")[:12])
        )

    cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line]
    ids = {c["id"] for c in cases}
    for split in ("dev", "holdout"):
        want = set(index.get("{}_cases".format(split)) or [])
        got = {c["id"] for c in cases if c.get("split") == split}
        if want != got:
            errors.append("{} 划分不一致：benchmark.json {}，cases.jsonl {}".format(
                split, sorted(want), sorted(got)))
    missing_gold = sorted(i for i in ids if not (out_dir / "gold" / "{}.json".format(i)).exists())
    if missing_gold:
        errors.append("缺少 gold 判据：{}".format(", ".join(missing_gold)))

    return {
        "ok": not errors,
        "errors": errors,
        "version": index.get("version"),
        "status": index.get("status"),
        "cases": len(cases),
        "splits": index.get("splits"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="冻结 Agent Benchmark")
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--force", action="store_true", help="覆盖已有 benchmark（会换 sha256）")
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = ap.parse_args()
    out_dir = Path(args.out)

    if args.check:
        result = check(out_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["ok"] else 1)

    existing = out_dir / "benchmark.json"
    if existing.exists() and not args.force:
        raise SystemExit(
            "{} 已冻结。要重新冻结请加 --force；只是想校验用 --check。".format(existing)
        )
    index = build(out_dir, force=args.force)
    print("已冻结 {}：{} 条（dev {} / holdout {}）".format(
        index["version"], sum(index["splits"].values()),
        index["splits"]["dev"], index["splits"]["holdout"]))
    print("cases_sha256:", index["cases_sha256"])


if __name__ == "__main__":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    main()
