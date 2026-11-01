# -*- coding: utf-8 -*-
"""排盘模块：八字 / 星盘 / 塔罗。

这三块和 RAG 那条链路的关系是：

- **排盘是确定性计算**，不经过大模型。同样的出生信息，任何时候算出同一个盘。
  这一点很重要：如果让模型"算"，它每次给的干支都可能不一样，那是错的。
- **解读**才用大模型，而且只允许基于排盘结果里已经算出来的字段说话。

所以模块边界是：这里只负责"算出盘"，不负责"讲吉凶"。
"""
from .astro import format_chart as format_astro
from .astro import natal_chart
from .bazi import format_bazi
from .bazi import paipan as paipan_bazi
from .tarot import draw as draw_tarot
from .tarot import format_draw as format_tarot

__all__ = [
    "paipan_bazi",
    "format_bazi",
    "natal_chart",
    "format_astro",
    "draw_tarot",
    "format_tarot",
]
