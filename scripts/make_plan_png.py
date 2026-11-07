# -*- coding: utf-8 -*-
"""生成七天排期图（PNG）。纯排版，不依赖网络。

用法：python scripts/make_plan_png.py [输出路径]
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#1b1b1b"
MUTED = "#6b6b6b"
LINE = "#dcd7d0"
ACCENT = "#a8431f"
BG = "#fdfbf7"

ROWS = [
    ("D1", "11/07", "reranker + jieba/324 条术语词典",
     "四组配置的检索对比（bigram / jieba / +rerank）", "10h"),
    ("D2", "11/08", "function calling 改造",
     "单/多 Agent 共用原生 tools 层，30 题零报错", "10h"),
    ("D3", "11/09", "前端 · 对话",
     "React 单页：流式回答、引用展开、会话列表", "10h"),
    ("D4", "11/10", "前端 · 排盘与记忆",
     "八字 / 星盘 / 星座三页 + 记忆管理面板", "10h"),
    ("D5", "11/11", "Postgres + pgvector + Redis + 4 worker",
     "k6 压测报告：P95、错误率；双用户并发不冲突", "12h"),
    ("D6", "11/12", "ECS 部署 + MCP client + 鉴权",
     "公网 /health 与 /chat 通；client 能挂 server", "10h"),
    ("D7", "11/13", "最终评测 + 文档",
     "四套评测重跑（带 code_commit）+ README + 演示脚本", "8h"),
]

FOOT = [
    ("超时砍单顺序", "MCP client → ECS 部署 → 星座独立页"),
    ("仍写进局限", "RAGAS 忠实度 · 盲测集扩容 · 向量记忆 · 多实例高可用"),
]


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"D:\mingli-7day-plan.png")
    fig = plt.figure(figsize=(12, 6.6), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0), 1, 1, facecolor=BG, edgecolor="none"))

    ax.text(0.06, 0.925, "命理古籍 RAG · 七天冲刺排期", fontsize=21, color=INK, weight="bold")
    ax.text(0.06, 0.875, "2026/11/07 – 11/13　约 70 小时　全量不砍",
            fontsize=10.5, color=MUTED)

    x0, x1 = 0.06, 0.94
    top, row_h = 0.815, 0.083
    for i, (day, date, focus, done, hours) in enumerate(ROWS):
        y = top - i * row_h
        if i % 2 == 0:
            ax.add_patch(Rectangle((x0 - 0.015, y - row_h + 0.012), x1 - x0 + 0.03,
                                   row_h - 0.004, facecolor="#f4efe7", edgecolor="none"))
        ax.text(x0, y, day, fontsize=13, color=ACCENT, weight="bold", va="top")
        ax.text(x0 + 0.045, y, date, fontsize=9, color=MUTED, va="top")
        ax.text(x0 + 0.115, y + 0.002, focus, fontsize=11.5, color=INK, va="top")
        ax.text(x0 + 0.115, y - 0.032, done, fontsize=9.2, color=MUTED, va="top")
        ax.text(x1, y + 0.002, hours, fontsize=11, color=INK, ha="right", va="top")

    ax.plot([x0 - 0.015, x1 + 0.015], [0.215, 0.215], color=LINE, lw=1)
    for j, (k, v) in enumerate(FOOT):
        y = 0.175 - j * 0.05
        ax.text(x0, y, k, fontsize=9.5, color=ACCENT, va="top")
        ax.text(x0 + 0.115, y, v, fontsize=9.5, color=MUTED, va="top")
    ax.text(x1, 0.175, "验收：每天最后一小时只做验收与提交", fontsize=9, color=MUTED,
            ha="right", va="top")

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=BG)
    print("saved:", out)


if __name__ == "__main__":
    main()
