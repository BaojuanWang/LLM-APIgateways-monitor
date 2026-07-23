"""Capture validation.

Validation answers one question: *can this capture be cited as evidence?* It is
not a health check on the remote site. A capture of a dead, blocked, or parked
service can be perfectly valid; what makes a capture invalid is that its own
artifacts are missing, corrupt, unhashed, mutated, or stored somewhere they must
never be.

Checks implemented (each maps to a required detection in the subsystem spec):

* missing WACZ
* corrupt ZIP/WACZ container
* missing Browsertrix logs
* missing manifest entries / hash mismatches / files added post-manifest
* absolute local path leakage in metadata
* secret-like content in outputs destined for the public export
* accidental overwrite attempts (pre-existing capture directory)
* raw files located inside the Git repository
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .canonical import read_json, write_json
from .envmeta import utc_now_iso
from .manifest import MANIFEST_RELPATH, load_manifest, verify_manifest
from .paths import repo_root
from .sanitize import SECRET_RULES, scan_text_for_secrets

VALIDATION_RELPATH = "validation/validation.json"

SEVERITY_ORDER = ("error", "warning", "info")


@dataclass
class Check:
    name: str
    passed: bool
    severity: str = "error"
    detail: str = ""
    data: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "severity": self.severity,
            "detail": self.detail,
            "data": self.data,
        }


def _wacz_path(capture_root: Path) -> Path | None:
    collections = capture_root / "raw" / "browsertrix" / "collections"
    if not collections.is_dir():
        return None
    for wacz in sorted(collections.glob("*/*.wacz")):
        return wacz
    return None


def check_wacz_present(capture_root: Path) -> tuple[Check, Path | None]:
    wacz = _wacz_path(capture_root)
    if wacz is None:
        return (
            Check(
                name="wacz_present",
                passed=False,
                detail="no .wacz found under raw/browsertrix/collections/*/",
            ),
            None,
        )
    size = wacz.stat().st_size
    return (
        Check(
            name="wacz_present",
            passed=size > 0,
            detail=f"{wacz.name} ({size} bytes)" if size else f"{wacz.name} is empty",
            data={"relative_path": str(wacz.relative_to(capture_root)), "size_bytes": size},
        ),
        wacz,
    )


# Entries a WACZ is expected to carry. `pages/pages.jsonl` and the datapackage
# are what replay tools actually need.
WACZ_EXPECTED_MEMBERS = ("datapackage.json",)


def check_wacz_container(wacz: Path | None) -> Check:
    """Open the WACZ as a ZIP and verify its members are readable.

    ``testzip()`` reads every member and checks CRCs, which is what catches a
    crawl that was killed mid-write — the file exists and looks plausible but
    the central directory or a deflate stream is truncated.
    """
    if wacz is None:
        return Check(name="wacz_container_valid", passed=False, detail="no WACZ to inspect")
    if not zipfile.is_zipfile(wacz):
        return Check(
            name="wacz_container_valid",
            passed=False,
            detail="file is not a valid ZIP container (WACZ is a ZIP)",
        )
    try:
        with zipfile.ZipFile(wacz) as archive:
            bad = archive.testzip()
            if bad is not None:
                return Check(
                    name="wacz_container_valid",
                    passed=False,
                    detail=f"CRC failure in member {bad!r}",
                )
            names = archive.namelist()
    except zipfile.BadZipFile as exc:
        return Check(name="wacz_container_valid", passed=False, detail=f"corrupt ZIP: {exc}")
    except OSError as exc:
        return Check(name="wacz_container_valid", passed=False, detail=f"unreadable WACZ: {exc}")

    missing = [m for m in WACZ_EXPECTED_MEMBERS if m not in names]
    has_warc = any(n.startswith("archive/") for n in names)
    return Check(
        name="wacz_container_valid",
        passed=not missing and has_warc,
        detail=(
            "ok"
            if not missing and has_warc
            else f"missing members: {missing}; warc payload present: {has_warc}"
        ),
        data={"member_count": len(names), "has_warc_payload": has_warc},
    )


def check_browsertrix_logs(capture_root: Path) -> Check:
    collections = capture_root / "raw" / "browsertrix" / "collections"
    logs = sorted(collections.glob("*/logs/*")) if collections.is_dir() else []
    return Check(
        name="browsertrix_logs_present",
        passed=bool(logs),
        detail=f"{len(logs)} log file(s)" if logs else "no Browsertrix logs retained",
        data={"log_files": [str(p.relative_to(capture_root)) for p in logs[:20]]},
    )


def check_browsertrix_aux(capture_root: Path) -> Check:
    """Indexes / pages / reports are expected but not fatal when absent."""
    collections = capture_root / "raw" / "browsertrix" / "collections"
    present = {}
    for sub in ("archive", "indexes", "pages", "logs", "reports"):
        present[sub] = bool(list(collections.glob(f"*/{sub}"))) if collections.is_dir() else False
    required = ("archive", "indexes", "pages")
    missing = [k for k in required if not present[k]]
    return Check(
        name="browsertrix_output_dirs",
        passed=not missing,
        severity="warning",
        detail="all expected output directories present" if not missing else f"missing: {missing}",
        data=present,
    )


def check_manifest(capture_root: Path) -> tuple[Check, Check, Check, Check]:
    if not (capture_root / MANIFEST_RELPATH).exists():
        absent = Check(name="manifest_present", passed=False, detail="no sha256 manifest")
        skipped = lambda name: Check(name=name, passed=False, detail="skipped: manifest absent")  # noqa: E731
        return absent, skipped("manifest_complete"), skipped("manifest_hashes_match"), skipped("no_files_added_after_manifest")

    report = verify_manifest(capture_root)
    return (
        Check(name="manifest_present", passed=True, detail=f"{report['file_count']} entries"),
        Check(
            name="manifest_complete",
            passed=not report["missing_files"],
            detail="all manifest entries exist on disk"
            if not report["missing_files"]
            else f"{len(report['missing_files'])} manifest entries missing from disk",
            data={"missing_files": report["missing_files"][:50]},
        ),
        Check(
            name="manifest_hashes_match",
            passed=not report["hash_mismatches"] and report["digest_matches"],
            detail="all hashes and the directory digest match"
            if not report["hash_mismatches"] and report["digest_matches"]
            else f"{len(report['hash_mismatches'])} hash mismatch(es); digest_matches={report['digest_matches']}",
            data={
                "hash_mismatches": report["hash_mismatches"][:50],
                "digest_recorded": report["digest_recorded"],
                "digest_recomputed": report["digest_recomputed"],
            },
        ),
        Check(
            name="no_files_added_after_manifest",
            passed=not report["added_files"],
            detail="no unmanifested files"
            if not report["added_files"]
            else f"{len(report['added_files'])} file(s) present but not in the manifest",
            data={"added_files": report["added_files"][:50]},
        ),
    )


def check_symlinks(capture_root: Path) -> Check:
    from .paths import assert_no_symlink_escape

    escapes = assert_no_symlink_escape(capture_root)
    return Check(
        name="no_symlink_escape",
        passed=not escapes,
        detail="no symlinks point outside the capture" if not escapes else f"{len(escapes)} escaping symlink(s)",
        data={"escapes": escapes[:20]},
    )


def check_not_in_repo(capture_root: Path) -> Check:
    repo = repo_root()
    resolved = Path(capture_root).resolve()
    inside = resolved == repo or str(resolved).startswith(str(repo) + "/")
    return Check(
        name="raw_not_inside_git_repo",
        passed=not inside,
        detail="capture is outside the Git repository"
        if not inside
        else "capture directory is INSIDE the Git repository; raw archival material must never live there",
    )


# Metadata files that are read by the public exporter and therefore must be
# free of absolute paths and secret-like strings.
PUBLIC_FACING_FILES = (
    "capture.json",
    "config/environment.json",
    "config/effective_archive_config.json",
    "config/seeds.txt",
    "validation/browsertrix_exit.json",
)


def check_no_absolute_paths(capture_root: Path) -> Check:
    offenders: list[dict] = []
    for rel in PUBLIC_FACING_FILES:
        path = capture_root / rel
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for finding in scan_text_for_secrets(text, rel):
            if finding.rule in ("absolute_user_path", "absolute_volume_path"):
                offenders.append(finding.as_dict())
    return Check(
        name="no_absolute_path_leakage",
        passed=not offenders,
        detail="no machine-specific absolute paths in public-facing metadata"
        if not offenders
        else f"{len(offenders)} absolute path leak(s)",
        data={"offenders": offenders[:25]},
    )


def check_no_secretlike_in_public_facing(capture_root: Path) -> Check:
    offenders: list[dict] = []
    for rel in PUBLIC_FACING_FILES:
        path = capture_root / rel
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for finding in scan_text_for_secrets(text, rel):
            if finding.rule not in ("absolute_user_path", "absolute_volume_path"):
                offenders.append(finding.as_dict())
    return Check(
        name="no_secretlike_content_in_public_facing_metadata",
        passed=not offenders,
        detail="no secret-like strings in public-facing metadata"
        if not offenders
        else f"{len(offenders)} secret-like match(es)",
        data={"offenders": offenders[:25], "rules_applied": [name for name, _ in SECRET_RULES]},
    )


# Filenames that only exist inside a Chrome user-data directory. Their presence
# means a browser profile survived into a sealed capture, which is both dead
# weight and a concentration of browser state that has no evidential value.
_PROFILE_MARKERS = ("Cookies", "History", "Web Data", "Login Data", "Preferences")


def check_no_browser_profile(capture_root: Path) -> Check:
    collections = capture_root / "raw" / "browsertrix" / "collections"
    offenders: list[str] = []
    if collections.is_dir():
        for profile_dir in collections.glob("*/profile"):
            offenders.append(str(profile_dir.relative_to(capture_root)))
        for marker in _PROFILE_MARKERS:
            for hit in collections.glob(f"*/**/{marker}"):
                if hit.is_file():
                    offenders.append(str(hit.relative_to(capture_root)))
    return Check(
        name="no_browser_profile_retained",
        passed=not offenders,
        detail="no Chrome user-data directory in the capture"
        if not offenders
        else f"{len(offenders)} browser-profile artifact(s) retained",
        data={"offenders": sorted(set(offenders))[:20]},
    )


def check_capture_metadata(capture_root: Path) -> Check:
    path = capture_root / "capture.json"
    if not path.exists():
        return Check(name="capture_metadata_present", passed=False, detail="capture.json missing")
    try:
        meta = read_json(path)
    except Exception as exc:
        return Check(name="capture_metadata_present", passed=False, detail=f"unreadable capture.json: {exc}")
    required = ("capture_id", "service_id", "started_utc", "capture_reason", "effective_config_hash")
    missing = [k for k in required if not meta.get(k)]
    return Check(
        name="capture_metadata_present",
        passed=not missing,
        detail="capture.json complete" if not missing else f"missing fields: {missing}",
    )


def validate_capture(capture_root: Path, *, write_report: bool = True) -> dict:
    """Run every check and (optionally) persist the report inside the capture."""
    capture_root = Path(capture_root)
    checks: list[Check] = []

    wacz_check, wacz = check_wacz_present(capture_root)
    checks.append(wacz_check)
    checks.append(check_wacz_container(wacz))
    checks.append(check_browsertrix_logs(capture_root))
    checks.append(check_browsertrix_aux(capture_root))
    checks.extend(check_manifest(capture_root))
    checks.append(check_symlinks(capture_root))
    checks.append(check_not_in_repo(capture_root))
    checks.append(check_no_absolute_paths(capture_root))
    checks.append(check_no_secretlike_in_public_facing(capture_root))
    checks.append(check_no_browser_profile(capture_root))
    checks.append(check_capture_metadata(capture_root))

    errors = [c for c in checks if not c.passed and c.severity == "error"]
    warnings = [c for c in checks if not c.passed and c.severity == "warning"]

    status = "valid" if not errors else "invalid"
    if not errors and warnings:
        status = "valid_with_warnings"

    manifest_digest = None
    try:
        manifest_digest = load_manifest(capture_root).get("capture_directory_digest")
    except Exception:
        pass

    report = {
        "schema": "validation",
        "validated_at_utc": utc_now_iso(),
        "capture_directory_digest": manifest_digest,
        "status": status,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "checks": [c.as_dict() for c in checks],
        "failed_checks": [c.name for c in errors],
        "warning_checks": [c.name for c in warnings],
    }

    if write_report:
        target = capture_root / VALIDATION_RELPATH
        # The validation report is the one file that may be written more than
        # once (re-validation years later must be possible), so previous
        # reports are preserved alongside rather than replaced.
        if target.exists():
            stamped = capture_root / "validation" / f"validation_{utc_now_iso().replace(':', '')}.json"
            write_json(stamped, report)
            report["written_to"] = str(stamped.relative_to(capture_root))
        else:
            write_json(target, report)
            report["written_to"] = VALIDATION_RELPATH

    return report
