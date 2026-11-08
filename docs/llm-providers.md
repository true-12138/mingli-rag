# 换 LLM 供应商 / 多 key 配置

项目默认走 DeepSeek。2026-11-08 实测中，同一个单 key 曾在 20 并发下出现持续
429（60s 内 89 条 `stream upstream failed status=429`），间隔一段时间后复测
2–20 并发全部 0 错误——说明这是上游的**瞬时限流**，不是稳定的容量上限；但单 key
没有余量，高峰期仍会失败。这份文档说明怎么换到其它 OpenAI 兼容供应商，以及
哪些地方会跟着变。

> **先跑验证脚本**，不要直接压测：
>
> ```bash
> python scripts/check_llm.py
> ```
>
> 它会检查本项目依赖的三件事：流式、`response_format: json_object`、`tools/tool_calls`。
> 三者缺一，RAG 或 Agent 模式会在运行时报错。

## 1. 当前支持范围

| 能力 | 现状 |
|---|---|
| 换单个供应商 | `MINGLI_LLM_URL` + `MINGLI_LLM_MODEL`，代码里的同步与异步两条路径都会跟随 |
| 同一供应商多 key | `DEEPSEEK_API_KEYS=key1,key2,...`，轮询 + 失败换 key + 熔断冷却 |
| 跨供应商自动 failover | **尚未实现**。一次进程只指向一个 `MINGLI_LLM_URL`；要自动切供应商需要改 `src/llm.py` 的 endpoint 池 |

key 的环境变量名沿用 `DEEPSEEK_API_KEYS` / `DEEPSEEK_API_KEY`，换成别家也写在这两个变量里。

## 2. 常用 OpenAI 兼容 endpoint

`MINGLI_LLM_URL` 要写**完整的 chat/completions 路径**——代码直接 POST 这个 URL。
模型名以各家控制台为准，下表只是常见值；代码里没有做模型名映射。

| 供应商 | `MINGLI_LLM_URL` | 常见 `MINGLI_LLM_MODEL` |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/chat/completions` | `deepseek-chat` |
| 硅基流动 | `https://api.siliconflow.cn/v1/chat/completions` | `deepseek-ai/DeepSeek-V3`（以控制台为准） |
| 火山方舟 | `https://ark.cn-beijing.volces.com/api/v3/chat/completions` | 推理接入点 ID（`ep-...`）或模型 ID |
| 阿里百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` | `qwen-plus` / `qwen-max` |
| 智谱 | `https://open.bigmodel.cn/api/paas/v4/chat/completions` | `glm-4-plus` 等 |
| OpenRouter | `https://openrouter.ai/api/v1/chat/completions` | `deepseek/deepseek-chat` |

## 3. 操作步骤

1. 在供应商控制台创建 key，确认配额/并发上限。
2. 编辑仓库根目录 `.env`（**不进仓库**）：

   ```bash
   DEEPSEEK_API_KEY=sk-xxxx
   MINGLI_LLM_URL=https://api.siliconflow.cn/v1/chat/completions
   MINGLI_LLM_MODEL=deepseek-ai/DeepSeek-V3
   ```

   同一供应商有多个 key 时：

   ```bash
   DEEPSEEK_API_KEYS=sk-aaa,sk-bbb
   ```

3. 验证调用契约：

   ```bash
   python scripts/check_llm.py
   ```

4. 重启服务，确认 key 数与闸门后端：

   ```bash
   pkill -f "src/api.py"
   MINGLI_WORKERS=2 MINGLI_REDIS_URL=redis://127.0.0.1:6379/0 nohup python src/api.py > api.log 2>&1 &
   sleep 20
   curl -s http://127.0.0.1:8000/health
   ```

5. 预热后压测：

   ```bash
   python loadtest/answers.py --concurrency 4 --duration 20
   python loadtest/answers.py --concurrency 20 --duration 30
   ```

## 4. 重要注意事项

- **同账号多 key 通常共享配额**：DeepSeek 的限流按账号算，多建 key 不会扩容；
  要么用不同账号，要么换供应商。
- **`response_format` 兼容性**：部分供应商/模型不支持 `json_object`，RAG 模式会直接失败。
  `scripts/check_llm.py` 的第一项就是查这个。
- **工具调用兼容性**：Agent 模式依赖 `tools` + 流式 `tool_calls` 分片；第二项检查覆盖。
- **换模型会改答案质量**：`eval/` 的基线是按 DeepSeek 跑的。换供应商后要重跑评测，
  或在 README 的评测表里明确标注模型名，不要把两套结果混在一起。
- **重试预算**：流式路径现在会遵守上游 `Retry-After`（上限 `MINGLI_LLM_RETRY_MAX_WAIT`，
  默认 8s），但持续 429 时重试只会把首 token P95 推高；容量问题仍要靠配额解决。

## 5. 相关环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `MINGLI_LLM_URL` | DeepSeek 官方 | 完整 chat/completions URL |
| `MINGLI_LLM_MODEL` | `deepseek-chat` | 模型名 |
| `DEEPSEEK_API_KEYS` | 空 | 逗号分隔，优先于单 key |
| `DEEPSEEK_API_KEY` | 空 | 单 key |
| `MINGLI_LLM_PER_KEY_CONCURRENCY` | 32 | 每 key 并发上限；**应改成供应商承诺值** |
| `MINGLI_LLM_RETRIES` | 3 | 429/5xx 重试次数 |
| `MINGLI_LLM_RETRY_MAX_WAIT` | 8 | 单次退避上限（秒） |
| `MINGLI_KEY_STRIKE_LIMIT` | 3 | 连续失败多少次后冷却该 key |
| `MINGLI_KEY_COOLDOWN` | 30 | 冷却时长（秒） |
