from __future__ import annotations

import argparse

from .hook_adapter import main as enqueue_main
from .report import main as report_main
from .scheduler import main as scheduler_main
from .service import main as collect_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent trajectory collector CLI")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("enqueue", help="enqueue a hook payload")
    subcommands.add_parser("collect", help="process queued hook payloads")
    subcommands.add_parser("schedule", help="run collector once or poll from a timer")
    subcommands.add_parser("report", help="build a collector report")
    args, rest = parser.parse_known_args(argv)
    if args.command == "enqueue":
        return enqueue_main(rest)
    if args.command == "collect":
        return collect_main(rest)
    if args.command == "schedule":
        return scheduler_main(rest)
    if args.command == "report":
        return report_main(rest)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
