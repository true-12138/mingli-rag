// 记忆页：跨会话的偏好与事实，可以逐条删除。
// 这里展示的是模型按「用户明确说过」抽出来的内容，不是聊天记录本身。
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, deleteMemory, listMemories, type Memory } from "../api";
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
            <p className="page__kicker">记忆</p>
            <h1 className="page__title">它记住的，只有你说过的话</h1>
            <p className="page__lead">
              跨会话保存的偏好与事实，只用于个性化回答，<strong>不作为引用依据</strong>。
              身份证、手机号、病史这类敏感信息不会入库。
            </p>
          </div>
          <div className="page__aside">
            <span className="page__count">{memories.length}</span>
            <span className="page__count-label">条记忆</span>
          </div>
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
            <div className="chart-empty">
              <span className="chart-empty__seal" aria-hidden="true">
                忆
              </span>
              <p>
                还没有记忆。在对话里明确说一句「以后优先查《子平真诠》」或「我习惯看原文」，
                下一轮起就会被记下来。
              </p>
            </div>
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

          <p className="mem-foot">
            记忆抽取失败不会影响回答——它是增强，不是主链路。想让它忘掉什么，直接在这里删。
          </p>
        </div>
      </div>
    </div>
  );
}
