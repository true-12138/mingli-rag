// 一轮问答：问 → 进度 / 正文 → 出处。
import { useEffect, useRef, useState } from "react";

import type { Chunk, StepEvent } from "../api";
import type { Turn } from "../useChat";
import { AnswerBody } from "./AnswerBody";
import { Sources } from "./Sources";

interface Props {
  turn: Turn;
  chunks: Record<number, Chunk>;
  streaming: boolean;
  onAsk: (question: string) => void;
}

interface Focus {
  chunkId: number;
  nonce: number;
}

export function TurnView({ turn, chunks, streaming, onAsk }: Props) {
  const [focus, setFocus] = useState<Focus | null>(null);
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (copyTimer.current != null) window.clearTimeout(copyTimer.current);
    },
    [],
  );

  const cite = (marker: number) => {
    const chunkId = resolveMarker(marker, turn);
    if (chunkId != null) setFocus({ chunkId, nonce: Date.now() });
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(turn.answer);
      setCopied(true);
      copyTimer.current = window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* 浏览器不给剪贴板权限就算了，不打扰用户 */
    }
  };

  const citedBooks = uniqueBooks(turn.citationIds, chunks);
  const labels = citationLabels(turn);
  const finished = turn.status !== "streaming";
  const refusal = turn.canAnswer === false;

  return (
    <article className="turn">
      <div className="turn__ask">
        <span className="turn__who">问</span>
        <p>{turn.question}</p>
      </div>

      <div className="turn__reply">
        <span className="turn__who turn__who--reply">答</span>

        <div className="turn__body">
          {streaming && <Progress turn={turn} />}

          {refusal && (
            <div className="note note--quiet">
              <strong>未能作答</strong>
              {turn.refusalReason ? <span>：{turn.refusalReason}</span> : <span>：语料里没有足够的依据。</span>}
            </div>
          )}

          {turn.answer ? (
            <div className={`answer-wrap${streaming ? " answer-wrap--streaming" : ""}`}>
              <AnswerBody text={turn.answer} onCite={cite} />
            </div>
          ) : (
            streaming &&
            turn.steps.length === 0 &&
            turn.stages.length === 0 && <p className="note note--pending">正在翻书…</p>
          )}

          {turn.status === "error" && (
            <div className="note note--error">
              <span>{turn.error || "这次没接上。"}</span>
              <button type="button" className="link-btn" onClick={() => onAsk(turn.question)}>
                重试
              </button>
            </div>
          )}

          {turn.status === "stopped" && (
            <div className="note note--quiet">
              <span>已停止生成。</span>
              <button type="button" className="link-btn" onClick={() => onAsk(turn.question)}>
                重新问一次
              </button>
            </div>
          )}

          {turn.invalidOutput && (
            <p className="note note--warn">回答格式异常，引用可能不完整，请回原文核对。</p>
          )}

          {finished && (
            <Sources ids={turn.citationIds} chunks={chunks} focus={focus} labels={labels} />
          )}

          {finished && turn.answer && (
            <div className="turn__meta">
              {turn.elapsedMs != null && <span>{(turn.elapsedMs / 1000).toFixed(1)} 秒</span>}
              {turn.llmCalls != null && turn.llmCalls > 0 && <span>{turn.llmCalls} 次模型调用</span>}
              {turn.citationIds.length > 0 && <span>{turn.citationIds.length} 处引用</span>}
              <button type="button" className="link-btn" onClick={copy}>
                {copied ? "已复制" : "复制"}
              </button>
            </div>
          )}

          {turn.steps.length > 0 && (
            <Trace steps={turn.steps} live={streaming} rag={turn.mode === "rag"} />
          )}

          {finished && turn.answer && !refusal && citedBooks.length > 0 && (
            <div className="followups">
              {citedBooks.slice(0, 2).map((book) => (
                <button
                  key={book}
                  type="button"
                  className="followup"
                  onClick={() => onAsk(`《${book}》里对这个问题还有别的论述吗？`)}
                >
                  《{book}》里还有别的说法吗？
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

// 正文 [n] 落到哪条 chunk：优先 RAG 的 citation_map，其次按引用顺序对齐。
function resolveMarker(marker: number, turn: Turn): number | null {
  const mapped = turn.citationMap.find((ref) => ref.marker === marker);
  if (mapped) return mapped.chunk_id;
  const byOrder = turn.citationIds[marker - 1];
  if (byOrder != null) return byOrder;
  return turn.citationIds.includes(marker) ? marker : null;
}

// 正文 [n] 的编号优先：RAG 引用的是第 n 条片段，列表也得用 n 标，
// 否则正文写 [3]、列表只有两条时，用户不知道该点哪个。
function citationLabels(turn: Turn): Record<number, number> {
  const labels: Record<number, number> = {};
  Array.from(new Set(turn.citationIds)).forEach((id, i) => {
    const ref = turn.citationMap.find((item) => item.chunk_id === id && item.marker != null);
    labels[id] = ref?.marker ?? i + 1;
  });
  return labels;
}

function uniqueBooks(ids: number[], chunks: Record<number, Chunk>): string[] {
  const seen: string[] = [];
  for (const id of ids) {
    const book = chunks[id]?.book;
    if (book && !seen.includes(book)) seen.push(book);
  }
  return seen;
}

function Progress({ turn }: { turn: Turn }) {
  const lastStep = turn.steps[turn.steps.length - 1];
  return (
    <div className="progress" aria-live="polite">
      <span className="progress__dot" />
      <span className="progress__text">{stageText(turn)}</span>
      {lastStep && <span className="progress__step">· {stepLabel(lastStep)}</span>}
    </div>
  );
}

function stageText(turn: Turn): string {
  const stage = turn.stages[turn.stages.length - 1];
  if (!stage) {
    if (turn.answer) return "成文中…";
    if (turn.steps.length > 0) return turn.mode === "rag" ? "检索中…" : "查证中…";
    return turn.mode === "rag" ? "检索古籍…" : "正在理解问题…";
  }
  const d = stage.detail ?? {};
  const status = str(d.status);

  switch (stage.agent) {
    case "planner":
      if (status === "start") return "拆解问题…";
      if (status === "retry") return "重新规划…";
      return `已规划 ${count(d.searches)} 路检索`;
    case "retriever":
      if (status === "start") return `查《${str(d.book) || "古籍"}》「${str(d.query)}」`;
      return `已查《${str(d.book) || "古籍"}》，手头 ${count(d.evidence)} 条证据`;
    case "verifier":
      if (status === "start") return "核对证据…";
      return d.sufficient ? "证据够了，起笔…" : "还差一些，补查…";
    case "synthesizer":
      return status === "start" ? "综合作答…" : "收束成文…";
    default:
      return "处理中…";
  }
}

function agentLabel(agent: string): string {
  switch (agent) {
    case "retrieval":
      return "检索";
    case "retriever":
      return "检索员";
    case "supervisor(pre)":
      return "前置";
    case "supervisor(gap)":
      return "补查";
    case "agent":
      return "Agent";
    default:
      return agent;
  }
}

function stepLabel(step: StepEvent): string {
  const args = step.args ?? {};
  const book = str(args.book);
  switch (step.tool) {
    case "retrieve":
      return "按问题检索片段";
    case "search_classics": {
      const query = str(args.query);
      const where = book ? `《${book}》` : "";
      const marks = step.ok === false ? "（未命中）" : "";
      return `检索${where}${query ? `「${query}」` : ""}${marks}`;
    }
    case "fetch_chunk":
      return `取第 ${args.chunk_id ?? "?"} 节原文`;
    case "list_books":
      return "翻检书目";
    case "search_terms":
      return `查术语「${str(args.term)}」`;
    case "draw_bazi":
      return "起四柱";
    case "draw_astro":
      return "排星盘";
    case "draw_tarot":
      return "生成牌面";
    default:
      return step.tool;
  }
}

function Trace({ steps, live, rag }: { steps: StepEvent[]; live: boolean; rag: boolean }) {
  const [open, setOpen] = useState(false);
  const shown = live || open;
  const noun = rag ? "检索" : "查证";
  return (
    <div className="trace">
      {!live && (
        <button type="button" className="trace__toggle" onClick={() => setOpen((v) => !v)}>
          {open ? `收起${noun}过程` : `${noun}过程（${steps.length} 步）`}
        </button>
      )}
      {shown && (
        <ol className="trace__list">
          {steps.map((step, i) => (
            <li key={i} className={step.ok === false ? "trace__row trace__row--bad" : "trace__row"}>
              <span className="trace__agent">{agentLabel(step.agent)}</span>
              <span>{stepLabel(step)}</span>
              {step.chunk_ids.length > 0 && (
                <span className="trace__hits">{step.chunk_ids.length} 条</span>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function str(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function count(value: unknown): number {
  if (Array.isArray(value)) return value.length;
  return typeof value === "number" ? value : 0;
}
