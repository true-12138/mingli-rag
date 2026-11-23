// 姓名：姓 + 名 → 康熙笔画、五格、三才、三运 → 可选解读。
// 全部是查表计算，点「测算」立刻出结果；解读才调模型。
import { useState } from "react";

import { ApiError, drawName, type NameChart, type NameGrid } from "../../api";
import { ReadingBox } from "./ReadingBox";

const GRIDS: { key: keyof NameChart["wuge"]; label: string }[] = [
  { key: "tian", label: "天格" },
  { key: "ren", label: "人格" },
  { key: "di", label: "地格" },
  { key: "wai", label: "外格" },
  { key: "zong", label: "总格" },
];

// 吉凶只用五种：大吉 / 吉 / 半吉 / 凶 / 大凶。
function levelClass(level: string): string {
  if (level === "大吉") return "great";
  if (level === "吉") return "good";
  if (level === "半吉") return "mid";
  if (level === "大凶") return "worst";
  if (level === "凶") return "bad";
  return "mid";
}

export function NamePanel({ onChart, onAsk }: { onChart: (chart: NameChart) => void; onAsk?: (question: string) => void }) {
  const [surname, setSurname] = useState("");
  const [given, setGiven] = useState("");
  const [chart, setChart] = useState<NameChart | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    const s = surname.trim();
    const g = given.trim();
    if (!s || !g) {
      setError("姓和名都要填。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await drawName({ surname: s, given: g });
      setChart(next);
      setSurname(next.surname);
      setGiven(next.given);
      // 盘一出来就挂到右侧对话上：可以就这个名字继续问
      onChart(next);
    } catch (err) {
      setChart(null);
      setError(err instanceof ApiError ? err.message : "测算失败了，请再试一次");
    } finally {
      setBusy(false);
    }
  };

  const total = chart ? chart.wuge.zong.num : 0;
  const strokes = chart ? chart.chars.map((item) => item.kangxi).join(" + ") : "";

  return (
    <>
      <form className="f-form f-form--name" onSubmit={submit}>
        <label className="f-field f-field--name">
          <span className="f-label">姓</span>
          <input
            className="f-input"
            value={surname}
            onChange={(event) => setSurname(event.target.value)}
            placeholder="李 / 欧阳"
            maxLength={2}
            autoComplete="off"
          />
        </label>
        <label className="f-field f-field--name">
          <span className="f-label">名</span>
          <input
            className="f-input"
            value={given}
            onChange={(event) => setGiven(event.target.value)}
            placeholder="明 / 明轩"
            maxLength={2}
            autoComplete="off"
          />
        </label>
        <button className="btn btn--solid f-submit" type="submit" disabled={busy}>
          {busy ? "测算中…" : "测算"}
        </button>
      </form>
      <p className="f-hint">
        按康熙字典笔画；单姓或复姓，单名或双名。五格剖象为 1928 年以来的现代数理体系，仅供文化参考。
      </p>

      {error && (
        <p className="note note--error" role="alert">
          {error}
        </p>
      )}

      {chart && (
        <>
          <div className="chart-card chart-card--name">
            <header className="chart-head">
              <span className="chart-kicker">姓名 · 五格剖象</span>
              <p className="chart-head__line">
                {chart.full}
                <span className="chart-head__dot">·</span>
                康熙笔画 {strokes}
                <span className="chart-head__dot">·</span>
                总 {total}
              </p>
            </header>

            <div className="name-chars">
              {chart.chars.map((item) => (
                <div className="name-char" key={`${item.char}-${item.role}`}>
                  <span className="name-char__glyph">{item.char}</span>
                  <span className="name-char__meta">
                    {item.role} · {item.kangxi} 画 · {item.wuxing || "五行未注"}
                  </span>
                  <span className="name-char__sub">
                    {item.pinyin || "—"} · {item.structure || "—"} · 部首 {item.radical || "—"}
                  </span>
                </div>
              ))}
            </div>

            <div className="name-grid">
              {GRIDS.map(({ key, label }) => {
                const grid: NameGrid = chart.wuge[key];
                return (
                  <div
                    className={`name-grid__cell${key === "ren" ? " name-grid__cell--main" : ""}`}
                    key={key}
                  >
                    <span className="name-grid__label">
                      {label}
                      <em>{grid.role}</em>
                    </span>
                    <span className="name-grid__num">{grid.num}</span>
                    <span className="name-grid__wx">{grid.wuxing}</span>
                    <span className={`name-level name-level--${levelClass(grid.level)}`}>
                      {grid.level}
                    </span>
                  </div>
                );
              })}
            </div>

            <div className="name-sancai">
              <div className="name-sancai__head">
                <span className="name-sancai__key">三才</span>
                <span className="name-sancai__combo">{chart.sancai.combo}</span>
                <span className="name-sancai__rel">
                  天→人 {chart.sancai.tian_ren} · 人→地 {chart.sancai.ren_di}
                </span>
                <span className={`name-level name-level--${levelClass(chart.sancai.level)}`}>
                  {chart.sancai.level}
                </span>
              </div>
              <p className="name-sancai__text">{chart.sancai.text}</p>
            </div>

            <div className="name-yun">
              {chart.yunshi.map((item) => (
                <div className="name-yun__item" key={item.name}>
                  <div className="name-yun__head">
                    <span className="name-yun__name">{item.name}</span>
                    <span className="name-yun__combo">
                      {item.combo} · {item.relation}
                    </span>
                    <span className={`name-level name-level--${levelClass(item.level)}`}>
                      {item.level}
                    </span>
                  </div>
                  <p className="name-yun__text">{item.text}</p>
                  <span className="name-yun__basis">{item.basis}</span>
                </div>
              ))}
            </div>

            <details className="fine">
              <summary>八十一数细目</summary>
              <dl className="fine__list">
                {GRIDS.map(({ key, label }) => {
                  const grid = chart.wuge[key];
                  return (
                    <div key={key}>
                      <dt>
                        {label} {grid.num}
                      </dt>
                      <dd>
                        {grid.poem}。{grid.text}
                        {grid.level_note ? `（${grid.level_note}）` : ""}
                      </dd>
                    </div>
                  );
                })}
              </dl>
            </details>
          </div>

          <ReadingBox
            kind="name"
            params={{ surname: chart.surname, given: chart.given }}
            resetKey={chart.full}
            onAsk={onAsk}
          />
        </>
      )}
    </>
  );
}
