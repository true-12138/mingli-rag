// 右侧问答栏：命盘 / 星盘 / 相术三个页面共用同一份对话状态。
//
// 古籍问答不再是单独板块：盘面一生成就挂到对话上，用户直接在旁边追问，
// 不必再「带着盘跳去另一个页面」。状态仍然留在 App 的 useChat 里，
// 换页签、换页面都不会丢正在生成的回答。
import { useCallback, useEffect, useRef, useState } from "react";

import { ActionCard } from "./ActionCard";
import { Composer } from "./Composer";
import { EmptyState } from "./EmptyState";
import { TurnView } from "./TurnView";
import { chartPlaceholder, chartSuggestions } from "../chartPrompts";
import { listPendingActions, type FortuneChart, type Mode, type PendingAction } from "../api";
import type { useChat } from "../useChat";

interface Props {
  chat: ReturnType<typeof useChat>;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  // 小屏时侧栏收进抽屉，这一栏自己的「新对话」是唯一入口
  onNew: () => void;
  // 空白对话的示例问题：按页面给，星盘/相术页不再显示八字题
  suggestions?: readonly string[];
}

export function ChatColumn({ chat, mode, onModeChange, onNew, suggestions }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([]);

  // 没有会话时标题固定成「问盘」，免得和右边的「＋ 新对话」重复。
  // 盘面刚挂上、还没开口时，标题直接改成「问这张盘」——
  // 这是整页最显眼的一行字，用户一眼能看出问答已经和盘连上了。
  const activeTitle =
    chat.conversations.find((conv) => conv.id === chat.activeId)?.title ??
    (chat.chart ? "问这张盘" : "问盘");

  // 挂上盘之后，示例问题换成从这张盘推出来的（日主、月柱十神、自述特征）。
  const emptySuggestions = chartSuggestions(chat.chart) ?? suggestions;

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
  useEffect(() => {
    const id = chat.activeId;
    if (!id) {
      setPendingActions([]);
      return;
    }
    setPendingActions([]);
    let cancelled = false;
    void (async () => {
      try {
        const actions = await listPendingActions(20, id);
        if (!cancelled) setPendingActions(actions.filter((a) => a.status === "pending"));
      } catch {
        if (!cancelled) setPendingActions([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chat.activeId]);

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

  const continueWith = useCallback(
    (question: string, turnMode: Mode, approvals: string[]) => {
      stickRef.current = true;
      void chat.send(question, turnMode, approvals);
    },
    [chat],
  );

  const turnActionIds = new Set(
    chat.turns.flatMap((turn) => turn.actions.map((action) => action.id)),
  );
  const seenActionIds = new Set<number>();
  const restoredActions = pendingActions.filter((action) => {
    if (turnActionIds.has(action.id) || seenActionIds.has(action.id)) return false;
    seenActionIds.add(action.id);
    return true;
  });
  const anchorTurn = chat.turns[chat.turns.length - 1];

  return (
    <aside className="chat-pane" aria-label="问盘">
      <header className="chat-pane__head">
        <div className="chat-pane__title" title={activeTitle}>
          {activeTitle}
        </div>
        <button
          type="button"
          className="chat-pane__new"
          onClick={onNew}
          disabled={chat.streaming}
          title="开一条新对话"
        >
          ＋ 新对话
        </button>
      </header>

      {chat.chart && (
        <div
          className="chart-note"
          role="status"
          title="之后的追问都会带上这张盘"
        >
          <span className="chart-note__tag">本盘</span>
          <span className="chart-note__text">{chartLabel(chat.chart)}</span>
          <button
            type="button"
            className="chart-note__close"
            onClick={chat.clearChart}
            aria-label="移除盘面"
            title="移除盘面，之后的追问不再带这张盘"
          >
            ×
          </button>
        </div>
      )}

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
            <EmptyState onPick={send} suggestions={emptySuggestions} />
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
        placeholder={chartPlaceholder(chat.chart)}
        onSend={send}
        onStop={chat.stop}
      />
    </aside>
  );
}

function chartLabel(chart: FortuneChart): string {
  switch (chart.kind) {
    case "bazi":
      return `八字 · 日主${chart.day_master} · 日柱${chart.sizhu["日柱"] ?? ""}`;
    case "astro":
      return `星盘 · 上升${chart.asc.sign}`;
    case "tarot":
      return `塔罗 · ${chart.cards.length} 张`;
    case "physiognomy": {
      const count = Object.values(chart.features).filter(Boolean).length;
      return `${chart.subject} · ${count} 项特征`;
    }
    case "name":
      return `姓名 · ${chart.full} · 三才${chart.sancai.combo}`;
    default:
      return "盘面";
  }
}
