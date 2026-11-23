# 语料来源与许可声明

本目录下的语料来自若干**开源项目**，均按其原始许可证使用。所有内容仅用于学习与研究。

第三方 npm 包的压缩包保存在 `vendor/oss/*.tgz`；为避免仓库膨胀，解压目录不再入库，使用前用 `tar -xzf` 解压即可。Sudo-Biao 与 ziwei-doushu 的原始源码保留在 `vendor/oss/`。

## 1. iztro — 紫微斗数排盘引擎

- 仓库：https://github.com/SylarLong/iztro
- 版本：2.6.2（经 npm 国内镜像 registry.npmmirror.com 获取）
- 许可证：**MIT**
- 使用的数据：
  - `lib/data/heavenlyStems.js` — 十天干：阴阳、五行、天干相冲、四化
  - `lib/data/earthlyBranches.js` — 十二地支：阴阳、五行、六冲、命主、身主、身体部位、健康提示
  - `lib/data/stars.js` — 星曜：庙旺利陷（按宫位地支）、五行、阴阳；四化定义
  - `lib/i18n/locales/zh-CN/*` — 中文术语对照（天干、地支、星曜、宫位、四化、亮度、时辰、生肖、星座）
- 产出：`data/terminology/iztro-*.txt`、`iztro-terms.jsonl`、`iztro-zh-terms-raw.json`
- 说明：已由 `src/acquire/extract-iztro.js` 将 JS 模块转为 RAG 友好的纯文本与 JSONL。

## 2. lunar-javascript — 农历 / 干支 / 节气 / 黄历

- 仓库：https://github.com/6tail/lunar-javascript
- 版本：1.7.7（经 npm 国内镜像获取）
- 许可证：**MIT**（Copyright (c) 2018 6tail）
- 另一并入版本：**lunar-typescript** 1.8.6（同作者，MIT）
- 使用的数据：六十甲子纳音、二十四节气、天干地支属性、十二地支藏干、十神、黄历日课术语（宜忌 / 神煞 / 彭祖百忌 / 九星 / 二十八宿）
- 产出：`data/terminology/lunar-*.txt`、`lunar-terms.jsonl`
- 说明：由 `src/acquire/extract-lunar.js` 生成。

## 3. bazi-terms — 八字术语词典

- 包：https://www.npmjs.com/package/bazi-terms
- 版本：0.1.0（经 npm 国内镜像获取）
- 许可证：**MIT**（作者 AskingMing）
- 产出：`data/terminology/bazi-terms-*.txt`、`bazi-terms.jsonl`、`bazi-terms-raw.json`
- 说明：由 `src/acquire/parse-bazi-terms.js` **以数据方式解析**（不执行该包代码）后生成。释义字段为英文。

## 4. Sudo-Biao/Chinese-Metaphysics-Platform — 命理知识讲义

- 仓库：https://github.com/Sudo-Biao/Chinese-Metaphysics-Platform
- 许可证：**MIT**（Copyright 2024-2026 Chinese Metaphysics Platform Contributors）
- 使用的数据：`knowledge/*.py` 共 23 个文件（八字、六爻、奇门、紫微、风水、择日、纳音、星宿等）
- 产出：`vendor/oss/sudo-biao-knowledge/`（原始 .py）与 `data/terminology/sudo-biao/`（转换后文本）
- 说明：由 `src/acquire/py_to_text.py` 用 `ast.parse` + `ast.literal_eval` **只读取字面量、不执行任何代码**后生成。
- 注意：内容为现代作者的归纳讲义（部分注明古籍出处），**不是古籍原文**，引用时应加以区分。

## 5. Renhuai123/ziwei-doushu — 紫微斗数古籍与格局库

- 仓库：https://github.com/Renhuai123/ziwei-doushu
- 许可证：仓库声明代码 **MIT**、数据集 **CC BY 4.0**（本次因 CDN 限制未能直接取到 LICENSE 原文，属二手确认，使用前建议自行核对）
- 使用的数据：`lib/classics/data/{gusufu,quanji,quanshu}.ts`（紫微斗数古籍原文）、`lib/ziwei/patterns.ts`（格局库）、`heming-knowledge.ts`、`constants.ts`、`sihua.ts`、`algorithm.ts`
- 产出：`vendor/oss/ziwei-doushu/`（原始 .ts，未做文本转换）
- 注意：`patterns.ts` 等文件混入现代讲师观点，**非纯古籍**；仓库同名的 51.8 万条命盘数据集位于 GitHub Releases，本次未能获取。

## 6. 殆知阁（daizhige.org）— 术数类古籍全文

- 站点：https://daizhige.org/
- 内容：`01-classics/术数/` 共 155 部古籍全文，抓取范围为「易藏 > 术数」类目
- 合规依据：该站 `robots.txt` 为 `User-agent: * / Allow: /`（仅 `Disallow: /jiaocheng/`、`/kuaixun/`），抓取路径均在允许范围内；无登录、无付费墙
- 原始文献均属**公有领域**（多为明清及更早刊本）
- 说明：由 `src/acquire/fetch-daizhige.js` 顺序抓取（间隔 1.2 秒），正文抽取自 `<div class="markdown-content">`，并已剥离站点附加的元数据尾注
- 使用范围：标点组 16 部、无标点组 29 部，以及 2026-11-22 补录的相术组 10 部（公笃相法、柳庄相法、神相全编、鬼谷子神奇相法全书、神相铁关刀、月波洞中记、永乐百问、冰鉴、许负相法、心相篇）均出自这一批「术数」类目

## 7. wt38.com — 《神相全編》卷八（手相）单卷转写

- 页面：http://www.wt38.com/to04/to04-12-08.htm （标题「神相全篇卷八」）
- 取用日期：2026-11-22
- 内容：`data/clean_text/11_相术/神相全編·卷八.txt`，即《神相全編》卷八手相部分：論手、玉掌圖（图题）、四季紋与约 70 种掌纹诗、相手、許負相手篇、論掌紋、論手背紋、玉掌記、相掌善惡、合相格/破相格、根基所屬、相指掌/骨肉/三才/氣色/爪/足/四肢/毛等
- 合规依据：页面为无登录、无付费墙的普通转写页，`robots.txt` 未禁止该路径；底层文本属**公有领域**（《神相全編》为明清相书汇编，通行本见《古今圖書集成》藝術典卷 640 及《新刻統會諸家風鑑全像人相全編》）
- 为什么单独收：既有 10 部相书没有掌纹专卷，「金井紋」「玉階紋」「鴈陣紋」「玉柱紋」「川字紋」「三才紋」等在手相界面里查不到原文；该卷补的正是这一块
- 处理说明（`D:\tmp\palm_src\clean_palm.py`，逐条可核对）：
  - 原页为 cp950 编码，`big5` 解码在 0xF9D8（裏）等字节失败，改用 `cp950` 且 `errors="replace"`；三处受影响字（姮娥月裏頻相約、綺羅叢裏貪歡樂、黑子手裏）已按上下文恢复，仅一处 «軟纖??» 依同诗通行本作「軟纖纖」（WebSearch 核对「貴人十指軟纖纖，不但清閑福自添」）
  - 去掉页面标题与重复目录、去掉「[图]」占位；被字体 span 打断的四个断行（四直、三角眼、棺材紋、火字紋）接回原句
  - 页内转写错误「金（花印）紋」按该页目录改为「金花印紋」；除此之外不改字、不补句
  - **保留繁体**（与柳庄相法等一致），未做繁简转换
- 未采用的来源：識典古籍（shidianguji.com）`robots.txt` 为 `Disallow: /`，不抓

## 8. shunshi-kangxi-core / shunshi-naming-core — 姓名测算的字库与五格表


- 包：https://www.npmjs.com/package/shunshi-kangxi-core（0.1.1）、https://www.npmjs.com/package/shunshi-naming-core（0.1.0）
- 许可证：**MIT**（Copyright (c) 2026 Shunshi.AI，https://shunshi.ai）
- 使用的数据：康熙笔画、字义五行、部首、拼音、字形结构（20,794 字，含异体字别名）；八十一数理、三才 125 组合与三大运势（基础运 / 成功运 / 社交运）表
- 产出：`src/fortune/data/*.json.gz`，许可原文见同目录 `LICENSE-shunshi-kangxi-core.txt`、`LICENSE-shunshi-naming-core.txt`
- 说明：由 `src/acquire/` 之外的构建步骤把 npm 包内的 JSON 压缩后入库，随 API 镜像发布；**不进入 RAG 语料**，也不参与检索
- 注意：五格剖象是熊崎健翁 1928 年整理的**现代数理体系**，不是中国古代古籍。界面与解读中一律表述为「这套体系的说法」，不得冒充「古书云」

## 使用与再分发注意

- MIT 许可证要求**保留版权声明与许可声明**。若把上述派生文本用于发布或再分发，请一并保留本文件。
- 这些语料是**算法与术语表**，不是古籍原文；引用具体命理断语时不应把程序常量当作古籍出处。
- 本目录**不包含**任何付费内容、VIP 资源，也未绕过任何站点的访问限制。
