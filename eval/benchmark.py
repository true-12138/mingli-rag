# -*- coding: utf-8 -*-
"""读一个冻结的 Benchmark：公开题面 + 私有判据。

评测脚本只通过这里拿任务，不再直接读 `agent_tasks.jsonl`。这样「题目有没有被改过」
和「这次结果能不能和旧 run 比」就是同一个问题——benchmark 的 sha256。

用法::

    from benchmark import load_index, load_tasks, verify

    bench = load_index()                     # benchmark.json 的内容
    tasks = load_tasks(split="holdout")      # 合并后的完整任务（含判据）
    verify()["ok"]                           # 题面是否与冻结时一致
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "eval" / "tasks" / "agent_v1"
LEGACY_PATH = ROOT / "eval" / "agent_tasks.jsonl"


def _dir(path: Path | str | None) -> Path:
    return Path(path) if path else DEFAULT_DIR


def available(path: Path | str | None = None) -> bool:
    return (_dir(path) / "benchmark.json").exists()


def load_index(path: Path | str | None = None) -> dict:
    return json.loads((_dir(path) / "benchmark.json").read_text(encoding="utf-8"))


def cases_sha256(path: Path | str | None = None) -> str:
    return hashlib.sha256((_dir(path) / "cases.jsonl").read_bytes()).hexdigest()


def verify(path: Path | str | None = None) -> dict:
    """题面与冻结记录是否一致。不一致时，结果不应与旧 run 直接比较。"""
    base = _dir(path)
    if not (base / "benchmark.json").exists():
        return {"ok": True, "frozen": False, "version": None,
                "note": "没有冻结 benchmark，使用 legacy agent_tasks.jsonl"}
    index = load_index(base)
    actual = cases_sha256(base)
    ok = actual == index.get("cases_sha256")
    return {
        "ok": ok,
        "frozen": True,
        "version": index.get("version"),
        "status": index.get("status"),
        "expected_sha256": index.get("cases_sha256"),
        "actual_sha256": actual,
        "splits": index.get("splits"),
        "error": None if ok else "cases.jsonl 与 benchmark.json 的 sha256 不一致（题面改过但未重新冻结）",
    }


def load_cases(path: Path | str | None = None, split: str = "all") -> list[dict]:
    """只读公开题面。split 取 all / dev / holdout。"""
    base = _dir(path)
    if not (base / "cases.jsonl").exists():
        return []
    rows = [
        json.loads(line)
        for line in (base / "cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if split and split != "all":
        rows = [r for r in rows if r.get("split") == split]
    return rows


def load_gold(case_id: str, path: Path | str | None = None) -> dict:
    gold = _dir(path) / "gold" / "{}.json".format(case_id)
    if not gold.exists():
        raise FileNotFoundError("缺少私有判据：{}".format(gold))
    return json.loads(gold.read_text(encoding="utf-8"))


def load_tasks(path: Path | str | None = None, split: str = "all") -> list[dict]:
    """公开题面与私有判据合并成 run_agent 认识的任务结构。

    合并后的字段与旧 agent_tasks.jsonl 兼容，所以 auto_judge 不用改。
    """
    base = _dir(path)
    if not (base / "cases.jsonl").exists():
        return _load_legacy(split)
    tasks = []
    for case in load_cases(base, split=split):
        task = dict(case)
        task.update(load_gold(case["id"], base))
        tasks.append(task)
    return tasks


def _load_legacy(split: str = "all") -> list[dict]:
    if not LEGACY_PATH.exists():
        return []
    tasks = [
        json.loads(line)
        for line in LEGACY_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # legacy 文件没有 split 字段；只有 all 能完整返回，其余视为未划分
    return tasks if split in ("all", "") else []


if __name__ == "__main__":
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
    for split in ("dev", "holdout", "all"):
        print("{:8} {}".format(split, len(load_cases(split=split))))
