// 塔罗：选牌阵 → 抽牌 → 可选解读。
// 服务端会返回具体 seed，解读时原样带回，保证「看到的牌」和「解读的牌」是同一组。
import { useState } from "react";

import { ApiError, drawTarot, type TarotChart, type TarotInput } from "../../api";
import { ReadingBox } from "./ReadingBox";

const SPREADS: { key: TarotInput["spread"]; label: string; count: number }[] = [
  { key: "single", label: "单张", count: 1 },
  { key: "three", label: "三张", count: 3 },
  { key: "cross", label: "五张", count: 5 },
];

export function TarotPanel() {
  const [spread, setSpread] = useState<TarotInput["spread"]>("three");
  const [chart, setChart] = useState<TarotChart | null>(null);
  const [lastInput, setLastInput] = useState<TarotInput | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const draw = async (nextSpread: TarotInput["spread"] = spread) => {
    if (busy) return;
    const input: TarotInput = { spread: nextSpread };
    setBusy(true);
    setError(null);
    try {
      setChart(await drawTarot(input));
      setLastInput(input);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "抽牌失败了，请再试一次");
    } finally {
      setBusy(false);
    }
  };

  // 解读要带上服务端给的 seed：塔罗参数里 seed 不传就会重抽。
  const params: Record<string, unknown> | null =
    chart && lastInput ? { ...lastInput, seed: chart.seed } : null;

  return (
    <>
      <form
        className="f-form f-form--tarot"
        onSubmit={(event) => {
          event.preventDefault();
          void draw();
        }}
      >
        <div className="f-field f-field--seg">
          <span className="f-label">牌阵</span>
          <div className="seg" role="group" aria-label="牌阵">
            {SPREADS.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`seg__item${spread === item.key ? " seg__item--on" : ""}`}
                onClick={() => setSpread(item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
        <button className="btn btn--solid f-submit" type="submit" disabled={busy}>
          {busy ? "抽牌中…" : chart ? "重新抽牌" : "抽牌"}
        </button>
      </form>
      <p className="f-hint">
        抽牌用服务端 seed，同一 seed 永远同一组牌——抽完才解读，解读的就是你眼前这组。
      </p>

      {error && (
        <p className="note note--error" role="alert">
          {error}
        </p>
      )}

      {!chart && !error && (
        <div className="chart-empty">
          <span className="chart-empty__seal" aria-hidden="true">
            卜
          </span>
          <p>选一个牌阵抽牌。这里不做「抽到满意为止」——想重抽就整组重来。</p>
        </div>
      )}

      {chart && (
        <>
          <div className="chart-card chart-card--tarot">
            <header className="chart-head">
              <span className="chart-kicker">塔罗 · {chart.spread}</span>
              <p className="chart-head__line">
                共 {chart.cards.length} 张
                <span className="chart-head__dot">·</span>
                seed {chart.seed}
              </p>
            </header>

            <div className="tarot-cards">
              {chart.cards.map((card, index) => (
                <figure
                  className={`tarot-tile${
                    card.orientation === "逆位" ? " tarot-tile--reversed" : ""
                  }`}
                  key={`${card.card_id}-${index}`}
                >
                  <figcaption className="tarot-tile__pos">{card.position}</figcaption>
                  <div className="tarot-tile__face">
                    <span className="tarot-tile__num">{String(index + 1).padStart(2, "0")}</span>
                    <span className="tarot-tile__name">{card.name}</span>
                    <span className="tarot-tile__orient">{card.orientation}</span>
                  </div>
                  <p className="tarot-tile__meaning">{card.meaning}</p>
                  <span className="tarot-tile__arcana">{card.arcana}</span>
                </figure>
              ))}
            </div>
          </div>

          {params && (
            <ReadingBox kind="tarot" params={params} resetKey={String(chart.seed)} />
          )}
        </>
      )}
    </>
  );
}
