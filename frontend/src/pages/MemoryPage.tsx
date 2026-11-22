// 记忆页：跨会话的偏好与事实，可以逐条删除。
// 这里展示的是模型按「用户明确说过」抽出来的内容，不是聊天记录本身。
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  confirmMemory,
  deleteMemory,
  listMemories,
  rejectMemory,
  type Memory,
} from "../api";
import { MenuIcon } from "../components/icons";
import { formatWhen } from "../format";

export function MemoryPage({ onOpenDrawer }: { onOpenDrawer: () => void }) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const timer = useRef<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setMemories(await listMemories());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "记忆加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      if (timer.current != null) window.clearTimeout(timer.current);
    };
  }, [load]);

  const remove = async (id: number) => {
    if (confirmId !== id) {
      setConfirmId(id);
      if (timer.current != null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setConfirmId(null), 2600);
      return;
    }
    setConfirmId(null);
    try {
      await deleteMemory(id);
      setMemories((prev) => prev.filter((item) => item.id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "删除失败，请再试一次");
    }
  };

  const resolvePending = async (memory: Memory, accept: boolean) => {
    try {
      const next = accept
        ? await confirmMemory(memory.id, memory.version)
        : await rejectMemory(memory.id, memory.version);
      setMemories((prev) => prev.map((item) => (item.id === next.id ? next : item)));
      setError(null);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "操作失败，请再试一次",
      );
      // 409：这条记忆已经在别的标签页变过了，重新读一次让用户看到最新状态
      if (err instanceof ApiError && err.status === 409) void load();
    }
  };

  const pendingCount = memories.filter((item) => item.status === "pending").length;

  return (
    <div className="page">
      <header className="page__head">
        <div className="page__head-inner">
          <div className="page__head-text">
            <button
              className="icon-btn page__drawer"
              onClick={onOpenDrawer}
              aria-label="导航"
            >
              <MenuIcon />
            </button>
            <h1 className="page__title">记忆</h1>
          </div>
          {memories.length > 0 && (
            <div className="page__aside">
              <span className="page__count">{memories.length}</span>
              <span className="page__count-label">
                条记忆{pendingCount > 0 ? ` · ${pendingCount} 条待确认` : ""}
              </span>
            </div>
          )}
        </div>
      </header>

      <div className="page__scroll">
        <div className="page__inner">
          {error && (
            <p className="note note--error" role="alert">
              {error}
            </p>
          )}

          {loading && memories.length === 0 && <p className="mem-tip">正在读取…</p>}

          {!loading && memories.length === 0 && (
            <p className="page-empty">
              还没有记忆。在对话里明确说一句偏好，下一轮起就会记下来。
            </p>
          )}

          {memories.length > 0 && (
            <ul className="mem-list">
              {memories.map((memory) => {
                const confirming = confirmId === memory.id;
                return (
                  <li className="mem" key={memory.id}>
                    <div className="mem__head">
                      <span className={`mem__kind mem__kind--${memory.kind}`}>
                        {memory.kind === "preference" ? "偏好" : "事实"}
                      </span>
                      <code className="mem__key">{memory.key}</code>
                      <span className="mem__when">{formatWhen(memory.updated_at)}</span>
                    </div>
                    <p className="mem__value">{memory.value}</p>
                    {memory.status === "pending" && memory.pending_value && (
                      <div className="mem__pending">
                        <p className="mem__pending-label">待确认改为：</p>
                        <p className="mem__pending-value">{memory.pending_value}</p>
                        <div className="mem__pending-actions">
                          <button
                            type="button"
                            className="mem__btn mem__btn--accept"
                            onClick={() => void resolvePending(memory, true)}
                          >
                            确认改
                          </button>
                          <button
                            type="button"
                            className="mem__btn"
                            onClick={() => void resolvePending(memory, false)}
                          >
                            保持原样
                          </button>
                        </div>
                      </div>
                    )}
                    <button
                      type="button"
                      className={`mem__del${confirming ? " mem__del--armed" : ""}`}
                      onClick={() => void remove(memory.id)}
                    >
                      {confirming ? "确认删除" : "删除"}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
