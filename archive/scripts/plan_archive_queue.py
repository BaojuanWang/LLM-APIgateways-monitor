#!/usr/bin/env python3
"""Plan which services deserve a full capture, from monitor data alone.

Reads the monitor's results and the *sanitized public* capture history, so
``--dry-run`` works with the external disk unplugged. Never queues the whole
inventory: output is bounded by ``--max-sites`` and ordered deterministically.

    python3 archive/scripts/plan_archive_queue.py --dry-run
    python3 archive/scripts/plan_archive_queue.py --dry-run --max-sites 5
    python3 archive/scripts/plan_archive_queue.py --service-id foo_1a2b3c4d --reason manual
    python3 archive/scripts/plan_archive_queue.py --monthly-days 45 --retry-failures
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _cli import add_common_args, emit, get_archive_root, get_config, get_repo, run_guarded  # noqa: E402

from archivelib.canonical import write_json  # noqa: E402
from archivelib.envmeta import utc_now_compact  # noqa: E402
from archivelib.identity import load_inventory, load_monitor_history  # noqa: E402
from archivelib.locks import file_lock  # noqa: E402
from archivelib.queueplan import load_capture_history, plan_queue  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    parser.add_argument("--dry-run", action="store_true", help="print the queue; write nothing")
    parser.add_argument("--service-id", help="restrict planning to one service_id")
    parser.add_argument("--domain", help="restrict planning to one host")
    parser.add_argument("--reason", help="force this capture reason for the selected service(s)")
    parser.add_argument("--max-sites", type=int, default=None, help="cap on queued services")
    parser.add_argument("--monthly-days", type=int, default=None, help="periodic re-capture interval in days")
    parser.add_argument("--retry-failures", action="store_true", help="also queue services whose last capture failed")
    parser.add_argument("--history-rows", type=int, default=60000, help="most recent monitor rows to consider")
    args = parser.parse_args()

    repo = get_repo()
    cfg = get_config(args)

    inventory = load_inventory(repo)
    observations = load_monitor_history(repo, limit_rows=args.history_rows)
    history = load_capture_history(repo)

    queue = plan_queue(
        inventory=inventory,
        observations=observations,
        history=history,
        cfg=cfg,
        only_service_id=args.service_id,
        only_domain=args.domain,
        forced_reason=args.reason,
        max_sites=args.max_sites,
        monthly_days=args.monthly_days,
        retry_failures=True if args.retry_failures else None,
    )

    written_to = None
    if not args.dry_run:
        root = get_archive_root(args)
        with file_lock(root.locks_dir / "plan-queue.lock", purpose="plan_archive_queue"):
            target = root.queue_dir / f"queue-{utc_now_compact()}.json"
            if target.exists():
                from archivelib.errors import OverwriteError

                raise OverwriteError(f"queue file already exists: {target}")
            write_json(target, queue)
            written_to = str(target.relative_to(root.path))
    queue["written_to"] = written_to

    if args.json:
        emit(queue, as_json=True)
    else:
        counts = queue["counts"]
        print(f"planned at {queue['generated_at_utc']}  (queue_hash={queue['queue_hash']})")
        print(
            f"  inventory={counts['inventory']}  observed={counts['with_observations']}  "
            f"candidates={counts['candidates']}  selected={counts['selected']}  "
            f"deferred={counts['deferred']}  skipped_cooldown={counts['skipped_cooldown']}"
        )
        for entry in queue["entries"]:
            print(f"  [{entry['priority']:>3}] {entry['reason']:<22} {entry['host']}")
            if entry["detail"]:
                print(f"        {entry['detail']}")
        if not queue["entries"]:
            print("  nothing to capture")
        print(f"  written to: $ARCHIVE_ROOT/{written_to}" if written_to else "  dry run — nothing written")
    return 0


if __name__ == "__main__":
    run_guarded(main)
