# -*- coding: utf-8 -*-
"""排盘模块测试。

这些断言只验证**计算的结构和边界**，不验证"解得准不准"——
吉凶没有客观答案，但"立春前后年柱要变""同一输入必须得到同一个盘"
这些是可以被证伪的，所以必须写死。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fortune.astro import SIGNS, natal_chart
from fortune.bazi import paipan
from fortune.intake import MODELS
from fortune.interpret import KIND_LABELS, SECTION_HINTS
from fortune.name import build as build_name
from fortune.tarot import DECK, SPREADS, draw


class TestBazi:
    def test_sizhu_shape(self):
        chart = paipan(1995, 8, 20, 14, 30, "male")
        assert set(chart["sizhu"]) == {"年柱", "月柱", "日柱", "时柱"}
        for ganzhi in chart["sizhu"].values():
            assert len(ganzhi) == 2

    def test_wuxing_counts_eight_chars(self):
        chart = paipan(1995, 8, 20, 14, 30, "male")
        assert sum(chart["wuxing"].values()) == 8

    def test_deterministic(self):
        a = paipan(1995, 8, 20, 14, 30, "male")
        b = paipan(1995, 8, 20, 14, 30, "male")
        assert a["sizhu"] == b["sizhu"]
        assert a["dayun"] == b["dayun"]

    def test_year_pillar_changes_across_lichun(self):
        """年柱按立春换，不是按元旦换——这是八字最容易错的地方。"""
        before = paipan(1995, 2, 3, 12, 0, "male")
        after = paipan(1995, 2, 5, 12, 0, "male")
        assert before["sizhu"]["年柱"] != after["sizhu"]["年柱"]

    def test_dayun_present(self):
        chart = paipan(1995, 8, 20, 14, 30, "male")
        assert len(chart["dayun"]) >= 6
        assert chart["dayun"][0]["ganzhi"]

    def test_gender_switches_direction(self):
        male = paipan(1995, 8, 20, 14, 30, "male")
        female = paipan(1995, 8, 20, 14, 30, "female")
        # 性别只影响大运顺逆，不影响四柱
        assert male["sizhu"] == female["sizhu"]
        assert male["qiyun"]["forward"] != female["qiyun"]["forward"]

    def test_invalid_date(self):
        with pytest.raises(ValueError):
            paipan(1995, 2, 30, 12, 0, "male")

    def test_invalid_gender(self):
        with pytest.raises(ValueError):
            paipan(1995, 8, 20, 14, 30, "other")


class TestAstro:
    def test_ten_planets(self):
        chart = natal_chart(1995, 8, 20, 14, 30, 8, 39.9, 116.4, "北京")
        assert len(chart["planets"]) == 10
        for p in chart["planets"]:
            assert p["sign"] in SIGNS
            assert 0 <= p["degree"] < 30

    def test_sun_sign_known_date(self):
        """1995-08-20 太阳应在狮子座末段（狮子 23°–29°）。"""
        chart = natal_chart(1995, 8, 20, 14, 30, 8, 39.9, 116.4, "北京")
        sun = next(p for p in chart["planets"] if p["name"] == "太阳")
        assert sun["sign"] == "狮子"
        assert 20 <= sun["degree"] < 30

    def test_asc_changes_with_time(self):
        """差 6 小时上升点必须换位置，否则时间没被用上。"""
        early = natal_chart(1995, 8, 20, 2, 0, 8, 39.9, 116.4, "北京")
        late = natal_chart(1995, 8, 20, 20, 0, 8, 39.9, 116.4, "北京")
        assert early["asc"]["sign"] != late["asc"]["sign"]

    def test_houses_cover_twelve_signs(self):
        chart = natal_chart(1995, 8, 20, 14, 30, 8, 39.9, 116.4, "北京")
        assert len(chart["houses"]) == 12
        assert len({h["sign"] for h in chart["houses"]}) == 12
        assert chart["houses"][0]["sign"] == chart["asc"]["sign"]

    def test_deterministic(self):
        a = natal_chart(1995, 8, 20, 14, 30, 8, 39.9, 116.4, "北京")
        b = natal_chart(1995, 8, 20, 14, 30, 8, 39.9, 116.4, "北京")
        assert [p["lon"] for p in a["planets"]] == [p["lon"] for p in b["planets"]]


class TestTarot:
    def test_deck_size(self):
        assert len(DECK) == 78
        assert len({c["name"] for c in DECK}) == 78

    def test_draw_count(self):
        assert len(draw(1)["cards"]) == 1
        assert len(draw(5)["cards"]) == 5

    def test_seed_reproducible(self):
        a = draw(3, seed=42)
        b = draw(3, seed=42)
        assert [c["name"] for c in a["cards"]] == [c["name"] for c in b["cards"]]
        assert [c["orientation"] for c in a["cards"]] == [c["orientation"] for c in b["cards"]]

    def test_different_seeds_differ(self):
        names = {tuple(c["name"] for c in draw(5, seed=s)["cards"]) for s in range(10)}
        assert len(names) > 1

    def test_spread_positions(self):
        result = draw(spread="cross")
        assert len(result["cards"]) == len(SPREADS["cross"][1])
        assert [c["position"] for c in result["cards"]] == list(SPREADS["cross"][1])

    def test_majors_and_minors_present(self):
        majors = [c for c in DECK if c["arcana"] == "大阿卡纳"]
        assert len(majors) == 22
        assert len(DECK) - len(majors) == 56


class TestName:
    """五格公式是可被证伪的：字库笔画是既定值，加法必须对得上。"""

    def test_single_surname_single_given_formulas(self):
        # 李 7 画、明 8 画：天=7+1、人=7+8、地=8+1、外=2、总=15
        chart = build_name("李", "明")
        nums = {k: v["num"] for k, v in chart["wuge"].items()}
        assert nums == {"tian": 8, "ren": 15, "di": 9, "wai": 2, "zong": 15}

    def test_zong_is_sum_of_strokes(self):
        chart = build_name("张", "伟")
        strokes = sum(c["kangxi"] for c in chart["chars"])
        assert chart["wuge"]["zong"]["num"] == strokes

    def test_deterministic(self):
        assert build_name("李", "明") == build_name("李", "明")

    def test_sancai_and_three_yunshi(self):
        chart = build_name("李", "明")
        combo = "".join(chart["wuge"][k]["wuxing"] for k in ("tian", "ren", "di"))
        assert chart["sancai"]["combo"] == combo
        assert chart["sancai"]["level"]
        assert len(chart["yunshi"]) == 3
        assert all(item["text"] for item in chart["yunshi"])

    def test_unknown_char_names_the_field(self):
        """字库没有的字不能猜笔画；错误要指到具体那一格。"""
        with pytest.raises(ValueError) as exc:
            build_name("李", "𠀀")
        assert getattr(exc.value, "field", None) == "given"

    def test_length_limit(self):
        with pytest.raises(ValueError):
            build_name("李", "一二三")


class TestInterpretCoverage:
    """新增盘种时，/read 的每一张表都要有它；姓名就漏过一次。"""

    def test_every_readable_kind_has_hints_and_label(self):
        assert set(KIND_LABELS) == set(SECTION_HINTS) == set(MODELS)

    def test_name_read_builds_prompt(self, monkeypatch):
        """不真的调模型：桩掉检索和 _chat，只确认 prompt 里认得出姓名盘。"""
        import sys
        import types

        from fortune import interpret
        from fortune.name import build

        seen = {}

        def fake_chat(messages, **kwargs):
            seen["prompt"] = messages[-1]["content"]
            return '{"summary": "s", "sections": [], "citations": [], "disclaimer": "d"}'

        stub = types.ModuleType("rag")
        stub._chat = fake_chat
        stub._parse_json = lambda raw: __import__("json").loads(raw)
        monkeypatch.setitem(sys.modules, "rag", stub)
        monkeypatch.setattr(interpret, "_retrieve_fragments", lambda *a, **k: ([], ""))

        result = interpret.read(build("李", "明"), question="三才是什么意思")

        assert "姓名五格" in seen["prompt"]
        assert "1928" in seen["prompt"]
        assert result["kind"] == "name"

