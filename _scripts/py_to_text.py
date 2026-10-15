#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把 Sudo-Biao/Chinese-Metaphysics-Platform (MIT) 的 knowledge/*.py 转成 RAG 文本。

安全说明：本脚本只用 ast.parse + ast.literal_eval 读取源码里的**字面量**，
不会执行被读取文件中的任何代码（不 import、不 eval、不 exec 该文件）。

用法: python -S py_to_text.py <knowledge目录> <输出目录>
"""
import ast
import json
import os
import sys


def render(v, indent=0):
    """把字面量渲染成可读文本。"""
    pad = "  " * indent
    if isinstance(v, dict):
        lines = []
        for k, val in v.items():
            if isinstance(val, (dict, list)):
                lines.append(f"{pad}{k}：")
                lines.append(render(val, indent + 1))
            else:
                lines.append(f"{pad}{k}：{val}")
        return "\n".join(lines)
    if isinstance(v, list):
        parts = []
        for item in v:
            if isinstance(item, (dict, list)):
                parts.append(render(item, indent + 1))
            else:
                parts.append(f"{pad}- {item}")
        return "\n".join(parts)
    return f"{pad}{v}"


def main():
    src_dir = os.path.abspath(sys.argv[1])
    out_dir = os.path.abspath(sys.argv[2])
    os.makedirs(out_dir, exist_ok=True)

    big_txt = []
    records = []
    summary = []

    for fn in sorted(os.listdir(src_dir)):
        if not fn.endswith(".py") or fn == "__init__.py":
            continue
        path = os.path.join(src_dir, fn)
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        try:
            tree = ast.parse(src)  # 只解析，不执行
        except SyntaxError as e:
            summary.append((fn, f"解析失败: {e}"))
            continue

        doc = ast.get_docstring(tree) or ""
        chunks = [f"# {fn}", f"# 来源：Sudo-Biao/Chinese-Metaphysics-Platform（MIT License）", ""]
        if doc:
            chunks.append("## 模块说明\n" + doc.strip() + "\n")

        n_vars = 0
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if not names:
                continue
            value_node = node.value
            try:
                value = ast.literal_eval(value_node)  # 仅字面量
            except (ValueError, SyntaxError):
                continue  # 含变量/函数调用，跳过
            for name in names:
                n_vars += 1
                chunks.append(f"\n## {name}\n")
                text = render(value)
                chunks.append(text)
                # 顶层为 dict 的，逐条产出 JSONL
                if isinstance(value, dict):
                    for k, v in value.items():
                        if isinstance(v, dict):
                            body = "；".join(
                                f"{kk}：{vv}" if not isinstance(vv, (dict, list)) else f"{kk}：{render(vv).strip()}"
                                for kk, vv in v.items()
                            )
                            records.append({"source": fn, "group": name, "term": str(k), "text": f"{k}：{body}"})
                        else:
                            records.append({"source": fn, "group": name, "term": str(k), "text": f"{k}：{v}"})

        body = "\n".join(chunks)
        with open(os.path.join(out_dir, fn.replace(".py", ".txt")), "w", encoding="utf-8") as f:
            f.write(body + "\n")
        big_txt.append(body)
        summary.append((fn, f"{n_vars} 个数据块, {len(body)} 字符"))

    with open(os.path.join(out_dir, "_全部合并.txt"), "w", encoding="utf-8") as f:
        f.write("\n\n".join(big_txt))
    with open(os.path.join(out_dir, "sudo-biao-terms.jsonl"), "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("转换结果：")
    for fn, s in summary:
        print(f"  {fn:34s} {s}")
    print(f"\n术语条目: {len(records)}")


if __name__ == "__main__":
    main()
