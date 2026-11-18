# -*- coding: utf-8 -*-
"""译文忠实度的确定性检查：只抓「译文里出现了原文没有的东西」。

边界先说清楚：这是**筛查器，不是判决书**。

- 命中不等于译错。原文「故」译成「所以」是对的，但这条规则看的是「译文有因果词、
  原文没有任何因果词」，前提不满足才报；即便如此，也可能原文用更隐蔽的方式
  （如两句并置）表达了因果，机器人看不懂。
- 漏掉不等于译对。模型可以一个连词都不加，直接把意思改了。真正的忠实度要靠
  `eval/eval_interpret.py` 的逐段判断（模型当评委 + 人工抽检），这里只负责把
  「一眼能看出越界」的那几类挑出来：确定性、可复现、零成本。

用途有两个：
1. 跑批时给出违规率，替代「看着还行」；
2. 线上单段译文先自检一次，命中「硬伤」就带着纠正要求重译一次（见 interpret.translate）。
"""
from __future__ import annotations

import difflib
import re
from typing import Any

# 译文里的因果/条件表达。只收明确的连词，不把「即」「则」这种高频道词算进来。
TRANSLATION_CONNECTIVES = (
    "因为", "因此", "所以", "由于", "故而", "以致", "导致", "从而", "进而",
    "于是", "使得", "只要", "如果", "假如", "一旦", "除非", "否则",
)
# 文言里的因果/条件表达。只要原文出现任意一个，就不判「凭空补出因果」。
# 刻意不收音近的常用字：「令」（月令）、「使」（使者）、「如」（如此）、
# 「则」「即」「盖」在文言里出现得太频繁，收进来等于让这条规则永不触发。
SOURCE_CONNECTIVES = (
    "故", "因", "是以", "是故", "所以", "由是", "遂", "于是", "致", "缘",
    "若", "倘", "苟",
)
# 转折：原文有，译文没有，多半是模型嫌麻烦把话捋顺了。
SOURCE_CONTRAST = ("虽", "然", "但", "却", "犹", "尚", "顾", "抑")
TRANSLATION_CONTRAST = ("虽然", "虽", "然而", "但是", "但", "不过", "却", "可是",
                        "仍然", "还是", "尚且", "只是")
# 直接把原文变成建议/结论的说法（提示词第 3 条禁止）。
ADVICE_PATTERNS = ("你会", "你可以", "你应", "你要", "你需要", "建议你", "建议您",
                   "对你", "有助于你", "有利于你")
# 把对译写成讲解的说法（提示词第 1 条禁止）。
EXPLAIN_PATTERNS = ("也就是说", "换言之", "换句话说", "意思是", "这里指", "指的是")

# 标点、空白不计入相似度：只替换了标点不叫翻译。
_PUNCT = re.compile(r"[\s，。、；：！？「」『』（）《》·,.;:!?()\[\]{}—…\"'“”‘’]")
# 0.97 是量出来的：真译文里「干支清单」这类内容会天然高度重合（实测最高 0.922，
# 见 eval/results_interpret 的 probe 记录），超过这个值基本就是原文照搬。
COPIED_RATIO = 0.97
# 0.90–0.97 这一档（只换「亦→也」这类虚词）刻意不设提示：30 段抽样里 5 段落在
# 这一档，评委只在其中一次跑批判过 3 段「未真正翻译」，另一次跑批全部通过。
# 规则分不清「忠于字面的直译」和「没译完」，加提示只会让读者疑神疑鬼。

HARD_RULES = frozenset({"causal_added", "second_person", "explained", "copied_source"})
SOFT_RULES = frozenset({"contrast_dropped", "term_dropped", "omission_suspect"})


def _present(text: str, needles: tuple[str, ...]) -> list[str]:
    return [n for n in needles if n in text]


def check(source: str, translation: str, terms: list[str] | None = None) -> list[dict[str, Any]]:
    """返回违规列表：[{rule, severity, detail}]。`terms` 是原文里出现的术语名。"""
    src = source or ""
    out = translation or ""
    hits: list[dict[str, Any]] = []

    norm_src = _PUNCT.sub("", src)
    norm_out = _PUNCT.sub("", out)
    if norm_src and norm_out and (
        norm_src == norm_out
        or difflib.SequenceMatcher(None, norm_src, norm_out).ratio() >= COPIED_RATIO
    ):
        hits.append({
            "rule": "copied_source",
            "severity": "hard",
            "detail": "译文与原文几乎逐字相同，没有真正翻译（可能只换了标点）",
        })

    conn = _present(out, TRANSLATION_CONNECTIVES)
    if conn and not _present(src, SOURCE_CONNECTIVES):
        hits.append({
            "rule": "causal_added",
            "severity": "hard",
            "detail": "译文用了「{}」，原文没有任何因果/条件表达".format("、".join(conn)),
        })

    if ("你" in out or "您" in out) and not _present(src, ("汝", "尔", "子", "君", "卿")):
        hits.append({
            "rule": "second_person",
            "severity": "hard",
            "detail": "译文出现第二人称「你/您」，原文是第一/第三人称叙述",
        })

    explain = _present(out, EXPLAIN_PATTERNS)
    if explain:
        hits.append({
            "rule": "explained",
            "severity": "hard",
            "detail": "译文出现讲解语「{}」，把对译写成了释义".format("、".join(explain)),
        })

    if _present(src, SOURCE_CONTRAST) and not _present(out, TRANSLATION_CONTRAST):
        hits.append({
            "rule": "contrast_dropped",
            "severity": "soft",
            "detail": "原文有转折/让步（{}），译文没有对应表达".format(
                "、".join(_present(src, SOURCE_CONTRAST))),
        })

    dropped = [t for t in (terms or []) if t and t not in out]
    if dropped:
        hits.append({
            "rule": "term_dropped",
            "severity": "soft",
            "detail": "原文术语在译文里没保留：{}".format("、".join(dropped[:8])),
        })

    if len(src) >= 100 and len(out) < len(src) * 0.45:
        hits.append({
            "rule": "omission_suspect",
            "severity": "soft",
            "detail": "译文 {} 字 / 原文 {} 字，可能概括代替了对译".format(len(out), len(src)),
        })

    return hits


def hard_rules(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [h for h in hits if h["severity"] == "hard"]


def source_terms(text: str, limit: int = 20) -> list[str]:
    """原文里能被词典认出来的术语。terms 模块加载失败时返回空，不影响检查本身。"""
    try:
        import terms as terms_mod

        return [span["term"] for span in terms_mod.annotate(text, limit=limit)]
    except Exception:  # noqa: BLE001 - 词典坏了不该让译文生成失败
        return []


def summarize(hits: list[dict[str, Any]]) -> list[str]:
    """给人看的一句话提示，存进接口返回的 warnings。"""
    return [h["detail"] for h in hits]
