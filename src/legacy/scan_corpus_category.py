"""历史脚本：按门类统计 corpus-derived/corpus 的文本质量。默认路径为旧 /workspace 布局。"""
from pathlib import Path
from dataclasses import dataclass
import csv

@dataclass
class BookStat:
    filename: str
    category: str
    lines: int
    total_char: int
    pure_text_chars: int
    punc_cnt: int
    punc_ratio: float

corpus_root = Path("/workspace/corpus-derived/corpus")
out_root = Path("/workspace/data/category_stats")
out_root.mkdir(exist_ok=True)  # 新建文件夹，存放每个门类独立csv

# 标点集合
punctuation = set("，。！？；：“”‘’（）【】《》、[]()")

def count_text_info(file_path: Path):
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    line_count = len(lines)
    full_text = "".join(lines)
    total_char = len(full_text)

    pure = 0
    punc = 0
    for c in full_text:
        if c in punctuation:
            punc += 1
        elif not c.isspace():
            pure +=1
    ratio = punc / total_char if total_char >0 else 0
    return line_count, total_char, pure, punc, ratio

all_stats = []
# 遍历一级门类文件夹
category_dirs = [d for d in corpus_root.iterdir() if d.is_dir()]

for cat_dir in category_dirs:
    category = cat_dir.name
    txt_files = list(cat_dir.rglob("*.txt"))
    print(f"\n==== 处理门类【{category}】，文件数量：{len(txt_files)} ====")
    cat_stats = []

    for fp in txt_files:
        fname = fp.name
        l_cnt, t_char, pure_char, p_cnt, p_ratio = count_text_info(fp)
        stat = BookStat(
            filename=fname,
            category=category,
            lines=l_cnt,
            total_char=t_char,
            pure_text_chars=pure_char,
            punc_cnt=p_cnt,
            punc_ratio=p_ratio
        )
        cat_stats.append(stat)
        all_stats.append(stat)
        print(f"  {fname} | punc_ratio:{p_ratio:.4f}")

    # 单独写入当前门类的csv
    cat_csv = out_root / f"{category}.csv"
    with open(cat_csv, "w", encoding="utf-8-sig", newline="") as csvf:
        writer = csv.writer(csvf)
        writer.writerow(["filename","category","lines","total_char","pure_text_chars","punc_cnt","punc_ratio"])
        for s in cat_stats:
            writer.writerow([s.filename, s.category, s.lines, s.total_char, s.pure_text_chars, s.punc_cnt, s.punc_ratio])
    print(f"✅ {category} 的统计结果保存至：{cat_csv}")

# 写入全局汇总总表
total_csv = Path("/workspace/data/corpus-derived-total-stats.csv")
with open(total_csv, "w", encoding="utf-8-sig", newline="") as csvf:
    writer = csv.writer(csvf)
    writer.writerow(["filename","category","lines","total_char","pure_text_chars","punc_cnt","punc_ratio"])
    for s in all_stats:
        writer.writerow([s.filename, s.category, s.lines, s.total_char, s.pure_text_chars, s.punc_cnt, s.punc_ratio])
print(f"\n✅ 全局汇总表保存至：{total_csv}")
print(f"\n全部处理完成！每个门类独立csv放在 /workspace/data/category_stats/")