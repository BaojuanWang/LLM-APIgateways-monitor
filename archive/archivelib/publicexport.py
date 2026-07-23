"""Public export: sanitized metadata for ``data/archive_public/``.

This is the only code path that writes anything from the corpus into the Git
repository, and it is built as an **allowlist**. Each output row is assembled
field by field from named sources; no dict from the corpus is ever copied
wholesale into a public file. Adding a field to the public index therefore
requires editing this module on purpose — it cannot happen by accident when a
new key appears in ``capture.json``.

What is deliberately excluded: WACZ/WARC bytes, HTML, response bodies, headers,
cookies and Set-Cookie, browser storage values, Authorization values, API keys,
raw redirect query strings, SingleFile HTML, screenshots, absolute filesystem
paths, and unsanitized Browsertrix logs.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .canonical import read_json
from .envmeta import utc_now_iso
from .sanitize import normalize_local_path, redact_url, scan_public_export

PUBLIC_DIR = "data/archive_public"
CAPTURES_CSV = "captures.csv"
TOMBSTONES_CSV = "tombstones.csv"
MANIFESTS_DIR = "manifests"

CAPTURE_COLUMNS = (
    "service_id",
    "domain",
    "capture_id",
    "capture_started_utc",
    "capture_ended_utc",
    "capture_reason",
    "status",
    "site_condition",
    "seed_count",
    "page_count",
    "wacz_bytes",
    "wacz_sha256",
    "capture_directory_digest",
    "browsertrix_version",
    "browsertrix_image_digest",
    "singlefile_version",
    "effective_config_hash",
    "storage_mode",
    "code_commit_sha",
    "source_monitor_timestamp",
    "source_monitor_status",
    "source_final_url",
    "source_page_title",
    "source_homepage_html_hash",
    "validation_status",
    "validation_errors",
    "tombstone_status",
    "corpus_relpath",
)

TOMBSTONE_COLUMNS = (
    "service_id",
    "domain",
    "recorded_at_utc",
    "prior_state",
    "new_state",
    "confidence",
    "is_provisional",
    "consecutive_observations",
    "span_hours",
    "last_live_observation_utc",
    "first_terminal_observation_utc",
    "last_terminal_observation_utc",
    "inconclusive_observation_count",
    "redirect_target_host",
    "evidence_source",
    "last_successful_capture_id",
    "last_successful_wacz_sha256",
    "final_capture_attempted",
    "final_capture_result",
    "notes",
)


def _clean(value) -> str:
    """Collapse a value to a single-line CSV-safe string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return normalize_local_path(text)


def capture_public_row(capture: dict, *, corpus_relpath: str, tombstone_status: str = "") -> dict:
    """Build one public index row from a capture.json, field by field."""
    validation = capture.get("validation", {}) or {}
    wacz = capture.get("wacz", {}) or {}
    tools = capture.get("tools", {}) or {}
    browsertrix = tools.get("browsertrix", {}) or {}
    singlefile = tools.get("singlefile", {}) or {}
    monitor = capture.get("prior_monitor_state", {}) or {}

    return {
        "service_id": _clean(capture.get("service_id")),
        "domain": _clean(capture.get("host")),
        "capture_id": _clean(capture.get("capture_id")),
        "capture_started_utc": _clean(capture.get("started_utc")),
        "capture_ended_utc": _clean(capture.get("ended_utc")),
        "capture_reason": _clean(capture.get("capture_reason")),
        "status": _clean(capture.get("status")),
        "site_condition": _clean(capture.get("site_condition")),
        "seed_count": _clean(capture.get("seed_count")),
        "page_count": _clean(capture.get("page_count")),
        "wacz_bytes": _clean(wacz.get("size_bytes")),
        "wacz_sha256": _clean(wacz.get("sha256")),
        "capture_directory_digest": _clean(capture.get("capture_directory_digest")),
        "browsertrix_version": _clean(browsertrix.get("tag")),
        "browsertrix_image_digest": _clean(browsertrix.get("digest")),
        "singlefile_version": _clean(singlefile.get("version")),
        "effective_config_hash": _clean(capture.get("effective_config_hash")),
        # The mode only — external_volume | explicitly_authorized_local. Never
        # the archive root path, which would carry the operator's username.
        "storage_mode": _clean(capture.get("storage_mode")),
        "code_commit_sha": _clean(capture.get("code_commit_sha")),
        "source_monitor_timestamp": _clean(monitor.get("timestamp")),
        "source_monitor_status": _clean(monitor.get("online_status")),
        # Query strings are dropped: gateway redirects routinely carry invite
        # and referral parameters.
        "source_final_url": _clean(redact_url(monitor.get("final_url", ""))),
        "source_page_title": _clean(monitor.get("page_title"))[:160],
        "source_homepage_html_hash": _clean(monitor.get("html_hash")),
        "validation_status": _clean(validation.get("status")),
        "validation_errors": _clean(";".join(validation.get("failed_checks", []) or [])),
        "tombstone_status": _clean(tombstone_status),
        "corpus_relpath": _clean(corpus_relpath),
    }


def tombstone_public_row(tombstone: dict) -> dict:
    evidence = tombstone.get("evidence", {}) or {}
    source = evidence.get("source", {}) or {}
    return {
        "service_id": _clean(tombstone.get("service_id")),
        "domain": _clean(tombstone.get("host")),
        "recorded_at_utc": _clean(tombstone.get("recorded_at_utc")),
        "prior_state": _clean(tombstone.get("prior_state")),
        "new_state": _clean(tombstone.get("new_state")),
        "confidence": _clean(tombstone.get("confidence")),
        "is_provisional": _clean(tombstone.get("is_provisional")),
        "consecutive_observations": _clean(evidence.get("consecutive_observations")),
        "span_hours": _clean(evidence.get("span_hours")),
        "last_live_observation_utc": _clean(evidence.get("last_live_observation_utc")),
        "first_terminal_observation_utc": _clean(evidence.get("first_terminal_observation_utc")),
        "last_terminal_observation_utc": _clean(evidence.get("last_terminal_observation_utc")),
        "inconclusive_observation_count": _clean(evidence.get("inconclusive_observation_count")),
        "redirect_target_host": _clean(evidence.get("redirect_target_host")),
        "evidence_source": _clean(source.get("file")),
        "last_successful_capture_id": _clean(tombstone.get("last_successful_capture_id")),
        "last_successful_wacz_sha256": _clean(tombstone.get("last_successful_wacz_sha256")),
        "final_capture_attempted": _clean(tombstone.get("final_capture_attempted")),
        "final_capture_result": _clean(tombstone.get("final_capture_result")),
        "notes": _clean("; ".join(tombstone.get("notes", []) or []))[:500],
    }


def public_manifest_summary(manifest: dict, capture: dict) -> dict:
    """Per-capture manifest summary safe to publish.

    Counts and hashes only — never file contents, and never a path outside the
    corpus-relative namespace.
    """
    by_role: dict[str, dict] = {}
    for entry in manifest.get("files", []):
        role = entry.get("role", "other")
        bucket = by_role.setdefault(role, {"count": 0, "bytes": 0})
        bucket["count"] += 1
        bucket["bytes"] += int(entry.get("size_bytes", 0) or 0)

    wacz_entries = [e for e in manifest.get("files", []) if e.get("role") == "wacz"]
    return {
        "schema": "public_capture_manifest_summary",
        "generated_at_utc": utc_now_iso(),
        "capture_id": manifest.get("capture_id"),
        "service_id": manifest.get("service_id"),
        "domain": capture.get("host"),
        "capture_started_utc": capture.get("started_utc"),
        "algorithm": manifest.get("algorithm", "sha256"),
        "file_count": manifest.get("file_count"),
        "total_bytes": manifest.get("total_bytes"),
        "capture_directory_digest": manifest.get("capture_directory_digest"),
        "files_by_role": {k: by_role[k] for k in sorted(by_role)},
        "wacz": [
            {
                "relative_path": e.get("path"),
                "size_bytes": e.get("size_bytes"),
                "sha256": e.get("sha256"),
            }
            for e in wacz_entries
        ],
        "note": (
            "Raw artifacts are NOT in this repository. Paths are relative to the "
            "capture directory inside the external corpus."
        ),
    }


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


def _read_digest(capture_dir: Path) -> str:
    path = capture_dir / "manifests" / "sha256_manifest.json"
    if not path.exists():
        return ""
    try:
        return str(read_json(path).get("capture_directory_digest", "") or "")
    except Exception:
        return ""


def _read_validation(capture_dir: Path) -> dict:
    """Most recent validation report for a capture.

    Re-validation writes timestamped siblings rather than replacing the
    original, so the latest verdict is the last one by name.
    """
    validation_dir = capture_dir / "validation"
    if not validation_dir.is_dir():
        return {}
    reports = sorted(validation_dir.glob("validation*.json"))
    if not reports:
        return {}
    try:
        return read_json(reports[-1])
    except Exception:
        return {}


def collect_corpus(root) -> tuple[list[tuple[Path, dict]], list[tuple[Path, dict]]]:
    """Walk the corpus and return (captures, tombstones) as (path, json) pairs."""
    captures: list[tuple[Path, dict]] = []
    tombstones: list[tuple[Path, dict]] = []
    corpus = root.corpus_dir
    if not corpus.is_dir():
        return captures, tombstones
    for service_dir in sorted(p for p in corpus.iterdir() if p.is_dir()):
        capture_root = service_dir / "captures"
        if capture_root.is_dir():
            for capture_dir in sorted(p for p in capture_root.iterdir() if p.is_dir()):
                meta = capture_dir / "capture.json"
                if not meta.exists():
                    continue
                try:
                    captures.append((capture_dir, read_json(meta)))
                except Exception:
                    continue
        tomb_dir = service_dir / "tombstones"
        if tomb_dir.is_dir():
            for tomb in sorted(tomb_dir.glob("*.json")):
                try:
                    tombstones.append((tomb, read_json(tomb)))
                except Exception:
                    continue
    return captures, tombstones


def build_public_export(*, root, repo: Path, write: bool = True) -> dict:
    """Rebuild ``data/archive_public/`` from the local corpus.

    Idempotent: the CSVs are regenerated in full from the corpus, so the
    repository is always a pure function of the (append-only) corpus.
    """
    repo = Path(repo)
    public_dir = repo / PUBLIC_DIR

    captures, tombstones = collect_corpus(root)

    tombstone_states: dict[str, str] = {}
    for _, tomb in tombstones:
        sid = tomb.get("service_id", "")
        if sid:
            tombstone_states[sid] = f"{tomb.get('new_state', '')}:{tomb.get('confidence', '')}"

    capture_rows: list[dict] = []
    manifest_summaries: list[tuple[str, dict]] = []
    for capture_dir, capture in captures:
        try:
            relpath = str(capture_dir.resolve().relative_to(root.path.resolve()))
        except ValueError:
            continue
        # The digest and validation verdict live in files written after (and
        # therefore outside) capture.json. Read them from their own artifacts
        # rather than trusting a copy — capture.json is hashed and never edited.
        capture = dict(capture)
        capture.setdefault("capture_directory_digest", _read_digest(capture_dir))
        capture.setdefault("validation", _read_validation(capture_dir))
        row = capture_public_row(
            capture,
            corpus_relpath=relpath,
            tombstone_status=tombstone_states.get(capture.get("service_id", ""), ""),
        )
        capture_rows.append(row)

        manifest_path = capture_dir / "manifests" / "sha256_manifest.json"
        if manifest_path.exists():
            try:
                manifest_summaries.append(
                    (str(capture.get("capture_id", "")), public_manifest_summary(read_json(manifest_path), capture))
                )
            except Exception:
                pass

    capture_rows.sort(key=lambda r: (r.get("capture_started_utc", ""), r.get("service_id", "")))
    tombstone_rows = sorted(
        (tombstone_public_row(t) for _, t in tombstones),
        key=lambda r: (r.get("recorded_at_utc", ""), r.get("service_id", "")),
    )

    if write:
        _write_csv(public_dir / CAPTURES_CSV, CAPTURE_COLUMNS, capture_rows)
        _write_csv(public_dir / TOMBSTONES_CSV, TOMBSTONE_COLUMNS, tombstone_rows)
        manifests_dir = public_dir / MANIFESTS_DIR
        manifests_dir.mkdir(parents=True, exist_ok=True)
        from .canonical import write_json

        for capture_id, summary in manifest_summaries:
            if capture_id:
                write_json(manifests_dir / f"{capture_id}.json", summary)

    scan = scan_public_export(public_dir)

    return {
        "generated_at_utc": utc_now_iso(),
        "public_dir": PUBLIC_DIR,
        "capture_rows": len(capture_rows),
        "tombstone_rows": len(tombstone_rows),
        "manifest_summaries": len(manifest_summaries),
        "written": write,
        "secret_scan": scan,
        "ok": scan.get("ok", False),
    }
