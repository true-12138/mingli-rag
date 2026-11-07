# -*- coding: utf-8 -*-
"""流式 JSON → 纯文本的增量提取。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from answer_stream import AnswerExtractor, extract_streamed_answer  # noqa: E402


def test_key_split_across_chunks():
    chunks = ['{"can_answer": true, "ans', 'wer": "正官', '与七杀"}']
    assert extract_streamed_answer(chunks) == "正官与七杀"


def test_stops_at_closing_quote():
    chunks = ['{"answer": "正文', '', '", "citations": [1, 2]}']
    assert extract_streamed_answer(chunks) == "正文"


def test_decodes_escapes_char_by_char():
    raw = '{"answer": "第一行\\n第二行 \\"引号\\" \\\\ 反斜杠"}'
    ex = AnswerExtractor()
    out = "".join(ex.feed(c) for c in raw)
    assert out == '第一行\n第二行 "引号" \\ 反斜杠'
    assert ex.done


def test_decodes_unicode_escape_split_mid_sequence():
    raw = '{"answer": "\\u6b63\\u5b98"}'
    ex = AnswerExtractor()
    out = "".join(ex.feed(c) for c in raw)
    assert out == "正官"


def test_ignores_non_json_output():
    ex = AnswerExtractor()
    assert ex.feed("模型没有按 JSON 输出") == ""
    assert not ex.done


def test_returns_empty_when_answer_missing():
    ex = AnswerExtractor()
    assert ex.feed('{"can_answer": false, "refusal_reason": "无依据"}') == ""
    assert not ex.done
