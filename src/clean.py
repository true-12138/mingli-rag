from pathlib import Path
import json
import csv
import re
base=Path("/workspace")
input_root=base/"corpus-derived"/"corpus"
output_root=base/"data"/"clean_text"
char_map_path=base/"src"/"assets"/"char_map.json"
noise_path=base/"src"/"assets"/"noise_keywords.txt"
log_path=base/"data"/"clean_log.csv"
with open(char_map_path,"r",encoding="utf-8") as f:
    char_map=json.load(f)
noise_keys=[]
if noise_path.exists():
    with open (noise_path,"r",encoding="utf-8") as f:
        noise_keys=[ln.strip() for ln in f if ln.strip()]
ctrl_pat=re.compile(r"[\x00-\x09\x0b-\x1f]")
multi_newline=re.compile(r"\n{2,}")
def clean_single_text(raw_text:str):
    orig_chars=len(raw_text)
    txt=raw_text.replace("\r\n","\n")
    txt=ctrl_pat.sub("",txt)
    for old_c, new_c in char_map.items():
        txt=txt.replace(old_c,new_c)
    lines_in=txt.split("\n")
    lines_out=[]
    drop_lines=0
    for line in lines_in:
        ln_stripped=line.strip()
        if any(k in ln_stripped for k in noise_keys):
            drop_lines+=1
            continue
        lines_out.append(line)
    txt="\n".join(lines_out)
    txt=multi_newline.sub("\n",txt)
    clean_chars=len(txt)
    return txt,orig_chars, clean_chars,drop_lines

def process_one_file(in_fp,out_fp):
    out_fp.parent.mkdir(parents=True,exist_ok=True)
    raw_text=in_fp.read_text(encoding="utf-8")
    cleaned,oc,cc,dl=clean_single_text(raw_text)
    out_fp.write_text(cleaned,encoding="utf-8")
    return oc,cc,dl

def run_all():
    output_root.mkdir(parents=True,exist_ok=True)
    log_rows=[]
    all_txt=list(input_root.rglob("*.txt"))
    print(f"一共找到{len(all_txt)}个待处理txt")
    for infile in all_txt:
        rel=infile.relative_to(input_root)
        outfile=output_root/rel
        oc,cc,dl=process_one_file(infile, outfile)
        print(f"{rel}|原始：{oc}|清洗：{cc}|删除行“{dl}")
        log_rows.append([str(rel),oc,cc,dl])
    with open(log_path,"w",encoding="utf-8") as f:
        w=csv.writer(f)
        w.writerow(["rel_path","origin_char","clean_char","dropped_lines"])
        w.writerows(log_rows)
if __name__=="__main__":
    run_all()

