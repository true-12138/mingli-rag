# -*- coding: utf-8 -*-
"""译文自检：只测「确定性规则」，不测译文质量本身。

规则集合刻意收窄——命中说明「值得人看一眼」，不说明「译错了」。
测试锁的是规则边界，不是译文好坏。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import interpret
import interpret_check


def _rules(hits):
    return {h["rule"] for h in hits}


def test_clean_translation_has_no_hits():
    hits = interpret_check.check(
        "正官者，乃甲见辛之类，阴阳相配，故为正。",
        "正官，就是甲木见辛金一类，阴阳相配，所以是正。",
    )
    assert hits == []


def test_causal_added_when_source_has_none():
    hits = interpret_check.check("月令为提纲。", "月令是提纲，所以最重要。")
    assert "causal_added" in _rules(hits)
    assert interpret_check.hard_rules(hits), "补因果算硬伤"


def test_causal_allowed_when_source_has_one():
    hits = interpret_check.check("月令为提纲，故为要。", "月令是提纲，所以重要。")
    assert "causal_added" not in _rules(hits)


def test_copied_source_is_hard():
    """照抄原文只改标点——真实跑批里出现过（《张果星宗》），评委当时也没抓到。"""
    hits = interpret_check.check("甲子乙丑海中金", "甲子、乙丑，海中金。")
    assert "copied_source" in _rules(hits)
    assert interpret_check.hard_rules(hits)


def test_real_translation_is_not_flagged_as_copy():
    source = "详其往圣，鉴以前贤；论生死全凭鬼谷，推消息端的徐公。"
    translation = "推详往古的圣人，借鉴从前的贤人；论生死完全凭鬼谷，推消息根本在徐公。"
    assert "copied_source" not in _rules(interpret_check.check(source, translation))


def test_second_person_is_hard():
    hits = interpret_check.check("身弱财旺。", "你的身弱，财旺。")
    assert "second_person" in _rules(hits)


def test_explainer_phrasing_is_hard():
    hits = interpret_check.check("食神生财。", "食神生财，也就是说靠技艺赚钱。")
    assert "explained" in _rules(hits)


def test_contrast_dropped_is_soft():
    hits = interpret_check.check("虽有余财，终不免困。", "有一点赞财，不免困顿。")
    assert "contrast_dropped" in _rules(hits)
    assert not interpret_check.hard_rules(hits), "转折丢失只提示，不重译"


def test_term_dropped_reports_terms():
    hits = interpret_check.check("七杀有制则为偏官。", "有克制的凶星就是偏官。",
                                 terms=["七杀"])
    assert "term_dropped" in _rules(hits)


def test_omission_suspect_only_for_long_source():
    long_src = "甲" * 200
    hits = interpret_check.check(long_src, "甲。")
    assert "omission_suspect" in _rules(hits)
    assert not _rules(interpret_check.check("甲子海中金。", "甲子属海中金。"))


def test_translate_retries_once_on_hard_issue(monkeypatch):
    """首版补了原文没有的「所以」，带着这条重译一次后采用干净的一版。"""
    calls = []

    def fake_chat(messages, api_key=None):
        calls.append(messages)
        if len(calls) == 1:
            return json.dumps({"translation": "正官是甲木见辛金，所以叫正官。"},
                              ensure_ascii=False)
        # 重译请求必须把违规原因带给模型，而不是重发同一个 prompt
        assert "不合规则" in messages[-1]["content"]
        return json.dumps({"translation": "正官，是甲木见到辛金。"}, ensure_ascii=False)

    monkeypatch.setattr(interpret.rag, "_chat", fake_chat)
    out = interpret.translate("正官者，甲见辛也。")
    assert out == "正官，是甲木见到辛金。"
    assert len(calls) == 2


def test_translate_keeps_original_when_retry_is_worse(monkeypatch):
    """重译没有减少硬伤时不采纳，避免为了自检把原文译丢。"""
    monkeypatch.setattr(
        interpret.rag, "_chat",
        lambda messages, api_key=None: json.dumps(
            {"translation": "你的正官，所以是好命。"}, ensure_ascii=False),
    )
    out = interpret.translate("正官者，甲见辛也。")
    assert out == "你的正官，所以是好命。"


def test_translate_rejects_persistent_copy(monkeypatch):
    """重译后仍然照搬原文时宁可报错，也不能把原文当译文显示。"""
    monkeypatch.setattr(
        interpret.rag, "_chat",
        lambda messages, api_key=None: json.dumps(
            {"translation": "正官者，甲见辛也。"}, ensure_ascii=False),
    )
    with pytest.raises(ValueError, match="照搬"):
        interpret.translate("正官者，甲见辛也。")


def test_retry_can_be_disabled(monkeypatch):
    monkeypatch.setenv("MINGLI_INTERPRET_RETRY", "0")
    calls = []

    def fake_chat(messages, api_key=None):
        calls.append(1)
        return json.dumps({"translation": "你的正官，所以是好命。"}, ensure_ascii=False)

    monkeypatch.setattr(interpret.rag, "_chat", fake_chat)
    interpret.translate("正官者，甲见辛也。")
    assert len(calls) == 1
