#!/usr/bin/env python3
"""End-to-end smoke test against the local synthetic fixture site.

Not a pytest test: it needs Docker, pulls a pinned image, and takes minutes.
The unit suite must stay fast and hermetic, so this lives beside it as a script.

What it exercises that unit tests cannot: a real Browsertrix crawl producing a
real WACZ, real Playwright rendering, real SingleFile output, and the full
manifest -> validate -> public-export -> secret-scan chain over genuine
artifacts.

Requires the explicit test-only storage opt-in and refuses to touch a real
corpus:

    export ARCHIVE_TEST_ONLY_ALLOW_NONEXTERNAL=1
    export ARCHIVE_ROOT=/some/scratch/dir
    python3 archive/tests/smoke_browsertrix.py --keep

The fixture server binds 0.0.0.0 so the container can reach it; the URL used is
the host's own LAN address, which resolves identically on the host (for
Playwright and seed discovery) and inside the container (for Browsertrix).
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ARCHIVE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ARCHIVE_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from archivelib.capture import run_capture  # noqa: E402
from archivelib.config import load_config  # noqa: E402
from archivelib.docker_tools import check_docker_available, resolve_image_digest  # noqa: E402
from archivelib.identity import ServiceIdentity, service_id_for_host  # noqa: E402
from archivelib.paths import repo_root, resolve_archive_root  # noqa: E402
from archivelib.publicexport import build_public_export  # noqa: E402
from archivelib.seeds import discover_seeds  # noqa: E402
from fixture_server import FixtureSite  # noqa: E402


def host_address() -> str:
    """An address for the fixture site that works on the host AND in Docker.

    ``127.0.0.1`` means the container itself, and ``host.docker.internal`` does
    not resolve on the host — so neither works for both. The machine's own LAN
    address does.
    """
    try:
        out = subprocess.run(
            ["ipconfig", "getifaddr", "en0"], capture_output=True, timeout=10, check=False
        )
        candidate = out.stdout.decode().strip()
        if candidate:
            return candidate
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 53))  # TEST-NET-1: no packet is actually sent
        return sock.getsockname()[0]
    finally:
        sock.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", action="store_true", help="keep the synthetic capture directory")
    parser.add_argument("--port", type=int, default=8731)
    parser.add_argument("--max-seeds", type=int, default=4)
    args = parser.parse_args()

    repo = repo_root()
    root = resolve_archive_root(allow_nonexternal=True)
    if root.is_real:
        print("REFUSING: this smoke test must not run against a real external corpus.", file=sys.stderr)
        return 2
    print(f"archive root : {root.path}  [mode={root.mode}]")

    check_docker_available()
    cfg = load_config(repo, None, {"capture": {"max_seeds": args.max_seeds, "page_limit": args.max_seeds}})
    pin = resolve_image_digest(cfg["browsertrix"]["image"], cfg["browsertrix"]["tag"], pull=True)
    print(f"browsertrix  : {pin.reference}")
    if not pin.digest:
        print(f"WARNING: image not digest-pinned: {pin.error}", file=sys.stderr)

    address = host_address()
    site = FixtureSite(port=args.port)
    site.httpd.server_close()
    # Rebind on all interfaces so the container can reach the fixture.
    from functools import partial
    from http.server import ThreadingHTTPServer

    from fixture_server import SITE_DIR, FixtureHandler

    handler = partial(FixtureHandler, site_dir=SITE_DIR)
    httpd = ThreadingHTTPServer(("0.0.0.0", args.port), handler)
    import threading

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://{address}:{args.port}/"
    print(f"fixture site : {base_url}")

    host = f"{address}:{args.port}"
    identity = ServiceIdentity(
        service_id=service_id_for_host(address),
        host=address,
        canonical_url=base_url,
        platform_name="Fixture Gateway",
        source="synthetic",
        inventory_file="archive/tests/fixtures/master_sites_sample.csv",
        inventory_file_sha256="0" * 64,
        inventory_row={"domain": host, "platform_name": "Fixture Gateway"},
        inventory_row_sha256="1" * 64,
    )

    outcome = None
    try:
        plan = discover_seeds(
            service_id=identity.service_id,
            host=identity.host,
            canonical_url=base_url,
            cfg=cfg,
        )
        print(f"seeds        : {len(plan.seeds)}")
        for seed in plan.seeds:
            print(f"   {seed.page_type:<16} {seed.url}")
        print(f"missing      : {', '.join(plan.missing_page_types) or '(none)'}")

        print("running browsertrix …")
        outcome = run_capture(
            root=root,
            repo=repo,
            identity=identity,
            plan=plan,
            cfg=cfg,
            reason="smoke_test",
            browsertrix_pin=pin,
            prior_monitor_state={"timestamp": "", "online_status": "ONLINE", "final_url": base_url},
            monitor_source={"file": "(synthetic smoke test)", "exists": False},
        )

        print()
        print(f"capture_id   : {outcome.capture_id}")
        print(f"status       : {outcome.status}")
        print(f"wacz bytes   : {outcome.wacz_bytes}")
        print(f"wacz sha256  : {outcome.wacz_sha256}")
        print(f"dir digest   : {outcome.manifest.get('capture_directory_digest')}")
        print(f"manifest     : {outcome.manifest.get('file_count')} files, {outcome.manifest.get('total_bytes')} bytes")
        print(f"validation   : {outcome.validation.get('status')}")
        for check in outcome.validation.get("failed_checks", []):
            detail = next(
                (c["detail"] for c in outcome.validation["checks"] if c["name"] == check), ""
            )
            print(f"   FAILED    : {check} — {detail}")
        for check in outcome.validation.get("warning_checks", []):
            detail = next(
                (c["detail"] for c in outcome.validation["checks"] if c["name"] == check), ""
            )
            print(f"   warning   : {check} — {detail}")
        for err in outcome.errors:
            print(f"   error     : {err}")

        rendered = outcome.capture_json.get("rendered", {})
        print(f"rendered     : {len(rendered.get('pages', []))} page(s), "
              f"{rendered.get('network_records')} network records")
        sf = outcome.capture_json.get("singlefile", [])
        print(f"singlefile   : {json.dumps(sf)[:200]}")

        # Public export into a scratch repo copy, then scan it.
        export_repo = root.path / "public-export-check"
        (export_repo / "data" / "archive_public").mkdir(parents=True, exist_ok=True)
        report = build_public_export(root=root, repo=export_repo, write=True)
        print()
        print(f"public export: {report['capture_rows']} capture row(s), {report['tombstone_rows']} tombstone(s)")
        print(f"secret scan  : {'CLEAN' if report['secret_scan']['ok'] else 'PROBLEMS'}")
        for finding in report["secret_scan"]["findings"]:
            print(f"   FINDING   : {finding['rule']} {finding['path']}:{finding['line']} {finding['excerpt']}")
        for bad in report["secret_scan"]["forbidden_files"]:
            print(f"   FORBIDDEN : {bad}")

        ok = outcome.status == "completed" and str(outcome.validation.get("status", "")).startswith("valid") and report["secret_scan"]["ok"]
        print()
        print(f"SMOKE TEST   : {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1
    finally:
        httpd.shutdown()
        httpd.server_close()
        if not args.keep and outcome is not None and outcome.capture_dir.exists():
            # Only ever removes synthetic output: real mode is refused above.
            shutil.rmtree(outcome.capture_dir.parent.parent, ignore_errors=True)
            print(f"cleaned up synthetic capture under {root.path}")


if __name__ == "__main__":
    raise SystemExit(main())
