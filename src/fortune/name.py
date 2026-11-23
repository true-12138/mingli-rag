# -*- coding: utf-8 -*-
"""姓名测算：康熙笔画 + 五格剖象（熊崎健翁，1928）。

这里只做确定性查表，不调模型：

- 每个字的**康熙笔画**、字义五行、部首、拼音、结构，来自康熙字典字库；
- 五格（天/人/地/外/总）按固定公式相加；
- 81 数理、125 三才、75 运势都是**整表查出来的**，不是按生克现推——
  业内对同一配置的吉凶是积累下来的判断，现推会和通行说法对不上。

数据与公式来自 MIT 许可的 shunshi-kangxi-core 0.1.1 / shunshi-naming-core 0.1.0，
许可见 ``data/LICENSE-shunshi-*.txt``。

要跟用户说清楚的一点：五格剖象是 1928 年日本人熊崎健翁整理的**现代数理体系**，
不是中国古代古籍。解读时可以说「这套体系的说法是……」，不能说「古书云……」。
"""
from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parent / "data"

# 五行生克，只用于显示关系（三才的吉凶本身查表，不现推）。
SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

# 数理五行按格数末位：1,2 木；3,4 火；5,6 土；7,8 金；9,0 水。
_NUM_WX = {1: "木", 2: "木", 3: "火", 4: "火", 5: "土", 6: "土", 7: "金", 8: "金", 9: "水", 0: "水"}

# 五格各自主管的人生阶段（熊崎派说法）。
GRID_ROLE = {
    "tian": "祖运（不论吉凶）",
    "ren": "主运",
    "di": "前运",
    "wai": "副运",
    "zong": "后运",
}

# 三运势：人格做主体，分别对地格、天格、外格看。
_YUNSHI_DEFS = (
    ("基础运", "di", "base", "人格与地格 —— 根基是否安稳，住所、健康、下属助力"),
    ("成功运", "tian", "succ", "人格与天格 —— 上进是否顺遂，长上、家世、时势的助力"),
    ("社交运", "wai", "soc", "人格与外格 —— 人际是否融洽，外在环境与他人对待"),
)


@lru_cache(maxsize=None)
def _table(name: str) -> Any:
    with gzip.open(_DATA / name, "rt", encoding="utf-8") as fh:
        return json.load(fh)


class NameInputError(ValueError):
    """姓名本身不合法；field 指到具体哪一格，前端可以只标红那一项。"""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


@lru_cache(maxsize=1)
def _chars() -> dict[str, dict[str, Any]]:
    return _table("kangxi-chars.json.gz")["chars"]


@lru_cache(maxsize=1)
def _alias() -> dict[str, str]:
    return _table("kangxi-chars.json.gz").get("alias") or {}


@lru_cache(maxsize=1)
def _struct() -> dict[str, str]:
    return _table("kangxi-struct.json.gz")


def _char_info(ch: str) -> dict[str, Any]:
    """单个字的康熙信息；字库没有就抛 ValueError，不猜笔画。"""
    key = _alias().get(ch, ch)
    info = _chars().get(key)
    if not info or not isinstance(info.get("kx"), int) or info["kx"] <= 0:
        raise ValueError("字库暂未收录「%s」，请换一个字，或用繁体写法" % ch)
    return {
        "char": ch,
        "kangxi": info["kx"],
        "wuxing": str(info.get("wx") or ""),
        "radical": str(info.get("rad") or ""),
        "pinyin": str(info.get("py") or ""),
        "structure": str(_struct().get(key) or ""),
    }


def _part(label: str, text: str, max_len: int, field: str) -> tuple[str, list[dict[str, Any]]]:
    text = "".join((text or "").split())
    if not text:
        raise NameInputError("%s不能为空" % label, field)
    if len(text) > max_len:
        raise NameInputError("%s最多 %d 个字" % (label, max_len), field)
    try:
        out = [_char_info(ch) for ch in text]
    except ValueError as exc:
        raise NameInputError(str(exc), field) from None
    for item in out:
        item["role"] = label
    return text, out


def _shuli_entry(n: int) -> dict[str, Any]:
    """81 数理条目；超过 81 按惯例逐次减 80。"""
    k = n
    while k > 81:
        k -= 80
    entry = _table("shuli-81.json.gz").get(str(k))
    if not entry:
        raise ValueError("数理表缺 %d（应为 81 条）" % k)
    return entry


def _num_wx(n: int) -> str:
    return _NUM_WX[n % 10]


def _relation_from(me: str, other: str) -> str:
    if me == other:
        return "比和"
    if SHENG.get(other) == me:
        return "生我"
    if SHENG.get(me) == other:
        return "我生"
    if KE.get(me) == other:
        return "我克"
    return "克我"


def _relation_pair(a: str, b: str) -> str:
    """三才里显示用的单向关系：a 对 b。"""
    if a == b:
        return "同"
    if SHENG.get(a) == b:
        return "生"
    if SHENG.get(b) == a:
        return "被生"
    if KE.get(a) == b:
        return "克"
    return "被克"


def build(surname: str, given: str) -> dict[str, Any]:
    """算一张姓名盘。参数不合法时抛 ValueError（带可以直接展示的中文原因）。"""
    surname, s_chars = _part("姓", surname, 2, "surname")
    given, g_chars = _part("名", given, 2, "given")

    s = [item["kangxi"] for item in s_chars]
    g = [item["kangxi"] for item in g_chars]

    # 五格公式（单复姓 × 单双名四种情况都覆盖）。
    tian = s[0] + 1 if len(s) == 1 else s[0] + s[1]
    ren = s[-1] + g[0]
    di = g[0] + 1 if len(g) == 1 else g[0] + g[1]
    zong = sum(s) + sum(g)
    if len(s) == 1 and len(g) == 1:
        wai = 2
    elif len(s) == 1:
        wai = g[-1] + 1
    elif len(g) == 1:
        wai = s[0] + 1
    else:
        wai = s[0] + g[-1]
    grids = {"tian": tian, "ren": ren, "di": di, "wai": wai, "zong": zong}

    wuge: dict[str, dict[str, Any]] = {}
    for key, num in grids.items():
        entry = _shuli_entry(num)
        wuge[key] = {
            "num": num,
            "wuxing": _num_wx(num),
            "role": GRID_ROLE[key],
            "level": entry.get("level") or "",
            "poem": entry.get("poem") or "",
            "text": entry.get("text") or "",
            "keywords": entry.get("keywords") or "",
        }
        if entry.get("level_note"):
            wuge[key]["level_note"] = entry["level_note"]

    combo = wuge["tian"]["wuxing"] + wuge["ren"]["wuxing"] + wuge["di"]["wuxing"]
    sancai_entry = _table("sancai-125.json.gz").get(combo)
    if not sancai_entry:
        raise ValueError("三才配置表缺 %s（应有 125 条）" % combo)
    sancai = {
        "combo": combo,
        "tian_ren": _relation_pair(wuge["tian"]["wuxing"], wuge["ren"]["wuxing"]),
        "ren_di": _relation_pair(wuge["ren"]["wuxing"], wuge["di"]["wuxing"]),
        "level": sancai_entry.get("level") or "",
        "text": sancai_entry.get("text") or "",
    }

    ren_wx = wuge["ren"]["wuxing"]
    yunshi = []
    for name, grid_key, table_key, basis in _YUNSHI_DEFS:
        other_wx = wuge[grid_key]["wuxing"]
        entry = _table("yunshi-75.json.gz").get("%s|%s|%s" % (table_key, ren_wx, other_wx))
        if not entry:
            raise ValueError("运势表缺 %s/%s" % (ren_wx, other_wx))
        yunshi.append({
            "name": name,
            "basis": basis,
            "combo": "%s/%s" % (ren_wx, other_wx),
            "relation": _relation_from(ren_wx, other_wx),
            "level": entry.get("level") or "",
            "text": entry.get("text") or "",
        })

    return {
        "kind": "name",
        "surname": surname,
        "given": given,
        "full": surname + given,
        "chars": s_chars + g_chars,
        "wuge": wuge,
        "sancai": sancai,
        "yunshi": yunshi,
    }
