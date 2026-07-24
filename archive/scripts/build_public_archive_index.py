#!/usr/bin/env python3
"""Export sanitized capture metadata from the local corpus into Git.

This is the only command that writes archive data into the repository, and it
writes only ``data/archive_public/``. Every field is allowlisted in
``archivelib/publicexport.py``; the secret scan runs afterwards as a backstop
and a non-clean scan fails the command.

    python3 archive/scripts/build_public_archive_index.py
    python3 archive/scripts/build_public_archive_index.py --dry-run
    python3 archive/scripts/build_public_archive_index.py --scan-only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _cli import add_common_args, emit, get_archive_root, get_repo, run_guarded  # noqa: E402

from archivelib.publicexport import PUBLIC_DIR, build_public_export  # noqa: E402
from archivelib.sanitize import scan_public_export  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    parser.add_argument("--dry-run", action="store_true", help="compute the export; write nothing")
    parser.add_argument(
        "--scan-only",
        action="store_true",
        help="only run the secret scan over the existing public export (no external disk needed)",
    )
    args = parser.parse_args()

    repo = get_repo()

    if args.scan_only:
        scan = scan_public_export(repo / PUBLIC_DIR)
        if args.json:
            emit(scan, as_json=True)
        else:
            print(f"scanned {len(scan['scanned_files'])} file(s) under {PUBLIC_DIR}")
            for finding in scan["findings"]:
                print(f"  FINDING {finding['rule']} at {finding['path']}:{finding['line']} — {finding['excerpt']}")
            for bad in scan["forbidden_files"]:
                print(f"  FORBIDDEN {bad}")
            print(f"  result: {'CLEAN' if scan['ok'] else 'PROBLEMS FOUND'}")
        return 0 if scan["ok"] else 1

    root = get_archive_root(args, require_writable=False)
    report = build_public_export(root=root, repo=repo, write=not args.dry_run)

    if args.json:
        emit(report, as_json=True)
    else:
        print(f"public export -> {PUBLIC_DIR}" + ("  (dry run)" if args.dry_run else ""))
        print(f"  captures   : {report['capture_rows']}")
        print(f"  tombstones : {report['tombstone_rows']}")
        print(f"  manifests  : {report['manifest_summaries']}")
        scan = report["secret_scan"]
        print(f"  scanned    : {len(scan['scanned_files'])} file(s)")
        for finding in scan["findings"]:
            print(f"  FINDING {finding['rule']} at {finding['path']}:{finding['line']} — {finding['excerpt']}")
        for bad in scan["forbidden_files"]:
            print(f"  FORBIDDEN {bad}")
        print(f"  scan result: {'CLEAN' if scan['ok'] else 'PROBLEMS FOUND'}")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    run_guarded(main)
