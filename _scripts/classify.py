#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
术数语料分类 / 排他 / 统计。只读 01-classics 与 03-terminology，只写 _meta/。

输出：
  _meta/books.json                  155 部书的完整元数据（切分时当 metadata 用）
  _meta/books.tsv                   shell 友好视图：title<TAB>school<TAB>use
  _meta/exclude.txt                 排除清单 + 原因
  _meta/corpus-stats.tsv            按体系汇总
  _meta/terminology-system-map.tsv  03 的 group -> 体系

用法：python3 _scripts/classify.py [--repo DIR]
"""
import argparse, collections, json, os, sys

# ── 一、155 部书的体系归属（人工核定）────────────────────────────────────────
SCHOOLS = {
    "08_八字禄命": ["三命通会", "五行精纪", "李虚中命书", "玉照定真经", "玉照神应真经", "珞琭子赋注",
                    "珞琭子三命消息赋注", "徐氏珞琭子赋注", "三命指迷赋", "兰台妙选", "渊海子平",
                    "子平真诠评注", "滴天髓阐微", "穷通宝鉴", "神峰通考", "命理正宗", "命理探源",
                    "千里命稿", "月谈赋"],
    "07_星命七政四余": ["张果星宗", "星学大成", "星命总括", "星命溯源", "乾元秘旨"],
    "06_六壬": ["六壬一字诀玉连环", "六壬兵占", "六壬大全", "六壬存验", "六壬寻源", "六壬心镜",
                "六壬拃河棹", "六壬括囊赋略疏", "六壬指南", "六壬指南注解", "六壬断案", "六壬灵觉经",
                "六壬直指御定", "六壬神定经", "六壬神将释", "六壬神课金口诀古本", "六壬秘本",
                "六壬管辂神书", "六壬粹言", "六壬经纬", "六壬翠雨歌", "六壬苗公射覆鬼撮脚",
                "六壬论命秘要", "六壬金铰剪", "六壬银河櫂", "六壬集成五要权衡",
                "壬占汇选", "壬学琐记", "壬归"],
    "05_卜筮六爻": ["京氏易传", "火珠林", "黄金策", "增删卜易", "卜筮正宗", "卜筮全书", "易冒", "易隐",
                    "易林补遗", "断易天机", "断易鬼灵经", "海底眼", "大易断例卜筮元龟目", "周易尚占",
                    "灵棋经", "文王金钱课", "卜法详考", "梅花易数"],
    "04_占候天文": ["开元占经", "唐开元占经", "乙巳占", "灵台秘苑", "马王堆汉墓帛书五星占"],
    "03_易学象数": ["吴园易解", "正易心法", "焦氏易林", "焦氏易林注", "焦氏易诂", "皇极经世",
                    "皇极经世书", "皇极经世心易发微", "皇极经世观物外篇衍义", "太玄经", "潜虚",
                    "潜虚发微论", "数术记遗"],
    "09_堪舆阴宅": ["葬书", "青乌经", "青囊奥语", "青囊序", "疑龙经", "撼龙经", "撼龙经疑龙经葬法倒杖",
                    "葬法倒杖", "催官篇", "天玉经", "天玉经外篇", "发微论", "灵城精义", "山洋指迷原本",
                    "人子须知", "入地眼全书", "地理醒心录", "本地姜地理峦头诀", "红囊经", "插泥剑",
                    "平砂玉尺经", "平砂玉尺辨伪", "平沙玉尺辨伪总括歌", "地理辨正", "地理辨惑",
                    "地理古镜歌", "天元五歌", "蒋公字字金", "二十四山八卦罗经图"],
    "10_堪舆阳宅": ["宅经", "宅法举隅", "阳宅指南"],
    "02_奇门遁甲": ["奇门宝鉴御定", "奇门旨归", "奇门法窍", "奇门遁甲元灵经", "奇门遁甲秘笈大全",
                    "奇门遁甲统宗", "遁甲演义", "遁甲符应经"],
    "11_相术": ["太清神鉴", "玉管照神局", "月波洞中记", "人伦大统赋", "神相全编", "神相铁关刀",
                "柳庄相法", "永乐百问", "许负相法", "公笃相法", "冰鉴", "心相篇", "鬼谷子神奇相法全书"],
    "12_择日历注": ["钦定协纪辨方书", "御定星历考原"],
    "13_杂占其他": ["推背图", "秘本诸葛神数", "神机妙算一掌经", "周公解梦", "测字秘牒", "辰州符咒大全",
                    "演禽通纂", "禽星易见"],
    "01_太乙": ["太乙秘书", "太乙金镜式经"],
    "00_基础理论": ["五行大义"],
}
# RAG 检索域：primary 是主域，core_ext 视需求并入，其余作可过滤的扩展域
PRIMARY = {"08_八字禄命"}
CORE_EXT = {"07_星命七政四余"}

# ── 二、重复关系（6-gram 包含率实测；keep 为空的只打标签不排除）──────────────
DUP = {
    "hanlong": dict(
        members=["撼龙经", "疑龙经", "葬法倒杖", "撼龙经疑龙经葬法倒杖"],
        keep=["撼龙经", "撼龙经疑龙经葬法倒杖"],
        note="疑龙经100%、葬法倒杖99%全含于合集；撼龙经单篇仅19%重合，属另一长本，单篇与合集都留"),
    "kaiyuan": dict(members=["开元占经", "唐开元占经"], keep=[],
                    note="同书两版：包含率仅10%，属异版异文，未确认前不排除，待人工对读"),
    "qingnang": dict(members=["青囊奥语", "青囊序", "地理辨正"], keep=[],
                     note="地理辨正以青囊奥语为第一章，但包含率21%/1%，非全文重复，保留"),
    "jiaoshi": dict(members=["焦氏易林", "焦氏易林注"], keep=[],
                    note="注本含林辞，包含率38%（夹注打断），可按需二选一"),
    "huangji": dict(members=["皇极经世", "皇极经世书"], keep=[],
                    note="道藏本 vs 文渊阁四库本，包含率0%，两套编排"),
    "bushi": dict(members=["卜筮正宗", "卜筮全书"], keep=[],
                  note="包含率16%，同源但各有独立价值，都留"),
    "yuzhao": dict(members=["玉照定真经", "玉照神应真经"], keep=[],
                   note="包含率1%，标题近而正文异，需人工判断是否异名同书"),
    "luzi": dict(members=["珞琭子赋注", "珞琭子三命消息赋注", "徐氏珞琭子赋注"], keep=[],
                 note="同一赋的三家注本，正文重叠、注文不同，都留"),
}
STUBS = {"命理正宗": "残片：1326 字，系《神峰通考》别题，内容不完整"}

# ── 三、03-terminology 的体系映射 ───────────────────────────────────────────
SYS_PREFIX = [
    ("ZIWEI", "紫微斗数"), ("AN_", "紫微斗数"), ("SI_HUA", "紫微斗数"), ("SIHUA", "紫微斗数"),
    ("FOURTEEN", "紫微斗数"), ("SHUANGXING", "紫微斗数"), ("MIAO_WANG", "紫微斗数"),
    ("WUXING_JU", "紫微斗数"), ("DAXIAN", "紫微斗数"), ("DA_XIAN", "紫微斗数"), ("LIUJI", "紫微斗数"),
    ("LIUSHA", "紫微斗数"), ("FEIHUA", "紫微斗数"), ("TWELVE_PALACES", "紫微斗数"),
    ("SHIGAN_SIHUA", "紫微斗数"),
    ("LIUYAO", "六爻纳甲"), ("NAJIA", "六爻纳甲"), ("HUNTAN", "六爻纳甲"), ("LIUSHEN", "六爻纳甲"),
    ("SHI_YING", "六爻纳甲"), ("WANGXIANG", "六爻纳甲"), ("KONGWANG", "六爻纳甲"),
    ("DONGBIAN", "六爻纳甲"), ("BAGONG", "六爻纳甲"),
    ("QIMEN", "奇门"), ("JIU_XING", "奇门"), ("JIUXING", "奇门"), ("BA_MEN", "奇门"), ("BA_SHEN", "奇门"),
    ("SAN_QI", "奇门"), ("ZHIFU", "奇门"), ("YONG_SHEN_QIFA", "奇门"), ("JIU_GONG", "奇门"),
    ("YANBO", "奇门"),
    ("FENGSHUI", "风水"), ("XUANKONG", "风水"), ("LONGXUE", "风水"), ("SHAQT", "风水"),
    ("ZIBAIFEIXING", "风水"), ("BAZHAI", "风水"), ("SHAJIAO", "风水"), ("YANGZHAI", "风水"),
    ("BAYUAN", "风水"), ("DONGXI_SANZHAI", "风水"), ("SANYUAN_JIUYUN", "风水"), ("TWENTY_FOUR", "风水"),
    ("FANGWEI", "风水"), ("MING_GUA", "风水"), ("YINZHAI", "风水"),
    ("ZERI", "择日"), ("DATE_", "择日"), ("JIANCHU", "择日"), ("JIANSHEN", "择日"), ("HUANGDAO", "择日"),
    ("SUISHA", "择日"), ("JISHI", "择日"), ("YUELING", "择日"), ("SUIDE", "择日"),
    ("XINGXIU", "星命/星象"), ("ERSHIBA", "星命/星象"), ("XIU_", "星命/星象"), ("QINXING", "星命/星象"),
    ("SANVUAN", "星命/星象"), ("QIZHENG", "星命/星象"),
    ("BAGUA", "易学/八卦基础"), ("XIANTIAN", "易学/八卦基础"), ("HOUTIAN", "易学/八卦基础"),
    ("JINGFANG", "易学/八卦基础"), ("SHICHI", "易学/八卦基础"), ("SIXIANG", "易学/八卦基础"),
    ("YIJING", "易学/八卦基础"), ("HETU", "易学/八卦基础"), ("LUOSHU", "易学/八卦基础"),
    ("TAIJI", "易学/八卦基础"),
    ("MEIHUA", "梅花易数"), ("DA_LIUREN", "六壬"),
]
SYS_OVERRIDE = {
    "ZENGSHAN_BUYI": "六爻纳甲", "RIYUE_JIAN": "六爻纳甲", "YINGQI_TUISUAN": "六爻纳甲",
    "YINGQI_ZONGHE": "六爻纳甲", "SIBAO_XITONG": "六爻纳甲",
    "FENYE": "星命/星象", "SANYUAN_ZERI": "择日", "XINGSHI_FENGSHUI": "风水",
    "WUXING": "易学/八卦基础", "WUXING_RELATIONS": "易学/八卦基础", "WUXING_SYSTEM": "易学/八卦基础",
    "YINYANG": "易学/八卦基础", "GANZHI_JINIAN": "易学/八卦基础",
}
SYS_DEFAULT = "八字/命理"   # 其余 BAZI_* / TIANGAN / DIZHI / SHISHEN / SHENSHA / … 均属八字
SYS_NOISE = {
    "bazi-terms.jsonl": "英文释义（168/168 含英文），中文 RAG 建议剔除或重写",
    "iztro-terms.jsonl": "紫微斗数算法常量 + 四化，仅限紫微域",
    "lunar-terms.jsonl": "历法算法生成，非古籍原文",
}
PUNCT = "，。、；：？！「」『』（）〈〉《》—…·“”‘’"


def cjk(s):
    return sum(1 for c in s if "一" <= c <= "鿿")


def strip_header(text):
    return "".join(l for l in text.splitlines(True) if not l.startswith("#"))


def punct_ratio(body):
    n = cjk(body)
    return sum(body.count(c) for c in PUNCT) / n if n else 0.0


def system_of(group):
    if group in SYS_OVERRIDE:
        return SYS_OVERRIDE[group]
    for p, name in SYS_PREFIX:
        if group.startswith(p):
            return name
    return SYS_DEFAULT


def wtext(path, text):
    """统一用 LF 写，避免 Windows 文本模式产生 CRLF 把 TSV 读坏。"""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    a = ap.parse_args()
    repo = a.repo
    meta = os.path.join(repo, "_meta")
    os.makedirs(meta, exist_ok=True)

    school_of = {t: s for s, ts in SCHOOLS.items() for t in ts}
    dup_of = {t: g for g, d in DUP.items() for t in d["members"]}
    keep = {t for d in DUP.values() for t in d["keep"]}

    with open(os.path.join(repo, "01-classics", "术数-manifest.json"), encoding="utf-8") as f:
        man = json.load(f)
    assert len(man) == 155, "manifest 应为 155 部，实际 %d" % len(man)
    assert len(school_of) == 155, "分类表应为 155 部，实际 %d" % len(school_of)
    assert set(school_of) == {m["title"] for m in man}, "分类表与 manifest 书名不一致"

    books = []
    for m in man:
        t = m["title"]
        with open(os.path.join(repo, "01-classics", m["file"]), encoding="utf-8") as f:
            body = strip_header(f.read())
        pr = punct_ratio(body)
        use, reason = True, ""
        if t in STUBS:
            use, reason = False, STUBS[t]
        elif dup_of.get(t) and t not in keep and DUP[dup_of[t]]["keep"]:
            use, reason = False, "已被同组更全版本取代（%s）" % dup_of[t]
        books.append(dict(
            title=t, file=m["file"], source=m["url"], chars=m["chars"], cjk=cjk(body),
            lines=body.count("\n"), punct_ratio=round(pr, 4), needs_despacing=pr < 0.02,
            school=school_of[t],
            domain=("primary" if school_of[t] in PRIMARY else
                    "core_ext" if school_of[t] in CORE_EXT else "extended"),
            dup_group=dup_of.get(t), use=use, reason=reason))

    wtext(os.path.join(meta, "books.json"),
          json.dumps(books, ensure_ascii=False, indent=1) + "\n")
    wtext(os.path.join(meta, "books.tsv"),
          "".join("%s\t%s\t%d\n" % (b["title"], b["school"], b["use"]) for b in books))
    wtext(os.path.join(meta, "exclude.txt"),
          "# 排除清单（由 _scripts/classify.py 生成，改规则请改脚本后重跑）\n"
          + "".join("%s\t%s\n" % (b["title"], b["reason"]) for b in books if not b["use"]))

    used = [b for b in books if b["use"]]
    tot = sum(b["chars"] for b in used) or 1
    rows = ["school\tbooks_total\tbooks_used\tchars_used\tshare\tneeds_despacing"]
    for s in sorted(SCHOOLS):
        g = [b for b in books if b["school"] == s]
        gu = [b for b in g if b["use"]]
        c = sum(b["chars"] for b in gu)
        rows.append("%s\t%d\t%d\t%d\t%.1f%%\t%d" % (
            s, len(g), len(gu), c, c / tot * 100, sum(1 for b in gu if b["needs_despacing"])))
    wtext(os.path.join(meta, "corpus-stats.tsv"), "\n".join(rows) + "\n")

    jl = os.path.join(repo, "03-terminology", "sudo-biao", "sudo-biao-terms.jsonl")
    cnt = collections.Counter()
    with open(jl, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                cnt[json.loads(line)["group"]] += 1
    wtext(os.path.join(meta, "terminology-system-map.tsv"),
          "group\tsystem\tterms\n"
          + "".join("%s\t%s\t%d\n" % (g, system_of(g), n) for g, n in sorted(cnt.items())))

    # ── 报告 ──
    print("清单 %d 部 / 入库 %d 部 / 排除 %d 部（残片 %d + 重复 %d）" % (
        len(books), len(used), len(books) - len(used), len(STUBS),
        sum(1 for b in books if not b["use"] and b["title"] not in STUBS)))
    print("入库字数 %s   无标点 %d 部" % (format(sum(b["chars"] for b in used), ","),
                                     sum(b["needs_despacing"] for b in used)))
    print()
    print("%-20s%5s%12s%8s%8s" % ("体系", "部数", "字数", "占比", "无标点"))
    for s in sorted(SCHOOLS):
        g = [b for b in used if b["school"] == s]
        if not g:
            continue
        c = sum(b["chars"] for b in g)
        print("%-20s%5d%12s%7.1f%%%8d" % (s, len(g), format(c, ","), c / tot * 100,
                                          sum(1 for b in g if b["needs_despacing"])))
    print()
    print("主域 = %s：%d 部 %s 字" % ("+".join(sorted(PRIMARY)),
        sum(1 for b in used if b["domain"] == "primary"),
        format(sum(b["chars"] for b in used if b["domain"] == "primary"), ",")))
    if CORE_EXT:
        print("备选并入 = %s：%d 部 %s 字" % ("+".join(sorted(CORE_EXT)),
            sum(1 for b in used if b["domain"] == "core_ext"),
            format(sum(b["chars"] for b in used if b["domain"] == "core_ext"), ",")))

    groups = sorted({g for _, g, _ in [(0, b["dup_group"], 0) for b in books if b["dup_group"]]})
    if groups:
        print()
        print("重复组（只打标签，未自动排除）：")
        for g in groups:
            ts = sorted({b["title"] for b in books if b["dup_group"] == g})
            own = [b["title"] for b in books if b["dup_group"] == g and not b["use"]]
            print("  %-9s %d 部  %s%s" % (g, len(ts), "/".join(ts),
                                          "  ← 排除：" + "/".join(own) if own else ""))
            print("  %-9s └ %s" % ("", DUP[g]["note"]))
    print()
    print("→ %s/{books.json, books.tsv, exclude.txt, corpus-stats.tsv, "
          "terminology-system-map.tsv}" % meta)
    for fn, note in SYS_NOISE.items():
        print("  ⚠ 03/%s：%s" % (fn, note))
    print("  ⚠ 03/sudo-biao：%d/%d 个 group 按默认归入「%s」，查 terminology-system-map.tsv 复核" % (
        sum(1 for g in cnt if system_of(g) == SYS_DEFAULT), len(cnt), SYS_DEFAULT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
