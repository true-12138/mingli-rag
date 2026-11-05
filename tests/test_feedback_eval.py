# -*- coding: utf-8 -*-
"""差评用例的自动判据测试：纯函数，不连数据库、不调模型。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import evalhub


def _result(answer="答案", can_answer=True, citations=("c1",), invalid=False):
    return {
        "answer": answer,
        "can_answer": can_answer,
        "citations_chunk_ids": list(citations),
        "invalid_output": invalid,
    }


def test_refusal_case_passes_only_with_valid_citations():
    case = {"bad_answer": "语料中没有足够的依据", "bad_can_answer": False}
    ok = evalhub.judge_feedback_case(case, _result(answer="有依据的回答"))
    assert ok["passed"] is True

    bad = evalhub.judge_feedback_case(
        case, _result(answer="有依据的回答", citations=())
    )
    assert bad["passed"] is False
    assert bad["auto"] is True


def test_expected_answer_requires_improvement_over_bad_answer():
    case = {
        "bad_answer": "羊刃就是凶煞，越少越好。",
        "bad_can_answer": True,
        "expected_answer": "羊刃有六种：阳刃、阴刃、飞刃、刃宫、刃星、刃度。",
    }
    better = evalhub.judge_feedback_case(
        case, _result(answer="羊刃分六种：阳刃、阴刃、飞刃、刃宫、刃星、刃度。")
    )
    assert better["passed"] is True
    assert better["new_similarity"] > better["old_similarity"]

    same = evalhub.judge_feedback_case(
        case, _result(answer=case["bad_answer"])
    )
    assert same["passed"] is False


def test_noise_level_improvement_is_rejected():
    """只比旧答案像 0.002，是模型随机波动，不能算修好。"""
    base = "".join(chr(0x4E00 + i) for i in range(200))
    case = {
        "bad_answer": base[:-1] + "X",
        "bad_can_answer": True,
        "expected_answer": base,
    }
    judged = evalhub.judge_feedback_case(case, _result(answer=base[:-1] + "Y"))
    assert judged["passed"] is False
    assert "噪声" in judged["reason"]


def test_expected_refusal_case():
    case = {
        "bad_answer": "你明天面试一定顺利。",
        "bad_can_answer": True,
        "expected_answer": "语料中没有足够的依据回答这个问题。",
    }
    assert evalhub.judge_feedback_case(
        case, _result(answer="语料中没有足够的依据回答这个问题。", can_answer=False,
                      citations=())
    )["passed"] is True
    assert evalhub.judge_feedback_case(
        case, _result(answer="一定顺利")
    )["passed"] is False


def test_case_without_expected_answer_goes_to_human():
    case = {"bad_answer": "旧答案", "bad_can_answer": True}
    judged = evalhub.judge_feedback_case(case, _result(answer="新答案"))
    assert judged["passed"] is None
    assert judged["auto"] is False


def test_similarity_is_symmetric_and_handles_empty():
    assert evalhub._similarity("羊刃分六种", "羊刃分六种") == 1.0
    assert evalhub._similarity("", "羊刃") == 0.0
    assert evalhub._similarity("甲", "乙") == 0.0
