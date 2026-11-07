// 后端接口封装。所有路径都相对 BASE，开发时由 Vite 代理到 FastAPI。
//
// 身份是 `X-Anonymous-Id`：一个浏览器一个 id，存在 localStorage。
// 这不是登录，换浏览器就是另一个人——演示够用，也别假装更安全。

export type Mode = "rag" | "agent" | "multi";

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";
const ANON_KEY = "mingli.anon-id";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function anonymousId(): string {
  let value = localStorage.getItem(ANON_KEY);
  if (!value) {
    value =
      typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `anon-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    localStorage.setItem(ANON_KEY, value);
  }
  return value;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "X-Anonymous-Id": anonymousId(),
    ...(init.headers as Record<string, string> | undefined),
  };
  if (init.body) headers["Content-Type"] = "application/json";

  const resp = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!resp.ok) {
    let detail = `请求失败（${resp.status}）`;
    try {
      const body = await resp.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail)) detail = "参数不合法";
    } catch {
      /* 非 JSON 错误体，用默认文案 */
    }
    throw new ApiError(detail, resp.status);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

// ---------- 数据结构 ----------

export interface Conversation {
  id: string;
  title: string;
  summary: string | null;
  status: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface CitationRef {
  marker: number | null;
  chunk_id: number;
}

export interface RunSummary {
  id: string;
  conversation_id: string;
  trace_id: string;
  mode: Mode;
  question: string;
  status: "running" | "succeeded" | "refused" | "failed";
  can_answer: boolean | null;
  answer: string | null;
  refusal_reason: string | null;
  invalid_output: boolean;
  citations_chunk_ids: number[];
  citation_map: CitationRef[];
  elapsed_ms: number | null;
  llm_calls: number;
  total_tokens: number;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface ConversationDetail extends Conversation {
  messages: { id: number; role: string; content: string; created_at: string }[];
  runs: RunSummary[];
}

export interface Chunk {
  chunk_id: number;
  book: string;
  volume: string;
  chapter: string;
  title: string;
  text: string;
}

// ---------- 会话接口 ----------

export function listConversations(): Promise<Conversation[]> {
  return request<Conversation[]>("/v1/conversations");
}

export function createConversation(title?: string): Promise<Conversation> {
  return request<Conversation>("/v1/conversations", {
    method: "POST",
    body: JSON.stringify(title ? { title } : {}),
  });
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/v1/conversations/${id}`);
}

export function deleteConversation(id: string): Promise<void> {
  return request<void>(`/v1/conversations/${id}`, { method: "DELETE" });
}

export function lookupChunks(ids: number[]): Promise<Chunk[]> {
  const unique = Array.from(new Set(ids.filter((id) => Number.isFinite(id))));
  if (unique.length === 0) return Promise.resolve([]);
  return request<Chunk[]>("/chunks", {
    method: "POST",
    body: JSON.stringify({ ids: unique.slice(0, 20) }),
  });
}

// ---------- 流式问答 ----------

export interface StepEvent {
  agent: string;
  tool: string;
  args: Record<string, unknown> | null;
  ok: boolean | null;
  chunk_ids: number[];
  error: string | null;
}

export interface StageEvent {
  agent: string;
  detail: Record<string, unknown>;
}

export interface DonePayload extends Record<string, unknown> {
  answer: string;
  can_answer: boolean | null;
  citations_chunk_ids: number[];
  citation_map?: CitationRef[];
  refusal_reason: string | null;
  invalid_output: boolean;
  elapsed_ms: number;
  llm_calls: number;
  mode: Mode;
}

export interface StreamHandlers {
  onDelta?: (text: string) => void;
  onStep?: (step: StepEvent) => void;
  onStage?: (stage: StageEvent) => void;
  onDone?: (result: DonePayload) => void;
  onError?: (message: string) => void;
}

function parseFrame(raw: string): { event: string; data: unknown } | null {
  let event = "";
  const dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith(":")) continue; // 心跳注释
    if (line.startsWith("event: ")) event = line.slice(7).trim();
    else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
  }
  if (!event || dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

export async function streamChat(
  conversationId: string,
  body: { question: string; mode: Mode; top_k?: number; max_steps?: number },
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`${BASE}/v1/conversations/${conversationId}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Anonymous-Id": anonymousId(),
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!resp.ok) {
    let detail = `请求失败（${resp.status}）`;
    try {
      const payload = await resp.json();
      if (typeof payload?.detail === "string") detail = payload.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(detail, resp.status);
  }
  if (!resp.body) throw new ApiError("这条连接没有返回流", 0);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let cut = buffer.indexOf("\n\n");
    while (cut >= 0) {
      const frame = parseFrame(buffer.slice(0, cut));
      buffer = buffer.slice(cut + 2);
      if (frame) dispatch(frame.event, frame.data, handlers);
      cut = buffer.indexOf("\n\n");
    }
  }
}

function dispatch(event: string, data: unknown, handlers: StreamHandlers): void {
  switch (event) {
    case "delta":
      handlers.onDelta?.((data as { text?: string }).text ?? "");
      break;
    case "step":
      handlers.onStep?.(data as StepEvent);
      break;
    case "stage":
      handlers.onStage?.(data as StageEvent);
      break;
    case "done":
      handlers.onDone?.(data as DonePayload);
      break;
    case "error":
      handlers.onError?.((data as { message?: string }).message ?? "生成失败");
      break;
    default:
      break;
  }
}
