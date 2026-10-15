/** Supported output languages. */
type Lang = 'zh' | 'en';
/** A single bilingual terminology entry. */
interface Term {
    /** Stable machine-readable identifier (camelCase pinyin or English). */
    key: string;
    /** Chinese name. */
    zh: string;
    /** English name. */
    en: string;
    /** Pinyin with tone marks (optional). */
    pinyin?: string;
    /** One-sentence English definition — what a blog author can copy-paste. */
    definition?: string;
}
type StemKey = 'jia' | 'yi' | 'bing' | 'ding' | 'wu' | 'ji' | 'geng' | 'xin' | 'ren' | 'gui';
type BranchKey = 'zi' | 'chou' | 'yin' | 'mao' | 'chen' | 'si' | 'wuHorse' | 'wei' | 'shen' | 'you' | 'xu' | 'hai';
type ElementKey = 'wood' | 'fire' | 'earth' | 'metal' | 'water';
type Polarity = 'yang' | 'yin';
type TenGodKey = 'biJian' | 'jieCai' | 'shiShen' | 'shangGuan' | 'pianCai' | 'zhengCai' | 'qiSha' | 'zhengGuan' | 'pianYin' | 'zhengYin' | 'dayMaster';
type GrowthStageKey = 'birth' | 'bathing' | 'crowning' | 'officiating' | 'peak' | 'decline' | 'illness' | 'death' | 'tomb' | 'extinction' | 'gestation' | 'nurturing';
type InteractionTypeKey = 'stemCombination' | 'liuHe' | 'sanHe' | 'sanHui' | 'liuChong' | 'xiangXing' | 'xiangHai' | 'xiangPo';
/** Stem term enriched with element and polarity. */
interface StemTerm extends Term {
    key: StemKey;
    element: ElementKey;
    polarity: Polarity;
}
/** Branch term enriched with zodiac animal, element and clock hours. */
interface BranchTerm extends Term {
    key: BranchKey;
    zodiacEn: string;
    zodiacZh: string;
    element: ElementKey;
    /** Representative clock hour range, e.g. "23:00-01:00". */
    hours: string;
}

/**
 * The Ten Heavenly Stems (十天干).
 * Order matters: index is used for combination/clash arithmetic.
 */
declare const STEMS: readonly StemTerm[];
/** Lookup: Chinese character → stem term. */
declare const STEM_BY_CHAR: Readonly<Record<string, StemTerm>>;
/** Lookup: key → stem term. */
declare const STEM_BY_KEY: Readonly<Record<string, StemTerm>>;
/**
 * Resolve a Heavenly Stem from a Chinese character.
 * Returns undefined for unknown characters instead of throwing,
 * so callers can render raw data defensively.
 */
declare function stemByChar(char: string): StemTerm | undefined;

/**
 * The Twelve Earthly Branches (十二地支).
 * Order matters: index is used for clash/combination arithmetic.
 * Note: the key for 午 (Horse) is 'wuHorse' to avoid colliding with stem 戊 (wu).
 */
declare const BRANCHES: readonly BranchTerm[];
/** Lookup: Chinese character → branch term. */
declare const BRANCH_BY_CHAR: Readonly<Record<string, BranchTerm>>;
/** Lookup: key → branch term. */
declare const BRANCH_BY_KEY: Readonly<Record<string, BranchTerm>>;
/** Resolve an Earthly Branch from a Chinese character. */
declare function branchByChar(char: string): BranchTerm | undefined;

interface ElementTerm extends Term {
    key: ElementKey;
}
/** The Five Elements (五行). */
declare const ELEMENTS: readonly ElementTerm[];
/** Lookup: Chinese character → element term. */
declare const ELEMENT_BY_CHAR: Readonly<Record<string, ElementTerm>>;
/** Lookup: key → element term. */
declare const ELEMENT_BY_KEY: Readonly<Record<string, ElementTerm>>;
/** Resolve a Five Element from a Chinese character or an English key. */
declare function elementOf(input: string): ElementTerm | undefined;
/**
 * The generating (生) and controlling (克) cycles, as key pairs.
 * generating: Wood→Fire→Earth→Metal→Water→Wood
 * controlling: Wood→Earth→Water→Fire→Metal→Wood
 */
declare const ELEMENT_CYCLES: {
    readonly generating: [ElementKey, ElementKey][];
    readonly controlling: [ElementKey, ElementKey][];
};

interface TenGodTerm extends Term {
    key: TenGodKey;
}
/**
 * The Ten Gods (十神) — relationship labels between each stem
 * and the Day Master, based on element and polarity.
 * Plus the Day Master itself, which engines emit as 日主 / 元男 / 元女.
 */
declare const TEN_GODS: readonly TenGodTerm[];
/** Lookup: key → ten-god term. */
declare const TEN_GOD_BY_KEY: Readonly<Record<string, TenGodTerm>>;
/** Resolve a Ten God from its Chinese label (aliases included). */
declare function tenGodByZh(zh: string): TenGodTerm | undefined;

interface GrowthStageTerm extends Term {
    key: GrowthStageKey;
}
/**
 * The Twelve Growth Stages (十二长生) — the lifecycle of an element
 * across the twelve branches: birth → bathing → … → extinction → gestation → nurturing.
 */
declare const GROWTH_STAGES: readonly GrowthStageTerm[];
/** Lookup: key → growth-stage term. */
declare const GROWTH_STAGE_BY_KEY: Readonly<Record<string, GrowthStageTerm>>;
/** Lookup: Chinese label → growth-stage term. */
declare const GROWTH_STAGE_BY_ZH: Readonly<Record<string, GrowthStageTerm>>;
/** Resolve a growth stage from its Chinese label. */
declare function growthStageByZh(zh: string): GrowthStageTerm | undefined;

/**
 * Common Shen Sha (神煞) — symbolic stars overlaid on the chart.
 * Coverage: the stars emitted by common community Bazi engines’ golden
 * samples, plus the most frequently referenced traditional stars.
 * Lookup falls back to the raw Chinese name for stars not in this table,
 * so unknown engine output never breaks rendering.
 */
declare const SHEN_SHA: readonly Term[];
/** Lookup: Chinese name → shen sha term. */
declare const SHEN_SHA_BY_ZH: Readonly<Record<string, Term>>;
/** Lookup: key → shen sha term. */
declare const SHEN_SHA_BY_KEY: Readonly<Record<string, Term>>;
/**
 * Resolve a Shen Sha star from its Chinese name.
 * Unknown stars return undefined — render the raw name instead of dropping data.
 */
declare function shenShaByZh(zh: string): Term | undefined;

interface NaYinTerm extends Term {
    /** The two sexagenary pairs this melody covers, e.g. ['甲子', '乙丑']. */
    pairs: [string, string];
}
/**
 * The Sixty Jiazi Na Yin (六十甲子纳音) — 30 melodic elements,
 * each covering two consecutive sexagenary cycle entries.
 */
declare const NA_YIN: readonly NaYinTerm[];
/** Lookup: Na Yin Chinese name → term. */
declare const NA_YIN_BY_ZH: Readonly<Record<string, NaYinTerm>>;
/** Lookup: sexagenary pair (e.g. '甲子') → Na Yin term. */
declare const NA_YIN_BY_GAN_ZHI: Readonly<Record<string, NaYinTerm>>;
/** Resolve a Na Yin melody from its Chinese name or a sexagenary pair. */
declare function naYinOf(input: string): NaYinTerm | undefined;

interface InteractionTerm extends Term {
    key: InteractionTypeKey;
    /** English interaction enum value (CLASH, TRINE, …), when one exists. */
    enumCode?: string;
    /** The Chinese verb embedded in description strings like "午子相冲". */
    zhVerb?: string;
}
/**
 * Chart interactions (刑冲合会) — the relationships between stems and branches.
 * Each entry carries two optional lookup codes:
 *   - an English `type` enum (CLASH, TRINE, …) used by enum-style engines
 *   - a Chinese verb embedded in description strings ("午子相冲")
 * The pairing tables below let callers verify or reconstruct a relationship
 * from raw branch characters.
 */
declare const INTERACTION_TYPES: readonly InteractionTerm[];
/** Lookup: key → interaction term. */
declare const INTERACTION_BY_KEY: Readonly<Record<string, InteractionTerm>>;
/** Lookup: English interaction enum (CLASH/TRINE/…) → interaction term. */
declare const INTERACTION_BY_ENUM: Readonly<Record<string, InteractionTerm>>;
/**
 * Resolve an interaction type from a Chinese description string
 * such as "午子相冲" or "卯子相刑". Returns undefined when no verb matches.
 */
declare function interactionFromZh(desc: string): InteractionTerm | undefined;
/** Resolve an interaction type from an English enum value (CLASH, TRINE, …). */
declare function interactionFromEnum(type: string): InteractionTerm | undefined;
/** 天干五合 — the five Heavenly Stem combinations. */
declare const STEM_COMBINATIONS: readonly (readonly [string, string])[];
/** 地支六合 — the six branch harmonies. */
declare const LIU_HE: readonly (readonly [string, string])[];
/** 地支六冲 — the six branch clashes. */
declare const LIU_CHONG: readonly (readonly [string, string])[];
/** 地支三合 — the four three-harmony triads (each resolving to one element). */
declare const SAN_HE: readonly (readonly [string, string, string])[];
/** 地支三会 — the four directional (seasonal) triads. */
declare const SAN_HUI: readonly (readonly [string, string, string])[];
/** 地支相害 — the six branch harms. */
declare const XIANG_HAI: readonly (readonly [string, string])[];
/** 地支相破 — the six branch destructions. */
declare const XIANG_PO: readonly (readonly [string, string])[];
/**
 * 地支相刑 — the punishments, grouped by classic type:
 *   wuEn (无恩之刑) 寅巳申, shiShi (恃势之刑) 丑戌未,
 *   wuLi (无礼之刑) 子卯, and ziXing (自刑) 辰/午/酉/亥 (each with itself).
 */
declare const XIANG_XING: {
    readonly wuEn: readonly ["寅", "巳", "申"];
    readonly shiShi: readonly ["丑", "戌", "未"];
    readonly wuLi: readonly ["子", "卯"];
    readonly ziXing: readonly ["辰", "午", "酉", "亥"];
};

/**
 * General chart vocabulary — the structural labels a renderer needs:
 * pillar names, calendar/time terms, cycle concepts and section headers.
 * Category-specific terms (stems, branches, ten gods, shen sha, na yin,
 * growth stages, interactions) live in their own modules; this file holds
 * everything else so a UI can label a chart bilingually end-to-end.
 */
declare const GENERAL_TERMS: readonly Term[];
/** Lookup: key → general term. */
declare const GENERAL_BY_KEY: Readonly<Record<string, Term>>;
/** Lookup: Chinese label → general term. */
declare const GENERAL_BY_ZH: Readonly<Record<string, Term>>;
/** Resolve a general term by key. */
declare function generalBy(key: string): Term | undefined;
/** Resolve a general term by its Chinese label. */
declare function generalByZh(zh: string): Term | undefined;

/** Every term from every category, in a stable order. */
declare const ALL_TERMS: readonly Term[];
/** Lookup: unique term key → term. Keys are unique across all categories. */
declare const TERM_BY_KEY: Readonly<Record<string, Term>>;
/** Lookup: Chinese label → term (exact match). */
declare const TERM_BY_ZH: Readonly<Record<string, Term>>;
/**
 * Translate a term key into the requested language.
 * Returns the key itself when unknown, so rendering never breaks.
 *
 * @example t('dayMaster')        // 'Day Master'
 * @example t('dayMaster', 'zh')  // '日主'
 */
declare function t(key: string, lang?: Lang): string;
/**
 * Best-effort translation of any raw engine value or term key.
 * Resolution order (exact → fuzzy):
 *   1. term key            (e.g. 'qiSha')
 *   2. exact Chinese label (e.g. '天乙贵人', '海中金', '比肩')
 *   3. ten-god alias       (e.g. '元男' → Day Master, '偏官' → Seven Killings)
 *   4. Na Yin by GanZhi    (e.g. '甲子' → Sea Gold)
 *   5. interaction by verb (e.g. '午子相冲' → Clash)
 * Falls back to the original input when nothing matches.
 *
 * @example translate('元男')          // 'Day Master'
 * @example translate('午子相冲')       // 'Clash'
 * @example translate('甲子', 'zh')    // '海中金'
 */
declare function translate(input: string, lang?: Lang): string;

export { ALL_TERMS, BRANCHES, BRANCH_BY_CHAR, BRANCH_BY_KEY, type BranchKey, type BranchTerm, ELEMENTS, ELEMENT_BY_CHAR, ELEMENT_BY_KEY, ELEMENT_CYCLES, type ElementKey, type ElementTerm, GENERAL_BY_KEY, GENERAL_BY_ZH, GENERAL_TERMS, GROWTH_STAGES, GROWTH_STAGE_BY_KEY, GROWTH_STAGE_BY_ZH, type GrowthStageKey, type GrowthStageTerm, INTERACTION_BY_ENUM, INTERACTION_BY_KEY, INTERACTION_TYPES, type InteractionTerm, type InteractionTypeKey, LIU_CHONG, LIU_HE, type Lang, NA_YIN, NA_YIN_BY_GAN_ZHI, NA_YIN_BY_ZH, type NaYinTerm, type Polarity, SAN_HE, SAN_HUI, SHEN_SHA, SHEN_SHA_BY_KEY, SHEN_SHA_BY_ZH, STEMS, STEM_BY_CHAR, STEM_BY_KEY, STEM_COMBINATIONS, type StemKey, type StemTerm, TEN_GODS, TEN_GOD_BY_KEY, TERM_BY_KEY, TERM_BY_ZH, type TenGodKey, type TenGodTerm, type Term, XIANG_HAI, XIANG_PO, XIANG_XING, branchByChar, elementOf, generalBy, generalByZh, growthStageByZh, interactionFromEnum, interactionFromZh, naYinOf, shenShaByZh, stemByChar, t, tenGodByZh, translate };
