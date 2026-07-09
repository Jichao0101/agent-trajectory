# Agent Trajectory Phase 0

This repository contains the Phase 0 hook feasibility spike for the agent
trajectory design.

Phase 0 scope:

- hook adapter performs lightweight local enqueue only
- collector converts queued hook payloads into append-only raw events
- raw events include schema version, collector version, sequence ordering,
  correlation metadata, payload artifact refs, and baseline snapshot refs
- report answers the Phase 0 feasibility questions
- raw collection path uses zero LLM calls

Run a sample:

```bash
printf '{"tool_name":"shell","tool_call_id":"call-1","session_id":"demo","cwd":"/home/jichao/agent-trajectory"}' \
  | python3 -m collector.hook_adapter --root . --hook-name tool_pre

python3 -m collector.service --root .
python3 -m collector.report --root . --write
```

For low-overhead continuous collection, keep hooks as enqueue-only and run the
collector outside the hook path:

```bash
python3 -m collector.scheduler --root /home/jichao/agent-trajectory --limit 100 --write-report
python3 -m collector.scheduler --root /home/jichao/agent-trajectory --loop --interval 30 --limit 100 --write-report
```

The scheduler uses a collector lock, so overlapping timer invocations do not
process the queue concurrently.

Primary outputs:

- `storage/queue/hook_events.jsonl`
- `storage/artifacts/*.json`
- `storage/snapshots/*.json`
- `trajectories/raw_events.jsonl`
- `trajectories/phase0_feasibility_report.json`
