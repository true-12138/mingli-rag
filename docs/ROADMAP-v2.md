# 三周完整版：范围、验收与架构（2026-11-07 起）

> 本文取代 `D:\项目规划.png` 的七天冲刺表。D1/D2 已完成，见 `README.md` §3 与 `eval/baselines.md`。
> **2026-11-07 更新：采用至尊版压缩排期，目标 11/14 跑通，11/15 缓冲；验收标准不变。**
> 目标不是「无限完美」，而是下面这些**可验收**的条目全部成立。

## 1. 目标

做一个可公网访问的命理古籍 RAG 应用：逐 token 流式回答、引用可展开、会话可管理、排盘与记忆可用；在 **200 个 SSE 连接 / 20 条并发回答**下稳定，超出容量时优雅降级。

### 功能验收

- [x] React 对话页：逐 token 流式输出；引用 chip 可展开原文与书名；会话列表可新建/切换/删除
- [x] 三种模式（RAG / 单 Agent / 多 Agent）都可流式，工具步骤实时显示
- [x] 排盘页：八字、星盘、塔罗三块可用（复用现有 `src/fortune`）——`GET/POST /v1/fortune/*` + `#/fortune`，盘面确定性计算，解读在服务端重算盘面
- [x] 记忆面板：长期记忆可查看、删除——`GET /v1/memories`、`DELETE /v1/memories/{id}` + `#/memory` 两步确认删除
- [ ] 鉴权：公网接口支持 Bearer token；未授权请求 401
- [ ] MCP client：能挂载至少一个外部 MCP server 并调用其工具
- [ ] 公网部署：`/health`、`/chat/stream`、前端页面可访问

### 性能验收（k6）

- [ ] **200 个 SSE 连接**保持 10 分钟，连接建立错误率 < 1%（连接挂在 `GET /v1/events`，只收心跳，不触发回答）
- [ ] **20 条并发回答**：首 token P95 ≤ 3s；完成 P95 ≤ 60s；错误率 ≤ 1%（全局 20 槽，多 worker 共享）
- [ ] 超出容量：第 21 条回答返回 429 + `Retry-After`，不排队、不崩溃、RSS 不上涨
- [ ] 检索接口：≥ 100 QPS，P95 ≤ 200ms（不含 LLM）
- [ ] 连续压测 30 分钟后 RSS 稳定，无连接泄漏

> 20 并发回答 ≈ 100 个在途 LLM 调用（每题约 5 次）。若单 key 被限流，需要多 key；
> 否则只能排队，**达不到 20 并发就不宣称达标**。

### 质量门槛

- [ ] 新增模块有单测；CI 全量测试通过
- [ ] 评测结果写入 `code_commit` / `tasks_sha256`，可追溯
- [ ] 日志不含 API key；`.env` 不进仓库
- [ ] README 的结果表与压测报告可复现

## 2. 非目标

- 多地域容灾、跨可用区高可用
- 自建模型推理集群 / fine-tuning
- 上千 QPS 的回答吞吐（受 LLM 供应商配额约束）
- 移动端原生 App

## 3. 目标架构

```
Browser (React + SSE)
        │
   Nginx / ALB  ──  TLS、静态资源、限流
        │
  FastAPI × N（无状态，async）
        │               │                │
   Redis           Postgres        LLM 网关
   - 全局回答槽      - 业务表         - 多 key 轮询
   - 每用户额度      - 连接池         - per-key 并发池
   - 幂等/缓存       - 运行记录       - 跨 key failover/熔断
        │
  Embedding 服务（独立进程）
   - BGE-M3 常驻，微批编码
   - worker 不再各载一份
        │
  arq Worker（仅离线：记忆抽取、评测、长 Agent；不进在线 SSE 路径）
```

> 在线回答**不排队**：槽满立刻 429 + `Retry-After`。SSE 要的是首 token 延迟，
> 队列只会把 P95 推高、把内存吃满。200 个 SSE 连接与 20 个回答槽是两件事：
> 连接通过轻量事件流 `GET /v1/events` 保持（只发心跳），不占回答槽。

### 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| Web 框架 | 保留 FastAPI，改全异步 | 现有接口与测试可复用；SSE 需要 async |
| HTTP 客户端 | `httpx.AsyncClient` | 原生 async 流式；替换同步 `requests` |
| 队列 | arq 仅用于离线任务 | 在线 SSE 不排队；排队会把首 token P95 推高 |
| 向量库 | **保留进程内暴力检索，不引 pgvector ANN** | 8,681×1024 ≈ 35 MB，单次扫描毫秒级；pgvector 多一次网络往返，还会改评测口径。多实例需要共享时再上精确扫描，不上 HNSW |
| 限流 | Redis 全局回答槽 + 每用户额度 | 多实例共享；进程内信号量在 4 worker 下会变成 4 倍上限 |
| Embedding | 独立 HTTP 服务 + 微批 | 4 worker 各载一份 BGE-M3 内存不可接受；query 编码是检索侧真正的 CPU 瓶颈 |
| LLM key | `DEEPSEEK_API_KEYS` 逗号分隔，轮询 + failover | 单 key 并发上限是硬约束；每题 5 次调用是**串行**的，峰值在途约 20–30，不是 100 |
| 流式协议 | SSE（`text/event-stream`） | 浏览器原生、易调试；不用 WebSocket |

### SSE 事件契约

```
event: step      data: {"agent":"retriever","tool":"search_classics","args":{...},"ok":true,"chunk_ids":[...],"error":null}
event: stage     data: {"agent":"planner","detail":{"status":"done","searches":[...]}}
event: delta     data: {"text":"..."}
event: done      data: {完整 ChatResponse，含 citations/trace/usage}
event: error     data: {"message":"...","request_id":"..."}
```

- `step` 一次工具调用完成；`stage` 只在多 Agent 出现（planner/retriever/verifier/synthesizer）。
- `delta` 是**预览**：终稿可能被拒答归一化改写（如 `can_answer=false` 时统一成固定拒答），
  前端收到 `done` 后用 `done.answer` 覆盖正文，不要拼接后直接当最终答案。
- 空闲超过 `MINGLI_SSE_HEARTBEAT`（默认 15s）发 `: keep-alive` 注释行。
- 端点：`POST /chat/stream`（无状态，前端自带 history）与
  `POST /v1/conversations/{id}/chat/stream`（服务端存历史，`done` 额外带
  conversation_id / run_id / 消息 ID）。

## 4. 压缩排期（至尊版，目标 11/14，11/15 缓冲）

| 日期 | 任务 | 交付物 |
|---|---|---|
| 11/07 夜 | 异步 LLM 客户端 + 增量 JSON 解析器 + 单测 | `src/llm.py`、`src/answer_stream.py`，10 tests |
| 11/08 | tool_loop / agent / rag 接入流式；SSE 端点 | 后端逐 token 流可用：`tool_loop.arun`、`rag/agent/agent_multi.answer_stream`、`/chat/stream`、`/v1/.../chat/stream`、`src/sse.py` |
| 11/09 | React 对话页：流式、引用展开、会话列表 | **已完成**：`frontend/`（React 18 + Vite + TS），`npm run build` 通过；三种模式、刷新回放、移动端抽屉均实跑截图验收 |
| 11/10 | D4 排盘 / 记忆页 | **已完成**：`src/api_fortune.py`（10 tests）、`/v1/memories` 列表/删除、`#/fortune` 与 `#/memory` 页面；1440 与 390 宽实跑截图验收（假 LLM + stub 检索，未用真实 key） |
| 11/11 | **D5 并发底座**：Redis 全局回答槽/额度；Postgres 业务库；独立 embedding 服务；`/v1/events` 连接流；LLM 跨 key failover；k6 冒烟 | **代码完成**（`src/gate.py`、`embed_service.py`、`loadtest/`，186 tests）；真实 Redis/PG 与 100/10 数据待云上跑 |
| 11/12 | 语义缓存 + k6 200/20 + 参数调优 | 200/20 拐点数据 |
| 11/13 | 部署、鉴权、MCP client、正式压测 | 公网 + 报告 |
| 11/14 | 修复压测问题、终评、README | 交付 |
| 11/15 | 缓冲 | — |

> 外部依赖不可压缩：DeepSeek 并发配额、ECS/网络、压测调参、逐 token 联调。
> 任一项卡住，按实测拐点降级（如 100/10），并在 README 如实写，不硬撑「200/20」。

## 5. 实施顺序（避免返工）

1. 异步 LLM 客户端（非流式 + 流式 + 多 key + 重试）
2. 增量 JSON 解析器：从流式 `json_object` 中提取 `answer` 字段
3. `rag.answer` / `tool_loop` / `agent_multi` 接入 `on_delta`
4. SSE 端点 + 事件契约测试
5. React 对话页（先接 SSE，再做样式）
6. D4 页面（已完成）
7. **并发底座**：Redis 全局槽 + Postgres + embedding 服务 + `/v1/events`
8. LLM 跨 key failover 与 k6 冒烟（先测 100/10，再上 200/20）
9. 部署、鉴权、MCP client、文档

## 6. 风险

| 风险 | 影响 | 应对 |
|---|---|---|
| DeepSeek 单 key 并发上限 | 20 并发回答达不到 | 多 key；队列 + 429；压测先测单 key 拐点 |
| 逐 token + `json_object` 增量解析 | 前端收到半个 JSON | 服务端增量提取 `answer`，只下发纯文本 delta |
| 4 worker × BGE-M3 内存 | OOM | embedding 独立服务；先测单进程常驻内存 |
| 进程内信号量在 4 worker 下放大上限 | 实际并发是 4×20，压测数据失真 | Redis 全局槽；`/health` 报告当前是 redis 还是 local |
| 200 连接与 20 回答混在一个端点 | 第 21 个连接就 429，连接测试必挂 | `GET /v1/events` 只保持连接；回答走独立 20 槽 |
| pgvector 改变检索结果 | 评测口径漂移，还得重跑全部基线 | 本轮不引 pgvector；要共享索引再上精确扫描并重跑评测 |
| 3 周内范围蔓延 | 延期 | 以本文验收表为准，新需求进 v3 |
