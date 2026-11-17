# -*- coding: utf-8 -*-
"""术语卡：词典合并规则与正文标注区间。

不加载检索索引，只读 data/terminology 下的 jsonl（test_snippets 除外，
它读的是预生成文件，不碰语料）。标注是「直接画在回答正文上」的，标错一个词
比少标十个更伤，所以这里钉的是口径：单字不标、通用词不标、长词优先、不重叠。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import terms


def test_dictionary_shape():
    entries = terms.load()
    assert len(entries) >= 150, "词典比预期小，可能是 jsonl 读失败"
    for term, item in entries.items():
        assert item["term"] == term
        assert item["category"], "{} 缺分类".format(term)
        assert isinstance(item["snippets"], list)
        assert item["source"] in ("bazi-terms.jsonl", "iztro-terms.jsonl")


def test_broken_source_definitions_never_surface():
    """iztro 有 6 个星曜的释义在源数据里被截断成「五行属，。」，不能展示。"""
    for item in terms.load().values():
        assert "，。" not in item["definition"], "{} 的释义是截断的".format(item["term"])


def test_chinese_definition_wins_over_english():
    """同一个词条两边都有时，中文释义优先（给中文读者看的卡片）。"""
    ziwei = terms.get("紫微")
    assert ziwei and "五行属" in ziwei["definition"]
    assert ziwei["category"] == "星曜"
    # 七杀在 iztro 里的中文释义是坏的，退回 bazi-terms 的英文，而不是留空
    qisha = terms.get("七杀")
    assert qisha and qisha["definition"], "七杀不该因为中文释义损坏就没有释义"


def test_snippets_are_real_excerpts_of_the_term():
    covered = 0
    for term, item in terms.load().items():
        for snippet in item["snippets"]:
            covered += 1
            assert isinstance(snippet["chunk_id"], int)
            assert snippet["book"], "{} 的例句缺书名".format(term)
            assert term in snippet["text"], "{} 的例句里没有这个词".format(term)
    assert covered > 100, "例句覆盖太少，build_term_snippets.py 可能没跑"


def test_annotate_returns_aligned_non_overlapping_spans():
    text = "日主甲木，月令建禄，年干透出正官，又有天乙贵人相助。"
    hits = terms.annotate_with_entries(text)
    found = [h["term"] for h in hits]
    assert "日主" in found and "正官" in found and "天乙贵人" in found
    last = 0
    for hit in hits:
        assert hit["start"] >= last
        assert text[hit["start"]:hit["end"]] == hit["term"]
        assert hit["definition"] or hit["snippets"], "术语卡不能是空的"
        last = hit["end"]


def test_annotate_longest_match_wins():
    # 「天乙贵人」同时以自己和「贵人」…的形式出现时只能标一次，且标长的
    text = "命带天乙贵人"
    hits = terms.annotate(text)
    assert [h["term"] for h in hits] == ["天乙贵人"]


def test_annotate_skips_single_chars_and_generic_words():
    assert terms.annotate("甲子年的性别，当前顺行") == []
    # 单字仍然可以搜到，只是不自动标注
    assert terms.search("甲")


def test_annotate_respects_limit():
    hits = terms.annotate("天乙贵人、食神、正官、七杀", limit=2)
    assert len(hits) == 2


def test_search_prefers_term_name_over_definition():
    hits = terms.search("贵人", limit=3)
    assert hits and hits[0]["term"] == "天乙贵人"
    assert terms.search("") == []
