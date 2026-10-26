# -*- coding: utf-8 -*-
"""从 results_v2.csv 重新生成 README 用的对比图。

旧 metric_compare.png 是评测口径修复前的数字（dense 25% / bm25 5% / rrf 20%），
中文还是方块；这里统一改成 results_v2.csv 的真实结果。

用法：python eval/make_chart.py
"""
import csv
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "results_v2.csv"
OUT_PATH = HERE.parent / "metric_compare.png"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]  # 已过 dataviz 校验（含对比度补偿：直接标数值）

CJK_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]


def setup_font():
    for p in CJK_CANDIDATES:
        if os.path.exists(p):
            font_manager.fontManager.addfont(p)
            name = font_manager.FontProperties(fname=p).get_name()
            plt.rcParams["font.sans-serif"] = [name]
            plt.rcParams["axes.unicode_minus"] = False
            return name
    raise SystemExit("找不到中文字体，请把 msyh.ttc / simhei.ttf 的路径加进 CJK_CANDIDATES")


def load_means():
    rows = [r for r in csv.DictReader(open(CSV_PATH, encoding="utf-8-sig"))
            if r["answerable"] == "True"]
    def mean(col):
        return sum(float(r[col]) for r in rows) / len(rows) * 100
    return {
        "dense": [mean("dense_exact_recall"), mean("dense_line_recall"), mean("dense_line_mrr")],
        "bm25": [mean("bm25_exact_recall"), mean("bm25_line_recall"), mean("bm25_line_mrr")],
        "rrf": [mean("rrf_exact_recall"), mean("rrf_line_recall"), mean("rrf_line_mrr")],
    }, len(rows)


def rounded_bar(fig, ax, x, height, width, color, radius_px=4):
    """数据端圆角、基线端贴平的柱子。

    圆角要用像素而不是数据单位，否则 50% 的柱子高度下圆角会被拉成 0.3px。
    所以先把数据坐标换算成显示坐标，再用 IdentityTransform 画；底端多伸出一个
    圆角半径，靠 axes 的 bbox 裁掉，得到平底。
    """
    x0, y0 = ax.transData.transform((x - width / 2, 0))
    x1, y1 = ax.transData.transform((x + width / 2, height))
    patch = FancyBboxPatch(
        (x0, y0 - radius_px), x1 - x0, (y1 - y0) + radius_px,
        boxstyle=f"round,pad=0,rounding_size={radius_px}",
        linewidth=0, facecolor=color, transform=None, zorder=3,
    )
    patch.set_clip_box(ax.bbox)
    fig.add_artist(patch)


def main():
    setup_font()
    data, n = load_means()
    metrics = ["Recall@5（exact）", "Recall@5（line）", "MRR（line）"]
    strategies = ["dense", "bm25", "rrf"]
    tick = ["dense\n向量单路", "BM25\n关键词单路", "RRF\n双路融合"]

    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    width, gap = 0.235, 0.012
    offsets = [-(width + gap), 0, (width + gap)]
    ax.set_xticks(range(len(strategies)))
    ax.set_xticklabels(tick, fontsize=10, color=INK_2)
    ax.set_xlim(-0.5, 2.5)
    ax.set_ylim(0, 100)
    ax.set_yticks(range(0, 101, 20))
    ax.set_yticklabels([f"{v}%" for v in range(0, 101, 20)], fontsize=9, color=MUTED)
    ax.tick_params(axis="both", length=0, pad=6)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.spines["bottom"].set_linewidth(1)

    ax.set_title(f"三档检索策略：Recall@5 与 MRR（{n} 条可答题，top-k=5）",
                 fontsize=13, color=INK, pad=28, loc="left")
    ax.text(0, 1.045, "同一评测集、同一 chunk 语料；line 口径 = 命中同一本书且行区间相交",
            transform=ax.transAxes, fontsize=9, color=MUTED)

    handles = [plt.Line2D([], [], color=c, linewidth=6) for c in SERIES]
    ax.legend(handles, metrics, loc="upper left", bbox_to_anchor=(0, -0.16),
              ncol=3, frameon=False, fontsize=9, labelcolor=INK_2,
              handlelength=1.2, columnspacing=1.6)

    fig.tight_layout()
    fig.canvas.draw()  # 固定坐标变换后再画柱子（圆角要按像素算）
    for j, metric in enumerate(metrics):
        for i, s in enumerate(strategies):
            rounded_bar(fig, ax, i + offsets[j], data[s][j], width, SERIES[j])

    # 数值标签画在图形层：柱子是 figure artist，axes 里的 text 会被盖住
    w_px, h_px = fig.get_size_inches() * fig.dpi
    for j, metric in enumerate(metrics):
        for i, s in enumerate(strategies):
            v = data[s][j]
            xd, yd = ax.transData.transform((i + offsets[j], v))
            fig.text(xd / w_px, (yd + 4) / h_px, f"{v:.1f}", ha="center", va="bottom",
                     fontsize=8.5, color=INK, zorder=5)

    fig.savefig(OUT_PATH, facecolor=SURFACE)
    print(f"已生成 {OUT_PATH}")
    for s in strategies:
        print(s, [round(v, 1) for v in data[s]])


if __name__ == "__main__":
    main()
