#!/usr/bin/env python3
"""Discover a bounded seed set for one service, without capturing anything.

Read-only against the target: one homepage fetch plus at most one request per
known path. No credentials, no form submission, no directory brute-forcing.
Useful on its own to see what a capture *would* cover.

    python3 archive/scripts/discover_capture_seeds.py --domain example.com
    python3 archive/scripts/discover_capture_seeds.py --service-id foo_1a2b3c4d --json
    python3 archive/scripts/discover_capture_seeds.py --domain example.com --no-probe
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _cli import add_common_args, emit, fail, get_config, get_repo, run_guarded  # noqa: E402

from archivelib.identity import load_inventory, service_id_for_host  # noqa: E402
from archivelib.seeds import discover_seeds  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--domain", help="host as it appears in the monitor inventory")
    group.add_argument("--service-id", help="archive service_id")
    parser.add_argument("--no-probe", action="store_true", help="use homepage links only; do not probe known paths")
    args = parser.parse_args()

    repo = get_repo()
    cfg = get_config(args)
    inventory = load_inventory(repo)

    sid = args.service_id or service_id_for_host(args.domain)
    identity = inventory.get(sid)
    if identity is None:
        fail(
            f"service {sid!r} is not in the monitor inventory. "
            "This subsystem only archives services the monitor already tracks."
        )

    plan = discover_seeds(
        service_id=identity.service_id,
        host=identity.host,
        canonical_url=identity.canonical_url,
        cfg=cfg,
        probe_known_paths=not args.no_probe,
    )

    if args.json:
        emit(plan.as_dict(), as_json=True)
    else:
        print(f"service   : {identity.service_id}")
        print(f"host      : {identity.host}")
        print(f"platform  : {identity.platform_name or '(none)'}")
        print(f"seeds     : {len(plan.seeds)} (cap {cfg['capture']['max_seeds']})")
        for seed in plan.seeds:
            status = f" [{seed.http_status}]" if seed.http_status else ""
            print(f"  - {seed.page_type:<16} {seed.url}{status}  ({seed.origin})")
        if plan.missing_page_types:
            print(f"missing   : {', '.join(plan.missing_page_types)}")
            print("            (recorded as missing — never fabricated)")
        if plan.errors:
            print(f"errors    : {'; '.join(plan.errors)}")
    return 0


if __name__ == "__main__":
    run_guarded(main)
