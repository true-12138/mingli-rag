# 优化轮次记录

这里放每一次「改 Agent → 重跑 → 接受或回滚」的记录。一条记录对应一轮，文件名 =
`YYYY-MM-DD-短名.md`，同名的预测写进 `YYYY-MM-DD-短名.prediction.json`。

## 为什么要先写预测

`eval/REPORT.md` 已经做过一次很好的事后归因（§5 机制表），但事后归因有两个问题：
它总能自圆其说，而且分不清「这处改动真的起了作用」和「模型这次状态好」。

所以每轮**先**写 `prediction.json`，再跑：

```json
{
  "round": "2026-11-12-verifier-gap",
  "hypothesis": "校验员对每本点名的书逐本核对，能把 d01 的复合链路补齐",
  "predicted_pass": ["d01", "a04"],
  "predicted_fail": ["b04"]
}
```

跑的时候带上它：

```bash
python eval/run_agent.py --agent multi --tag multi_r4 \
  --split dev --predict eval/rounds/2026-11-12-verifier-gap.prediction.json
```

跑完终端会打印三行对照，结果文件里也会存 `prediction` 字段：

- **预测翻绿且确实翻绿** —— 假设成立的证据；
- **预测翻绿但没翻** —— 下一轮假设的入口，比失败更有信息量；
- **预测失败但过了** —— 说明收益来自别处，别急着归因。

## 接受规则

不要用「比上一次高就接受」。15 题里 1 题就是 6.7 个点，单次高 1 题可能只是波动。
用 `evalhub.accept_candidate()`，它要求两者之一：

1. 候选最差的一次也高于基准最好的一次（区间不重叠）；
2. 均值涨幅换算成题数 ≥ 1 题，且没有指标跌破回归门。

两条都不满足，就是 inconclusive——不算改进，也不算退步，继续攒证据。

```bash
python eval/compare_runs.py --accept 12 13 14 --candidate 15 16 17
```

## 记录模板

见 [`TEMPLATE.md`](TEMPLATE.md)。最小要求：**假设、预测、改动文件、state 版本、
run id、结论**。没有 run id 的轮次不写进来——那只是感想。
