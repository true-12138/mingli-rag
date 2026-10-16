from pathlib import Path
import string
import pandas as pd
from dataclasses import dataclass
corpus_root=Path('/workspace/01-classics')
outpu_csv=Path('/workspace/data/corpus_info.csv')
punctuation=set(string.punctuation+'，。、；：？“”‘’《》（）【】『』「」〔〕〖〗〈〉〔〕〖〗〈〉....——')
@dataclass
class Bookstat:
    filename: str
    lines: int
    total_char:int
    punc_cnt:int
    punc_ratio:float

def count_char(text:str):
    pure=0
    punc=0
    for i in text:
        if i in punctuation:
            punc+=1
        elif "\u4e00"<=i<="\u9fa5":
            pure+=1
    return pure,punc
def scan_one_file(filepath:Path):
    with open(filepath,'r',encoding='utf-8') as f:
        lines=f.readlines()
    raw_text=''.join(lines)
    total_chars=len(raw_text.strip())
    pure_text_chars,punc_cnt=count_char(raw_text)
    punc_ratio=punc_cnt/total_chars
    return Bookstat(filepath.name,len(lines),total_chars,punc_cnt,round(punc_ratio,4))
def main():
    stat_list=[]
    txt_files=list(corpus_root.rglob("*.txt"))
    print(f"一共找到{len(txt_files)}")
    for fp in txt_files:
        print(f'正在处理{fp.name}')
        res=scan_one_file(fp)
        stat_list.append(res)
    df=pd.DataFrame(s.__dict__ for s in stat_list)
    df.to_csv(outpu_csv,index=False,encoding='utf-8')
    print(f"结果已保存到{outpu_csv}")
if __name__=='__main__':
    main()