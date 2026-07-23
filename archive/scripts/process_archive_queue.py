#!/usr/bin/env python3
"""Execute a planned capture queue, with locking, cooldown, and resume.

Designed to be safe under launchd: with ``--scheduled`` it exits 0 and logs a
line when the external volume is absent, so a missing disk is a no-op rather
than a recurring failure notification.

    python3 archive/scripts/process_archive_queue.py --dry-run
    python3 archive/scripts/process_archive_queue.py --queue <file> --max-sites 3
    python3 archive/scripts/process_archive_queue.py --resume
    python3 archive/scripts/process_archive_queue.py --scheduled   # launchd entry point
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _cli import add_common_args, emit, get_archive_root, get_config, get_repo, run_guarded  # noqa: E402

from archivelib.canonical import read_json, write_json  # noqa: E402
from archivelib.capture import run_capture  # noqa: E402
from archivelib.docker_tools import check_docker_available, resolve_image_digest  # noqa: E402
from archivelib.envmeta import utc_now_compact, utc_now_iso  # noqa: E402
from archivelib.errors import ArchiveError, ArchiveRootError, ExternalVolumeError  # noqa: E402
from archivelib.identity import load_inventory, load_monitor_history, monitor_source_fingerprint  # noqa: E402
from archivelib.locks import file_lock  # noqa: E402
from archivelib.queueplan import load_capture_history, plan_queue  # noqa: E402
from archivelib.seeds import discover_seeds  # noqa: E402


def latest_queue_file(root) -> Path | None:
    if not root.queue_dir.is_dir():
        return None
    files = sorted(root.queue_dir.glob("queue-*.json"))
    return files[-1] if files else None


def completed_capture_ids(root, service_id: str) -> set[str]:
    """capture_ids already on disk for a service — the basis for --resume."""
    captures = root.corpus_dir / service_id / "captures"
    if not captures.is_dir():
        return set()
    return {p.name for p in captures.iterdir() if p.is_dir() and (p / "capture.json").exists()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    parser.add_argument("--queue", type=Path, help="queue JSON to execute (default: newest in the corpus)")
    parser.add_argument("--dry-run", action="store_true", help="show what would be captured; write nothing")
    parser.add_argument("--service-id", help="process only this service from the queue")
    parser.add_argument("--domain", help="process only this host from the queue")
    parser.add_argument("--reason", help="force this capture reason")
    parser.add_argument("--max-sites", type=int, default=None, help="cap on services processed this run")
    parser.add_argument("--monthly-days", type=int, default=None)
    parser.add_argument("--retry-failures", action="store_true")
    parser.add_argument("--resume", action="store_true", help="skip services that already have a capture from this queue")
    parser.add_argument("--concurrency", type=int, default=None, help="bounded concurrency (default 1)")
    parser.add_argument(
        "--scheduled",
        action="store_true",
        help="launchd mode: exit 0 with a log line when the external volume is unavailable",
    )
    args = parser.parse_args()

    repo = get_repo()
    cfg = get_config(args)

    # --- storage: the one place launchd-friendly behaviour differs -----
    try:
        root = get_archive_root(args)
    except (ArchiveRootError, ExternalVolumeError) as exc:
        message = f"archive volume unavailable: {exc}"
        if args.scheduled:
            print(f"{utc_now_iso()} SKIP {message}")
            return 0
        print(f"ERROR: {message}", file=sys.stderr)
        return 2

    concurrency = int(args.concurrency or cfg.get("queue", {}).get("concurrency", 1))
    if concurrency != 1:
        print(f"note: concurrency={concurrency} requested; running sequentially is the supported mode", file=sys.stderr)

    # --- queue ----------------------------------------------------------
    if args.queue:
        queue = read_json(args.queue)
        queue_source = str(args.queue)
    else:
        existing = latest_queue_file(root)
        if existing and not (args.service_id or args.domain or args.reason):
            queue = read_json(existing)
            queue_source = str(existing.relative_to(root.path))
        else:
            queue = plan_queue(
                inventory=load_inventory(repo),
                observations=load_monitor_history(repo, limit_rows=60000),
                history=load_capture_history(repo),
                cfg=cfg,
                only_service_id=args.service_id,
                only_domain=args.domain,
                forced_reason=args.reason,
                max_sites=args.max_sites,
                monthly_days=args.monthly_days,
                retry_failures=True if args.retry_failures else None,
            )
            queue_source = "(planned in-process)"

    entries = list(queue.get("entries", []))
    if args.service_id:
        entries = [e for e in entries if e.get("service_id") == args.service_id]
    if args.domain:
        entries = [e for e in entries if e.get("host") == args.domain]
    if args.max_sites:
        entries = entries[: args.max_sites]

    inventory = load_inventory(repo)
    monitor_source = monitor_source_fingerprint(repo)

    results: list[dict] = []

    if args.dry_run:
        payload = {
            "dry_run": True,
            "queue_source": queue_source,
            "entries": [{"service_id": e["service_id"], "host": e["host"], "reason": e["reason"]} for e in entries],
        }
        emit(payload, as_json=args.json)
        if not args.json:
            print(f"[dry-run] queue={queue_source}  {len(entries)} service(s)")
            for entry in entries:
                print(f"  {entry['reason']:<22} {entry['host']}")
        return 0

    check_docker_available()
    bt = cfg.get("browsertrix", {})
    pin = resolve_image_digest(bt.get("image"), str(bt.get("tag")), pull=True)
    if not pin.digest and not pin.image_id:
        print(f"ERROR: could not pin the Browsertrix image: {pin.error}", file=sys.stderr)
        return 2

    run_id = utc_now_compact()
    with file_lock(root.locks_dir / "process-queue.lock", purpose="process_archive_queue"):
        for entry in entries:
            sid = entry["service_id"]
            identity = inventory.get(sid)
            if identity is None:
                results.append({"service_id": sid, "status": "skipped", "detail": "not in inventory"})
                continue
            if args.resume and completed_capture_ids(root, sid):
                results.append({"service_id": sid, "status": "skipped", "detail": "already captured (--resume)"})
                continue
            try:
                plan = discover_seeds(
                    service_id=identity.service_id,
                    host=identity.host,
                    canonical_url=identity.canonical_url,
                    cfg=cfg,
                )
                outcome = run_capture(
                    root=root,
                    repo=repo,
                    identity=identity,
                    plan=plan,
                    cfg=cfg,
                    reason=entry.get("reason", "manual"),
                    browsertrix_pin=pin,
                    prior_monitor_state=entry.get("prior_monitor_state") or {},
                    monitor_source=monitor_source,
                )
                results.append(
                    {
                        "service_id": sid,
                        "host": identity.host,
                        "capture_id": outcome.capture_id,
                        "status": outcome.status,
                        "validation_status": outcome.validation.get("status"),
                        "wacz_bytes": outcome.wacz_bytes,
                        "wacz_sha256": outcome.wacz_sha256,
                    }
                )
            except ArchiveError as exc:
                # A failed service must not abort the run: the remaining queue
                # entries are independent observations.
                results.append({"service_id": sid, "status": "error", "detail": f"{type(exc).__name__}: {exc}"})
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "service_id": sid,
                        "status": "error",
                        "detail": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(limit=3),
                    }
                )

        log = {
            "schema": "archive_queue_run",
            "run_id": run_id,
            "started_utc": utc_now_iso(),
            "queue_source": queue_source,
            "queue_hash": queue.get("queue_hash"),
            "concurrency": concurrency,
            "results": results,
        }
        write_json(root.logs_dir / f"run-{run_id}.json", log)

    payload = {"run_id": run_id, "processed": len(results), "results": results}
    if args.json:
        emit(payload, as_json=True)
    else:
        print(f"run {run_id}: {len(results)} service(s) from {queue_source}")
        for res in results:
            print(f"  {res['status']:<10} {res.get('host', res['service_id'])}  {res.get('detail', res.get('capture_id', ''))}")
    return 0 if all(r["status"] in ("completed", "skipped") for r in results) else 1


if __name__ == "__main__":
    run_guarded(main)
