// 空会话：一句介绍 + 几个真能问的问题。
const SUGGESTIONS = [
  "天乙贵人怎么查，落在哪一柱才算？",
  "七杀与偏官是不是一回事？",
  "子平真诠论用神，关键在哪几句？",
  "三命通会和滴天髓对格局的说法有什么不同？",
];

export function EmptyState({ onPick }: { onPick: (question: string) => void }) {
  return (
    <div className="empty">
      <div className="empty__seal" aria-hidden="true">
        问
      </div>
      <h1 className="empty__title">回到原书里找答案</h1>
      <p className="empty__lead">
        四十五部古籍文献（含术数类史料）、八千余节正文。回答逐字生成，每一处引用都能展开看原文。
      </p>

      <div className="empty__asks">
        {SUGGESTIONS.map((question) => (
          <button key={question} type="button" className="ask" onClick={() => onPick(question)}>
            <span className="ask__mark">问</span>
            <span>{question}</span>
          </button>
        ))}
      </div>

      <p className="empty__foot">也可以直接贴一段原文，让书里的话来对。</p>
    </div>
  );
}
