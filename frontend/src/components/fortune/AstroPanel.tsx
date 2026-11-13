// 星盘：出生信息 + 出生地 → 本命盘轮盘 → 可选解读。
// 地点只影响上升/天顶和宫位；行星的黄经由时刻决定。
import { useState } from "react";

import {
  ApiError,
  intakeFortune,
  type AstroChart,
  type AstroInput,
  type IntakeNeedInput,
} from "../../api";
import { AstroWheel } from "./AstroWheel";
import { Questionnaire } from "./Questionnaire";
import { ReadingBox } from "./ReadingBox";
import { splitDate, splitTime } from "./datetime";

const CITIES = [
  { name: "北京", lat: 39.9, lon: 116.4 },
  { name: "上海", lat: 31.23, lon: 121.47 },
  { name: "广州", lat: 23.13, lon: 113.26 },
  { name: "深圳", lat: 22.54, lon: 114.06 },
  { name: "成都", lat: 30.57, lon: 104.07 },
  { name: "杭州", lat: 30.27, lon: 120.16 },
  { name: "西安", lat: 34.34, lon: 108.94 },
  { name: "武汉", lat: 30.59, lon: 114.31 },
  { name: "哈尔滨", lat: 45.8, lon: 126.53 },
  { name: "乌鲁木齐", lat: 43.83, lon: 87.62 },
  { name: "拉萨", lat: 29.65, lon: 91.14 },
  { name: "香港", lat: 22.32, lon: 114.17 },
  { name: "台北", lat: 25.03, lon: 121.57 },
];

const ELEMENTS = ["火", "土", "风", "水"];
const MODALITIES = ["基本", "固定", "变动"];

export function AstroPanel() {
  const [date, setDate] = useState("");
  const [time, setTime] = useState("12:00");
  const [city, setCity] = useState(CITIES[0].name);
  const [lat, setLat] = useState(String(CITIES[0].lat));
  const [lon, setLon] = useState(String(CITIES[0].lon));
  const [chart, setChart] = useState<AstroChart | null>(null);
  const [lastInput, setLastInput] = useState<AstroInput | null>(null);
  const [needInput, setNeedInput] = useState<IntakeNeedInput | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  const pickCity = (name: string) => {
    setCity(name);
    const found = CITIES.find((item) => item.name === name);
    if (found) {
      setLat(String(found.lat));
      setLon(String(found.lon));
    }
  };

  // 缺出生日期/钟点时由后端决定问什么；城市和经纬度可选，
  // 用默认值时会带回警告，不悄悄当成北京。
  const runIntake = async (params: Record<string, unknown>) => {
    setBusy(true);
    setError(null);
    setWarning(null);
    try {
      const result = await intakeFortune("astro", params);
      if (result.status === "need_input") {
        setNeedInput(result);
        setChart(null);
        return;
      }
      const next = result.chart as AstroChart;
      setChart(next);
      setLastInput(result.params as unknown as AstroInput);
      setNeedInput(null);
      const p = result.params as {
        year: number; month: number; day: number; hour: number; minute: number;
      };
      setDate(
        `${p.year}-${String(p.month).padStart(2, "0")}-${String(p.day).padStart(2, "0")}`,
      );
      setTime(`${String(p.hour).padStart(2, "0")}:${String(p.minute).padStart(2, "0")}`);
      setCity(next.input.city);
      setLat(String(next.input.lat));
      setLon(String(next.input.lon));
      if (result.warnings.length > 0) setWarning(result.warnings.join(" "));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "排盘失败了，请检查出生信息");
    } finally {
      setBusy(false);
    }
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    const ymd = splitDate(date);
    const { hour, minute } = splitTime(time);
    const input: Record<string, unknown> = { hour, minute, tz: 8 };
    if (ymd) Object.assign(input, ymd);
    if (city.trim()) input.city = city.trim();
    if (lat.trim() && Number.isFinite(Number(lat))) input.lat = Number(lat);
    if (lon.trim() && Number.isFinite(Number(lon))) input.lon = Number(lon);
    void runIntake(input);
  };

  const params: Record<string, unknown> | null = lastInput
    ? { ...lastInput }
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
        <label className="f-field f-field--city">
          <span className="f-label">出生地</span>
          <select
            className="f-input"
            value={city}
            onChange={(event) => pickCity(event.target.value)}
          >
            {CITIES.map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label className="f-field f-field--coord">
          <span className="f-label">纬度</span>
          <input
            className="f-input"
            type="number"
            step="0.01"
            value={lat}
            onChange={(event) => setLat(event.target.value)}
          />
        </label>
        <label className="f-field f-field--coord">
          <span className="f-label">经度</span>
          <input
            className="f-input"
            type="number"
            step="0.01"
            value={lon}
            onChange={(event) => setLon(event.target.value)}
          />
        </label>
        <button className="btn btn--solid f-submit" type="submit" disabled={busy}>
          {busy ? "排盘中…" : "排盘"}
        </button>
      </form>
      <p className="f-hint">
        东经、北纬为正，按东八区换算。上升与宫位对出生地和分钟很敏感，地点尽量填准。
      </p>

      {error && (
        <p className="note note--error" role="alert">
          {error}
        </p>
      )}

      {warning && <p className="note note--warn">{warning}</p>}

      {needInput && (
        <Questionnaire
          message={needInput.message}
          fields={needInput.fields}
          busy={busy}
          onSubmit={(values) => void runIntake({ ...needInput.known, ...values })}
        />
      )}

      {!chart && !error && !needInput && (
        <div className="chart-empty">
          <span className="chart-empty__seal" aria-hidden="true">
            星
          </span>
          <p>行星位置按地心视黄经计算，上升点用当地恒星时求解。宫位采用整宫制。</p>
        </div>
      )}

      {chart && (
        <>
          <div className="chart-card chart-card--astro">
            <header className="chart-head">
              <span className="chart-kicker">西方本命盘 · {chart.house_system}</span>
              <p className="chart-head__line">
                {chart.input.solar}
                <span className="chart-head__dot">·</span>
                {chart.input.city}（{chart.input.lat.toFixed(2)}N, {chart.input.lon.toFixed(2)}E）
                <span className="chart-head__dot">·</span>
                UTC {chart.input.utc}
              </p>
            </header>

            <div className="astro-layout">
              <div className="astro-wheel">
                <AstroWheel chart={chart} />
              </div>

              <aside className="astro-side">
                <div className="astro-angles">
                  <div>
                    <span className="astro-angles__label">上升</span>
                    <strong>
                      {chart.asc.sign} {Math.floor(chart.asc.degree)}°
                    </strong>
                  </div>
                  <div>
                    <span className="astro-angles__label">天顶</span>
                    <strong>
                      {chart.mc.sign} {Math.floor(chart.mc.degree)}°
                    </strong>
                  </div>
                </div>

                <ol className="planet-list">
                  {chart.planets.map((planet) => (
                    <li key={planet.name}>
                      <span className="planet-list__name">{planet.name}</span>
                      <span className="planet-list__pos">
                        {planet.sign} {Math.floor(planet.degree)}°
                        {planet.retrograde && <em className="planet-list__rx">逆</em>}
                      </span>
                      <span className="planet-list__house">{planet.house} 宫</span>
                    </li>
                  ))}
                </ol>

                <div className="balance">
                  <div className="balance__row">
                    <span className="balance__label">元素</span>
                    {ELEMENTS.map((name) => (
                      <span className="balance__cell" key={name}>
                        <span className="balance__bar">
                          <span
                            className="balance__fill"
                            style={{
                              width: `${((chart.elements[name] ?? 0) / chart.planets.length) * 100}%`,
                            }}
                          />
                        </span>
                        {name} {chart.elements[name] ?? 0}
                      </span>
                    ))}
                  </div>
                  <div className="balance__row">
                    <span className="balance__label">三分类</span>
                    {MODALITIES.map((name) => (
                      <span className="balance__cell" key={name}>
                        <span className="balance__bar">
                          <span
                            className="balance__fill"
                            style={{
                              width: `${((chart.modalities[name] ?? 0) / chart.planets.length) * 100}%`,
                            }}
                          />
                        </span>
                        {name} {chart.modalities[name] ?? 0}
                      </span>
                    ))}
                  </div>
                </div>

                {chart.aspects.length > 0 && (
                  <details className="fine fine--inline">
                    <summary>主要相位（{chart.aspects.length}）</summary>
                    <ul className="aspect-list">
                      {chart.aspects.map((aspect, index) => (
                        <li key={`${aspect.a}-${aspect.b}-${index}`}>
                          {aspect.a}
                          <em>{aspect.aspect}</em>
                          {aspect.b}
                          <span>{aspect.orb.toFixed(1)}°</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </aside>
            </div>
          </div>

          {params && (
            <ReadingBox kind="astro" params={params} resetKey={chart.text} />
          )}
        </>
      )}
    </>
  );
}
