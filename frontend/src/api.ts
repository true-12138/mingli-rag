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
      else if (typeof body?.detail?.message === "string") detail = body.detail.message;
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

export interface Memory {
  id: number;
  kind: "preference" | "fact";
  key: string;
  value: string;
  confidence: number;
  // pending：value 之外还有一个新值在等确认；value 始终是生效值
  status: "active" | "pending";
  pending_value: string | null;
  pending_confidence: number | null;
  version: number;
  updated_at: string;
}

// 模型提议、但被权限层拦下的有副作用工具调用。args 已是对象，不用再解析字符串。
export interface PendingAction {
  id: number;
  tool: string;
  args: unknown;
  reason: string | null;
  status: string;
  created_at: string;
}

export interface ActionApprove {
  // 一次性令牌只返回这一次，默认 10 分钟后过期；前端不要持久化。
  token: string;
  expires_at: string;
}

export interface ActionState {
  id: number;
  status: string;
}

// ---------- 排盘 ----------

export type FortuneKind = "bazi" | "astro" | "tarot";

export interface BirthInput {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

export interface BaziInput extends BirthInput {
  gender: "male" | "female";
}

export interface AstroInput extends BirthInput {
  tz: number;
  lat: number;
  lon: number;
  city: string;
}

export interface TarotInput {
  spread: "single" | "three" | "cross";
  seed?: number | null;
}

export interface BaziChart {
  kind: "bazi";
  input: {
    solar: string;
    lunar: string;
    gender: "male" | "female";
    year: number;
    month: number;
    day: number;
    hour: number;
    minute: number;
  };
  sizhu: Record<string, string>;
  rizhu: string;
  day_master: string;
  shengxiao: string;
  canggan: Record<string, string[]>;
  shishen_gan: Record<string, string>;
  shishen_zhi: Record<string, string[]>;
  nayin: Record<string, string>;
  wuxing: Record<string, number>;
  wuxing_missing: string[];
  xunkong: Record<string, string>;
  taiyuan: string;
  minggong: string;
  shengong: string;
  qiyun: { years: number; months: number; days: number; forward: boolean };
  dayun: { start_year: number; start_age: number; ganzhi: string }[];
  current_dayun: { start_year: number; start_age: number; ganzhi: string } | null;
  text: string;
}

export interface AstroChart {
  kind: "astro";
  input: { solar: string; utc: string; city: string; lat: number; lon: number; tz: number };
  planets: {
    name: string;
    lon: number;
    sign: string;
    degree: number;
    retrograde: boolean;
    house: number;
  }[];
  asc: { sign: string; degree: number; lon: number };
  mc: { sign: string; degree: number; lon: number };
  houses: { house: number; sign: string }[];
  aspects: { a: string; b: string; aspect: string; angle: number; orb: number }[];
  elements: Record<string, number>;
  modalities: Record<string, number>;
  house_system: string;
  text: string;
}

export interface TarotChart {
  kind: "tarot";
  spread: string;
  seed: number | null;
  cards: {
    position: string;
    name: string;
    arcana: string;
    orientation: string;
    meaning: string;
    card_id: number;
  }[];
  text: string;
}

export type FortuneChart = BaziChart | AstroChart | TarotChart;

// 排盘信息不够时，后端返回「还缺什么」，由这里渲染成追问表单。
export interface IntakeField {
  name: string;
  label: string;
  ask: string;
  type: "int" | "float" | "str" | "enum";
  required: boolean;
  min?: number;
  max?: number;
  max_length?: number;
  options?: string[];
  option_labels?: Record<string, string>;
  example?: number | string;
  error?: string;
  value?: unknown;
}

export interface IntakeNeedInput {
  status: "need_input";
  kind: FortuneKind;
  reason: "missing" | "invalid" | "calendar";
  known: Record<string, unknown>;
  fields: IntakeField[];
  message: string;
}

export interface IntakeReady {
  status: "ready";
  kind: FortuneKind;
  params: Record<string, unknown>;
  defaults: Record<string, unknown>;
  ignored: string[];
  warnings: string[];
  chart: FortuneChart;
}

export type IntakeResult = IntakeNeedInput | IntakeReady;

export interface FortuneReading {
  kind: FortuneKind;
  summary: string;
  sections: { title: string; content: string }[];
  disclaimer: string;
  parse_error?: boolean;
}

export function listMemories(): Promise<Memory[]> {
  return request<Memory[]>("/v1/memories");
}

export function deleteMemory(id: number): Promise<void> {
  return request<void>(`/v1/memories/${id}`, { method: "DELETE" });
}

// 带上页面读到的 version：记忆已经在别的标签页被改过时后端返回 409，
// 前端刷新而不是假装确认成功。
export function confirmMemory(id: number, version?: number): Promise<Memory> {
  return request<Memory>(`/v1/memories/${id}/confirm`, {
    method: "POST",
    body: JSON.stringify({ version: version ?? null }),
  });
}

export function rejectMemory(id: number, version?: number): Promise<Memory> {
  return request<Memory>(`/v1/memories/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ version: version ?? null }),
  });
}

// 先把已知信息交给后端检查：齐了直接带盘回来，不齐就返回要补的字段。
// 默认值只用于可选字段，并在 warnings 里说明。
export function intakeFortune(
  kind: FortuneKind,
  params: Record<string, unknown>,
): Promise<IntakeResult> {
  return request<IntakeResult>("/v1/fortune/intake", {
    method: "POST",
    body: JSON.stringify({ kind, params }),
  });
}

export function drawBazi(input: BaziInput): Promise<BaziChart> {
  return request<BaziChart>("/v1/fortune/bazi", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function drawAstro(input: AstroInput): Promise<AstroChart> {
  return request<AstroChart>("/v1/fortune/astro", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function drawTarot(input: TarotInput): Promise<TarotChart> {
  return request<TarotChart>("/v1/fortune/tarot", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function readFortune(
  kind: FortuneKind,
  params: Record<string, unknown>,
  question?: string,
  note?: string,
): Promise<FortuneReading> {
  // 解读可能调用模型，等得比普通请求久；
  // key 不从前端传，走服务端环境变量。
  return request<FortuneReading>("/v1/fortune/read", {
    method: "POST",
    body: JSON.stringify({ kind, params, question: question || null, note: note || null }),
  });
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

// ---------- 待确认动作 ----------

export function listPendingActions(limit = 20): Promise<PendingAction[]> {
  return request<PendingAction[]>(`/v1/actions?limit=${limit}`);
}

// 确认后拿到一次性令牌；只有模型下次真的调用同一个工具时才会消费。
export function approveAction(id: number): Promise<ActionApprove> {
  return request<ActionApprove>(`/v1/actions/${id}/approve`, { method: "POST" });
}

export function rejectAction(id: number): Promise<ActionState> {
  return request<ActionState>(`/v1/actions/${id}/reject`, { method: "POST" });
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
  pending_actions?: PendingAction[];
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
  body: {
    question: string;
    mode: Mode;
    top_k?: number;
    max_steps?: number;
    // 用户确认动作后拿到的一次性令牌；后端只在模型再次调用该工具时消费。
    approvals?: string[];
  },
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
