# 压测脚本

两条验收分开测，避免口径互相污染：

| 场景 | 脚本 | 说明 |
|---|---|---|
| 200 个 SSE 连接保持 10 分钟 | `hold_sse.py` | 连 `GET /v1/events`，只收心跳，不触发模型 |
| 20 条并发回答 | `k6-smoke.js` | 每次请求触发一次完整回答；`timings.waiting` 近似首 token |

## 200 连接

```bash
python loadtest/hold_sse.py --connections 200 --duration 600
python loadtest/hold_sse.py --connections 200 --duration 600 \
  --url https://your-host/v1/events --token "$MINGLI_API_TOKEN"
```

输出示例：

```json
{"connections":200,"ok":200,"error_rate":0.0,"duration_s":603.2,
 "connect_ms_p50":12.4,"connect_ms_p95":48.1,"heartbeats_total":7800,"errors":[]}
```

退出码非 0 表示有连接失败。`heartbeats_total` 约等于 `连接数 × 时长 / 15s`。

## 并发回答

```bash
k6 run loadtest/k6-smoke.js                       # 10 并发 / 2 分钟
NO_CACHE=1 VUS=20 DURATION=5m k6 run loadtest/k6-smoke.js    # 20 并发 / 5 分钟
TOKEN=xxx BASE=https://your-host NO_CACHE=1 VUS=20 k6 run loadtest/k6-smoke.js
```

脚本默认在 12 道题里轮换，避免固定一问被语义缓存全部命中。**正式测「20
条并发回答」时加 `NO_CACHE=1`**，否则重复题会走缓存，TTFB 很好看但不代表
模型并发能力；缓存收益单独看 `/metrics` 的 `mingli_semcache_hits_total`。

先跑 10 并发拿到基线，再上 20。看三个数：

- `answer_ttfb_ms` 的 p95（阈值 3s）；
- `http_req_failed`（阈值 1%）；
- 第 21 条并发是否拿到 `429` 且带 `Retry-After`。

连接池/槽位状态看 `/health` 的 `concurrency_gate` 与 `semantic_cache`；
实时指标看 `/metrics` 的 `mingli_answer_slots_active`、
`mingli_gate_acquire_total`、`mingli_semcache_hits_total`。

## 本地

本地 WSL 没装 Redis/Postgres 时，闸门会退化为进程内实现（`/health` 显示
`backend: "local"`），连接数可以测，但「多 worker 共享 20 槽」必须在装了
Redis 的环境验证。正式数据在 CloudStudio / 部署机上跑，结果贴回 README。
