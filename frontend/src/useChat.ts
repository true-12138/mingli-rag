// 对话状态：会话列表、当前会话、流式回答。
//
// 一条原则：流式过程中的本地状态是唯一真相，不要用重新拉取的会话详情去覆盖它。
// 只有切会话 / 刷新页面时才从服务端重建。
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  lookupChunks,
  streamChat,
  type Chunk,
  type CitationRef,
  type Conversation,
  type DonePayload,
  type Mode,
  type PendingAction,
  type RunSummary,
  type StageEvent,
  type StepEvent,
} from "./api";

export type TurnStatus = "streaming" | "done" | "error" | "stopped";

export interface Turn {
  key: string;
  question: string;
  mode: Mode;
  answer: string;
  status: TurnStatus;
  stages: StageEvent[];
  steps: StepEvent[];
  actions: PendingAction[];
  citationIds: number[];
  citationMap: CitationRef[];
  canAnswer: boolean | null;
  refusalReason: string | null;
  invalidOutput: boolean;
  error: string | null;
  elapsedMs: number | null;
  llmCalls: number | null;
}

function emptyTurn(key: string, question: string, mode: Mode): Turn {
  return {
    key,
    question,
    mode,
    answer: "",
    status: "streaming",
    stages: [],
    steps: [],
    actions: [],
    citationIds: [],
    citationMap: [],
    canAnswer: null,
    refusalReason: null,
    invalidOutput: false,
    error: null,
    elapsedMs: null,
    llmCalls: null,
  };
}

function turnFromRun(run: RunSummary): Turn {
  return {
    key: run.id,
    question: run.question,
    mode: run.mode,
    answer: run.answer ?? "",
    status: run.status === "failed" ? "error" : "done",
    stages: [],
    steps: [],
    actions: [],
    citationIds: run.citations_chunk_ids ?? [],
    citationMap: run.citation_map ?? [],
    canAnswer: run.can_answer,
    refusalReason: run.refusal_reason,
    invalidOutput: run.invalid_output,
    error: run.error,
    elapsedMs: run.elapsed_ms,
    llmCalls: run.llm_calls,
  };
}

const newKey = () =>
  typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;

export function useChat() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [chunks, setChunks] = useState<Record<number, Chunk>>({});
  const [loadingList, setLoadingList] = useState(true);
  const [loadingThread, setLoadingThread] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [fatal, setFatal] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const loadTokenRef = useRef(0);
  const chunksRef = useRef<Record<number, Chunk>>({});
  // 刚建的会话紧接着就要发第一条：别让「切换会话」的加载把它清空
  const skipLoadRef = useRef<string | null>(null);

  const hydrate = useCallback(async (ids: number[]) => {
    const missing = Array.from(new Set(ids)).filter((id) => !chunksRef.current[id]);
    if (missing.length === 0) return;
    try {
      const fetched = await lookupChunks(missing);
      if (fetched.length === 0) return;
      const next = { ...chunksRef.current };
      for (const chunk of fetched) next[chunk.chunk_id] = chunk;
      chunksRef.current = next;
      setChunks(next);
    } catch {
      // 引用展开失败不影响回答本身，下次点开再取
    }
  }, []);

  const patchTurn = useCallback((key: string, patch: (turn: Turn) => Turn) => {
    setTurns((prev) => prev.map((turn) => (turn.key === key ? patch(turn) : turn)));
  }, []);

  const refreshList = useCallback(async () => {
    try {
      const list = await listConversations();
      setConversations(list);
      return list;
    } catch (err) {
      setFatal(err instanceof ApiError ? err.message : "会话列表加载失败");
      return [];
    } finally {
      setLoadingList(false);
    }
  }, []);

  // 首次进入：拉列表并打开最近一条会话
  useEffect(() => {
    void (async () => {
      const list = await refreshList();
      if (list.length > 0) setActiveId((current) => current ?? list[0].id);
    })();
  }, [refreshList]);

  // 切换会话：从服务端重建整条对话
  useEffect(() => {
    if (!activeId) {
      setTurns([]);
      return;
    }
    if (skipLoadRef.current === activeId) {
      skipLoadRef.current = null;
      setLoadingThread(false);
      return;
    }
    const token = ++loadTokenRef.current;
    setLoadingThread(true);
    setFatal(null);
    void (async () => {
      try {
        const detail = await getConversation(activeId);
        if (token !== loadTokenRef.current) return; // 用户已经切走
        const restored = detail.runs.map(turnFromRun);
        setTurns(restored);
        void hydrate(restored.flatMap((turn) => turn.citationIds));
      } catch (err) {
        if (token !== loadTokenRef.current) return;
        setTurns([]);
        setFatal(err instanceof ApiError ? err.message : "这条会话打不开");
      } finally {
        if (token === loadTokenRef.current) setLoadingThread(false);
      }
    })();
  }, [activeId, hydrate]);

  const send = useCallback(
    async (rawQuestion: string, mode: Mode, approvals: string[] = []) => {
      const question = rawQuestion.trim();
      if (!question || streaming) return;

      let conversationId = activeId;
      try {
        if (!conversationId) {
          const created = await createConversation(question.slice(0, 30));
          conversationId = created.id;
          skipLoadRef.current = created.id;
          setActiveId(created.id);
          setConversations((prev) => [created, ...prev]);
        }
      } catch (err) {
        setFatal(err instanceof ApiError ? err.message : "新会话建不出来");
        return;
      }

      const key = newKey();
      setTurns((prev) => [...prev, emptyTurn(key, question, mode)]);
      const controller = new AbortController();
      abortRef.current = controller;
      setStreaming(true);
      setFatal(null);

      try {
        await streamChat(
          conversationId,
          {
            question,
            mode,
            // 只有用户确认过动作才带令牌；空数组不必发给后端。
            ...(approvals.length > 0 ? { approvals } : {}),
          },
          {
            onDelta: (text) =>
              patchTurn(key, (turn) => ({ ...turn, answer: turn.answer + text })),
            onStep: (step) =>
              patchTurn(key, (turn) => ({ ...turn, steps: [...turn.steps, step] })),
            onStage: (stage) =>
              patchTurn(key, (turn) => ({ ...turn, stages: [...turn.stages, stage] })),
            onDone: (result: DonePayload) => {
              patchTurn(key, (turn) => ({
                ...turn,
                // done.answer 是终稿：拒答归一化会改正文，delta 只是预览
                answer: result.answer ?? turn.answer,
                status: "done",
                actions: result.pending_actions ?? [],
                citationIds: result.citations_chunk_ids ?? [],
                citationMap: result.citation_map ?? [],
                canAnswer: result.can_answer,
                refusalReason: result.refusal_reason,
                invalidOutput: Boolean(result.invalid_output),
                elapsedMs: result.elapsed_ms ?? null,
                llmCalls: result.llm_calls ?? null,
              }));
              void hydrate(result.citations_chunk_ids ?? []);
            },
            onError: (message) =>
              patchTurn(key, (turn) => ({ ...turn, status: "error", error: message })),
          },
          controller.signal,
        );
      } catch (err) {
        if (controller.signal.aborted) {
          patchTurn(key, (turn) => ({ ...turn, status: "stopped" }));
        } else {
          patchTurn(key, (turn) => ({
            ...turn,
            status: "error",
            error: err instanceof ApiError ? err.message : "连接中断了",
          }));
        }
      } finally {
        abortRef.current = null;
        setStreaming(false);
        void refreshList();
      }
    },
    [activeId, hydrate, patchTurn, refreshList, streaming],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const startNew = useCallback(() => {
    if (streaming) return;
    setActiveId(null);
    setTurns([]);
  }, [streaming]);

  const remove = useCallback(
    async (id: string) => {
      try {
        await deleteConversation(id);
      } catch {
        /* 删失败就保持原样，下一次刷新会说明问题 */
      }
      setConversations((prev) => prev.filter((conv) => conv.id !== id));
      if (activeId === id) {
        setActiveId(null);
        setTurns([]);
      }
    },
    [activeId],
  );

  // 切走正在生成的会话时先停流，否则那段文字会落在已卸载的列表里
  const select = useCallback(
    (id: string | null) => {
      if (streaming) abortRef.current?.abort();
      setActiveId(id);
    },
    [streaming],
  );

  return {
    conversations,
    activeId,
    turns,
    chunks,
    loadingList,
    loadingThread,
    streaming,
    fatal,
    select,
    send,
    stop,
    startNew,
    remove,
    clearFatal: () => setFatal(null),
  };
}
