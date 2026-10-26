import json
import os
from pathlib import Path
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
# 默认用仓库自带的 data/，部署到别的目录时用 MINGLI_DATA_DIR 覆盖。
# 之前这里硬编码 /workspace，本地克隆下来直接跑会 FileNotFoundError。
DATA_DIR = Path(os.environ.get("MINGLI_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
data_chunk = str(DATA_DIR / "chunks" / "punct.jsonl")
data_emb = str(DATA_DIR / "embeddings.npy")
rrf_k=60
top_k=5
candidate_k=20  # 融合前每路先取这么多，再截 top_k
def tokenize(text):
    # 中文用字二元组：比单字更有区分度，也不需要 jieba 词典。
    # v1.1 再换 jieba + data/terminology 自定义词典。
    s="".join(ch for ch in text if not ch.isspace())
    if len(s)<2:
        return list(s)
    return [s[i:i+2] for i in range(len(s)-1)]
def load_chunks(path):
    chunks=[]
    texts_bm25=[]
    with open(path,"r",encoding="utf-8") as f:
        for line in f:
            obj=json.loads(line)
            chunks.append(obj)
            texts_bm25.append(tokenize(obj["chunk_text"]))
        return chunks, texts_bm25
chunks,tokenized_corpus=load_chunks(data_chunk)
embeds=np.load(data_emb).astype(np.float32)
print(f"chunks:{len(chunks)}|embeds shape:{embeds.shape}")
assert len(chunks)==embeds.shape[0]
# 统一归一化，保证 embeds @ q_emb 就是余弦相似度（不依赖 embedding 脚本是否归一化过）
norms=np.linalg.norm(embeds,axis=1,keepdims=True)
norms[norms==0]=1.0
embeds=embeds/norms
bm25=BM25Okapi(tokenized_corpus)
model=SentenceTransformer("BAAI/bge-m3")
def dense_search(query,topk=top_k):
    q_emb=model.encode(query,normalize_embeddings=True)
    sims=embeds@q_emb
    indices=np.argsort(sims)[::-1][:topk]
    res=[{"idx":i,"scores":float(sims[i] )} for i in indices]
    return res
def bm25_search(query,topk=top_k):
    q_tokens=tokenize(query)
    scores=bm25.get_scores(q_tokens)
    indices=np.argsort(scores)[::-1][:topk]
    res=[{"idx":i, "scores":float(scores[i])} for i in indices]
    return res
def rrf_fuse(dense_list,bm25_list,k=rrf_k,topk=top_k):
    rrf_dict={}
    for rank,item in enumerate(dense_list,start=1):
        idx=item["idx"]
        rrf_dict[idx]=rrf_dict.get(idx,0.0)+1.0/(rank+k)
    for rank,item in enumerate(bm25_list,start=1):
        idx=item["idx"]
        rrf_dict[idx]=rrf_dict.get(idx,0.0)+1.0/(rank+k)
    sorted_idx=sorted(rrf_dict.items(),key=lambda x:x[1], reverse=True)
    out=[{"idx":i,"scores":s} for i,s in sorted_idx[:topk]]
    return out
def retrieve_one(query,top_k=5,mode="rrf"):
    cand=max(top_k,candidate_k)
    d_res=dense_search(query,cand)
    b_res=bm25_search(query,cand)
    fused=rrf_fuse(d_res,b_res,topk=top_k)
    if mode=="dense":
        raw_list=d_res
    elif mode=="bm25":
        raw_list=b_res
    elif mode=="rrf":
        raw_list=fused
    else:
        raise ValueError("mode 只能是dense、bm25、rrf中的一种")
    final=[]
    for item in raw_list[:top_k]:
        c=chunks[item["idx"]]
        final.append({
            "query":query,
            # idx 是语料行号（0 起），chunk_id 才是评测和引用用的 1 起编号
            "chunk_id":c["chunk_id"],
            "chunk_idx":item["idx"],
            "rrf_score":item["scores"],
            "text":c["chunk_text"],
            "meta":c["meta"]
        })
    return final

if __name__=="__main__":
    test_query=[
        "什么叫禄命",
        "什么叫天乙贵人",
        "什么是夹禄",
        "兰台妙选讲了什么",
        "西人所说的九重天，自最上至最下依次是哪几重？哪一重没有星辰、每日带动各重天自东而西左旋？恒星以下的八重天为什么既随宗动天左旋，又各有右旋之度？",
"十二宫为什么以命宫第一、财帛第二、兄弟第三、田宅第四？命、禄、福、妻、田宅、子孙、奴仆、财帛、兄弟、相貌、疾厄、迁移各宫分别管多少年？",
"星命学以经、络、贯、串、填、冲、守、钓、拱、夹、拦截论星曜与命度的关系，这些术语各指什么？钓与拱、夹与拦截有何区别？",
"星命十二宫中哪些属于强宫、哪些属于弱宫？为什么财帛被称为次弱、迁移被称为近强？",
"七政四余各曜一日行多少度、约多少年一周天？其中哪两曜顺行宫而逆行度？",
"纳音五行怎样由干支推算？子午数至庚、丑未数至辛，得七为金、三为火、九为木、一为土、五为水，请以甲子、丙寅、戊辰、庚午、丙子为例说明。",
"马化龙驹奔凤阙、蛇化青龙入天池、宝剑冲于牛斗这三种取象，分别对应哪些地支和干支组合？各格成立需要什么条件？",
"判断身强有哪三个条件？最强、中强、次强分别需要具备什么？",
"六十花甲子纳音的名称如何得来？请解释海中金、炉中火、大林木、路旁土、剑锋金五种命名的依据。",
"取用神为什么专求月令？扶抑、病药、调候、专旺、通关五种取用法各自的思路是什么？",
"命理中“以干为禄、以支为命”应如何理解？“一辰十载”“三日为年”的行运推算法又是什么意思？",
"命理以财为父、印为母，男命以财为妻、正官为子，这种六亲取象如何推断父母、妻子、子女的吉凶？",
"命书所说的四柱、三元、九命分别指什么？它与后世子平以年月日时为四柱、以日干为主的做法有何不同？",
"太岁有日犯岁君、征太岁、晦太岁三种情况，它们如何界定、各主什么吉凶？什么情况下算有救？",
"五行旺相休囚为什么要按气机进退判断，而不看长生、死绝？将来者进、进而当令、功成者退、退而无气分别对应什么？",
"“有病方为贵，无伤不是奇”与“到底中和，乃为至贵”是否矛盾？如何用去病与中和把二者统一起来？",
"“四阳俱立，定知难有阴尊；阴覆全逢，不是阳尊老寿”是什么意思？“卦逢生气，天德合世，世长年；身命逢刑，反克而必须夭贱”的推断逻辑是什么？",
"命理中的“从无而立有”与“见不见之形”各指什么？请各举一例。",
"病药说中的病与药指什么？雕、枯、旺、弱四病与损、益、生、长四药分别是什么？",
"正月、二月甲木的取用有什么不同？“寒木向阳”“阳刃驾杀”分别指什么组合？为什么说正二月甲木有庚戊者上命？"
    ]
    log_lines=[]
    for q in test_query:
        print(f"\n------Query:{q}")
        hits=retrieve_one(q)
        for h in hits:
            line = f"{q}\t{h['chunk_idx']}\t{h['rrf_score']:.4f}\t{h['text'][:80]}"
            print(line)
            log_lines.append(line)
    # 保存日志
    with open("data\retrieval_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
    print("\n✅全部检索日志已经保存至 data/retrieval_log.txt")
