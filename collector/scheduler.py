from __future__ import annotations

import argparse
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .paths import CollectorPaths
from .report import write_report
from .service import collect


@contextmanager
def collector_lock(paths: CollectorPaths) -> Iterator[bool]:
    paths.ensure()
    with paths.lock_file.open("w", encoding="utf-8") as handle:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


def run_once(root: Path, limit: int | None = None, write_feasibility_report: bool = False) -> dict[str, Any]:
    paths = CollectorPaths(root)
    with collector_lock(paths) as acquired:
        if not acquired:
            return {
                "locked": True,
                "processed": 0,
                "raw_trajectory_dir": str(paths.raw_trajectory_dir),
                "report_written": False,
            }
        result = collect(paths.root, limit)
        result["locked"] = False
        result["report_written"] = False
        if write_feasibility_report:
            write_report(paths.root)
            result["report_written"] = True
            result["report_file"] = str(paths.report_file)
        return result


def run_loop(
    root: Path,
    interval_seconds: float,
    limit: int | None = None,
    write_feasibility_report: bool = False,
    max_iterations: int | None = None,
) -> list[dict[str, Any]]:
    results = []
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        results.append(run_once(root, limit, write_feasibility_report))
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        time.sleep(interval_seconds)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the collector from a timer or lightweight background loop.")
    parser.add_argument("--root", default=".", help="agent-trajectory project root")
    parser.add_argument("--limit", type=int, help="maximum queued envelopes to process per run")
    parser.add_argument("--write-report", action="store_true", help="write the collection report after each run")
    parser.add_argument("--loop", action="store_true", help="keep polling the queue instead of running once")
    parser.add_argument("--interval", type=float, default=30.0, help="poll interval in seconds for --loop")
    args = parser.parse_args(argv)

    if args.loop:
        for result in run_loop(Path(args.root), args.interval, args.limit, args.write_report):
            print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
        return 0

    result = run_once(Path(args.root), args.limit, args.write_report)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
