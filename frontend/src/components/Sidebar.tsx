// 左侧：牌记 + 新建 + 会话列表。删除要点两下，避免误触。
import { useEffect, useRef, useState } from "react";

import type { Conversation } from "../api";
import { formatWhen } from "../format";

export type View =
  | "chart"
  | "physiognomy"
  | "memory"
  | "materials"
  | "about";

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

// 问答不再是单独板块：术数页面右侧都常驻对话栏，
// 侧栏的会话列表因此一直显示，切页签也能接着上一轮问。
// 星盘并进命盘页当页签，侧栏不再单列。
const NAV: { key: View; label: string }[] = [
  { key: "chart", label: "命盘" },
  { key: "physiognomy", label: "相术" },
  { key: "memory", label: "记忆" },
  { key: "materials", label: "素材" },
  { key: "about", label: "关于" },
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
        <span className="brand__name">问古</span>
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
            {item.label}
          </button>
        ))}
      </nav>

      <button type="button" className="new-btn" onClick={onNew} disabled={streaming}>
        <span aria-hidden="true">＋</span> 新对话
      </button>

      <div className="conv-list" role="list">
        {loading && conversations.length === 0 && (
          <p className="conv-list__tip">正在取会话…</p>
        )}
        {!loading && conversations.length === 0 && (
          <p className="conv-list__tip">还没有对话</p>
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

    </aside>
  );
}
