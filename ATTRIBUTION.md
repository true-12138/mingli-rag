# 语料来源与许可声明

本目录下的语料来自若干**开源项目**，均按其原始许可证使用。所有内容仅用于学习与研究。

## 1. iztro — 紫微斗数排盘引擎

- 仓库：https://github.com/SylarLong/iztro
- 版本：2.6.2（经 npm 国内镜像 registry.npmmirror.com 获取）
- 许可证：**MIT**
- 使用的数据：
  - `lib/data/heavenlyStems.js` — 十天干：阴阳、五行、天干相冲、四化
  - `lib/data/earthlyBranches.js` — 十二地支：阴阳、五行、六冲、命主、身主、身体部位、健康提示
  - `lib/data/stars.js` — 星曜：庙旺利陷（按宫位地支）、五行、阴阳；四化定义
  - `lib/i18n/locales/zh-CN/*` — 中文术语对照（天干、地支、星曜、宫位、四化、亮度、时辰、生肖、星座）
- 产出：`03-terminology/iztro-*.txt`、`iztro-terms.jsonl`、`iztro-zh-terms-raw.json`
- 说明：已由 `_scripts/extract-iztro.js` 将 JS 模块转为 RAG 友好的纯文本与 JSONL。

## 2. lunar-javascript — 农历 / 干支 / 节气 / 黄历

- 仓库：https://github.com/6tail/lunar-javascript
- 版本：1.7.7（经 npm 国内镜像获取）
- 许可证：**MIT**（Copyright (c) 2018 6tail）
- 另一并入版本：**lunar-typescript** 1.8.6（同作者，MIT）
- 使用的数据：六十甲子纳音、二十四节气、天干地支属性、十二地支藏干、十神、黄历日课术语（宜忌 / 神煞 / 彭祖百忌 / 九星 / 二十八宿）
- 产出：`03-terminology/lunar-*.txt`、`lunar-terms.jsonl`
- 说明：由 `_scripts/extract-lunar.js` 生成。

## 3. bazi-terms — 八字术语词典

- 包：https://www.npmjs.com/package/bazi-terms
- 版本：0.1.0（经 npm 国内镜像获取）
- 许可证：**MIT**（作者 AskingMing）
- 产出：`03-terminology/bazi-terms-*.txt`、`bazi-terms.jsonl`、`bazi-terms-raw.json`
- 说明：由 `_scripts/parse-bazi-terms.js` **以数据方式解析**（不执行该包代码）后生成。释义字段为英文。

## 4. Sudo-Biao/Chinese-Metaphysics-Platform — 命理知识讲义

- 仓库：https://github.com/Sudo-Biao/Chinese-Metaphysics-Platform
- 许可证：**MIT**（Copyright 2024-2026 Chinese Metaphysics Platform Contributors）
- 使用的数据：`knowledge/*.py` 共 23 个文件（八字、六爻、奇门、紫微、风水、择日、纳音、星宿等）
- 产出：`02-oss-code/sudo-biao-knowledge/`（原始 .py）与 `03-terminology/sudo-biao/`（转换后文本）
- 说明：由 `_scripts/py_to_text.py` 用 `ast.parse` + `ast.literal_eval` **只读取字面量、不执行任何代码**后生成。
- 注意：内容为现代作者的归纳讲义（部分注明古籍出处），**不是古籍原文**，引用时应加以区分。

## 5. Renhuai123/ziwei-doushu — 紫微斗数古籍与格局库

- 仓库：https://github.com/Renhuai123/ziwei-doushu
- 许可证：仓库声明代码 **MIT**、数据集 **CC BY 4.0**（本次因 CDN 限制未能直接取到 LICENSE 原文，属二手确认，使用前建议自行核对）
- 使用的数据：`lib/classics/data/{gusufu,quanji,quanshu}.ts`（紫微斗数古籍原文）、`lib/ziwei/patterns.ts`（格局库）、`heming-knowledge.ts`、`constants.ts`、`sihua.ts`、`algorithm.ts`
- 产出：`02-oss-code/ziwei-doushu/`（原始 .ts，未做文本转换）
- 注意：`patterns.ts` 等文件混入现代讲师观点，**非纯古籍**；仓库同名的 51.8 万条命盘数据集位于 GitHub Releases，本次未能获取。

## 6. 殆知阁（daizhige.org）— 术数类古籍全文

- 站点：https://daizhige.org/
- 内容：`01-classics/术数/` 共 155 部古籍全文，抓取范围为「易藏 > 术数」类目
- 合规依据：该站 `robots.txt` 为 `User-agent: * / Allow: /`（仅 `Disallow: /jiaocheng/`、`/kuaixun/`），抓取路径均在允许范围内；无登录、无付费墙
- 原始文献均属**公有领域**（多为明清及更早刊本）
- 说明：由 `_scripts/fetch-daizhige.js` 顺序抓取（间隔 1.2 秒），正文抽取自 `<div class="markdown-content">`，并已剥离站点附加的元数据尾注

## 使用与再分发注意

- MIT 许可证要求**保留版权声明与许可声明**。若把上述派生文本用于发布或再分发，请一并保留本文件。
- 这些语料是**算法与术语表**，不是古籍原文；引用具体命理断语时不应把程序常量当作古籍出处。
- 本目录**不包含**任何付费内容、VIP 资源，也未绕过任何站点的访问限制。
