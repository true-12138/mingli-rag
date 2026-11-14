// 对话页：顶栏 + 正文流 + 输入区。
// 状态留在 App 的 useChat 里，切到排盘页再切回来不会丢正在生成的回答。
import { useCallback, useEffect, useRef, useState } from "react";

import { ActionCard } from "../components/ActionCard";
import { Composer } from "../components/Composer";
import { EmptyState } from "../components/EmptyState";
import { TurnView } from "../components/TurnView";
import { MenuIcon } from "../components/icons";
import { listPendingActions, type Mode, type PendingAction } from "../api";
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
  // 从服务端补回来的待确认项：刷新/切回会话后，chat 响应里的 pending_actions
  // 已经不在内存里，但动作还在库里等着确认。
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([]);

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
  }, [chat.turns, pendingActions]);

  // 打开已有会话（含刷新后自动打开最近一条）时补拉该会话的待确认动作。
  // 只拉一次；后续 chat 响应带来的动作走 turns，不在这里重复订阅。
  useEffect(() => {
    const id = chat.activeId;
    if (!id) {
      setPendingActions([]);
      return;
    }
    // 先清空再拉：切会话的一瞬间不要把上一个会话的卡片显示在新会话里。
    setPendingActions([]);
    let cancelled = false;
    void (async () => {
      try {
        const actions = await listPendingActions(20, id);
        if (!cancelled) setPendingActions(actions.filter((a) => a.status === "pending"));
      } catch {
        // 补拉失败不影响对话本身；下一次打开这个会话会再试。
        if (!cancelled) setPendingActions([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chat.activeId]);

  // 拒绝成功或允许后已提交继续：从补拉列表里移除这张卡片。
  const resolvePending = useCallback((id: number) => {
    setPendingActions((prev) => prev.filter((action) => action.id !== id));
  }, []);

  const send = useCallback(
    (question: string) => {
      stickRef.current = true;
      void chat.send(question, mode);
    },
    [chat, mode],
  );

  // 用户点「让助手继续」：沿用该轮的问题和模式，只多带一个一次性令牌。
  const continueWith = useCallback(
    (question: string, turnMode: Mode, approvals: string[]) => {
      stickRef.current = true;
      void chat.send(question, turnMode, approvals);
    },
    [chat],
  );

  // 同一条动作按 id 去重：chat 响应里已经渲染过的，不再从补拉列表重复渲染。
  const turnActionIds = new Set(
    chat.turns.flatMap((turn) => turn.actions.map((action) => action.id)),
  );
  const seenActionIds = new Set<number>();
  const restoredActions = pendingActions.filter((action) => {
    if (turnActionIds.has(action.id) || seenActionIds.has(action.id)) return false;
    seenActionIds.add(action.id);
    return true;
  });
  // 补拉的动作不知道原本属于哪一轮：沿用最后一轮的问题和模式，
  // 用户点「让助手继续」时能接着刚才的上下文发请求。
  const anchorTurn = chat.turns[chat.turns.length - 1];

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
                busy={chat.streaming}
                onAsk={send}
                onContinue={continueWith}
              />
            ))
          )}
          {chat.loadingThread && <div className="thread__loading">正在打开会话…</div>}

          {restoredActions.length > 0 && (
            <div className="actions" aria-label="待确认的工具调用">
              {restoredActions.map((action) => (
                <ActionCard
                  key={action.id}
                  action={action}
                  question={anchorTurn?.question ?? ""}
                  mode={anchorTurn?.mode ?? mode}
                  busy={chat.streaming}
                  onContinue={continueWith}
                  onResolved={resolvePending}
                />
              ))}
            </div>
          )}
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
