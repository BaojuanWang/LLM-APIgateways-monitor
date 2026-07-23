"""Manifest generation, determinism, and verification tests."""

from __future__ import annotations

import json
import shutil
import zipfile

import pytest

from archivelib.canonical import sha256_file
from archivelib.errors import ManifestError
from archivelib.manifest import (
    MANIFEST_RELPATH,
    SHASUMS_RELPATH,
    build_entries,
    capture_directory_digest,
    classify_role,
    classify_sensitivity,
    generate_manifest,
    is_excluded,
    load_manifest,
    verify_manifest,
)
from archivelib.paths import create_capture_dir


def _populate(capture_dir, *, wacz_body: bytes | None = None) -> None:
    """Write a plausible capture tree: WACZ, logs, indexes, rendered output."""
    collection = capture_dir / "raw" / "browsertrix" / "collections" / "c1"
    (collection / "archive").mkdir(parents=True)
    (collection / "indexes").mkdir(parents=True)
    (collection / "logs").mkdir(parents=True)
    (collection / "pages").mkdir(parents=True)

    wacz = collection / "c1.wacz"
    if wacz_body is None:
        with zipfile.ZipFile(wacz, "w") as archive:
            archive.writestr("datapackage.json", json.dumps({"resources": []}))
            archive.writestr("archive/data.warc.gz", b"\x1f\x8b synthetic warc payload")
            archive.writestr("pages/pages.jsonl", '{"url":"http://127.0.0.1/"}\n')
    else:
        wacz.write_bytes(wacz_body)

    (collection / "archive" / "data.warc.gz").write_bytes(b"\x1f\x8b synthetic")
    (collection / "indexes" / "index.cdxj").write_text("com,example)/ 20260101 {}\n", encoding="utf-8")
    (collection / "logs" / "crawl.log").write_text('{"logLevel":"info"}\n', encoding="utf-8")
    (collection / "pages" / "pages.jsonl").write_text('{"url":"http://127.0.0.1/"}\n', encoding="utf-8")

    rendered = capture_dir / "raw" / "rendered"
    (rendered / "final_dom.html").write_text("<html><body>fixture</body></html>", encoding="utf-8")
    (rendered / "network_summary.jsonl").write_text('{"url":"http://127.0.0.1/"}\n', encoding="utf-8")
    (rendered / "browser_state_names.json").write_text('{"cookie_names":[]}', encoding="utf-8")
    (rendered / "screenshots" / "viewport.png").write_bytes(b"\x89PNG\r\n\x1a\n synthetic")

    (capture_dir / "config" / "seeds.txt").write_text("http://127.0.0.1/\n", encoding="utf-8")
    (capture_dir / "config" / "environment.json").write_text('{"os":"synthetic"}', encoding="utf-8")
    (capture_dir / "capture.json").write_text('{"capture_id":"cid"}', encoding="utf-8")


@pytest.fixture
def capture_dir(archive_root):
    target = create_capture_dir(archive_root, "svc_00000000", "20260101T000000Z_svc_00000000_abcdef123456")
    _populate(target)
    return target


# --- classification ---------------------------------------------------------


@pytest.mark.parametrize(
    "relpath,role",
    [
        ("raw/browsertrix/collections/c1/c1.wacz", "wacz"),
        ("raw/browsertrix/collections/c1/archive/data.warc.gz", "warc"),
        ("raw/browsertrix/collections/c1/indexes/index.cdxj", "cdx_index"),
        ("raw/browsertrix/collections/c1/logs/crawl.log", "crawl_log"),
        ("raw/browsertrix/collections/c1/pages/pages.jsonl", "pages_jsonl"),
        ("raw/rendered/final_dom.html", "rendered_dom"),
        ("raw/rendered/singlefile.html", "singlefile"),
        ("raw/rendered/screenshots/viewport.png", "screenshot"),
        ("raw/rendered/network_summary.jsonl", "network_summary"),
        ("raw/rendered/browser_state_names.json", "browser_state_names"),
        ("config/seeds.txt", "seeds"),
        ("capture.json", "capture_metadata"),
        ("something/unexpected.bin", "other"),
    ],
)
def test_role_classification(relpath, role):
    assert classify_role(relpath) == role


def test_unknown_files_are_treated_as_sensitive():
    """Fail safe: anything unrecognized is assumed to contain raw material."""
    assert classify_sensitivity(classify_role("mystery.bin")) == "raw_sensitive"


def test_raw_artifacts_are_never_public_safe():
    for role in ("wacz", "warc", "rendered_dom", "singlefile", "screenshot", "crawl_log"):
        assert classify_sensitivity(role) == "raw_sensitive"


# --- generation -------------------------------------------------------------


def test_manifest_covers_every_file(capture_dir):
    manifest = generate_manifest(capture_dir, capture_id="cid", service_id="svc_00000000")
    listed = {entry["path"] for entry in manifest["files"]}
    on_disk = {
        str(p.relative_to(capture_dir))
        for p in capture_dir.rglob("*")
        if p.is_file() and not is_excluded(str(p.relative_to(capture_dir)))
    }
    assert listed == on_disk
    assert manifest["file_count"] == len(on_disk)


def test_manifest_entries_carry_required_fields(capture_dir):
    manifest = generate_manifest(capture_dir, capture_id="cid", service_id="svc_00000000")
    for entry in manifest["files"]:
        assert set(entry) >= {"path", "size_bytes", "sha256", "role", "sensitivity", "created_at_utc"}
        assert len(entry["sha256"]) == 64


def test_hashes_match_the_actual_files(capture_dir):
    manifest = generate_manifest(capture_dir, capture_id="cid", service_id="svc_00000000")
    for entry in manifest["files"]:
        assert entry["sha256"] == sha256_file(capture_dir / entry["path"])


def test_shasums_file_is_written(capture_dir):
    generate_manifest(capture_dir, capture_id="cid", service_id="svc_00000000")
    lines = (capture_dir / SHASUMS_RELPATH).read_text(encoding="utf-8").strip().splitlines()
    assert lines and all("  " in line for line in lines)


def test_manifest_is_append_only(capture_dir):
    generate_manifest(capture_dir, capture_id="cid", service_id="svc_00000000")
    with pytest.raises(ManifestError, match="append-only"):
        generate_manifest(capture_dir, capture_id="cid", service_id="svc_00000000")


def test_empty_capture_is_rejected(archive_root):
    empty = create_capture_dir(archive_root, "svc_11111111", "20260101T000000Z_svc_11111111_abcdef123456")
    with pytest.raises(ManifestError, match="no files"):
        generate_manifest(empty, capture_id="cid", service_id="svc_11111111")


# --- determinism ------------------------------------------------------------


def test_directory_digest_is_deterministic(capture_dir):
    entries = build_entries(capture_dir)
    assert capture_directory_digest(entries) == capture_directory_digest(entries)
    assert capture_directory_digest(list(reversed(entries))) == capture_directory_digest(entries)


def test_directory_digest_survives_a_faithful_copy(capture_dir, tmp_path):
    """The migration guarantee: same bytes elsewhere -> same digest."""
    original = capture_directory_digest(build_entries(capture_dir))
    copy = tmp_path / "migrated"
    shutil.copytree(capture_dir, copy)
    assert capture_directory_digest(build_entries(copy)) == original


def test_directory_digest_changes_when_content_changes(capture_dir):
    before = capture_directory_digest(build_entries(capture_dir))
    (capture_dir / "raw" / "rendered" / "final_dom.html").write_text("<html>changed</html>", encoding="utf-8")
    assert capture_directory_digest(build_entries(capture_dir)) != before


# --- verification -----------------------------------------------------------


def test_verify_clean_capture(capture_dir):
    generate_manifest(capture_dir, capture_id="cid", service_id="svc_00000000")
    report = verify_manifest(capture_dir)
    assert report["ok"]
    assert report["digest_matches"]
    assert not report["missing_files"] and not report["added_files"] and not report["hash_mismatches"]


def test_verify_detects_modified_bytes(capture_dir):
    generate_manifest(capture_dir, capture_id="cid", service_id="svc_00000000")
    (capture_dir / "raw" / "rendered" / "final_dom.html").write_text("<html>tampered</html>", encoding="utf-8")
    report = verify_manifest(capture_dir)
    assert not report["ok"]
    assert any(m["path"] == "raw/rendered/final_dom.html" for m in report["hash_mismatches"])


def test_verify_detects_deleted_file(capture_dir):
    generate_manifest(capture_dir, capture_id="cid", service_id="svc_00000000")
    (capture_dir / "raw" / "rendered" / "final_dom.html").unlink()
    report = verify_manifest(capture_dir)
    assert not report["ok"]
    assert "raw/rendered/final_dom.html" in report["missing_files"]


def test_verify_detects_file_added_after_manifest(capture_dir):
    generate_manifest(capture_dir, capture_id="cid", service_id="svc_00000000")
    (capture_dir / "raw" / "rendered" / "sneaked_in.html").write_text("<html>later</html>", encoding="utf-8")
    report = verify_manifest(capture_dir)
    assert not report["ok"]
    assert "raw/rendered/sneaked_in.html" in report["added_files"]


def test_verify_detects_a_rewritten_manifest(capture_dir):
    """Editing the manifest to match tampered bytes still breaks the digest."""
    generate_manifest(capture_dir, capture_id="cid", service_id="svc_00000000")
    target = capture_dir / "raw" / "rendered" / "final_dom.html"
    target.write_text("<html>tampered</html>", encoding="utf-8")

    manifest = load_manifest(capture_dir)
    for entry in manifest["files"]:
        if entry["path"] == "raw/rendered/final_dom.html":
            entry["sha256"] = sha256_file(target)
            entry["size_bytes"] = target.stat().st_size
    (capture_dir / MANIFEST_RELPATH).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    report = verify_manifest(capture_dir)
    assert not report["hash_mismatches"], "per-file hashes were made consistent"
    assert not report["digest_matches"], "but the directory digest must expose the edit"
    assert not report["ok"]


def test_verify_detects_symlink_escape(capture_dir, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("not part of the capture", encoding="utf-8")
    generate_manifest(capture_dir, capture_id="cid", service_id="svc_00000000")
    (capture_dir / "raw" / "rendered" / "escape.txt").symlink_to(outside)
    report = verify_manifest(capture_dir)
    assert report["symlink_escapes"]
    assert not report["ok"]


def test_manifest_generation_refuses_escaping_symlink(archive_root, tmp_path):
    capture = create_capture_dir(archive_root, "svc_22222222", "20260101T000000Z_svc_22222222_abcdef123456")
    _populate(capture)
    outside = tmp_path / "outside.txt"
    outside.write_text("elsewhere", encoding="utf-8")
    (capture / "raw" / "escape.txt").symlink_to(outside)
    with pytest.raises(ManifestError, match="symlink"):
        generate_manifest(capture, capture_id="cid", service_id="svc_22222222")
