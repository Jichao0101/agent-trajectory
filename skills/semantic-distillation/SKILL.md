---
name: semantic-distillation
description: 当用户要求对 agent-trajectory 中某条 trajectory 做异步语义蒸馏、复盘、提取任务意图、decision point、failure tags、uncertainty、causal links、evidence chain，或把 raw trajectory 转成 distilled experience 时使用。输入必须是明确的 trajectory_id 或明确的 raw bundle 路径。
---

# 语义蒸馏

本 skill 用于把 `/home/jichao/agent-trajectory` 中已经采集完成的一条 raw trajectory 异步蒸馏为中文经验记录。它不参与 hook、collector 或 scheduler 的同步调用路径。

## 使用边界

- 只处理用户指定的 `trajectory_id` 或明确 raw bundle 路径。
- 未经用户要求，不扫描全部 `trajectories/raw/`。
- 不修改 `trajectories/raw/<trajectory_id>/` 下的原始 bundle。
- 只把派生产物写入 `trajectories/distilled/<trajectory_id>/<distillation_run_id>/`。
- 可以使用 LLM 做语义判断，但每条语义结论必须保留 evidence chain。
- 证据不足时标记为低置信或不确定，不把时间顺序直接等同于因果关系。

## 工作流程

1. 确认输入是一条具体 `trajectory_id`；仓库根目录默认使用 `/home/jichao/agent-trajectory`。
2. 先生成确定性的蒸馏运行目录和证据索引：

```bash
python3 distiller/scripts/prepare_distillation.py \
  --root /home/jichao/agent-trajectory \
  --trajectory-id <trajectory_id> \
  --write-run
```

3. 读取同一条 trajectory 的 `trajectory_meta.json`、`raw_events.jsonl`、`artifact_index.json`、`snapshot_refs.json`，以及本次生成的 `evidence_index.json`。
4. 用中文补全 `distilled_experience.json` 和 `distilled_experience.md`，至少覆盖：
   - 任务意图与成功标准
   - 关键约束和上下文
   - 重要观察、动作和结果
   - 决策点与替代路径
   - 失败标签、不确定性和证据缺口
   - 可复用经验、候选 skill 或知识库沉淀建议
5. 未经过明确复核时，保持 `reviewer_status: unreviewed`。

## 证据链要求

- 每个 distilled claim 至少引用一个 `event_id`、`artifact_id`、`snapshot_id` 或连续事件范围。
- 因果判断必须说明依据；只有先后顺序时写成“时间上相邻”，不要写成“导致”。
- 无法从 raw bundle 验证的内容必须进入 `uncertainty`，不得写成确定事实。
- 若发现 raw bundle 不完整，停止蒸馏并报告缺失文件。

## 输出格式

完成后向用户报告：

- `distillation_run_id`
- 蒸馏产物目录
- 关键结论
- 主要不确定性
- 是否建议人工复核、知识库候选沉淀或新 skill 提炼
