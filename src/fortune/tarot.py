# -*- coding: utf-8 -*-
"""塔罗抽牌。

78 张：22 张大阿卡纳 + 4 组小阿卡纳（权杖/圣杯/宝剑/星币，各 14 张）。

抽牌必须**可复现**：同一个 seed 抽出同一组牌，否则"再抽一次"就成了刷结果，
用户会一直抽到满意为止——那就不是占卜，是自欺。seed 默认取当前时间，
所以真实使用是随机的，但测试和复现时可以固定。
"""
from __future__ import annotations

import random
import time

MAJORS = [
    ("愚者", "新的开始、跃入未知、纯粹的可能性", "鲁莽、逃避责任、原地打转"),
    ("魔术师", "资源齐备、主动创造、把想法变成现实", "空谈、操纵、能力用错方向"),
    ("女祭司", "直觉、未说出口的信息、静观", "忽视直觉、信息被隐瞒、疏离"),
    ("女皇", "丰饶、滋养、创造力与身体的连接", "过度付出、依赖、创造力受阻"),
    ("皇帝", "秩序、边界、掌控与责任", "僵化、控制欲、权威压迫"),
    ("教皇", "传统、师承、既定的规则与体系", "教条、反叛、形式大于实质"),
    ("恋人", "选择、结合、价值观的契合", "摇摆、错配、逃避选择"),
    ("战车", "意志推进、方向明确、克服阻力", "失控、方向不明、硬撑"),
    ("力量", "温和的坚持、驯服本能、内在韧性", "自我怀疑、被情绪牵着走"),
    ("隐士", "独处、内省、寻找自己的答案", "孤立、拒绝求助、钻牛角尖"),
    ("命运之轮", "周期转动、时机、无法预料的转折", "时机未到、重复同样的循环"),
    ("正义", "因果、权衡、为自己的选择负责", "失衡、偏颇、逃避责任"),
    ("倒吊人", "暂停、换视角、以退为进", "无谓的牺牲、拖延、卡住不动"),
    ("死神", "结束与转化、旧结构必须退场", "抗拒结束、拖着不放、停滞"),
    ("节制", "调和、节奏、两种力量的融合", "失衡、急躁、过度"),
    ("恶魔", "执着、诱惑、被欲望或关系捆住", "松绑、看清束缚、走出依赖"),
    ("高塔", "突然的崩塌、虚假结构的瓦解", "延迟的崩塌、内在的动摇"),
    ("星星", "希望、疗愈、长远的指引", "失望、信心不足、看不清方向"),
    ("月亮", "模糊、潜意识、尚未显形的恐惧", "迷雾散去、真相浮现、焦虑缓解"),
    ("太阳", "清晰、成就、坦荡的喜悦", "暂时的阴影、过度乐观、延迟的成果"),
    ("审判", "召唤、清算、重新出发", "回避反思、旧账未了、自我批判"),
    ("世界", "完成、整合、一个阶段的收束", "差最后一步、未竟、循环未闭"),
]

SUITS = {
    "权杖": "行动、热情、事业与创造力的推进",
    "圣杯": "情感、关系、直觉与内心的流动",
    "宝剑": "思维、沟通、冲突与判断",
    "星币": "现实、金钱、身体与具体的成果",
}

RANKS = {
    "Ace": "起点、纯粹的种子、一次机会",
    "2": "二元、选择、关系的建立",
    "3": "初步成果、协作、扩张",
    "4": "稳定、结构、停下来巩固",
    "5": "冲突、损失、被打破的平衡",
    "6": "回流、和解、给予与接受",
    "7": "评估、诱惑、坚持与怀疑",
    "8": "推进、重复、专注的投入",
    "9": "接近完成、独自承担、临界的满足",
    "10": "终点、满溢、一个周期的完成",
    "侍从": "消息、学习、年轻的开始",
    "骑士": "行动、推进、带着方向出发",
    "王后": "承接、滋养、内在的成熟",
    "国王": "掌控、决断、外在的成熟",
}

SPREADS = {
    "single": ("单张指引", ["整体提示"]),
    "three": ("三张牌", ["过去", "现在", "未来"]),
    "cross": ("五张牌", ["现状", "阻碍", "根源", "建议", "结果"]),
}


def _deck():
    """78 张牌的完整列表。"""
    cards = []
    for i, (name, up, rev) in enumerate(MAJORS):
        cards.append({"id": i, "name": name, "arcana": "大阿卡纳", "up": up, "rev": rev})
    for suit, theme in SUITS.items():
        for rank, rank_meaning in RANKS.items():
            cards.append({
                "id": len(cards),
                "name": "%s%s" % (suit, rank),
                "arcana": "小阿卡纳",
                "suit": suit,
                "suit_theme": theme,
                "up": "%s；%s" % (theme, rank_meaning),
                "rev": "%s受阻或过头：%s" % (theme.split("、")[0], rank_meaning),
            })
    return cards


DECK = _deck()


def draw(n=3, seed=None, spread=None):
    """抽 n 张牌，返回带位置和正逆位的结构。

    Args:
        n: 张数（1–10）。spread 给了就按 spread 的位置数来。
        seed: 固定随机种子，便于复现；None 时用当前时间。
    """
    if spread:
        if spread not in SPREADS:
            raise ValueError("spread 只能是 %s" % "、".join(SPREADS))
        n = len(SPREADS[spread][1])
    n = max(1, min(int(n), 10))

    rng = random.Random(seed if seed is not None else time.time_ns())
    picked = rng.sample(DECK, n)
    positions = SPREADS[spread][1] if spread else ["第%d张" % (i + 1) for i in range(n)]

    result = []
    for pos, card in zip(positions, picked):
        upright = rng.random() >= 0.5
        result.append({
            "position": pos,
            "name": card["name"],
            "arcana": card["arcana"],
            "orientation": "正位" if upright else "逆位",
            "meaning": card["up"] if upright else card["rev"],
            "card_id": card["id"],
        })

    return {
        "kind": "tarot",
        "spread": SPREADS[spread][0] if spread else "%d 张牌" % n,
        "seed": seed,
        "cards": result,
        "text": format_draw(result),
    }


def format_draw(cards):
    lines = []
    for c in cards:
        lines.append("%s｜%s（%s）：%s" % (c["position"], c["name"], c["orientation"], c["meaning"]))
    return "\n".join(lines)


if __name__ == "__main__":
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print(format_draw(draw(3, seed=42)["cards"]))
