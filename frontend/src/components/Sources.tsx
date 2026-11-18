// 出处：回答底部的引用条。点编号展开那一节的原文。
//
// 正文里的 [n] 点过来时，TurnView 把 chunk_id 塞进 focus，这里负责展开并滚到眼前。
// 白话释义只在读者点「白话释义」时才请求：默认仍是原文，避免展开一条就多一次模型调用。
import { useEffect, useRef, useState } from "react";

import type { Chunk, ChunkInterpretation } from "../api";
import { loadInterpretation } from "../interpretCache";

interface Focus {
  chunkId: number;
  nonce: number;
}

type Gloss = ChunkInterpretation | "loading";

interface Props {
  ids: number[];
  chunks: Record<number, Chunk>;
  focus: Focus | null;
  /** chunk_id → 正文里的编号。RAG 的 [n] 和列表编号必须一致，否则点 [3] 落到第 2 条让人发懵。 */
  labels?: Record<number, number>;
}

export function Sources({ ids, chunks, focus, labels }: Props) {
  const unique = Array.from(new Set(ids)).filter((id) => Number.isFinite(id));
  const [open, setOpen] = useState<number | null>(null);
  const [tab, setTab] = useState<"origin" | "gloss">("origin");
  const quoteRefs = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(() => {
    if (!focus) return;
    setOpen(focus.chunkId);
  }, [focus]);

  useEffect(() => {
    if (open == null) return;
    const el = quoteRefs.current[open];
    if (el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [open, focus]);

  if (unique.length === 0) return null;

  return (
    <section className="sources" aria-label="引用出处">
      <div className="sources__head">
        <span className="sources__label">出处</span>
        <span className="sources__count">{unique.length} 条</span>
      </div>

      <div className="sources__chips">
        {unique.map((id, i) => {
          const chunk = chunks[id];
          const active = open === id;
          const label = labels?.[id] ?? i + 1;
          return (
            <button
              key={id}
              type="button"
              className={`chip${active ? " chip--open" : ""}`}
              onClick={() => setOpen(active ? null : id)}
              title={chunk ? chunk.title || chunk.book : "取原文…"}
            >
              <span className="chip__no">{label}</span>
              <span className="chip__label">{chunk ? shortBook(chunk) : "…"}</span>
            </button>
          );
        })}
      </div>

      {open != null && (
        <div
          className="source-quote"
          ref={(el) => {
            quoteRefs.current[open] = el;
          }}
        >
          <QuoteHead
            chunk={chunks[open]}
            citationNo={labels?.[open] ?? unique.indexOf(open) + 1}
          />
          <div className="source-quote__bar">
            <div className="source-quote__tabs" role="tablist" aria-label="原文与白话释义">
              <button
                type="button"
                role="tab"
                aria-selected={tab === "origin"}
                className={`source-quote__tab${tab === "origin" ? " is-active" : ""}`}
                onClick={() => setTab("origin")}
              >
                原文
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === "gloss"}
                className={`source-quote__tab${tab === "gloss" ? " is-active" : ""}`}
                onClick={() => setTab("gloss")}
              >
                白话释义
              </button>
            </div>
            <span className="source-quote__note">译文仅辅助阅读，不算引用依据</span>
          </div>
          {tab === "origin" ? (
            <p className="source-quote__text">
              {chunks[open] ? chunks[open].text : "原文还在取，稍等片刻。"}
            </p>
          ) : (
            // key=chunk_id：换一段就重新挂载，请求状态跟着这一段走，
            // 不在父组件里维护一份「正在生成」的字典（那样切换时会漏掉回调）。
            <GlossBody key={open} chunkId={open} />
          )}
        </div>
      )}
    </section>
  );
}

function shortBook(chunk: Chunk): string {
  return chunk.book || "古籍";
}

function GlossBody({ chunkId }: { chunkId: number }) {
  const [item, setItem] = useState<Gloss>("loading");

  useEffect(() => {
    let alive = true;
    setItem("loading");
    loadInterpretation(chunkId).then((result) => {
      if (alive) setItem(result);
    });
    return () => {
      alive = false;
    };
  }, [chunkId]);

  if (item === "loading") {
    return <p className="source-quote__hint">正在生成白话释义…</p>;
  }
  if (!item.translation) {
    return <p className="source-quote__hint">{item.error || "这段原文暂时没有释义。"}</p>;
  }
  return (
    <>
      <p className="source-quote__text source-quote__text--gloss">{item.translation}</p>
      {item.truncated && (
        <p className="source-quote__hint">原文较长，译文只覆盖开头一段；完整原文见「原文」。</p>
      )}
    </>
  );
}

function QuoteHead({ chunk, citationNo }: { chunk: Chunk | undefined; citationNo: number }) {
  if (!chunk) return <div className="source-quote__head">[{citationNo}] 正在取原文…</div>;
  const meta = [chunk.volume, chunk.chapter].filter(Boolean).join(" · ");
  return (
    <div className="source-quote__head">
      <span className="source-quote__no">[{citationNo}]</span>
      <span className="source-quote__book">《{chunk.book}》</span>
      {meta && <span className="source-quote__meta">{meta}</span>}
    </div>
  );
}
