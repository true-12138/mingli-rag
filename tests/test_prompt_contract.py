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


@pytest.mark.parametrize("source,name", [
    ("agent.py", "FUNCTION_SYSTEM_PROMPT"),
    ("agent_multi.py", "RETRIEVER_PROMPT"),
])
def test_json_mode_prompts_mention_json(source, name):
    """这两个提示词会配 response_format=json_object 使用，必须含 json 字样。"""
    body = _prompt(source, name)
    assert re.search(r"json", body, re.I), \
        "{} 缺 json 关键字，JSON 模式会 400".format(name)
