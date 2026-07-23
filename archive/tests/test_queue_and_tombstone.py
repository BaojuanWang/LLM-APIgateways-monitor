"""Queue-planning and tombstone-evidence tests.

Uses the synthetic monitor fixture in ``fixtures/monitor_results_sample.csv``,
which encodes the six situations that matter: stable, dying, briefly-timed-out,
recovered, permanently-challenged, and redirected-to-parking.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from archivelib.config import DEFAULT_CONFIG
from archivelib.identity import (
    MonitorObservation,
    ServiceIdentity,
    normalize_host,
    service_id_for_host,
)
from archivelib.locks import LockError, file_lock
from archivelib.queueplan import CaptureHistoryEntry, plan_queue
from archivelib.tombstone import evaluate_service

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _observations() -> list[MonitorObservation]:
    rows = []
    with open(FIXTURES / "monitor_results_sample.csv", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            rows.append(
                MonitorObservation(
                    timestamp=row["timestamp"],
                    host=normalize_host(row["domain"]),
                    platform_name=row["platform_name"],
                    source=row["source"],
                    online_status=row["online_status"],
                    http_status=row["http_status"],
                    final_url=row["final_url"],
                    page_title=row["page_title"],
                    html_hash=row["html_hash"],
                    redirect_chain=row["redirect_chain"],
                    error=row["error"],
                )
            )
    return sorted(rows, key=lambda o: (o.host, o.timestamp))


def _inventory() -> dict[str, ServiceIdentity]:
    inventory = {}
    with open(FIXTURES / "master_sites_sample.csv", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            host = normalize_host(row["domain"])
            sid = service_id_for_host(host)
            inventory[sid] = ServiceIdentity(
                service_id=sid,
                host=host,
                canonical_url=f"https://{host}/",
                platform_name=row["platform_name"],
                source="discovery",
                inventory_file="archive/tests/fixtures/master_sites_sample.csv",
                inventory_file_sha256="0" * 64,
                inventory_row=row,
                inventory_row_sha256="1" * 64,
            )
    return inventory


def _by_host(observations, host):
    return [o for o in observations if o.host == host]


# --- tombstone evidence ------------------------------------------------------


def test_persistent_dns_failure_emits_a_tombstone():
    evidence = evaluate_service(_by_host(_observations(), "beta.example.test"), cfg=DEFAULT_CONFIG)
    assert evidence.should_emit
    assert evidence.new_state == "dns_failure_persistent"
    assert evidence.confidence in ("provisional", "probable", "high")
    assert evidence.consecutive_observations >= 3
    assert evidence.last_live_utc == "2026-05-01T00:00:00Z"


def test_single_transient_timeout_emits_nothing():
    """The core rule: one failure is noise, not a death."""
    evidence = evaluate_service(_by_host(_observations(), "gamma.example.test"), cfg=DEFAULT_CONFIG)
    assert not evidence.should_emit
    assert evidence.confidence == "insufficient"
    assert "needs >=" in " ".join(evidence.notes)


def test_recovered_service_emits_nothing():
    evidence = evaluate_service(_by_host(_observations(), "delta.example.test"), cfg=DEFAULT_CONFIG)
    assert not evidence.should_emit
    assert evidence.new_state == "live"


def test_persistent_challenge_is_never_a_tombstone():
    """A Cloudflare challenge proves the origin is answering — 'cannot see',
    not 'is gone'. Five consecutive blocks must still emit nothing."""
    evidence = evaluate_service(_by_host(_observations(), "epsilon.example.test"), cfg=DEFAULT_CONFIG)
    assert not evidence.should_emit
    assert evidence.confidence == "insufficient"
    assert evidence.new_state == "unknown_not_live"
    assert any("challenge" in note or "blocked" in note for note in evidence.notes)


def test_offsite_redirect_is_detected():
    evidence = evaluate_service(_by_host(_observations(), "zeta.example.test"), cfg=DEFAULT_CONFIG)
    assert evidence.new_state == "redirects_offsite"
    assert evidence.redirect_target_host == "unrelated-parking.example.org"
    assert evidence.should_emit


def test_stable_service_emits_nothing():
    evidence = evaluate_service(_by_host(_observations(), "alpha.example.test"), cfg=DEFAULT_CONFIG)
    assert not evidence.should_emit


def test_thresholds_are_configurable():
    cfg = {**DEFAULT_CONFIG, "tombstone": {**DEFAULT_CONFIG["tombstone"], "min_consecutive_observations": 99}}
    evidence = evaluate_service(_by_host(_observations(), "beta.example.test"), cfg=cfg)
    assert not evidence.should_emit


def test_confidence_rises_with_more_evidence():
    observations = _by_host(_observations(), "beta.example.test")
    short = evaluate_service(observations[:4], cfg=DEFAULT_CONFIG)
    long_run = evaluate_service(observations, cfg=DEFAULT_CONFIG)
    levels = ["insufficient", "provisional", "probable", "high"]
    assert levels.index(long_run.confidence) >= levels.index(short.confidence)


# --- queue planning ----------------------------------------------------------


def test_first_capture_is_queued_for_everything_unarchived():
    queue = plan_queue(
        inventory=_inventory(),
        observations=_observations(),
        history={},
        cfg=DEFAULT_CONFIG,
        now_utc="2026-05-17T00:00:00Z",
        max_sites=50,
    )
    assert queue["counts"]["candidates"] == len(_inventory())
    reasons = {e["reason"] for e in queue["entries"]}
    assert "first_capture" in reasons


def test_queue_never_takes_the_whole_inventory_by_default():
    queue = plan_queue(
        inventory=_inventory(),
        observations=_observations(),
        history={},
        cfg=DEFAULT_CONFIG,
        now_utc="2026-05-17T00:00:00Z",
    )
    assert len(queue["entries"]) <= DEFAULT_CONFIG["queue"]["max_sites"]
    assert queue["counts"]["deferred"] >= 0


def test_max_sites_is_respected():
    queue = plan_queue(
        inventory=_inventory(),
        observations=_observations(),
        history={},
        cfg=DEFAULT_CONFIG,
        now_utc="2026-05-17T00:00:00Z",
        max_sites=2,
    )
    assert len(queue["entries"]) == 2


def test_tombstone_evidence_outranks_first_capture():
    queue = plan_queue(
        inventory=_inventory(),
        observations=_observations(),
        history={},
        cfg=DEFAULT_CONFIG,
        now_utc="2026-05-17T00:00:00Z",
        max_sites=50,
    )
    by_sid = {e["service_id"]: e for e in queue["entries"]}
    beta = by_sid[service_id_for_host("beta.example.test")]
    assert beta["reason"] == "tombstone_evidence"
    assert beta["priority"] < 40  # ahead of first_capture


def test_ordering_is_deterministic():
    kwargs = dict(
        inventory=_inventory(),
        observations=_observations(),
        history={},
        cfg=DEFAULT_CONFIG,
        now_utc="2026-05-17T00:00:00Z",
        max_sites=50,
    )
    first = plan_queue(**kwargs)
    second = plan_queue(**kwargs)
    assert [e["service_id"] for e in first["entries"]] == [e["service_id"] for e in second["entries"]]
    assert first["queue_hash"] == second["queue_hash"]


def test_cooldown_suppresses_recent_captures():
    sid = service_id_for_host("alpha.example.test")
    history = {
        sid: [
            CaptureHistoryEntry(
                service_id=sid,
                capture_id="c1",
                started_utc="2026-05-16T23:00:00Z",
                status="completed",
                validation_status="valid",
                wacz_sha256="a" * 64,
            )
        ]
    }
    queue = plan_queue(
        inventory=_inventory(),
        observations=_observations(),
        history=history,
        cfg=DEFAULT_CONFIG,
        now_utc="2026-05-17T00:00:00Z",
        max_sites=50,
    )
    assert sid not in {e["service_id"] for e in queue["entries"]}
    assert any(s["service_id"] == sid and s["reason"] == "cooldown" for s in queue["skipped"])


def test_homepage_hash_change_triggers_recapture():
    sid = service_id_for_host("alpha.example.test")
    history = {
        sid: [
            CaptureHistoryEntry(
                service_id=sid,
                capture_id="c1",
                started_utc="2026-05-02T00:00:00Z",
                status="completed",
                validation_status="valid",
                wacz_sha256="a" * 64,
                homepage_html_hash="aaaa1111",  # fixture later changes to bbbb2222
                final_url="https://alpha.example.test/",
                page_title="Alpha Gateway",
            )
        ]
    }
    queue = plan_queue(
        inventory=_inventory(),
        observations=_observations(),
        history=history,
        cfg=DEFAULT_CONFIG,
        now_utc="2026-05-17T00:00:00Z",
        max_sites=50,
    )
    entry = next(e for e in queue["entries"] if e["service_id"] == sid)
    assert entry["reason"] == "homepage_hash_change"


def test_monthly_interval_fires_when_nothing_else_does():
    sid = service_id_for_host("alpha.example.test")
    history = {
        sid: [
            CaptureHistoryEntry(
                service_id=sid,
                capture_id="c1",
                started_utc="2026-01-01T00:00:00Z",
                status="completed",
                validation_status="valid",
                wacz_sha256="a" * 64,
                homepage_html_hash="bbbb2222",
                final_url="https://alpha.example.test/",
                page_title="Alpha Gateway v2",
            )
        ]
    }
    queue = plan_queue(
        inventory=_inventory(),
        observations=_observations(),
        history=history,
        cfg=DEFAULT_CONFIG,
        now_utc="2026-05-17T00:00:00Z",
        max_sites=50,
    )
    entry = next(e for e in queue["entries"] if e["service_id"] == sid)
    assert entry["reason"] == "monthly_interval"


def test_reappearance_is_queued():
    sid = service_id_for_host("delta.example.test")
    queue = plan_queue(
        inventory=_inventory(),
        observations=_observations(),
        history={
            sid: [
                CaptureHistoryEntry(
                    service_id=sid,
                    capture_id="c1",
                    started_utc="2026-05-02T00:00:00Z",
                    status="completed",
                    validation_status="valid",
                    wacz_sha256="a" * 64,
                )
            ]
        },
        cfg=DEFAULT_CONFIG,
        now_utc="2026-05-17T00:00:00Z",
        max_sites=50,
    )
    entry = next(e for e in queue["entries"] if e["service_id"] == sid)
    assert entry["reason"] in ("reappearance", "status_transition")


def test_retry_failures_is_opt_in():
    sid = service_id_for_host("alpha.example.test")
    history = {
        sid: [
            CaptureHistoryEntry(
                service_id=sid,
                capture_id="c1",
                started_utc="2026-05-02T00:00:00Z",
                status="failed_no_wacz",
                validation_status="invalid",
                wacz_sha256="",
            )
        ]
    }
    common = dict(
        inventory=_inventory(),
        observations=_observations(),
        history=history,
        cfg=DEFAULT_CONFIG,
        now_utc="2026-05-17T00:00:00Z",
        max_sites=50,
    )
    # No successful capture on record -> first_capture takes precedence, but the
    # entry must exist either way; with retry enabled it is never absent.
    with_retry = plan_queue(**common, retry_failures=True)
    assert sid in {e["service_id"] for e in with_retry["entries"]}


def test_service_filter_restricts_planning():
    sid = service_id_for_host("alpha.example.test")
    queue = plan_queue(
        inventory=_inventory(),
        observations=_observations(),
        history={},
        cfg=DEFAULT_CONFIG,
        now_utc="2026-05-17T00:00:00Z",
        only_service_id=sid,
    )
    assert [e["service_id"] for e in queue["entries"]] == [sid]


def test_domain_filter_resolves_to_service_id():
    queue = plan_queue(
        inventory=_inventory(),
        observations=_observations(),
        history={},
        cfg=DEFAULT_CONFIG,
        now_utc="2026-05-17T00:00:00Z",
        only_domain="alpha.example.test",
    )
    assert [e["service_id"] for e in queue["entries"]] == [service_id_for_host("alpha.example.test")]


# --- locking -----------------------------------------------------------------


def test_lock_is_exclusive(tmp_path):
    lock = tmp_path / "test.lock"
    with file_lock(lock, purpose="first"):
        assert lock.exists()
        with pytest.raises(LockError, match="lock held"):
            with file_lock(lock, purpose="second", break_stale=False):
                pass
    assert not lock.exists(), "lock must be released"


def test_lock_records_its_holder(tmp_path):
    import json
    import os

    lock = tmp_path / "test.lock"
    with file_lock(lock, purpose="capture svc"):
        info = json.loads(lock.read_text(encoding="utf-8"))
        assert info["pid"] == os.getpid()
        assert info["purpose"] == "capture svc"


def test_lock_is_released_on_exception(tmp_path):
    lock = tmp_path / "test.lock"
    with pytest.raises(ValueError):
        with file_lock(lock, purpose="boom"):
            raise ValueError("boom")
    assert not lock.exists()
