# preproc_add_meta.py
from pathlib import Path
import re

# ===== 配置区 =====
INPUT_DIR = Path("data/clean_text")
OUTPUT_DIR = Path("data/clean_meta_tagged")
SCAN_DIRS = ["07_星命七政四余", "08_八字禄命"]

# regex 规则：可以后续不断迭代调优
re_vol = re.compile(r"【\s*卷\s*([一二三四五六七八九十\d]+)\s*】")
re_chapter = re.compile(r"^##\s*(.+)")
re_book = re.compile(r"【全书：(.+?)】")   # 如果你的文件开头放了【全书：兰台妙选】就可以用上

def meta_str(book: str, vol: str, chapter: str, typ: str):
    return f"@@META|book={book};vol={vol};chapter={chapter};type={typ}@@"

def process_one_txt(infile: Path, outfile: Path):
    lines = infile.read_text(encoding="utf-8").splitlines()
    active_book = infile.stem
    active_vol = ""
    active_chapter = ""
    out = []

    for ln in lines:
        strip_ln = ln.strip()
        if not strip_ln:
            out.append("")
            continue

        # 匹配【全书：xxx】
        m_book = re_book.match(strip_ln)
        if m_book:
            active_book = m_book.group(1)
            out.append(meta_str(active_book, active_vol, active_chapter, "unknown"))
            continue

        # 匹配【卷X】
        m_vol = re_vol.search(strip_ln)
        if m_vol:
            active_vol = m_vol.group(1)
            out.append(meta_str(active_book, active_vol, active_chapter, "unknown"))
            out.append(strip_ln)
            continue

        # 匹配行首 ## 标题
        m_chap = re_chapter.match(strip_ln)
        if m_chap:
            active_chapter = m_chap.group(1).strip()
            out.append(meta_str(active_book, active_vol, active_chapter, "unknown"))
            out.append(strip_ln)
            continue

        # 拿不准但很像标题，打上TODO标记事后人工扫
        if len(strip_ln) < 22 and ("论" in strip_ln or "歌" in strip_ln or "赋" in strip_ln):
            # 启发式：短 + 有论/歌/赋 → 疑似标题；不想自动乱标就TODO
            out.append(f"@@TODO::{strip_ln}@@")
            out.append(strip_ln)
            continue

        out.append(ln)

    out_text = "\n".join(out)
    outfile.write_text(out_text, encoding="utf-8")
    print(f"✅ {infile.name} → {outfile.name} | book={active_book}, vol={active_vol}, chapter={active_chapter[:12]}…")

def main():
    OUTPUT_DIR.mkdir(exist_ok=True, parents=True)
    for topdn in SCAN_DIRS:
        in_dp = INPUT_DIR / topdn / "标点组"
        out_dp = OUTPUT_DIR / topdn / "标点组"
        out_dp.mkdir(exist_ok=True, parents=True)
        if not in_dp.exists():
            print(f"跳过不存在：{in_dp}")
            continue
        all_txt = list(in_dp.glob("*.txt"))
        for fp in all_txt:
            ofp = out_dp / fp.name
            process_one_txt(fp, ofp)
    print("\n🎉预处理全部跑完；记得搜 @@TODO@@ 手工补一部分meta！")

if __name__ == "__main__":
    main()