// 解读块：三种盘共用。
//
// 盘面在上，这里只负责「把已经算好的盘讲一讲」。
// 用户可以不填问题直接要整体解读；问题只影响措辞，不影响盘面。
//
// 解读会带回收到的古籍片段编号：正文里的 [n] 可以点开原文。
// 但盘面本身才是主证据——没有引用不代表解读失败。
import { useEffect, useState } from "react";

import {
  ApiError,
  lookupChunks,
  readFortune,
  type Chunk,
  type FortuneKind,
  type FortuneReading,
} from "../../api";
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

  useEffect(() => {
    setReading(null);
    setFocus(null);
    setError(null);
  }, [resetKey]);

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
  const labels: Record<number, number> = {};
  for (const ref of reading?.citation_map ?? []) {
    if (ref.marker != null) labels[ref.chunk_id] = ref.marker;
  }
  Array.from(new Set(citationIds)).forEach((id, index) => {
    if (labels[id] == null) labels[id] = index + 1;
  });

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
        盘面由程序算出，解读由模型组织语言；它只解释上面的盘面，不重算、不补星体。
      </p>
      <p className="reading__hint">
        正文里的 [n] 是检索到的古籍片段，可点开核对原文；没有引用表示这段只依据盘面。
      </p>
      <p className="reading__hint">
        以下内容为传统文化视角的说明，仅供文化研究与娱乐参考，不构成任何决策建议。
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
              <AnswerBody text={reading.summary} onCite={cite} />
            </div>
          )}
          {reading.sections.map((section, index) => (
            <div className="reading__section" key={`${section.title}-${index}`}>
              {section.title && <h3>{section.title}</h3>}
              <AnswerBody text={section.content} onCite={cite} />
            </div>
          ))}
          <Sources ids={citationIds} chunks={chunks} focus={focus} labels={labels} />
          <p className="reading__disclaimer">{reading.disclaimer}</p>
        </article>
      )}
    </section>
  );
}
