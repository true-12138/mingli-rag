// 白话释义的前端缓存。
//
// 展开同一段引用、来回切会话时不该反复花掉模型调用：按 chunk_id 记住结果。
// 后端的持久缓存仍然存在，这里只是少发一次请求；两边都以 chunk_id 为键。
import { interpretChunks, type ChunkInterpretation } from "./api";

const LIMIT = 48;
const cache = new Map<number, ChunkInterpretation>();
const inflight = new Map<number, Promise<ChunkInterpretation>>();

function remember(item: ChunkInterpretation): void {
  if (cache.size >= LIMIT) {
    const oldest = cache.keys().next().value;
    if (oldest != null) cache.delete(oldest);
  }
  cache.set(item.chunk_id, item);
}

export function loadInterpretation(chunkId: number): Promise<ChunkInterpretation> {
  const hit = cache.get(chunkId);
  if (hit) return Promise.resolve(hit);

  // 同一段正在生成时，第二次点击复用同一个请求。
  const pending = inflight.get(chunkId);
  if (pending) return pending;

  const task = interpretChunks([chunkId])
    .then((items) => {
      const item: ChunkInterpretation =
        items[0] ?? {
          chunk_id: chunkId,
          translation: null,
          cached: false,
          truncated: false,
          error: "没有取到释义",
        };
      remember(item);
      return item;
    })
    .catch((err: unknown) => {
      // 网络错误不缓存：下次展开还会重试。
      const item: ChunkInterpretation = {
        chunk_id: chunkId,
        translation: null,
        cached: false,
        truncated: false,
        error: err instanceof Error ? err.message : "释义暂时不可用",
      };
      return item;
    })
    .finally(() => {
      inflight.delete(chunkId);
    });

  inflight.set(chunkId, task);
  return task;
}
