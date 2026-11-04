# -*- coding: utf-8 -*-
"""重跑线上差评用例，并可选地过回归门。

用法::

    # 第一次只登记基线
    python eval/run_feedback.py --mode rag

    # 之后改完代码，拿基线 id 对比；掉超过 5 个点会以退出码 1 失败
    python eval/run_feedback.py --mode rag --baseline 12

    # 先跑 3 条试水
    python eval/run_feedback.py --mode rag --limit 3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import evalhub  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["rag", "agent", "multi"],
                    help="统一覆盖用例里记录的模式；不传则按每条用例自己的模式跑")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条，0 为全部")
    ap.add_argument("--name", help="这次 run 的名字，默认自动生成")
    ap.add_argument("--baseline", type=int, help="基线 eval_runs.id；给出才过回归门")
    args = ap.parse_args()

    run_id = evalhub.run_feedback(mode=args.mode, limit=args.limit, name=args.name)
    latest = evalhub.list_runs(suite="feedback", limit=1)[0]
    print("新 run id: {}".format(run_id))
    print(json.dumps(latest["metrics"], ensure_ascii=False, indent=2))

    if args.baseline:
        gate = evalhub.compare(args.baseline, run_id)
        print(json.dumps(gate, ensure_ascii=False, indent=2))
        if gate["status"] == "fail":
            print("回归门失败：通过率掉超过阈值。", file=sys.stderr)
            raise SystemExit(1)
        print("回归门通过。")


if __name__ == "__main__":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    main()
