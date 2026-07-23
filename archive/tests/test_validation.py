"""Validator tests, including the corrupt-WACZ detection path."""

from __future__ import annotations

import json
import zipfile

import pytest

from archivelib.manifest import generate_manifest
from archivelib.paths import create_capture_dir
from archivelib.schemaval import validate_document
from archivelib.validate import validate_capture


def _check(report, name):
    return next(c for c in report["checks"] if c["name"] == name)


def _build(capture_dir, *, wacz_body: bytes | None = None, with_logs: bool = True, with_manifest: bool = True):
    collection = capture_dir / "raw" / "browsertrix" / "collections" / "c1"
    for sub in ("archive", "indexes", "pages", "logs"):
        (collection / sub).mkdir(parents=True, exist_ok=True)

    wacz = collection / "c1.wacz"
    if wacz_body is None:
        with zipfile.ZipFile(wacz, "w") as archive:
            archive.writestr("datapackage.json", json.dumps({"resources": []}))
            archive.writestr("archive/data.warc.gz", b"synthetic warc payload")
            archive.writestr("pages/pages.jsonl", '{"url":"http://127.0.0.1/"}\n')
    else:
        wacz.write_bytes(wacz_body)

    (collection / "archive" / "data.warc.gz").write_bytes(b"synthetic")
    (collection / "indexes" / "index.cdxj").write_text("entry\n", encoding="utf-8")
    (collection / "pages" / "pages.jsonl").write_text("{}\n", encoding="utf-8")
    if with_logs:
        (collection / "logs" / "crawl.log").write_text('{"logLevel":"info"}\n', encoding="utf-8")

    (capture_dir / "capture.json").write_text(
        json.dumps(
            {
                "capture_id": "20260101T000000Z_svc_1a2b3c4d_abcdef123456",
                "service_id": "svc_1a2b3c4d",
                "started_utc": "2026-01-01T00:00:00Z",
                "capture_reason": "smoke_test",
                "effective_config_hash": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    (capture_dir / "config" / "seeds.txt").write_text("http://127.0.0.1/\n", encoding="utf-8")
    if with_manifest:
        generate_manifest(capture_dir, capture_id="cid", service_id="svc_1a2b3c4d")


@pytest.fixture
def good_capture(archive_root):
    capture = create_capture_dir(archive_root, "svc_1a2b3c4d", "20260101T000000Z_svc_1a2b3c4d_abcdef123456")
    _build(capture)
    return capture


def test_valid_capture_passes(good_capture):
    report = validate_capture(good_capture, write_report=False)
    assert report["status"] in ("valid", "valid_with_warnings"), report["failed_checks"]
    assert report["error_count"] == 0


def test_missing_wacz_is_detected(archive_root):
    capture = create_capture_dir(archive_root, "svc_2a2b3c4d", "20260101T000000Z_svc_2a2b3c4d_abcdef123456")
    (capture / "capture.json").write_text(
        json.dumps(
            {
                "capture_id": "cid",
                "service_id": "svc_2a2b3c4d",
                "started_utc": "2026-01-01T00:00:00Z",
                "capture_reason": "smoke_test",
                "effective_config_hash": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    generate_manifest(capture, capture_id="cid", service_id="svc_2a2b3c4d")
    report = validate_capture(capture, write_report=False)
    assert report["status"] == "invalid"
    assert "wacz_present" in report["failed_checks"]


def test_corrupt_wacz_container_is_detected(archive_root):
    """A file named .wacz that is not a readable ZIP must not pass."""
    capture = create_capture_dir(archive_root, "svc_3a2b3c4d", "20260101T000000Z_svc_3a2b3c4d_abcdef123456")
    _build(capture, wacz_body=b"this is not a zip file at all")
    report = validate_capture(capture, write_report=False)
    assert report["status"] == "invalid"
    assert "wacz_container_valid" in report["failed_checks"]
    assert "not a valid ZIP" in _check(report, "wacz_container_valid")["detail"]


def test_truncated_wacz_is_detected(archive_root, tmp_path):
    """The realistic corruption: a crawl killed mid-write."""
    intact = tmp_path / "intact.wacz"
    with zipfile.ZipFile(intact, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("datapackage.json", json.dumps({"resources": []}))
        archive.writestr("archive/data.warc.gz", b"x" * 5000)
    truncated = intact.read_bytes()[: len(intact.read_bytes()) // 2]

    capture = create_capture_dir(archive_root, "svc_4a2b3c4d", "20260101T000000Z_svc_4a2b3c4d_abcdef123456")
    _build(capture, wacz_body=truncated)
    report = validate_capture(capture, write_report=False)
    assert report["status"] == "invalid"
    assert "wacz_container_valid" in report["failed_checks"]


def test_wacz_without_warc_payload_is_detected(archive_root, tmp_path):
    empty = tmp_path / "empty.wacz"
    with zipfile.ZipFile(empty, "w") as archive:
        archive.writestr("datapackage.json", json.dumps({"resources": []}))
    capture = create_capture_dir(archive_root, "svc_5a2b3c4d", "20260101T000000Z_svc_5a2b3c4d_abcdef123456")
    _build(capture, wacz_body=empty.read_bytes())
    report = validate_capture(capture, write_report=False)
    assert "wacz_container_valid" in report["failed_checks"]
    assert _check(report, "wacz_container_valid")["data"]["has_warc_payload"] is False


def test_missing_browsertrix_logs_are_detected(archive_root):
    capture = create_capture_dir(archive_root, "svc_6a2b3c4d", "20260101T000000Z_svc_6a2b3c4d_abcdef123456")
    _build(capture, with_logs=False)
    report = validate_capture(capture, write_report=False)
    assert "browsertrix_logs_present" in report["failed_checks"]


def test_missing_manifest_is_detected(archive_root):
    capture = create_capture_dir(archive_root, "svc_7a2b3c4d", "20260101T000000Z_svc_7a2b3c4d_abcdef123456")
    _build(capture, with_manifest=False)
    report = validate_capture(capture, write_report=False)
    assert "manifest_present" in report["failed_checks"]


def test_post_manifest_file_addition_is_detected(good_capture):
    (good_capture / "raw" / "rendered" / "added_later.txt").write_text("late", encoding="utf-8")
    report = validate_capture(good_capture, write_report=False)
    assert "no_files_added_after_manifest" in report["failed_checks"]


def test_hash_mismatch_is_detected(good_capture):
    (good_capture / "config" / "seeds.txt").write_text("http://127.0.0.1/changed\n", encoding="utf-8")
    report = validate_capture(good_capture, write_report=False)
    assert "manifest_hashes_match" in report["failed_checks"]


def test_symlink_escape_is_detected(good_capture, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("elsewhere", encoding="utf-8")
    (good_capture / "raw" / "escape.txt").symlink_to(outside)
    report = validate_capture(good_capture, write_report=False)
    assert "no_symlink_escape" in report["failed_checks"]


def test_absolute_path_leakage_is_detected(archive_root):
    capture = create_capture_dir(archive_root, "svc_8a2b3c4d", "20260101T000000Z_svc_8a2b3c4d_abcdef123456")
    _build(capture, with_manifest=False)
    (capture / "config" / "environment.json").write_text(
        json.dumps({"corpus": "/Users/someone/LLM-APIgateways-corpus"}), encoding="utf-8"
    )
    generate_manifest(capture, capture_id="cid", service_id="svc_8a2b3c4d")
    report = validate_capture(capture, write_report=False)
    assert "no_absolute_path_leakage" in report["failed_checks"]


def test_secretlike_content_in_metadata_is_detected(archive_root):
    capture = create_capture_dir(archive_root, "svc_9a2b3c4d", "20260101T000000Z_svc_9a2b3c4d_abcdef123456")
    _build(capture, with_manifest=False)
    (capture / "validation" / "browsertrix_exit.json").write_text(
        json.dumps({"stderr_tail": "Authorization: Bearer " + "q" * 40}), encoding="utf-8"
    )
    generate_manifest(capture, capture_id="cid", service_id="svc_9a2b3c4d")
    report = validate_capture(capture, write_report=False)
    assert "no_secretlike_content_in_public_facing_metadata" in report["failed_checks"]


def test_capture_inside_the_repo_is_detected(tmp_path, monkeypatch):
    """A capture directory inside the Git repo must fail, full stop."""
    from archivelib import validate as validate_mod

    fake_repo = tmp_path / "repo"
    capture = fake_repo / "archive" / "runtime" / "corpus" / "cap"
    capture.mkdir(parents=True)
    monkeypatch.setattr(validate_mod, "repo_root", lambda: fake_repo)
    check = validate_mod.check_not_in_repo(capture)
    assert not check.passed
    assert "INSIDE the Git repository" in check.detail


def test_validation_report_never_replaces_an_earlier_one(good_capture):
    first = validate_capture(good_capture, write_report=True)
    second = validate_capture(good_capture, write_report=True)
    assert first["written_to"] == "validation/validation.json"
    assert second["written_to"] != first["written_to"]
    assert (good_capture / "validation" / "validation.json").exists()
    assert len(list((good_capture / "validation").glob("validation*.json"))) == 2


# --- JSON Schema ------------------------------------------------------------


def test_capture_json_validates_against_its_schema():
    document = {
        "capture_id": "20260101T000000Z_svc-example_1a2b3c4d_abcdef123456",
        "service_id": "svc-example_1a2b3c4d",
        "host": "example.com",
        "started_utc": "2026-01-01T00:00:00Z",
        "capture_reason": "manual",
        "status": "completed",
        "site_condition": "ok",
        "effective_config_hash": "a" * 64,
        "seed_count": 3,
        "wacz": {"relative_path": "raw/x.wacz", "size_bytes": 10, "sha256": "b" * 64},
    }
    report = validate_document(document, "capture")
    assert report["valid"] is not False, report["errors"]


def test_public_index_schema_forbids_extra_fields():
    row = {
        "service_id": "svc_1a2b3c4d",
        "domain": "example.com",
        "capture_id": "cid",
        "capture_started_utc": "2026-01-01T00:00:00Z",
        "capture_reason": "manual",
        "status": "completed",
        "validation_status": "valid",
        "corpus_relpath": "corpus/svc/captures/cid",
        "raw_html": "<html>leak</html>",
    }
    report = validate_document(row, "public_capture_index")
    assert report["valid"] is False, "additionalProperties must be false"


def test_public_index_schema_rejects_absolute_relpath():
    row = {
        "service_id": "svc_1a2b3c4d",
        "domain": "example.com",
        "capture_id": "cid",
        "capture_started_utc": "2026-01-01T00:00:00Z",
        "capture_reason": "manual",
        "status": "completed",
        "validation_status": "valid",
        "corpus_relpath": "/Volumes/Disk/corpus/svc/captures/cid",
    }
    assert validate_document(row, "public_capture_index")["valid"] is False


# --- browser profile retention ----------------------------------------------


def test_retained_browser_profile_is_detected(archive_root):
    """Browsertrix leaves a Chrome user-data dir behind; a sealed capture must
    not contain one. All archived site content lives in the WARC."""
    capture = create_capture_dir(archive_root, "svc_ba2b3c4d", "20260101T000000Z_svc_ba2b3c4d_abcdef123456")
    _build(capture, with_manifest=False)
    profile = capture / "raw" / "browsertrix" / "collections" / "c1" / "profile" / "Default"
    profile.mkdir(parents=True)
    (profile / "Cookies").write_bytes(b"SQLite format 3\x00")
    (profile / "History").write_bytes(b"SQLite format 3\x00")
    generate_manifest(capture, capture_id="cid", service_id="svc_ba2b3c4d")
    report = validate_capture(capture, write_report=False)
    assert "no_browser_profile_retained" in report["failed_checks"]


def test_clean_capture_has_no_browser_profile(good_capture):
    report = validate_capture(good_capture, write_report=False)
    assert "no_browser_profile_retained" not in report["failed_checks"]
