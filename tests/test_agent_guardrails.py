# -*- coding: utf-8 -*-
"""Agent 出口约束的单元测试（不加载 BGE-M3、不调 API）。

`agent.py` 在导入时会 import tools/rag；这里先把它们替换成最小 stub，
只测 `_finalize` 的引用白名单与拒答逻辑，保证 CI 里不需要模型权重。
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

sys.modules["tools"] = types.SimpleNamespace(call=lambda *a, **k: {"ok": True})
sys.modules["rag"] = types.SimpleNamespace(
    REFUSAL_TEXT="语料中没有足够的依据回答这个问题。",
    _chat=lambda *a, **k: "",
    _parse_json=lambda raw: {},
)

from agent import _finalize, REFUSAL_TEXT  # noqa: E402


def test_citation_whitelist_keeps_only_seen_ids():
    res = _finalize(
        {"can_answer": True, "answer": "有依据的回答", "citations": [1, 99]},
        seen={1}, trace=[],
    )
    assert res["citations_chunk_ids"] == [1]
    assert res["invalid_citations"] == [99]
    assert res["invalid_output"] is True


def test_claiming_answer_without_valid_citation_is_invalid():
    res = _finalize(
        {"can_answer": True, "answer": "看起来像答案", "citations": [99]},
        seen={1}, trace=[],
    )
    assert res["citations_chunk_ids"] == []
    assert res["invalid_output"] is True


def test_empty_answer_is_invalid():
    res = _finalize(
        {"can_answer": True, "answer": "", "citations": [1]},
        seen={1}, trace=[],
    )
    assert res["invalid_output"] is True


def test_refusal_uses_fixed_text():
    res = _finalize(
        {"can_answer": False, "answer": "", "citations": [1]},
        seen={1}, trace=[],
    )
    assert res["can_answer"] is False
    assert res["answer"] == REFUSAL_TEXT
    assert res["citations_chunk_ids"] == []
