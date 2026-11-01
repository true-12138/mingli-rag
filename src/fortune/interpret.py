# -*- coding: utf-8 -*-
"""把排盘结果讲成人话。

分工要说清楚，这是这个模块存在的理由：

- 盘是**算**出来的（fortune.bazi / astro / tarot），字段固定、可复现；
- 解读是**讲**出来的，允许模型组织语言，但不允许它改盘。

所以进 prompt 的盘面是工具返回的原文，并且明确告诉模型：
干支、行星度数、牌面都已经是既定事实，你只能解释，不能重算。
一旦允许模型"顺便推一下"，它就会开始编——而编出来的东西用户分辨不了。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag import _chat, _parse_json

DISCLAIMER = (
    "以上为传统文化视角的解读，属于文化娱乐内容，不构成医疗、法律、投资或人生决策建议。"
    "命盘描述的是倾向，不是注定；具体选择仍取决于你自己。"
)

SYSTEM_PROMPT = """你是命理解读助手，负责把已经算好的盘面讲清楚。规则：

1. 盘面数据（干支、行星位置、牌面）是系统算好的既定事实，**不得修改、不得重新推算、不得补充盘面里没有的星体或神煞**。
2. 只解释盘面里出现的字段。想引用古籍说法时，只能引用用户提供的片段；没有片段就不要假装引用。
3. 用倾向性语言（"容易…""倾向于…"），不用断言（"你一定会…""注定…"）。不做生死、疾病、灾祸、婚姻成败的预测。
4. 不评判好坏，讲结构和偏向：这个配置擅长什么、在哪里容易卡住、可以怎么用。
5. 结合用户给出的具体问题；没问题就做整体解读。
6. 涉及健康、法律、投资的问题，明确说明这超出解读范围，建议找专业人士。

只输出 JSON，不要输出 JSON 以外的文字：
{
  "summary": "三句话以内的整体印象",
  "sections": [{"title": "小标题", "content": "这一段的内容"}],
  "disclaimer": "一句提醒"
}
"""

# 三种盘各自希望模型覆盖的角度。写死在代码里，避免模型每次自由发挥结构不一致。
SECTION_HINTS = {
    "bazi": "性格底色（日主与十神）、关系与相处方式、事业学业取向、当前大运阶段、需要注意的倾向",
    "astro": "核心人格（太阳/月亮/上升）、情感与关系、事业与表达、盘面张力（四分相/对分相）、成长方向",
    "tarot": "整体氛围、逐张说明它在对应位置的含义、几张牌之间的呼应、可执行的建议",
}


def _payload(chart):
    """只把解读需要的字段送进 prompt，整盘 JSON 太吵。"""
    kind = chart.get("kind")
    if kind == "bazi":
        return {
            "四柱": chart["sizhu"],
            "日主": chart["day_master"],
            "十神": chart["shishen_gan"],
            "地支十神": chart["shishen_zhi"],
            "藏干": chart["canggan"],
            "五行": chart["wuxing"],
            "五行缺": chart["wuxing_missing"],
            "纳音": chart["nayin"],
            "起运": chart["qiyun"],
            "大运": chart["dayun"][:6],
            "当前大运": chart["current_dayun"],
        }
    if kind == "astro":
        return {
            "上升": chart["asc"],
            "天顶": chart["mc"],
            "行星": chart["planets"],
            "主要相位": chart["aspects"][:8],
            "元素": chart["elements"],
            "三分类": chart["modalities"],
            "宫制": chart["house_system"],
        }
    if kind == "tarot":
        return {"牌阵": chart["spread"], "牌面": chart["cards"]}
    return chart


def read(chart, question=None, user_note=None, temperature=0.7):
    """生成解读。返回 {summary, sections, disclaimer, kind}。

    Args:
        chart: 排盘结果（bazi / astro / tarot 三个函数返回的 dict）。
        question: 用户具体想问的事，可以为空。
        user_note: 用户补充的处境（比如"正在准备实习"），会一起给模型。
    """
    kind = chart.get("kind", "")
    if kind not in SECTION_HINTS:
        raise ValueError("不支持的盘类型：%s" % kind)

    parts = [
        "【盘类型】" + {"bazi": "八字命盘", "astro": "西方本命星盘", "tarot": "塔罗牌阵"}[kind],
        "【盘面数据】\n" + json.dumps(_payload(chart), ensure_ascii=False, indent=2),
    ]
    if question:
        parts.append("【用户的问题】\n" + str(question).strip())
    if user_note:
        parts.append("【用户补充的处境】\n" + str(user_note).strip())
    parts.append("【希望覆盖的角度】\n" + SECTION_HINTS[kind])

    raw = _chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(parts)},
        ],
        temperature=temperature,
    )
    try:
        data = _parse_json(raw)
    except json.JSONDecodeError:
        # 解读不是评测项，解析失败就原样返回，别让整个页面崩掉
        return {
            "kind": kind,
            "summary": "",
            "sections": [{"title": "解读", "content": raw.strip()}],
            "disclaimer": DISCLAIMER,
            "parse_error": True,
        }

    sections = data.get("sections") or []
    if not isinstance(sections, list):
        sections = []
    sections = [
        {"title": str(s.get("title") or ""), "content": str(s.get("content") or "")}
        for s in sections if isinstance(s, dict)
    ]
    return {
        "kind": kind,
        "summary": str(data.get("summary") or ""),
        "sections": sections,
        "disclaimer": str(data.get("disclaimer") or DISCLAIMER),
        "parse_error": False,
    }


def has_api_key():
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


if __name__ == "__main__":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    from .bazi import paipan

    chart = paipan(1995, 8, 20, 14, 30, "male")
    res = read(chart, question="适合做什么方向的工作？")
    print(res["summary"])
    for s in res["sections"]:
        print("\n##", s["title"])
        print(s["content"])
    print("\n", res["disclaimer"])
