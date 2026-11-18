# -*- coding: utf-8 -*-
"""无标点组题库（eval/questions_unpunct.jsonl）的口径测试。

2026-11-18 的教训：草稿里用的是 `unpunct.jsonl` 的文件内局部编号（1..5851），
评测用的是 `corpus.py` 重编的全局编号（2831..8681）。第一次跑出来 36 题全 0，
看起来像检索坏了，其实是 gold 指到了标点组别的书。这里把「gold 必须落在
无标点组、引文必须真在原文里」钉成测试，改题库或改编号规则时先红一次。
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import corpus  # noqa: E402
import segment  # noqa: E402

QUESTIONS = ROOT / "eval" / "questions_unpunct.jsonl"
PREFIX = "data/clean_text/"


@pytest.fixture(scope="module")
def questions():
    with QUESTIONS.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@pytest.fixture(scope="module")
def chunks():
    return {c["chunk_id"]: c for c in corpus.load_chunks()}


def _plain(text):
    return segment._PUNCT.sub("", text)


def test_question_set_size_and_books(questions):
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids)), "题目 id 有重复"
    assert len(questions) >= 30, "无标点组题库不少于 30 题（README 写的是 30–40）"
    books = {q["evidence"][0]["book"] for q in questions}
    assert len(books) == 29, "应覆盖全部 29 部无标点书，实际 {} 部".format(len(books))


def test_gold_chunks_are_unpunct_and_exist(questions, chunks):
    for q in questions:
        golds = q["gold_chunk_ids"]
        assert len(golds) == 1, "{}：这组题一题一段".format(q["id"])
        chunk = chunks.get(golds[0])
        assert chunk is not None, "{}：gold #{} 不在语料里".format(q["id"], golds[0])
        assert chunk["meta"].get("index_source") == "unpunct", (
            "{}：gold #{} 落在{}组——多半是用了 unpunct.jsonl 的局部编号".format(
                q["id"], golds[0], chunk["meta"].get("index_source")))


def test_evidence_matches_gold_chunk(questions, chunks):
    for q in questions:
        gold = q["gold_chunk_ids"][0]
        ev = q["evidence"][0]
        meta = chunks[gold]["meta"]
        assert ev["chunk_id"] == gold
        assert ev["book"] == meta.get("book")
        assert ev["line_start"] == meta.get("line_start")
        assert ev["line_end"] == meta.get("line_end")
        sourcefile = str(meta.get("sourcefile") or "")
        expected = sourcefile[len(PREFIX):] if sourcefile.startswith(PREFIX) else sourcefile
        assert ev["sourcefile"] == expected


def test_quotes_come_from_the_chunk_text(questions, chunks):
    for q in questions:
        text = str(chunks[q["gold_chunk_ids"][0]].get("chunk_text") or "")
        quote = _plain(q["evidence"][0]["quote"])
        assert len(quote) >= 8, "{}：引文太短".format(q["id"])
        assert quote in _plain(text), "{}：引文不在 #{} 原文里".format(
            q["id"], q["gold_chunk_ids"][0])
