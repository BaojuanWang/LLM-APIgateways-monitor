#!/usr/bin/env python3
"""Capture one service into the local corpus.

Requires a verified external $ARCHIVE_ROOT unless the explicit test-only opt-in
is set. Creates a new capture directory fail-closed, runs Browsertrix for the
canonical WACZ, adds rendered secondary representations, hashes everything, and
validates the result.

    export ARCHIVE_ROOT=/Volumes/<external-volume>/LLM-APIgateways-corpus
    python3 archive/scripts/run_archive_capture.py --domain example.com --reason manual
    python3 archive/scripts/run_archive_capture.py --domain example.com --dry-run
    python3 archive/scripts/run_archive_capture.py --domain example.com --max-seeds 3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _cli import add_common_args, emit, fail, get_archive_root, get_config, get_repo, run_guarded  # noqa: E402

from archivelib.capture import run_capture  # noqa: E402
from archivelib.docker_tools import check_docker_available, resolve_image_digest  # noqa: E402
from archivelib.identity import (  # noqa: E402
    ServiceIdentity,
    group_by_service,
    load_inventory,
    load_monitor_history,
    monitor_source_fingerprint,
    normalize_host,
    service_id_for_host,
)
from archivelib.locks import file_lock  # noqa: E402
from archivelib.seeds import discover_seeds  # noqa: E402

REASONS = (
    "first_capture", "status_transition", "reappearance", "homepage_hash_change",
    "final_url_change", "title_change", "tombstone_evidence", "monthly_interval",
    "retry_failure", "manual", "smoke_test",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--domain", help="host as it appears in the monitor inventory")
    group.add_argument("--service-id", help="archive service_id")
    parser.add_argument("--reason", choices=REASONS, default="manual")
    parser.add_argument("--max-seeds", type=int, default=None, help="override the seed cap for this run")
    parser.add_argument("--dry-run", action="store_true", help="plan the capture; write nothing")
    parser.add_argument(
        "--allow-unlisted",
        action="store_true",
        help="permit a host that is not in the monitor inventory (synthetic fixtures only)",
    )
    parser.add_argument("--url", help="explicit canonical URL; only valid with --allow-unlisted")
    args = parser.parse_args()

    repo = get_repo()
    overrides = {"capture": {"max_seeds": args.max_seeds}} if args.max_seeds else None
    cfg = get_config(args)
    if overrides:
        from archivelib.config import load_config

        cfg = load_config(repo, args.config, overrides)

    inventory = load_inventory(repo)
    sid = args.service_id or service_id_for_host(args.domain)
    identity = inventory.get(sid)

    if identity is None:
        if not args.allow_unlisted:
            fail(
                f"service {sid!r} is not in the monitor inventory. Pass --allow-unlisted "
                "only for synthetic fixture captures."
            )
        host = normalize_host(args.domain or args.url or "")
        identity = ServiceIdentity(
            service_id=service_id_for_host(host),
            host=host,
            canonical_url=args.url or f"https://{host}/",
            platform_name="",
            source="unlisted",
            inventory_file="(not in inventory)",
            inventory_file_sha256="",
            inventory_row={},
            inventory_row_sha256="",
        )
    elif args.url:
        fail("--url may only be used together with --allow-unlisted")

    # Prior monitor state gives the capture its "why now" context.
    prior_state: dict = {}
    try:
        observations = group_by_service(load_monitor_history(repo, limit_rows=60000)).get(identity.service_id, [])
        if observations:
            latest = observations[-1]
            prior_state = {
                "timestamp": latest.timestamp,
                "online_status": latest.online_status,
                "http_status": latest.http_status,
                "final_url": latest.final_url,
                "page_title": latest.page_title,
                "html_hash": latest.html_hash,
                "error": latest.error[:200],
            }
    except Exception:
        prior_state = {}

    # Resolve storage BEFORE touching the third-party site. Contacting a service
    # we have nowhere to store the result of is pointless traffic against
    # someone else's server, so a missing disk must fail before the first
    # request — except under --dry-run, where seed discovery IS the output.
    root = None if args.dry_run else get_archive_root(args)

    plan = discover_seeds(
        service_id=identity.service_id,
        host=identity.host,
        canonical_url=identity.canonical_url,
        cfg=cfg,
    )

    if args.dry_run:
        from archivelib.config import config_hash

        payload = {
            "dry_run": True,
            "service_id": identity.service_id,
            "host": identity.host,
            "reason": args.reason,
            "effective_config_hash": config_hash(cfg),
            "seeds": plan.as_dict(),
            "would_write_under": "$ARCHIVE_ROOT/corpus/%s/captures/<capture_id>/" % identity.service_id,
        }
        emit(payload, as_json=args.json, human=None)
        if not args.json:
            print(f"[dry-run] {identity.host}: {len(plan.seeds)} seed(s), reason={args.reason}")
            for seed in plan.seeds:
                print(f"  - {seed.page_type:<16} {seed.url}")
            print("  nothing written")
        return 0

    check_docker_available()

    bt = cfg.get("browsertrix", {})
    pin = resolve_image_digest(bt.get("image"), str(bt.get("tag")), pull=True)
    if not pin.digest and not pin.image_id:
        fail(f"could not pin the Browsertrix image: {pin.error}")

    lock = root.locks_dir / f"capture-{identity.service_id}.lock"
    with file_lock(lock, purpose=f"capture {identity.service_id}"):
        outcome = run_capture(
            root=root,
            repo=repo,
            identity=identity,
            plan=plan,
            cfg=cfg,
            reason=args.reason,
            browsertrix_pin=pin,
            prior_monitor_state=prior_state,
            monitor_source=monitor_source_fingerprint(repo),
        )

    payload = {
        "capture_id": outcome.capture_id,
        "service_id": outcome.service_id,
        "status": outcome.status,
        "corpus_relpath": outcome.capture_json.get("corpus_relpath"),
        "wacz_bytes": outcome.wacz_bytes,
        "wacz_sha256": outcome.wacz_sha256,
        "capture_directory_digest": outcome.manifest.get("capture_directory_digest"),
        "manifest_file_count": outcome.manifest.get("file_count"),
        "validation_status": outcome.validation.get("status"),
        "failed_checks": outcome.validation.get("failed_checks", []),
        "site_condition": outcome.capture_json.get("site_condition"),
        "errors": outcome.errors,
    }
    if args.json:
        emit(payload, as_json=True)
    else:
        print(f"capture   : {outcome.capture_id}")
        print(f"status    : {outcome.status}   site_condition={payload['site_condition']}")
        print(f"corpus    : $ARCHIVE_ROOT/{payload['corpus_relpath']}")
        print(f"wacz      : {outcome.wacz_bytes} bytes  sha256={outcome.wacz_sha256 or '(none)'}")
        print(f"manifest  : {payload['manifest_file_count']} files")
        print(f"digest    : {payload['capture_directory_digest']}")
        print(f"validation: {payload['validation_status']}")
        for check in payload["failed_checks"]:
            print(f"  FAILED  : {check}")
        for err in outcome.errors:
            print(f"  error   : {err}")

    return 0 if outcome.status == "completed" else 1


if __name__ == "__main__":
    run_guarded(main)
