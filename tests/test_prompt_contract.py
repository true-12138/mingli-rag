# -*- coding: utf-8 -*-
"""JSON 模式的前置条件：提示词里必须出现 "json" 这个词。

DeepSeek 的 response_format=json_object 要求 prompt 里含 json 关键字，
否则直接 400。这个约束不在类型系统里，只能靠测试守：
D2 改造检索员时删掉了「输出 JSON」这句话，多智能体全量跑出 19 条 400。
用源码正则而不是 import，避免加载语料和模型。
"""
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"


def _prompt(source: str, name: str) -> str:
    src = (SRC / source).read_text(encoding="utf-8")
    m = re.search(name + r'\s*=\s*"""(.*?)"""', src, re.S)
    assert m, "{} 里找不到 {}".format(source, name)
    return m.group(1)


# 所有走 rag._chat（response_format=json_object）的 prompt 都在这里。
# 只守检索员那两个不够：D2 之前 PLANNER / VERIFIER / SYNTHESIZER 也共用一个坑。
@pytest.mark.parametrize("source,name", [
    ("agent.py", "SYSTEM_PROMPT"),
    ("agent.py", "FUNCTION_SYSTEM_PROMPT"),
    ("agent_multi.py", "PLANNER_PROMPT"),
    ("agent_multi.py", "RETRIEVER_PROMPT"),
    ("agent_multi.py", "VERIFIER_PROMPT"),
    ("agent_multi.py", "SYNTHESIZER_PROMPT"),
    ("rag.py", "SYSTEM_PROMPT"),
    ("interpret.py", "INTERPRET_PROMPT"),
    ("segment.py", "SEGMENT_PROMPT"),
])
def test_json_mode_prompts_mention_json(source, name):
    """这些提示词都会配 response_format=json_object 使用，必须含 json 字样。"""
    body = _prompt(source, name)
    assert re.search(r"json", body, re.I), \
        "{} 缺 json 关键字，JSON 模式会 400".format(name)


# 出口拒答判据：有原文证据时，不能仅因「表述不标准 / 没有定义句式」拒答。
# 它对应的失分是 eval/multiturn.jsonl 的 mt17（v6-v8 多轮集里反复出现的失分点）。
# 这几个 prompt 都能直接决定 can_answer，改措辞时容易把这条一起删掉，所以钉住。
OVER_REFUSAL_MARKERS = [
    ("rag.py", "SYSTEM_PROMPT", "不算证据不足"),
    ("agent.py", "SYSTEM_PROMPT", "不算证据不足"),
    ("agent.py", "FUNCTION_SYSTEM_PROMPT", "不算证据不足"),
    ("agent_multi.py", "SYNTHESIZER_PROMPT", "不等于材料不足"),
    # 校验员这一侧守的是「对象有、清单类属性不全 → 先补检索，别直接判不足」
    ("agent_multi.py", "VERIFIER_PROMPT", "属性词"),
    # mt17（v8 多 Agent 挂、单 Agent 过）：「原文只讲义理和用法，没有『甲见辛之类』
    # 那种形式化定义」被读成证据不足，整题拒答。定义类问题必须认义理/作用/分类/取舍。
    ("rag.py", "SYSTEM_PROMPT", "形式化定义"),
    ("agent.py", "SYSTEM_PROMPT", "形式化定义"),
    ("agent.py", "FUNCTION_SYSTEM_PROMPT", "形式化定义"),
    ("agent_multi.py", "SYNTHESIZER_PROMPT", "形式化定义"),
    ("agent_multi.py", "VERIFIER_PROMPT", "形式化定义"),
]


@pytest.mark.parametrize("source,name,marker", OVER_REFUSAL_MARKERS)
def test_refusal_prompts_keep_anti_over_refusal_rule(source, name, marker):
    body = _prompt(source, name)
    assert marker in body, \
        "{} 里缺「{}」：有证据却因谨慎拒答的判据丢了".format(name, marker)


# 放宽拒答的同时，跨时代类比的硬拒答必须还在：这两条是反方向的约束，
# 少了它，「不因谨慎拒答」会被读成「什么都能答」。
MODERN_LIFE_MARKERS = [
    ("rag.py", "SYSTEM_PROMPT"),
    ("agent.py", "SYSTEM_PROMPT"),
    ("agent.py", "FUNCTION_SYSTEM_PROMPT"),
    ("agent_multi.py", "SYNTHESIZER_PROMPT"),
]


@pytest.mark.parametrize("source,name", MODERN_LIFE_MARKERS)
def test_refusal_prompts_keep_modern_life_guard(source, name):
    body = _prompt(source, name)
    assert "科举" in body and "财星" in body, \
        "{} 丢了「古代概念≠现代生活」的拒答例子".format(name)


# mt19 的实测（2026-11-17，3 次复跑：PASS/PASS/FAIL + 一次重跑 FAIL）：放宽出口判据后，
# 「那我今年适合加杠杆买股票吗」会被规则「有一部分就答这一部分」拆成「财星概念可答 +
# 投资不可答」，于是 can_answer=true 并引了《三命通会》。现实决策类问题必须整题拒答，
# 而且要压过「部分回答」那条，否则放宽后的出口判据会把它读回来。
DECISION_GUARD_MARKERS = [
    ("rag.py", "SYSTEM_PROMPT"),
    ("agent.py", "SYSTEM_PROMPT"),
    ("agent.py", "FUNCTION_SYSTEM_PROMPT"),
    ("agent_multi.py", "SYNTHESIZER_PROMPT"),
]


@pytest.mark.parametrize("source,name", DECISION_GUARD_MARKERS)
def test_refusal_prompts_keep_decision_guard(source, name):
    body = _prompt(source, name)
    assert "现实决定" in body and "整题拒答" in body, \
        "{} 丢了「拿命理替现实决定→整题拒答」这条，mt19 会重新被部分回答".format(name)


# mt09 的实测：目标原文（chunk 8213，同时讲建日/除日）在 BM25 限书检索里
# 「除日」排第 15、「除日 宜 忌」排第 8，k=8 拿不到；但同一 chunk 在上一轮
# 「建日 宜」里排第 1。检索员必须知道要放大 k，否则只会判「没有原文」。
def test_retriever_prompt_tells_to_widen_k():
    body = _prompt("agent_multi.py", "RETRIEVER_PROMPT")
    assert "k=20" in body and "清单类" in body, \
        "RETRIEVER_PROMPT 丢了「清单类问题放大 k 再搜」这条，mt09 一类会继续漏召回"
