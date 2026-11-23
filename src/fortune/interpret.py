# -*- coding: utf-8 -*-
"""把排盘结果讲成人话。

分工要说清楚，这是这个模块存在的理由：

- 盘是**算**出来的（fortune.bazi / astro / tarot），字段固定、可复现；
- 解读是**讲**出来的，允许模型组织语言，但不允许它改盘。

所以进 prompt 的盘面是工具返回的原文，并且明确告诉模型：
干支、行星度数、牌面都已经是既定事实，你只能解释，不能重算。
一旦允许模型"顺便推一下"，它就会开始编——而编出来的东西用户分辨不了。

解读会先按盘面关键词 + 用户问题检索几段古籍，作为**术语与结构的说明材料**
一起进 prompt。检索只是增强：语料或 embedding 不可用时退化为纯盘面解读，
不会让整个解读失败。片段和盘面冲突时以盘面为准；引用只允许来自本轮片段，
编号越界的引用直接丢掉。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DISCLAIMER = (
    "以上为传统文化视角的说明，仅供文化研究与娱乐参考，不是预测，"
    "不构成医疗、法律、投资或人生决策建议。"
)

SYSTEM_PROMPT = """你是古籍文化解读助手，负责用传统文化视角说明已经算好的盘面（仅供文化研究与娱乐参考）。规则：

1. 盘面数据（干支、行星位置、牌面）是系统算好的既定事实，**不得修改、不得重新推算、不得补充盘面里没有的星体或神煞**。
2. 只解释盘面里出现的字段。想引用古籍说法时，只能引用【古籍片段】里的原文，并在句末用 [n] 标注片段编号；没有片段支撑就按盘面讲，不要假装引用。
3. 片段只用于说明术语和结构，不能用来预测。片段和盘面冲突时以盘面为准，**不得把片段里出现、盘面里没有的星体或神煞补进盘面**。
4. 用倾向性语言（"容易…""倾向于…"），不用断言（"你一定会…""注定…"）。不做生死、疾病、灾祸、婚姻成败、考试录取、投资与彩票结果的预测。
5. 不评判好坏，讲结构和偏向：这个配置擅长什么、在哪里容易卡住、可以怎么用。不给改运、消灾、转运类建议。
6. 用户给了具体问题，就正面回答这个问题：summary 就是对这个问题的回答，sections 围绕它展开。**不管问什么都把整张盘从头讲一遍是错误回答**——那等于没看问题。只有用户没给问题时，才做整体解读。
7. 涉及健康、法律、投资的问题，明确说明这超出解读范围，建议找专业人士。

只输出 JSON，不要输出 JSON 以外的文字：
{
  "summary": "三句话以内：用户有问题就直接回答这个问题，没问题才给整体印象",
  "sections": [{"title": "小标题", "content": "这一段的内容"}],
  "citations": [1, 3],
  "disclaimer": "一句提醒"
}
citations 只能写【古籍片段】里出现过的编号；没有引用就写 []。不要在正文里编造片段编号。
"""

# 三种盘各自希望模型覆盖的角度。写死在代码里，避免模型每次自由发挥结构不一致。
SECTION_HINTS = {
    "bazi": "性格底色（日主与十神）、关系与相处方式、事业学业取向、当前大运阶段、需要注意的倾向",
    "astro": "核心人格（太阳/月亮/上升）、情感与关系、事业与表达、盘面张力（四分相/对分相）、成长方向",
    "tarot": "整体氛围、逐张说明它在对应位置的含义、几张牌之间的呼应、可供自我反思的提问",
    "name": "用字的字义与五行、五格（天/人/地/外/总）各自的数理与主管、三才配置、三大运势，并说明这套体系能说明什么、不能说明什么",
}

# 送进 prompt 的盘类型名。新增盘种时三处必须一起加：chart_context.KINDS、
# SECTION_HINTS、这里——少一处就会在 /read 里 KeyError（姓名就踩过）。
KIND_LABELS = {
    "bazi": "八字命盘",
    "astro": "西方本命星盘",
    "tarot": "塔罗牌阵",
    "name": "姓名五格（1928 年以来的现代数理体系，不是古籍）",
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
    if kind == "name":
        # 姓名盘全是查表结果：把每格的「数 + 五行 + 吉凶 + 说明」都送进去，
        # 模型只负责组织语言，不负责判断吉凶。
        wuge = chart["wuge"]
        grid_names = (
            ("tian", "天格"), ("ren", "人格"), ("di", "地格"),
            ("wai", "外格"), ("zong", "总格"),
        )
        return {
            "姓名": chart["full"],
            "姓": chart["surname"],
            "名": chart["given"],
            "用字": [
                {
                    "字": item["char"],
                    "位": item["role"],
                    "康熙笔画": item["kangxi"],
                    "字义五行": item["wuxing"],
                    "部首": item["radical"],
                    "拼音": item["pinyin"],
                    "结构": item["structure"],
                }
                for item in chart["chars"]
            ],
            "五格": {
                label: {
                    "数": wuge[key]["num"],
                    "五行": wuge[key]["wuxing"],
                    "主管": wuge[key]["role"],
                    "吉凶": wuge[key]["level"],
                    "诗诀": wuge[key]["poem"],
                    "说明": wuge[key]["text"],
                }
                for key, label in grid_names
            },
            "三才": {
                "配置": chart["sancai"]["combo"],
                "天对人格": chart["sancai"]["tian_ren"],
                "人对地格": chart["sancai"]["ren_di"],
                "吉凶": chart["sancai"]["level"],
                "说明": chart["sancai"]["text"],
            },
            "三运": [
                {
                    "名": item["name"],
                    "看": item["basis"],
                    "五行": item["combo"],
                    "关系": item["relation"],
                    "吉凶": item["level"],
                    "说明": item["text"],
                }
                for item in chart["yunshi"]
            ],
        }
    if kind == "physiognomy":
        # 相术没有程序算出来的盘：进 prompt 的是用户确认过的特征卡。
        # 字段名带「用户自述」，免得模型把它当成图像识别的结论。
        subject = str(chart.get("subject") or "").strip()
        features = chart.get("features")
        if subject not in ("面相", "手相") or not isinstance(features, dict) or not features:
            # 空卡等于没带盘：让上游退化成普通问答，比送一张空表进 prompt 好
            return {}
        clean = {
            str(key).strip(): str(value).strip()
            for key, value in list(features.items())[:16]
            if str(key).strip() and str(value).strip()
        }
        if not clean:
            return {}
        return {
            "类型": subject,
            "用户自述特征": clean,
            "补充": str(chart.get("note") or "").strip()[:120],
        }
    return chart


def _retrieval_query(chart, question=None):
    """把盘面关键词和用户问题拼成检索问句。

    这个问句只用于检索，不展示给用户。没有它，解读就只能靠模型的通用知识；
    有了它，模型能拿到和这张盘相关的术语解释与古籍原文。
    """
    kind = chart.get("kind")
    bits = []

    if kind == "bazi":
        day_master = str(chart.get("day_master") or "").strip()
        if day_master:
            bits.append("日主 " + day_master)
        shishen = [
            str(value).strip()
            for value in (chart.get("shishen_gan") or {}).values()
            if str(value).strip()
        ]
        if shishen:
            bits.append("十神 " + " ".join(dict.fromkeys(shishen)))
        wuxing = chart.get("wuxing") or {}
        strong = [
            key for key, _ in
            sorted(wuxing.items(), key=lambda kv: -int(kv[1] or 0))[:2]
        ]
        if strong:
            bits.append("五行 " + " ".join(strong))
        missing = [str(x) for x in (chart.get("wuxing_missing") or []) if str(x)]
        if missing:
            bits.append("缺 " + " ".join(missing))
    elif kind == "astro":
        asc = (chart.get("asc") or {}).get("sign")
        if asc:
            bits.append("上升 " + str(asc))
        for planet in (chart.get("planets") or [])[:6]:
            name = str(planet.get("name") or "").strip()
            sign = str(planet.get("sign") or "").strip()
            if name:
                bits.append(name + sign)
        aspects = [
            str(item.get("aspect") or "").strip()
            for item in (chart.get("aspects") or [])[:4]
        ]
        aspects = [item for item in aspects if item]
        if aspects:
            bits.append("相位 " + " ".join(aspects))
    elif kind == "tarot":
        spread = str(chart.get("spread") or "").strip()
        if spread:
            bits.append("塔罗 " + spread)
        for card in chart.get("cards") or []:
            name = str(card.get("name") or "").strip()
            if name:
                bits.append(name)
    elif kind == "physiognomy":
        subject = str(chart.get("subject") or "").strip()
        if subject:
            bits.append(subject)
        features = chart.get("features") or {}
        if isinstance(features, dict):
            # 只取前 8 项，特征卡再长也不该把检索问句撑成一段作文
            for key, value in list(features.items())[:8]:
                value = str(value or "").strip()
                if value:
                    bits.append(f"{key}{value}")
    elif kind == "name":
        # 语料里没有姓名学专著，能搜到的是五行、字义一类的说明；
        # 五格剖象是 1928 年的现代体系，检索只为解释用字与五行。
        wx = [
            str(item.get("wuxing") or "").strip()
            for item in chart.get("chars") or []
        ]
        wx = [item for item in wx if item]
        if wx:
            bits.append("用字五行 " + " ".join(dict.fromkeys(wx)))
        combo = str((chart.get("sancai") or {}).get("combo") or "").strip()
        if combo:
            bits.append("三才 " + combo)

    q = str(question or "").strip()
    if q:
        bits.append(q)
    return " ".join(bits).strip()


def _retrieve_fragments(chart, question=None, top_k=5):
    """按盘面 + 问题检索古籍片段；返回 (hits, query)。

    单独抽成函数是为了让测试能在不加载语料和 embedding 的情况下替换掉它。
    """
    query = _retrieval_query(chart, question)
    if not query:
        return [], ""
    # 和 rag 一样延迟导入：retrieval 会加载语料和 34MB embedding。
    from retrieval import retrieve_one

    return retrieve_one(query, top_k=top_k, mode="rrf"), query


def _attach_citations(data, hits):
    """把解读里的 [n] 映射成 chunk_id；越界编号丢掉，不报错。

    和 RAG 的差别：盘面本身就是确定性证据，解读没有引用**不算不合规**，
    所以这里只做校验和映射，不把结果改判成拒答或 invalid_output。
    """
    cited = data.get("citations") if isinstance(data, dict) else None
    if not isinstance(cited, list):
        cited = []

    valid, invalid = [], []
    for n in cited:
        if isinstance(n, int) and 1 <= n <= len(hits):
            if n not in valid:  # 同一个片段被引用多次，只留一条出处
                valid.append(n)
        else:
            invalid.append(n)

    return {
        "citations_chunk_ids": [hits[n - 1]["chunk_id"] for n in valid],
        "citation_map": [
            {"marker": n, "chunk_id": hits[n - 1]["chunk_id"]} for n in valid
        ],
        "invalid_citations": invalid,
        "retrieved_chunk_ids": [hit["chunk_id"] for hit in hits],
    }


def read(chart, question=None, user_note=None, temperature=0.7, api_key=None,
         top_k=5):
    """生成解读。返回 {summary, sections, disclaimer, kind, citations...}。

    Args:
        chart: 排盘结果（bazi / astro / tarot 三个函数返回的 dict）。
        question: 用户具体想问的事，可以为空。
        user_note: 用户补充的处境（比如"正在准备实习"），会一起给模型。
        api_key: 访客自带的 key；不传就读环境变量。公网 Demo 没配服务端 key 时用。
        top_k: 检索几段古籍作为解读材料。检索失败不影响解读。
    """
    kind = chart.get("kind", "")
    if kind not in SECTION_HINTS:
        raise ValueError("不支持的盘类型：%s" % kind)

    hits, retrieval_query = [], ""
    try:
        hits, retrieval_query = _retrieve_fragments(chart, question, top_k=top_k)
    except Exception as exc:
        # 检索是增强，不是主链路：embedding/语料缺失时按纯盘面解读继续，
        # 但要在 stderr 留痕，否则线上会悄悄退化成"模型自由发挥"。
        print(
            "[warn] 盘面解读检索失败，按纯盘面解读继续：{}".format(exc),
            file=sys.stderr,
        )

    parts = [
        "【盘类型】" + KIND_LABELS[kind],
        "【盘面数据】\n" + json.dumps(_payload(chart), ensure_ascii=False, indent=2),
    ]
    if hits:
        # 和 rag 用同一套片段格式，编号 [n] 的含义在两条链路里一致。
        from rag import build_context

        parts.append("【古籍片段】\n" + build_context(hits))
    else:
        parts.append("【古籍片段】\n（本轮没有检索到可用片段，不要引用任何古籍。）")
    if question:
        parts.append("【用户的问题】\n" + str(question).strip())
    if user_note:
        parts.append("【用户补充的处境】\n" + str(user_note).strip())
    if question:
        # 有问题就按问题组织回答。以前这里无条件附上 SECTION_HINTS，
        # 结果同一张盘换任何问题都吐同一套五节整体解读——线上实测三问三同。
        parts.append(
            "【回答要求】\n"
            "本轮以【用户的问题】为中心：summary 直接给出这个问题的答案；"
            "sections 按问题本身拆成 1–3 节，只讲与它直接相关的盘面与古籍说法。"
            "不要为了覆盖一般角度把整张盘再讲一遍；与问题无关的方面可以一句带过或不写。"
        )
    else:
        parts.append("【希望覆盖的角度】\n" + SECTION_HINTS[kind])

    # rag 会加载语料和 34MB embedding；放到真正要解读时才导入，
    # 否则 Streamlit 首屏要等十几秒。
    from rag import _chat, _parse_json

    raw = _chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n\n".join(parts)},
        ],
        temperature=temperature,
        api_key=api_key,
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
            "retrieval_query": retrieval_query,
            **_attach_citations({}, hits),
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
        "retrieval_query": retrieval_query,
        **_attach_citations(data, hits),
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
