import os
import sys
import threading
from pathlib import Path
import numpy as np
from rank_bm25 import BM25Okapi

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus

# 语料顺序与编号由 src/corpus.py 统一决定（标点组在前、无标点组顺延），
# 和 src/embed.py 用的是同一个 loader，不会出现两边顺序不一致。
# 部署到别的目录时用 MINGLI_DATA_DIR 覆盖；用本地权重时设 MINGLI_MODEL_DIR。
DATA_DIR = corpus.data_dir()
data_emb = str(DATA_DIR / "embeddings.npy")
MODEL_ID = os.environ.get("MINGLI_MODEL_DIR", "BAAI/bge-m3")
# RRF 参数是在 8,681 条语料上重新扫出来的（见 eval/tune_rrf.py 与 eval/baselines.md）。
# 原来 k=60 / candidate_k=20 是 2,830 条时调的，候选池扩大三倍后融合变得太钝：
# 第 1 名和第 20 名的分差只有 1/61 : 1/80 ≈ 1.3 倍，等于没区分。
rrf_k=10
top_k=5
candidate_k=40  # 融合前每路先取这么多，再截 top_k
# 两路等权。试过把 BM25 降到 0.7：单跳释义题涨 1 道、应用推理题掉 1 道，
# 总 recall 不变却多了一个需要调的旋钮，20 道题的量样本上不划算。
w_dense=1.0
w_bm25=1.0
import retrieval_utils

# BM25 分词器：默认字二元组（v1 口径），设 MINGLI_BM25_TOKENIZER=jieba
# 换成 jieba + data/terminology 里的 324 条术语词典。
# 换分词器会改变所有检索结果，评测必须整轮重跑，不能和旧数字混着比。
TOKENIZER = os.environ.get("MINGLI_BM25_TOKENIZER", "bigram")
tokenize = retrieval_utils.make_tokenizer(TOKENIZER, DATA_DIR / "terminology")

# 重排：MINGLI_RERANK=1 时对候选池再打一次分。默认关闭——
# 单次向量扫描 8,681 条约 1.6ms，耗时在 embedding 和 LLM 上，重排只在
# 「融合把单路强命中挤出 Top-5」这类问题上才值得开。
RERANK = os.environ.get("MINGLI_RERANK", "0").strip().lower() not in ("", "0", "false", "no", "off")
RERANK_MODEL_ID = os.environ.get("MINGLI_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
# 重排能看到多少条候选。默认=候选池 40；调大能捞回「融合排名 41–100 的 gold」，
# 代价是 CrossEncoder 要打更多对。评测用 MINGLI_RERANK_POOL 扫一下再定。
try:
    RERANK_POOL = max(candidate_k, int(os.environ.get("MINGLI_RERANK_POOL", candidate_k)))
except ValueError:
    RERANK_POOL = candidate_k
reranker = retrieval_utils.LazyReranker(RERANK_MODEL_ID)
chunks=corpus.load_chunks(DATA_DIR)
tokenized_corpus=[tokenize(c["chunk_text"]) for c in chunks]
embeds=np.load(data_emb).astype(np.float32)
# 必须写 stderr：MCP 的 stdio 通道把 stdout 当作 JSON-RPC 帧，任何调试输出
# 混进 stdout 都会让客户端报 "Failed to parse JSONRPC message"。
print(f"chunks:{len(chunks)}|embeds shape:{embeds.shape}", file=sys.stderr)
# embeddings 是一段**前缀**时（索引还没覆盖新增语料）只检索已编码的部分，
# 否则直接报错。corpus.load_chunks 的顺序是标点组在前，所以前缀正好是 v1 的 16 部。
# 要让全部语料可检索：python src/embed.py
if embeds.shape[0] > len(chunks):
    raise SystemExit(
        f"embeddings 有 {embeds.shape[0]} 行，但语料只有 {len(chunks)} 条——"
        "语料文件被删过，必须重跑 python src/embed.py"
    )
if embeds.shape[0] < len(chunks):
    print(
        f"[warn] 索引只覆盖前 {embeds.shape[0]} 条语料（共 {len(chunks)} 条），"
        "本次只检索这部分；重跑 python src/embed.py 可覆盖全部。",
        file=sys.stderr,
    )
    chunks = chunks[: embeds.shape[0]]
    tokenized_corpus = tokenized_corpus[: embeds.shape[0]]
# 统一归一化，保证 embeds @ q_emb 就是余弦相似度（不依赖 embedding 脚本是否归一化过）
norms=np.linalg.norm(embeds,axis=1,keepdims=True)
norms[norms==0]=1.0
embeds=embeds/norms
bm25=BM25Okapi(tokenized_corpus)


class _LazyModel:
    """延迟到第一次检索才加载 BGE-M3。

    以前这里是模块导入时就 SentenceTransformer(MODEL_ID)：Streamlit 先把整个脚本
    跑完才渲染页面，于是首次打开（尤其 ModelScope 上的新环境还要下 2GB 权重）
    一直是一片白板，看起来像「前端没写」。改成懒加载后界面立刻出来，
    模型在第一次检索时才载入。

    调用方（tools.py / rag.py）用的是 model.encode，所以这里只要代理 encode 即可，
    其余属性透传给真实模型。
    """

    def __init__(self, model_id):
        self.model_id = model_id
        self._m = None
        # 并发首批请求会同时进 encode。没有锁的话每个线程都会 load 一次
        # BGE-M3，内存和启动时间都会乘上并发数。
        self._lock = threading.Lock()

    @property
    def loaded(self):
        return self._m is not None

    def _load(self):
        with self._lock:
            if self._m is not None:
                return self._m
            return self._load_locked()

    def _load_locked(self):
        # 大陆网络直连 huggingface 多数会失败。用户没显式配置时默认走镜像，
        # 想直连就把 HF_ENDPOINT 设成 https://huggingface.co。
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        try:
            import inspect
            from sentence_transformers import SentenceTransformer
            kwargs = {}
            # sentence-transformers 3.x 支持 model_kwargs。显式关掉 low_cpu_mem_usage，
            # 避免 accelerate 把权重留在 meta device，随后 .to() 报
            # "Cannot copy out of meta tensor; no data!"。
            if "model_kwargs" in inspect.signature(SentenceTransformer.__init__).parameters:
                kwargs["model_kwargs"] = {"low_cpu_mem_usage": False}
            self._m = SentenceTransformer(self.model_id, **kwargs)
        except Exception as exc:
            detail = str(exc)
            if "meta tensor" in detail:
                detail += (
                    "\n  依赖版本不匹配：按 requirements.txt 安装 "
                    "sentence-transformers==2.7.0 / transformers==4.37.2，"
                    "并清掉旧缓存后重试。")
            raise RuntimeError(
                "加载检索模型失败（{}）：{}\n"
                "  1) 大陆网络先设 HF_ENDPOINT=https://hf-mirror.com 再重试；\n"
                "  2) 或把权重放到本地，设 MINGLI_MODEL_DIR=/path/to/bge-m3".format(
                    self.model_id, detail)) from exc
        return self._m

    def encode(self, *args, **kwargs):
        return self._load().encode(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._load(), name)


# 配了 MINGLI_EMBED_URL 就把 query 编码交给独立服务；否则本地懒加载。
# 两条路径对调用方是同一个 `model.encode` 接口。
EMBED_URL = os.environ.get("MINGLI_EMBED_URL", "").strip()
if EMBED_URL:
    import embed_client
    model = embed_client.RemoteEmbedder(EMBED_URL)
    EMBED_BACKEND = "remote"
else:
    model = _LazyModel(MODEL_ID)
    EMBED_BACKEND = "local"

def dense_search(query,topk=top_k):
    q_emb=np.asarray(model.encode(query,normalize_embeddings=True),dtype=np.float32)
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
def rrf_fuse(dense_list,bm25_list,k=rrf_k,topk=top_k,w_d=w_dense,w_b=w_bm25):
    rrf_dict={}
    for rank,item in enumerate(dense_list,start=1):
        idx=item["idx"]
        rrf_dict[idx]=rrf_dict.get(idx,0.0)+w_d/(rank+k)
    for rank,item in enumerate(bm25_list,start=1):
        idx=item["idx"]
        rrf_dict[idx]=rrf_dict.get(idx,0.0)+w_b/(rank+k)
    sorted_idx=sorted(rrf_dict.items(),key=lambda x:x[1], reverse=True)
    out=[{"idx":i,"scores":s} for i,s in sorted_idx[:topk]]
    return out
def retrieve_one(query,top_k=5,mode="rrf"):
    cand=max(top_k,RERANK_POOL if RERANK else candidate_k)
    d_res=dense_search(query,cand)
    b_res=bm25_search(query,cand)
    if mode=="dense":
        raw_list=d_res
    elif mode=="bm25":
        raw_list=b_res
    elif mode=="rrf":
        # 要重排就先融合到候选池大小；只融合 top_k 的话没得选，重排等于空转
        raw_list=rrf_fuse(d_res,b_res,topk=cand if RERANK else top_k)
    else:
        raise ValueError("mode 只能是dense、bm25、rrf中的一种")
    if RERANK:
        raw_list=retrieval_utils.apply_rerank(
            query,
            raw_list,
            [c["chunk_text"] for c in chunks],
            top_k,
            reranker,
            on_error=lambda exc: print(
                "[warn] rerank 失败，保留融合顺序：{}".format(exc), file=sys.stderr),
        )
    final=[]
    for item in raw_list[:top_k]:
        c=chunks[item["idx"]]
        hit={
            "query":query,
            # idx 是语料行号（0 起），chunk_id 才是评测和引用用的 1 起编号
            "chunk_id":c["chunk_id"],
            "chunk_idx":item["idx"],
            "rrf_score":item["scores"],
            "text":c["chunk_text"],
            "meta":c["meta"]
        }
        if "rerank_score" in item:
            hit["rerank_score"]=item["rerank_score"]
        final.append(hit)
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
    with open(DATA_DIR / "retrieval_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
    print("\n✅全部检索日志已经保存至 data/retrieval_log.txt")
