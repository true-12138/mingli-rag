# -*- coding: utf-8 -*-
"""按问题难度在小模型 / 大模型之间路由。

为什么是规则，不是分类器
------------------------
评测集只有 30 道题，训练一个「难度分类器」只会把 30 个样本背下来。
规则路由的每一条加分都能在响应的 `route.signals` 里看到，出错时能直接
改规则，而不是面对一个黑盒调阈值。

两档模型
--------
默认沿用 DeepSeek 同 key 下的两档：
- small: deepseek-chat（服务端即 Flash，便宜、快）
- large: deepseek-v4-pro（贵约 13 倍，复杂推理更稳）

换供应商时用 `MINGLI_TIER_SMALL_MODEL` / `MINGLI_TIER_LARGE_MODEL` 覆盖。
如果小模型不是 DeepSeek 系列，默认不再自动指向 v4-pro，而是两档同模型，
避免在只配了一个模型的部署上把请求打到不存在的模型名。

级联
----
小模型先答；只有当输出无法使用（JSON 解析失败、声称能答却没有有效引用）
才用同一批召回片段升级到大模型。拒答默认**不**升级：评测里 1/3 的题
本来就该拒答，升级只会多付一次大模型的钱。需要时用
`MINGLI_ROUTER_ESCALATE_REFUSAL=on` 打开。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

SMALL = "small"
LARGE = "large"
AUTO = "auto"
TIERS = (AUTO, SMALL, LARGE)

DEFAULT_SMALL_MODEL = "deepseek-chat"
DEFAULT_LARGE_MODEL = "deepseek-v4-pro"
DEFAULT_THRESHOLD = 3


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value is not None and value.strip() else default


def _flag(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() not in ("0", "false", "no", "off", "disabled")


def enabled() -> bool:
    """路由器总开关。默认开：简单题走小模型不改变当前行为，
    复杂题才多花钱，符合「日常用得起」的目标。"""
    return _flag("MINGLI_ROUTER", True)


def escalation_enabled() -> bool:
    return _flag("MINGLI_ROUTER_ESCALATE", True)


def _models() -> tuple[str, str]:
    small = _env("MINGLI_TIER_SMALL_MODEL") or _env("MINGLI_LLM_MODEL") or DEFAULT_SMALL_MODEL
    large = _env("MINGLI_TIER_LARGE_MODEL")
    if not large:
        large = DEFAULT_LARGE_MODEL if small.startswith("deepseek") else small
    return small, large


def _threshold() -> int:
    try:
        return int(_env("MINGLI_ROUTER_THRESHOLD", str(DEFAULT_THRESHOLD)))
    except ValueError:
        return DEFAULT_THRESHOLD


@dataclass(frozen=True)
class ModelSpec:
    """一次生成要用的模型，以及该档位的思考配置。"""

    tier: str
    model: str
    thinking: str | None = None
    effort: str | None = None

    def request_fields(self) -> dict:
        """只把 DeepSeek 认识的字段放进请求体。

        `thinking` / `reasoning_effort` 不是 OpenAI 标准字段，别的供应商
        （OpenRouter、硅基流动等）可能直接 400。换模型时自动退回原请求。
        """
        if not self.model.startswith("deepseek") or self.thinking not in ("enabled", "disabled"):
            return {}
        fields: dict = {"thinking": {"type": self.thinking}}
        if self.thinking == "enabled" and self.effort:
            fields["reasoning_effort"] = self.effort
        return fields


def spec_for(tier: str) -> ModelSpec:
    small, large = _models()
    if tier == LARGE:
        return ModelSpec(
            tier=LARGE,
            model=large,
            thinking=_env("MINGLI_TIER_LARGE_THINKING", "enabled"),
            effort=_env("MINGLI_TIER_LARGE_EFFORT", "high"),
        )
    return ModelSpec(
        tier=SMALL,
        model=small,
        # 小模型的任务是「定义 / 起法 / 有几种」这类单跳问答，关掉思考
        # 能省掉大部分输出 token，也是它便宜得快的原因。
        thinking=_env("MINGLI_TIER_SMALL_THINKING", "disabled"),
        effort=_env("MINGLI_TIER_SMALL_EFFORT", "low"),
    )


@dataclass
class RouteDecision:
    spec: ModelSpec
    reason: str
    score: int = 0
    signals: list[str] = field(default_factory=list)
    forced: bool = False
    router_on: bool = True
    initial_tier: str = SMALL
    small_model: str = ""
    large_model: str = ""

    @property
    def tier(self) -> str:
        return self.spec.tier

    def as_dict(self) -> dict:
        return {
            "tier": self.spec.tier,
            "model": self.spec.model,
            "reason": self.reason,
            "score": self.score,
            "signals": list(self.signals),
            "forced": self.forced,
            "enabled": self.router_on,
            "initial_tier": self.initial_tier,
            "small_model": self.small_model,
            "large_model": self.large_model,
            "thinking": self.spec.thinking,
            "effort": self.spec.effort,
            "escalated": False,
        }


# 跨书比较 / 多观点取舍：答案必须同时压住两处原文，小模型最容易只引一边。
_COMPARE_RE = re.compile(
    r"对比|比较|异同|区别|差别|差在哪|哪个更|孰优|孰先|"
    r"取舍|矛盾|冲突|兼看|合参|两本|两说|各家|互相|相比"
)
# 「不同 / 不一样」在日常问法里太常见，不能单独当跨书比较：
# 「白天生和晚上生犯的不一样吗」是同一本书里的单跳题，答对不需要大模型。
# 只有句子里确实在指书（点名两本或出现「书」），才升级成跨书比较。
_COMPARE_WEAK_RE = re.compile(r"不同|不一样|不一致|对不上")
# 需要多步推理或术语体系支撑的问法。
_REASON_RE = re.compile(
    r"为什么|为何|原理|依据|推导|推断|如何理解|怎么理解|怎么判断|如何判断|"
    r"格局|用神|调候|扶抑|旺衰|大运|流年|小运|合婚|神煞|纳音|藏干|透干"
)
# 单跳释义类问法：命中且问题短，说明用户只想知道「是什么」。
_EASY_RE = re.compile(
    r"是什么|什么意思|啥意思|含义|指什么|怎么算|怎么起|起法|有几种|哪几种|"
    r"几位|哪些|叫什么|包括什么"
)
# 口语改写的题面往往有这些前缀，但语义仍是单跳。
_COLLOQ_RE = re.compile(r"算命的说|听说|据说|有人说|别人说|网上说")
# 现代现实决策：按系统提示应当整题拒答，不需要大模型推理。
_REAL_DECISION_RE = re.compile(
    r"该不该|要不要|能不能|可不可以|值不值得|适不适合|该买|该投|该不该买|"
    r"能考上|能录取|会不会离婚|会不会分手|能不能治"
)
_BOOK_RE = re.compile(r"《([^》]{1,30})》")


def score_question(question: str, *, history=None, chart=None) -> tuple[int, list[str]]:
    """给问题打难度分；返回 (分数, 人类可读的信号列表)。

    正分越大越该走大模型；负分表示明显是单跳 / 该拒答的题。
    """
    q = (question or "").strip()
    score = 0
    signals: list[str] = []

    books = {m.group(1) for m in _BOOK_RE.finditer(q)}
    compare = _COMPARE_RE.search(q)
    weak = _COMPARE_WEAK_RE.search(q)
    cross_book = bool(compare) or bool(weak and (len(books) >= 2 or "书" in q))
    if compare:
        score += 3
        signals.append("跨书比较：" + compare.group(0))
    elif cross_book:
        score += 3
        signals.append("跨书比较：" + weak.group(0) + "（提到书）")
    elif weak:
        score += 1
        signals.append("比较倾向（弱）：" + weak.group(0))

    # 术语命中只说明「题在术语体系里」，不等于「小模型答不好」：实测 q16（起运）
    # 小模型 1.6s 就答对，大模型反而要 8s。所以这项只加 1 分，不单独把题推上去。
    reason = _REASON_RE.search(q)
    if reason:
        score += 1
        signals.append("推理/术语：" + reason.group(0))

    length = len(q)
    if length >= 50:
        score += 2
        signals.append("长问题（{}字）".format(length))
    elif length >= 34:
        score += 1
        signals.append("较长问题（{}字）".format(length))

    marks = q.count("？") + q.count("?")
    if marks >= 2:
        score += 1
        signals.append("包含 {} 个问句".format(marks))

    if len(books) >= 2:
        score += 2
        signals.append("点名 {} 本书".format(len(books)))
    elif len(books) == 1 and not cross_book:
        score -= 1
        signals.append("只点名一本书")

    turns = len(history or [])
    if turns >= 4:
        score += 1
        signals.append("多轮上下文（{}条）".format(turns))

    if chart:
        score += 1
        signals.append("附排盘")

    if _REAL_DECISION_RE.search(q):
        score -= 2
        signals.append("现实决策（应拒答）")

    if _EASY_RE.search(q) and length <= 30 and not cross_book and not reason:
        score -= 2
        signals.append("短定义/起法问题")

    if _COLLOQ_RE.search(q):
        score -= 1
        signals.append("口语化单跳问题")

    return score, signals


def decide(question: str, *, history=None, chart=None, tier: str = AUTO,
           mode: str = "rag") -> RouteDecision:
    """选档位。`tier` 是请求级覆盖：auto / small / large。"""
    small_model, large_model = _models()
    router_on = enabled()

    if tier not in TIERS:
        tier = AUTO

    if tier in (SMALL, LARGE):
        spec = spec_for(tier)
        return RouteDecision(
            spec=spec,
            reason="请求指定 {}".format("大模型" if tier == LARGE else "小模型"),
            forced=True,
            router_on=router_on,
            initial_tier=tier,
            small_model=small_model,
            large_model=large_model,
        )

    if not router_on or small_model == large_model:
        spec = spec_for(SMALL)
        reason = "路由已关闭" if not router_on else "两档模型相同"
        return RouteDecision(
            spec=spec,
            reason=reason,
            router_on=router_on,
            initial_tier=SMALL,
            small_model=small_model,
            large_model=large_model,
        )

    score, signals = score_question(question, history=history, chart=chart)
    target = LARGE if score >= _threshold() else SMALL
    spec = spec_for(target)
    if target == LARGE:
        reason = "难度 {} ≥ 阈值 {}".format(score, _threshold())
    else:
        reason = "难度 {} < 阈值 {}".format(score, _threshold())
    return RouteDecision(
        spec=spec,
        reason=reason,
        score=score,
        signals=signals,
        router_on=router_on,
        initial_tier=target,
        small_model=small_model,
        large_model=large_model,
    )


def needs_escalation(result: dict, *, hits=None) -> tuple[bool, str]:
    """小模型的结果是否值得再让大模型答一遍。

    只升级「输出不可用」这一类：换大模型确实可能救回来。拒答不升级，
    因为大模型看到同一批片段，大概率也拒答，白付一次钱。
    """
    if not escalation_enabled():
        return False, ""
    if not isinstance(result, dict):
        return True, "小模型没有返回结果"
    if result.get("can_answer") is None:
        return True, "小模型没有产出可解析的 JSON"
    if result.get("invalid_output"):
        return True, "小模型声称能答但没有有效引用"
    # 拒答默认也升级，但只在高检索分时升级：检索明明白白找到了东西，小模型却
    # 说「语料里没有」，这种拒答多半是它读不懂而不是语料确实没有（实测 q02）。
    if _flag("MINGLI_ROUTER_ESCALATE_REFUSAL", True) and result.get("can_answer") is False:
        if hits:
            try:
                limit = float(_env("MINGLI_ROUTER_REFUSAL_MIN_SCORE") or 0.10)
            except ValueError:
                limit = 0.10
            top = max((_hit_score(h) for h in hits), default=0.0)
            if top >= limit:
                return True, "检索分数 {:.3f} 达到升级线".format(top)
    return False, ""


def _hit_score(hit) -> float:
    """检索命中的分数：RRF 模式写 `rrf_score`，其他模式写 `score`。"""
    if not isinstance(hit, dict):
        return 0.0
    for key in ("score", "rrf_score"):
        value = hit.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0
