#!/usr/bin/env bash
#
# 术数语料 → RAG 可用语料（历史脚本，不在 v1 关键路径上）。
#
#   ① 分类 / 排他 / 统计   → data/_meta/（books.json, exclude.txt, corpus-stats.tsv …）
#   ② 生成干净副本         → $OUT/corpus/<体系>/<书名>.txt（去页眉、异体字归一）
#   ③ 术语语料规范化       → $OUT/terminology/*.jsonl（加 system 字段，跳过 txt 视图）
#
# 注意：本脚本依赖 01-classics/术数 与 01-classics/术数-manifest.json；
#       这两个路径在语料仓库中默认被 .gitignore 忽略，需自备原始语料。
#
# 用法：
#   bash src/legacy/prepare-corpus.sh --out ~/workspace/corpus-derived
#   bash src/legacy/prepare-corpus.sh --dry-run           # 只看统计，不写语料
#   PYTHON='python -S' bash src/legacy/prepare-corpus.sh  # anaconda site 损坏时
#   --keep-header  保留殆知阁 3 行页眉　--no-norm  不做异体字归一
#
# 原则：01-classics/ 只读；输出一律写 $OUT。
set -euo pipefail

PYTHON="${PYTHON:-python3}"
SKIP_HEADER=1; NORM=1; DRY=0; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out)         OUT="$2"; shift 2 ;;
    --out=*)       OUT="${1#*=}"; shift ;;
    --dry-run)     DRY=1; shift ;;
    --keep-header) SKIP_HEADER=0; shift ;;
    --no-norm)     NORM=0; shift ;;
    -h|--help)     sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLASSICS="$REPO/01-classics/术数"
META="$REPO/data/_meta"
[ -n "$OUT" ] || OUT="$(cd "$REPO/.." && pwd)/corpus-derived"
export PYTHONIOENCODING=utf-8

if [ -t 1 ]; then
  say() { printf '\033[1m%s\033[0m\n' "$*"; }
else
  say() { printf '%s\n' "$*"; }
fi
die() { printf '%s\n' "$*" >&2; exit 1; }

# ── 0. 环境自检 ────────────────────────────────────────────────────────────
$PYTHON --version >/dev/null 2>&1 || die "找不到 $PYTHON，请先装 python3（或用 PYTHON=... 指定）"
[ -d "$CLASSICS" ] || die "语料目录不存在：$CLASSICS"
n=$(find "$CLASSICS" -maxdepth 1 -name '*.txt' | wc -l | tr -d ' ')
[ "$n" = 155 ] || die "01-classics/术数 应有 155 部 txt，实际 $n"
case "$OUT" in "$REPO"/01-classics*) die "输出目录不能写进 01-classics/" ;; esac
say "仓库 $REPO"
say "输出 $OUT$([ "$DRY" = 1 ] && echo '   (dry-run)')"

# ── ① 分类 / 排他 / 统计 ───────────────────────────────────────────────────
say ""
say "① 分类与统计 → data/_meta/"
$PYTHON "$REPO/src/legacy/classify.py" --repo "$REPO"
if [ "$DRY" = 1 ]; then say ""; say "（dry-run：未生成语料副本）"; exit 0; fi

# ── ② 干净副本 ─────────────────────────────────────────────────────────────
say ""
say "② 生成干净副本 → $OUT/corpus/<体系>/"
rm -rf "$OUT/corpus" "$OUT/terminology"
mkdir -p "$OUT/corpus" "$OUT/terminology"

# 异体字归一：实测在该语料中出现过的（巻66 塟77 敎46 髪201 竝30 昬19 査2 畱20 旣87 皃11 頼73 廼2 剏3 暦3 冩3）
SED=()
if [ "$NORM" = 1 ]; then
  for p in 巻:卷 塟:葬 敎:教 髪:发 竝:并 昬:昏 査:查 畱:留 旣:既 皃:貌 頼:赖 廼:乃 剏:创 暦:历 冩:写; do
    SED+=(-e "s/${p%%:*}/${p##*:}/g")
  done
fi

total=0; used=0
while IFS=$'\t' read -r title school use; do
  use="${use%$'\r'}"                      # 容忍 CRLF
  total=$((total + 1))
  [ "$use" = 1 ] || continue
  mkdir -p "$OUT/corpus/$school"
  dst="$OUT/corpus/$school/$title.txt"
  if [ "$SKIP_HEADER" = 1 ]; then src_cmd=(tail -n +4); else src_cmd=(cat); fi
  "${src_cmd[@]}" "$CLASSICS/$title.txt" \
    | { if [ "${#SED[@]}" -gt 0 ]; then sed "${SED[@]}"; else cat; fi; } > "$dst"
  used=$((used + 1))
done < "$META/books.tsv"

got=$(find "$OUT/corpus" -name '*.txt' | wc -l | tr -d ' ')
[ "$got" = "$used" ] || die "副本数不符：期望 $used，实际 $got"
echo "  $used/$total 部 → $got 个文件，$(du -sh "$OUT/corpus" | cut -f1)"
echo "  体系分目录 $(find "$OUT/corpus" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ') 个"
echo "  异体字归一 $([ "$NORM" = 1 ] && echo 开 || echo 关)　页眉剥离 $([ "$SKIP_HEADER" = 1 ] && echo 开 || echo 关)"

# 抽查：确认页眉已剥、归一已生效
if [ "$SKIP_HEADER" = 1 ]; then
  first=$(find "$OUT/corpus" -name '*.txt' | head -1)
  head -1 "$first" | grep -q '^#' && die "页眉未剥离：$first" || true
fi

# ── ③ 术语语料：只走 jsonl，加 system 字段 ─────────────────────────────────
say ""
say "③ 术语语料规范化 → $OUT/terminology/"
$PYTHON - "$REPO" "$OUT" <<'PY'
import json, os, sys
repo, out = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(repo, "src", "legacy"))
import classify as C

SRC = os.path.join(repo, "data", "terminology")
JOBS = [
    # 相对路径,                group 字段,   固定 system,      备注
    ("bazi-terms.jsonl", "category", "八字/命理", "英文释义，中文 RAG 建议剔除或重写"),
    ("iztro-terms.jsonl", "category", "紫微斗数", None),
    ("lunar-terms.jsonl", "category", "历法/黄历", None),
    ("sudo-biao/sudo-biao-terms.jsonl", "group", None, None),
]
for rel, gk, fixed, review in JOBS:
    src = os.path.join(SRC, rel)
    dst = os.path.join(out, "terminology", os.path.basename(rel))
    n = 0
    with open(src, encoding="utf-8") as fi, \
         open(dst, "w", encoding="utf-8", newline="\n") as fo:
        for line in fi:
            if not line.strip():
                continue
            d = json.loads(line)
            d["system"] = fixed or C.system_of(d.get(gk, ""))
            d["source_file"] = rel
            # 程序常量 / 现代讲义：引用时不得当古籍原文
            d["is_primary_source"] = False
            if rel.startswith("sudo-biao"):
                d["source_module"] = d.pop("source", None)
            if review:
                d["needs_review"] = review
            fo.write(json.dumps(d, ensure_ascii=False) + "\n")
            n += 1
    print("  %-22s%6d 条   system=%s" % (
        os.path.basename(rel), n, ("固定 " + fixed) if fixed else "按 group"))
PY
echo "  跳过：所有 *-*.txt 分组视图与 sudo-biao/_全部合并.txt（与 jsonl 逐字重复，已实测）"

# ── ④ 摘要 ─────────────────────────────────────────────────────────────────
say ""
say "④ 产物"
( cd "$OUT" && find . -maxdepth 2 -type d | sort | sed 's/^/  /' )
printf '  %s\n' "$(find "$OUT" -type f | wc -l | tr -d ' ') 个文件，$(du -sh "$OUT" | cut -f1)"
say ""
say "下一步（第 2 周）：切 $OUT/corpus/ 下的 txt；metadata 直接取 data/_meta/books.json 的"
say "  school / domain / dup_group / needs_despacing 四个字段。"
