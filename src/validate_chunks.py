# -*- coding: utf-8 -*-
"""校验 data/chunks/*.jsonl 的数据契约。

用法：
    python -S src/validate_chunks.py
    python -S src/validate_chunks.py data/chunks/punct.jsonl

检查项：
1. 每行是一个合法 JSON，且 chunk_text / meta / chunk_uid 非空；
2. chunk_id 在单文件内从 1 连续递增且唯一；
3. chunk_uid 全局唯一（跨文件也不重复）；
4. 同一个 chunk_uid 前缀（category/book/section_id）内，
   chunk_index 从 1 连续到 chunk_total；
5. char_count == len(chunk_text)；
6. line_start <= line_end；
7. meta 必需字段齐全，chunk_type 在允许集合内。
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILES = [
    ROOT / "data" / "chunks" / "punct.jsonl",
    ROOT / "data" / "chunks" / "unpunct.jsonl",
]
REQUIRED_META = [
    "book", "category", "volume", "group", "chapter", "section_titles",
    "section_path", "section_id", "line_start", "line_end", "chunk_index",
    "chunk_total", "char_count", "chunk_type", "has_punctuation",
    "chunk_uid", "text_for_embedding",
]
ALLOWED_TYPES = {"body", "chart", "verse", "unpunct"}


def _utf8_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def load_jsonl(path: Path):
    rows = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append((lineno, json.loads(line)))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{_rel(path)}:{lineno}: JSON 解析失败：{exc}") from exc
    return rows


def validate_file(path: Path, errors, warnings, seen_uids):
    rows = load_jsonl(path)
    if not rows:
        errors.append(f"{_rel(path)}: 空文件")
        return {"rows": 0, "books": set(), "chars": 0, "types": Counter(), "missing_volume": 0}

    books = set()
    chars = 0
    types = Counter()
    missing_volume = 0
    ids = []
    uid_to_line = {}
    groups = defaultdict(list)
    texts = Counter()

    for lineno, row in rows:
        where = f"{_rel(path)}:{lineno}"
        if not isinstance(row, dict):
            errors.append(f"{where}: 行不是 JSON object")
            continue

        chunk_id = row.get("chunk_id")
        if not isinstance(chunk_id, int):
            errors.append(f"{where}: chunk_id 不是整数：{chunk_id!r}")
        else:
            ids.append(chunk_id)

        chunk_text = row.get("chunk_text")
        if not isinstance(chunk_text, str) or not chunk_text.strip():
            errors.append(f"{where}: chunk_text 为空")
            chunk_text = ""
        texts[chunk_text] += 1
        chars += len(chunk_text)

        sourcefile = row.get("sourcefile")
        if not isinstance(sourcefile, str) or not sourcefile.strip():
            errors.append(f"{where}: sourcefile 为空")

        meta = row.get("meta")
        if not isinstance(meta, dict):
            errors.append(f"{where}: 缺少 meta 或 meta 不是 object")
            continue

        for key in REQUIRED_META:
            if key not in meta:
                errors.append(f"{where}: meta 缺少字段 {key}")

        uid = meta.get("chunk_uid")
        if not isinstance(uid, str) or not uid.strip():
            errors.append(f"{where}: chunk_uid 为空")
            uid = ""
        else:
            if uid in seen_uids:
                errors.append(f"{where}: chunk_uid 重复：{uid}（另见 {seen_uids[uid]}）")
            else:
                seen_uids[uid] = where
            uid_to_line[uid] = where
            prefix = uid.rsplit("/C", 1)[0]
            groups[prefix].append((uid, meta.get("chunk_index"),
                                   meta.get("chunk_total"), where))

        book = meta.get("book")
        if not isinstance(book, str) or not book.strip():
            errors.append(f"{where}: meta.book 为空")
        else:
            books.add(book)

        if not meta.get("category"):
            errors.append(f"{where}: meta.category 为空")

        if not meta.get("volume"):
            missing_volume += 1

        if not meta.get("text_for_embedding"):
            errors.append(f"{where}: meta.text_for_embedding 为空")

        ctype = meta.get("chunk_type")
        types[ctype] += 1
        if ctype not in ALLOWED_TYPES:
            errors.append(f"{where}: 未知 chunk_type：{ctype!r}")

        if meta.get("char_count") != len(chunk_text):
            errors.append(
                f"{where}: char_count={meta.get('char_count')!r} "
                f"与 len(chunk_text)={len(chunk_text)} 不一致"
            )
        ls, le = meta.get("line_start"), meta.get("line_end")
        if not isinstance(ls, int) or not isinstance(le, int) or ls > le:
            errors.append(f"{where}: line_start/line_end 非法：{ls!r}/{le!r}")
        if not isinstance(meta.get("has_punctuation"), bool):
            errors.append(f"{where}: has_punctuation 不是 bool")

    # chunk_id 连续且唯一
    if ids and sorted(ids) != list(range(1, len(ids) + 1)):
        missing = sorted(set(range(1, len(ids) + 1)) - set(ids))
        dup = [x for x, n in Counter(ids).items() if n > 1]
        errors.append(
            f"{_rel(path)}: chunk_id 不是 1..{len(ids)} 的连续序列；"
            f"缺失={missing[:10]} 重复={dup[:10]}"
        )

    # 每个 section/book 内 chunk_index 连续
    for prefix, items in groups.items():
        totals = {total for _, _, total, _ in items}
        indexes = sorted(i for _, i, _, _ in items if isinstance(i, int))
        total = next(iter(totals)) if len(totals) == 1 else None
        if len(totals) != 1:
            errors.append(f"{_rel(path)}: {prefix} 的 chunk_total 不一致：{sorted(totals)}")
            continue
        if indexes != list(range(1, total + 1)):
            errors.append(
                f"{_rel(path)}: {prefix} 的 chunk_index 不是 1..{total}：{indexes[:12]}"
            )

    dup_texts = [(t, n) for t, n in texts.items() if n > 1 and t]
    if dup_texts:
        warnings.append(
            f"{_rel(path)}: {len(dup_texts)} 组重复 chunk_text"
            f"（最多一组 {max(n for _, n in dup_texts)} 条）"
        )

    return {
        "rows": len(rows),
        "books": books,
        "chars": chars,
        "types": types,
        "missing_volume": missing_volume,
    }


def main(argv):
    _utf8_stdout()
    paths = [Path(x) for x in argv[1:]] or DEFAULT_FILES
    errors = []
    warnings = []
    seen_uids = {}

    print("=" * 72)
    for path in paths:
        if not path.exists():
            errors.append(f"文件不存在：{path}")
            continue
        stats = validate_file(path, errors, warnings, seen_uids)
        print(
            f"{_rel(path)}: rows={stats['rows']} books={len(stats['books'])} "
            f"chars={stats['chars']} types={dict(stats['types'])} "
            f"volume_empty={stats['missing_volume']}"
        )
    print("=" * 72)

    for w in warnings:
        print("警告:", w)
    if errors:
        print(f"发现 {len(errors)} 个错误：")
        for e in errors[:50]:
            print("  -", e)
        if len(errors) > 50:
            print(f"  ... 其余 {len(errors) - 50} 条省略")
        return 1
    print("校验通过：chunk 与内嵌 meta 一一对应，字段与编号连续。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
