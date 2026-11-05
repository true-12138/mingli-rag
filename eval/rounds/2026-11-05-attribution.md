# 2026-11-05 · 把评测从「有分数」改成「可归因」

这一轮没有改提示词，也没有产生新的分数，所以**不声称任何指标提升**。
它做的是基础设施：让之后的每一轮都能回答「这次分数变化是谁带来的」。

- **state**：v1.5 之前没有 state 版本 → `agent_state` 首次冻结
- **benchmark**：`eval/tasks/agent_v1` 首次冻结（dev 10 / holdout 5）
- **改动文件**：见下面的清单
- **run**：无新增（历史 run 保留，`state_version` 为 NULL，不参与归因）

## 1. 观察到的形状

`eval/REPORT.md` §5 的机制表已经能做事后归因，但它依赖「记得当时改了哪几个 prompt」。
具体缺口：

- `eval_runs` 只有 `dataset_version`，没有 Agent 版本；改了 prompt 之后，两次 run 在库里长得一样；
- 题目、判据、提示词都在同一分支上迭代，报告里的数字无法回答「有没有对着测试集调参」；
- 分数与 trace、成本是三个独立文件，查一条失败用例要手工翻 JSON；
- 接受与否只有回归门（掉点才拦），没有「候选是否真的更好」的判断。

## 2. 这一轮引入的约束

| 约束 | 位置 | 效果 |
|---|---|---|
| 提示词从 Python 常量移到 `src/prompts/*.md`，参数移到 `agent_config.json` | `src/agent_state.py` | 改一处 prompt，`state_version` 必变 |
| 每次 run 记录 state 版本、benchmark 版本、第几次运行 | `eval_runs` 新列 | 两次 run 可以精确说「差在哪几个文件」 |
| 题面与判据分离 | `eval/tasks/agent_v1/` | 公开题面不含 `required_tools` / `pass_criteria` |
| 冻结 + sha256 | `benchmark.json` | 改题未重新冻结时，run_agent 会警告 |
| case × run 矩阵 | `evalhub.case_matrix()` | 翻转率与稳定通过率成为一等指标 |
| 接受规则 | `evalhub.accept_candidate()` | 区间不重叠 / 均值涨够 1 题，否则 inconclusive |
| 预测先于结果 | `run_agent.py --predict` | 跑完打印「预测翻绿但没翻」 |
| 每题 trace_id + token | `eval_cases` 新列 | 分数能跳回轨迹，能算每通过一题的成本 |

## 3. 已知边界（下一轮之前要记住）

1. **v1 的 holdout 不是无污染的**。15 条题在冻结前都参与过提示词迭代，
   所以 a03/a05/b05/c02/d02 的分数只能约束**之后**的改动，不能当作泛化证明。
   扩题到 30 条后重新冻结，才有一份真正没见过的 holdout。
2. **单次 run 仍不足以判改进**。接受规则要求 3 次 run；只有 1 次时一律按 inconclusive 处理。
3. 历史 run 的 `state_version` 为 NULL，`compare()` 会标 `same_state=false`，
   不要用它们做「改动前后」的强结论。

## 4. 下一轮的第一条假设

从「两本书都点名了、但只查了一本」的 case 入手（a04、d01），
预测 b04 不受影响、a02 仍失败（判据缺陷已知，不作为优化目标）。
下一次真正跑批之前，按 `TEMPLATE.md` 建对应的 `.prediction.json`。
