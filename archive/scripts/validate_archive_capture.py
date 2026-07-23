#!/usr/bin/env python3
"""Validate one capture, or every capture in the corpus.

Read-only with one exception: it writes a validation report *alongside* previous
reports (never replacing one), because re-validating an old capture years later
must be possible without mutating it.

    python3 archive/scripts/validate_archive_capture.py --all
    python3 archive/scripts/validate_archive_capture.py --capture-dir <path>
    python3 archive/scripts/validate_archive_capture.py --all --no-write --json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _cli import add_common_args, emit, fail, get_archive_root, run_guarded  # noqa: E402

from archivelib.envmeta import utc_now_iso  # noqa: E402
from archivelib.schemaval import validate_document  # noqa: E402
from archivelib.validate import validate_capture  # noqa: E402


def iter_captures(root):
    corpus = root.corpus_dir
    if not corpus.is_dir():
        return
    for service in sorted(p for p in corpus.iterdir() if p.is_dir()):
        captures = service / "captures"
        if not captures.is_dir():
            continue
        for capture in sorted(p for p in captures.iterdir() if p.is_dir()):
            yield capture


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--capture-dir", type=Path, help="a single capture directory")
    group.add_argument("--all", action="store_true", help="validate every capture in the corpus")
    parser.add_argument("--no-write", action="store_true", help="do not persist the validation report")
    parser.add_argument("--schema", action="store_true", help="also validate capture.json against its JSON Schema")
    args = parser.parse_args()

    targets: list[Path] = []
    if args.capture_dir:
        if not args.capture_dir.is_dir():
            fail(f"not a directory: {args.capture_dir}")
        targets = [args.capture_dir]
    else:
        root = get_archive_root(args, require_writable=not args.no_write)
        targets = list(iter_captures(root))

    reports: list[dict] = []
    for capture_dir in targets:
        report = validate_capture(capture_dir, write_report=not args.no_write)
        report["capture_dir"] = capture_dir.name
        if args.schema:
            meta = capture_dir / "capture.json"
            if meta.exists():
                from archivelib.canonical import read_json

                report["schema_validation"] = validate_document(read_json(meta), "capture")
        reports.append(report)

    summary = {
        "validated_at_utc": utc_now_iso(),
        "capture_count": len(reports),
        "valid": sum(1 for r in reports if r["status"] == "valid"),
        "valid_with_warnings": sum(1 for r in reports if r["status"] == "valid_with_warnings"),
        "invalid": sum(1 for r in reports if r["status"] == "invalid"),
        "reports": reports,
    }

    if args.json:
        emit(summary, as_json=True)
    else:
        print(f"validated {summary['capture_count']} capture(s)")
        print(
            f"  valid={summary['valid']}  with_warnings={summary['valid_with_warnings']}  invalid={summary['invalid']}"
        )
        for report in reports:
            marker = {"valid": "OK  ", "valid_with_warnings": "WARN", "invalid": "FAIL"}[report["status"]]
            print(f"  {marker} {report['capture_dir']}")
            for check in report["failed_checks"]:
                detail = next((c["detail"] for c in report["checks"] if c["name"] == check), "")
                print(f"         error  : {check} — {detail}")
            for check in report["warning_checks"]:
                detail = next((c["detail"] for c in report["checks"] if c["name"] == check), "")
                print(f"         warning: {check} — {detail}")
            sv = report.get("schema_validation")
            if sv and sv.get("valid") is False:
                for err in sv["errors"][:5]:
                    print(f"         schema : {err['path']}: {err['message']}")

    return 0 if summary["invalid"] == 0 else 1


if __name__ == "__main__":
    run_guarded(main)
