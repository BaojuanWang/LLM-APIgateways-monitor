"""Public-export sanitization tests.

The strings below that look like credentials are synthetic and exist only so the
detector has something to detect. They are what a real gateway page or header
would put in front of the crawler, and the point of these tests is that none of
it survives into ``data/archive_public/``.
"""

from __future__ import annotations

import pytest

from archivelib.publicexport import (
    CAPTURE_COLUMNS,
    capture_public_row,
    public_manifest_summary,
    tombstone_public_row,
)
from archivelib.sanitize import (
    FORBIDDEN_PUBLIC_EXTENSIONS,
    browser_state_names,
    classify_failure,
    normalize_local_path,
    redact_url,
    sanitized_network_record,
    scan_public_export,
    scan_text_for_secrets,
)

# Synthetic, non-functional credential-shaped strings used as detector input.
FAKE_BEARER = "Bearer " + "z" * 40
FAKE_SK_KEY = "sk-" + "0" * 32
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.c2lnbmF0dXJlX3BsYWNlaG9sZGVy"


# --- URL redaction ----------------------------------------------------------


def test_userinfo_is_stripped():
    assert "secret" not in redact_url("https://user:secret@example.com/path")
    assert redact_url("https://user:pw@example.com/p") == "https://example.com/p"


def test_query_values_are_dropped():
    out = redact_url("https://example.com/join?invite=ABC123&token=" + "x" * 30)
    assert "ABC123" not in out
    assert "x" * 30 not in out
    assert "REDACTED_QUERY" in out


def test_query_keys_can_be_kept_without_values():
    out = redact_url("https://example.com/p?invite=ABC123&ref=zzz", keep_query_keys=True)
    assert "invite" in out and "ref" in out
    assert "ABC123" not in out and "zzz" not in out


def test_fragment_is_redacted():
    assert "sensitive" not in redact_url("https://example.com/p#sensitive")


# --- local path normalization -----------------------------------------------


def test_username_is_removed_from_paths():
    assert normalize_local_path("/Users/someone/Documents/x") == "/Users/$USER/Documents/x"
    assert normalize_local_path("/home/someone/x") == "/home/$USER/x"


def test_volume_name_is_generalized():
    assert normalize_local_path("/Volumes/MyDisk/corpus/x") == "/Volumes/$ARCHIVE_VOLUME/corpus/x"


def test_archive_root_is_replaced_by_placeholder(tmp_path):
    out = normalize_local_path(f"{tmp_path}/corpus/a", root=tmp_path)
    assert str(tmp_path) not in out
    assert out.startswith("$ARCHIVE_ROOT")


# --- network summary --------------------------------------------------------


def test_network_record_contains_only_allowlisted_fields():
    record = sanitized_network_record(
        timestamp_utc="2026-01-01T00:00:00Z",
        url="https://example.com/api?key=" + "s" * 30,
        method="get",
        resource_type="xhr",
        status=200,
        mime_type="application/json; charset=utf-8",
        timing_ms=12.3456,
        response_bytes=99,
    )
    assert set(record) == {
        "timestamp_utc", "url", "method", "resource_type", "status",
        "mime_type", "redirected_from", "redirected_to", "timing_ms",
        "response_bytes", "failure_category",
    }
    assert "s" * 30 not in record["url"]
    assert record["method"] == "GET"
    assert record["mime_type"] == "application/json"


def test_network_record_has_no_header_or_body_field():
    record = sanitized_network_record(timestamp_utc="t", url="https://x.test/")
    for forbidden in ("headers", "request_headers", "response_headers", "body", "cookies", "authorization"):
        assert forbidden not in record


@pytest.mark.parametrize(
    "error,expected",
    [
        ("net::ERR_NAME_NOT_RESOLVED", "dns"),
        ("net::ERR_CONNECTION_REFUSED", "connection"),
        ("net::ERR_CERT_AUTHORITY_INVALID", "tls"),
        ("net::ERR_TIMED_OUT", "timeout"),
        ("net::ERR_ABORTED", "aborted"),
        ("net::ERR_BLOCKED_BY_CLIENT", "blocked"),
        ("something odd", "other"),
        (None, None),
    ],
)
def test_failure_classification(error, expected):
    assert classify_failure(error) == expected


# --- browser state ----------------------------------------------------------


def test_browser_state_records_names_never_values():
    state = browser_state_names(
        cookies=[{"name": "session", "value": "SUPER-SECRET-VALUE", "domain": "x.test", "path": "/"}],
        local_storage_keys=["theme", "token"],
        session_storage_keys=["nonce"],
    )
    blob = repr(state)
    assert "SUPER-SECRET-VALUE" not in blob
    assert "value" not in {k for c in state["cookie_names"] for k in c}
    assert state["cookie_names"][0]["name"] == "session"
    assert state["local_storage_keys"] == ["theme", "token"]


# --- secret detection -------------------------------------------------------


@pytest.mark.parametrize(
    "text,rule",
    [
        (f"Authorization: {FAKE_BEARER}", "authorization_header"),
        (FAKE_BEARER, "bearer_token"),
        ("Set-Cookie: session=abc123; Path=/", "set_cookie_header"),
        (FAKE_SK_KEY, "openai_style_key"),
        ("AKIA" + "A" * 16, "aws_access_key"),
        ("ghp_" + "b" * 30, "github_token"),
        (FAKE_JWT, "jwt"),
        ("-----BEGIN RSA PRIVATE KEY-----", "private_key_block"),
        ("api_key = " + "c" * 20, "api_key_assignment"),
        ("/Users/someone/corpus", "absolute_user_path"),
        ("/Volumes/MyDisk/corpus", "absolute_volume_path"),
    ],
)
def test_secret_rules_fire(text, rule):
    assert rule in {f.rule for f in scan_text_for_secrets(text)}


def test_clean_text_produces_no_findings():
    clean = "service_id,domain,capture_started_utc\nfoo_1a2b3c4d,example.com,2026-01-01T00:00:00Z\n"
    assert scan_text_for_secrets(clean) == []


def test_placeholder_paths_do_not_trip_the_scanner():
    """Normalized output must be clean, or the gate would cry wolf forever."""
    assert scan_text_for_secrets("/Users/$USER/x and /Volumes/$ARCHIVE_VOLUME/y") == []


# --- public row construction -------------------------------------------------


@pytest.fixture
def dirty_capture():
    """A capture whose metadata is full of things that must not be published."""
    return {
        "capture_id": "20260101T000000Z_svc_00000000_abcdef123456",
        "service_id": "svc_00000000",
        "host": "example.com",
        "started_utc": "2026-01-01T00:00:00Z",
        "capture_reason": "manual",
        "status": "completed",
        "site_condition": "ok",
        "seed_count": 3,
        "page_count": 3,
        "wacz": {"size_bytes": 1234, "sha256": "a" * 64, "relative_path": "raw/.../c1.wacz"},
        "capture_directory_digest": "sha256:" + "b" * 64,
        "tools": {"browsertrix": {"tag": "1.12.4", "digest": "sha256:" + "c" * 64}, "singlefile": {"version": "2.0.83"}},
        "effective_config_hash": "d" * 64,
        "code_commit_sha": "e" * 40,
        "prior_monitor_state": {
            "timestamp": "2026-01-01T00:00:00Z",
            "online_status": "ONLINE",
            "final_url": "https://example.com/landing?invite=SECRET123&token=" + "t" * 30,
            "page_title": "Example",
            "html_hash": "abc123",
        },
        "validation": {"status": "valid", "failed_checks": []},
        # Fields that exist in capture.json and must NOT reach the public row:
        "rendered": {"pages": [{"dom_path": "final_dom.html"}]},
        "environment": {"free_bytes_before": 1, "absolute_path": "/Users/someone/corpus"},
        "singlefile": [{"output": "singlefile.html"}],
        "errors": ["Authorization: " + FAKE_BEARER],
    }


def test_public_row_uses_only_declared_columns(dirty_capture):
    row = capture_public_row(dirty_capture, corpus_relpath="corpus/svc/captures/cid")
    assert set(row) == set(CAPTURE_COLUMNS), "the row schema is an allowlist"


def test_public_row_drops_redirect_query_parameters(dirty_capture):
    row = capture_public_row(dirty_capture, corpus_relpath="corpus/svc/captures/cid")
    assert "SECRET123" not in row["source_final_url"]
    assert "t" * 30 not in row["source_final_url"]


def test_public_row_carries_no_raw_content(dirty_capture):
    row = capture_public_row(dirty_capture, corpus_relpath="corpus/svc/captures/cid")
    blob = "\n".join(f"{k}={v}" for k, v in row.items())
    assert FAKE_BEARER not in blob
    assert "final_dom.html" not in blob
    assert "singlefile.html" not in blob
    assert "/Users/" not in blob
    assert scan_text_for_secrets(blob) == []


def test_public_row_relpath_is_relative(dirty_capture):
    row = capture_public_row(dirty_capture, corpus_relpath="corpus/svc/captures/cid")
    assert not row["corpus_relpath"].startswith("/")
    assert ".." not in row["corpus_relpath"]


def test_public_row_keeps_the_evidence_fields(dirty_capture):
    row = capture_public_row(dirty_capture, corpus_relpath="corpus/svc/captures/cid")
    assert row["wacz_sha256"] == "a" * 64
    assert row["capture_directory_digest"].startswith("sha256:")
    assert row["browsertrix_version"] == "1.12.4"
    assert row["validation_status"] == "valid"


def test_tombstone_row_is_clean():
    row = tombstone_public_row(
        {
            "service_id": "svc_00000000",
            "host": "example.com",
            "recorded_at_utc": "2026-01-01T00:00:00Z",
            "prior_state": "ONLINE",
            "new_state": "dns_failure_persistent",
            "confidence": "probable",
            "is_provisional": False,
            "evidence": {
                "consecutive_observations": 4,
                "span_hours": 96.0,
                "source": {"file": "results/monitor_results.csv"},
            },
            "notes": ["path was /Users/someone/x"],
        }
    )
    blob = "\n".join(f"{k}={v}" for k, v in row.items())
    assert "/Users/someone" not in blob
    assert scan_text_for_secrets(blob) == []


def test_manifest_summary_publishes_no_file_contents():
    manifest = {
        "capture_id": "cid",
        "service_id": "svc",
        "algorithm": "sha256",
        "file_count": 2,
        "total_bytes": 100,
        "capture_directory_digest": "sha256:" + "f" * 64,
        "files": [
            {"path": "raw/browsertrix/collections/c1/c1.wacz", "size_bytes": 90, "sha256": "a" * 64, "role": "wacz"},
            {"path": "raw/rendered/final_dom.html", "size_bytes": 10, "sha256": "b" * 64, "role": "rendered_dom"},
        ],
    }
    summary = public_manifest_summary(manifest, {"host": "example.com", "started_utc": "2026-01-01T00:00:00Z"})
    blob = repr(summary)
    assert "<html" not in blob
    assert summary["files_by_role"]["wacz"]["count"] == 1
    assert summary["wacz"][0]["sha256"] == "a" * 64


# --- directory-level gate ----------------------------------------------------


def test_scan_flags_forbidden_extensions(tmp_path):
    (tmp_path / "leak.wacz").write_bytes(b"PK\x03\x04")
    (tmp_path / "page.html").write_text("<html></html>", encoding="utf-8")
    report = scan_public_export(tmp_path)
    assert not report["ok"]
    assert len(report["forbidden_files"]) == 2


def test_scan_flags_symlinks(tmp_path):
    target = tmp_path / "outside.txt"
    target.write_text("x", encoding="utf-8")
    link_dir = tmp_path / "public"
    link_dir.mkdir()
    (link_dir / "link.csv").symlink_to(target)
    report = scan_public_export(link_dir)
    assert not report["ok"]
    assert any("symlink" in f for f in report["forbidden_files"])


def test_scan_flags_secret_in_csv(tmp_path):
    (tmp_path / "captures.csv").write_text(f"a,b\n1,{FAKE_SK_KEY}\n", encoding="utf-8")
    report = scan_public_export(tmp_path)
    assert not report["ok"]
    assert any(f["rule"] == "openai_style_key" for f in report["findings"])


def test_scan_passes_on_clean_export(tmp_path):
    (tmp_path / "captures.csv").write_text("service_id,domain\nsvc_1,example.com\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# notes\n", encoding="utf-8")
    report = scan_public_export(tmp_path)
    assert report["ok"], report


def test_forbidden_extension_list_covers_raw_artifacts():
    for ext in (".wacz", ".warc", ".cdxj", ".html", ".png", ".har"):
        assert ext in FORBIDDEN_PUBLIC_EXTENSIONS


def test_unknown_timing_is_null_not_negative():
    """Playwright reports -1 when a phase never completed; -1 is not a duration."""
    assert sanitized_network_record(timestamp_utc="t", url="https://x.test/", timing_ms=-1)["timing_ms"] is None
    assert sanitized_network_record(timestamp_utc="t", url="https://x.test/", timing_ms=12.5)["timing_ms"] == 12.5
    assert sanitized_network_record(timestamp_utc="t", url="https://x.test/", timing_ms=None)["timing_ms"] is None
