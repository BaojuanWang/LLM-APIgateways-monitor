"""Append-only / immutability tests.

The corpus's evidential value rests on one rule: nothing that was written is
ever rewritten. Retries create new capture ids; failed, blocked, and dead-site
captures are kept; tombstones and discovery evidence accumulate rather than
being replaced.
"""

from __future__ import annotations

import json

import pytest

from archivelib.capture import collection_name_for, make_capture_id
from archivelib.errors import OverwriteError
from archivelib.manifest import generate_manifest
from archivelib.paths import create_capture_dir
from archivelib.tombstone import build_tombstone, evaluate_service, write_tombstone


# --- capture ids ------------------------------------------------------------


def test_capture_id_shape():
    cid = make_capture_id(
        service_id="example-com_1a2b3c4d",
        seeds=["https://example.com/"],
        effective_config_hash="a" * 64,
        started_utc="20260101T000000Z",
    )
    assert cid.startswith("20260101T000000Z_example-com_1a2b3c4d_")
    assert len(cid.rsplit("_", 1)[1]) == 12


def test_capture_id_is_deterministic_in_its_inputs():
    kwargs = dict(
        service_id="svc_1a2b3c4d",
        seeds=["https://x.test/", "https://x.test/pricing"],
        effective_config_hash="b" * 64,
        started_utc="20260101T000000Z",
    )
    assert make_capture_id(**kwargs) == make_capture_id(**kwargs)
    # Seed order must not matter; seed content must.
    reordered = {**kwargs, "seeds": list(reversed(kwargs["seeds"]))}
    assert make_capture_id(**reordered) == make_capture_id(**kwargs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("seeds", ["https://x.test/other"]),
        ("effective_config_hash", "c" * 64),
        ("started_utc", "20260101T000001Z"),
        ("service_id", "other_1a2b3c4d"),
    ],
)
def test_capture_id_changes_with_every_input(field, value):
    base = dict(
        service_id="svc_1a2b3c4d",
        seeds=["https://x.test/"],
        effective_config_hash="b" * 64,
        started_utc="20260101T000000Z",
    )
    assert make_capture_id(**{**base, field: value}) != make_capture_id(**base)


def test_retry_produces_a_new_capture_id():
    """A retry is a new observation, never an overwrite of the failed one."""
    base = dict(service_id="svc_1a2b3c4d", seeds=["https://x.test/"], effective_config_hash="b" * 64)
    first = make_capture_id(**base, started_utc="20260101T000000Z")
    retry = make_capture_id(**base, started_utc="20260101T010000Z")
    assert first != retry


def test_collection_name_is_docker_safe():
    name = collection_name_for("20260101T000000Z_svc_1a2b3c4d_abcdef123456")
    assert name.islower()
    assert all(ch.isalnum() or ch == "-" for ch in name)


# --- directory-level immutability -------------------------------------------


def test_capture_directory_creation_fails_closed(archive_root):
    args = (archive_root, "svc_1a2b3c4d", "20260101T000000Z_svc_1a2b3c4d_abcdef123456")
    create_capture_dir(*args)
    with pytest.raises(OverwriteError):
        create_capture_dir(*args)


def test_preexisting_directory_blocks_creation(archive_root):
    """Even a directory this code did not create must not be adopted."""
    target = archive_root.corpus_dir / "svc_1a2b3c4d" / "captures" / "20260101T000000Z_svc_1a2b3c4d_abcdef123456"
    target.mkdir(parents=True)
    (target / "stray.txt").write_text("pre-existing", encoding="utf-8")
    with pytest.raises(OverwriteError):
        create_capture_dir(archive_root, "svc_1a2b3c4d", "20260101T000000Z_svc_1a2b3c4d_abcdef123456")
    assert (target / "stray.txt").exists(), "existing content must be left untouched"


def test_two_captures_of_one_service_coexist(archive_root):
    first = create_capture_dir(archive_root, "svc_1a2b3c4d", "20260101T000000Z_svc_1a2b3c4d_aaaaaaaaaaaa")
    second = create_capture_dir(archive_root, "svc_1a2b3c4d", "20260102T000000Z_svc_1a2b3c4d_bbbbbbbbbbbb")
    assert first.exists() and second.exists() and first != second


def test_failed_capture_is_kept_and_manifested(archive_root):
    """A crawl that produced no WACZ is still evidence and still gets hashed."""
    capture = create_capture_dir(archive_root, "svc_1a2b3c4d", "20260101T000000Z_svc_1a2b3c4d_abcdef123456")
    (capture / "capture.json").write_text(
        json.dumps({"capture_id": "cid", "status": "failed_no_wacz", "site_condition": "unavailable"}),
        encoding="utf-8",
    )
    (capture / "validation" / "browsertrix_exit.json").write_text(
        json.dumps({"exit_code": 1, "wacz_present": False}), encoding="utf-8"
    )
    manifest = generate_manifest(capture, capture_id="cid", service_id="svc_1a2b3c4d")
    assert manifest["file_count"] == 2
    assert manifest["capture_directory_digest"].startswith("sha256:")


def test_screenshot_is_never_replaced(archive_root):
    capture = create_capture_dir(archive_root, "svc_1a2b3c4d", "20260101T000000Z_svc_1a2b3c4d_abcdef123456")
    shot = capture / "raw" / "rendered" / "screenshots" / "viewport.png"
    shot.write_bytes(b"\x89PNG original")
    generate_manifest(capture, capture_id="cid", service_id="svc_1a2b3c4d")

    from archivelib.manifest import verify_manifest

    shot.write_bytes(b"\x89PNG replaced")
    report = verify_manifest(capture)
    assert not report["ok"], "replacing a screenshot must be detectable"
    assert any(m["path"].endswith("viewport.png") for m in report["hash_mismatches"])


# --- tombstone immutability --------------------------------------------------


def _tombstone(recorded_at: str) -> dict:
    return {
        "schema": "tombstone.schema.json",
        "service_id": "svc_1a2b3c4d",
        "host": "example.com",
        "recorded_at_utc": recorded_at,
        "prior_state": "ONLINE",
        "new_state": "dns_failure_persistent",
        "confidence": "probable",
        "evidence": {"consecutive_observations": 4, "span_hours": 96},
        "final_capture_attempted": True,
        "final_capture_result": "failed_no_wacz",
        "notes": [],
        "uncertainty": "single vantage point",
    }


def test_tombstone_write_is_immutable(archive_root):
    tombstones = archive_root.corpus_dir / "svc_1a2b3c4d" / "tombstones"
    write_tombstone(tombstones, _tombstone("2026-01-01T00:00:00Z"))
    with pytest.raises(OverwriteError):
        write_tombstone(tombstones, _tombstone("2026-01-01T00:00:00Z"))


def test_later_tombstone_is_added_not_merged(archive_root):
    tombstones = archive_root.corpus_dir / "svc_1a2b3c4d" / "tombstones"
    write_tombstone(tombstones, _tombstone("2026-01-01T00:00:00Z"))
    write_tombstone(tombstones, _tombstone("2026-02-01T00:00:00Z"))
    assert len(list(tombstones.glob("*.json"))) == 2


def test_discovery_evidence_appends(archive_root, tmp_path):
    """Discovery evidence is a JSONL log; a second capture must not truncate it."""
    evidence = archive_root.corpus_dir / "svc_1a2b3c4d" / "discovery" / "discovery_evidence.jsonl"
    evidence.parent.mkdir(parents=True)
    for i in range(3):
        with open(evidence, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"capture_id": f"cid{i}"}) + "\n")
    lines = evidence.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["capture_id"] == "cid0"


def test_build_tombstone_always_states_uncertainty():
    from archivelib.identity import MonitorObservation

    observations = [
        MonitorObservation("2026-05-01T00:00:00Z", "x.test", "X", "hvoy", "ONLINE", "200", "https://x.test/", "X", "h1", "", ""),
        *[
            MonitorObservation(f"2026-05-{d:02d}T00:00:00Z", "x.test", "X", "hvoy", "DNS_FAIL", "", "", "", "", "", "dns")
            for d in (5, 7, 9, 11, 13, 15, 17)
        ],
    ]
    from archivelib.config import DEFAULT_CONFIG

    evidence = evaluate_service(observations, cfg=DEFAULT_CONFIG)
    tombstone = build_tombstone(
        evidence=evidence,
        monitor_source={"file": "results/monitor_results.csv"},
        last_successful_capture_id=None,
        last_successful_wacz_sha256=None,
        final_capture_attempted=False,
        final_capture_result="not_attempted",
    )
    assert tombstone["uncertainty"]
    assert "permanently" in tombstone["uncertainty"]
    assert tombstone["confidence"] in ("provisional", "probable", "high")


# --- crawler scratch pruning -------------------------------------------------


def test_prune_removes_only_the_browser_profile(archive_root):
    """Pruning happens before the manifest seals the capture, and it must never
    touch anything that is actually evidence."""
    from archivelib.capture import prune_crawler_scratch

    capture = create_capture_dir(archive_root, "svc_1a2b3c4d", "20260101T000000Z_svc_1a2b3c4d_abcdef123456")
    collection = capture / "raw" / "browsertrix" / "collections" / "c1"
    for keep in ("archive", "indexes", "logs", "pages", "crawlIds"):
        (collection / keep).mkdir(parents=True)
        (collection / keep / "payload.bin").write_bytes(b"evidence")
    profile = collection / "profile" / "Default"
    profile.mkdir(parents=True)
    (profile / "Cookies").write_bytes(b"SQLite format 3\x00")
    (collection / "c1.wacz").write_bytes(b"PK\x03\x04")

    removed = prune_crawler_scratch(collection, capture)

    assert not (collection / "profile").exists()
    assert [r["path"] for r in removed] == ["raw/browsertrix/collections/c1/profile"]
    assert removed[0]["file_count"] == 1
    assert "browser state" in removed[0]["reason"]
    for keep in ("archive", "indexes", "logs", "pages", "crawlIds"):
        assert (collection / keep / "payload.bin").read_bytes() == b"evidence"
    assert (collection / "c1.wacz").exists()


def test_prune_refuses_to_follow_a_symlink_out_of_the_capture(archive_root, tmp_path):
    from archivelib.capture import prune_crawler_scratch

    outside = tmp_path / "precious"
    outside.mkdir()
    (outside / "keep.txt").write_text("must survive", encoding="utf-8")

    capture = create_capture_dir(archive_root, "svc_2a2b3c4d", "20260101T000000Z_svc_2a2b3c4d_abcdef123456")
    collection = capture / "raw" / "browsertrix" / "collections" / "c1"
    collection.mkdir(parents=True)
    (collection / "profile").symlink_to(outside)

    removed = prune_crawler_scratch(collection, capture)
    assert removed == []
    assert (outside / "keep.txt").exists(), "a symlinked profile must never be followed and deleted"


def test_prune_is_a_noop_when_there_is_nothing_to_prune(archive_root):
    from archivelib.capture import prune_crawler_scratch

    capture = create_capture_dir(archive_root, "svc_3a2b3c4d", "20260101T000000Z_svc_3a2b3c4d_abcdef123456")
    collection = capture / "raw" / "browsertrix" / "collections" / "c1"
    collection.mkdir(parents=True)
    assert prune_crawler_scratch(collection, capture) == []
    assert prune_crawler_scratch(None, capture) == []
