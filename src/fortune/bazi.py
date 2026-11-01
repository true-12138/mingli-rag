# -*- coding: utf-8 -*-
"""八字排盘。

干支、节气、大运这些是**历法计算**，交给 lunar_python（6tail 那套算法）做，
不自己实现——自己写节气误差一天，整个盘就全错了。

这里负责的是：调用 + 整理成统一结构 + 拼一段人能读的文字。
"""
from __future__ import annotations

from datetime import datetime

from lunar_python import Solar

# 天干地支 → 五行。统计"命里缺什么"用，只数八个字，不数藏干。
_GAN_WUXING = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
    "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水",
}
_ZHI_WUXING = {
    "寅": "木", "卯": "木", "巳": "火", "午": "火",
    "申": "金", "酉": "金", "亥": "水", "子": "水",
    "辰": "土", "戌": "土", "丑": "土", "未": "土",
}

PILLAR_NAMES = ("年柱", "月柱", "日柱", "时柱")


def _wuxing_count(sizhu):
    """四柱八个字的五行分布。"""
    counts = {"木": 0, "火": 0, "土": 0, "金": 0, "水": 0}
    for ganzhi in sizhu:
        if len(ganzhi) != 2:
            continue
        gan, zhi = ganzhi[0], ganzhi[1]
        if gan in _GAN_WUXING:
            counts[_GAN_WUXING[gan]] += 1
        if zhi in _ZHI_WUXING:
            counts[_ZHI_WUXING[zhi]] += 1
    return counts


def paipan(year, month, day, hour=0, minute=0, gender="male"):
    """排八字盘。

    Args:
        year/month/day/hour/minute: 出生地**当地**公历时间（不是 UTC）。
        gender: "male" / "female"，只影响大运顺逆和起运岁数。

    Returns:
        dict，字段见下方 out 的构造。算不出来会抛 ValueError。
    """
    gender = (gender or "male").lower()
    if gender not in ("male", "female"):
        raise ValueError("gender 只能是 male 或 female")
    try:
        # lunar_python 会把 2 月 30 日静默地顺延，所以先自己验一遍
        datetime(int(year), int(month), int(day), int(hour), int(minute))
    except (TypeError, ValueError) as exc:
        raise ValueError("出生时间不合法：%s" % exc)

    try:
        hour = int(hour)
        minute = int(minute)
        solar = Solar.fromYmdHms(int(year), int(month), int(day), hour, minute, 0)
    except Exception as exc:
        raise ValueError("出生时间不合法：%s" % exc)

    lunar = solar.getLunar()
    ec = lunar.getEightChar()

    sizhu = [ec.getYear(), ec.getMonth(), ec.getDay(), ec.getTime()]
    # 数值 1 = 男，0 = 女；这是 lunar_python 的约定
    yun = ec.getYun(1 if gender == "male" else 0)

    dayun = []
    for d in yun.getDaYun():
        ganzhi = d.getGanZhi()
        if not ganzhi:  # 起运前那一段没有干支，跳过
            continue
        dayun.append({
            "start_year": d.getStartYear(),
            "start_age": d.getStartAge(),
            "ganzhi": ganzhi,
        })
        if len(dayun) >= 8:
            break

    now_year = datetime.now().year
    liunian = next(
        (d for d in dayun if d["start_year"] <= now_year < d["start_year"] + 10),
        None,
    )

    out = {
        "kind": "bazi",
        "input": {
            "year": int(year), "month": int(month), "day": int(day),
            "hour": hour, "minute": minute, "gender": gender,
            "solar": "%04d-%02d-%02d %02d:%02d" % (int(year), int(month), int(day), hour, minute),
            "lunar": lunar.toString(),
        },
        "sizhu": dict(zip(PILLAR_NAMES, sizhu)),
        "rizhu": ec.getDay(),           # 日柱，命主本身
        "day_master": ec.getDayGan(),   # 日干，所有十神都相对它来定
        "shengxiao": lunar.getYearShengXiao(),
        "canggan": dict(zip(PILLAR_NAMES, [
            ec.getYearHideGan(), ec.getMonthHideGan(), ec.getDayHideGan(), ec.getTimeHideGan(),
        ])),
        "shishen_gan": dict(zip(PILLAR_NAMES, [
            ec.getYearShiShenGan(), ec.getMonthShiShenGan(),
            "日主", ec.getTimeShiShenGan(),
        ])),
        "shishen_zhi": dict(zip(PILLAR_NAMES, [
            ec.getYearShiShenZhi(), ec.getMonthShiShenZhi(),
            ec.getDayShiShenZhi(), ec.getTimeShiShenZhi(),
        ])),
        "nayin": dict(zip(PILLAR_NAMES, [
            ec.getYearNaYin(), ec.getMonthNaYin(), ec.getDayNaYin(), ec.getTimeNaYin(),
        ])),
        "wuxing": _wuxing_count(sizhu),
        "xunkong": dict(zip(PILLAR_NAMES, [
            ec.getYearXunKong(), ec.getMonthXunKong(),
            ec.getDayXunKong(), ec.getTimeXunKong(),
        ])),
        "taiyuan": ec.getTaiYuan(),
        "minggong": ec.getMingGong(),
        "shengong": ec.getShenGong(),
        "qiyun": {
            "years": yun.getStartYear(),
            "months": yun.getStartMonth(),
            "days": yun.getStartDay(),
            "forward": bool(yun.isForward()),
        },
        "dayun": dayun,
        "current_dayun": liunian,
    }

    missing = [k for k, v in out["wuxing"].items() if v == 0]
    out["wuxing_missing"] = missing
    out["text"] = format_bazi(out)
    return out


def format_bazi(chart):
    """把盘压成一段紧凑文本，给模型和界面用。"""
    s = chart["sizhu"]
    lines = [
        "公历 %s（%s），%s" % (
            chart["input"]["solar"], chart["input"]["lunar"],
            "男" if chart["input"]["gender"] == "male" else "女",
        ),
        "四柱：年 %s ｜ 月 %s ｜ 日 %s ｜ 时 %s" % (s["年柱"], s["月柱"], s["日柱"], s["时柱"]),
        "日主：%s（十神都以它为准）  生肖：%s" % (chart["day_master"], chart["shengxiao"]),
        "藏干：年 %s ｜ 月 %s ｜ 日 %s ｜ 时 %s" % (
            "、".join(chart["canggan"]["年柱"]), "、".join(chart["canggan"]["月柱"]),
            "、".join(chart["canggan"]["日柱"]), "、".join(chart["canggan"]["时柱"]),
        ),
        "十神：年 %s ｜ 月 %s ｜ 时 %s" % (
            chart["shishen_gan"]["年柱"], chart["shishen_gan"]["月柱"], chart["shishen_gan"]["时柱"],
        ),
        "五行：木%d 火%d 土%d 金%d 水%d" % tuple(chart["wuxing"][k] for k in "木火土金水"),
        "纳音：年 %s ｜ 日 %s" % (chart["nayin"]["年柱"], chart["nayin"]["日柱"]),
        "起运：%d 岁 %d 个月，%s" % (
            chart["qiyun"]["years"], chart["qiyun"]["months"],
            "顺排" if chart["qiyun"]["forward"] else "逆排",
        ),
    ]
    if chart["wuxing_missing"]:
        lines.append("五行缺：" + "、".join(chart["wuxing_missing"]))
    if chart["dayun"]:
        lines.append("大运：" + "  ".join(
            "%d岁 %s" % (d["start_age"], d["ganzhi"]) for d in chart["dayun"][:6]
        ))
    if chart["current_dayun"]:
        cur = chart["current_dayun"]
        lines.append("当前大运：%s（%d 岁起）" % (cur["ganzhi"], cur["start_age"]))
    return "\n".join(lines)


if __name__ == "__main__":
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print(format_bazi(paipan(1995, 8, 20, 14, 30, "male")))
