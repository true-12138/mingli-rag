"""
knowledge/rag.py
================
BM25 + jieba Classical Text RAG Engine.

Replaces static prompt-injection with semantic retrieval:
every LLM call now gets the TOP-K most relevant classical
passages for the specific question, rather than fixed snippets.

Usage:
    from knowledge.rag import ClassicalRAG
    rag = ClassicalRAG()                        # auto-indexes on first call
    chunks = rag.search("日主强弱用神", top_k=5)
    context = rag.format_context(chunks)        # ready for LLM prompt
"""
from __future__ import annotations
import importlib, pkgutil
from typing import List, Dict, Tuple, Any, Optional

_rag_instance: Optional["ClassicalRAG"] = None


class ClassicalRAG:
    """
    Lightweight BM25-based RAG over the classical text knowledge base.
    Tokenises with jieba (Chinese word segmentation).
    Thread-safe read after build; build is done once at startup.
    """

    def __init__(self):
        self._corpus: List[Tuple[str, str]] = []   # [(doc_id, text), ...]
        self._bm25 = None
        self._built = False

    # ── Build index ──────────────────────────────────────────────────────────

    def build(self) -> None:
        """Harvest all knowledge modules and build the BM25 index."""
        import knowledge as _kb_pkg
        import jieba
        from rank_bm25 import BM25Okapi

        jieba.setLogLevel("ERROR")

        corpus: List[Tuple[str, str]] = []
        seen: set = set()

        def harvest(obj: Any, prefix: str, depth: int = 0) -> None:
            if depth > 5:
                return
            if isinstance(obj, str):
                text = obj.strip()
                if len(text) >= 20 and text not in seen:
                    seen.add(text)
                    corpus.append((prefix, text))
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    harvest(v, f"{prefix}.{k}", depth + 1)
            elif isinstance(obj, (list, tuple)):
                for i, v in enumerate(obj):
                    if isinstance(v, str):
                        harvest(v, f"{prefix}[{i}]", depth + 1)
                    else:
                        harvest(v, prefix, depth + 1)

        for info in pkgutil.iter_modules(_kb_pkg.__path__):
            if info.name in ("rag", "manager"):
                continue
            try:
                mod = importlib.import_module(f"knowledge.{info.name}")
                # Check for explicit chunk generator (e.g. get_all_deep_chunks)
                chunk_fn = getattr(mod, "get_all_deep_chunks", None)
                if callable(chunk_fn):
                    for chunk in chunk_fn():
                        text = chunk.get("content", "").strip()
                        if text and text not in seen:
                            seen.add(text)
                            corpus.append((chunk.get("source", info.name), text))
                # Also harvest raw module attributes
                for attr in dir(mod):
                    if attr.startswith("_"):
                        continue
                    val = getattr(mod, attr)
                    if isinstance(val, (str, dict, list)):
                        harvest(val, f"{info.name}.{attr}")
            except Exception:
                pass

        self._corpus = corpus
        tokenized = [list(jieba.cut(text)) for _, text in corpus]
        self._bm25 = BM25Okapi(tokenized)
        self._built = True

    def _ensure_built(self) -> None:
        if not self._built:
            self.build()

    # ── Search ───────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 6,
        min_score: float = 1.0,
        exclude_prefix: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return top_k most relevant classical text chunks for the query.

        Each result: { "id": str, "text": str, "score": float }
        """
        self._ensure_built()
        import jieba
        import numpy as np

        jieba.setLogLevel("ERROR")

        # ── Synonym expansion for classical metaphysics terms ──────────────
        _SYNONYMS: Dict[str, List[str]] = {
            "用神":    ["用神", "喜用", "取用", "忌神", "调候"],
            "格局":    ["格局", "格", "正格", "变格", "外格"],
            "日主":    ["日主", "日干", "日元", "我"],
            "四化":    ["四化", "飞化", "化禄", "化权", "化科", "化忌"],
            "飞星":    ["飞星", "紫白", "九星", "年飞星", "流年飞星"],
            "六爻":    ["六爻", "纳甲", "卜筮", "摇卦"],
            "用神取法":["用神", "取用", "用神取法", "用神喜忌"],
            "世爻":    ["世爻", "世", "世应"],
            "应爻":    ["应爻", "应", "世应"],
            "旺相":    ["旺相", "旺衰", "当令", "得令", "失令"],
            "空亡":    ["空亡", "旬空", "截空"],
            "大限":    ["大限", "小限", "大运", "流年", "运程"],
            "三方":    ["三方四正", "三合", "命迁财官"],
            "真太阳时":["真太阳时", "地方时", "经度修正"],
            "调候":    ["调候", "调候用神", "穷通宝鉴"],
            "伏吟":    ["伏吟", "反伏吟", "反吟"],
        }

        # Expand query terms
        expanded_queries = [query]
        query_lower = query
        for key, synonyms in _SYNONYMS.items():
            if key in query_lower:
                expanded_queries.append(" ".join(synonyms))

        # Multi-query BM25: take element-wise max across all query expansions
        scores = None
        for eq in expanded_queries[:3]:  # cap at 3 expansions
            tokens = [t for t in jieba.cut(eq) if len(t) > 1]
            if not tokens:
                tokens = list(jieba.cut(eq))
            eq_scores = self._bm25.get_scores(tokens)
            if scores is None:
                scores = eq_scores
            else:
                scores = np.maximum(scores, eq_scores)

        if scores is None:
            scores = [0.0] * len(self._corpus)

        # Build sorted results
        indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        results = []
        for idx, score in indexed:
            if score < min_score:
                break
            if len(results) >= top_k:
                break
            doc_id, text = self._corpus[idx]
            if exclude_prefix and any(doc_id.startswith(p) for p in exclude_prefix):
                continue
            results.append({"id": doc_id, "text": text, "score": round(float(score), 2)})

        return results

    def format_context(
        self,
        chunks: List[Dict[str, Any]],
        header: str = "【相关古籍知识】",
    ) -> str:
        """Format retrieved chunks into a prompt-ready string."""
        if not chunks:
            return ""
        lines = [header]
        for i, c in enumerate(chunks, 1):
            # Extract module/section name for attribution
            parts = c["id"].split(".")
            section = ".".join(parts[:2]) if len(parts) >= 2 else c["id"]
            lines.append(f"{i}. [{section}] {c['text']}")
        return "\n".join(lines)

    def search_and_format(
        self,
        query: str,
        top_k: int = 6,
        header: str = "【相关古籍知识】",
    ) -> str:
        """Convenience: search + format in one call."""
        chunks = self.search(query, top_k=top_k)
        return self.format_context(chunks, header=header)

    @property
    def corpus_size(self) -> int:
        self._ensure_built()
        return len(self._corpus)


# ── Singleton accessor ────────────────────────────────────────────────────────

def get_rag() -> ClassicalRAG:
    """Return the shared (lazily-built) RAG instance."""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = ClassicalRAG()
    return _rag_instance
