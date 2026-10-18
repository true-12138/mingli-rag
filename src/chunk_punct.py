import os
import re
import json
from pathlib import Path

target_chunk_len = 500
overlap_len = 100
BUF_READ = 65536
META_LOOKAHEAD = 128   # 专门用来粘被切断meta标记的小缓冲区，很小

# 正文分句
sentence_pat = re.compile(r'(。|；|？)')
# meta标记正则：@@META|k1=v1;k2=v2@@
meta_pat = re.compile(r'@@META\|([^@]+)@@')

input_root = Path("data/clean_text")
output_path = Path("data/chunks_punct_meta.jsonl")
scan_dir = ["07_星命七政四余","08_八字禄命"]

def parse_meta_str(s:str):
    """把 vol=卷二;title=xxx 转成 dict；容错"""
    d = {}
    for part in s.split(";"):
        if "=" in part:
            k, v = part.split("=",1)
            d[k.strip()] = v.strip()
    return d

def feed_buffer(buf: str):
    parts = sentence_pat.split(buf)
    tail = ""
    if len(parts)>=2 and (parts[-1] not in ("。","；","？")):
        tail = parts.pop()
    sents = []
    for i in range(0, len(parts)-1, 2):
        s = (parts[i].strip() + parts[i+1]).strip()
        if s:
            sents.append(s)
    return sents, tail

def chunk_by_sentences(sents, cur_buffer):
    new_chunks = []
    for s in sents:
        if len("".join(cur_buffer)) + len(s) > target_chunk_len and cur_buffer:
            full = "".join(cur_buffer)
            new_chunks.append(full)
            # overlap：安全保护，不要取负数
            take = min(overlap_len, len(full))
            cur_buffer = [full[-take:]]
        cur_buffer.append(s)
    return new_chunks, cur_buffer

def process_one_file(fpath: Path, fw):
    print(f"▶开始 {fpath.name}")
    rel_path = str(fpath.relative_to(input_root))

    tail_str = ""             # 正文残留（原有）
    meta_detect_tail = ""      # NEW：专门粘可能截断meta标记
    cur_sent_buf = []
    chunk_counter = 0
    current_meta = {"vol": None, "chapter": None, "title": None} # NEW 当前生效meta

    with open(fpath,"r",encoding="utf-8",errors="ignore") as f:
        while True:
            chunk_raw = f.read(BUF_READ)
            if not chunk_raw:
                break
            work_text = meta_detect_tail + chunk_raw
            matched_meta = []
            last_pos = 0
            # 扫描全部meta标记
            for m in meta_pat.finditer(work_text):
                matched_meta.append(m.group(1))
                text_segment = work_text[last_pos:m.start()]
                tail_str += text_segment
                last_pos = m.end()
            # 剩下没处理的：判断末尾是否有可能是标记的一部分
            remaining = work_text[last_pos:]
            # 简单策略：末尾最多保留 META_LOOKAHEAD 字节当作待检测尾巴
            if len(remaining) > META_LOOKAHEAD:
                tail_str += remaining[:-META_LOOKAHEAD]
                meta_detect_tail = remaining[-META_LOOKAHEAD:]
            else:
                meta_detect_tail = remaining

            # 所有抓到meta全部更新 current_meta
            for meta_content in matched_meta:
                parsed = parse_meta_str(meta_content)
                current_meta.update(parsed)

            # --- 原来整套正文切分流水线完全不变！只喂 tail_str ---
            sents, tail_str = feed_buffer(tail_str)
            ck_list, cur_sent_buf = chunk_by_sentences(sents, cur_sent_buf)
            for ck in ck_list:
                rec = {
                    "sourcefile": rel_path,
                    "chunk_id": chunk_counter,
                    "chunk_text": ck,
                    "meta": current_meta.copy()   # ⭐这里是关键！copy防止dict引用坑
                }
                fw.write(json.dumps(rec, ensure_ascii=False)+"\n")
                chunk_counter +=1

        # 文件读完：把最后的 meta_detect_tail 全部当成正文（已经不可能有跨buffer标记了）
        tail_str += meta_detect_tail
        rest_txt = "".join(cur_sent_buf) + tail_str
        if rest_txt.strip():
            rec = {
                "sourcefile": rel_path,
                "chunk_id": chunk_counter,
                "chunk_text": rest_txt.strip(),
                "meta": current_meta.copy()
            }
            fw.write(json.dumps(rec, ensure_ascii=False)+"\n")
    print(f"✅{fpath.name} 完成")

def main():
    print("===带meta标记流式切分启动===")
    total_files = 0
    with open(output_path,"w",encoding="utf-8") as fw:
        for dn in scan_dir:
            dp = input_root / dn / "标点组"
            if not dp.exists():
                print(f"目录不存在：{dn}")
                continue
            all_txt = list(dp.glob("*.txt"))
            print(f"发现 {len(all_txt)} 个txt")
            for fp in all_txt:
                process_one_file(fp, fw)
                total_files +=1
    print(f"\n🎉全部结束，处理文件数：{total_files}")

if __name__=="__main__":
    main()