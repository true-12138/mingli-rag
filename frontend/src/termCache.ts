// 术语标注的请求缓存。
//
// 标注是「等正文写完再发一次」的请求，同一段文字翻回来时应该命中同一份结果，
// 否则每切一次会话就重新请求一次。缓存只存最近若干段正文，够翻一轮旧会话。
import { annotateTerms, type TermHit } from "./api";

const TERM_CACHE_LIMIT = 24;
const cache = new Map<string, TermHit[]>();

export function loadTerms(text: string): Promise<TermHit[]> {
  const cached = cache.get(text);
  if (cached) return Promise.resolve(cached);
  return annotateTerms(text).then((hits) => {
    if (cache.size >= TERM_CACHE_LIMIT) {
      const oldest = cache.keys().next().value;
      if (oldest != null) cache.delete(oldest);
    }
    cache.set(text, hits);
    return hits;
  });
}
