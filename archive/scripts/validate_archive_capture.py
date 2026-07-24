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

    def outcome_of(r):
        return (r.get("outcome") or {}).get("outcome", "")

    # Outcome-aware categories (the WACZ requirement follows the outcome policy).
    valid_wacz = [r for r in reports if outcome_of(r) == "archived" and r["status"].startswith("valid")]
    valid_unreachable = [r for r in reports if outcome_of(r) == "documented_unreachable"]
    retryable = [r for r in reports if outcome_of(r) == "retryable_no_wacz"]
    incomplete = [r for r in reports if r["status"] == "incomplete" or outcome_of(r) == "incomplete"]
    # Anything invalid that is not a retryable-no-WACZ (e.g. corrupt WACZ, hash
    # mismatch) is a hard failure that still needs attention.
    other_invalid = [
        r for r in reports if r["status"] == "invalid" and outcome_of(r) != "retryable_no_wacz"
    ]

    summary = {
        "validated_at_utc": utc_now_iso(),
        "capture_count": len(reports),
        "valid_total": sum(1 for r in reports if r["status"].startswith("valid")),
        "valid_wacz_captures": len(valid_wacz),
        "valid_tombstones_without_wacz": len(valid_unreachable),
        "retryable_failures": len(retryable),
        "other_invalid": len(other_invalid),
        "incomplete_interrupted": len(incomplete),
        "reports": reports,
    }

    if args.json:
        emit(summary, as_json=True)
    else:
        print(f"validated {summary['capture_count']} capture(s) (incomplete excluded from valid/invalid totals)")
        print(f"  valid WACZ captures            : {summary['valid_wacz_captures']}")
        print(f"  valid tombstones without WACZ  : {summary['valid_tombstones_without_wacz']}")
        print(f"  retryable failures             : {summary['retryable_failures']}")
        if summary["other_invalid"]:
            print(f"  other invalid (needs attention): {summary['other_invalid']}")
        print(f"  incomplete / interrupted       : {summary['incomplete_interrupted']}")
        marker = {"valid": "OK  ", "valid_with_warnings": "WARN", "invalid": "FAIL", "incomplete": "INCM"}
        for report in reports:
            oc = outcome_of(report)
            tag = {"documented_unreachable": " [tombstone/no-wacz]", "retryable_no_wacz": " [retryable]",
                   "incomplete": " [quarantined]"}.get(oc, "")
            print(f"  {marker.get(report['status'], '????')} {report['capture_dir']}{tag}")
            for check in report["failed_checks"]:
                detail = next((c["detail"] for c in report["checks"] if c["name"] == check), "")
                print(f"         error  : {check} — {detail}")
            sv = report.get("schema_validation")
            if sv and sv.get("valid") is False:
                for err in sv["errors"][:5]:
                    print(f"         schema : {err['path']}: {err['message']}")

    # Exit non-zero only on hard failures (retryable/other invalid); tombstone
    # captures and quarantined interrupted dirs are not failures.
    return 0 if not retryable and not other_invalid else 1


if __name__ == "__main__":
    run_guarded(main)
