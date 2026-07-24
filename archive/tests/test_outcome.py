"""Capture outcome / artifact policy: tombstone validity is not inferred from a
missing WACZ, only from positive evidence of a genuine unreachable host."""

from __future__ import annotations

import json
import zipfile

import pytest

from archivelib.manifest import generate_manifest
from archivelib.outcome import (
    OUTCOME_ARCHIVED,
    OUTCOME_INCOMPLETE,
    OUTCOME_RETRYABLE,
    OUTCOME_UNREACHABLE,
    classify_outcome,
)
from archivelib.paths import create_capture_dir
from archivelib.validate import validate_capture

_CID = "20260101T000000Z_svc_1a2b3c4d_abcdef123456"


def _base_capture_json(**over):
    d = {
        "capture_id": _CID,
        "service_id": "svc_1a2b3c4d",
        "host": "x.test",
        "started_utc": "2026-01-01T00:00:00Z",
        "ended_utc": "2026-01-01T00:01:00Z",
        "capture_reason": "tombstone_evidence",
        "effective_config_hash": "a" * 64,
        "site_condition": "unavailable",
        "seeds": [{"url": "https://x.test/", "page_type": "homepage", "origin": "canonical", "present": False, "http_status": None}],
        "seed_discovery": {"homepage_reachable": False, "probing_skipped": True, "probing_skipped_reason": "dns_failure"},
        "rendered": {"pages": []},
    }
    d.update(over)
    return d


def _build_capture(capture_dir, *, wacz: bool, capture_json: dict | None,
                   network_summary: bool = True, browsertrix_exit: bool = True,
                   environment: bool = True, logs: bool = True, manifest: bool = True):
    collection = capture_dir / "raw" / "browsertrix" / "collections" / "c1"
    (collection / "logs").mkdir(parents=True, exist_ok=True)
    if logs:
        (collection / "logs" / "crawl.log").write_text('{"logLevel":"info"}\n', encoding="utf-8")
    if wacz:
        (collection / "archive").mkdir(parents=True, exist_ok=True)
        (collection / "indexes").mkdir(parents=True, exist_ok=True)
        (collection / "pages").mkdir(parents=True, exist_ok=True)
        w = collection / "c1.wacz"
        with zipfile.ZipFile(w, "w") as z:
            z.writestr("datapackage.json", json.dumps({"resources": []}))
            z.writestr("archive/data.warc.gz", b"payload")
        (collection / "archive" / "data.warc.gz").write_bytes(b"payload")
        (collection / "indexes" / "index.cdxj").write_text("e\n", encoding="utf-8")
        (collection / "pages" / "pages.jsonl").write_text("{}\n", encoding="utf-8")

    rendered = capture_dir / "raw" / "rendered"
    rendered.mkdir(parents=True, exist_ok=True)
    if network_summary:
        (rendered / "network_summary.jsonl").write_text(
            '{"timestamp_utc":"2026-01-01T00:00:30Z","url":"https://x.test/","failure_category":"dns"}\n',
            encoding="utf-8",
        )
    if browsertrix_exit:
        (capture_dir / "validation" / "browsertrix_exit.json").write_text(
            json.dumps({"exit_code": 1, "wacz_present": False}), encoding="utf-8"
        )
    (capture_dir / "config" / "seeds.txt").write_text("https://x.test/\n", encoding="utf-8")
    if environment:
        (capture_dir / "config" / "environment.json").write_text('{"os":"synthetic"}', encoding="utf-8")
    if capture_json is not None:
        (capture_dir / "capture.json").write_text(json.dumps(capture_json), encoding="utf-8")
    if manifest and capture_json is not None:
        generate_manifest(capture_dir, capture_id="cid", service_id="svc_1a2b3c4d")


def _mk(archive_root, sid, cid, **kw):
    cap = create_capture_dir(archive_root, sid, cid)
    _build_capture(cap, **kw)
    return cap


# --- classify_outcome -------------------------------------------------------


def test_wacz_present_is_archived(archive_root):
    cap = _mk(archive_root, "svc_1a2b3c4d", _CID, wacz=True, capture_json=_base_capture_json(site_condition="ok"))
    o = classify_outcome(cap)
    assert o.outcome == OUTCOME_ARCHIVED and o.wacz_required is True


@pytest.mark.parametrize("reason", ["dns_failure", "connection_refused", "network_unreachable", "tls_failure"])
def test_definitive_unreachable_with_complete_evidence_is_documented(archive_root, reason):
    cj = _base_capture_json(seed_discovery={"homepage_reachable": False, "probing_skipped": True, "probing_skipped_reason": reason})
    cap = _mk(archive_root, "svc_1a2b3c4d", _CID, wacz=False, capture_json=cj)
    o = classify_outcome(cap)
    assert o.outcome == OUTCOME_UNREACHABLE
    assert o.wacz_required is False
    assert o.network_failure == reason
    assert o.evidence_complete is True


@pytest.mark.parametrize("reason", ["connection_timeout", "read_timeout_no_response", "connection_error", None])
def test_indeterminate_no_wacz_is_retryable(archive_root, reason):
    cj = _base_capture_json(seed_discovery={"homepage_reachable": False, "probing_skipped": bool(reason), "probing_skipped_reason": reason})
    cap = _mk(archive_root, "svc_1a2b3c4d", _CID, wacz=False, capture_json=cj)
    o = classify_outcome(cap)
    assert o.outcome == OUTCOME_RETRYABLE
    assert o.wacz_required is True
    assert o.reachability == "indeterminate"


def test_reachable_no_wacz_is_retryable(archive_root):
    """An HTTP response was seen but no WACZ produced -> must retry, not pass."""
    cj = _base_capture_json(
        site_condition="ok",
        seeds=[{"url": "https://x.test/", "page_type": "homepage", "origin": "canonical", "present": True, "http_status": 200}],
        seed_discovery={"homepage_reachable": True, "probing_skipped": False, "probing_skipped_reason": ""},
    )
    cap = _mk(archive_root, "svc_1a2b3c4d", _CID, wacz=False, capture_json=cj)
    o = classify_outcome(cap)
    assert o.outcome == OUTCOME_RETRYABLE
    assert o.reachability == "reachable"


def test_blocked_challenge_no_wacz_is_retryable(archive_root):
    """A challenge page IS an HTTP response; it should have been captured."""
    cj = _base_capture_json(site_condition="blocked_or_challenge")
    cap = _mk(archive_root, "svc_1a2b3c4d", _CID, wacz=False, capture_json=cj)
    assert classify_outcome(cap).outcome == OUTCOME_RETRYABLE


def test_unreachable_but_missing_evidence_is_retryable(archive_root):
    """Definitive failure but an incomplete record cannot be trusted -> retry."""
    cj = _base_capture_json()  # dns_failure
    cap = _mk(archive_root, "svc_1a2b3c4d", _CID, wacz=False, capture_json=cj, network_summary=False)
    o = classify_outcome(cap)
    assert o.outcome == OUTCOME_RETRYABLE
    assert "network_summary.jsonl" in o.missing_evidence


def test_missing_capture_json_is_incomplete(archive_root):
    cap = _mk(archive_root, "svc_1a2b3c4d", _CID, wacz=False, capture_json=None)
    o = classify_outcome(cap)
    assert o.outcome == OUTCOME_INCOMPLETE
    assert "capture.json" in o.missing_evidence


def test_quarantine_marker_forces_incomplete(archive_root):
    cj = _base_capture_json(site_condition="ok")
    cap = _mk(archive_root, "svc_1a2b3c4d", _CID, wacz=True, capture_json=cj)
    (cap / "quarantine.json").write_text(json.dumps({"schema": "quarantine_marker"}), encoding="utf-8")
    assert classify_outcome(cap).outcome == OUTCOME_INCOMPLETE


# --- validate_capture integration ------------------------------------------


def test_documented_unreachable_validates_as_valid_without_wacz(archive_root):
    cj = _base_capture_json()  # dns_failure, complete
    cap = _mk(archive_root, "svc_1a2b3c4d", _CID, wacz=False, capture_json=cj)
    report = validate_capture(cap, write_report=False)
    assert report["status"].startswith("valid"), report["failed_checks"]
    assert report["outcome"]["outcome"] == OUTCOME_UNREACHABLE
    # the WACZ checks did not cause failure
    assert "wacz_present" not in report["failed_checks"]
    assert "wacz_container_valid" not in report["failed_checks"]


def test_retryable_no_wacz_validates_as_invalid(archive_root):
    cj = _base_capture_json(seed_discovery={"homepage_reachable": False, "probing_skipped": True, "probing_skipped_reason": "connection_timeout"})
    cap = _mk(archive_root, "svc_1a2b3c4d", _CID, wacz=False, capture_json=cj)
    report = validate_capture(cap, write_report=False)
    assert report["status"] == "invalid"
    assert report["outcome"]["outcome"] == OUTCOME_RETRYABLE
    assert "wacz_present" in report["failed_checks"]


def test_reachable_no_wacz_validates_as_invalid(archive_root):
    cj = _base_capture_json(
        site_condition="ok",
        seeds=[{"url": "https://x.test/", "page_type": "homepage", "origin": "canonical", "present": True, "http_status": 200}],
        seed_discovery={"homepage_reachable": True, "probing_skipped": False, "probing_skipped_reason": ""},
    )
    cap = _mk(archive_root, "svc_1a2b3c4d", _CID, wacz=False, capture_json=cj)
    report = validate_capture(cap, write_report=False)
    assert report["status"] == "invalid"
    assert "wacz_present" in report["failed_checks"]


def test_archived_capture_validates_as_valid(archive_root):
    cj = _base_capture_json(site_condition="ok")
    cap = _mk(archive_root, "svc_1a2b3c4d", _CID, wacz=True, capture_json=cj)
    report = validate_capture(cap, write_report=False)
    assert report["status"].startswith("valid")
    assert report["outcome"]["outcome"] == OUTCOME_ARCHIVED


def test_incomplete_validates_as_incomplete_status(archive_root):
    cap = _mk(archive_root, "svc_1a2b3c4d", _CID, wacz=False, capture_json=None)
    report = validate_capture(cap, write_report=False)
    assert report["status"] == "incomplete"
    assert report["outcome"]["outcome"] == OUTCOME_INCOMPLETE
    assert report["failed_checks"] == []  # not counted as a failure


def test_corrupt_wacz_still_invalid_even_though_unreachable_reason(archive_root):
    """A definitive-unreachable reason must NOT excuse a corrupt WACZ that exists."""
    cj = _base_capture_json()
    cap = _mk(archive_root, "svc_1a2b3c4d", _CID, wacz=False, capture_json=None, manifest=False)
    # write a corrupt wacz + a proper capture.json + manifest
    coll = cap / "raw" / "browsertrix" / "collections" / "c1"
    (coll / "c1.wacz").write_bytes(b"not a zip")
    (cap / "capture.json").write_text(json.dumps(cj), encoding="utf-8")
    generate_manifest(cap, capture_id="cid", service_id="svc_1a2b3c4d")
    report = validate_capture(cap, write_report=False)
    # WACZ present (non-empty) -> archived -> wacz_required -> corrupt = invalid
    assert report["status"] == "invalid"
    assert "wacz_container_valid" in report["failed_checks"]
