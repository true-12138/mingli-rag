# -*- coding: utf-8 -*-
"""多轮评测集与判分器的离线测试。

不调用 API：只验证任务集本身没写错书名，以及 judge_turn 在几种典型
通过/失败形态下判得对。真正的模型行为由 run_multiturn.py 带 key 跑。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

import run_multiturn as rm  # noqa: E402

TASKS = rm.load_tasks(rm.TASKS_PATH)
BY_ID = {t["id"]: t for t in TASKS}
ID2BOOK = {1: "三命通会", 2: "五行精纪", 3: "神峰通考"}


def _rec(answer="", rewritten="", citations=None, can_answer=True,
         trace=None, invalid_citations=None, invalid_output=False):
    return {
        "answer": answer,
        "rewritten_question": rewritten,
        "citations": citations or [],
        "can_answer": can_answer,
        "trace": trace or [],
        "invalid_citations": invalid_citations,
        "invalid_output": invalid_output,
    }


def test_set_shape_and_categories():
    assert len(TASKS) == 20
    cats = {}
    for t in TASKS:
        cats[t["category"]] = cats.get(t["category"], 0) + 1
    assert cats == {"指代": 5, "省略": 5, "跨轮约束": 5, "引用隔离": 5}


def test_all_books_exist_and_rewrite_groups_cover_followups():
    books = {c["meta"].get("book") for c in __import__("corpus").load_chunks()}
    for t in TASKS:
        for i, turn in enumerate(t["turns"]):
            for name in (turn.get("expected_books") or []) + (turn.get("forbidden_books") or []):
                assert name in books, "{} 第 {} 轮的书不在语料里：{}".format(t["id"], i, name)
            if i > 0:
                assert turn.get("rewrite_groups"), "{} 第 {} 轮缺改写检查".format(t["id"], i)


def test_judge_rewrite_passes_when_reference_resolved():
    spec = BY_ID["mt01"]["turns"][1]
    rec = _rec(answer="羊刃与阳刃同类而异名……",
               rewritten="《三命通会》里羊刃和阳刃是否是一回事",
               citations=[1])
    judge = rm.judge_turn(spec, rec, ID2BOOK)
    assert judge["pass"], judge["problems"]
    assert all(c["ok"] for c in judge["checks"])


def test_judge_rewrite_fails_when_book_dropped():
    spec = BY_ID["mt01"]["turns"][1]
    rec = _rec(answer="是一回事", rewritten="阳刃是什么", citations=[1])
    judge = rm.judge_turn(spec, rec, ID2BOOK)
    assert not judge["pass"]
    assert any("三命通会" in p for p in judge["problems"])


def test_judge_forbidden_book_catches_stale_citation():
    spec = BY_ID["mt16"]["turns"][1]
    rec = _rec(answer="神峰通考论羊刃……", rewritten="《神峰通考》怎么论羊刃",
               citations=[1])  # 1 = 三命通会，是上一轮的书
    judge = rm.judge_turn(spec, rec, ID2BOOK)
    assert not judge["pass"]
    assert any(c["name"] == "forbidden_books" and not c["ok"] for c in judge["checks"])


def test_judge_refusal_requires_no_citations():
    spec = BY_ID["mt20"]["turns"][0]
    ok = _rec(answer="本工具没有紫微斗数排盘能力。", can_answer=False, citations=[])
    assert rm.judge_turn(spec, ok, ID2BOOK)["pass"]
    bad = _rec(answer="本工具没有紫微斗数排盘能力。", can_answer=False, citations=[1])
    assert not rm.judge_turn(spec, bad, ID2BOOK)["pass"]


def test_judge_must_contain_any_accepts_enumeration():
    spec = BY_ID["mt05"]["turns"][1]
    rec = _rec(answer="四病指雕、枯、旺、弱；四药指损、益、生、长。",
               rewritten="《神峰通考》的四病和四药分别指什么",
               citations=[3])
    judge = rm.judge_turn(spec, rec, ID2BOOK)
    assert judge["pass"], judge["problems"]


def test_judge_forbidden_tool():
    spec = BY_ID["mt15"]["turns"][1]
    trace = [{"step": 1, "action": "search_terms", "ok": True, "chunk_ids": []},
             {"step": 2, "action": "search_classics", "ok": True, "chunk_ids": [1]}]
    rec = _rec(answer="正印与偏印……", rewritten="《三命通会》里正印和偏印怎么区分",
               citations=[1], trace=trace)
    judge = rm.judge_turn(spec, rec, ID2BOOK)
    assert not judge["pass"]
    assert any(c["name"] == "forbidden_tools" and not c["ok"] for c in judge["checks"])


def test_judge_conversation_rejects_missing_turn():
    task = BY_ID["mt01"]
    judge = rm.judge_conversation(task, [_rec(answer="羊刃……", citations=[1])], ID2BOOK)
    assert not judge["auto_pass"]
    assert "轮次缺失" in judge["turns"][0]["problems"][0]


def test_scrub_removes_secret():
    out = rm._scrub({"error": "bad key sk-abc", "nested": ["sk-abc"]}, "sk-abc")
    assert out == {"error": "bad key ***", "nested": ["***"]}
