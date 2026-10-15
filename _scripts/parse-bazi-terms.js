#!/usr/bin/env node
/**
 * 把 bazi-terms (MIT) 的打包产物当「数据」解析，而不是执行它。
 *
 * 做法：取出 `var NAME = <literal>;` 里的字面量文本，做最小规范化后交给 JSON.parse。
 * 字面量只含 字符串/数字/数组/对象/布尔，不含函数调用，故可安全地当作数据解析。
 *
 * 用法: node parse-bazi-terms.js <bazi-terms解压目录> <输出目录>
 */
'use strict';
const fs = require('fs');
const path = require('path');

const pkgDir = path.resolve(process.argv[2]);
const outDir = path.resolve(process.argv[3]);
fs.mkdirSync(outDir, { recursive: true });

const src = fs.readFileSync(path.join(pkgDir, 'dist', 'index.js'), 'utf8');

// 抽取顶层 `var NAME = [...];` / `{...};` 块
function grabBlocks(text) {
  const out = {};
  const re = /^var ([A-Z_]+) = (\[|\{)/gm;
  let m;
  while ((m = re.exec(text))) {
    const name = m[1];
    const start = text.indexOf(m[2], m.index + m[0].length - 1);
    // 从起始括号起做括号配对，跳过字符串内的括号
    let depth = 0, i = start, inStr = false, q = '';
    for (; i < text.length; i++) {
      const c = text[i];
      if (inStr) {
        if (c === '\\') { i++; continue; }
        if (c === q) inStr = false;
        continue;
      }
      if (c === '"' || c === "'" || c === '`') { inStr = true; q = c; continue; }
      if (c === '[' || c === '{') depth++;
      else if (c === ']' || c === '}') { depth--; if (depth === 0) { i++; break; } }
    }
    out[name] = text.slice(start, i);
  }
  return out;
}

// 最小规范化 -> JSON
function toJson(literal) {
  let s = literal;
  s = s.replace(/\/\*[\s\S]*?\*\//g, '');           // 块注释
  s = s.replace(/^\s*\/\/[^\n]*$/gm, '');           // 行注释
  s = s.replace(/([{,[])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:/g, '$1"$2":'); // 裸键加引号
  s = s.replace(/'((?:[^'\\]|\\.)*)'/g, (_, inner) => JSON.stringify(inner.replace(/\\'/g, "'"))); // 单引号串
  s = s.replace(/\\x([0-9A-Fa-f]{2})/g, '\\u00$1'); // JS \xHH 转义 -> JSON \u00HH
  s = s.replace(/,(\s*[\]}])/g, '$1');               // 尾逗号
  return JSON.parse(s);
}

const blocks = grabBlocks(src);
const parsed = {};
const stats = [];
for (const [name, lit] of Object.entries(blocks)) {
  try {
    let v = toJson(lit);
    // 展开 \uXXXX 已被 JSON.parse 处理
    parsed[name] = v;
    stats.push([name, Array.isArray(v) ? `${v.length} 条` : `${Object.keys(v).length} 键`]);
  } catch (e) {
    stats.push([name, `解析失败: ${e.message}`]);
  }
}

// ---- 产出：术语 JSONL（只取带中文的条目） ----
const records = [];
const pushArr = (arr, category) => {
  for (const o of arr || []) {
    if (!o || typeof o !== 'object') continue;
    const zh = o.zh || o.name_zh;
    if (!zh) continue;
    const bits = [];
    if (o.en) bits.push(o.en);
    if (o.pinyin) bits.push(`拼音 ${o.pinyin}`);
    if (o.element) bits.push(`五行 ${o.element}`);
    if (o.polarity) bits.push(`阴阳 ${o.polarity}`);
    if (o.definition) bits.push(o.definition);
    records.push({ category, term: zh, text: `${zh}${bits.length ? '：' + bits.join('；') : ''}` });
  }
};
pushArr(parsed.STEMS, '天干');
pushArr(parsed.BRANCHES, '地支');
pushArr(parsed.ELEMENTS, '五行');
pushArr(parsed.TEN_GODS, '十神');
pushArr(parsed.GROWTH_STAGES, '十二长生');
pushArr(parsed.SHEN_SHA, '神煞');
pushArr(parsed.NA_YIN, '纳音');
pushArr(parsed.GENERAL_TERMS, '通用术语');
pushArr(parsed.INTERACTION_TYPES, '刑冲合会');

fs.writeFileSync(path.join(outDir, 'bazi-terms.jsonl'),
  records.map((r) => JSON.stringify(r)).join('\n') + '\n', 'utf8');

// 分门别类 txt
const byCat = {};
for (const r of records) (byCat[r.category] ||= []).push(r);
for (const [cat, rs] of Object.entries(byCat)) {
  fs.writeFileSync(path.join(outDir, `bazi-terms-${cat}.txt`),
    `# ${cat}（数据来源：bazi-terms，MIT License）\n\n` +
    rs.map((r) => r.text).join('\n') + '\n', 'utf8');
}

// 全量原始数据
fs.writeFileSync(path.join(outDir, 'bazi-terms-raw.json'), JSON.stringify(parsed, null, 2), 'utf8');

console.log('解析结果：');
for (const [n, s] of stats) console.log('  ' + n.padEnd(22) + s);
console.log(`\n术语记录: ${records.length}`);
for (const [c, rs] of Object.entries(byCat)) console.log(`  ${c}: ${rs.length}`);
