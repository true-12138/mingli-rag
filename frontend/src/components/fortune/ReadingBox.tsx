// 解读块：三种盘共用。
//
// 盘面在上，这里只负责「把已经算好的盘讲一讲」。
// 用户可以不填问题直接要整体解读；问题只影响措辞，不影响盘面。
import { useEffect, useState } from "react";

import { ApiError, readFortune, type FortuneKind, type FortuneReading } from "../../api";
import { AnswerBody } from "../AnswerBody";

interface Props {
  kind: FortuneKind;
  params: Record<string, unknown>;
  /** 换了盘就把上一次的解读清掉，避免解读和盘面对不上。 */
  resetKey: string;
}

export function ReadingBox({ kind, params, resetKey }: Props) {
  const [question, setQuestion] = useState("");
  const [reading, setReading] = useState<FortuneReading | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setReading(null);
    setError(null);
  }, [resetKey]);

  const run = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await readFortune(kind, params, question.trim() || undefined);
      setReading(result);
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
          {busy ? "解读中…" : "解读此盘"}
        </button>
      </div>
      <p className="reading__hint">
        盘面由程序算出，解读由模型组织语言；它只解释上面的盘面，不重算、不补星体。
      </p>

      {error && (
        <p className="note note--error" role="alert">
          {error}
        </p>
      )}

      {reading && (
        <article className="reading__out">
          {reading.summary && <p className="reading__summary">{reading.summary}</p>}
          {reading.sections.map((section, index) => (
            <div className="reading__section" key={`${section.title}-${index}`}>
              {section.title && <h3>{section.title}</h3>}
              <AnswerBody text={section.content} />
            </div>
          ))}
          <p className="reading__disclaimer">{reading.disclaimer}</p>
        </article>
      )}
    </section>
  );
}
