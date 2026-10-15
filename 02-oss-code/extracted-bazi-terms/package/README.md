# bazi-terms

> Bilingual (中文 / English) terminology database for Bazi / Four Pillars of Destiny (八字·四柱). Zero dependencies, framework-agnostic. Part of [BaziKit](../../README.md).

Every concept a Bazi chart uses — Heavenly Stems, Earthly Branches, Ten Gods, Shen Sha, Na Yin, Growth Stages, interactions and general chart vocabulary — as structured, translated data you can drop into any app, blog glossary or i18n layer.

## Install

```bash
npm install bazi-terms
```

ESM + CJS builds with full TypeScript declarations.

## Coverage

| Category | Export | Size |
| --- | --- | --- |
| Ten Heavenly Stems 天干 | `STEMS` | 10 |
| Twelve Earthly Branches 地支 | `BRANCHES` | 12 |
| Five Elements 五行 (+ generating/controlling cycles) | `ELEMENTS`, `ELEMENT_CYCLES` | 5 |
| Ten Gods 十神 (+ Day Master) | `TEN_GODS` | 11 |
| Twelve Growth Stages 十二长生 | `GROWTH_STAGES` | 12 |
| Shen Sha 神煞 (symbolic stars) | `SHEN_SHA` | 38 |
| Sixty Jiazi Na Yin 六十甲子纳音 | `NA_YIN` | 30 melodies / 60 pairs |
| Interactions 刑冲合会 (+ pairing tables) | `INTERACTION_TYPES` | 8 |
| General vocabulary 通用术语 | `GENERAL_TERMS` | 40+ |

Each term carries `key`, `zh`, `en`, optional `pinyin` and an English `definition` you can copy straight into a glossary or tooltip.

## API

### Translation helpers

```ts
import { t, translate, ALL_TERMS, TERM_BY_KEY } from 'bazi-terms';

t('dayMaster');          // 'Day Master'   — translate a term KEY
t('dayMaster', 'zh');    // '日主'

// translate() accepts a key OR any raw engine value (Chinese / English key),
// resolving aliases, Na Yin pairs and interaction descriptions:
translate('元男');        // 'Day Master'      (元男/元女/日元 → Day Master)
translate('偏官');        // 'Seven Killings'  (alias of 七杀)
translate('枭神');        // 'Indirect Resource'
translate('海中金');       // 'Sea Gold'
translate('甲子');        // 'Sea Gold'        (Na Yin by sexagenary pair)
translate('午子相冲');     // 'Clash'           (Chinese description)
translate('metal', 'zh'); // '金'
```

`translate()` never throws — unknown input is returned unchanged, so it is safe to pipe raw engine output through it.

### Category resolvers

```ts
import {
  stemByChar, branchByChar, elementOf,
  tenGodByZh, growthStageByZh, shenShaByZh, naYinOf,
  interactionFromZh, interactionFromEnum,
} from 'bazi-terms';

stemByChar('庚');              // { key: 'geng', element: 'metal', polarity: 'yang', ... }
branchByChar('午');            // { key: 'wuHorse', zodiacEn: 'Horse', element: 'fire', ... }
elementOf('金');               // { key: 'metal', ... }   (accepts '金' or 'metal')
tenGodByZh('正财');            // { key: 'zhengCai', en: 'Direct Wealth', ... }
naYinOf('甲子');               // { key: 'seaGold', en: 'Sea Gold', pairs: ['甲子','乙丑'] }
shenShaByZh('天乙贵人');        // { key: 'tianYiGuiRen', en: 'Heavenly Nobleman', ... }
growthStageByZh('帝旺');        // { key: 'peak', en: 'Peak', ... }

// Interaction resolvers accept either representation:
interactionFromZh('卯子相刑');         // Chinese description → { key: 'xiangXing', en: 'Punishment' }
interactionFromEnum('CLASH');         // English enum        → { key: 'liuChong',   en: 'Clash' }
```

### Pairing tables

Reference data for validating or reconstructing relationships from raw branch characters:

```ts
import {
  STEM_COMBINATIONS, LIU_HE, LIU_CHONG, SAN_HE, SAN_HUI,
  XIANG_HAI, XIANG_PO, XIANG_XING,
} from 'bazi-terms';

LIU_CHONG;  // [['子','午'], ['丑','未'], ['寅','申'], ['卯','酉'], ['辰','戌'], ['巳','亥']]
SAN_HE;     // [['申','子','辰'], ['亥','卯','未'], ['寅','午','戌'], ['巳','酉','丑']]
```

## Engine compatibility

Most Bazi engines emit **Chinese values** for ten gods, Na Yin, growth stages and Shen Sha — even those whose field *names* are English. So a single `zh → key` mapping serves them all. Where engines differ (some use `元男` for the Day Master; others use interaction enums like `CLASH`), `bazi-terms` normalizes them through aliases and dedicated resolvers (`interactionFromZh` for Chinese descriptions, `interactionFromEnum` for English enums).

## License

[MIT](./LICENSE) © 2026 [AskingMing](https://askingming.com).
