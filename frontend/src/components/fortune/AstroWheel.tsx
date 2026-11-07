// 本命盘轮盘：纯 SVG，无第三方库。
//
// 方位沿用占星习惯：上升点放在圆盘左侧（9 点钟方向），黄经逆时针增加。
// 宫位是整宫制，所以宫界线就是星座界线，不另画一套。
import type { AstroChart } from "../../api";

const SIZE = 520;
const C = SIZE / 2;
const R_OUT = 224;
const R_SIGN = 192;
const R_HOUSE = 184;
const R_PLANET = 150;
const R_LABEL = 164;
const R_ASPECT = 132;
// 同一扇区里行星挨得太近时，标签按这个最小角距错开，再用细线连回真实位置
const LABEL_GAP = 15;

const SIGNS = [
  "白羊", "金牛", "双子", "巨蟹", "狮子", "处女",
  "天秤", "天蝎", "射手", "摩羯", "水瓶", "双鱼",
];

const SHORT: Record<string, string> = {
  太阳: "日", 月亮: "月", 水星: "水", 金星: "金", 火星: "火",
  木星: "木", 土星: "土", 天王星: "天王", 海王星: "海王", 冥王星: "冥王",
};

const HARD = new Set(["四分相", "对分相"]);

interface Point {
  x: number;
  y: number;
}

function mod360(value: number): number {
  return ((value % 360) + 360) % 360;
}

/** 黄经 → 屏幕角度。上升在左，黄经增加逆时针（和传统星盘一致）。 */
function screenAngle(lon: number, ascLon: number): number {
  return mod360(180 + (lon - ascLon));
}

function atAngle(deg: number, radius: number): Point {
  const rad = (deg * Math.PI) / 180;
  return { x: C + radius * Math.cos(rad), y: C - radius * Math.sin(rad) };
}

function polar(lon: number, ascLon: number, radius: number): Point {
  return atAngle(screenAngle(lon, ascLon), radius);
}

function line(a: Point, b: Point) {
  return { x1: a.x, y1: a.y, x2: b.x, y2: b.y };
}

export function AstroWheel({ chart }: { chart: AstroChart }) {
  const ascLon = chart.asc.lon;
  const mcLon = chart.mc.lon;
  const byName = new Map(chart.planets.map((p) => [p.name, p]));
  // 整宫制：第一宫就是上升所在星座，所以宫号不能直接用星座序号
  const ascIndex = SIGNS.indexOf(chart.asc.sign);

  // 标签角度：先按真实黄经排，再强制最小角距，避免同宫行星糊成一团
  const labels = chart.planets
    .map((planet) => ({ planet, angle: screenAngle(planet.lon, ascLon) }))
    .sort((a, b) => a.angle - b.angle);
  for (let pass = 0; pass < 4; pass += 1) {
    for (let i = 1; i < labels.length; i += 1) {
      const gap = labels[i].angle - labels[i - 1].angle;
      if (gap < LABEL_GAP) labels[i].angle = labels[i - 1].angle + LABEL_GAP;
    }
  }

  return (
    <svg
      className="wheel"
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      role="img"
      aria-label={`本命盘：上升${chart.asc.sign}，共 ${chart.planets.length} 颗行星`}
    >
      <title>本命盘 · 整宫制</title>

      <circle cx={C} cy={C} r={R_OUT} className="wheel__rim" />
      <circle cx={C} cy={C} r={R_SIGN} className="wheel__rim wheel__rim--thin" />
      <circle cx={C} cy={C} r={R_HOUSE} className="wheel__house-ring" />

      {/* 星座界线 + 星座名 */}
      {SIGNS.map((sign, i) => {
        const start = i * 30;
        const a = polar(start, ascLon, R_SIGN);
        const b = polar(start, ascLon, R_OUT);
        const mid = polar(start + 15, ascLon, (R_OUT + R_SIGN) / 2);
        return (
          <g key={sign}>
            <line className="wheel__cusp" {...line(a, b)} />
            <text x={mid.x} y={mid.y} className="wheel__sign">
              {sign}
            </text>
            <text
              x={polar(start + 15, ascLon, R_HOUSE - 4).x}
              y={polar(start + 15, ascLon, R_HOUSE - 4).y}
              className="wheel__house-no"
            >
              {((i - ascIndex + 12) % 12) + 1}
            </text>
          </g>
        );
      })}

      {/* 相位线：硬相位朱砂，软相位淡墨 */}
      {chart.aspects
        .filter((asp) => asp.angle !== 0)
        .map((asp, i) => {
          const a = byName.get(asp.a);
          const b = byName.get(asp.b);
          if (!a || !b) return null;
          return (
            <line
              key={`${asp.a}-${asp.b}-${i}`}
              className={`wheel__aspect${HARD.has(asp.aspect) ? " wheel__aspect--hard" : ""}`}
              {...line(polar(a.lon, ascLon, R_ASPECT), polar(b.lon, ascLon, R_ASPECT))}
            />
          );
        })}

      {/* 行星：点标在真实黄经，标签按最小角距错开，错开时用细线连回 */}
      {labels.map(({ planet, angle }) => {
        const trueAngle = screenAngle(planet.lon, ascLon);
        const shift = Math.abs(((angle - trueAngle + 540) % 360) - 180);
        const tip = atAngle(trueAngle, R_PLANET);
        const anchor = atAngle(angle, R_LABEL - 5);
        const labelPoint = atAngle(angle, R_LABEL);
        return (
          <g key={planet.name}>
            <line
              className={shift > 2 ? "wheel__leader" : "wheel__tick"}
              {...line(tip, anchor)}
            />
            <circle cx={tip.x} cy={tip.y} r={2.6} className="wheel__dot" />
            <text x={labelPoint.x} y={labelPoint.y} className="wheel__planet">
              {SHORT[planet.name] ?? planet.name}
              <tspan className="wheel__deg">
                {" "}
                {Math.floor(planet.degree)}°
                {planet.retrograde ? "逆" : ""}
              </tspan>
            </text>
          </g>
        );
      })}

      {/* 上升 / 天顶 */}
      {[
        { lon: ascLon, label: `升 ${chart.asc.sign}` },
        { lon: mcLon, label: `顶 ${chart.mc.sign}` },
      ].map(({ lon, label }) => {
        const p = polar(lon, ascLon, R_OUT + 14);
        return (
          <text key={label} x={p.x} y={p.y} className="wheel__angle">
            {label}
          </text>
        );
      })}

      <circle cx={C} cy={C} r={3} className="wheel__center" />
      <text x={C} y={C + 20} className="wheel__system">
        {chart.house_system}
      </text>
    </svg>
  );
}
