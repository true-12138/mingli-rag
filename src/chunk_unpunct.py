# -*- coding: utf-8 -*-
"""无标点组处理入口（对应 PLAN.md 第 2 周 D4）。

做法
----
1. 扫描 ``data/clean_text`` 下全部 txt，选出标点率 < 2% 的文本
   （与 PLAN.md 实测的 29 部一致；07/08 下已归入「无标点组」的 7 部也在其中）；
2. 按刻本行款合并：连续行合并成约 200 字的段落（5～8 行一段）；
   单行超过 MAX 时直接硬切，不丢字；
3. **不做断句**，段落作为最小单位，按约 450 字组成 chunk，
   overlap 只取完整段落，避免把句子从中间切开；
4. 输出独立的 chunk / meta / 报告，不改写任何语料文件，也不覆盖标点组产物。

这一版刻意不做卷、篇、章结构解析：无标点古籍的行款差异很大，
结构字段留空是设计选择，不是解析失败。

输出
----
    data/chunks/unpunct.jsonl        每行 = 一个 chunk + 内嵌 meta（唯一事实来源）
    data/chunks/unpunct_report.json  每本书的行数/段数/chunk 统计
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

try:  # 作为包导入
    from .chunk_meta import TARGET, MAX, MIN, OVERLAP, chunk_stats
except ImportError:  # 直接运行 src/chunk_unpunct.py
    from chunk_meta import TARGET, MAX, MIN, OVERLAP, chunk_stats

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean_text"

OUT_CHUNKS = ROOT / "data" / "chunks" / "unpunct.jsonl"
OUT_REPORT = ROOT / "data" / "chunks" / "unpunct_report.json"

# 选书与分段参数
PUNCT_CHARS = set("。！？，；：、,;:!?")
PUNCT_RE = re.compile(r"[。！？，；：、,;:!?]")
PUNCT_RATE_MAX = 0.02   # PLAN.md：<2% 视为无标点/极少标点
MIN_BOOK_CHARS = 200    # 太短的文件不参与
PARA_TARGET = 200       # 一段约 200 字
PARA_MAX_LINES = 8      # 一段最多 8 行
GROUP_NAME = "无标点组"


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


def punct_rate(text: str) -> float:
    if not text:
        return 0.0
    return sum(1 for ch in text if ch in PUNCT_CHARS) / len(text)


def _hard_split_keep(s: str, limit: int):
    """按 limit 硬切，但不 strip，保证各段拼回去与原文逐字相同。"""
    if len(s) <= limit:
        return [s]
    out = []
    while len(s) > limit:
        cut = max(s.rfind(ch, 0, limit) for ch in "，、；")
        if cut < limit // 2:
            cut = limit - 1
        out.append(s[:cut + 1])
        s = s[cut + 1:]
    if s:
        out.append(s)
    return out


def read_lines(path: Path):
    """返回 [(行文本, 行号)]，行号从 1 开始，去掉空行和首尾行款空白。"""
    out = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = raw.strip(" \t　 ")
        if text:
            out.append((text, lineno))
    return out


def merge_paragraphs(lines):
    """按刻本行款把连续行合并成段。

    段落边界（任一满足即断段）：
    - 已有约 PARA_TARGET 字；
    - 已有 PARA_MAX_LINES 行；
    - 再合并会超过 MAX（保持单段不超过一个 chunk 的上限）。
    单行本身超过 MAX 时先冲掉缓冲，再硬切成若干段。
    """
    paras = []
    buf = []
    buf_len = 0

    def flush():
        nonlocal buf, buf_len
        if buf:
            paras.append({
                "text": "".join(x[0] for x in buf),
                "line_start": buf[0][1],
                "line_end": buf[-1][1],
                "n_lines": len(buf),
            })
            buf = []
            buf_len = 0

    for text, lineno in lines:
        if len(text) > MAX:
            flush()
            for piece in _hard_split_keep(text, MAX):
                paras.append({
                    "text": piece,
                    "line_start": lineno,
                    "line_end": lineno,
                    "n_lines": 1,
                })
            continue

        if buf and (
            buf_len >= PARA_TARGET
            or len(buf) >= PARA_MAX_LINES
            or buf_len + len(text) > MAX
        ):
            flush()

        buf.append((text, lineno))
        buf_len += len(text)

    flush()
    return paras


def merge_tiny_paragraphs(paras):
    """把短于 MIN 的段落并入相邻段落，避免标题行单独成为一个 chunk。

    无标点文本里常有「论五行生成」这类独立标题行；如果它后面紧跟一个
    接近 MAX 的长段落，按 MAX 断段会把标题单独切出来。这里统一向后合并，
    合并后的段落可能略超 MAX，但不会再产生 2～5 字的碎块。
    """
    out = []
    buf = None

    def concat(a, b):
        return {
            "text": a["text"] + b["text"],
            "line_start": min(a["line_start"], b["line_start"]),
            "line_end": max(a["line_end"], b["line_end"]),
            "n_lines": a["n_lines"] + b["n_lines"],
        }

    for p in paras:
        buf = dict(p) if buf is None else concat(buf, p)
        if len(buf["text"]) >= MIN:
            out.append(buf)
            buf = None

    if buf is not None:
        if out:
            out[-1] = concat(out[-1], buf)
        else:
            out.append(buf)
    return out


def group_chunks(paras):
    """把段落按 TARGET 组合成 chunk；overlap 只取完整段落。"""
    chunks = []
    cur = []
    cur_len = 0

    for p in paras:
        if cur and cur_len + len(p["text"]) > TARGET:
            chunks.append(cur)
            ov = []
            ov_len = 0
            for old in reversed(cur):
                if ov_len + len(old["text"]) > OVERLAP:
                    break
                ov.insert(0, old)
                ov_len += len(old["text"])
            cur = ov
            cur_len = ov_len
        cur.append(p)
        cur_len += len(p["text"])

    if cur:
        chunks.append(cur)

    # 开头的短块并入下一块
    if len(chunks) >= 2 and sum(len(x["text"]) for x in chunks[0]) < MIN:
        if sum(len(x["text"]) for x in chunks[0]) + sum(len(x["text"]) for x in chunks[1]) <= MAX + OVERLAP:
            chunks[1] = chunks[0] + chunks[1]
            chunks.pop(0)
    # 结尾的短块并入上一块
    if len(chunks) >= 2 and sum(len(x["text"]) for x in chunks[-1]) < MIN:
        if sum(len(x["text"]) for x in chunks[-2]) + sum(len(x["text"]) for x in chunks[-1]) <= MAX:
            chunks[-2].extend(chunks[-1])
            chunks.pop()

    out = []
    for c in chunks:
        # 不 strip：硬切片段可能以空格开头/结尾，strip 会丢字
        text = "\n".join(x["text"] for x in c)
        if not text.strip():
            continue
        out.append({
            "text": text,
            "line_start": min(x["line_start"] for x in c),
            "line_end": max(x["line_end"] for x in c),
            "char_count": len(text),
            "paragraphs": len(c),
        })
    return out


def build_book(category: str, path: Path):
    """返回一本书的全部 chunk、统计与标点率。"""
    book = path.stem
    rel = _rel(path)
    raw = path.read_text(encoding="utf-8")
    rate = punct_rate(raw)

    lines = read_lines(path)
    paras = merge_paragraphs(lines)
    paras = merge_tiny_paragraphs(paras)
    chunks = group_chunks(paras)

    rows = []
    for idx, c in enumerate(chunks, 1):
        meta = {
            "book": book,
            "category": category,
            # 无标点组不做结构解析：卷/篇/章留空是设计选择
            "volume": "",
            "group": GROUP_NAME,
            "chapter": "",
            "section_titles": [],
            "section_path": [GROUP_NAME],
            "section_id": "U",
            "sourcefile": rel,
            "chunk_index": idx,
            "chunk_total": len(chunks),
            "line_start": c["line_start"],
            "line_end": c["line_end"],
            "char_count": c["char_count"],
            "paragraphs": c["paragraphs"],
            "chunk_type": "unpunct",
            "has_punctuation": bool(PUNCT_RE.search(c["text"])),
            "punct_rate": round(rate, 6),
        }
        meta["chunk_uid"] = "%s/%s/U/C%04d" % (category, book, idx)
        meta["text_for_embedding"] = "《%s》\n%s" % (book, c["text"])
        rows.append({
            "sourcefile": rel,
            "chunk_id": None,
            "chunk_text": c["text"],
            "meta": meta,
        })

    stats = chunk_stats([r["meta"] for r in rows])
    stats.update({
        "book": book,
        "category": category,
        "sourcefile": rel,
        "lines": len(lines),
        "paragraphs": len(paras),
        "punct_rate": round(rate, 6),
    })
    return {
        "book": book,
        "category": category,
        "sourcefile": rel,
        "punct_rate": rate,
        "chunks": rows,
        "stats": stats,
    }


def iter_books():
    """按类别扫描，返回 (category, path)。只有标点率 < 2% 的文本入选。"""
    for path in sorted(CLEAN.rglob("*.txt")):
        text = path.read_text(encoding="utf-8")
        if len(text) < MIN_BOOK_CHARS:
            continue
        rate = punct_rate(text)
        if rate >= PUNCT_RATE_MAX:
            continue
        try:
            rel = path.relative_to(CLEAN)
        except ValueError:
            continue
        yield rel.parts[0], path


def main() -> int:
    _utf8_stdout()
    OUT_CHUNKS.parent.mkdir(parents=True, exist_ok=True)
    tmp_chunks = OUT_CHUNKS.with_name(OUT_CHUNKS.name + ".tmp")

    books = []
    errors = []
    chunk_id = 0
    total_chars = 0
    missing = Counter()
    seen_files = []
    cats = Counter()

    with open(tmp_chunks, "w", encoding="utf-8", newline="\n") as fc:
        for category, path in iter_books():
            try:
                result = build_book(category, path)
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

            total_chars += stats["chars_total"]
            missing["book"] += sum(1 for r in rows if not r["meta"].get("book"))
            missing["category"] += sum(1 for r in rows if not r["meta"].get("category"))
            missing["volume"] += sum(1 for r in rows if not r["meta"].get("volume"))
            missing["chapter"] += sum(1 for r in rows if not r["meta"].get("chapter"))
            missing["section_path"] += sum(1 for r in rows if not r["meta"].get("section_path"))
            missing["chunk_uid"] += sum(1 for r in rows if not r["meta"].get("chunk_uid"))
            seen_files.append(result["sourcefile"])
            cats[category] += len(rows)

            print(
                f"  [{category}] {result['book']}: {stats['n']} chunks | "
                f"lines={stats['lines']} paras={stats['paragraphs']} | "
                f"p50={stats['p50']} p90={stats['p90']} max={stats['max']} "
                f"small={stats['small']} | punct={result['punct_rate']*100:.2f}%"
            )

    tmp_chunks.replace(OUT_CHUNKS)

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "script": _rel(Path(__file__)),
        "scope": {
            "pattern": "data/clean_text/**/*.txt",
            "selection": "punct_rate < %.0f%%" % (PUNCT_RATE_MAX * 100),
            "files": len(seen_files),
        },
        "params": {
            "para_target": PARA_TARGET,
            "para_max_lines": PARA_MAX_LINES,
            "target": TARGET,
            "max": MAX,
            "min": MIN,
            "overlap": OVERLAP,
            "no_sentence_split": True,
        },
        "outputs": {
            "chunks": _rel(OUT_CHUNKS),
        },
        "categories": dict(cats),
        "books": books,
        "totals": {
            "books": len(books),
            "chunks": chunk_id,
            "chars": total_chars,
        },
        "coverage": {
            "missing_book": missing["book"],
            "missing_category": missing["category"],
            "missing_volume": missing["volume"],
            "missing_chapter": missing["chapter"],
            "missing_section_path": missing["section_path"],
            "missing_chunk_uid": missing["chunk_uid"],
            "note": (
                "无标点组只做行款合并，不解析卷/篇/章；"
                "volume、chapter 为空是设计选择，不代表数据缺失。"
            ),
        },
        "errors": errors,
    }
    OUT_REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print(f"chunk 总数：{chunk_id}，书数：{len(books)}，字符数：{total_chars}")
    print(f"按类别：{dict(cats)}")
    print(f"volume/chapter 为空（设计如此）：{missing['volume']}/{missing['chapter']}")
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
