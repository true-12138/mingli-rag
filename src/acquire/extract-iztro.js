#!/usr/bin/env node
/**
 * 把 iztro (MIT, https://github.com/SylarLong/iztro) 的结构化数据
 * 转成 RAG 友好的纯文本 / JSONL。
 *
 * 用法: node extract-iztro.js <iztro解压目录> <输出目录>
 * 脚本位于 src/acquire/，不从被读取的目录内运行。
 */
'use strict';
const fs = require('fs');
const path = require('path');

const pkgDir = path.resolve(process.argv[2]);
const outDir = path.resolve(process.argv[3]);
fs.mkdirSync(outDir, { recursive: true });

const dataDir = path.join(pkgDir, 'lib', 'data');
const zhDir = path.join(pkgDir, 'lib', 'i18n', 'locales', 'zh-CN');

// 编译后的 CJS 模块，default 导出与命名导出都读一遍
function load(p) {
  const m = require(p);
  return m && m.default ? { ...m, ...m.default } : m;
}

const data = {
  stems: load(path.join(dataDir, 'heavenlyStems.js')).heavenlyStems,
  branches: load(path.join(dataDir, 'earthlyBranches.js')).earthlyBranches,
  stars: load(path.join(dataDir, 'stars.js')).STARS_INFO,
  mutagen: load(path.join(dataDir, 'stars.js')).MUTAGEN,
  constants: load(path.join(dataDir, 'constants.js')),
};
const zh = {
  stem: load(path.join(zhDir, 'heavenlyStem.js')),
  branch: load(path.join(zhDir, 'earthlyBranch.js')),
  star: load(path.join(zhDir, 'star.js')),
  brightness: load(path.join(zhDir, 'brightness.js')),
  palace: load(path.join(zhDir, 'palace.js')),
  mutagen: load(path.join(zhDir, 'mutagen.js')),
  common: JSON.parse(fs.readFileSync(path.join(zhDir, 'common.json'), 'utf8')),
};

const t = (dict, key) => (key && dict && dict[key]) || key || '';

const records = [];
const push = (o) => records.push(o);

// ---- 十天干 ----
for (const [key, v] of Object.entries(data.stems || {})) {
  const name = t(zh.stem, key);
  const sihua = Array.isArray(v.mutagen)
    ? v.mutagen.map((s, i) => `${t(zh.mutagen, data.mutagen[i])}：${t(zh.star, s)}`).join('，')
    : '';
  push({
    category: '天干',
    term: name,
    text:
      `${name}：五行属${v.fiveElements}，${v.yinYang}。` +
      (v.crash ? `相冲：${name}与${t(zh.stem, v.crash)}相冲。` : '') +
      (sihua ? `四化：${sihua}。` : ''),
  });
}

// ---- 十二地支 ----
for (const [key, v] of Object.entries(data.branches || {})) {
  const name = t(zh.branch, key);
  const parts = [`${name}：五行属${v.fiveElements}，${v.yinYang}。`];
  if (v.crash) parts.push(`六冲：${name}与${t(zh.branch, v.crash)}相冲。`);
  if (v.soul) parts.push(`命主：${t(zh.star, v.soul)}。`);
  if (v.body) parts.push(`身主：${t(zh.star, v.body)}。`);
  if (v.inside) parts.push(`身体部位（内）：${v.inside}。`);
  if (v.outside) parts.push(`身体部位（外）：${v.outside}。`);
  if (v.healthTip) parts.push(`健康提示：${v.healthTip}。`);
  push({ category: '地支', term: name, text: parts.join('') });
}

// ---- 星曜 ----
const BRIGHT_ORDER = ['寅', '卯', '辰', '巳', '午', '未', '申', '酉', '戌', '亥', '子', '丑'];
for (const [key, v] of Object.entries(data.stars || {})) {
  const name = t(zh.star, key);
  const parts = [`${name}：五行属${v.fiveElements}，${v.yinYang}。`];
  if (Array.isArray(v.brightness) && v.brightness.length === 12) {
    const b = v.brightness.map((x, i) => `${BRIGHT_ORDER[i]}${t(zh.brightness, x)}`).join('、');
    parts.push(`庙旺利陷（按宫位地支）：${b}。`);
  }
  push({ category: '星曜', term: name, text: parts.join('') });
}

// ---- 十二宫 / 四化 / 五行局 / 时辰等术语 ----
const gloss = [];
for (const [k, v] of Object.entries(zh.palace || {})) if (typeof v === 'string') gloss.push({ category: '十二宫', term: v, text: `紫微斗数十二宫之一：${v}。` });
for (const [k, v] of Object.entries(zh.mutagen || {})) if (typeof v === 'string') gloss.push({ category: '四化', term: v, text: `四化之一：${v}。` });
gloss.forEach(push);

// ---- 输出 ----
const jsonl = records.map((r) => JSON.stringify(r)).join('\n');
fs.writeFileSync(path.join(outDir, 'iztro-terms.jsonl'), jsonl + '\n', 'utf8');

// 分门别类的可读 txt，方便直接切块
const byCat = {};
for (const r of records) (byCat[r.category] ||= []).push(r);
for (const [cat, rs] of Object.entries(byCat)) {
  fs.writeFileSync(
    path.join(outDir, `iztro-${cat}.txt`),
    `# ${cat}（数据来源：iztro，MIT License，https://github.com/SylarLong/iztro）\n\n` +
      rs.map((r) => r.text).join('\n\n') + '\n',
    'utf8'
  );
}

// 原始中文词表全量导出，便于自行组装
fs.writeFileSync(
  path.join(outDir, 'iztro-zh-terms-raw.json'),
  JSON.stringify({ ...zh, brightOrder: BRIGHT_ORDER }, null, 2),
  'utf8'
);

console.log(`记录数: ${records.length}`);
for (const [c, rs] of Object.entries(byCat)) console.log(`  ${c}: ${rs.length}`);
