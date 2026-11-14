// 待确认的工具调用：模型提议、权限层拦下，由用户在这里放行或拒绝。
//
// 一次性令牌只留在本组件内存里，过期即丢弃；不写 localStorage，也不放进任何全局状态。
import { useEffect, useState } from "react";

import {
  ApiError,
  approveAction,
  rejectAction,
  type Mode,
  type PendingAction,
} from "../api";

interface Props {
  action: PendingAction;
  /** 沿用上一轮的问题文本；后端靠 history 理解上下文。 */
  question: string;
  mode: Mode;
  /** 有回答正在生成时不允许再发下一条。 */
  busy: boolean;
  onContinue: (question: string, mode: Mode, approvals: string[]) => void;
  /**
   * 卡片已经不再是「待确认」时通知父级（拒绝成功，或允许后已提交继续）。
   * 刷新后恢复的卡片据此从待确认区域移除；允许成功但还没继续时保留卡片，
   * 否则一次性令牌会随组件卸载丢掉，工具再也执行不了。
   */
  onResolved?: (id: number) => void;
}

type Phase =
  | "pending"
  | "approving"
  | "allowed"
  | "expired"
  | "rejecting"
  | "rejected"
  | "submitted";

const STATE_LABEL: Record<Phase, string> = {
  pending: "待确认",
  approving: "确认中",
  allowed: "已允许",
  expired: "已过期",
  rejecting: "处理中",
  rejected: "已拒绝",
  submitted: "已允许",
};

const TOOL_LABELS: Record<string, string> = {
  save_note: "保存笔记",
  create_note: "新建笔记",
  update_note: "更新笔记",
  delete_note: "删除笔记",
  send_email: "发送邮件",
  send_message: "发送消息",
  create_event: "创建日程",
  create_calendar_event: "创建日程",
  create_reminder: "创建提醒",
  create_task: "创建任务",
  add_todo: "添加待办",
  write_file: "写入文件",
  delete_file: "删除文件",
  http_post: "发起外部请求",
};

const DEFAULT_REASON = "这个操作会修改外部状态，需要你确认后才会执行。";

export function ActionCard({
  action,
  question,
  mode,
  busy,
  onContinue,
  onResolved,
}: Props) {
  const [phase, setPhase] = useState<Phase>("pending");
  const [token, setToken] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 到点自动作废：卡片切到「已过期」，令牌不再留在内存里。
  useEffect(() => {
    if (phase !== "allowed" || expiresAt == null) return;
    const left = expiresAt - Date.now();
    if (left <= 0) {
      setToken(null);
      setExpiresAt(null);
      setPhase("expired");
      return;
    }
    const timer = window.setTimeout(() => {
      setToken(null);
      setExpiresAt(null);
      setPhase("expired");
    }, left);
    return () => window.clearTimeout(timer);
  }, [phase, expiresAt]);

  const allow = async (renew = false) => {
    if (renew && busy) return;
    setPhase("approving");
    setError(null);
    try {
      const result = await approveAction(action.id);
      const at = Date.parse(result.expires_at);
      setToken(result.token);
      setExpiresAt(Number.isNaN(at) ? Date.now() + 600_000 : at);
      setPhase("allowed");
    } catch (err) {
      // 令牌过期后后端仍把动作记作 approved，不会补发新令牌；
      // 再发一轮不带令牌的请求，让模型重新提议，新动作会带新 id 回来。
      if (renew && err instanceof ApiError && err.status === 409) {
        onContinue(question, mode, []);
        setPhase("submitted");
        return;
      }
      setPhase(renew ? "expired" : "pending");
      setError(describeError(err, "没能允许"));
    }
  };

  const reject = async () => {
    setPhase("rejecting");
    setError(null);
    try {
      await rejectAction(action.id);
      setPhase("rejected");
      onResolved?.(action.id);
    } catch (err) {
      // 409 等冲突保持现有逻辑：回到待确认并展示错误，交给用户刷新后重试。
      setPhase("pending");
      setError(describeError(err, "没能拒绝"));
    }
  };

  const continueChat = () => {
    if (!token || busy) return;
    // onContinue 会同步把令牌放进下一轮请求体；之后前端不再保留它。
    onContinue(question, mode, [token]);
    setToken(null);
    setExpiresAt(null);
    setPhase("submitted");
    onResolved?.(action.id);
  };

  const tool = toolLabel(action.tool);
  const rows = argRows(action.args);
  const working = phase === "approving" || phase === "rejecting";
  const minutesLeft =
    expiresAt == null ? 0 : Math.max(1, Math.ceil((expiresAt - Date.now()) / 60_000));

  return (
    <article
      className={`action-card action-card--${toneOf(phase)}`}
      aria-label={`工具调用：${tool}`}
    >
      <div className="action-card__head">
        <span className="action-card__state">{STATE_LABEL[phase]}</span>
        <span className="action-card__tool">{tool}</span>
        {tool !== action.tool && <span className="action-card__raw">{action.tool}</span>}
      </div>

      {rows.length > 0 && (
        <dl className="action-card__args">
          {rows.map((row) => (
            <div className="action-card__arg" key={row.key}>
              <dt>{row.key}</dt>
              <dd title={row.full}>{row.value}</dd>
            </div>
          ))}
        </dl>
      )}

      <p className="action-card__reason">{action.reason?.trim() || DEFAULT_REASON}</p>

      <div className="action-card__foot">
        {(phase === "pending" || working) && (
          <>
            <button
              type="button"
              className="action-card__btn action-card__btn--allow"
              disabled={working}
              onClick={() => void allow()}
            >
              {phase === "approving" ? "确认中…" : "允许一次"}
            </button>
            <button
              type="button"
              className="action-card__btn"
              disabled={working}
              onClick={() => void reject()}
            >
              {phase === "rejecting" ? "拒绝中…" : "拒绝"}
            </button>
          </>
        )}

        {phase === "allowed" && (
          <>
            <button
              type="button"
              className="action-card__btn action-card__btn--allow"
              disabled={busy}
              title={busy ? "助手正在回答，稍后再继续" : undefined}
              onClick={continueChat}
            >
              已允许，让助手继续
            </button>
            <span className="action-card__hint">{minutesLeft} 分钟内有效</span>
          </>
        )}

        {phase === "expired" && (
          <>
            <button
              type="button"
              className="action-card__btn action-card__btn--allow"
              disabled={busy}
              title={busy ? "助手正在回答，稍后再继续" : undefined}
              onClick={() => void allow(true)}
            >
              重新允许
            </button>
            <span className="action-card__hint">确认已过期，操作没有执行。</span>
          </>
        )}

        {phase === "rejected" && (
          <span className="action-card__hint">已拒绝，这个操作不会再执行。</span>
        )}

        {phase === "submitted" && (
          <span className="action-card__hint">已提交，等待助手继续。</span>
        )}
      </div>

      {error && (
        <p className="action-card__error" role="alert">
          {error}
        </p>
      )}
    </article>
  );
}

function toneOf(phase: Phase): "pending" | "allowed" | "expired" | "rejected" {
  if (phase === "allowed" || phase === "submitted") return "allowed";
  if (phase === "expired") return "expired";
  if (phase === "rejected") return "rejected";
  return "pending";
}

/** 用中文名；MCP 的 `mcp__server__tool` 取最后一段再查表。 */
function toolLabel(tool: string): string {
  const base = tool.includes("__")
    ? tool.split("__").filter(Boolean).pop() || tool
    : tool;
  return TOOL_LABELS[base] ?? base;
}

interface ArgRow {
  key: string;
  value: string;
  full: string;
}

function argRows(args: unknown): ArgRow[] {
  if (args == null) return [];
  if (typeof args === "object" && !Array.isArray(args)) {
    return Object.entries(args as Record<string, unknown>).map(([key, value]) => {
      const full = valueText(value);
      return { key, value: shorten(full), full };
    });
  }
  const full = valueText(args);
  return [{ key: "参数", value: shorten(full), full }];
}

function valueText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null) return "空";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/** 把长值压成一行并截断；完整值仍留在 title 里。 */
function shorten(text: string, limit = 120): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit)}…` : flat;
}

function describeError(err: unknown, prefix: string): string {
  if (err instanceof ApiError) return `${prefix}：${err.message}`;
  return `${prefix}：网络没接上，请稍后再试。`;
}
