# -*- coding: utf-8 -*-
"""检查合并后的语料，并生成索引报告。

不做任何改写：源文件保持原样，合并顺序和编号规则由 src/corpus.py 统一决定。
这个脚本只负责"在花一小时编码之前，先把会静默出错的地方查出来"：

1. chunk_id 是否 1..N 连续且唯一；
2. chunk_uid 是否重复；
3. 必需字段是否齐全（sourcefile / chunk_text / meta / text_for_embedding）；
4. 标点组在合并后的编号是否仍与原始 chunk_id 一致
   （一旦不一致，eval/questions.jsonl 的 gold_chunk_ids 全部失效）；
5. 评测题的 gold_chunk_ids 是否都还落在有效范围内。

用法::

    python src/build_index.py            # 只检查 + 出报告
    python src/build_index.py --emit     # 额外落一份 all.jsonl 方便肉眼检查
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

import corpus


def _utf8_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _load_jsonl(path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main() -> int:
    _utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", action="store_true", help="额外输出 data/chunks/all.jsonl")
    args = ap.parse_args()

    dd = corpus.data_dir()
    raw_punct = _load_jsonl(dd / "chunks" / "punct.jsonl")
    chunks = corpus.load_chunks(dd)
    n_punct = len(raw_punct)
    n_total = len(chunks)

    errors = []
    warnings = []

    # 1. 编号连续且唯一
    ids = [c["chunk_id"] for c in chunks]
    if ids != list(range(1, n_total + 1)):
        errors.append("chunk_id 不是 1..N 连续编号")

    # 2. chunk_uid 唯一
    uids = [c.get("meta", {}).get("chunk_uid") for c in chunks]
    dup_uid = [u for u, n in Counter(uids).items() if n > 1]
    if None in uids:
        warnings.append(f"有 {uids.count(None)} 条缺少 chunk_uid（不影响检索，但无法作为稳定主键）")
    if dup_uid:
        errors.append(f"chunk_uid 重复 {len(dup_uid)} 个，例如 {dup_uid[:3]}")

    # 3. 必需字段
    missing = Counter()
    for c in chunks:
        for field in corpus.REQUIRED_FIELDS:
            if not c.get(field):
                missing[field] += 1
        if not c.get("meta", {}).get("text_for_embedding"):
            missing["meta.text_for_embedding"] += 1
    for field, n in missing.items():
        errors.append(f"{field} 缺失或为空：{n} 条")

    # 4. 标点组编号没有漂移（eval 的 gold_chunk_ids 依赖它）
    drifted = [
        (i + 1, raw["chunk_id"], chunks[i]["chunk_id"])
        for i, raw in enumerate(raw_punct)
        if raw["chunk_id"] != chunks[i]["chunk_id"]
    ]
    if drifted:
        errors.append(
            f"标点组编号漂移 {len(drifted)} 条，例如 行{i} 原 {old} -> 现 {new}".format(
                i=drifted[0][0], old=drifted[0][1], new=drifted[0][2]
            )
        )

    # 5. 评测 gold 仍有效
    qpath = dd.parent / "eval" / "questions.jsonl"
    gold_total = 0
    if qpath.exists():
        questions = _load_jsonl(qpath)
        id_set = set(ids)
        bad_gold = []
        for q in questions:
            for g in q.get("gold_chunk_ids") or []:
                gold_total += 1
                if g not in id_set:
                    bad_gold.append((q.get("id"), g))
                elif g > n_punct:
                    warnings.append(f"{q.get('id')} 的 gold {g} 落在无标点组，确认是否期望")
        if bad_gold:
            errors.append(f"评测 gold 指向不存在的 chunk_id：{bad_gold[:5]}")
    else:
        warnings.append(f"没找到评测题：{qpath}")

    # 统计
    by_source = Counter(c["meta"]["index_source"] for c in chunks)
    books = {src: sorted({c["meta"].get("book", "") for c in chunks if c["meta"]["index_source"] == src})
             for src in by_source}
    chars = {src: sum(len(c["chunk_text"]) for c in chunks if c["meta"]["index_source"] == src)
             for src in by_source}
    empty_meta = {
        "volume": sum(1 for c in chunks if not c["meta"].get("volume")),
        "chapter": sum(1 for c in chunks if not c["meta"].get("chapter")),
    }

    report = {
        "generated_by": "src/build_index.py",
        "corpus_files": [f for f, _ in corpus.CORPUS_FILES],
        "chunks": {
            "total": n_total,
            "by_source": dict(by_source),
            "books": {k: len(v) for k, v in books.items()},
        },
        "chars_by_source": chars,
        "chars_total": sum(chars.values()),
        "empty_meta": empty_meta,
        "id_range": {"punct": f"1..{n_punct}", "unpunct": f"{n_punct + 1}..{n_total}"},
        "eval": {"questions": len(questions) if qpath.exists() else 0, "gold_refs": gold_total},
        "errors": errors,
        "warnings": warnings,
    }

    out = dd / "chunks" / "index_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"语料总数      : {n_total}")
    print(f"  标点组      : {by_source.get('punct', 0):>5} 条 / {len(books.get('punct', []))} 部 / {chars.get('punct', 0):,} 字")
    print(f"  无标点组    : {by_source.get('unpunct', 0):>5} 条 / {len(books.get('unpunct', []))} 部 / {chars.get('unpunct', 0):,} 字")
    print(f"编号区间      : punct 1..{n_punct} / unpunct {n_punct + 1}..{n_total}")
    print(f"空 volume     : {empty_meta['volume']} 条   空 chapter: {empty_meta['chapter']} 条")
    print(f"评测 gold 引用: {gold_total} 处")
    print(f"报告          : {out}")

    for w in warnings:
        print(f"[WARN] {w}")
    if errors:
        for e in errors:
            print(f"[FAIL] {e}")
        print("\n检查未通过，先修数据再编码。")
        return 1

    if args.emit:
        merged = dd / "chunks" / "all.jsonl"
        with merged.open("w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        print(f"[emit] 已写出 {merged}")

    print("\n检查通过，可以跑 python src/embed.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
