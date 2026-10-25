#!/usr/bin/env node
/**
 * 用 lunar-javascript (MIT, https://github.com/6tail/lunar-javascript) 生成
 * 八字/黄历 排盘规则参考表，输出为 RAG 友好的纯文本 + JSONL。
 *
 * 用法: node extract-lunar.js <lunar解压目录> <输出目录>
 */
'use strict';
const fs = require('fs');
const path = require('path');

const pkgDir = path.resolve(process.argv[2]);
const outDir = path.resolve(process.argv[3]);
fs.mkdirSync(outDir, { recursive: true });

const L = require(path.join(pkgDir, 'index.js'));
const SRC = '数据来源：lunar-javascript（MIT License，https://github.com/6tail/lunar-javascript）';

const records = [];
const out = []; // [文件名, 标题, 正文]

// ---------- 1. 六十甲子纳音表 ----------
{
  const lines = [];
  // 1984-02-02 之后为甲子年，逐月取年干支遍历一甲子
  for (let y = 1984; y < 2044; y++) {
    const lu = L.Solar.fromYmdHms(y, 6, 1, 12, 0, 0).getLunar();
    const gz = lu.getYearInGanZhi();
    lines.push(`${gz}：纳音${lu.getYearNaYin()}，生肖${lu.getYearShengXiao()}`);
    records.push({ category: '六十甲子纳音', term: gz, text: `${gz}年为${lu.getYearNaYin()}，生肖属${lu.getYearShengXiao()}。` });
  }
  out.push(['lunar-六十甲子纳音.txt', '六十甲子纳音表', lines.join('\n')]);
}

// ---------- 2. 二十四节气 ----------
{
  // 节气名固定顺序（从小寒起为大寒前的完整循环）
  const JIEQI = ['小寒', '大寒', '立春', '雨水', '惊蛰', '春分', '清明', '谷雨', '立夏', '小满',
    '芒种', '夏至', '小暑', '大暑', '立秋', '处暑', '白露', '秋分', '寒露', '霜降', '立冬',
    '小雪', '大雪', '冬至'];
  const table = L.Solar.fromYmdHms(2024, 6, 1, 12, 0, 0).getLunar().getJieQiTable();
  // 冬至在农历表中常落到上一年年末，改从年末的日期取表
  const tableLate = L.Solar.fromYmdHms(2025, 3, 1, 12, 0, 0).getLunar().getJieQiTable();
  const lines = [];
  for (const name of JIEQI) {
    const solar = name === '冬至' ? tableLate[name] : table[name];
    if (!solar) continue;
    const isJie = JIEQI.indexOf(name) % 2 === 0;
    lines.push(`${name}（${isJie ? '节' : '中气'}）：2024 年前后为 ${solar.toYmdHms()}`);
    records.push({ category: '二十四节气', term: name, text: `${name}，二十四节气之一（${isJie ? '节' : '中气'}）。` });
  }
  out.push(['lunar-二十四节气.txt', '二十四节气', lines.join('\n')]);
}

// ---------- 3. 天干地支属性 + 藏干 ----------
{
  const GAN = ['甲', '乙', '丙', '丁', '戊', '己', '庚', '辛', '壬', '癸'];
  const ZHI = ['子', '丑', '寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥'];
  const yz = { 甲: '阳', 乙: '阴', 丙: '阳', 丁: '阴', 戊: '阳', 己: '阴', 庚: '阳', 辛: '阴', 壬: '阳', 癸: '阴' };
  const wx = { 甲: '木', 乙: '木', 丙: '火', 丁: '火', 戊: '土', 己: '土', 庚: '金', 辛: '金', 壬: '水', 癸: '水' };
  const zyz = { 子: '阳', 丑: '阴', 寅: '阳', 卯: '阴', 辰: '阳', 巳: '阴', 午: '阳', 未: '阴', 申: '阳', 酉: '阴', 戌: '阳', 亥: '阴' };
  const zwx = { 子: '水', 丑: '土', 寅: '木', 卯: '木', 辰: '土', 巳: '火', 午: '火', 未: '土', 申: '金', 酉: '金', 戌: '土', 亥: '水' };

  const gLines = GAN.map((g) => `${g}：五行属${wx[g]}，${yz[g]}。`);
  const zLines = ZHI.map((z) => `${z}：五行属${zwx[z]}，${zyz[z]}。`);
  out.push(['lunar-天干地支属性.txt', '十天干、十二地支属性', [...gLines, '', ...zLines].join('\n')]);

  // 藏干：用八字 API 反查每个地支（取日支）
  const hideLines = [];
  for (const z of ZHI) {
    // 构造一个日支为该支的日期：用 1900 起的连续日反查
    for (let d = 1; d <= 400; d++) {
      const s = L.Solar.fromYmdHms(2024, 1, 1, 12, 0, 0).next(d - 1);
      const lu = s.getLunar();
      if (lu.getDayZhi() === z) {
        const ec = lu.getEightChar();
        hideLines.push(`${z}藏干：${ec.getDayHideGan().join('、')}。`);
        records.push({ category: '地支藏干', term: z, text: `${z}的藏干为${ec.getDayHideGan().join('、')}。` });
        break;
      }
    }
  }
  out.push(['lunar-地支藏干.txt', '十二地支藏干', hideLines.join('\n')]);
}

// ---------- 4. 十神 ----------
{
  const shen = ['比肩', '劫财', '食神', '伤官', '偏财', '正财', '七杀', '正官', '偏印', '正印'];
  const lines = shen.map((s) => `${s}：八字十神之一（以日主为我，与它干五行的生克关系定名）。`);
  // 用 API 实测一组，作为关系示例
  const ec = L.Solar.fromYmdHms(1990, 5, 20, 14, 30, 0).getLunar().getEightChar();
  lines.push('', '示例（1990-05-20 14:30，日主乙木）：');
  lines.push(`  年干十神：${ec.getYearShiShenGan()}；月干：${ec.getMonthShiShenGan()}；时干：${ec.getTimeShiShenGan()}`);
  lines.push(`  年支藏干十神：${ec.getYearShiShenZhi().join('、')}`);
  out.push(['lunar-十神.txt', '十神', lines.join('\n')]);
}

// ---------- 5. 黄历日课术语采样（宜忌/神煞/彭祖百忌/九星/二十八宿） ----------
{
  const lines = [];
  const lu = L.Solar.fromYmdHms(2024, 6, 1, 12, 0, 0).getLunar();
  lines.push(`宜：${lu.getDayYi().join('、')}`);
  lines.push(`忌：${lu.getDayJi().join('、')}`);
  lines.push(`彭祖百忌：${lu.getPengZuGan()} / ${lu.getPengZuZhi()}`);
  lines.push(`天神（日）：${lu.getDayTianShen()}，属${lu.getDayTianShenType()}（${lu.getDayTianShenLuck()}）`);
  lines.push(`九星：${lu.getDayNineStar().toString()}`);
  lines.push(`二十八宿：${lu.getXiu()}宿，${lu.getZheng()}，${lu.getAnimal()}，吉凶${lu.getXiuLuck()}`);
  out.push(['lunar-黄历日课术语.txt', '黄历日课术语（示例日）', lines.join('\n')]);
}

// ---------- 输出 ----------
for (const [fn, title, body] of out) {
  fs.writeFileSync(path.join(outDir, fn), `# ${title}\n# ${SRC}\n\n${body}\n`, 'utf8');
}
fs.writeFileSync(path.join(outDir, 'lunar-terms.jsonl'), records.map((r) => JSON.stringify(r)).join('\n') + '\n', 'utf8');

console.log('生成文件：');
for (const [fn] of out) console.log('  ' + fn);
console.log(`JSONL 记录数: ${records.length}`);
