import json
import numpy as np
import pickle
from sentence_transformers import SentenceTransformer

input_path = "/workspace/data/chunks/punct.jsonl"
output_npy = "/workspace/data/embeddings.npy"
batch_size = 64
model_id = "BAAI/bge-m3"

model = SentenceTransformer(model_id)

rows = []
texts_for_embed = []

with open(input_path, "r", encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line.strip())
        rows.append(rec)
        texts_for_embed.append(rec["meta"]["text_for_embedding"])

N = len(texts_for_embed)
print(f"一共有 {N} 条记录")

embed_list = []
for start in range(0, N, batch_size):
    end = start + batch_size
    batch = texts_for_embed[start:end]
    batch_vecs = model.encode(
        batch,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    embed_list.append(batch_vecs)
    print(f"{start + 1}~{min(end, N)} done")

emb_batch = np.concatenate(embed_list, axis=0)
np.save(output_npy, emb_batch)
print(f"输出 shape={emb_batch.shape}")

with open("/workspace/data/all_records.pkl", "wb") as f:
    pickle.dump(rows, f)

print("已经保存 pkl")