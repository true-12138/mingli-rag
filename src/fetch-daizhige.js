#!/usr/bin/env node
/**
 * 从 殆知阁 (https://daizhige.org) 抓取「易藏 > 术数」类目下的古籍全文，
 * 转为纯文本。
 *
 * 依据：
 *   - 该站 robots.txt: User-agent:* Allow:/ (仅 Disallow /jiaocheng/ /kuaixun/)
 *   - 抓取路径均为 /易藏/术数/*.html，robots 允许
 *   - 无需登录、无付费墙；原文均为公有领域古籍
 * 行为：
 *   - 顺序抓取，每次请求间隔 DELAY_MS，避免给站点压力
 *   - 正文取自 <div class="markdown-content">
 *
 * 用法: node fetch-daizhige.js <url列表文件> <输出根目录> [--limit=N]
 */
'use strict';
const fs = require('fs');
const path = require('path');

const listFile = path.resolve(process.argv[2]);
const outRoot = path.resolve(process.argv[3]);
const limitArg = process.argv.find((a) => a.startsWith('--limit='));
const LIMIT = limitArg ? parseInt(limitArg.split('=')[1], 10) : Infinity;

const DELAY_MS = 1200;
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36 (research-corpus; polite crawler)';

const textDir = path.join(outRoot, '术数');
const rawDir = path.join(outRoot, '_raw', '术数');
fs.mkdirSync(textDir, { recursive: true });
fs.mkdirSync(rawDir, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function decodeEntities(s) {
  return s
    .replace(/&nbsp;/g, ' ')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&');
}

function extractText(html) {
  const m = html.match(/<div class="markdown-content">([\s\S]*?)<\/div>\s*<\/div>/);
  if (!m) return null;
  let t = m[1]
    .replace(/<script[\s\S]*?<\/script>/g, '')
    .replace(/<br\s*\/?>/g, '\n')
    .replace(/<\/(p|div|h[1-6]|li|tr)>/g, '\n')
    .replace(/<[^>]+>/g, '');
  t = decodeEntities(t);
  // 去掉正文末尾殆知阁附加的「标题：…作者：…附加信息：…」元数据段
  t = t.replace(/\n*\s*标题：[\s\S]*$/m, '');
  t = t.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  return t;
}

function safeName(u) {
  const last = decodeURIComponent(u.split('/').pop().replace(/\.html$/, ''));
  return last.replace(/[\\/:*?"<>|]/g, '_').trim();
}

(async () => {
  const urls = fs
    .readFileSync(listFile, 'utf8')
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter((s) => s.endsWith('.html'));

  console.log(`待抓取: ${urls.length} 部`);
  const manifest = [];
  let ok = 0, fail = 0;

  for (const [i, url] of urls.entries()) {
    if (i >= LIMIT) { console.log(`达到 limit=${LIMIT}，停止`); break; }
    const name = safeName(url);
    const rawPath = path.join(rawDir, `${name}.html`);
    const txtPath = path.join(textDir, `${name}.txt`);

    try {
      const res = await fetch(url, { headers: { 'User-Agent': UA } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const html = await res.text();
      fs.writeFileSync(rawPath, html, 'utf8');

      const text = extractText(html);
      if (!text || text.length < 50) throw new Error('正文抽取失败');

      fs.writeFileSync(txtPath, `# ${name}\n# 来源：殆知阁 https://daizhige.org （易藏 > 术数）\n# ${url}\n\n${text}\n`, 'utf8');
      manifest.push({ title: name, url, chars: text.length, file: `术数/${name}.txt` });
      ok++;
      console.log(`[${i + 1}/${urls.length}] OK  ${name}  ${text.length} 字`);
    } catch (e) {
      fail++;
      console.log(`[${i + 1}/${urls.length}] FAIL ${name}  ${e.message}`);
      manifest.push({ title: name, url, error: e.message });
    }
    await sleep(DELAY_MS);
  }

  const mf = path.join(outRoot, '术数-manifest.json');
  fs.writeFileSync(mf, JSON.stringify(manifest, null, 2), 'utf8');
  console.log(`\n完成: 成功 ${ok} / 失败 ${fail}；manifest -> ${mf}`);
})();
