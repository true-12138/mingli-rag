// 对话页：顶栏 + 正文流 + 输入区。
// 状态留在 App 的 useChat 里，切到排盘页再切回来不会丢正在生成的回答。
import { useCallback, useEffect, useRef } from "react";

import { Composer } from "../components/Composer";
import { EmptyState } from "../components/EmptyState";
import { TurnView } from "../components/TurnView";
import { MenuIcon } from "../components/icons";
import type { Mode } from "../api";
import type { useChat } from "../useChat";

interface Props {
  chat: ReturnType<typeof useChat>;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  onOpenDrawer: () => void;
}

export function ChatPage({ chat, mode, onModeChange, onOpenDrawer }: Props) {
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
    },
    [chat, mode],
  );

  return (
    <>
      <header className="topbar">
        <button className="icon-btn drawer-toggle" onClick={onOpenDrawer} aria-label="会话列表">
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
        onModeChange={onModeChange}
        streaming={chat.streaming}
        onSend={send}
        onStop={chat.stop}
      />
    </>
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
