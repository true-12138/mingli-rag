# 压测脚本

两条验收分开测，避免口径互相污染：

| 场景 | 脚本 | 说明 |
|---|---|---|
| 200 个 SSE 连接保持 10 分钟 | `hold_sse.py` | 连 `GET /v1/events`，只收心跳，不触发模型 |
| 20 条并发回答 | `answers.py` | 逐 token 读 SSE，能区分「200 但没收到 done」；`X-No-Cache: 1` 绕过缓存 |
| 同上（k6 口径） | `k6-smoke.js` | 每次请求触发一次完整回答；`timings.waiting` 近似首 token |
| 检索 QPS | `retrieve.py` | 直打 `/retrieve`，不过 LLM、不过语义缓存 |
| 内存稳定性 | `rss_sampler.py` | 按 `/proc` 汇总 API 进程树 RSS，输出 CSV |

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

## 检索 QPS

验收线：≥100 QPS，P95 ≤200ms。`/retrieve` 是同步端点（走线程池），每次
都真实做一遍向量检索，不经过 LLM 和语义缓存，所以这组数才是检索吞吐。

```bash
python loadtest/retrieve.py --concurrency 32 --duration 30
python loadtest/retrieve.py --concurrency 64 --duration 60 --min-qps 100 --max-p95 200
python loadtest/retrieve.py --concurrency 64 --duration 60 --mode dense   # 只走向量
python loadtest/retrieve.py --concurrency 64 --duration 60 --unique       # 冷查询
```

**两种口径要分开报，不能混用**：

| 口径 | 命令 | 测的是什么 |
|---|---|---|
| 重复问题 | 默认 | query 编码命中 LRU，剩余成本是 BM25 + 点积，代表真实流量里重复问 |
| 冷查询 | `--unique` | 每条都是新问题，编码缓存必然 miss，代表编码吞吐的硬件上限 |

`/retrieve` 的耗时几乎全在 BGE-M3 编码上（单条几十毫秒），numpy 点积和 BM25
都是毫秒级。所以在 CPU 机器上「冷查询 100 QPS」物理上做不到，能过 100 QPS
的是重复问题口径或 GPU/远程 embed 服务。并发要压到 32 以上才能看出上限；
返回 200 但 `hits` 为空按失败计。退出码非 0 表示 QPS 或 P95 没过验收线。

## 并发回答

```bash
python loadtest/answers.py --concurrency 20 --duration 300      # 默认绕过缓存
python loadtest/answers.py --concurrency 20 --duration 300 --cache

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

## 内存稳定性

```bash
python loadtest/rss_sampler.py --pattern src/api.py --duration 1800 --interval 30
```

按 `/proc/<pid>/task/<tid>/children` 把 master + uvicorn worker 的进程树加总，
每 30s 一行写进 `rss.csv`。看首尾差值：30 分钟内涨幅 <1% 视为无泄漏。

## 本地

本地 WSL 没装 Redis/Postgres 时，闸门会退化为进程内实现（`/health` 显示
`backend: "local"`），连接数可以测，但「多 worker 共享 20 槽」必须在装了
Redis 的环境验证。正式数据在 CloudStudio / 部署机上跑，结果贴回 README。
