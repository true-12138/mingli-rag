# Agent 轨迹评测报告：单 Agent vs 多 Agent

评测日期：2026-11-02
模型：`deepseek-chat`，`temperature=0`
任务集：`eval/agent_tasks.jsonl`（本报告为 2026-11-02 的 15 条版本；2026-11-06 已扩到 30 条，新增 15 条尚未重跑）
跑批脚本：`eval/run_agent.py`

---

## 1. 实验设置

**任务集构成**（本报告范围）：多跳 5 条（a01–a05）、换工具 5 条（b01–b05）、拒答 3 条（c01–c03）、复合 2 条（d01–d02）。扩到 30 条后新增 a06–a10、b06–b09、c04–c06、d03–d05，不在下文的统计内。

每条任务的判据写在自己的 `required_tools` / `evidence_books` / `max_steps` / `pass_criteria` 字段里，由 `run_agent.auto_judge` 自动判定，判定不了的列进 `needs_human` 留待人工。`auto_pass` 要求全部可判项通过。

**两个系统**：

| | 实现 | 结构 |
|---|---|---|
| 单 Agent | `src/agent.py` | 一个 ReAct 循环，7 个工具，最多 6 步 |
| 多 Agent | `src/agent_multi.py` | Supervisor 规划 → Retriever 定向检索 → Verifier 校验缺口 → Supervisor 汇总 |

两者共用同一个工具预算（`max_steps=6`，一次工具调用算一步）和同一份出口检查（`agent._finalize`：citations 只能来自本次 trace 真实返回过的 `chunk_id`；声称能答却无有效引用判为不合规输出）。

**两个指标**：

- **通过数**：`auto_pass` 的条数。
- **双书显式检索**（诊断项，不计入通过）：判据里点名的每一本书，是否都用 `book=` 参数显式检索过。单 Agent 常靠一次全局检索顺带命中两本书（`via=citation`），形式上过、实质上没有做多跳——这个指标把这种情况显出来。

每系统各跑 3 次，中途不改任何代码、提示词或判据。

---

## 2. 主结果

| | 单 Agent | 多 Agent |
|---|---|---|
| 三次通过数 | 9、8、7 | 13、13、12 |
| **均值（区间）** | **8.0 / 15（7–9）** | **12.7 / 15（12–13）** |
| 双书显式检索 | 2.5 / 10（2 次可统计） | **9.0 / 10** |
| 拒答正确 | 3/3、2/3、3/3 | 3/3、3/3、3/3 |
| 复合通过 | 0/2、0/2、0/2 | 2/2、2/2、1/2 |
| 报错 | 0 | 0 |

两个区间不重叠（单 Agent 最高 9 < 多 Agent 最低 12）。

## 3. 逐题配对

三次运行中，逐题 PASS/FAIL 序列：

| 任务 | 类型 | 单 Agent | 多 Agent | 配对结果 |
|---|---|---|---|---|
| a01 | 多跳 | PPP | PPP | 持平 |
| a02 | 多跳 | PPP | FFF | **单 Agent 更好** |
| a03 | 多跳 | FFF | PPP | **多 Agent 更好** |
| a04 | 多跳 | FFF | PPP | **多 Agent 更好** |
| a05 | 多跳 | PPF | PPP | **多 Agent 更好** |
| b01 | 换工具 | FFF | PPP | **多 Agent 更好** |
| b02 | 换工具 | PPP | PPP | 持平 |
| b03 | 换工具 | PPP | PPP | 持平 |
| b04 | 换工具 | FPF | FFF | **单 Agent 更好** |
| b05 | 换工具 | PFF | PPP | **多 Agent 更好** |
| c01 | 拒答 | PPP | PPP | 持平 |
| c02 | 拒答 | PFP | PPP | **多 Agent 更好** |
| c03 | 拒答 | PPP | PPP | 持平 |
| d01 | 复合 | FFF | PPP | **多 Agent 更好** |
| d02 | 复合 | FFF | PPF | **多 Agent 更好** |

**8 条多 Agent 更稳，2 条单 Agent 更稳，5 条持平。**

稳定性：三次运行之间结果发生翻转的 5 道任务里，4 道在单 Agent 侧（a05、b04、b05、c02），多 Agent 侧只有 d02。多 Agent 的收益不只是分数更高，还在于行为更可复现。

## 4. 成本

| | 单 Agent | 多 Agent |
|---|---|---|
| 工具调用 / 题 | 2.8 | 4.1 |
| LLM 调用 / 题 | ≈3.8 | **8.3** |
| 单次跑完 15 题 | 150s | 204s |

单 Agent 的 LLM 调用数未在结果文件中记录，按「每步一次调用 + 一次 final」从步数估算（两轮可统计的 run 平均 2.8 步）。
多 Agent 的额外开销来自四个角色各调一次模型：规划、每条检索、校验、汇总。

---

## 5. 差异从哪来

单 Agent 的失败集中在一个形状上：**拿到一本能自圆其说的一本书的答案就收尾**。

针对该形状所设的机制与对应效果：

| 机制 | 位置 | 对应首次基线观察到的失败 |
|---|---|---|
| 规划时枚举必须查的书，逐本派检索任务 | `PLANNER_PROMPT` | a04、d01、d02 各少查一本书 |
| 检索员调 `search_classics` 时 `book` 由代码强制覆写 | `_retrieve` | a05、a02 靠全局检索顺带命中，实质没做多跳 |
| 规划前注入语料书目 | `_book_catalog` | 规划凭空发明书目里不存在的书 |
| 校验员逐本核对，缺书目则下发缺口回补 | `VERIFIER_PROMPT` / `agent_answer` | 复合题只完成一半链路 |
| 前置工具（排盘/星盘）输出传给校验员与汇总员 | `_run_pre` → `_verify` / `_synthesize` | 涉及出生时间的题被判「古籍里没有四柱」而误拒 |
| 前置工具参数写错时按签名自动修复重试 | `agent_answer` | 一次参数错误导致整题作废 |
| 超出语料范围时仍先检索再拒答 | `PLANNER_PROMPT` | 拒答题 0 步直接拒，未经语料确认 |

**说明**：多 Agent 的第一版跑出 1/15，原因是上表后三条未做到——前置工具输出没有在角色间传递、规划无书目、参数错误即作废。这些属于实现缺陷，修完后为 13/15。因此本报告的对比基线用的是修正后的单 Agent，多 Agent 的增益不应包含修 bug 的部分。

---

## 6. 已知失效与不适用

**a02（多 Agent 三次全失）**：判据要求引用《三命通会》与《五行精纪》。多 Agent 规划选择了《渊海子平》（全库「纳音」0 条）与《李虚中命书》，未选《五行精纪》。但其答案引用了《三命通会》「本之以五行为经，参之以纳音为纬」与《李虚中命书》「纳音主材能器识」「纳音为身」，是从内容质量上更好的取书。该判据中的《五行精纪》系出题时按命中数（130 条）选定，未穷举全部候选书，属于任务设计缺陷。

**b04（两系统均基本未过）**：判据要求 `fetch_chunk`。两个系统均倾向一次检索后直接作答。核查其 8 条检索结果原文，回答中引用的每一句都能在检索结果里找到，无编造；内容层面达标，仅流程不合规。

以上两条均未修改判据。修改判据会使 A/B 结果失去可比性。

**其他局限**：

1. 每系统 3 次运行，样本量小，均值区间用于呈现波动，不作显著性推断。
2. d02 在多 Agent 下吃到 6 步预算上限（2/2、2/2、1/2），第三次因容量不足失败，属预算问题而非逻辑错误。
3. 任务集是围绕本语料设计的（书目、术语异名、章节结构均在出题前实测），结论不外推到其他语料。
4. 判据中 `evidence_books` 的选书带有出题者主观判断，a02 即为反例。

---

## 7. 复现

```bash
pip install -r requirements.txt
export DEEPSEEK_API_KEY=sk-xxxx

python eval/run_agent.py --agent single --tag single_r1
python eval/run_agent.py --agent single --tag single_r2
python eval/run_agent.py --agent single --tag single_r3

python eval/run_agent.py --agent multi  --tag multi_r1
python eval/run_agent.py --agent multi  --tag multi_r2
python eval/run_agent.py --agent multi  --tag multi_r3

python eval/compare_runs.py eval/results_agent_*.json
```

`--rescore <结果文件>` 可在不重跑 API 的情况下用当前判据重新判定已有结果（加诊断项时用）。

本报告的原始结果文件：`results_agent_baseline.json`（单 Agent 第 1 次）、`results_agent_single_r2/r3.json`、`results_agent_multi.json`（多 Agent 第 1 次）、`results_agent_multi_r2/r3.json`。每次跑批请用不同 `--tag`，否则会互相覆盖。
