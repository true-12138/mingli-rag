# -*- coding: utf-8 -*-
"""排盘参数的结构化收集（Questionnaire）。

排盘需要哪些槽位是固定的，但调用方手里常常只有一部分信息：
用户可能只说「1995 年生的」，模型也可能只从一句话里抽到年份。
这个模块不替用户猜：缺什么就返回缺的字段，每个字段带标签、类型、范围、
示例和一句可以直接拿去问用户的话，前端渲染成表单或模型照着追问都行。

三种结果状态：

- ``ready``：槽位齐了，``params`` 是可以直接排盘的完整参数；
- ``need_input``：还缺字段或字段不合法，``fields`` 只列需要补的那几项；
- 不支持的盘类型直接抛 ``ValueError``（这是调用方的编程错误，不是用户缺信息）。

默认值只在可选字段上使用，并且会明确写在 ``defaults`` / ``warnings`` 里，
不会把「不知道出生地」悄悄当成北京。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


# ---------- 请求模型 ----------
# 放在这里而不是 api_fortune，是为了让「收集参数」和「校验参数」共用同一套定义。

class BirthRequest(BaseModel):
    """出生地当地公历时间；日期范围限制在历法库算得准的区间内。"""

    year: int = Field(ge=1900, le=2100)
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    hour: int = Field(default=0, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)


class BaziRequest(BirthRequest):
    gender: Literal["male", "female"] = "male"


class AstroRequest(BirthRequest):
    tz: float = Field(default=8.0, ge=-12, le=14)
    lat: float = Field(default=39.90, ge=-90, le=90)
    lon: float = Field(default=116.40, ge=-180, le=180)
    city: str = Field(default="北京", max_length=40)


class TarotRequest(BaseModel):
    n: int = Field(default=3, ge=1, le=10)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)
    spread: Literal["single", "three", "cross"] | None = None


MODELS: dict[str, type[BaseModel]] = {
    "bazi": BaziRequest,
    "astro": AstroRequest,
    "tarot": TarotRequest,
}


# ---------- 字段说明 ----------
# required=False 的字段没填时交给 pydantic 补默认值，并记进 defaults。

_YMD = (
    {"name": "year", "label": "出生年份", "type": "int", "required": True,
     "min": 1900, "max": 2100, "example": 1995,
     "ask": "出生年份是哪一年？（公历，如 1995）"},
    {"name": "month", "label": "出生月份", "type": "int", "required": True,
     "min": 1, "max": 12, "example": 8,
     "ask": "出生月份是几月？（1–12）"},
    {"name": "day", "label": "出生日", "type": "int", "required": True,
     "min": 1, "max": 31, "example": 20,
     "ask": "出生日是哪一天？（1–31）"},
)

_HOUR = (
    {"name": "hour", "label": "出生钟点", "type": "int", "required": True,
     "min": 0, "max": 23, "example": 14,
     "ask": "出生在几点？（0–23 时；只知道时辰也可以换算，不确定就先填 12）"},
    {"name": "minute", "label": "出生分钟", "type": "int", "required": False,
     "min": 0, "max": 59, "example": 30,
     "ask": "出生在几分？（0–59，不确定可留空按 0 分算）"},
)

FIELD_SPECS: dict[str, tuple[dict[str, Any], ...]] = {
    "bazi": _YMD + _HOUR + (
        {"name": "gender", "label": "性别", "type": "enum", "required": True,
         "options": ["male", "female"], "option_labels": {"male": "男", "female": "女"},
         "ask": "性别是？（传统排盘用性别定大运顺逆）"},
    ),
    "astro": _YMD + _HOUR + (
        {"name": "city", "label": "出生城市", "type": "str", "required": False,
         "max_length": 40, "example": "杭州",
         "ask": "出生在哪个城市？（影响上升和宫位）"},
        {"name": "tz", "label": "时区", "type": "float", "required": False,
         "min": -12, "max": 14, "example": 8,
         "ask": "出生地时区是几？（默认东八区 8）"},
        {"name": "lat", "label": "纬度", "type": "float", "required": False,
         "min": -90, "max": 90, "example": 30.27,
         "ask": "出生地纬度？（不知道可只给城市，默认按北京）"},
        {"name": "lon", "label": "经度", "type": "float", "required": False,
         "min": -180, "max": 180, "example": 120.16,
         "ask": "出生地经度？（不知道可只给城市，默认按北京）"},
    ),
    "tarot": (
        {"name": "spread", "label": "牌阵", "type": "enum", "required": False,
         "options": ["single", "three", "cross"],
         "option_labels": {"single": "单张", "three": "三张", "cross": "十字"},
         "ask": "想用哪种牌阵？（单张 / 三张 / 十字）"},
        {"name": "n", "label": "抽几张", "type": "int", "required": False,
         "min": 1, "max": 10, "example": 3,
         "ask": "想抽几张？（1–10；选了牌阵就按牌阵来）"},
        {"name": "seed", "label": "随机种子", "type": "int", "required": False,
         "min": 0, "max": 2**63 - 1,
         "ask": "要固定 seed 以便复现吗？（一般不用填）"},
    ),
}

_SPEC_BY_NAME = {
    kind: {spec["name"]: spec for spec in specs}
    for kind, specs in FIELD_SPECS.items()
}


class _BadValue(ValueError):
    """单个字段的值转不过去。"""


def _coerce(spec: dict[str, Any], value: Any) -> Any:
    """按字段类型把外部值转成 Python 值；转不了一律抛 _BadValue。"""
    name = spec["name"]
    kind = spec["type"]

    if kind == "enum":
        if not isinstance(value, str) or value.strip() not in spec["options"]:
            raise _BadValue("只能是 %s" % " / ".join(spec["options"]))
        return value.strip()

    if kind == "str":
        if not isinstance(value, str):
            raise _BadValue("需要文本")
        value = value.strip()
        if spec.get("max_length") and len(value) > spec["max_length"]:
            raise _BadValue("最多 %d 个字" % spec["max_length"])
        return value

    # int / float：接受数字或数字字符串；bool 是 int 的子类，单独排除
    if isinstance(value, bool):
        raise _BadValue("需要数字")
    if isinstance(value, str):
        value = value.strip()
        if not value:
            raise _BadValue("需要数字")
        try:
            value = float(value)
        except ValueError:
            raise _BadValue("需要数字") from None
    if not isinstance(value, (int, float)):
        raise _BadValue("需要数字")

    if kind == "int":
        if isinstance(value, float) and not value.is_integer():
            raise _BadValue("需要整数")
        value = int(value)
    else:
        value = float(value)

    if "min" in spec and value < spec["min"]:
        raise _BadValue("不能小于 %s" % spec["min"])
    if "max" in spec and value > spec["max"]:
        raise _BadValue("不能大于 %s" % spec["max"])
    return value


def _question(spec: dict[str, Any], *, error: str | None = None,
              value: Any = None) -> dict[str, Any]:
    """把一个字段说明变成一条追问。"""
    item = {
        "name": spec["name"],
        "label": spec["label"],
        "ask": spec["ask"],
        "type": spec["type"],
        "required": spec["required"],
    }
    for key in ("min", "max", "max_length", "options", "option_labels", "example"):
        if key in spec:
            item[key] = spec[key]
    if error:
        item["error"] = error
    if value is not None:
        item["value"] = value
    return item


def _message(fields: list[dict[str, Any]]) -> str:
    bad = [f for f in fields if f.get("error")]
    if bad:
        return "有 %d 项信息需要改一下：%s" % (
            len(bad), "、".join(f["label"] for f in bad),
        )
    return "还缺 %d 项信息：%s" % (len(fields), "、".join(f["label"] for f in fields))


def need_input(kind: str, known: dict[str, Any], names: list[str], *,
               reason: str = "missing", message: str | None = None,
               errors: dict[str, str] | None = None) -> dict[str, Any]:
    """构造一个 need_input 响应，只问 ``names`` 里的字段。"""
    specs = _SPEC_BY_NAME.get(kind)
    if specs is None:
        raise ValueError("不支持的盘类型：%s" % kind)
    errors = errors or {}
    fields = [_question(specs[name], error=errors.get(name)) for name in names]
    return {
        "status": "need_input",
        "kind": kind,
        "reason": reason,
        "known": dict(known),
        "fields": fields,
        "message": message or _message(fields),
    }


def _warnings(kind: str, defaults: dict[str, Any],
              data: dict[str, Any]) -> list[str]:
    out = []
    if "minute" in defaults:
        out.append("未填写出生分钟，按 %s 分计算。" % defaults["minute"])
    if kind == "astro" and "city" in defaults:
        if "lat" in defaults and "lon" in defaults:
            out.append(
                "未提供出生城市，上升与宫位按默认城市「北京」"
                "（北纬 %s，东经 %s，东八区）计算，可能与实际出生地有偏差。"
                % (data.get("lat"), data.get("lon"))
            )
        else:
            out.append(
                "未提供出生城市，上升与宫位按所给经纬度"
                "（北纬 %s，东经 %s）计算。" % (data.get("lat"), data.get("lon"))
            )
    return out


def collect(kind: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """检查参数是否够排盘；不够就返回结构化追问。

    不会修改 ``params``。未知键会被忽略并记在 ``ignored`` 里——调用方可能
    直接把一张盘的 ``input`` 对象原样传回来，里面带着 ``solar`` / ``lunar``
    这类只用于展示的字段。
    """
    specs = FIELD_SPECS.get(kind)
    if specs is None:
        raise ValueError("不支持的盘类型：%s" % kind)

    raw = dict(params or {})
    names = {spec["name"] for spec in specs}
    ignored = sorted(str(key) for key in raw if key not in names)

    known: dict[str, Any] = {}
    fields: list[dict[str, Any]] = []
    for spec in specs:
        name = spec["name"]
        value = raw.get(name)
        blank = value is None or (isinstance(value, str) and not value.strip())
        if blank:
            if spec["required"]:
                fields.append(_question(spec))
            continue
        try:
            known[name] = _coerce(spec, value)
        except _BadValue as exc:
            fields.append(_question(spec, error=str(exc), value=value))

    if fields:
        reason = "invalid" if any(f.get("error") for f in fields) else "missing"
        return {"status": "need_input", "kind": kind, "reason": reason,
                "known": known, "fields": fields, "message": _message(fields)}

    # 槽位齐了再过一遍完整模型：范围之外的组合（如 2 月 30 日）由排盘函数
    # 在 api_fortune 里兜底，这里只负责类型和单字段范围。
    try:
        parsed = MODELS[kind].model_validate(known)
    except ValidationError as exc:
        bad: dict[str, str] = {}
        for error in exc.errors():
            loc = error.get("loc") or ()
            if loc and str(loc[0]) in names:
                bad[str(loc[0])] = error.get("msg") or "值不合法"
        if not bad:  # 理论上不会到这里；真到了就让调用方看到原始错误
            raise
        return need_input(kind, known, list(bad), reason="invalid", errors=bad)

    data = parsed.model_dump()
    defaults = {k: v for k, v in data.items() if k not in known and v is not None}
    return {
        "status": "ready",
        "kind": kind,
        "params": data,
        "defaults": defaults,
        "ignored": ignored,
        "warnings": _warnings(kind, defaults, data),
    }
