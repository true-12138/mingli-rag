# 三周完整版：范围、验收与架构（2026-11-07 起）

> 本文取代 `D:\项目规划.png` 的七天冲刺表。D1/D2 已完成，见 `README.md` §3 与 `eval/baselines.md`。
> **2026-11-07 更新：采用至尊版压缩排期，目标 11/14 跑通，11/15 缓冲；验收标准不变。**
> 目标不是「无限完美」，而是下面这些**可验收**的条目全部成立。

## 1. 目标

做一个可公网访问的命理古籍 RAG 应用：逐 token 流式回答、引用可展开、会话可管理、排盘与记忆可用；在 **200 个 SSE 连接 / 20 条并发回答**下稳定，超出容量时优雅降级。

### 功能验收

- [x] React 对话页：逐 token 流式输出；引用 chip 可展开原文与书名；会话列表可新建/切换/删除
- [x] 三种模式（RAG / 单 Agent / 多 Agent）都可流式，工具步骤实时显示
- [ ] 排盘页：八字、星盘、塔罗三块可用（复用现有 `src/fortune`）
- [ ] 记忆面板：长期记忆可查看、删除
- [ ] 鉴权：公网接口支持 Bearer token；未授权请求 401
- [ ] MCP client：能挂载至少一个外部 MCP server 并调用其工具
- [ ] 公网部署：`/health`、`/chat/stream`、前端页面可访问

### 性能验收（k6）

- [ ] **200 个 SSE 连接**保持 10 分钟，连接建立错误率 < 1%
- [ ] **20 条并发回答**：首 token P95 ≤ 3s；完成 P95 ≤ 60s；错误率 ≤ 1%
- [ ] 超出容量：返回 429 + `Retry-After`，不出现进程崩溃/内存持续上涨
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
        │            │              │
   Redis          Postgres        LLM Gateway
   - 会话/缓存     - 业务表         - 多 key 轮询
   - 分布式限流    - pgvector       - per-key 并发池
   - 队列/Stream   - 运行记录       - 重试/熔断
        │
  Worker × M（arq）
   - Agent 长任务
   - 结果写 Redis Stream
        │
  Embedding 服务（独立进程/容器）
   - BGE-M3 批量编码，避免每 worker 各载一份
```

### 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| Web 框架 | 保留 FastAPI，改全异步 | 现有接口与测试可复用；SSE 需要 async |
| HTTP 客户端 | `httpx.AsyncClient` | 原生 async 流式；替换同步 `requests` |
| 队列 | arq（Redis） | 轻量、async、与 Redis 复用 |
| 向量库 | pgvector | 与业务库同源，少一个组件；8,681 条足够 |
| 限流 | Redis 令牌桶 + 每用户配额 | 多实例共享；进程内信号量必须废弃 |
| Embedding | 独立 HTTP 服务 + 微批 | 4 worker 各载一份 BGE-M3 内存不可接受 |
| LLM key | `DEEPSEEK_API_KEYS` 逗号分隔，轮询 | 单 key 并发上限是硬约束 |
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
| 11/10 | D4 排盘 / 记忆页 | 功能完整 |
| 11/11 | Postgres/pgvector/Redis；arq 队列；分布式限流；embedding 服务 | 基础设施 |
| 11/12 | 多 key 网关 + 语义缓存 + k6 首轮 | 200/20 拐点数据 |
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
6. D4 页面
7. Redis / Postgres / 队列 / embedding 服务
8. 多 key 网关与压测
9. 部署、鉴权、MCP client、文档

## 6. 风险

| 风险 | 影响 | 应对 |
|---|---|---|
| DeepSeek 单 key 并发上限 | 20 并发回答达不到 | 多 key；队列 + 429；压测先测单 key 拐点 |
| 逐 token + `json_object` 增量解析 | 前端收到半个 JSON | 服务端增量提取 `answer`，只下发纯文本 delta |
| 4 worker × BGE-M3 内存 | OOM | embedding 独立服务；先测单进程常驻内存 |
| 3 周内范围蔓延 | 延期 | 以本文验收表为准，新需求进 v3 |
