#!/usr/bin/env python3
"""Render the launchd plist template — without installing or activating it.

This command deliberately stops at "here is a file you could install". It never
writes to ``~/Library/LaunchAgents`` and never calls ``launchctl``: scheduling a
recurring process that touches an external disk and a public repository is a
decision for the operator to make explicitly.

    python3 archive/scripts/install_launchd_template.py --print
    python3 archive/scripts/install_launchd_template.py --out ./edu.drexel.llm-api-archive.plist
    python3 archive/scripts/install_launchd_template.py --out <path> --hour 3 --minute 30
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _cli import add_common_args, fail, get_repo, run_guarded  # noqa: E402

TEMPLATE_REL = "archive/launchd/edu.drexel.llm-api-archive.plist.template"
DEFAULT_LABEL = "edu.drexel.llm-api-archive"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    parser.add_argument("--out", type=Path, help="write the rendered plist here (never into LaunchAgents)")
    parser.add_argument("--print", dest="do_print", action="store_true", help="print the rendered plist to stdout")
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--archive-root", help="value to substitute for __ARCHIVE_ROOT__ (default: $ARCHIVE_ROOT)")
    parser.add_argument("--python", default=sys.executable, help="python interpreter to run")
    parser.add_argument("--hour", type=int, default=4, help="local hour to run (0-23)")
    parser.add_argument("--minute", type=int, default=0, help="local minute to run (0-59)")
    parser.add_argument("--max-sites", type=int, default=5)
    args = parser.parse_args()

    if not args.out and not args.do_print:
        fail("choose --out <path> and/or --print; this command never installs the job itself")

    repo = get_repo()
    template_path = repo / TEMPLATE_REL
    if not template_path.exists():
        fail(f"template missing: {TEMPLATE_REL}")

    import os

    archive_root = args.archive_root or os.environ.get("ARCHIVE_ROOT", "")
    if not archive_root:
        fail("ARCHIVE_ROOT is not set and --archive-root was not given")
    if not archive_root.startswith("/Volumes/"):
        fail(f"refusing to schedule against a non-/Volumes ARCHIVE_ROOT: {archive_root!r}")

    rendered = (
        template_path.read_text(encoding="utf-8")
        .replace("__LABEL__", args.label)
        .replace("__ARCHIVE_ROOT__", archive_root)
        .replace("__REPO_ROOT__", str(repo))
        .replace("__PYTHON__", str(args.python))
        .replace("__HOUR__", str(args.hour))
        .replace("__MINUTE__", str(args.minute))
        .replace("__MAX_SITES__", str(args.max_sites))
    )

    if args.out:
        out = Path(args.out).expanduser()
        if "LaunchAgents" in out.parts or "LaunchDaemons" in out.parts:
            fail(
                "refusing to write directly into LaunchAgents/LaunchDaemons. "
                "Render elsewhere, review it, then copy and `launchctl load` it yourself."
            )
        if out.exists():
            fail(f"refusing to overwrite {out}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
        print(f"wrote {out}")
        print()
        print("NOT installed and NOT activated. To install it yourself, after reviewing:")
        print(f"  cp {out} ~/Library/LaunchAgents/{args.label}.plist")
        print(f"  launchctl load ~/Library/LaunchAgents/{args.label}.plist")
        print()
        print("The job exits 0 when the external volume is absent, so an unplugged disk is a no-op.")

    if args.do_print:
        print(rendered)

    return 0


if __name__ == "__main__":
    run_guarded(main)
