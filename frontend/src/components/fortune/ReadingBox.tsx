// 解读块：三种盘共用。
//
// 盘面在上，这里只负责「把已经算好的盘讲一讲」。
// 用户可以不填问题直接要整体解读；问题只影响措辞，不影响盘面。
//
// 解读会带回收到的古籍片段编号：正文里的 [n] 可以点开原文。
// 但盘面本身才是主证据——没有引用不代表解读失败。
import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  lookupChunks,
  readFortune,
  type Chunk,
  type FortuneKind,
  type FortuneReading,
  type TermHit,
} from "../../api";
import { loadTerms } from "../../termCache";
import { AnswerBody } from "../AnswerBody";
import { Sources } from "../Sources";

interface Props {
  kind: FortuneKind;
  params: Record<string, unknown>;
  /** 换了盘就把上一次的解读清掉，避免解读和盘面对不上。 */
  resetKey: string;
}

export function ReadingBox({ kind, params, resetKey }: Props) {
  const [question, setQuestion] = useState("");
  const [reading, setReading] = useState<FortuneReading | null>(null);
  const [chunks, setChunks] = useState<Record<number, Chunk>>({});
  const [focus, setFocus] = useState<{ chunkId: number; nonce: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 摘要和每个小节各标一次；下标与渲染顺序一一对应（0 是摘要）。
  const [terms, setTerms] = useState<TermHit[][]>([]);

  useEffect(() => {
    setReading(null);
    setFocus(null);
    setError(null);
    setTerms([]);
  }, [resetKey]);

  // 解读是本项目里最集中出现命理术语的地方，术语卡在这里比在问答里更有用。
  // 标注失败不影响解读本身，所以静默降级成纯文字。
  useEffect(() => {
    if (!reading) {
      setTerms([]);
      return;
    }
    const texts = [reading.summary ?? "", ...reading.sections.map((section) => section.content ?? "")];
    let alive = true;
    Promise.all(texts.map((text) => (text.trim() ? loadTerms(text) : Promise.resolve([]))))
      .then((all) => {
        if (alive) setTerms(all);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [reading]);

  const loadChunks = async (ids: number[]) => {
    const unique = Array.from(new Set(ids.filter((id) => Number.isFinite(id))));
    if (unique.length === 0) return;
    try {
      const fetched = await lookupChunks(unique);
      setChunks((prev) => {
        const next = { ...prev };
        for (const chunk of fetched) next[chunk.chunk_id] = chunk;
        return next;
      });
    } catch {
      /* 原文取不到不影响解读本身 */
    }
  };

  const run = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await readFortune(kind, params, question.trim() || undefined);
      setReading(result);
      setFocus(null);
      void loadChunks(result.citations_chunk_ids ?? []);
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setError("服务端还没配置模型 key，现在只能看盘面。");
      } else if (err instanceof ApiError && err.status === 429) {
        setError("解读请求排队已满，稍等几秒再试。");
      } else {
        setError(err instanceof ApiError ? err.message : "解读失败了，请再试一次");
      }
    } finally {
      setBusy(false);
    }
  };

  const citationIds = reading?.citations_chunk_ids ?? [];
  // 正文渲染依赖这张表，每次 render 新建对象会让整段重新解析。
  const labels = useMemo(() => {
    const out: Record<number, number> = {};
    for (const ref of reading?.citation_map ?? []) {
      if (ref.marker != null) out[ref.chunk_id] = ref.marker;
    }
    Array.from(new Set(reading?.citations_chunk_ids ?? [])).forEach((id, index) => {
      if (out[id] == null) out[id] = index + 1;
    });
    return out;
  }, [reading]);

  const cite = (marker: number) => {
    const mapped = reading?.citation_map?.find((ref) => ref.marker === marker);
    const chunkId = mapped?.chunk_id ?? citationIds[marker - 1];
    if (chunkId != null) setFocus({ chunkId, nonce: Date.now() });
  };

  return (
    <section className="reading">
      <div className="reading__bar">
        <input
          className="reading__q"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="想问什么？（可不填，直接看整体）"
          maxLength={500}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.nativeEvent.isComposing) void run();
          }}
        />
        <button type="button" className="btn btn--solid" onClick={run} disabled={busy}>
          {busy ? "解读中…" : "查看文化视角说明"}
        </button>
      </div>
      <p className="reading__hint">
        {kind === "name"
          ? "姓名解读按康熙笔画与五格剖象表解释；这套体系来自 1928 年，仅供文化参考，不涉及改名与命运断言。"
          : "解读只解释盘面；[n] 可点开核对原文；仅供文化研究与娱乐参考。"}
      </p>

      {error && (
        <p className="note note--error" role="alert">
          {error}
        </p>
      )}

      {reading && (
        <article className="reading__out">
          {reading.summary && (
            <div className="reading__summary">
              <AnswerBody text={reading.summary} onCite={cite} terms={terms[0]} chunkLabels={labels} />
            </div>
          )}
          {reading.sections.map((section, index) => (
            <div className="reading__section" key={`${section.title}-${index}`}>
              {section.title && <h3>{section.title}</h3>}
              <AnswerBody
                text={section.content}
                onCite={cite}
                terms={terms[index + 1]}
                chunkLabels={labels}
              />
            </div>
          ))}
          <Sources ids={citationIds} chunks={chunks} focus={focus} labels={labels} />
          <p className="reading__disclaimer">{reading.disclaimer}</p>
        </article>
      )}
    </section>
  );
}
