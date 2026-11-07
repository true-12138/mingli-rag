// 回答正文：markdown + 引用标记。
//
// 后端的引用有两种写法：RAG 正文里是 [1][2]（片段序号），Agent 正文里没有标记、
// 引用在 structured 字段里。这里只负责把 [n] 变成可点的上标，n 指什么由
// TurnView 查 citation_map / 顺序决定，不在渲染层假设。
import { useMemo } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props {
  text: string;
  onCite: (marker: number) => void;
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

export function AnswerBody({ text, onCite }: Props) {
  const source = useMemo(() => linkCitations(text), [text]);

  const components: Components = {
    a({ href, children }) {
      if (href?.startsWith("#cite-")) {
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
      <Markdown remarkPlugins={[remarkGfm]} components={components}>
        {source}
      </Markdown>
    </div>
  );
}
