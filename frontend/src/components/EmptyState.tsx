// 空白对话：直接给四个真能问的问题，点一条就发出去。
const SUGGESTIONS = [
  "天乙贵人怎么查，落在哪一柱才算？",
  "七杀与偏官是不是一回事？",
  "子平真诠论用神，关键在哪几句？",
  "三命通会和滴天髓对格局的说法有什么不同？",
];

export function EmptyState({ onPick }: { onPick: (question: string) => void }) {
  return (
    <div className="empty">
      <div className="empty__asks" role="group" aria-label="示例问题">
        {SUGGESTIONS.map((question) => (
          <button key={question} type="button" className="ask" onClick={() => onPick(question)}>
            {question}
          </button>
        ))}
      </div>
    </div>
  );
}
