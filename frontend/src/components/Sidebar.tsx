// 左侧：牌记 + 新建 + 会话列表。删除要点两下，避免误触。
import { useEffect, useRef, useState } from "react";

import type { Conversation } from "../api";
import { formatWhen } from "../format";

export type View = "chat" | "fortune" | "memory";

interface Props {
  conversations: Conversation[];
  activeId: string | null;
  loading: boolean;
  streaming: boolean;
  view: View;
  onView: (view: View) => void;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRemove: (id: string) => void;
}

const NAV: { key: View; label: string; mark: string }[] = [
  { key: "chat", label: "对话", mark: "问" },
  { key: "fortune", label: "排盘", mark: "盘" },
  { key: "memory", label: "记忆", mark: "忆" },
];

export function Sidebar({
  conversations,
  activeId,
  loading,
  streaming,
  view,
  onView,
  onSelect,
  onNew,
  onRemove,
}: Props) {
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current != null) window.clearTimeout(timer.current);
    },
    [],
  );

  const remove = (id: string) => {
    if (confirmId !== id) {
      setConfirmId(id);
      if (timer.current != null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setConfirmId(null), 2600);
      return;
    }
    setConfirmId(null);
    onRemove(id);
  };

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand__seal" aria-hidden="true">
          问
        </span>
        <div className="brand__text">
          <span className="brand__name">问古</span>
          <span className="brand__sub">古籍问答</span>
        </div>
      </div>

      <nav className="nav" aria-label="主导航">
        {NAV.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`nav__item${view === item.key ? " nav__item--on" : ""}`}
            onClick={() => onView(item.key)}
            aria-current={view === item.key ? "page" : undefined}
          >
            <span className="nav__mark" aria-hidden="true">
              {item.mark}
            </span>
            {item.label}
          </button>
        ))}
      </nav>

      {view === "chat" && (
        <button type="button" className="new-btn" onClick={onNew} disabled={streaming}>
          <span aria-hidden="true">＋</span> 新对话
        </button>
      )}

      {view === "chat" && (
        <div className="conv-list" role="list">
          {loading && conversations.length === 0 && (
            <p className="conv-list__tip">正在取会话…</p>
          )}
          {!loading && conversations.length === 0 && (
            <p className="conv-list__tip">还没有对话。问一句，就从这里开始。</p>
          )}
          {conversations.map((conv) => {
            const active = conv.id === activeId;
            const confirming = confirmId === conv.id;
            return (
              <div
                key={conv.id}
                role="listitem"
                className={`conv${active ? " conv--on" : ""}`}
              >
                <button type="button" className="conv__main" onClick={() => onSelect(conv.id)}>
                  <span className="conv__title">{conv.title || "未命名"}</span>
                  <span className="conv__meta">
                    {formatWhen(conv.updated_at)} · {conv.message_count} 则
                  </span>
                </button>
                <button
                  type="button"
                  className={`conv__del${confirming ? " conv__del--armed" : ""}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    remove(conv.id);
                  }}
                  aria-label={confirming ? "确认删除" : "删除这条会话"}
                  title={confirming ? "再点一次就删" : "删除"}
                >
                  {confirming ? "删" : "×"}
                </button>
              </div>
            );
          })}
        </div>
      )}

      <div className="sidebar__foot">
        <span>四十五部</span>
        <span className="dot" aria-hidden="true">·</span>
        <span>八千六百八十一节</span>
      </div>
    </aside>
  );
}
