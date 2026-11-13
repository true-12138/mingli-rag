# -*- coding: utf-8 -*-
"""多轮对话的边界测试。

重点不是「能聊」，而是三条不能破的约束：
1. 历史有上限，不能被无限带进 prompt；
2. 改写失败必须退回原问题，多轮不能拖垮单轮；
3. 引用只来自本轮检索，历史里的旧 chunk 不能混进引用。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import conversation
import rag


def test_normalize_history_keeps_recent_turns_and_drops_bad_items():
    history = [
        {"role": "system", "content": "ignored"},
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "第一答"},
        {"role": "user", "content": "第二问"},
        {"role": "assistant", "content": "第二答"},
        {"role": "user", "content": "第三问"},
        {"role": "assistant", "content": "第三答"},
        {"role": "user", "content": "第四问"},
        {"role": "assistant", "content": "第四答"},
    ]
    got = conversation.normalize_history(history, max_turns=2)
    assert [m["content"] for m in got] == ["第三问", "第三答", "第四问", "第四答"]


def test_normalize_history_respects_char_budget_and_keeps_newest():
    history = [
        {"role": "user", "content": "旧" * 800},
        {"role": "assistant", "content": "新" * 800},
    ]
    got = conversation.normalize_history(history, max_turns=3, max_chars=300)
    assert got
    assert sum(len(m["content"]) for m in got) <= 300
    # 最新的消息一定在，旧的先被丢掉
    assert got[-1]["content"].startswith("新")


def test_history_block_is_marked_as_not_evidence():
    block = conversation.history_block([{"role": "user", "content": "那第二点呢"}])
    assert "不作为回答证据" in block
    assert "那第二点呢" in block


def test_rewrite_without_history_returns_original_without_llm_call(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("没有历史时不应调用模型")

    monkeypatch.setattr(rag, "_chat", boom)
    assert conversation.rewrite_question("七杀是什么", []) == "七杀是什么"


def test_rewrite_success_returns_standalone(monkeypatch):
    monkeypatch.setattr(rag, "_chat_message",
                        lambda *a, **k: {"content": '{"standalone": "《渊海子平》怎么看正官"}'})
    counter = {"llm_calls": 0}
    got = conversation.rewrite_question(
        "那这本书呢",
        [{"role": "user", "content": "正官是什么意思"}, {"role": "assistant", "content": "……"}],
        counter=counter,
    )
    assert got == "《渊海子平》怎么看正官"
    assert counter["llm_calls"] == 1


def test_rewrite_failure_falls_back_to_original(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(rag, "_chat", boom)
    counter = {"llm_calls": 0}
    got = conversation.rewrite_question(
        "那第二点呢",
        [{"role": "user", "content": "第一点是什么"}],
        counter=counter,
    )
    assert got == "那第二点呢"
    assert counter["llm_calls"] == 1


def test_answer_retrieves_with_standalone_and_isolates_citations(monkeypatch):
    hits = [
        {"chunk_id": "c1", "text": "正官者，……", "meta": {"book": "渊海子平"}},
        {"chunk_id": "c2", "text": "七杀者，……", "meta": {"book": "三命通会"}},
    ]
    seen_questions = []

    def fake_retrieve(question, top_k=5, mode="rrf"):
        seen_questions.append(question)
        return hits

    def fake_chat(messages, temperature=0.0, api_key=None):
        if "改写器" in messages[0]["content"]:
            return '{"standalone": "《渊海子平》怎么看正官"}'
        return '{"can_answer": true, "answer": "正官为……", "citations": [1]}'

    monkeypatch.setattr(rag, "retrieve_one", fake_retrieve)
    monkeypatch.setattr(rag, "_chat", fake_chat)
    # 追问改写走 _chat_message（要拿 usage），回答正文仍走 _chat
    monkeypatch.setattr(rag, "_chat_message",
                        lambda messages, **kw: {"content": fake_chat(messages, **kw)})

    res = rag.answer(
        "那这本书呢",
        history=[
            {"role": "user", "content": "正官是什么意思"},
            {"role": "assistant", "content": "旧回答里引用过 c2"},
        ],
    )
    assert seen_questions == ["《渊海子平》怎么看正官"]
    # 只允许本轮第 1 条片段成为引用，历史里提到的 c2 不能带进来
    assert res["citations_chunk_ids"] == ["c1"]
    assert res["rewritten_question"] == "《渊海子平》怎么看正官"
    assert res["history_turns"] == 2
    assert res["llm_calls"] == 2
