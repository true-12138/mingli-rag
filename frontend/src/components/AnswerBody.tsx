// 回答正文：markdown + 引用标记 + 术语卡。
//
// 后端的引用有两种写法：RAG 正文里是 [1][2]（片段序号），Agent 正文里没有标记、
// 引用在 structured 字段里。这里只负责把 [n] 变成可点的上标，n 指什么由
// TurnView 查 citation_map / 顺序决定，不在渲染层假设。
//
// 术语卡（terms）是另一条线：后端标出正文里出现的命理词条，这里把它们变成
// 下划线，点开是一张释义卡。释义和例句只作解释，不算这条回答的引用依据，
// 所以卡片底部单独写了这句。
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import type { TermHit } from "../api";

interface Props {
  text: string;
  /** 不传就只渲染文字，不把 [n] 变成可点的引用。 */
  onCite?: (marker: number) => void;
  /** 后端标出的术语；不传就不加下划线。 */
  terms?: TermHit[];
}

const CITE = /\[(\d{1,4})\](?!\()/g;

/** 把 [n] 改成 markdown 链接。代码块和行内代码里的方括号原样保留。 */
function linkCitations(md: string): string {
  const lines = md.split("\n");
  const out: string[] = [];
  let fenced = false;

  for (const line of lines) {
    if (/^\s*(```|~~~)/.test(line)) {
      fenced = !fenced;
      out.push(line);
      continue;
    }
    if (fenced) {
      out.push(line);
      continue;
    }
    // 按行内代码切开，只处理偶数段（代码外的文字）
    out.push(
      line
        .split(/(`[^`\n]*`)/g)
        .map((seg, i) => (i % 2 === 1 ? seg : seg.replace(CITE, (_, n: string) => `[${n}](#cite-${n})`)))
        .join(""),
    );
  }
  return out.join("\n");
}

// ---------- 术语：mdast 文本节点里查词 ----------

type MdNode = { type: string; value?: string; url?: string; children?: MdNode[] };

// 代码里的词不加下划线；链接（引用上标）里也不能再套一层链接。
const SKIP_NODES = new Set(["code", "inlineCode", "html", "link", "linkReference"]);

/** 把一段纯文本切成 文本 / 术语 交替的节点。同一处命中取最长的词条。 */
function splitTerms(value: string, terms: string[], hits: TermHit[]): MdNode[] {
  const out: MdNode[] = [];
  let rest = value;
  while (rest) {
    let best = "";
    let at = -1;
    for (const term of terms) {
      const pos = rest.indexOf(term);
      if (pos < 0) continue;
      if (at < 0 || pos < at || (pos === at && term.length > best.length)) {
        at = pos;
        best = term;
      }
    }
    if (at < 0 || !best) {
      out.push({ type: "text", value: rest });
      break;
    }
    if (at > 0) out.push({ type: "text", value: rest.slice(0, at) });
    const index = hits.findIndex((hit) => hit.term === best);
    out.push({ type: "link", url: `#term-${index}`, children: [{ type: "text", value: best }] });
    rest = rest.slice(at + best.length);
  }
  return out;
}

function walkTerms(node: MdNode, terms: string[], hits: TermHit[]): void {
  if (!node.children) return;
  const next: MdNode[] = [];
  for (const child of node.children) {
    if (child.type === "text" && typeof child.value === "string") {
      next.push(...splitTerms(child.value, terms, hits));
      continue;
    }
    if (!SKIP_NODES.has(child.type)) walkTerms(child, terms, hits);
    next.push(child);
  }
  node.children = next;
}

/** remark 插件：词典里的词在正文里一律变成 #term-<序号> 链接。 */
function remarkTerms(terms: string[], hits: TermHit[]) {
  return (tree: MdNode): void => walkTerms(tree, terms, hits);
}

// ---------- 术语卡 ----------

const CARD_WIDTH = 320;
const VIEWPORT_GAP = 12;

interface CardState {
  hit: TermHit;
  top: number;
  left: number;
}

function TermCard({ card, onClose }: { card: CardState; onClose: () => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    const onDown = (event: MouseEvent) => {
      const target = event.target as Element | null;
      if (target?.closest(".term-pop")) return;
      onClose();
    };
    // 卡片是按点击时的坐标 fixed 定位的，页面一滚动就对不上了，直接收起。
    // 卡片自己内部滚动要放过，否则长释义没法往下翻。
    const onScroll = (event: Event) => {
      const target = event.target as Node | null;
      // 文档本身的滚动不影响 fixed 定位；卡片内部的滚动要放过。
      if (!target || target.nodeType === Node.DOCUMENT_NODE) return;
      if ((target as Element).closest?.(".term-pop")) return;
      onClose();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [onClose]);

  const { hit } = card;
  return createPortal(
    <div className="term-pop" role="dialog" aria-label={hit.term} style={{ top: card.top, left: card.left }}>
      <div className="term-pop__head">
        <span className="term-pop__term">{hit.term}</span>
        {hit.category && <span className="term-pop__cat">{hit.category}</span>}
        <button type="button" className="term-pop__close" aria-label="关闭" onClick={onClose}>
          ×
        </button>
      </div>

      {hit.definition ? (
        <p className="term-pop__def">{hit.definition}</p>
      ) : (
        <p className="term-pop__def term-pop__def--missing">词典里这个词的释义缺失，下面是原文例句。</p>
      )}

      {hit.snippets.map((snippet) => (
        <blockquote className="term-pop__snippet" key={`${snippet.chunk_id}-${snippet.text.slice(0, 8)}`}>
          <p>{snippet.text}</p>
          <cite className="term-pop__src">
            《{snippet.book}》{snippet.chapter ? `·${snippet.chapter}` : ""}
          </cite>
        </blockquote>
      ))}

      <p className="term-pop__note">词典释义与例句只作术语解释，不算本条回答的引用依据。</p>
    </div>,
    document.body,
  );
}

// ---------- 组件 ----------

export function AnswerBody({ text, onCite, terms }: Props) {
  const source = useMemo(() => linkCitations(text), [text]);
  const [card, setCard] = useState<CardState | null>(null);

  // 同一个词条在一段话里可能出现多次，下划线只按词条名对齐，卡片内容按名字查。
  const termHits = useMemo(() => {
    if (!terms || terms.length === 0) return [];
    const seen = new Set<string>();
    return terms.filter((hit) => {
      if (seen.has(hit.term)) return false;
      seen.add(hit.term);
      return true;
    });
  }, [terms]);
  const termNames = useMemo(() => termHits.map((hit) => hit.term), [termHits]);
  const plugins = useMemo(
    () => (termNames.length > 0 ? [remarkGfm, remarkTerms(termNames, termHits)] : [remarkGfm]),
    [termNames, termHits],
  );

  const openTerm = (element: HTMLElement, hit: TermHit) => {
    const rect = element.getBoundingClientRect();
    const maxLeft = window.innerWidth - CARD_WIDTH - VIEWPORT_GAP;
    setCard({
      hit,
      top: Math.min(rect.bottom + 8, window.innerHeight - 160),
      left: Math.max(VIEWPORT_GAP, Math.min(rect.left, maxLeft)),
    });
  };

  const components: Components = {
    a({ href, children }) {
      if (href?.startsWith("#term-")) {
        const hit = termHits[Number(href.slice(6))];
        if (!hit) return <span>{children}</span>;
        return (
          <button
            type="button"
            className="term-link"
            aria-label={`术语：${hit.term}`}
            aria-expanded={card?.hit.term === hit.term}
            onClick={(event) => openTerm(event.currentTarget, hit)}
          >
            {children}
          </button>
        );
      }
      if (href?.startsWith("#cite-")) {
        if (!onCite) return <span>{children}</span>;
        const marker = Number(href.slice(6));
        return (
          <sup
            className="cite-link"
            role="button"
            tabIndex={0}
            title="查看原文"
            onClick={(event) => {
              event.preventDefault();
              onCite(marker);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onCite(marker);
              }
            }}
          >
            {children}
          </sup>
        );
      }
      return (
        <a href={href} target="_blank" rel="noreferrer noopener">
          {children}
        </a>
      );
    },
    table({ children }) {
      return (
        <div className="table-wrap">
          <table>{children}</table>
        </div>
      );
    },
  };

  return (
    <div className="answer">
      <Markdown remarkPlugins={plugins} components={components}>
        {source}
      </Markdown>
      {card && <TermCard card={card} onClose={() => setCard(null)} />}
    </div>
  );
}
