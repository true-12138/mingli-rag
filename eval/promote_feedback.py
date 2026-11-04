# -*- coding: utf-8 -*-
"""把线上差评晋升成回归用例。

流程：
    POST /v1/runs/{run_id}/feedback  (rating=-1)
        -> feedback 表
        -> 本脚本写入 eval/feedback_cases.jsonl
        -> eval/run_feedback.py 重跑并过 evalhub.compare() 回归门

用法::

    python eval/promote_feedback.py

只处理还没晋升过的差评；处理完把 promoted_to_eval 标成 1。
同一条反馈被修改后会覆盖 JSONL 里的旧用例，不会追加重复行。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from db import repo  # noqa: E402
from db.base import SessionLocal  # noqa: E402

OUT_PATH = ROOT / "eval" / "feedback_cases.jsonl"


def _load_cases(path: Path) -> dict[str, dict]:
    """按 id 读已有用例；dict 保持文件里的顺序，方便人工 diff。"""
    cases: dict[str, dict] = {}
    if not path.exists():
        return cases
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("id"):
                cases[str(obj["id"])] = obj
    return cases


def _write_cases(path: Path, cases: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for obj in cases.values():
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT_PATH), help="输出 JSONL 路径")
    args = ap.parse_args()
    out_path = Path(args.out)

    session = SessionLocal()
    try:
        rows = repo.pending_negative_feedback(session)
        cases = _load_cases(out_path)
        added = updated = 0

        for feedback, run in rows:
            case_id = "fb-{}".format(feedback.id)
            if case_id in cases:
                updated += 1
            else:
                added += 1
            cases[case_id] = {
                "id": case_id,
                "source": "feedback",
                "question": run.question,
                "mode": run.mode,
                "bad_answer": run.answer,
                "bad_can_answer": run.can_answer,
                "reason": feedback.reason,
                "expected_answer": feedback.expected_answer,
                "run_id": run.id,
                "feedback_id": feedback.id,
                "created_at": feedback.created_at.isoformat(),
            }
            feedback.promoted_to_eval = True

        if rows:
            _write_cases(out_path, cases)
        session.commit()
    finally:
        session.close()

    print("新增 {} 条，更新 {} 条 -> {}".format(added, updated, out_path))
    if not added and not updated:
        print("没有待晋升的差评。先去 /docs 对某次回答点“没用”，再回来跑。")


if __name__ == "__main__":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    main()
