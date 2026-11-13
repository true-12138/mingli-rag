# 工程边界与异常处理

这份文档回答一个问题：**每一层坏掉的时候，用户看到什么、系统留下什么、哪条测试锁住了它。**

它不是架构介绍，也不重复 README 的启动步骤。所有条目都对应仓库里的真实代码，
行号会随重构漂移，以函数名为准。

## 1. 总原则

1. **失败要变成可读的 observation，不能把循环带走。** 模型、工具、外部 MCP server
   都是不可信的执行体；它们抛异常时，调用方应该拿到一条 `ok=false` 的结果继续跑，
   而不是 500。
2. **预算先于重试。** 步数、token、并发、历史长度都有硬上限。上限用完后系统
   不是「再试一次」，而是强制收口或明确拒绝。
3. **不确定时拒绝，不猜。** 排盘缺字段就追问；检索证据不足就 `can_answer=false`；
   记忆有并发冲突就 409，不覆盖别人刚写的值。
4. **降级要显式。** Redis 挂了退化为进程内限流并记指标；权限层自身出错按放行处理
   （fail-open），但会留下 warning。所有降级都有日志或字段，不静默。
5. **用户可见的文案不承诺能力。** 古籍问答只做「依据原文检索与阅读」，
   不做预测、不给医疗/法律/投资/人生决策建议（见 §7）。

## 2. 分层边界

```
HTTP / SSE           src/api.py, src/api_conversations.py, src/api_fortune.py
  ↓
并发闸门与配额        src/gate.py, src/guards.py
  ↓
编排                 src/agent.py（单 Agent）/ src/agent_multi.py（多 Agent）
  ↓
工具循环             src/tool_loop.py
  ↓
工具实现             src/tools.py（内置 7 个）+ src/mcp_client.py（外部 MCP）
  ↓
模型                 src/llm.py（多 Key、重试、并发上限）
  ↓
存储                 检索索引 / Postgres·SQLite / Redis / 语义缓存
```

每层的职责边界是：**本层能把错误翻译成协议内结果，就不要往上抛。** 只有
「这一层已经无法给出有意义的结果」时才转成 HTTP 状态码或 SSE `error` 事件。

## 3. 逐项契约

### 3.1 模型调用

| 失败点 | 当前行为 | 用户/调用方看到 | 代码 | 测试 |
|---|---|---|---|---|
| 上游 429/5xx | 指数退避重试，最多 `MINGLI_LLM_RETRIES` 次（默认 3） | 重试期间无感；最终失败转 502 | `src/llm.py:37-40` | `tests/test_llm_async.py` |
| 单 Key 并发打满 | 换下一个 Key；全部打满则排队等信号量 | 延迟上升，不报错 | `src/llm.py:40` | — |
| 上游超时 | httpx timeout 120s | 502 `上游模型调用失败` | `src/llm.py:118`、`src/api.py:474` | — |
| 没有可用 Key | 抛 `RuntimeError` | 503，detail 说明缺 Key | `src/api.py:478` | `tests/test_api.py` |
| 流式生成中途失败 | 已下发的 token 无法撤回；补一帧 `error` | SSE `event: error` | `src/api.py:639-646` | — |
| 终稿 JSON 解析失败 | 第一次失败追加一条「只输出 JSON」observation 重跑；第二次仍失败 | `invalid_output=true`，保留 raw 文本 | `src/agent.py:122-193` | `tests/test_agent_guardrails.py` |
| token 预算耗尽 | `MINGLI_MAX_TOKENS`（默认 24000，0=不限）累计用完后，下一轮不再传 tools | 模型被迫直接给终稿；`tokens_used` 回传 | `src/agent.py:30`、`src/tool_loop.py:136-144` | `tests/test_tool_loop.py::test_token_budget_forces_final_without_tools` |

### 3.2 工具循环

`src/tool_loop.py` 是所有工具调用的唯一入口，单 Agent、多 Agent 检索员共用。

| 失败点 | 当前行为 | 回给模型的内容 | 测试 |
|---|---|---|---|
| 工具预算用完（`MAX_STEPS=6` 单 Agent / `RETRIEVER_MAX_CALLS=2` 检索员） | 剩余调用不执行，但每个 `tool_call_id` 仍回一条 budget observation，然后下一轮不传 tools | `{"ok": false, "error": "步数预算已用完…"}` | `test_budget_caps_multi_calls_and_forces_final_without_tools` |
| `arguments` 不是合法 JSON | 不执行，回错误让模型改参数 | `{"ok": false, "error": "arguments 不是合法 JSON…"}` | `test_invalid_arguments_are_reported_not_raised` |
| 工具名不存在 | `tools.call` 返回「未知工具」并附可用列表 | `ok=false` + 可用工具 | `test_failure_modes_flows.py` |
| 工具实现抛异常 | `_invoke()` 兜住所有 `Exception` | `{"ok": false, "error": "工具执行异常（RuntimeError）：…"}` | `test_failure_modes_flows.py` |
| `prepare()` 参数预处理失败 | 同样转 observation，不终止循环 | `{"ok": false, "error": "参数预处理失败：…"}` | — |
| 一次返回多个 tool_calls、预算不够 | 前面的执行，后面的补 budget observation | 保证每个 `tool_call_id` 都有响应 | `test_budget_caps_multi_calls_…` |
| 权限拒绝 | `side_effect` 工具默认不执行，但**占一步**，防止模型无限重试 | `{"ok": false, "requires_confirmation": true, "tier": "side_effect", "args": {...}}` | `test_side_effect_tool_is_denied_and_not_executed` |
| 用户确认后重跑 | 同一次运行传 `allow_side_effects=True` 才执行 | 正常 result | `test_side_effect_tool_runs_after_user_confirmation` |

关键设计：**拒绝也计数**。如果拒绝不占步数，模型会在「调用 → 被拒 → 再调用」
之间死循环；占一步后，最多 `MAX_STEPS` 次就会收口。

### 3.3 权限分级

- 内置 7 个工具全部是 `READ`（`src/tool_policy.py` 的 `BUILTIN_TIERS`）：
  `search_classics` / `fetch_chunk` / `list_books` / `search_terms` /
  `draw_bazi` / `draw_astro` / `draw_tarot` 都是纯函数，重复调用无副作用。
- 外部 MCP 工具**默认 `SIDE_EFFECT`**，只有配置文件 `read_only` 里显式声明的才是 `READ`
  （`src/mcp_client.py:402-410`、`tier()` at `:424`）。
- `deny` 里的工具连 schema 都不挂，模型根本不知道它存在（`visible_tools()`）。
- 权限层自身抛异常时 **fail-open**（`src/tool_loop.py:50-51`），因为把「权限服务坏了」
  解释成「所有工具都不能用」会让整个服务不可用；真正的风险由工具自身的参数校验兜底。
- 当前没有实现「前端 Action Card 确认后带 token 重放」的端到端链路：
  `allow_side_effects` 是运行参数，不是持久化授权。这是已知限制，见 §6。

### 3.4 检索与引用

| 失败点 | 当前行为 | 测试 |
|---|---|---|
| 检索结果为空 | 模型收到空证据，应按 prompt 返回 `can_answer=false` | `tests/test_agent_guardrails.py` |
| 模型编造 `chunk_id` | 不在本轮 trace 里的 id 进入 `invalid_citations`，不进入引用列表 | `tests/test_failure_modes.py::test_agent_citation_not_in_trace_goes_to_invalid` |
| 历史里出现旧 chunk_id | 引用白名单只来自**本轮**检索，历史 chunk 不能混入 | `tests/test_conversation.py::test_answer_retrieves_with_standalone_and_isolates_citations` |
| 检索后端异常 | 转 500 `检索失败`（非预期错误不吞） | `src/api.py:394-398` |
| 证据不足 | 固定拒答文案「语料中没有足够的依据回答这个问题。」 | `src/rag.py:16` |

### 3.5 并发与配额

| 机制 | 值 | 行为 | 代码 |
|---|---|---|---|
| 生成并发闸门 | `MINGLI_ANSWER_SLOTS`（默认 20） | 满了立刻 429，不排队 | `src/gate.py:318-319` |
| 占位 TTL | 300s | 进程崩溃后槽位自动过期，不会永久泄漏 | `src/gate.py:30` |
| Redis 不可用 | 2s socket timeout | 整段退化为进程内 `LocalGate`，记 `redis_errors` 指标 | `src/gate.py:127-177` |
| 每日/会话额度 | `MINGLI_DAILY_LLM_LIMIT=300`、`MINGLI_SESSION_LLM_LIMIT=6` | 超限拒绝生成 | `src/app.py:81-82、:101-107` |
| SSE 心跳 | 15s | 空闲时发注释帧，防止代理断连 | `src/sse.py:17` |
| 客户端断开 | 取消后台任务 | 避免 200 个连接留下 200 个孤儿协程 | `src/sse.py:48-52` |

### 3.6 记忆的并发与确认

记忆写入不是「最后写入者赢」，而是显式两阶段：

1. 抽取到与现有值不同的新值时，新值进入 `pending_value`，`value` 保持旧值；
2. 前端展示「有 1 条更新待确认」；
3. 用户点确认 → `pending_value` 变成生效值，`version += 1`；
   点忽略 → 丢弃 pending；
4. 确认/忽略都带页面读到的 `version`，不一致返回 **409 + 库内最新状态**
   （`src/api_conversations.py:417`），前端刷新而不是盲目重试。

`pending_value` **不会进入 prompt**：模型只看到已确认的事实，否则等于未经用户同意
就把猜测写进了长期上下文。测试：`test_pending_memory_is_not_in_prompt`、
`test_memory_lost_update_is_rejected_with_409`、`test_memory_confirm_is_idempotent`、
`test_reject_rolls_back_pending_value`。

### 3.7 结构化追问（排盘 intake）

`/v1/fortune/intake` 的原则是**不替用户猜必填项**：

| 情况 | 返回 | 测试 |
|---|---|---|
| 缺必填字段 | `status=need_input`、`reason=missing`，只列缺的字段 | `test_intake_asks_for_missing_slots_without_guessing` |
| 字段值非法（如 month=13） | `status=need_input`、`reason=invalid`，只重问这一项，合法字段保留在 `known` | `test_intake_invalid_value_only_asks_that_field` |
| 日历上不存在（如 4 月 31 日） | 200 + `reason=calendar`，不 500 | `test_intake_calendar_error_does_not_500` |
| 可选字段用了默认值 | `defaults` 明示 + `warnings`，不静默补 | `test_intake_defaults_are_disclosed_not_silent` |
| `/read` 参数不全 | 400 + `need_input=true` + `fields` | `test_read_incomplete_params_returns_structured_400` |
| 塔罗 seed | intake 时固定，并回填进 `params.seed`，原样传给 `/read` 可复现同一组牌 | `test_intake_tarot_params_carry_the_seed_so_reuse_reproduces_cards` |

排盘本身是确定性计算，不经过模型；只有「解读」调模型，而且 prompt 里的盘面由
服务端重新算出来，不接受前端塞一张盘进来。

### 3.8 MCP client / server

| 失败点 | 行为 | 代码 |
|---|---|---|
| 配置不存在 | 不挂载任何外部 server，不联网、不起进程 | `src/mcp_client.py:108-112` |
| 配置格式错误 | 记 warning，返回空列表 | `:113-129` |
| 单个 server 连不上 | 记入 `errors`，其他 server 照常挂载 | `:253-257` |
| 建连超时 | 25s | `:65` |
| 单次调用超时 | 60s，可按 server 覆盖 | `:66` |
| 调用抛异常 | 转 `ok=false` 的 result，不炸工具循环 | `:429-440` |
| server 退出 | 排队中的 future 全部唤醒为异常，调用方不会等到超时 | `:258-267` |

### 3.9 HTTP 错误码约定

| 码 | 含义 | 典型场景 |
|---|---|---|
| 400 | 请求本身不合法 | 参数校验失败、MCP 配置错误、未知盘类型 |
| 401 | 鉴权失败 | 配了 `MINGLI_API_TOKEN` 但没带或带错 |
| 404 | 资源不存在 | trace 已淘汰 |
| 409 | 并发冲突 | 记忆确认的 version 不一致 |
| 429 | 限流 | 并发闸门满、额度用尽 |
| 502 | 上游失败 | 模型厂商不可用、解读上游失败 |
| 503 | 本服务暂时不可用 | 没配 Key、上游未配置 |
| 500 | 未预期错误 | 统一 handler 记录 `request_id` 并回给调用方 |

## 4. 预算上限速查

| 名称 | 默认值 | 位置 | 超限后果 |
|---|---|---|---|
| `MAX_STEPS` | 6 | `src/agent.py:27` | `can_answer=false`，`refusal_reason=步数用尽` |
| `MINGLI_MAX_TOKENS` | 24000 | `src/agent.py:30` | 下一轮不传 tools，强制终稿 |
| `MAX_ROUNDS` | 12 | `src/tool_loop.py:27` | 循环退出，返回空终稿 |
| `RETRIEVER_MAX_CALLS` | 2 | `src/agent_multi.py:42` | 检索员收口 |
| `MAX_TURNS` | 3 | `src/conversation.py:11` | 更早的历史被丢弃 |
| `MAX_CHARS` | 1200 | `src/conversation.py:12` | 历史总字符超限，最旧的先丢 |
| `MAX_MEMORIES` | 8 | `src/conversation.py:68` | 记忆块只带 8 条 |
| `MAX_MEMORIES_PER_TURN` | 3 | `src/memory.py:24` | 单轮最多写 3 条 |
| `MAX_VALUE_CHARS` | 200 | `src/memory.py:25` | 记忆值截断，末尾加 `…` |
| 并发槽位 | 20 | `src/gate.py:318-319` | 429 |
| 单 Key 并发 | 32 | `src/llm.py:40` | 换 Key 或排队 |

## 5. 可观测性

- 每个请求有 `request_id`，未预期错误会返回它；日志里能直接对上。
- 回答链路统一记录：`mode`、`elapsed_ms`、`llm_calls`、`can_answer`、`trace_id`。
- 每次运行回传 `tokens_used`（含追问改写与 JSON 重跑），用于成本核算。
- 闸门指标：`redis_errors`、当前占用、拒绝次数（`src/gate.py` 的 `STATS`）。
- 工具调用全部进 trace：`on_call` 在成功、失败、权限拒绝时都会触发，
  失败步骤可以复盘（`on_call` 收到 `ok=false` 的 result）。

## 6. 已知限制（不要假装没有）

1. **没有 compaction 子系统。** 多轮上下文只有「保留最近 3 轮 / 1200 字」的硬裁剪，
   被裁掉的信息不可恢复。长期记忆是另一条路径，不是压缩摘要。
2. **记忆值截断到 200 字符**，超长偏好会丢后半段；这是有意的成本控制，
   但意味着「用户说过的话」不一定被完整保留。
3. **权限确认没有端到端重放。** `allow_side_effects` 是单次运行参数；
   用户在前端确认后如何把授权传回下一次运行，尚未实现。
4. **权限层 fail-open。** 权限服务自身故障时按放行处理，依赖工具参数校验兜底。
5. **SSE 已下发的 token 无法撤回。** 上游中途失败时，用户会先看到半截回答，
   再收到 `error` 事件；前端应以 `done` 事件的 `answer` 为准。
6. **单进程假设。** Redis 闸门是多进程安全的，但进程内 `LocalGate` 退化模式
   只在单进程下准确。
7. **语义缓存可能返回旧答案。** 缓存键包含问题、模式、top_k；语料更新后
   需要手动清理或换前缀。

## 7. 内容与合规边界

这个项目检索的是古籍文献，不是命理预测服务。公开版本在文案和接口上遵守：

- 定位为**古籍检索与阅读**、**历法换算**、**传统文化视角的说明**；
- 不提供预测吉凶、改运、消灾、转运、付费化解；
- 不提供医疗、法律、投资、婚姻、考试录取等决策建议；
- 所有解读类输出固定附免责声明：

  > 以上为传统文化视角的说明，仅供文化研究与娱乐参考，不是预测，不构成医疗、法律、投资或人生决策建议。

- 塔罗只做牌面文化展示，不宣称占卜有效性；
- 公开页面不包含账号、token、服务器 IP、个人身份信息；不捏造 ICP 备案号。

工程上的对应约束：`src/fortune/interpret.py` 的提示词明确禁止上述建议；
前端 `ReadingBox` 固定渲染静态声明，不依赖接口返回；回答以原文引用为准。

## 8. 测试地图

| 关注点 | 文件 |
|---|---|
| 失败模式清单（记忆/追问/塔罗/引用） | `tests/test_failure_modes.py` |
| 工具循环失败模式 | `tests/test_failure_modes_flows.py`、`tests/test_tool_loop.py` |
| 权限分级 | `tests/test_tool_policy.py`、`tests/test_tool_loop.py` |
| Agent 护栏与拒答 | `tests/test_agent_guardrails.py`、`tests/test_agent_function_calling.py` |
| 多轮与历史边界 | `tests/test_conversation.py` |
| 记忆并发 | `tests/test_memory.py`、`tests/test_conversations_api.py` |
| 并发闸门 | `tests/test_gate.py` |
| MCP | `tests/test_mcp_client.py`、`tests/test_mcp_server.py` |
| 排盘与追问 | `tests/test_fortune.py`、`tests/test_fortune_api.py` |

回归基线：全量 `pytest` 必须全绿；任何失败模式修复都要先有一条会红的测试。
