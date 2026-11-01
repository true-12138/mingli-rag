# -*- coding: utf-8 -*-
"""西方星盘（本命盘）。

行星位置用 pyephem 的**地心视黄经**算——这是占星通用的口径。
上升/天顶不用星历，是纯球面三角，直接用当地恒星时算。

宫位采用**整宫制**（Whole Sign）：上升所在星座为第一宫，依次排下去。
传统希腊占星用这套，规则最简单、不会因为宫头算法不同吵起来。
Placidus 那类不等宫制需要解三次方程，这里不做——不是不能，是没必要。
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import ephem

SIGNS = ("白羊", "金牛", "双子", "巨蟹", "狮子", "处女",
         "天秤", "天蝎", "射手", "摩羯", "水瓶", "双鱼")

# (中文名, ephem 类, 是否常逆行的外行星——用于标注)
PLANETS = (
    ("太阳", ephem.Sun),
    ("月亮", ephem.Moon),
    ("水星", ephem.Mercury),
    ("金星", ephem.Venus),
    ("火星", ephem.Mars),
    ("木星", ephem.Jupiter),
    ("土星", ephem.Saturn),
    ("天王星", ephem.Uranus),
    ("海王星", ephem.Neptune),
    ("冥王星", ephem.Pluto),
)

ELEMENTS = {"白羊": "火", "狮子": "火", "射手": "火",
            "金牛": "土", "处女": "土", "摩羯": "土",
            "双子": "风", "天秤": "风", "水瓶": "风",
            "巨蟹": "水", "天蝎": "水", "双鱼": "水"}

MODALITIES = {"白羊": "基本", "巨蟹": "基本", "天秤": "基本", "摩羯": "基本",
              "金牛": "固定", "狮子": "固定", "天蝎": "固定", "水瓶": "固定",
              "双子": "变动", "处女": "变动", "射手": "变动", "双鱼": "变动"}

ASPECTS = ((0, "合相", 8), (180, "对分相", 8), (120, "三分相", 6),
           (90, "四分相", 6), (60, "六分相", 4))


def _norm360(x):
    return x % 360.0


def _sign_of(lon):
    """黄经 → (星座名, 宫内度数)。"""
    idx = int(lon // 30) % 12
    return SIGNS[idx], lon - idx * 30


def _gmst_deg(jd):
    """格林尼治平恒星时（度）。Meeus《天文算法》第 12 章。"""
    t = (jd - 2451545.0) / 36525.0
    gmst = (280.46061837 + 360.98564736629 * (jd - 2451545.0)
            + 0.000387933 * t * t - t ** 3 / 38710000.0)
    return _norm360(gmst)


def _obliquity(jd):
    t = (jd - 2451545.0) / 36525.0
    return 23.4392911 - 0.0130042 * t - 1.64e-7 * t * t


def _angles(jd, lat_deg, lon_deg):
    """上升点与天顶的黄经。lat 北纬为正，lon 东经为正。"""
    ramc = math.radians(_norm360(_gmst_deg(jd) + lon_deg))
    eps = math.radians(_obliquity(jd))
    phi = math.radians(lat_deg)

    mc = math.degrees(math.atan2(math.sin(ramc), math.cos(ramc) * math.cos(eps)))
    asc = math.degrees(math.atan2(
        math.cos(ramc),
        -(math.sin(ramc) * math.cos(eps) + math.tan(phi) * math.sin(eps)),
    ))
    return _norm360(asc), _norm360(mc)


def _lon_at(planet_cls, dt):
    body = planet_cls()
    body.compute(dt)
    return _norm360(math.degrees(ephem.Ecliptic(body).lon))


def natal_chart(year, month, day, hour=0, minute=0,
                tz=8.0, lat=39.90, lon=116.40, city="北京"):
    """排一张本命盘。

    Args:
        year..minute: 出生地**当地**时间。
        tz: 时区偏移（小时，东八区 = 8）。
        lat/lon: 出生地纬度/经度，东经北纬为正。
        city: 只是给输出看的标签，不参与计算。
    """
    try:
        local = datetime(int(year), int(month), int(day), int(hour), int(minute))
    except ValueError as exc:
        raise ValueError("出生时间不合法：%s" % exc)

    utc = local - timedelta(hours=float(tz))
    jd = ephem.julian_date(utc)

    planets = []
    for name, cls in PLANETS:
        lon_now = _lon_at(cls, utc)
        lon_next = _lon_at(cls, utc + timedelta(days=1))
        # 黄经一天内变小 → 逆行
        retro = _norm360(lon_next - lon_now) > 180
        sign, deg = _sign_of(lon_now)
        planets.append({
            "name": name,
            "lon": round(lon_now, 4),
            "sign": sign,
            "degree": round(deg, 2),
            "retrograde": retro,
        })

    asc_lon, mc_lon = _angles(jd, float(lat), float(lon))
    asc_sign, asc_deg = _sign_of(asc_lon)
    mc_sign, mc_deg = _sign_of(mc_lon)

    # 整宫制：第一宫 = 上升星座
    asc_idx = SIGNS.index(asc_sign)
    houses = [{"house": i + 1, "sign": SIGNS[(asc_idx + i) % 12]} for i in range(12)]

    # 行星落宫：按星座直接对应
    sign_to_house = {h["sign"]: h["house"] for h in houses}
    for p in planets:
        p["house"] = sign_to_house.get(p["sign"])

    aspects = []
    for i in range(len(planets)):
        for j in range(i + 1, len(planets)):
            diff = abs(_norm360(planets[i]["lon"] - planets[j]["lon"]))
            diff = min(diff, 360 - diff)
            for angle, label, orb in ASPECTS:
                if abs(diff - angle) <= orb:
                    aspects.append({
                        "a": planets[i]["name"], "b": planets[j]["name"],
                        "aspect": label, "angle": angle,
                        "orb": round(abs(diff - angle), 2),
                    })
                    break

    elements = {"火": 0, "土": 0, "风": 0, "水": 0}
    modalities = {"基本": 0, "固定": 0, "变动": 0}
    for p in planets:
        elements[ELEMENTS[p["sign"]]] += 1
        modalities[MODALITIES[p["sign"]]] += 1

    out = {
        "kind": "astro",
        "input": {
            "solar": "%04d-%02d-%02d %02d:%02d" % (int(year), int(month), int(day), int(hour), int(minute)),
            "tz": tz, "lat": lat, "lon": lon, "city": city,
            "utc": utc.strftime("%Y-%m-%d %H:%M"),
        },
        "planets": planets,
        "asc": {"sign": asc_sign, "degree": round(asc_deg, 2), "lon": round(asc_lon, 4)},
        "mc": {"sign": mc_sign, "degree": round(mc_deg, 2), "lon": round(mc_lon, 4)},
        "houses": houses,
        "aspects": aspects,
        "elements": elements,
        "modalities": modalities,
        "house_system": "整宫制",
    }
    out["text"] = format_chart(out)
    return out


def format_chart(chart):
    lines = [
        "出生：%s（UTC%s）　地点约 %s（%.2fN, %.2fE）" % (
            chart["input"]["solar"], chart["input"]["utc"], chart["input"]["city"],
            chart["input"]["lat"], chart["input"]["lon"],
        ),
        "上升 %s %d°　天顶 %s %d°　（%s）" % (
            chart["asc"]["sign"], int(chart["asc"]["degree"]),
            chart["mc"]["sign"], int(chart["mc"]["degree"]),
            chart["house_system"],
        ),
    ]
    for p in chart["planets"]:
        lines.append("%s：%s %d°%s（第%d宫）" % (
            p["name"], p["sign"], int(p["degree"]),
            " 逆行" if p["retrograde"] else "", p["house"],
        ))
    if chart["aspects"]:
        lines.append("主要相位：" + "；".join(
            "%s%s%s（容许度%.1f°）" % (a["a"], a["aspect"], a["b"], a["orb"])
            for a in chart["aspects"][:8]
        ))
    el = chart["elements"]
    md = chart["modalities"]
    lines.append("元素：火%d 土%d 风%d 水%d　｜　三分类：基本%d 固定%d 变动%d" % (
        el["火"], el["土"], el["风"], el["水"], md["基本"], md["固定"], md["变动"],
    ))
    return "\n".join(lines)


if __name__ == "__main__":
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print(format_chart(natal_chart(1995, 8, 20, 14, 30, 8, 39.9, 116.4, "北京")))
