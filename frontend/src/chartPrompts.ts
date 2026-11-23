// 盘面挂上之后，右侧示例问题换成「就这张盘能问什么」。
// 问句只用这批古籍里真出现过的说法，且都实测过能命中；
// 星盘/塔罗的古籍覆盖弱，沿用页面自带的七政四余题，不硬凑。
// 姓名（五格剖象）是现代数理体系，问句一律说「这套体系」，不冒充古书。
import type { FortuneChart } from "./api";

// 天干 → 五行。古籍里叫「己土」「甲木」，带上五行才检索得到。
const WUXING: Record<string, string> = {
  甲: "木",
  乙: "木",
  丙: "火",
  丁: "火",
  戊: "土",
  己: "土",
  庚: "金",
  辛: "金",
  壬: "水",
  癸: "水",
};

// 输入框占位文字也按盘型说人话：相术页再写「用神」就串味了。
export function chartPlaceholder(chart: FortuneChart | null): string | undefined {
  if (!chart) return undefined;
  switch (chart.kind) {
    case "bazi":
      return "就这张盘追问，比如用神、性情";
    case "astro":
      return "就这张盘追问，比如宫位、格局";
    case "tarot":
      return "就这次牌阵追问，比如牌义、位置";
    case "physiognomy":
      return "就问这些特征，比如气色、格局";
    case "name":
      return "就这个名字追问，比如五格、三才";
    default:
      return undefined;
  }
}

export function chartSuggestions(chart: FortuneChart | null): readonly string[] | null {
  if (!chart) return null;

  if (chart.kind === "bazi") {
    const dm = (chart.day_master || "").trim();
    const element = WUXING[dm] ?? "";
    const out: string[] = [];
    if (dm) {
      out.push(`日主${dm}${element}有什么特点？`);
      out.push(`我这盘日主${dm}${element}，用神大概怎么取？`);
    }
    const monthGod = (chart.shishen_gan?.["月柱"] || "").trim();
    if (monthGod && monthGod !== "日主") {
      out.push(`${monthGod}在月柱，古书怎么讲？`);
    }
    return out.length > 0 ? out.slice(0, 3) : null;
  }

  if (chart.kind === "physiognomy") {
    const out: string[] = [];
    for (const [key, value] of Object.entries(chart.features || {})) {
      const text = (value || "").trim();
      if (!text) continue;
      // 单字特征（white 的「白」「黄」）离开部位说不通，补上字段名。
      out.push(text.length > 1 ? `${text}，古籍怎么论？` : `${key}${text}，古籍怎么论？`);
      if (out.length >= 4) break;
    }
    return out.length > 0 ? out : null;
  }

  if (chart.kind === "name") {
    // 五格剖象不是古籍：问句说「这套体系」，不能说「古书」。
    const out: string[] = [];
    const ren = chart.wuge.ren;
    if (ren?.num) {
      out.push(`人格${ren.num}${ren.wuxing}${ren.level}，这套体系怎么讲？`);
    }
    if (chart.sancai?.combo) {
      out.push(`三才${chart.sancai.combo}是什么意思？`);
    }
    const wx = [...new Set((chart.chars || []).map((item) => item.wuxing).filter(Boolean))];
    if (wx.length > 0) {
      out.push(`名字里用${wx.join("、")}，说明什么？`);
    }
    return out.length > 0 ? out.slice(0, 3) : null;
  }

  return null;
}
