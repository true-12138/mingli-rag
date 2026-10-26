# 中文命理古籍 RAG —— 语料工程（v1）

> 免责声明：本项目仅作为大模型检索增强生成（RAG）技术、古籍文本处理方向的学习研究项目。项目内古籍文本仅为文史资料，不提供任何命理预测，不构成人生决策建议，请勿将模型输出结果用于现实判断。

本文件只讲 **“古籍全文 → 可检索 chunk”** 这一段：数据从哪来、怎么切、契约是什么、有哪些已知瑕疵。
检索、生成、评测和界面的说明见根目录 [`README.md`](../README.md)。

---

## 当前状态（2026-10-20）

| 产物 | 规模 | 状态 |
|---|---|---|
| `data/chunks/punct.jsonl` | **2,830 chunk / 16 部 / 1,168,327 字** | ✅ v1 唯一输入 |
| `data/chunks/unpunct.jsonl` | 5,851 chunk / 29 部 / 2,231,003 字 | ✅ 已切好，v2 才索引 |
| `data/terminology/*.jsonl` | 324 条术语（bazi 168 + iztro 60 + lunar 96） | ✅ BM25 词典 / 术语辅助 |
| `data/terminology/sudo-biao/` | 1,698 条结构化讲义 + 23 个 txt | ✅ 最贴合问答 |
| `data/clean_text/` | 152 部清洗后全文 | ✅ chunk 的只读输入 |

**v1 只使用标点组 16 部书。** 29 部无标点古籍（含《三命通会》《星学大成》）已经在 `unpunct.jsonl` 里切好，但按 `PLAN.md` 冻结到 v2，不进入 11 月 1 日前的 Demo。

---

## 目录结构

```text
.
├── README.md
├── PLAN.md                    # 11 月投递冲刺计划
├── ATTRIBUTION.md             # 语料来源与许可证
├── data/
│   ├── clean_text/            # 清洗后全文（chunk 的只读输入，不要改）
│   ├── terminology/           # 术语语料（jsonl + txt 视图）
│   ├── chunks/                # 唯一 chunk 产物
│   │   ├── punct.jsonl        #   标点组：2,830 行，一行 = 一个 chunk + 内嵌 meta
│   │   ├── punct_report.json  #   每本书的结构 / chunk 统计
│   │   ├── unpunct.jsonl      #   无标点组：5,851 行，同上
│   │   └── unpunct_report.json
│   ├── stats/                 # 语料统计（corpus_info、category_stats、clean_log）
│   └── _meta/                 # 书目清单、排除表、殆知阁 URL、标点扫描
├── src/
│   ├── chunk_meta.py          # 标点组结构解析与 meta 生成
│   ├── chunk_punct.py         # 标点组入口
│   ├── chunk_unpunct.py       # 无标点组入口（行款合并，不做断句）
│   ├── validate_chunks.py     # data/chunks 数据契约校验
│   ├── acquire/               # 外部数据获取 / 转换（殆知阁、iztro、lunar、bazi-terms、Sudo-Biao）
│   └── legacy/                # 早期 /workspace 语料流水线（不在 v1 关键路径上）
├── vendor/oss/                # 第三方源码包（tgz + 原始 py/ts；解压目录已移除，可按需重解）
├── docs/
│   ├── daily_dev_journal.md
│   └── eval_questions_seed.md # 30 条评测问题的种子（10 条已写答案）
└── notebooks/
    └── 01-analyse-corpus.ipynb
```

---

## 数据契约（下游只看这一节）

`data/chunks/punct.jsonl` 和 `data/chunks/unpunct.jsonl` 的每一行结构相同：

```json
{
  "sourcefile": "07_星命七政四余/标点组/乾元秘旨.txt",
  "chunk_id": 1,
  "chunk_text": "《楚词》言：阛则九重，孰营度之？\n……",
  "meta": {
    "book": "乾元秘旨",
    "category": "07_星命七政四余",
    "volume": "",
    "group": "",
    "chapter": "正文",
    "section_titles": ["正文"],
    "section_path": ["正文"],
    "section_id": "S0000",
    "line_start": 2,
    "line_end": 4,
    "chunk_index": 1,
    "chunk_total": 6,
    "char_count": 477,
    "chunk_type": "body",
    "has_punctuation": true,
    "chunk_uid": "07_星命七政四余/乾元秘旨/S0000/C0001",
    "text_for_embedding": "《乾元秘旨》 · 正文\n《楚词》言：……"
  }
}
```

必须成立的不变量：

1. **一行 = 一个 chunk = 一条 meta**。meta 内嵌在 chunk 行里，不再另存扁平 meta 文件，结构上保证 1:1。
2. `chunk_id` 在**单个文件内**从 1 连续到 N；两个文件之间可以重复。合并两套语料时，用 `chunk_uid` 做主键。
3. `chunk_uid` 全局唯一。
4. `char_count == len(chunk_text)`；`line_start <= line_end`。
5. 同一个 `chunk_uid` 前缀（`category/book/section_id`）内，`chunk_index` 从 1 连续到 `chunk_total`。
6. `chunk_text` 用于展示、引用和 BM25；`text_for_embedding` 只用于 BGE-M3 编码，不要展示给用户。
7. `volume` / `chapter` 允许为空。标点组有 1,558 / 2,830 条没有卷次；无标点组 5,851 条全部为空，这是设计选择，不是解析失败。

校验命令：

```bash
python -S src/validate_chunks.py
```

---

## 重新生成

本机 anaconda 的 site-packages 已损坏，命令统一用 `python -S`；如果你在干净 venv 里运行，去掉 `-S` 即可。

```bash
# v1：标点组 16 部 → data/chunks/punct.jsonl
python -S src/chunk_punct.py

# v2：无标点组 29 部 → data/chunks/unpunct.jsonl
python -S src/chunk_unpunct.py

# 校验数据契约
python -S src/validate_chunks.py
```

两个脚本都从 `data/clean_text/` 只读输入，不修改源文件；输出先写 `.tmp` 再原子替换。

### 术语语料

`data/terminology/` 是从第三方包派生出来的，不需要每次重跑。若要重建：

```bash
mkdir -p /tmp/iztro && tar -xzf vendor/oss/iztro-2.6.2.tgz -C /tmp/iztro
node src/acquire/extract-iztro.js /tmp/iztro/package data/terminology
# lunar / bazi-terms / Sudo-Biao 同理，见 ATTRIBUTION.md
```

---

## v1 使用方式

- 应用只读 `data/chunks/punct.jsonl`，不要读 `data/clean_text/`，也不要把 `unpunct.jsonl` 混进来。
- Dense：对 `meta.text_for_embedding` 跑 BGE-M3，得到 2,830 × 1024。
- BM25：对 `chunk_text` 建索引；书名等字段单独作为过滤/加权项，不要把 `text_for_embedding` 的合成前缀重复喂给 BM25。
- 引用：展示 `chunk_text`，出处用 `meta.book` + `meta.chapter`（有 `volume` 才加卷次）。
- 评测问题只从这 16 部标点组书里出；不要拿《三命通会》《星学大成》出题，它们在 v2 才入库。

---

## 已知限制

- **卷次缺失**：标点组 55% 的 chunk 没有 `volume`。引用口径建议定为“《书名·章名》”，卷次有则加、无则标“卷次不详”。
- **无标点组没有结构**：`volume` / `chapter` 全为空，引用只能到书名 + 行号区间。
- **无标点组未做断句**：当前只按刻本行款合并段落。BGE-M3 不要求标点，能编码，但长段无标点可能稀释单向量；标点恢复放到 v2。
- **跨书重复**：`punct.jsonl` 有 1 组重复文本（《命理探源》引用《子平真诠评注》），属于正常互引，未去重。
- **只切了 45 部书**：152 部清洗文本中，16 部标点组 + 29 部无标点组已进入 chunk 产线，其余 107 部留给 v2 扩容。

---

## 旧路径迁移说明

如果你还记着旧结构，对应关系如下：

| 旧路径 | 新路径 |
|---|---|
| `data/chunks.jsonl`（2,753 条旧切分） | **已删除**，改用 `data/chunks/punct.jsonl`（2,830 条） |
| `data/chunks_punct_meta.jsonl` | `data/chunks/punct.jsonl` |
| `data/chunks_unpunct_meta.jsonl` | `data/chunks/unpunct.jsonl` |
| `data/chunk_meta_07_08.jsonl` / `chunk_meta_unpunct.jsonl` | **已删除**，meta 内嵌在 chunk 行里 |
| `data/chunk_meta_*_report.json` | `data/chunks/punct_report.json` / `unpunct_report.json` |
| `data/03-terminology/` | `data/terminology/` |
| `data/category_stats/`、`corpus_info.csv` 等 | `data/stats/` |
| `02-oss-code/` | `vendor/oss/`（解压目录已删除，tgz 保留） |
| `src/extract-*.js`、`parse-bazi-terms.js`、`py_to_text.py`、`fetch-daizhige.js` | `src/acquire/` |
| `src/classify.py`、`clean.py`、`scan_corpus*.py`、`prepare-corpus.sh` | `src/legacy/` |
| `docs/问题清单.md` | `docs/eval_questions_seed.md` |

---

## 来源与许可

语料来源、版本、许可证和使用边界见 [`ATTRIBUTION.md`](ATTRIBUTION.md)。MIT 许可证要求保留版权与许可声明；若再分发派生文本，请一并保留该文件。
