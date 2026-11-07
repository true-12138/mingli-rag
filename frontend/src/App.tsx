import { useCallback, useEffect, useRef, useState } from "react";

import { Composer } from "./components/Composer";
import { EmptyState } from "./components/EmptyState";
import { Sidebar } from "./components/Sidebar";
import { TurnView } from "./components/TurnView";
import type { Mode } from "./api";
import { useChat } from "./useChat";

export default function App() {
  const chat = useChat();
  const [mode, setMode] = useState<Mode>("rag");
  const [drawer, setDrawer] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  const activeTitle =
    chat.conversations.find((conv) => conv.id === chat.activeId)?.title ?? "新对话";

  // 只在用户本来就贴着底部时才跟随；往上翻旧内容时不被拽回去
  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [chat.turns]);

  const send = useCallback(
    (question: string) => {
      stickRef.current = true;
      void chat.send(question, mode);
      setDrawer(false);
    },
    [chat, mode],
  );

  return (
    <div className={`app${drawer ? " app--drawer" : ""}`}>
      <Sidebar
        conversations={chat.conversations}
        activeId={chat.activeId}
        loading={chat.loadingList}
        streaming={chat.streaming}
        onSelect={(id) => {
          chat.select(id);
          setDrawer(false);
        }}
        onNew={() => {
          chat.startNew();
          setDrawer(false);
        }}
        onRemove={chat.remove}
      />

      <div className="scrim" onClick={() => setDrawer(false)} aria-hidden="true" />

      <main className="main">
        <header className="topbar">
          <button
            className="icon-btn drawer-toggle"
            onClick={() => setDrawer((open) => !open)}
            aria-label="会话列表"
          >
            <MenuIcon />
          </button>
          <div className="topbar__title" title={activeTitle}>
            {activeTitle}
          </div>
          <div className="topbar__meta">{modeLabel(mode)}</div>
        </header>

        {chat.fatal && (
          <div className="banner" role="alert">
            <span>{chat.fatal}</span>
            <button className="banner__close" onClick={chat.clearFatal} aria-label="关闭">
              ×
            </button>
          </div>
        )}

        <div className="thread" ref={scrollRef} onScroll={onScroll}>
          <div className="thread__inner">
            {chat.turns.length === 0 && !chat.loadingThread ? (
              <EmptyState onPick={send} />
            ) : (
              chat.turns.map((turn) => (
                <TurnView
                  key={turn.key}
                  turn={turn}
                  chunks={chat.chunks}
                  streaming={chat.streaming && turn.status === "streaming"}
                  onAsk={send}
                />
              ))
            )}
            {chat.loadingThread && <div className="thread__loading">正在打开会话…</div>}
          </div>
        </div>

        <Composer
          mode={mode}
          onModeChange={setMode}
          streaming={chat.streaming}
          onSend={send}
          onStop={chat.stop}
        />
      </main>
    </div>
  );
}

function modeLabel(mode: Mode): string {
  switch (mode) {
    case "agent":
      return "查证后回答";
    case "multi":
      return "多书对照";
    default:
      return "原文直答";
  }
}

function MenuIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true">
      <path d="M2.5 5h13M2.5 9h13M2.5 13h9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}
