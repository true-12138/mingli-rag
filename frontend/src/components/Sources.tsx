// 出处：回答底部的引用条。点编号展开那一节的原文。
//
// 正文里的 [n] 点过来时，TurnView 把 chunk_id 塞进 focus，这里负责展开并滚到眼前。
import { useEffect, useRef, useState } from "react";

import type { Chunk } from "../api";

interface Focus {
  chunkId: number;
  nonce: number;
}

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
          <p className="source-quote__text">
            {chunks[open] ? chunks[open].text : "原文还在取，稍等片刻。"}
          </p>
        </div>
      )}
    </section>
  );
}

function shortBook(chunk: Chunk): string {
  return chunk.book || "古籍";
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
