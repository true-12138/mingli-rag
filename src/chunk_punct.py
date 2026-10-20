# -*- coding: utf-8 -*-
"""07/08 标点组 chunk + meta 生成入口。

只扫描：
    data/clean_text/07_星命七政四余/标点组/*.txt
    data/clean_text/08_八字禄命/标点组/*.txt

输出：
    data/chunks/punct.jsonl         每行 = 一个 chunk + 内嵌 meta（唯一事实来源）
    data/chunks/punct_report.json   每本书的结构/chunk 统计与覆盖率

meta 内嵌在 chunk 行里，因此结构上保证「一条 chunk 对应一条 meta」。
不改动 clean_text 或其他类别的数据。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

try:  # 作为包导入
    from . import chunk_meta
except ImportError:  # 直接运行 src/chunk_punct.py
    import chunk_meta

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean_text"
CATS = chunk_meta.CATS

OUT_CHUNKS = ROOT / "data" / "chunks" / "punct.jsonl"
OUT_REPORT = ROOT / "data" / "chunks" / "punct_report.json"


def _utf8_stdout():
    """Windows 控制台默认 cp936，统一切到 UTF-8，避免中文输出乱码。"""
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


def _iter_books():
    for cat in CATS:
        dp = CLEAN / cat / "标点组"
        if not dp.exists():
            yield cat, dp, []
            continue
        yield cat, dp, sorted(dp.glob("*.txt"))


def main() -> int:
    _utf8_stdout()
    OUT_CHUNKS.parent.mkdir(parents=True, exist_ok=True)
    tmp_chunks = OUT_CHUNKS.with_name(OUT_CHUNKS.name + ".tmp")

    books = []
    errors = []
    chunk_id = 0
    type_counts = Counter()
    missing = Counter()
    total_chars = 0
    seen_files = []

    with open(tmp_chunks, "w", encoding="utf-8", newline="\n") as fc:
        for cat, dp, files in _iter_books():
            if not dp.exists():
                errors.append(f"目录不存在：{_rel(dp)}")
                continue
            if not files:
                errors.append(f"目录下没有 txt：{_rel(dp)}")
                continue
            print(f"\n[{cat}] {len(files)} 本")
            for path in files:
                try:
                    result = chunk_meta.build_book_chunks(cat, path, CLEAN)
                except Exception as exc:  # 保留其他书的产出，报告里记录
                    errors.append(f"{_rel(path)}: {type(exc).__name__}: {exc}")
                    print(f"  [失败] {path.name}: {exc}")
                    continue

                rows = result["chunks"]
                for row in rows:
                    chunk_id += 1
                    row["chunk_id"] = chunk_id
                    fc.write(json.dumps(row, ensure_ascii=False) + "\n")

                stats = dict(result["stats"])
                stats["chunk_id_start"] = chunk_id - len(rows) + 1 if rows else None
                stats["chunk_id_end"] = chunk_id if rows else None
                books.append(stats)

                type_counts.update(stats["chunk_types"])
                total_chars += stats["chars_total"]
                missing["book"] += sum(1 for r in rows if not r["meta"].get("book"))
                missing["category"] += sum(1 for r in rows if not r["meta"].get("category"))
                missing["volume"] += stats["missing_volume"]
                missing["chapter"] += stats["missing_chapter"]
                missing["section_path"] += stats["missing_section_path"]
                missing["chunk_uid"] += sum(1 for r in rows if not r["meta"].get("chunk_uid"))
                seen_files.append(result["sourcefile"])

                print(
                    f"  {result['book']}: {stats['n']} chunks | "
                    f"sections={stats['sections']} groups={stats['groups']} | "
                    f"p50={stats['p50']} p90={stats['p90']} max={stats['max']} "
                    f"small={stats['small']} | types={stats['chunk_types']}"
                )

    tmp_chunks.replace(OUT_CHUNKS)

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "script": _rel(Path(__file__)),
        "scope": {
            "categories": CATS,
            "pattern": "data/clean_text/<category>/标点组/*.txt",
            "files": len(seen_files),
        },
        "params": {
            "target": chunk_meta.TARGET,
            "max": chunk_meta.MAX,
            "min": chunk_meta.MIN,
            "overlap": chunk_meta.OVERLAP,
        },
        "outputs": {
            "chunks": _rel(OUT_CHUNKS),
        },
        "books": books,
        "totals": {
            "books": len(books),
            "chunks": chunk_id,
            "chars": total_chars,
            "chunk_types": dict(type_counts),
        },
        "coverage": {
            "missing_book": missing["book"],
            "missing_category": missing["category"],
            "missing_volume": missing["volume"],
            "missing_chapter": missing["chapter"],
            "missing_section_path": missing["section_path"],
            "missing_chunk_uid": missing["chunk_uid"],
            "note": "volume 为空表示原书没有可识别的卷次结构，不代表解析失败。",
        },
        "errors": errors,
    }
    OUT_REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print(f"chunk 总数：{chunk_id}，书数：{len(books)}，字符数：{total_chars}")
    print(f"chunk 类型：{dict(type_counts)}")
    print(f"缺失 book/category/chapter/section_path/chunk_uid："
          f"{missing['book']}/{missing['category']}/{missing['chapter']}/"
          f"{missing['section_path']}/{missing['chunk_uid']}")
    print(f"缺失 volume（原书无卷次）：{missing['volume']}")
    print(f"输出：{_rel(OUT_CHUNKS)}")
    print(f"报告：{_rel(OUT_REPORT)}")
    if errors:
        print(f"\n有 {len(errors)} 个错误：")
        for err in errors:
            print("  -", err)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
