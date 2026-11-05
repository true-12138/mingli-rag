# 轮次记录模板

复制本文件为 `YYYY-MM-DD-短名.md`，同时写一份 `YYYY-MM-DD-短名.prediction.json`。
**预测必须在跑之前写**，否则这一轮只能算事后解释。

---

## 2026-XX-XX · 一句话说明这轮想改什么

- **state**：`<before 12 位>` → `<after 12 位>`
- **benchmark**：agent_v1（dev 10 / holdout 5）
- **改动文件**：`src/prompts/verifier.md`、`src/agent_config.json:max_steps`
- **run**：dev `multi_r4`（id 21, 22, 23）；holdout `multi_h1`（id 24, 25, 26）

### 1. 观察到的失败形状

从上一轮的 trace 里看到的 **行为**，不是「分数低」：

> 例：b04 两次运行都在第一次检索后直接 final，没有调 fetch_chunk 读上下文。

### 2. 可证伪的假设

> 例：b04 失败的共同点不是检索没命中，而是模型把「主题相关」当成「足以回答」。
> 如果在校验员里要求「证据只有断语、没有前提时，必须 fetch_chunk」，
> 那么 b04 会翻绿，而 a01 这类本来就查全的题不应受影响。

### 3. 预测（跑之前写，同步进 prediction.json）

```json
{
  "round": "2026-11-12-verifier-gap",
  "hypothesis": "...",
  "predicted_pass": ["b04"],
  "predicted_fail": ["a02"]
}
```

### 4. 实测

| run | 通过 | 每通过一题 LLM 调用 | 备注 |
|---|---|---|---|
| multi_r4 | 13/15 | 9.4 | dev 10 条 |

预测对照（`run_agent.py` 自动打印）：

- 翻绿且确认：
- 预测翻绿但没翻：
- 预测失败但过了：

### 5. 结论

`accept` / `reject` / `inconclusive`，以及依据：

```bash
python eval/compare_runs.py --accept 18 19 20 --candidate 21 22 23
```

写清是「区间不重叠」还是「均值涨够 1 题」；如果是 inconclusive，不要把这一轮写成改进。

### 6. 下一轮的线索

优先写「预测翻绿但没翻」的 case：它说明这条行为不是被这个机制控制的，
下一轮应该换一个假设，而不是在同一处继续加词。
