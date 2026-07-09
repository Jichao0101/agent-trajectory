# Agent Trajectory Collector

本仓库实现 agent trajectory 的 hook 驱动采集器。

当前范围：

- hook adapter 只执行轻量本地 enqueue。
- collector 将 queued hook payload 转换为按 trajectory 分段的 append-only raw events。
- raw events 记录 schema version、collector version、全局 sequence、trajectory 内 sequence、correlation metadata、payload artifact refs 和 baseline snapshot refs。
- report 聚合 per-trajectory raw bundle，输出采集状态、ordering、tool correlation 和基础可观测性指标。
- raw collection 路径不调用 LLM。

## 快速运行

```bash
printf '{"tool_name":"shell","tool_call_id":"call-1","session_id":"demo","cwd":"/home/jichao/agent-trajectory"}' \
  | python3 -m collector.hook_adapter --root . --hook-name tool_pre

python3 -m collector.service --root .
python3 -m collector.report --root . --write
```

## 连续采集

为了降低 hook 同步开销，hook 路径保持 enqueue-only，collector 在 hook 外运行：

```bash
python3 -m collector.scheduler --root /home/jichao/agent-trajectory --limit 100 --write-report
python3 -m collector.scheduler --root /home/jichao/agent-trajectory --loop --interval 30 --limit 100 --write-report
```

`scheduler` 使用 collector lock，重叠触发时不会并发消费 queue。

## 主要输出

- `storage/queue/hook_events.jsonl`
- `storage/artifacts/*.json`
- `storage/snapshots/*.json`
- `trajectories/raw/<trajectory_id>/raw_events.jsonl`
- `trajectories/raw/<trajectory_id>/trajectory_meta.json`
- `trajectories/collection_report.json`
