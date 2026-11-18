// 出处：回答底部的引用条。点编号展开那一节的原文。
//
// 正文里的 [n] 点过来时，TurnView 把 chunk_id 塞进 focus，这里负责展开并滚到眼前。
// 白话释义只在读者点「白话释义」时才请求：默认仍是原文，避免展开一条就多一次模型调用。
// 无标点组的原文可以点「自动断句」：后端只插标点、改字的结果会被拒绝。
import { useEffect, useRef, useState } from "react";

import type { Chunk, ChunkInterpretation, ChunkSegmentation } from "../api";
import {
  deleteFavorite,
  listFavorites,
  saveFavorite,
  segmentChunks,
} from "../api";
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
            <span className="source-quote__note">
              {tab === "origin" ? "引用以原样原文为准" : "译文仅辅助阅读，不算引用依据"}
            </span>
            <FavoriteButton chunkId={open} />
          </div>
          {tab === "origin" ? (
            <OriginBody key={open} chunk={chunks[open]} />
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

/**
 * 引用卡的收藏开关：只记 chunk_id，笔记在素材页写。
 * 挂载时查一次这段是否已收藏；重复收藏由后端按 (用户, chunk_id) 幂等。
 */
function FavoriteButton({ chunkId }: { chunkId: number }) {
  const [state, setState] = useState<"loading" | "idle" | "saved" | "saving">("loading");
  const [favoriteId, setFavoriteId] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    setState("loading");
    listFavorites(chunkId)
      .then((items) => {
        if (!alive) return;
        const hit = items[0];
        setFavoriteId(hit ? hit.id : null);
        setState(hit ? "saved" : "idle");
      })
      .catch(() => {
        if (alive) setState("idle");
      });
    return () => {
      alive = false;
    };
  }, [chunkId]);

  async function toggle() {
    if (state === "loading" || state === "saving") return;
    const before = state;
    setState("saving");
    try {
      if (before === "saved" && favoriteId != null) {
        await deleteFavorite(favoriteId);
        setFavoriteId(null);
        setState("idle");
      } else {
        const favorite = await saveFavorite(chunkId);
        setFavoriteId(favorite.id);
        setState("saved");
      }
    } catch {
      // 失败就回到原来的状态，不给假成功。
      setState(before);
    }
  }

  const label =
    state === "saved" ? "已收藏" : state === "saving" ? "保存中…" : state === "loading" ? "…" : "收藏";

  return (
    <button
      type="button"
      className={`source-quote__fav${state === "saved" ? " is-saved" : ""}`}
      onClick={() => void toggle()}
      disabled={state === "loading" || state === "saving"}
      title={
        state === "saved"
          ? "再点一次取消收藏；笔记在「素材」页写"
          : "把这段原文存进「素材」，可导出 Markdown"
      }
    >
      {label}
    </button>
  );
}

type SegmentState = ChunkSegmentation | "loading";

/** 无标点组：句读标点占比极低。阈值放宽到 1%，避免把「一段只有一两个逗号」的残卷漏掉。 */
function looksUnpunctuated(text: string): boolean {
  if (text.length < 40) return false;
  const marks = (text.match(/[，。、；：！？]/g) || []).length;
  return marks / text.length < 0.01;
}

function OriginBody({ chunk }: { chunk: Chunk | undefined }) {
  const [state, setState] = useState<SegmentState | null>(null);
  const [showSegmented, setShowSegmented] = useState(false);

  if (!chunk) {
    return <p className="source-quote__hint">原文还在取，稍等片刻。</p>;
  }
  const text = chunk.text;
  const offer = looksUnpunctuated(text);
  const loading = state === "loading";
  const result = state && state !== "loading" ? state : null;
  const canToggle = Boolean(result?.text);

  async function run() {
    setState("loading");
    try {
      const items = await segmentChunks([chunk!.chunk_id]);
      const item = items[0];
      if (item) {
        setState(item);
        setShowSegmented(Boolean(item.text));
      } else {
        setState({
          chunk_id: chunk!.chunk_id, text: null, cached: false,
          error: "没有返回断句结果",
        });
      }
    } catch (err) {
      setState({
        chunk_id: chunk!.chunk_id, text: null, cached: false,
        error: err instanceof Error ? err.message : "自动断句失败",
      });
    }
  }

  if (!offer && !canToggle) {
    return <p className="source-quote__text">{text}</p>;
  }

  return (
    <>
      <p className="source-quote__text">
        {showSegmented && result?.text ? result.text : text}
      </p>
      <div className="source-quote__foot">
        <button
          type="button"
          className="source-quote__action"
          disabled={loading}
          onClick={() => {
            if (canToggle) setShowSegmented((v) => !v);
            else void run();
          }}
        >
          {loading ? "正在断句…" : canToggle ? (showSegmented ? "看原样" : "看断句") : "自动断句"}
        </button>
        {showSegmented && (
          <span className="source-quote__hint">
            程序只补了标点，未改一字；引用仍以原样原文为准。
          </span>
        )}
        {!showSegmented && result?.error && (
          <span className="source-quote__hint">{result.error}</span>
        )}
      </div>
    </>
  );
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
      {item.warnings && item.warnings.length > 0 && (
        <p className="source-quote__hint">
          自检提示：{item.warnings.join("；")}。以原文为准。
        </p>
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
