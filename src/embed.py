# -*- coding: utf-8 -*-
"""离线编码：把 src/corpus.py 定义的整份语料编码成 data/embeddings.npy。

语料顺序由 src/corpus.py 决定（标点组在前、无标点组在后），
retrieval.py 用同一个 loader，两边顺序天然一致。

用法::

    python src/embed.py                        # 默认 BAAI/bge-m3
    python src/embed.py --model /mnt/d/bge-m3  # 用本地权重，避免联网下载
"""
import argparse
import os
import pickle
import sys
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus

DEFAULT_MODEL = os.environ.get("MINGLI_MODEL_DIR", "BAAI/bge-m3")
BATCH_SIZE = 64


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL, help="模型名或本地权重目录")
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = ap.parse_args()

    dd = corpus.data_dir()
    rows = corpus.load_chunks(dd)
    texts = [r["meta"]["text_for_embedding"] for r in rows]
    n = len(texts)
    print(f"语料 {n} 条，模型 {args.model}")

    out_npy = dd / "embeddings.npy"
    if out_npy.exists():
        old = np.load(out_npy, mmap_mode="r")
        print(f"已有 {out_npy.name}：shape={old.shape}，将被覆盖")

    model = SentenceTransformer(args.model)
    vectors = []
    for start in range(0, n, args.batch_size):
        batch = texts[start:start + args.batch_size]
        vecs = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
        vectors.append(vecs)
        print(f"{start + 1}~{min(start + args.batch_size, n)} / {n}")

    emb = np.concatenate(vectors, axis=0).astype(np.float32)
    if emb.shape[0] != n:
        raise SystemExit(f"编码条数 {emb.shape[0]} 与语料 {n} 不一致")

    np.save(out_npy, emb)
    with open(dd / "all_records.pkl", "wb") as f:
        pickle.dump(rows, f)

    print(f"输出 {out_npy}  shape={emb.shape}  {emb.nbytes / 1e6:.1f} MB")
    print(f"输出 {dd / 'all_records.pkl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
