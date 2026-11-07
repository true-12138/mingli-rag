# -*- coding: utf-8 -*-
"""工具 schema 与工具实现必须对得上。

用 AST 读 tools.py，不 import —— 导入 tools 会连带加载语料和 BGE-M3，
这个测试要保持秒级、能在没有模型权重的机器上跑。
"""
import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))


@pytest.fixture(scope="module")
def tools_ast():
    tree = ast.parse((SRC / "tools.py").read_text(encoding="utf-8"))
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    tools_dict = next(
        n for n in tree.body
        if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "TOOLS" for t in n.targets)
    )
    names = [k.value for k in tools_dict.value.keys]
    return funcs, names


def test_schema_names_match_tools(tools_ast):
    funcs, names = tools_ast
    from tool_schema import SCHEMAS

    schema_names = [s["function"]["name"] for s in SCHEMAS]
    assert len(schema_names) == len(set(schema_names)), "schema 里有重名"
    assert set(schema_names) == set(names)


def test_required_params_exist_in_signature(tools_ast):
    funcs, _ = tools_ast
    from tool_schema import SCHEMAS

    for schema in SCHEMAS:
        fn = schema["function"]
        name = fn["name"]
        sig = funcs[name]
        params = [a.arg for a in sig.args.args]
        required = fn["parameters"].get("required", [])
        for r in required:
            assert r in params, "{}: schema 要求 {}，但函数签名里没有".format(name, r)
        # 函数里没有默认值的参数，都必须出现在 required 里
        positional = sig.args.args
        defaults = sig.args.defaults
        first_default = len(positional) - len(defaults)
        for i, arg in enumerate(positional):
            if i < first_default:
                assert arg.arg in required, \
                    "{}: 函数参数 {} 无默认值，schema 却没标 required".format(name, arg.arg)


def test_schema_props_are_real_params(tools_ast):
    funcs, _ = tools_ast
    from tool_schema import SCHEMAS

    for schema in SCHEMAS:
        fn = schema["function"]
        params = {a.arg for a in funcs[fn["name"]].args.args}
        for prop in fn["parameters"].get("properties", {}):
            assert prop in params, "{}: schema 里的 {} 不是函数参数".format(fn["name"], prop)
