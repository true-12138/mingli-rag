# -*- coding: utf-8 -*-
"""一条命令跑完反馈闭环，不需要 API key、不碰真实数据。

流程：
    建会话 -> 问答（用假模型，答案故意不好） -> 回放运行
    -> 提交差评 -> 晋升成评测用例 -> 打印 JSONL

用法::

    python scripts/demo_closed_loop.py

所有数据都写在临时目录，进程结束自动删除。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# 必须在 import db.base 之前设好，engine 是模块级创建的
_TMP = tempfile.TemporaryDirectory(prefix="mingli-demo-", ignore_cleanup_errors=True)
TMP = Path(_TMP.name)
os.environ["MINGLI_DB_URL"] = "sqlite:///" + str(TMP / "app.sqlite3").replace("\\", "/")
os.environ["MINGLI_PLATFORM_DB"] = str(TMP / "platform.sqlite3")
os.environ.pop("MINGLI_API_TOKEN", None)
# 鉴权默认拒绝；这个脚本只跑本机临时库，显式开放。额度也关掉，
# 免得演示脚本受当天计数影响。
os.environ["MINGLI_ALLOW_OPEN"] = "1"
os.environ["MINGLI_QUOTA_ENABLED"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import api_conversations  # noqa: E402
from db.base import Base, engine  # noqa: E402

BROKEN = {
    "can_answer": True,
    "answer": "贵格有很多种，具体要看各书。",
    "citations": [1],
    "citations_chunk_ids": [851],
    "invalid_citations": [],
    "invalid_output": False,
    "refusal_reason": None,
    "retrieved_chunk_ids": [851],
    "rewritten_question": "有几种贵格",
    "history_turns": 0,
    "llm_calls": 1,
}


def step(n: int, text: str) -> None:
    print("\n[{}] {}".format(n, text))


def main() -> None:
    Base.metadata.create_all(engine)
    # 演示不调真模型：答案写死，且故意没有回答"几种"
    api_conversations.rag.answer = lambda *a, **k: dict(BROKEN)

    with TestClient(api.app) as client:
        step(1, "新建会话")
        conv = client.post("/v1/conversations", json={},
                           headers={"X-Anonymous-Id": "demo"}).json()
        print("   conversation_id =", conv["id"])

        step(2, "问答（假模型，模拟一次答非所问）")
        chat = client.post(
            "/v1/conversations/{}/chat".format(conv["id"]),
            json={"question": "有几种贵格", "mode": "rag"},
            headers={"X-Anonymous-Id": "demo"},
        )
        print("   run_id       =", chat.json()["run_id"])
        print("   request_id   =", chat.headers.get("x-request-id"))
        print("   answer       =", chat.json()["answer"])

        run_id = chat.json()["run_id"]
        step(3, "回放这次运行")
        detail = client.get("/v1/runs/{}".format(run_id),
                            headers={"X-Anonymous-Id": "demo"}).json()
        print("   status       =", detail["status"])
        print("   llm_calls    =", detail["llm_calls"])

        step(4, "提交差评（带期望答案）")
        fb = client.post(
            "/v1/runs/{}/feedback".format(run_id),
            json={
                "rating": -1,
                "reason": "问数量，回答没有给出数量",
                "expected_answer": "《五行精纪·论贵局上》第一组贵格约五十一种。",
            },
            headers={"X-Anonymous-Id": "demo"},
        ).json()
        print("   feedback_id  =", fb["id"])
        print("   promoted     =", fb["promoted_to_eval"])

    step(5, "晋升差评 -> eval/feedback_cases.jsonl（写到临时目录）")
    out = TMP / "feedback_cases.jsonl"
    subprocess.run(
        [sys.executable, str(ROOT / "eval" / "promote_feedback.py"), "--out", str(out)],
        check=True,
        env=os.environ.copy(),
    )
    line = out.read_text(encoding="utf-8").strip()
    print("   用例: " + json.dumps(json.loads(line), ensure_ascii=False)[:160] + " ...")

    step(6, "闭环节点全部打通")
    print("   线上差评 -> feedback 表 -> JSONL 用例 -> 可重跑、可回归门")
    print("   真实评测：python eval/run_feedback.py --mode rag（需要 DEEPSEEK_API_KEY）")


if __name__ == "__main__":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    try:
        main()
    finally:
        engine.dispose()  # Windows 上先关连接才能删临时库
        _TMP.cleanup()
