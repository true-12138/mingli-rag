// 空白对话：按当前页面给三四个真能问到古籍的问题，点一条就发出去。
// 问题都对着语料里的词写（五岳、剑眉、七政四余、掌厚薄……），点开就能被检索到。
export const SUGGESTIONS = {
  bazi: [
    "天乙贵人怎么查，落在哪一柱才算？",
    "七杀与偏官是不是一回事？",
    "子平真诠论用神，关键在哪几句？",
    "三命通会和滴天髓对格局的说法有什么不同？",
  ],
  astro: [
    "七政四余里，命宫是怎么立的？",
    "星学大成怎么定宫主？",
    "紫气、月孛、罗喉、计都各主什么？",
    "二十八宿在星命里怎么用？",
  ],
  face: [
    "五岳在相书里指哪几处？",
    "剑眉在古籍里怎么论？",
    "悬胆鼻的说法出自哪本相书？",
    "垂珠耳主什么？",
  ],
  palm: [
    "掌厚和掌薄，古书分别怎么说？",
    "土形掌有什么特征？",
    "金井纹在掌中主什么？",
    "直纹多和横纹多分别主什么？",
    "掌心红润在相法里是什么意思？",
  ],
} as const;

export function EmptyState({
  onPick,
  suggestions = SUGGESTIONS.bazi,
}: {
  onPick: (question: string) => void;
  suggestions?: readonly string[];
}) {
  return (
    <div className="empty">
      <div className="empty__asks" role="group" aria-label="示例问题">
        {suggestions.map((question) => (
          <button key={question} type="button" className="ask" onClick={() => onPick(question)}>
            {question}
          </button>
        ))}
      </div>
    </div>
  );
}
