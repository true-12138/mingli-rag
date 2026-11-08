// 并发回答冒烟：先测 10 并发，确认 TTFB 和错误率，再放大到 20。
//
//   k6 run loadtest/k6-smoke.js
//   BASE=https://your-host VUS=20 DURATION=5m k6 run loadtest/k6-smoke.js
//   TOKEN=xxx k6 run loadtest/k6-smoke.js
//
// 注意：k6 的 http 不暴露逐 token 的 SSE 流，`timings.waiting` 是首字节时间，
// 用它近似首 token 延迟；整条回答的耗时看 `timings.duration`。200 连接另用
// `loadtest/hold_sse.py` 测，两者不要混在一个端点里。
import http from "k6/http";
import { check } from "k6";
import { Rate, Trend } from "k6/metrics";

const BASE = __ENV.BASE || "http://127.0.0.1:8000";
const VUS = Number(__ENV.VUS || 10);
const DURATION = __ENV.DURATION || "2m";
const MODE = __ENV.MODE || "rag";

const ttfb = new Trend("answer_ttfb_ms", true);
const answerOk = new Rate("answer_ok");

export const options = {
  scenarios: {
    answers: {
      executor: "constant-vus",
      vus: VUS,
      duration: DURATION,
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    answer_ok: ["rate>0.99"],
    answer_ttfb_ms: ["p(95)<3000"],
  },
};

export default function () {
  const headers = { "Content-Type": "application/json" };
  if (__ENV.TOKEN) headers.Authorization = "Bearer " + __ENV.TOKEN;
  headers["X-Anonymous-Id"] = "k6-" + __VU;

  const res = http.post(
    `${BASE}/chat/stream`,
    JSON.stringify({
      question: "羊刃分几种？",
      mode: MODE,
      top_k: 5,
    }),
    { headers, timeout: "120s" },
  );

  ttfb.add(res.timings.waiting);
  const ok = check(res, {
    "status 200": (r) => r.status === 200,
    "SSE done event": (r) => typeof r.body === "string" && r.body.includes("event: done"),
  });
  answerOk.add(ok);
}
