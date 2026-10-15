// src/data/stems.ts
var STEMS = [
  { key: "jia", zh: "\u7532", en: "Jia", pinyin: "ji\u01CE", element: "wood", polarity: "yang", definition: "Yang Wood \u2014 a towering tree; growth, initiative and uprightness." },
  { key: "yi", zh: "\u4E59", en: "Yi", pinyin: "y\u01D0", element: "wood", polarity: "yin", definition: "Yin Wood \u2014 flowering plants and vines; flexibility and adaptability." },
  { key: "bing", zh: "\u4E19", en: "Bing", pinyin: "b\u01D0ng", element: "fire", polarity: "yang", definition: "Yang Fire \u2014 the sun; brightness, generosity and visibility." },
  { key: "ding", zh: "\u4E01", en: "Ding", pinyin: "d\u012Bng", element: "fire", polarity: "yin", definition: "Yin Fire \u2014 a candle or lamp flame; focus, warmth and refinement." },
  { key: "wu", zh: "\u620A", en: "Wu", pinyin: "w\xF9", element: "earth", polarity: "yang", definition: "Yang Earth \u2014 a mountain or city wall; stability and reliability." },
  { key: "ji", zh: "\u5DF1", en: "Ji", pinyin: "j\u01D0", element: "earth", polarity: "yin", definition: "Yin Earth \u2014 garden soil; nourishment, patience and practicality." },
  { key: "geng", zh: "\u5E9A", en: "Geng", pinyin: "g\u0113ng", element: "metal", polarity: "yang", definition: "Yang Metal \u2014 a sword or axe; decisiveness, justice and resolve." },
  { key: "xin", zh: "\u8F9B", en: "Xin", pinyin: "x\u012Bn", element: "metal", polarity: "yin", definition: "Yin Metal \u2014 jewelry and fine ornaments; precision, elegance and sensitivity." },
  { key: "ren", zh: "\u58EC", en: "Ren", pinyin: "r\xE9n", element: "water", polarity: "yang", definition: "Yang Water \u2014 the ocean or a great river; movement, ambition and resourcefulness." },
  { key: "gui", zh: "\u7678", en: "Gui", pinyin: "gu\u01D0", element: "water", polarity: "yin", definition: "Yin Water \u2014 rain, dew and springs; intuition, gentleness and permeation." }
];
var STEM_BY_CHAR = Object.freeze(
  Object.fromEntries(STEMS.map((s) => [s.zh, s]))
);
var STEM_BY_KEY = Object.freeze(
  Object.fromEntries(STEMS.map((s) => [s.key, s]))
);
function stemByChar(char) {
  return STEM_BY_CHAR[char];
}

// src/data/branches.ts
var BRANCHES = [
  { key: "zi", zh: "\u5B50", en: "Zi", pinyin: "z\u01D0", zodiacZh: "\u9F20", zodiacEn: "Rat", element: "water", hours: "23:00-01:00", definition: "Rat branch \u2014 cardinal Water; midnight, winter solstice, hidden beginnings." },
  { key: "chou", zh: "\u4E11", en: "Chou", pinyin: "ch\u01D2u", zodiacZh: "\u725B", zodiacEn: "Ox", element: "earth", hours: "01:00-03:00", definition: "Ox branch \u2014 moist Earth; late winter, quiet accumulation." },
  { key: "yin", zh: "\u5BC5", en: "Yin", pinyin: "y\xEDn", zodiacZh: "\u864E", zodiacEn: "Tiger", element: "wood", hours: "03:00-05:00", definition: "Tiger branch \u2014 Yang Wood; early spring, the start of the zodiac year." },
  { key: "mao", zh: "\u536F", en: "Mao", pinyin: "m\u01CEo", zodiacZh: "\u5154", zodiacEn: "Rabbit", element: "wood", hours: "05:00-07:00", definition: "Rabbit branch \u2014 Yin Wood; mid-spring, sunrise and expansion." },
  { key: "chen", zh: "\u8FB0", en: "Chen", pinyin: "ch\xE9n", zodiacZh: "\u9F99", zodiacEn: "Dragon", element: "earth", hours: "07:00-09:00", definition: "Dragon branch \u2014 wet Earth; late spring, the water reservoir." },
  { key: "si", zh: "\u5DF3", en: "Si", pinyin: "s\xEC", zodiacZh: "\u86C7", zodiacEn: "Snake", element: "fire", hours: "09:00-11:00", definition: "Snake branch \u2014 Yin Fire; early summer, hidden heat." },
  { key: "wuHorse", zh: "\u5348", en: "Wu", pinyin: "w\u01D4", zodiacZh: "\u9A6C", zodiacEn: "Horse", element: "fire", hours: "11:00-13:00", definition: "Horse branch \u2014 cardinal Fire; noon, summer solstice, peak Yang." },
  { key: "wei", zh: "\u672A", en: "Wei", pinyin: "w\xE8i", zodiacZh: "\u7F8A", zodiacEn: "Goat", element: "earth", hours: "13:00-15:00", definition: "Goat branch \u2014 dry Earth; late summer, the wood reservoir." },
  { key: "shen", zh: "\u7533", en: "Shen", pinyin: "sh\u0113n", zodiacZh: "\u7334", zodiacEn: "Monkey", element: "metal", hours: "15:00-17:00", definition: "Monkey branch \u2014 Yang Metal; early autumn, the water birthplace." },
  { key: "you", zh: "\u9149", en: "You", pinyin: "y\u01D2u", zodiacZh: "\u9E21", zodiacEn: "Rooster", element: "metal", hours: "17:00-19:00", definition: "Rooster branch \u2014 cardinal Metal; mid-autumn, sunset and precision." },
  { key: "xu", zh: "\u620C", en: "Xu", pinyin: "x\u016B", zodiacZh: "\u72D7", zodiacEn: "Dog", element: "earth", hours: "19:00-21:00", definition: "Dog branch \u2014 dry Earth; late autumn, the fire reservoir." },
  { key: "hai", zh: "\u4EA5", en: "Hai", pinyin: "h\xE0i", zodiacZh: "\u732A", zodiacEn: "Pig", element: "water", hours: "21:00-23:00", definition: "Pig branch \u2014 Yang Water; early winter, the wood birthplace." }
];
var BRANCH_BY_CHAR = Object.freeze(
  Object.fromEntries(BRANCHES.map((b) => [b.zh, b]))
);
var BRANCH_BY_KEY = Object.freeze(
  Object.fromEntries(BRANCHES.map((b) => [b.key, b]))
);
function branchByChar(char) {
  return BRANCH_BY_CHAR[char];
}

// src/data/elements.ts
var ELEMENTS = [
  { key: "wood", zh: "\u6728", en: "Wood", pinyin: "m\xF9", definition: "Growth, expansion and benevolence; associated with spring and the east." },
  { key: "fire", zh: "\u706B", en: "Fire", pinyin: "hu\u01D2", definition: "Heat, illumination and propriety; associated with summer and the south." },
  { key: "earth", zh: "\u571F", en: "Earth", pinyin: "t\u01D4", definition: "Stability, nourishment and trust; associated with the late-season transitions and the center." },
  { key: "metal", zh: "\u91D1", en: "Metal", pinyin: "j\u012Bn", definition: "Structure, decisiveness and righteousness; associated with autumn and the west." },
  { key: "water", zh: "\u6C34", en: "Water", pinyin: "shu\u01D0", definition: "Flow, wisdom and adaptability; associated with winter and the north." }
];
var ELEMENT_BY_CHAR = Object.freeze(
  Object.fromEntries(ELEMENTS.map((e) => [e.zh, e]))
);
var ELEMENT_BY_KEY = Object.freeze(
  Object.fromEntries(ELEMENTS.map((e) => [e.key, e]))
);
function elementOf(input) {
  return ELEMENT_BY_CHAR[input] ?? ELEMENT_BY_KEY[input];
}
var ELEMENT_CYCLES = {
  generating: [
    ["wood", "fire"],
    ["fire", "earth"],
    ["earth", "metal"],
    ["metal", "water"],
    ["water", "wood"]
  ],
  controlling: [
    ["wood", "earth"],
    ["earth", "water"],
    ["water", "fire"],
    ["fire", "metal"],
    ["metal", "wood"]
  ]
};

// src/data/tenGods.ts
var TEN_GODS = [
  { key: "biJian", zh: "\u6BD4\u80A9", en: "Friend", pinyin: "b\u01D0 ji\u0101n", definition: "Same element, same polarity as the Day Master: peers, siblings, competitors and self-reliance." },
  { key: "jieCai", zh: "\u52AB\u8D22", en: "Rob Wealth", pinyin: "ji\xE9 c\xE1i", definition: "Same element, opposite polarity: rivals who share your resources; boldness and spending." },
  { key: "shiShen", zh: "\u98DF\u795E", en: "Eating God", pinyin: "sh\xED sh\xE9n", definition: "Element the Day Master generates, same polarity: creativity, enjoyment, expression and fertility." },
  { key: "shangGuan", zh: "\u4F24\u5B98", en: "Hurting Officer", pinyin: "sh\u0101ng gu\u0101n", definition: "Element the Day Master generates, opposite polarity: talent, rebellion and rule-breaking brilliance." },
  { key: "pianCai", zh: "\u504F\u8D22", en: "Indirect Wealth", pinyin: "pi\u0101n c\xE1i", definition: "Element the Day Master controls, same polarity: windfall money, business acumen and generosity." },
  { key: "zhengCai", zh: "\u6B63\u8D22", en: "Direct Wealth", pinyin: "zh\xE8ng c\xE1i", definition: "Element the Day Master controls, opposite polarity: stable income, savings and (traditionally) the wife star." },
  { key: "qiSha", zh: "\u4E03\u6740", en: "Seven Killings", pinyin: "q\u012B sh\u0101", definition: "Element that controls the Day Master, same polarity: pressure, authority, courage and fierce ambition." },
  { key: "zhengGuan", zh: "\u6B63\u5B98", en: "Direct Officer", pinyin: "zh\xE8ng gu\u0101n", definition: "Element that controls the Day Master, opposite polarity: career, discipline, reputation and (traditionally) the husband star." },
  { key: "pianYin", zh: "\u504F\u5370", en: "Indirect Resource", pinyin: "pi\u0101n y\xECn", definition: "Element that generates the Day Master, same polarity: unconventional learning, intuition and solitude." },
  { key: "zhengYin", zh: "\u6B63\u5370", en: "Direct Resource", pinyin: "zh\xE8ng y\xECn", definition: "Element that generates the Day Master, opposite polarity: education, protection, motherly support and credentials." },
  { key: "dayMaster", zh: "\u65E5\u4E3B", en: "Day Master", pinyin: "r\xEC zh\u01D4", definition: "The Heavenly Stem of the Day Pillar \u2014 the reference point of the whole chart, representing the self." }
];
var TEN_GOD_BY_KEY = Object.freeze(
  Object.fromEntries(TEN_GODS.map((t2) => [t2.key, t2]))
);
var TEN_GOD_ZH_ALIASES = Object.freeze({
  \u6BD4\u80A9: "biJian",
  \u52AB\u8D22: "jieCai",
  \u98DF\u795E: "shiShen",
  \u4F24\u5B98: "shangGuan",
  \u504F\u8D22: "pianCai",
  \u6B63\u8D22: "zhengCai",
  \u4E03\u6740: "qiSha",
  \u504F\u5B98: "qiSha",
  \u6B63\u5B98: "zhengGuan",
  \u504F\u5370: "pianYin",
  \u67AD\u795E: "pianYin",
  \u6B63\u5370: "zhengYin",
  \u65E5\u4E3B: "dayMaster",
  \u65E5\u5143: "dayMaster",
  \u5143\u7537: "dayMaster",
  \u5143\u5973: "dayMaster"
});
function tenGodByZh(zh) {
  const key = TEN_GOD_ZH_ALIASES[zh];
  return key ? TEN_GOD_BY_KEY[key] : void 0;
}

// src/data/growthStages.ts
var GROWTH_STAGES = [
  { key: "birth", zh: "\u957F\u751F", en: "Birth", pinyin: "ch\xE1ng sh\u0113ng", definition: "Newly born energy; the element enters its most promising phase." },
  { key: "bathing", zh: "\u6C90\u6D74", en: "Bathing", pinyin: "m\xF9 y\xF9", definition: "Infancy and washing; vulnerable, romantic and unstable energy." },
  { key: "crowning", zh: "\u51A0\u5E26", en: "Crowning", pinyin: "gu\xE0n d\xE0i", definition: "Coming of age; the element dresses up and starts to show capability." },
  { key: "officiating", zh: "\u4E34\u5B98", en: "Officiating", pinyin: "l\xEDn gu\u0101n", definition: "Taking office; mature, productive energy approaching its peak." },
  { key: "peak", zh: "\u5E1D\u65FA", en: "Peak", pinyin: "d\xEC w\xE0ng", definition: "Imperial prosperity; the element at maximum strength." },
  { key: "decline", zh: "\u8870", en: "Decline", pinyin: "shu\u0101i", definition: "Energy past its prime, gradually weakening." },
  { key: "illness", zh: "\u75C5", en: "Illness", pinyin: "b\xECng", definition: "Weakened energy, like sickness; low vitality." },
  { key: "death", zh: "\u6B7B", en: "Death", pinyin: "s\u01D0", definition: "Dormant energy; quiet, still and inactive." },
  { key: "tomb", zh: "\u5893", en: "Tomb", pinyin: "m\xF9", definition: "Stored energy locked in the tomb; latent, hoarded, awaiting a key." },
  { key: "extinction", zh: "\u7EDD", en: "Extinction", pinyin: "ju\xE9", definition: "The lowest point; energy seemingly gone but about to turn." },
  { key: "gestation", zh: "\u80CE", en: "Gestation", pinyin: "t\u0101i", definition: "Conception; a new cycle forming in secret." },
  { key: "nurturing", zh: "\u517B", en: "Nurturing", pinyin: "y\u01CEng", definition: "Nourishment before birth; gentle preparation for the next cycle." }
];
var GROWTH_STAGE_BY_KEY = Object.freeze(
  Object.fromEntries(GROWTH_STAGES.map((g) => [g.key, g]))
);
var GROWTH_STAGE_BY_ZH = Object.freeze(
  Object.fromEntries(GROWTH_STAGES.map((g) => [g.zh, g]))
);
function growthStageByZh(zh) {
  return GROWTH_STAGE_BY_ZH[zh];
}

// src/data/shenSha.ts
var SHEN_SHA = [
  { key: "tianYiGuiRen", zh: "\u5929\u4E59\u8D35\u4EBA", en: "Heavenly Nobleman", pinyin: "ti\u0101n y\u01D0 gu\xEC r\xE9n", definition: "The most auspicious star: helpful people and timely rescue in difficulty." },
  { key: "taiJiGuiRen", zh: "\u592A\u6781\u8D35\u4EBA", en: "Taiji Nobleman", pinyin: "t\xE0i j\xED gu\xEC r\xE9n", definition: "Affinity with metaphysics, philosophy and deep research." },
  { key: "tianDeGuiRen", zh: "\u5929\u5FB7\u8D35\u4EBA", en: "Heavenly Virtue", pinyin: "ti\u0101n d\xE9 gu\xEC r\xE9n", definition: "Heaven-sent protection that softens disasters." },
  { key: "yueDeGuiRen", zh: "\u6708\u5FB7\u8D35\u4EBA", en: "Monthly Virtue", pinyin: "yu\xE8 d\xE9 gu\xEC r\xE9n", definition: "Gentle protective virtue; calming influence on misfortune." },
  { key: "tianDeHe", zh: "\u5929\u5FB7\u5408", en: "Heavenly Virtue Union", pinyin: "ti\u0101n d\xE9 h\xE9", definition: "Companion star of Heavenly Virtue; reinforces protection." },
  { key: "yueDeHe", zh: "\u6708\u5FB7\u5408", en: "Monthly Virtue Union", pinyin: "yu\xE8 d\xE9 h\xE9", definition: "Companion star of Monthly Virtue; reinforces protection." },
  { key: "deXiuGuiRen", zh: "\u5FB7\u79C0\u8D35\u4EBA", en: "Virtue-Elegance Nobleman", pinyin: "d\xE9 xi\xF9 gu\xEC r\xE9n", definition: "Refined character and talent; turns danger into fortune." },
  { key: "fuXingGuiRen", zh: "\u798F\u661F\u8D35\u4EBA", en: "Blessing Nobleman", pinyin: "f\xFA x\u012Bng gu\xEC r\xE9n", definition: "Everyday blessings, comfort and a smooth life path." },
  { key: "wenChangGuiRen", zh: "\u6587\u660C\u8D35\u4EBA", en: "Literary Star", pinyin: "w\xE9n ch\u0101ng gu\xEC r\xE9n", definition: "Academic success, writing talent and examination luck." },
  { key: "xueTang", zh: "\u5B66\u5802", en: "School Hall", pinyin: "xu\xE9 t\xE1ng", definition: "Scholarly star favoring study and intellectual growth." },
  { key: "ciGuan", zh: "\u8BCD\u9986", en: "Literary Bureau", pinyin: "c\xED gu\u01CEn", definition: "Eloquence and literary accomplishment." },
  { key: "tianYi", zh: "\u5929\u533B", en: "Heavenly Doctor", pinyin: "ti\u0101n y\u012B", definition: "Affinity with medicine, healing and health work." },
  { key: "yiMa", zh: "\u9A7F\u9A6C", en: "Traveling Horse", pinyin: "y\xEC m\u01CE", definition: "Movement: travel, relocation, overseas ties and restless change." },
  { key: "taoHua", zh: "\u6843\u82B1", en: "Peach Blossom", pinyin: "t\xE1o hu\u0101", definition: "Romance, charm and social magnetism." },
  { key: "hongYan", zh: "\u7EA2\u8273", en: "Red Beauty", pinyin: "h\xF3ng y\xE0n", definition: "Intense romantic allure; passion that can outshine caution." },
  { key: "hongLuan", zh: "\u7EA2\u9E3E", en: "Red Phoenix", pinyin: "h\xF3ng lu\xE1n", definition: "Marriage and celebration star; joyous occasions." },
  { key: "tianXi", zh: "\u5929\u559C", en: "Heavenly Joy", pinyin: "ti\u0101n x\u01D0", definition: "Happiness, weddings and festive events." },
  { key: "huaGai", zh: "\u534E\u76D6", en: "Elegant Canopy", pinyin: "hu\xE1 g\xE0i", definition: "Artistic genius and spiritual depth, tinged with solitude." },
  { key: "jinYu", zh: "\u91D1\u8206", en: "Golden Carriage", pinyin: "j\u012Bn y\xFA", definition: "Comfort, spousal support and an easy ride through life." },
  { key: "jiangXing", zh: "\u5C06\u661F", en: "General Star", pinyin: "ji\xE0ng x\u012Bng", definition: "Leadership, authority and command over others." },
  { key: "yangRen", zh: "\u7F8A\u5203", en: "Blade", pinyin: "y\xE1ng r\xE8n", definition: "Sharp, aggressive edge just past the peak; courage mixed with risk of injury." },
  { key: "feiRen", zh: "\u98DE\u5203", en: "Flying Blade", pinyin: "f\u0113i r\xE8n", definition: "The opposite-facing blade; sudden conflicts and impulsive force." },
  { key: "luShen", zh: "\u7984\u795E", en: "Prosperity Star", pinyin: "l\xF9 sh\xE9n", definition: "Steady income and self-earned wealth; the stem at its own root." },
  { key: "liuXia", zh: "\u6D41\u971E", en: "Flowing Mist", pinyin: "li\xFA xi\xE1", definition: "Blood-related caution star; watch for injuries and inflammation." },
  { key: "guChen", zh: "\u5B64\u8FB0", en: "Solitary Star", pinyin: "g\u016B ch\xE9n", definition: "Emotional distance and preference for solitude." },
  { key: "guaSu", zh: "\u5BE1\u5BBF", en: "Widowed Star", pinyin: "gu\u01CE s\xF9", definition: "Loneliness in close relationships; inner detachment." },
  { key: "jieSha", zh: "\u52AB\u715E", en: "Robbery Star", pinyin: "ji\xE9 sh\xE0", definition: "Sudden loss or seizure; act with caution in risky matters." },
  { key: "zaiSha", zh: "\u707E\u715E", en: "Disaster Star", pinyin: "z\u0101i sh\xE0", definition: "External misfortune; traditionally linked to accidents and setbacks." },
  { key: "wangShen", zh: "\u4EA1\u795E", en: "Lost Spirit", pinyin: "w\xE1ng sh\xE9n", definition: "Hidden schemes and mental drain; can sharpen strategy when controlled." },
  { key: "piMa", zh: "\u62AB\u9EBB", en: "Mourning Veil", pinyin: "p\u012B m\xE1", definition: "Family worries and melancholy events." },
  { key: "tongZiSha", zh: "\u7AE5\u5B50\u715E", en: "Child Star", pinyin: "t\xF3ng z\u01D0 sh\xE0", definition: "Folk belief of a celestial child identity; a youthful, otherworldly temperament." },
  { key: "liuXiuRi", zh: "\u516D\u79C0\u65E5", en: "Six Elegance Day", pinyin: "li\xF9 xi\xF9 r\xEC", definition: "Day pillar known for talent and refined appearance." },
  { key: "jiuChouRi", zh: "\u4E5D\u4E11\u65E5", en: "Nine Ugly Day", pinyin: "ji\u01D4 ch\u01D2u r\xEC", definition: "Day pillar linked to romantic entanglements; name misleads, effect is relational friction." },
  { key: "kongWang", zh: "\u7A7A\u4EA1", en: "Void", pinyin: "k\u014Dng w\xE1ng", definition: "The two branches outside the current decade cycle; energy that feels hollow or deferred." },
  { key: "guoYin", zh: "\u56FD\u5370", en: "State Seal", pinyin: "gu\xF3 y\xECn", definition: "Officialdom, seals of office and institutional power." },
  { key: "tianLuoDiWang", zh: "\u5929\u7F57\u5730\u7F51", en: "Sky Net & Earth Net", pinyin: "ti\u0101n lu\xF3 d\xEC w\u01CEng", definition: "Confining combinations (\u620C\u4EA5 / \u8FB0\u5DF3) that feel like being trapped." },
  { key: "yinChaYangCuo", zh: "\u9634\u5DEE\u9633\u9519", en: "Yin-Yang Mismatch", pinyin: "y\u012Bn ch\u0101 y\xE1ng cu\xF2", definition: "Day pillar linked to misunderstandings in family and marriage matters." },
  { key: "shiEDaBai", zh: "\u5341\u6076\u5927\u8D25", en: "Ten Evils Great Defeat", pinyin: "sh\xED \xE8 d\xE0 b\xE0i", definition: "Classic inauspicious day pillar group; tradition advises careful money management." }
];
var SHEN_SHA_BY_ZH = Object.freeze(
  Object.fromEntries(SHEN_SHA.map((s) => [s.zh, s]))
);
var SHEN_SHA_BY_KEY = Object.freeze(
  Object.fromEntries(SHEN_SHA.map((s) => [s.key, s]))
);
function shenShaByZh(zh) {
  return SHEN_SHA_BY_ZH[zh];
}

// src/data/nayin.ts
var NA_YIN = [
  { key: "seaGold", zh: "\u6D77\u4E2D\u91D1", en: "Sea Gold", pairs: ["\u7532\u5B50", "\u4E59\u4E11"], definition: "Gold hidden in the sea: talent waiting to be discovered." },
  { key: "furnaceFire", zh: "\u7089\u4E2D\u706B", en: "Furnace Fire", pairs: ["\u4E19\u5BC5", "\u4E01\u536F"], definition: "Fire in the furnace: energy that forges and transforms." },
  { key: "forestWood", zh: "\u5927\u6797\u6728", en: "Forest Wood", pairs: ["\u620A\u8FB0", "\u5DF1\u5DF3"], definition: "Great forest wood: abundant, sheltering growth." },
  { key: "roadsideEarth", zh: "\u8DEF\u65C1\u571F", en: "Roadside Earth", pairs: ["\u5E9A\u5348", "\u8F9B\u672A"], definition: "Earth by the roadside: practical, trodden, serviceable." },
  { key: "swordEdgeGold", zh: "\u5251\u950B\u91D1", en: "Sword-edge Gold", pairs: ["\u58EC\u7533", "\u7678\u9149"], definition: "Sharpened blade metal: precision and cutting brilliance." },
  { key: "mountaintopFire", zh: "\u5C71\u5934\u706B", en: "Mountaintop Fire", pairs: ["\u7532\u620C", "\u4E59\u4EA5"], definition: "Fire on the summit: visible, far-reaching light." },
  { key: "streamWater", zh: "\u6DA7\u4E0B\u6C34", en: "Stream Water", pairs: ["\u4E19\u5B50", "\u4E01\u4E11"], definition: "Water in the ravine: clear, quiet, persistent flow." },
  { key: "cityWallEarth", zh: "\u57CE\u5934\u571F", en: "City-wall Earth", pairs: ["\u620A\u5BC5", "\u5DF1\u536F"], definition: "Rampart earth: defensive strength and boundaries." },
  { key: "waxGold", zh: "\u767D\u8721\u91D1", en: "Wax Gold", pairs: ["\u5E9A\u8FB0", "\u8F9B\u5DF3"], definition: "White wax metal: formable value needing refinement." },
  { key: "willowWood", zh: "\u6768\u67F3\u6728", en: "Willow Wood", pairs: ["\u58EC\u5348", "\u7678\u672A"], definition: "Willow wood: graceful flexibility and resilience." },
  { key: "springWater", zh: "\u6CC9\u4E2D\u6C34", en: "Spring Water", pairs: ["\u7532\u7533", "\u4E59\u9149"], definition: "Water in the well: inexhaustible, hidden source." },
  { key: "rooftopEarth", zh: "\u5C4B\u4E0A\u571F", en: "Rooftop Earth", pairs: ["\u4E19\u620C", "\u4E01\u4EA5"], definition: "Earth on the roof: shelter and protection." },
  { key: "thunderboltFire", zh: "\u9739\u96F3\u706B", en: "Thunderbolt Fire", pairs: ["\u620A\u5B50", "\u5DF1\u4E11"], definition: "Lightning fire: sudden, dramatic power." },
  { key: "pineWood", zh: "\u677E\u67CF\u6728", en: "Pine Wood", pairs: ["\u5E9A\u5BC5", "\u8F9B\u536F"], definition: "Pine and cypress: endurance through seasons." },
  { key: "longFlowingWater", zh: "\u957F\u6D41\u6C34", en: "Long-flowing Water", pairs: ["\u58EC\u8FB0", "\u7678\u5DF3"], definition: "Ever-flowing water: momentum that never stagnates." },
  { key: "sandGold", zh: "\u6C99\u4E2D\u91D1", en: "Sand Gold", pairs: ["\u7532\u5348", "\u4E59\u672A"], definition: "Gold in sand: value requiring patient sifting." },
  { key: "foothillFire", zh: "\u5C71\u4E0B\u706B", en: "Foothill Fire", pairs: ["\u4E19\u7533", "\u4E01\u9149"], definition: "Fire below the mountain: warmth close to home." },
  { key: "plainWood", zh: "\u5E73\u5730\u6728", en: "Plain Wood", pairs: ["\u620A\u620C", "\u5DF1\u4EA5"], definition: "Wood on the plain: steady, unpretentious growth." },
  { key: "wallEarth", zh: "\u58C1\u4E0A\u571F", en: "Wall Earth", pairs: ["\u5E9A\u5B50", "\u8F9B\u4E11"], definition: "Earth on the wall: quiet support and structure." },
  { key: "goldFoil", zh: "\u91D1\u7B94\u91D1", en: "Gold Foil", pairs: ["\u58EC\u5BC5", "\u7678\u536F"], definition: "Gilt foil: beauty, ornament and surface brilliance." },
  { key: "lampFire", zh: "\u8986\u706F\u706B", en: "Lamp Fire", pairs: ["\u7532\u8FB0", "\u4E59\u5DF3"], definition: "Covered lamp flame: small light that guides in darkness." },
  { key: "riverOfHeavenWater", zh: "\u5929\u6CB3\u6C34", en: "River of Heaven Water", pairs: ["\u4E19\u5348", "\u4E01\u672A"], definition: "Celestial river: the Milky Way; inspiration from above." },
  { key: "highwayEarth", zh: "\u5927\u9A7F\u571F", en: "Highway Earth", pairs: ["\u620A\u7533", "\u5DF1\u9149"], definition: "Great post-road earth: connection, travel and commerce." },
  { key: "hairpinGold", zh: "\u9497\u948F\u91D1", en: "Hairpin Gold", pairs: ["\u5E9A\u620C", "\u8F9B\u4EA5"], definition: "Ornamental jewelry metal: adornment and refined value." },
  { key: "mulberryWood", zh: "\u6851\u67D8\u6728", en: "Mulberry Wood", pairs: ["\u58EC\u5B50", "\u7678\u4E11"], definition: "Mulberry wood: cultivation, silkworms and useful craft." },
  { key: "greatStreamWater", zh: "\u5927\u6EAA\u6C34", en: "Great Stream Water", pairs: ["\u7532\u5BC5", "\u4E59\u536F"], definition: "Rushing stream: vigorous, purposeful movement." },
  { key: "desertEarth", zh: "\u6C99\u4E2D\u571F", en: "Desert Earth", pairs: ["\u4E19\u8FB0", "\u4E01\u5DF3"], definition: "Earth in sand: loose foundation needing consolidation." },
  { key: "celestialFire", zh: "\u5929\u4E0A\u706B", en: "Celestial Fire", pairs: ["\u620A\u5348", "\u5DF1\u672A"], definition: "Fire in the sky: the sun itself; universal warmth." },
  { key: "pomegranateWood", zh: "\u77F3\u69B4\u6728", en: "Pomegranate Wood", pairs: ["\u5E9A\u7533", "\u8F9B\u9149"], definition: "Pomegranate wood: hard wood bearing many fruits." },
  { key: "oceanWater", zh: "\u5927\u6D77\u6C34", en: "Ocean Water", pairs: ["\u58EC\u620C", "\u7678\u4EA5"], definition: "The open ocean: vastness, depth and inclusiveness." }
];
var NA_YIN_BY_ZH = Object.freeze(
  Object.fromEntries(NA_YIN.map((n) => [n.zh, n]))
);
var NA_YIN_BY_GAN_ZHI = Object.freeze(
  Object.fromEntries(NA_YIN.flatMap((n) => n.pairs.map((p) => [p, n])))
);
function naYinOf(input) {
  return NA_YIN_BY_ZH[input] ?? NA_YIN_BY_GAN_ZHI[input];
}

// src/data/interactions.ts
var INTERACTION_TYPES = [
  {
    key: "stemCombination",
    zh: "\u5929\u5E72\u4E94\u5408",
    en: "Stem Combination",
    pinyin: "ti\u0101n g\u0101n w\u01D4 h\xE9",
    zhVerb: "\u5408",
    definition: "Five Heavenly Stem pairings that bond and may transform: \u7532\u5DF1, \u4E59\u5E9A, \u4E19\u8F9B, \u4E01\u58EC, \u620A\u7678."
  },
  {
    key: "liuHe",
    zh: "\u516D\u5408",
    en: "Six Harmony",
    pinyin: "li\xF9 h\xE9",
    enumCode: "COMBINATION_2",
    zhVerb: "\u5408",
    definition: "Six branch pairings of mutual affinity and support: \u5B50\u4E11, \u5BC5\u4EA5, \u536F\u620C, \u8FB0\u9149, \u5DF3\u7533, \u5348\u672A."
  },
  {
    key: "sanHe",
    zh: "\u4E09\u5408",
    en: "Three Harmony",
    pinyin: "s\u0101n h\xE9",
    enumCode: "TRINE",
    definition: "Triads that combine into one element: \u7533\u5B50\u8FB0(water), \u4EA5\u536F\u672A(wood), \u5BC5\u5348\u620C(fire), \u5DF3\u9149\u4E11(metal)."
  },
  {
    key: "sanHui",
    zh: "\u4E09\u4F1A",
    en: "Directional Combination",
    pinyin: "s\u0101n hu\xEC",
    enumCode: "DIRECTIONAL",
    definition: "Three adjacent branches of one seasonal direction: \u5BC5\u536F\u8FB0(east), \u5DF3\u5348\u672A(south), \u7533\u9149\u620C(west), \u4EA5\u5B50\u4E11(north)."
  },
  {
    key: "liuChong",
    zh: "\u516D\u51B2",
    en: "Clash",
    pinyin: "li\xF9 ch\u014Dng",
    enumCode: "CLASH",
    zhVerb: "\u51B2",
    definition: "Six opposing branch pairings that collide and disrupt: \u5B50\u5348, \u4E11\u672A, \u5BC5\u7533, \u536F\u9149, \u8FB0\u620C, \u5DF3\u4EA5."
  },
  {
    key: "xiangXing",
    zh: "\u76F8\u5211",
    en: "Punishment",
    pinyin: "xi\u0101ng x\xEDng",
    enumCode: "PUNISHMENT",
    zhVerb: "\u5211",
    definition: "Branch punishments that grind and injure: \u5BC5\u5DF3\u7533, \u4E11\u620C\u672A, \u5B50\u536F, and the self-punishments \u8FB0/\u5348/\u9149/\u4EA5."
  },
  {
    key: "xiangHai",
    zh: "\u76F8\u5BB3",
    en: "Harm",
    pinyin: "xi\u0101ng h\xE0i",
    enumCode: "HARM",
    zhVerb: "\u5BB3",
    definition: "Six branch pairings of hidden injury and betrayal: \u5B50\u672A, \u4E11\u5348, \u5BC5\u5DF3, \u536F\u8FB0, \u7533\u4EA5, \u9149\u620C."
  },
  {
    key: "xiangPo",
    zh: "\u76F8\u7834",
    en: "Destruction",
    pinyin: "xi\u0101ng p\xF2",
    enumCode: "DESTRUCTION",
    zhVerb: "\u7834",
    definition: "Six branch pairings of breakage and erosion: \u5B50\u9149, \u536F\u5348, \u8FB0\u4E11, \u672A\u620C, \u5BC5\u4EA5, \u5DF3\u7533."
  }
];
var INTERACTION_BY_KEY = Object.freeze(
  Object.fromEntries(INTERACTION_TYPES.map((i) => [i.key, i]))
);
var INTERACTION_BY_ENUM = Object.freeze(
  Object.fromEntries(
    INTERACTION_TYPES.filter((i) => i.enumCode).map((i) => [i.enumCode, i])
  )
);
var ZH_VERB_RULES = [
  ["\u4E09\u5408", "sanHe"],
  ["\u4E09\u4F1A", "sanHui"],
  ["\u4F1A", "sanHui"],
  ["\u76F8\u51B2", "liuChong"],
  ["\u51B2", "liuChong"],
  ["\u76F8\u5211", "xiangXing"],
  ["\u5211", "xiangXing"],
  ["\u76F8\u7834", "xiangPo"],
  ["\u7834", "xiangPo"],
  ["\u76F8\u5BB3", "xiangHai"],
  ["\u5BB3", "xiangHai"],
  ["\u516D\u5408", "liuHe"],
  ["\u76F8\u5408", "liuHe"],
  ["\u5408", "liuHe"]
];
function interactionFromZh(desc) {
  for (const [verb, key] of ZH_VERB_RULES) {
    if (desc.includes(verb)) return INTERACTION_BY_KEY[key];
  }
  return void 0;
}
function interactionFromEnum(type) {
  return INTERACTION_BY_ENUM[type];
}
var STEM_COMBINATIONS = [
  ["\u7532", "\u5DF1"],
  ["\u4E59", "\u5E9A"],
  ["\u4E19", "\u8F9B"],
  ["\u4E01", "\u58EC"],
  ["\u620A", "\u7678"]
];
var LIU_HE = [
  ["\u5B50", "\u4E11"],
  ["\u5BC5", "\u4EA5"],
  ["\u536F", "\u620C"],
  ["\u8FB0", "\u9149"],
  ["\u5DF3", "\u7533"],
  ["\u5348", "\u672A"]
];
var LIU_CHONG = [
  ["\u5B50", "\u5348"],
  ["\u4E11", "\u672A"],
  ["\u5BC5", "\u7533"],
  ["\u536F", "\u9149"],
  ["\u8FB0", "\u620C"],
  ["\u5DF3", "\u4EA5"]
];
var SAN_HE = [
  ["\u7533", "\u5B50", "\u8FB0"],
  ["\u4EA5", "\u536F", "\u672A"],
  ["\u5BC5", "\u5348", "\u620C"],
  ["\u5DF3", "\u9149", "\u4E11"]
];
var SAN_HUI = [
  ["\u5BC5", "\u536F", "\u8FB0"],
  ["\u5DF3", "\u5348", "\u672A"],
  ["\u7533", "\u9149", "\u620C"],
  ["\u4EA5", "\u5B50", "\u4E11"]
];
var XIANG_HAI = [
  ["\u5B50", "\u672A"],
  ["\u4E11", "\u5348"],
  ["\u5BC5", "\u5DF3"],
  ["\u536F", "\u8FB0"],
  ["\u7533", "\u4EA5"],
  ["\u9149", "\u620C"]
];
var XIANG_PO = [
  ["\u5B50", "\u9149"],
  ["\u536F", "\u5348"],
  ["\u8FB0", "\u4E11"],
  ["\u672A", "\u620C"],
  ["\u5BC5", "\u4EA5"],
  ["\u5DF3", "\u7533"]
];
var XIANG_XING = {
  wuEn: ["\u5BC5", "\u5DF3", "\u7533"],
  shiShi: ["\u4E11", "\u620C", "\u672A"],
  wuLi: ["\u5B50", "\u536F"],
  ziXing: ["\u8FB0", "\u5348", "\u9149", "\u4EA5"]
};

// src/data/general.ts
var GENERAL_TERMS = [
  /* Chart & pillars */
  { key: "bazi", zh: "\u516B\u5B57", en: "BaZi (Four Pillars)", pinyin: "b\u0101 z\xEC", definition: "The Eight Characters: a destiny chart built from the year, month, day and hour of birth." },
  { key: "fourPillars", zh: "\u56DB\u67F1", en: "Four Pillars", pinyin: "s\xEC zh\xF9", definition: "The four stem-branch pairs \u2014 year, month, day and hour \u2014 that make up a chart." },
  { key: "yearPillar", zh: "\u5E74\u67F1", en: "Year Pillar", pinyin: "ni\xE1n zh\xF9", definition: "The first pillar; roots, ancestry and early life." },
  { key: "monthPillar", zh: "\u6708\u67F1", en: "Month Pillar", pinyin: "yu\xE8 zh\xF9", definition: "The second pillar; parents, career environment and youth." },
  { key: "dayPillar", zh: "\u65E5\u67F1", en: "Day Pillar", pinyin: "r\xEC zh\xF9", definition: "The third pillar; the self (stem) and the spouse palace (branch)." },
  { key: "hourPillar", zh: "\u65F6\u67F1", en: "Hour Pillar", pinyin: "sh\xED zh\xF9", definition: "The fourth pillar; children, later life and ambitions." },
  { key: "heavenlyStem", zh: "\u5929\u5E72", en: "Heavenly Stem", pinyin: "ti\u0101n g\u0101n", definition: "One of ten yang/yin symbols; the visible, active layer of a pillar." },
  { key: "earthlyBranch", zh: "\u5730\u652F", en: "Earthly Branch", pinyin: "d\xEC zh\u012B", definition: "One of twelve symbols (the zodiac animals); the hidden, receptive layer of a pillar." },
  { key: "ganZhi", zh: "\u5E72\u652F", en: "Stem-Branch (GanZhi)", pinyin: "g\u0101n zh\u012B", definition: "A stem paired with a branch; one unit of the sexagenary cycle." },
  { key: "hiddenStems", zh: "\u85CF\u5E72", en: "Hidden Stems", pinyin: "c\xE1ng g\u0101n", definition: "The stems concealed inside each branch, giving it layered meaning." },
  /* Cycles & palaces */
  { key: "daYun", zh: "\u5927\u8FD0", en: "Luck Pillar", pinyin: "d\xE0 y\xF9n", definition: "A ten-year fortune cycle overlaid on the natal chart." },
  { key: "liuNian", zh: "\u6D41\u5E74", en: "Annual Fortune", pinyin: "li\xFA ni\xE1n", definition: "The influence of a specific calendar year on the chart." },
  { key: "xiaoYun", zh: "\u5C0F\u8FD0", en: "Minor Cycle", pinyin: "xi\u01CEo y\xF9n", definition: "A one-year cycle used before the first Luck Pillar begins." },
  { key: "qiYun", zh: "\u8D77\u8FD0", en: "Luck Onset", pinyin: "q\u01D0 y\xF9n", definition: "The age at which the first Luck Pillar cycle starts." },
  { key: "mingGong", zh: "\u547D\u5BAB", en: "Life Palace", pinyin: "m\xECng g\u014Dng", definition: "An auxiliary pillar describing the core life theme." },
  { key: "shenGong", zh: "\u8EAB\u5BAB", en: "Body Palace", pinyin: "sh\u0113n g\u014Dng", definition: "An auxiliary pillar describing how life is lived out in practice." },
  { key: "taiYuan", zh: "\u80CE\u5143", en: "Conception Pillar", pinyin: "t\u0101i yu\xE1n", definition: "The stem-branch of conception; inherited and prenatal influence." },
  { key: "taiXi", zh: "\u80CE\u606F", en: "Prenatal Breath", pinyin: "t\u0101i x\u012B", definition: "A pillar paired with the Conception Pillar; subtle life force." },
  /* Symbolic systems */
  { key: "yinYang", zh: "\u9634\u9633", en: "Yin & Yang", pinyin: "y\u012Bn y\xE1ng", definition: "The two complementary polarities underlying every stem and branch." },
  { key: "wuXing", zh: "\u4E94\u884C", en: "Five Elements", pinyin: "w\u01D4 x\xEDng", definition: "Wood, Fire, Earth, Metal and Water \u2014 the phases of transforming energy." },
  { key: "shiShenGods", zh: "\u5341\u795E", en: "Ten Gods", pinyin: "sh\xED sh\xE9n", definition: "Relationship labels between each stem and the Day Master." },
  { key: "shenSha", zh: "\u795E\u715E", en: "Shen Sha (Symbolic Stars)", pinyin: "sh\xE9n sh\xE0", definition: "Auspicious and inauspicious symbolic stars overlaid on the chart." },
  { key: "naYin", zh: "\u7EB3\u97F3", en: "Na Yin (Melodic Element)", pinyin: "n\xE0 y\u012Bn", definition: "The thirty melodic elements assigned to each stem-branch pair." },
  { key: "interactions", zh: "\u5211\u51B2\u5408\u4F1A", en: "Interactions", pinyin: "x\xEDng ch\u014Dng h\xE9 hu\xEC", definition: "The clashes, combinations, punishments, harms and destructions between stems and branches." },
  { key: "shengXiao", zh: "\u751F\u8096", en: "Chinese Zodiac", pinyin: "sh\u0113ng xi\xE0o", definition: "The twelve animals mapped to the Earthly Branches." },
  { key: "xun", zh: "\u65EC", en: "Decade (Xun)", pinyin: "x\xFAn", definition: "A ten-day group of the sexagenary cycle; determines the void branches." },
  { key: "xingYun", zh: "\u661F\u8FD0", en: "Growth Stage", pinyin: "x\u012Bng y\xF9n", definition: "One of the twelve lifecycle stages of an element across the branches." },
  { key: "ziZuo", zh: "\u81EA\u5750", en: "Self-sitting", pinyin: "z\xEC zu\xF2", definition: "The branch directly beneath the Day Stem and the ten god it forms." },
  /* Scoring & roles */
  { key: "wuXingFenZhi", zh: "\u4E94\u884C\u5206\u503C", en: "Element Score", pinyin: "w\u01D4 x\xEDng f\u0113n zh\xED", definition: "Weighted strength of each of the Five Elements in the chart." },
  { key: "zhuXing", zh: "\u4E3B\u661F", en: "Main Star", pinyin: "zh\u01D4 x\u012Bng", definition: "The primary ten god of a pillar (usually its hidden main stem)." },
  { key: "fuXing", zh: "\u526F\u661F", en: "Secondary Star", pinyin: "f\xF9 x\u012Bng", definition: "The additional ten gods contributed by other hidden stems." },
  { key: "dayMasterElement", zh: "\u65E5\u4E3B\u4E94\u884C", en: "Day Master Element", pinyin: "r\xEC zh\u01D4 w\u01D4 x\xEDng", definition: "The Five Element of the Day Stem \u2014 the self element of the chart." },
  /* Calendar & time */
  { key: "zhenTaiYangShi", zh: "\u771F\u592A\u9633\u65F6", en: "True Solar Time", pinyin: "zh\u0113n t\xE0i y\xE1ng sh\xED", definition: "Local apparent solar time, corrected for longitude and season; the basis of the Hour Pillar." },
  { key: "shiChen", zh: "\u65F6\u8FB0", en: "Double-hour", pinyin: "sh\xED ch\xE9n", definition: "A traditional two-hour period; twelve of them span a day." },
  { key: "nongLi", zh: "\u519C\u5386", en: "Lunar Calendar", pinyin: "n\xF3ng l\xEC", definition: "The traditional Chinese lunisolar calendar." },
  { key: "gongLi", zh: "\u516C\u5386", en: "Gregorian Calendar", pinyin: "g\u014Dng l\xEC", definition: "The international solar calendar." },
  { key: "gender", zh: "\u6027\u522B", en: "Gender", pinyin: "x\xECng bi\xE9", definition: "Male or female; determines the direction of the Luck Pillar cycles." },
  { key: "male", zh: "\u7537", en: "Male", definition: "Male gender input for chart calculation." },
  { key: "female", zh: "\u5973", en: "Female", definition: "Female gender input for chart calculation." },
  { key: "forward", zh: "\u987A\u884C", en: "Forward", pinyin: "sh\xF9n x\xEDng", definition: "Luck Pillars advancing in the natural cycle order." },
  { key: "backward", zh: "\u9006\u884C", en: "Backward", pinyin: "n\xEC x\xEDng", definition: "Luck Pillars advancing in the reverse cycle order." },
  { key: "current", zh: "\u5F53\u524D", en: "Current", pinyin: "d\u0101ng qi\xE1n", definition: "Marks the Luck Pillar or year that is active now." }
];
var GENERAL_BY_KEY = Object.freeze(
  Object.fromEntries(GENERAL_TERMS.map((g) => [g.key, g]))
);
var GENERAL_BY_ZH = Object.freeze(
  Object.fromEntries(GENERAL_TERMS.map((g) => [g.zh, g]))
);
function generalBy(key) {
  return GENERAL_BY_KEY[key];
}
function generalByZh(zh) {
  return GENERAL_BY_ZH[zh];
}

// src/index.ts
var ALL_TERMS = Object.freeze([
  ...STEMS,
  ...BRANCHES,
  ...ELEMENTS,
  ...TEN_GODS,
  ...GROWTH_STAGES,
  ...SHEN_SHA,
  ...NA_YIN,
  ...INTERACTION_TYPES,
  ...GENERAL_TERMS
]);
var TERM_BY_KEY = Object.freeze(
  Object.fromEntries(ALL_TERMS.map((term) => [term.key, term]))
);
var TERM_BY_ZH = Object.freeze(
  Object.fromEntries(ALL_TERMS.map((term) => [term.zh, term]))
);
function t(key, lang = "en") {
  const term = TERM_BY_KEY[key];
  if (!term) return key;
  return lang === "zh" ? term.zh : term.en;
}
function translate(input, lang = "en") {
  const term = TERM_BY_KEY[input] ?? TERM_BY_ZH[input] ?? tenGodByZh(input) ?? naYinOf(input) ?? interactionFromZh(input);
  if (!term) return input;
  return lang === "zh" ? term.zh : term.en;
}
export {
  ALL_TERMS,
  BRANCHES,
  BRANCH_BY_CHAR,
  BRANCH_BY_KEY,
  ELEMENTS,
  ELEMENT_BY_CHAR,
  ELEMENT_BY_KEY,
  ELEMENT_CYCLES,
  GENERAL_BY_KEY,
  GENERAL_BY_ZH,
  GENERAL_TERMS,
  GROWTH_STAGES,
  GROWTH_STAGE_BY_KEY,
  GROWTH_STAGE_BY_ZH,
  INTERACTION_BY_ENUM,
  INTERACTION_BY_KEY,
  INTERACTION_TYPES,
  LIU_CHONG,
  LIU_HE,
  NA_YIN,
  NA_YIN_BY_GAN_ZHI,
  NA_YIN_BY_ZH,
  SAN_HE,
  SAN_HUI,
  SHEN_SHA,
  SHEN_SHA_BY_KEY,
  SHEN_SHA_BY_ZH,
  STEMS,
  STEM_BY_CHAR,
  STEM_BY_KEY,
  STEM_COMBINATIONS,
  TEN_GODS,
  TEN_GOD_BY_KEY,
  TERM_BY_KEY,
  TERM_BY_ZH,
  XIANG_HAI,
  XIANG_PO,
  XIANG_XING,
  branchByChar,
  elementOf,
  generalBy,
  generalByZh,
  growthStageByZh,
  interactionFromEnum,
  interactionFromZh,
  naYinOf,
  shenShaByZh,
  stemByChar,
  t,
  tenGodByZh,
  translate
};
//# sourceMappingURL=index.js.map