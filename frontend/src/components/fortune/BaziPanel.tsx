// 八字：表单 → 四柱盘 → 可选的模型解读。
// 排盘本身不调模型，点「排盘」会立刻出结果；解读才需要等模型。
import { useState } from "react";

import { ApiError, drawBazi, type BaziChart, type BaziInput } from "../../api";
import { ReadingBox } from "./ReadingBox";
import { splitDate, splitTime } from "./datetime";

const PILLARS = ["年柱", "月柱", "日柱", "时柱"];
const WUXING = [
  { name: "木", cls: "mu" },
  { name: "火", cls: "huo" },
  { name: "土", cls: "tu" },
  { name: "金", cls: "jin" },
  { name: "水", cls: "shui" },
];

export function BaziPanel() {
  const [date, setDate] = useState("");
  const [time, setTime] = useState("12:00");
  const [gender, setGender] = useState<"male" | "female">("male");
  const [chart, setChart] = useState<BaziChart | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    const ymd = splitDate(date);
    if (!ymd) {
      setError("先填出生日期（公历）。");
      return;
    }
    const { hour, minute } = splitTime(time);
    const input: BaziInput = { ...ymd, hour, minute, gender };
    setBusy(true);
    setError(null);
    try {
      setChart(await drawBazi(input));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "排盘失败了，请检查出生时间");
    } finally {
      setBusy(false);
    }
  };

  const params: Record<string, unknown> | null = chart
    ? {
        year: chart.input.year,
        month: chart.input.month,
        day: chart.input.day,
        hour: chart.input.hour,
        minute: chart.input.minute,
        gender: chart.input.gender,
      }
    : null;

  return (
    <>
      <form className="f-form" onSubmit={submit}>
        <label className="f-field">
          <span className="f-label">出生日期</span>
          <input
            className="f-input"
            type="date"
            value={date}
            min="1900-01-01"
            max="2100-12-31"
            onChange={(event) => setDate(event.target.value)}
            required
          />
        </label>
        <label className="f-field f-field--time">
          <span className="f-label">出生时间</span>
          <input
            className="f-input"
            type="time"
            value={time}
            onChange={(event) => setTime(event.target.value)}
          />
        </label>
        <div className="f-field f-field--seg">
          <span className="f-label">性别</span>
          <div className="seg" role="group" aria-label="性别">
            {(["male", "female"] as const).map((value) => (
              <button
                key={value}
                type="button"
                className={`seg__item${gender === value ? " seg__item--on" : ""}`}
                onClick={() => setGender(value)}
              >
                {value === "male" ? "男" : "女"}
              </button>
            ))}
          </div>
        </div>
        <button className="btn btn--solid f-submit" type="submit" disabled={busy}>
          {busy ? "排盘中…" : "排盘"}
        </button>
      </form>
      <p className="f-hint">
        公历时间，按北京时间排。不确定时辰就填 12:00——时柱会不准，日柱仍然准确。
      </p>

      {error && (
        <p className="note note--error" role="alert">
          {error}
        </p>
      )}

      {!chart && !error && (
        <div className="chart-empty">
          <span className="chart-empty__seal" aria-hidden="true">
            八
          </span>
          <p>填好出生时间，盘会当场算出来。干支、节气、大运都来自历法计算，不经过模型。</p>
        </div>
      )}

      {chart && (
        <>
          <div className="chart-card">
            <header className="chart-head">
              <span className="chart-kicker">八字 · 四柱</span>
              <p className="chart-head__line">
                公历 {chart.input.solar}
                <span className="chart-head__dot">·</span>
                {chart.input.lunar}
                <span className="chart-head__dot">·</span>
                {chart.input.gender === "male" ? "男" : "女"}
                <span className="chart-head__dot">·</span>
                属{chart.shengxiao}
              </p>
            </header>

            <div className="pillars">
              {PILLARS.map((name) => {
                const ganzhi = chart.sizhu[name] ?? "";
                const self = name === "日柱";
                return (
                  <div className={`pillar${self ? " pillar--self" : ""}`} key={name}>
                    <span className="pillar__label">{name}</span>
                    <span className="pillar__chars">
                      <span>{ganzhi[0] ?? "—"}</span>
                      <span>{ganzhi[1] ?? "—"}</span>
                    </span>
                    <span className="pillar__shishen">
                      {chart.shishen_gan[name] || "—"}
                    </span>
                    <span className="pillar__cang">
                      藏 {(chart.canggan[name] ?? []).join("、") || "—"}
                    </span>
                    <span className="pillar__nayin">{chart.nayin[name]}</span>
                  </div>
                );
              })}
            </div>

            <div className="wuxing">
              <div className="wuxing__bars">
                {WUXING.map(({ name, cls }) => {
                  const count = chart.wuxing[name] ?? 0;
                  return (
                    <div className={`wx wx--${cls}`} key={name}>
                      <span className={`wx__count${count === 0 ? " wx__count--zero" : ""}`}>
                        {count}
                      </span>
                      <div className="wx__track">
                        <span
                          className="wx__fill"
                          style={{ height: `${(count / 8) * 100}%` }}
                        />
                      </div>
                      <span className="wx__name">{name}</span>
                    </div>
                  );
                })}
              </div>
              <p className="wuxing__note">
                {chart.wuxing_missing.length > 0
                  ? `八个字里缺：${chart.wuxing_missing.join("、")}`
                  : "八个字五行俱全"}
                <span>（只数天干地支，不数藏干）</span>
              </p>
            </div>

            <div className="dayun">
              <span className="dayun__label">
                大运
                <em>
                  起运 {chart.qiyun.years} 岁 {chart.qiyun.months} 个月，
                  {chart.qiyun.forward ? "顺排" : "逆排"}
                </em>
              </span>
              <div className="dayun__rail">
                {chart.dayun.map((item) => {
                  const current = chart.current_dayun?.start_year === item.start_year;
                  return (
                    <div className={`dayun__item${current ? " dayun__item--on" : ""}`} key={item.start_year}>
                      <span className="dayun__gz">{item.ganzhi}</span>
                      <span className="dayun__age">{item.start_age} 岁</span>
                    </div>
                  );
                })}
              </div>
            </div>

            <details className="fine">
              <summary>盘面细目</summary>
              <dl className="fine__list">
                <div>
                  <dt>日主</dt>
                  <dd>{chart.day_master}</dd>
                </div>
                <div>
                  <dt>空亡</dt>
                  <dd>
                    {PILLARS.map((name) => `${chart.xunkong[name]}（${name[0]}）`).join("　")}
                  </dd>
                </div>
                <div>
                  <dt>纳音</dt>
                  <dd>
                    {PILLARS.map((name) => `${name[0]} ${chart.nayin[name]}`).join("　")}
                  </dd>
                </div>
                <div>
                  <dt>地支十神</dt>
                  <dd>
                    {PILLARS.map(
                      (name) => `${name[0]} ${(chart.shishen_zhi[name] ?? []).join("、")}`,
                    ).join("　")}
                  </dd>
                </div>
                <div>
                  <dt>胎元 / 命宫 / 身宫</dt>
                  <dd>
                    {chart.taiyuan} / {chart.minggong} / {chart.shengong}
                  </dd>
                </div>
              </dl>
            </details>
          </div>

          {params && (
            <ReadingBox kind="bazi" params={params} resetKey={chart.input.solar + chart.input.gender} />
          )}
        </>
      )}
    </>
  );
}
